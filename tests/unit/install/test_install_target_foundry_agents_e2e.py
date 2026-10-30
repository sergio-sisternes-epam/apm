"""CliRunner tests for Foundry agent emission into ``azure.yaml``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from apm_cli.cli import cli

_ENV = {"APM_E2E_TESTS": "1"}

_LOCAL_AGENT = """---
name: support-assistant
description: Answers support questions
foundry:
  model: ${AZURE_AI_MODEL_DEPLOYMENT=small}
  skills: [kb-lookup, local-notes]
  builtin_tools:
    enabled: [subagents, filesystem_read]
  mcp:
    - connection: my-search-connection
      server_label: search
      server_url: https://search.example.com/mcp/
      allowed_tools: [search_documents]
---
You are a support assistant.
"""


def _skill(root: Path, name: str) -> None:
    skill_dir = root / ".apm" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill\n---\nBody\n", encoding="ascii"
    )


def _agent(root: Path, name: str, text: str) -> None:
    agents_dir = root / ".apm" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.agent.md").write_text(text, encoding="ascii")


def _simple_agent(skill: str) -> str:
    return f"---\ndescription: d\nfoundry:\n  model: small\n  skills: [{skill}]\n---\nHelp.\n"


def _package(tmp_path: Path, name: str, skill: str, agent: str) -> None:
    pkg = tmp_path / name
    _skill(pkg, skill)
    _agent(pkg, agent, _simple_agent(skill))
    (pkg / "apm.yml").write_text(f"name: {name}\nversion: 1.0.0\n", encoding="ascii")


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    apm_dir = home / ".apm"
    apm_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    import apm_cli.config as conf

    monkeypatch.setattr(conf, "CONFIG_DIR", str(apm_dir))
    monkeypatch.setattr(conf, "CONFIG_FILE", str(apm_dir / "config.json"))
    monkeypatch.setattr(conf, "_config_cache", None)

    _package(tmp_path, "prodpkg", "kb-lookup", "catalog-agent")
    _package(tmp_path, "devpkg", "dev-only-skill", "dev-only-agent")

    proj = tmp_path / "proj"
    _skill(proj, "local-notes")
    _agent(proj, "support-assistant", _LOCAL_AGENT)
    _agent(proj, "plain-helper", "---\ndescription: not for foundry\n---\nHi.\n")
    (proj / "apm.yml").write_text(
        "name: proj\nversion: 1.0.0\n"
        "dependencies:\n  apm:\n    - ../prodpkg\n"
        "devDependencies:\n  apm:\n    - ../devpkg\n",
        encoding="ascii",
    )
    yield proj, apm_dir
    monkeypatch.setattr(conf, "_config_cache", None)


def _enable(apm_dir: Path) -> None:
    (apm_dir / "config.json").write_text(
        json.dumps({"experimental": {"foundry": True}}), encoding="ascii"
    )


def _install(proj: Path, *args: str):
    cwd = os.getcwd()
    os.chdir(proj)
    try:
        return CliRunner().invoke(cli, ["install", *args], env=_ENV)
    finally:
        os.chdir(cwd)


def _snapshot(proj: Path) -> dict[str, bytes]:
    files = {"azure.yaml": (proj / "azure.yaml").read_bytes()}
    for path in sorted((proj / ".foundry").rglob("*")):
        if path.is_file():
            files[path.relative_to(proj).as_posix()] = path.read_bytes()
    return files


def test_flag_on_emits_local_and_prod_agents_only(project) -> None:
    proj, apm_dir = project
    _enable(apm_dir)
    result = _install(proj, "--target", "foundry")
    assert result.exit_code == 0, result.output

    from apm_cli.utils.yaml_io import load_yaml

    services = load_yaml(proj / "azure.yaml")["services"]
    assert sorted(services) == [
        "catalog-agent",
        "kb-lookup",
        "local-notes",
        "support-assistant",
    ]
    assert services["support-assistant"]["uses"] == ["kb-lookup", "local-notes"]
    assert services["catalog-agent"]["host"] == "azure.ai.agent"
    assert services["kb-lookup"] == {
        "host": "azure.ai.skill",
        "archive": "./.foundry/skills/kb-lookup",
    }
    sidecar = json.loads((proj / ".foundry" / "apm-services.json").read_text())
    assert sidecar == {"services": sorted(services)}

    text = (proj / "azure.yaml").read_text()
    assert "dev-only" not in text
    assert "plain-helper" not in text
    foundry_files = [p.as_posix() for p in (proj / ".foundry").rglob("*")]
    assert not any("dev-only" in f for f in foundry_files)
    assert not (proj / ".foundry" / "agents").exists()
    assert (proj / ".foundry" / "skills" / "kb-lookup" / "SKILL.md").is_file()
    assert (proj / ".foundry" / "skills" / "local-notes" / "SKILL.md").is_file()


def test_second_install_is_byte_identical(project) -> None:
    proj, apm_dir = project
    _enable(apm_dir)
    first = _install(proj, "--target", "foundry")
    assert first.exit_code == 0, first.output
    before = _snapshot(proj)
    second = _install(proj, "--target", "foundry")
    assert second.exit_code == 0, second.output
    assert _snapshot(proj) == before


def test_azure_yaml_is_not_recorded_as_deployed(project) -> None:
    proj, apm_dir = project
    _enable(apm_dir)
    result = _install(proj, "--target", "foundry")
    assert result.exit_code == 0, result.output
    lock_text = (proj / "apm.lock.yaml").read_text()
    assert "azure.yaml" not in lock_text
    assert ".foundry/skills/dev-only-skill" not in lock_text


def test_agent_using_dev_only_skill_fails(project) -> None:
    proj, apm_dir = project
    _enable(apm_dir)
    _agent(proj, "support-assistant", _simple_agent("dev-only-skill"))
    result = _install(proj, "--target", "foundry")
    output = " ".join(result.output.split())
    assert result.exit_code != 0
    assert "dev-only-skill" in output
    assert "devDependencies" in output
    assert not (proj / "azure.yaml").exists()


def test_dev_dependency_reaches_other_targets_but_not_foundry(project) -> None:
    proj, apm_dir = project
    _enable(apm_dir)
    result = _install(proj, "--target", "foundry,claude")
    assert result.exit_code == 0, result.output
    assert (proj / ".claude" / "skills" / "dev-only-skill" / "SKILL.md").is_file()
    assert not (proj / ".foundry" / "skills" / "dev-only-skill").exists()
    assert "dev-only" not in (proj / "azure.yaml").read_text()


def test_flag_off_refuses_and_writes_nothing(project) -> None:
    proj, _ = project
    result = _install(proj, "--target", "foundry")
    assert "apm experimental enable foundry" in " ".join(result.output.split())
    assert not (proj / ".foundry").exists()
    assert not (proj / "azure.yaml").exists()
