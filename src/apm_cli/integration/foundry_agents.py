"""Foundry agent primitives -> azd ``azure.ai.agent`` service entries.

The experimental ``foundry`` target reads ``.agent.md`` primitives that carry a
top-level ``foundry:`` frontmatter mapping and turns each one into an inline
Azure Developer CLI prompt-agent service for the project-root ``azure.yaml``.
Agents without a ``foundry:`` mapping are not Foundry agents and are skipped.

This module owns the frontmatter schema, its validation, and the exact shape
of the emitted service mappings. Merging into ``azure.yaml`` lives in
:mod:`apm_cli.integration.foundry_azure_yaml`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apm_cli.integration.targets import KNOWN_TARGETS
from apm_cli.primitives.models import Chatmode

FOUNDRY_PROJECT_DIR = KNOWN_TARGETS["foundry"].root_dir
FOUNDRY_SKILLS_PREFIX = f"{KNOWN_TARGETS['foundry'].skills_rel_root}/"
AGENT_HOST = "azure.ai.agent"
SKILL_HOST = "azure.ai.skill"
TOOLSET_TYPE = "microsoft_copilot_toolset_preview"

SUPPORTED_KINDS = ("prompt",)
SUPPORTED_HARNESSES = ("microsoft_copilot_preview",)
BUILTIN_TOOL_NAMES = frozenset({"filesystem_read", "filesystem_write", "shell", "subagents", "web"})
REQUIRE_APPROVAL_VALUES = ("always", "never")
SECRET_LIKE_KEYS = frozenset(
    {"token", "api_key", "apikey", "key", "secret", "password", "headers", "authorization"}
)

SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SERVER_LABEL_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

_FOUNDRY_KEYS = frozenset({"model", "kind", "harness", "skills", "builtin_tools", "mcp"})
_BUILTIN_KEYS = frozenset({"default_enabled", "enabled", "disabled"})
_MCP_KEYS = frozenset(
    {"connection", "server_label", "server_url", "require_approval", "allowed_tools"}
)


class FoundryAgentError(ValueError):
    """A Foundry agent primitive cannot be emitted."""


@dataclass(frozen=True)
class FoundryMcpServer:
    """One remote MCP server reached through a Foundry project connection."""

    connection: str
    server_label: str
    server_url: str
    require_approval: str = "always"
    allowed_tools: tuple[str, ...] | None = None


@dataclass(frozen=True)
class FoundryAgentSpec:
    """Validated Foundry agent ready for emission."""

    name: str
    instructions: str
    model: str
    source: Path
    kind: str = "prompt"
    harness: str = "microsoft_copilot_preview"
    skills: tuple[str, ...] = ()
    builtin_tools: dict[str, bool] | None = None
    builtin_default_enabled: bool = False
    mcp: tuple[FoundryMcpServer, ...] = field(default_factory=tuple)


def _fail(source: Path, message: str) -> FoundryAgentError:
    return FoundryAgentError(f"{source.as_posix()}: {message}")


def _check_keys(source: Path, where: str, value: dict, allowed: frozenset[str]) -> None:
    """Reject secret-looking keys first, then any unknown key."""
    for key in value:
        normalized = str(key).lower().replace("-", "_")
        if normalized in SECRET_LIKE_KEYS:
            raise _fail(
                source,
                f"'{where}.{key}' looks like a credential; credentials belong in the "
                "Foundry project connection, reference it by name with 'connection'",
            )
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise _fail(
            source,
            f"unknown key(s) under '{where}': {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(allowed))})",
        )


def _string(source: Path, where: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(source, f"'{where}' must be a non-empty string")
    return value.strip()


def _string_list(source: Path, where: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _fail(source, f"'{where}' must be a list of strings")
    return tuple(sorted({_string(source, where, item) for item in value}))


def _choice(source: Path, where: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise _fail(source, f"'{where}' must be one of: {', '.join(allowed)} (got {value!r})")
    return value


def _parse_builtin_tools(source: Path, raw: Any) -> tuple[dict[str, bool], bool]:
    if not isinstance(raw, dict):
        raise _fail(source, "'foundry.builtin_tools' must be a mapping")
    _check_keys(source, "foundry.builtin_tools", raw, _BUILTIN_KEYS)
    default_enabled = raw.get("default_enabled", False)
    if not isinstance(default_enabled, bool):
        raise _fail(source, "'foundry.builtin_tools.default_enabled' must be true or false")
    configs: dict[str, bool] = {}
    for list_key, enabled in (("enabled", True), ("disabled", False)):
        where = f"foundry.builtin_tools.{list_key}"
        for name in _string_list(source, where, raw.get(list_key, [])):
            if name not in BUILTIN_TOOL_NAMES:
                raise _fail(
                    source,
                    f"'{where}' has unknown built-in tool '{name}' "
                    f"(allowed: {', '.join(sorted(BUILTIN_TOOL_NAMES))})",
                )
            if name in configs:
                raise _fail(
                    source,
                    f"built-in tool '{name}' is listed in both 'enabled' and 'disabled'",
                )
            configs[name] = enabled
    return configs, default_enabled


def _parse_mcp(source: Path, raw: Any) -> tuple[FoundryMcpServer, ...]:
    if not isinstance(raw, list):
        raise _fail(source, "'foundry.mcp' must be a list of mappings")
    servers: dict[str, FoundryMcpServer] = {}
    for index, entry in enumerate(raw):
        where = f"foundry.mcp[{index}]"
        if not isinstance(entry, dict):
            raise _fail(source, f"'{where}' must be a mapping")
        _check_keys(source, where, entry, _MCP_KEYS)
        label = _string(source, f"{where}.server_label", entry.get("server_label"))
        if not SERVER_LABEL_RE.match(label):
            raise _fail(source, f"'{where}.server_label' must match {SERVER_LABEL_RE.pattern}")
        if label in servers:
            raise _fail(source, f"duplicate MCP server_label '{label}'")
        url = _string(source, f"{where}.server_url", entry.get("server_url"))
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise _fail(source, f"'{where}.server_url' must be an https:// URL (got {url!r})")
        allowed_tools = None
        if "allowed_tools" in entry:
            allowed_tools = _string_list(
                source, f"{where}.allowed_tools", entry.get("allowed_tools")
            )
            if not allowed_tools:
                raise _fail(
                    source,
                    f"'{where}.allowed_tools' must list at least one tool; omit it to allow all",
                )
        servers[label] = FoundryMcpServer(
            connection=_string(source, f"{where}.connection", entry.get("connection")),
            server_label=label,
            server_url=url,
            require_approval=_choice(
                source,
                f"{where}.require_approval",
                entry.get("require_approval", "always"),
                REQUIRE_APPROVAL_VALUES,
            ),
            allowed_tools=allowed_tools,
        )
    return tuple(servers[label] for label in sorted(servers))


def normalize_instructions(body: str) -> str:
    """Return the agent body with trailing whitespace removed, one final newline."""
    lines = [line.rstrip() for line in body.strip("\r\n").splitlines()]
    text = "\n".join(lines).rstrip()
    return f"{text}\n" if text else ""


def parse_foundry_agent(agent: Chatmode) -> FoundryAgentSpec | None:
    """Validate *agent* for Foundry; ``None`` when it has no ``foundry:`` mapping.

    Raises:
        FoundryAgentError: The ``foundry:`` mapping or body is invalid. The
            message is prefixed with the agent file path.
    """
    raw = agent.foundry
    if raw is None:
        return None
    source = Path(agent.file_path)
    if not isinstance(raw, dict):
        raise _fail(source, "'foundry' must be a mapping")
    _check_keys(source, "foundry", raw, _FOUNDRY_KEYS)

    name = agent.declared_name if agent.declared_name is not None else agent.name
    if not SERVICE_NAME_RE.match(name or ""):
        raise _fail(
            source,
            f"agent name {name!r} is not a valid azure.yaml service name "
            f"(must match {SERVICE_NAME_RE.pattern})",
        )
    instructions = normalize_instructions(agent.content or "")
    if not instructions:
        raise _fail(source, "agent body is empty; it becomes the Foundry agent instructions")
    if "model" not in raw:
        raise _fail(source, "'foundry.model' is required (deployment name or ${VAR} reference)")

    builtin_tools, default_enabled = (
        _parse_builtin_tools(source, raw["builtin_tools"])
        if "builtin_tools" in raw
        else (None, False)
    )
    return FoundryAgentSpec(
        name=name,
        instructions=instructions,
        model=_string(source, "foundry.model", raw["model"]),
        source=source,
        kind=_choice(source, "foundry.kind", raw.get("kind", "prompt"), SUPPORTED_KINDS),
        harness=_choice(
            source,
            "foundry.harness",
            raw.get("harness", "microsoft_copilot_preview"),
            SUPPORTED_HARNESSES,
        ),
        skills=_string_list(source, "foundry.skills", raw.get("skills", [])),
        builtin_tools=builtin_tools,
        builtin_default_enabled=default_enabled,
        mcp=_parse_mcp(source, raw.get("mcp", [])),
    )


def build_skill_service(skill: str) -> dict[str, Any]:
    """Return the managed ``azure.ai.skill`` service for a deployed skill."""
    return {"host": SKILL_HOST, "archive": f"./{FOUNDRY_SKILLS_PREFIX}{skill}"}


def build_agent_service(spec: FoundryAgentSpec) -> dict[str, Any]:
    """Return the inline ``azure.ai.agent`` service mapping (exact key order)."""
    from ruamel.yaml.scalarstring import LiteralScalarString

    service: dict[str, Any] = {
        "host": AGENT_HOST,
        "project": FOUNDRY_PROJECT_DIR,
        "kind": spec.kind,
        "harness": {"type": spec.harness},
        "model": spec.model,
        "instructions": LiteralScalarString(spec.instructions),
    }
    if spec.skills:
        service["skills"] = list(spec.skills)
        service["uses"] = list(spec.skills)
    tools: list[dict[str, Any]] = []
    if spec.builtin_tools is not None:
        toolset: dict[str, Any] = {
            "type": TOOLSET_TYPE,
            "defaultConfig": {"enabled": spec.builtin_default_enabled},
        }
        if spec.builtin_tools:
            toolset["configs"] = [
                {"name": name, "enabled": spec.builtin_tools[name]}
                for name in sorted(spec.builtin_tools)
            ]
        tools.append(toolset)
    for server in spec.mcp:
        entry: dict[str, Any] = {
            "type": "mcp",
            "server_label": server.server_label,
            "server_url": server.server_url,
            "project_connection_id": server.connection,
            "require_approval": server.require_approval,
        }
        if server.allowed_tools is not None:
            entry["allowed_tools"] = list(server.allowed_tools)
        tools.append(entry)
    if tools:
        service["tools"] = tools
    return service


def build_foundry_services(
    specs: list[FoundryAgentSpec],
    deployed_skills: set[str],
) -> dict[str, dict[str, Any]]:
    """Return every managed service (agents + their skills) keyed by name.

    Raises:
        FoundryAgentError: Duplicate agent names, an agent/skill name clash,
            or an agent referencing a skill this install did not deploy.
    """
    services: dict[str, dict[str, Any]] = {}
    agents: dict[str, FoundryAgentSpec] = {}
    for spec in specs:
        if spec.name in agents:
            raise FoundryAgentError(
                f"duplicate Foundry agent name '{spec.name}' in "
                f"{agents[spec.name].source.as_posix()} and {spec.source.as_posix()}"
            )
        agents[spec.name] = spec
        for skill in spec.skills:
            if skill not in deployed_skills:
                raise FoundryAgentError(
                    f"{spec.source.as_posix()}: agent '{spec.name}' uses skill '{skill}', "
                    f"which this install did not deploy to {FOUNDRY_SKILLS_PREFIX}. Add the "
                    "skill locally or through a 'dependencies' package (skills from "
                    "devDependencies are never deployed to foundry)."
                )
            services[skill] = build_skill_service(skill)
    for name, spec in agents.items():
        if name in services:
            raise FoundryAgentError(
                f"{spec.source.as_posix()}: agent name '{name}' clashes with a skill "
                "service of the same name; rename the agent"
            )
        services[name] = build_agent_service(spec)
    return {name: services[name] for name in sorted(services)}
