"""Schema, validation, and emission tests for Foundry agent primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

import apm_cli.cli  # noqa: F401  -- import order: primitives need the package graph loaded
from apm_cli.integration.foundry_agents import (
    BUILTIN_TOOL_NAMES,
    FoundryAgentError,
    build_foundry_services,
    parse_foundry_agent,
)
from apm_cli.integration.foundry_azure_yaml import merge_foundry_services
from apm_cli.primitives.parser import parse_primitive_file

FULL_AGENT = """---
name: support-assistant
description: Answers support questions
foundry:
  model: ${AZURE_AI_MODEL_DEPLOYMENT=small}
  kind: prompt
  harness: microsoft_copilot_preview
  skills: [kb-lookup, kb-lookup]
  builtin_tools:
    default_enabled: false
    enabled: [subagents, filesystem_read]
  mcp:
    - connection: my-search-connection
      server_label: search
      server_url: https://search.example.com/mcp/
      require_approval: always
      allowed_tools: [search_documents, search_documents]
---
You are a support assistant.

Use the kb-lookup skill.   \n\n
"""

GOLDEN = """name: proj
services:
  kb-lookup:
    host: azure.ai.skill
    archive: ./.foundry/skills/kb-lookup
  support-assistant:
    host: azure.ai.agent
    project: .foundry
    kind: prompt
    harness:
      type: microsoft_copilot_preview
    model: ${AZURE_AI_MODEL_DEPLOYMENT=small}
    instructions: |
      You are a support assistant.

      Use the kb-lookup skill.
    skills:
      - kb-lookup
    uses:
      - kb-lookup
    tools:
      - type: microsoft_copilot_toolset_preview
        defaultConfig:
          enabled: false
        configs:
          - name: filesystem_read
            enabled: true
          - name: subagents
            enabled: true
      - type: mcp
        server_label: search
        server_url: https://search.example.com/mcp/
        project_connection_id: my-search-connection
        require_approval: always
        allowed_tools:
          - search_documents
"""


def _write(tmp_path: Path, text: str, stem: str = "support-assistant") -> Path:
    agents = tmp_path / ".apm" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / f"{stem}.agent.md"
    path.write_text(text, encoding="utf-8")
    return path


def _parse(tmp_path: Path, text: str, stem: str = "support-assistant"):
    return parse_foundry_agent(parse_primitive_file(_write(tmp_path, text, stem)))


def _agent(foundry_block: str, body: str = "Help.\n", header: str = "") -> str:
    return f"---\ndescription: d\n{header}foundry:\n{foundry_block}---\n{body}"


def test_full_example_parses(tmp_path: Path) -> None:
    spec = _parse(tmp_path, FULL_AGENT)
    assert spec.name == "support-assistant"
    assert spec.skills == ("kb-lookup",)
    assert spec.builtin_tools == {"filesystem_read": True, "subagents": True}
    assert spec.mcp[0].allowed_tools == ("search_documents",)
    assert spec.instructions.endswith("skill.\n")


def test_defaults(tmp_path: Path) -> None:
    spec = _parse(tmp_path, _agent("  model: small\n"), stem="kb-helper")
    assert spec.name == "kb-helper"
    assert (spec.kind, spec.harness, spec.skills, spec.mcp) == (
        "prompt",
        "microsoft_copilot_preview",
        (),
        (),
    )
    assert spec.builtin_tools is None
    service = build_foundry_services([spec], set())["kb-helper"]
    assert list(service) == ["host", "project", "kind", "harness", "model", "instructions"]


def test_agent_without_foundry_mapping_is_skipped(tmp_path: Path) -> None:
    assert _parse(tmp_path, "---\ndescription: d\n---\nHi.\n") is None


def test_builtin_names_constant() -> None:
    assert (
        frozenset({"filesystem_read", "filesystem_write", "shell", "subagents", "web"})
        == BUILTIN_TOOL_NAMES
    )


_MCP = (
    "  model: small\n  mcp:\n    - connection: my-search-connection\n"
    "      server_label: search\n      server_url: {url}\n"
)


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (_agent("  kind: prompt\n"), "foundry.model' is required"),
        (_agent("  model: small\n  kind: hosted\n"), "foundry.kind"),
        (_agent("  model: small\n  harness: other\n"), "foundry.harness"),
        (_agent("  model: small\n  extra: 1\n"), "unknown key"),
        (_agent("  model: small\n  builtin_tools:\n    bogus: 1\n"), "unknown key"),
        (_agent("  model: small\n  api_key: abc\n"), "credential"),
        (_agent(_MCP.format(url="https://x.example") + "      Token: abc\n"), "credential"),
        (_agent(_MCP.format(url="https://x.example") + "      headers: {}\n"), "credential"),
        (_agent(_MCP.format(url="http://x.example")), "https://"),
        (
            _agent(
                _MCP.format(url="https://x.example")
                + "    - connection: c\n      server_label: search\n"
                "      server_url: https://y.example\n"
            ),
            "duplicate MCP server_label",
        ),
        (
            _agent(
                "  model: small\n  builtin_tools:\n    enabled: [shell]\n    disabled: [shell]\n"
            ),
            "both 'enabled' and 'disabled'",
        ),
        (_agent("  model: small\n  builtin_tools:\n    enabled: [teleport]\n"), "unknown built-in"),
        (_agent("  model: small\n", header="name: Bad_Name\n"), "not a valid azure.yaml service"),
        (_agent("  model: small\n", body="   \n"), "body is empty"),
    ],
)
def test_validation_errors_name_the_file(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(FoundryAgentError, match=match) as info:
        _parse(tmp_path, text)
    assert "support-assistant.agent.md" in str(info.value)


def test_missing_skill_names_agent_and_skill(tmp_path: Path) -> None:
    spec = _parse(tmp_path, _agent("  model: small\n  skills: [kb-lookup]\n"))
    with pytest.raises(FoundryAgentError, match="devDependencies") as info:
        build_foundry_services([spec], set())
    assert "'support-assistant'" in str(info.value)
    assert "'kb-lookup'" in str(info.value)


def test_golden_emission(tmp_path: Path) -> None:
    spec = _parse(tmp_path, FULL_AGENT)
    services = build_foundry_services([spec], {"kb-lookup"})
    assert merge_foundry_services(tmp_path, "proj", services) is True
    assert (tmp_path / "azure.yaml").read_text(encoding="utf-8") == GOLDEN
    assert (tmp_path / ".foundry" / "apm-services.json").read_text(encoding="utf-8") == (
        '{\n  "services": [\n    "kb-lookup",\n    "support-assistant"\n  ]\n}\n'
    )
    assert merge_foundry_services(tmp_path, "proj", services) is False
    assert not (tmp_path / ".foundry" / "agents").exists()
