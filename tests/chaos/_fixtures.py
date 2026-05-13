"""Hermetic fixture recipes for chaos vector reproduction.

Every recipe is a pure function that takes a caller-supplied
``Path`` (a scratch tempdir) and writes scenario state INSIDE that
tempdir only. No global state, no network, no real credentials, no
mutation of the repo working copy.

These recipes are surfaced in two places:

- in ``tests/chaos/conftest.py`` as pytest fixtures, so the
  regression-trap tests authored by the chaos-monkey agent build the
  SAME scenario in CI;
- in ``.apm/skills/chaos-vector-catalogue/references/<surface>.md``
  as copy-paste snippets, so the chaos agent builds the SAME
  scenario during discovery.

The chaos-monkey persona body MUST call these functions; it MUST NOT
hand-roll ad-hoc setup, because the regression-trap test would then
fail to reproduce.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


def apm_project(tmp: Path, *, name: str = "chaos-fixture") -> Path:
    """Create a minimal valid apm.yml project under ``tmp``.

    Writes a project that ``apm`` accepts as well-formed so the
    chaos vector can target a specific surface (e.g. dependency
    resolution) without first tripping schema validation.
    """
    project = tmp / name
    project.mkdir(parents=True, exist_ok=True)
    (project / "apm.yml").write_text(
        textwrap.dedent(
            f"""\
            name: {name}
            version: 0.0.1
            description: Chaos fixture project (hermetic; do not modify by hand).
            targets:
              - copilot
            """
        ),
        encoding="utf-8",
    )
    # Provide the copilot target signal so target detection does not
    # have to guess.
    github_dir = project / ".github"
    github_dir.mkdir(parents=True, exist_ok=True)
    (github_dir / "copilot-instructions.md").write_text("# Chaos fixture\n", encoding="utf-8")
    return project


def apm_yml(tmp: Path, content: str, *, name: str = "chaos-yml") -> Path:
    """Write an arbitrary ``apm.yml`` body under ``tmp``.

    Used for schema-surface chaos: the body may be intentionally
    malformed (invalid YAML, wrong types, missing required fields,
    unicode surprises, etc.). No ``apm init`` is run.
    """
    project = tmp / name
    project.mkdir(parents=True, exist_ok=True)
    (project / "apm.yml").write_text(content, encoding="utf-8")
    return project


def bogus_pat_env(value: str = "invalid", *, host: str = "github") -> dict[str, str]:
    """Return env overrides for credential surfaces.

    ``host`` selects the variable to poison:

    - ``github`` -> ``GITHUB_APM_PAT``
    - ``ado`` -> ``ADO_APM_PAT``
    - ``both`` -> both

    Combine with another fixture (typically ``apm_project`` or
    ``local_pkg_repo``) to drive a flow that exercises auth
    resolution.
    """
    overrides: dict[str, str] = {}
    if host in {"github", "both"}:
        overrides["GITHUB_APM_PAT"] = value
    if host in {"ado", "both"}:
        overrides["ADO_APM_PAT"] = value
    if not overrides:
        raise ValueError(f"unknown host '{host}'; expected 'github', 'ado', or 'both'")
    return overrides


def local_pkg_repo(
    tmp: Path,
    *,
    name: str = "fake-pkg",
    include_apm_yml: bool = True,
    ref: str = "main",
) -> str:
    """Initialise a local git repo posing as an APM package source.

    Returns a ``file://`` URL that can be embedded in an ``apm.yml``
    dependency entry. The repo is fully offline (no network) and
    lives under ``tmp``. ``ref`` controls the branch name so a chaos
    vector can request a non-existent ref.

    ``include_apm_yml=False`` produces a repo missing the manifest,
    used to discover how ``apm`` reacts to a dependency that points
    at a non-APM repository.
    """
    repo = tmp / "_pkg_repos" / name
    repo.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["GIT_AUTHOR_NAME"] = "chaos"
    env["GIT_AUTHOR_EMAIL"] = "chaos@local"
    env["GIT_COMMITTER_NAME"] = "chaos"
    env["GIT_COMMITTER_EMAIL"] = "chaos@local"
    subprocess.run(["git", "init", "-b", ref, "-q"], cwd=str(repo), env=env, check=True)
    if include_apm_yml:
        (repo / "apm.yml").write_text(
            textwrap.dedent(
                f"""\
                name: {name}
                version: 0.0.1
                description: Hermetic chaos package (no real content).
                """
            ),
            encoding="utf-8",
        )
    (repo / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), env=env, check=True)
    subprocess.run(
        ["git", "commit", "-m", "chaos fixture", "-q"],
        cwd=str(repo),
        env=env,
        check=True,
    )
    return f"file://{repo}"


def target_project(tmp: Path, target: str, *, present: bool = True) -> Path:
    """Build a project with (or without) a specific target signal.

    ``target`` is one of ``copilot``, ``claude``, ``vscode``,
    ``windsurf``, ``cursor``, ``codex``. ``present=False`` deliberately
    omits the signal file so target auto-detection chaos can be
    exercised.

    The signal files used here match the conventions documented in
    the apm-usage skill and verified against
    ``src/apm_cli/core/target_detection.py``.
    """
    project = apm_project(tmp, name=f"target-{target}")
    if not present:
        copilot_signal = project / ".github" / "copilot-instructions.md"
        if copilot_signal.exists():
            copilot_signal.unlink()
        github_dir = project / ".github"
        if github_dir.exists() and not any(github_dir.iterdir()):
            github_dir.rmdir()
        return project

    if target == "copilot":
        (project / ".github" / "copilot-instructions.md").write_text(
            "# copilot\n", encoding="utf-8"
        )
    elif target == "claude":
        (project / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    elif target == "vscode":
        (project / ".github").mkdir(exist_ok=True)
    elif target == "windsurf":
        windsurf_dir = project / ".windsurf"
        windsurf_dir.mkdir(exist_ok=True)
        (windsurf_dir / "rules.md").write_text("# windsurf\n", encoding="utf-8")
    elif target == "cursor":
        cursor_dir = project / ".cursor"
        cursor_dir.mkdir(exist_ok=True)
        (cursor_dir / "rules.md").write_text("# cursor\n", encoding="utf-8")
    elif target == "codex":
        (project / "AGENTS.md").write_text("# codex\n", encoding="utf-8")
    else:
        raise ValueError(f"unknown target '{target}'")
    return project


def mcp_config(tmp: Path, content: str, *, target: str = "copilot") -> Path:
    """Write a synthetic MCP server config for the given target.

    The location follows the conventions documented in the apm-usage
    skill. Used for MCP-surface chaos: malformed JSON, wrong
    hostnames, missing required keys, etc.
    """
    project = apm_project(tmp, name=f"mcp-{target}")
    if target == "copilot":
        cfg_dir = project / ".vscode"
        cfg_dir.mkdir(exist_ok=True)
        cfg_path = cfg_dir / "mcp.json"
    elif target == "claude":
        cfg_path = project / ".mcp.json"
    else:
        raise ValueError(f"unsupported mcp target '{target}'")
    cfg_path.write_text(content, encoding="utf-8")
    return project
