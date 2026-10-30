"""Foundry agents phase: emit azd prompt-agent services into ``azure.yaml``.

Runs only when the experimental ``foundry`` target is active at project
scope, after the integration phase has deployed skills to
``.foundry/skills/``. Agent primitives (``.apm/agents/<name>.agent.md`` with a
``foundry:`` frontmatter mapping) come from the local project and from
production dependencies whose effective targets include ``foundry``;
devDependencies never contribute.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apm_cli.install.context import InstallContext

FOUNDRY_TARGET = "foundry"
_AGENTS_SUBDIR = Path(".apm") / "agents"


def _agent_files(root: Path) -> list[Path]:
    agents_dir = root / _AGENTS_SUBDIR
    return sorted(agents_dir.glob("*.agent.md")) if agents_dir.is_dir() else []


def _dependency_agent_roots(ctx: InstallContext, foundry_profile) -> list[Path]:
    """Install roots of production dependencies authorized for foundry."""
    from apm_cli.install.target_filter import resolve_effective_package_targets

    tree = getattr(ctx.dependency_graph, "dependency_tree", None)
    if tree is None or ctx.apm_modules_dir is None:
        return []
    roots: list[Path] = []
    nodes = sorted(tree.nodes.values(), key=lambda n: n.dependency_ref.get_unique_key())
    for node in nodes:
        selection = resolve_effective_package_targets(
            [foundry_profile],
            node.dependency_ref.target_subset,
            node.package,
            None,
            "",
            is_dev_dependency=node.is_dev,
        )
        if selection.targets:
            roots.append(node.dependency_ref.get_install_path(ctx.apm_modules_dir))
    return roots


def _deployed_foundry_skills(ctx: InstallContext) -> set[str]:
    from apm_cli.integration.foundry_agents import FOUNDRY_SKILLS_PREFIX

    paths = list(ctx.local_deployed_files)
    for files in ctx.package_deployed_files.values():
        paths.extend(files)
    skills: set[str] = set()
    for path in paths:
        normalized = str(path).replace("\\", "/")
        if normalized.startswith(FOUNDRY_SKILLS_PREFIX):
            name = normalized[len(FOUNDRY_SKILLS_PREFIX) :].split("/", 1)[0]
            if name:
                skills.add(name)
    return skills


def run(ctx: InstallContext) -> None:
    """Collect Foundry agents and merge their services into ``azure.yaml``."""
    import yaml

    from apm_cli.core.scope import InstallScope
    from apm_cli.integration.foundry_agents import (
        FoundryAgentError,
        build_foundry_services,
        parse_foundry_agent,
    )
    from apm_cli.integration.foundry_azure_yaml import merge_foundry_services
    from apm_cli.primitives.parser import parse_primitive_file

    foundry = next((t for t in ctx.targets or () if t.name == FOUNDRY_TARGET), None)
    if foundry is None or ctx.dry_run or ctx.scope not in (None, InstallScope.PROJECT):
        return

    logger = ctx.logger
    errors: list[str] = []
    specs = []
    roots = [ctx.source_root or ctx.project_root, *_dependency_agent_roots(ctx, foundry)]
    for root in roots:
        for agent_file in _agent_files(root):
            try:
                spec = parse_foundry_agent(parse_primitive_file(agent_file))
            except (FoundryAgentError, ValueError) as exc:
                errors.append(str(exc))
                continue
            if spec is None:
                if logger:
                    logger.verbose_detail(
                        f"Skipping {agent_file.name} for foundry: no 'foundry:' frontmatter"
                    )
                continue
            specs.append(spec)

    if not errors:
        try:
            services = build_foundry_services(specs, _deployed_foundry_skills(ctx))
            project_name = getattr(ctx.apm_package, "name", None) or ctx.project_root.name
            if merge_foundry_services(ctx.project_root, project_name, services) and logger:
                logger.progress(
                    f"Updated azure.yaml with {len(specs)} Foundry agent(s)", symbol="info"
                )
        except (FoundryAgentError, ValueError, yaml.YAMLError) as exc:
            errors.append(str(exc))

    for message in errors:
        ctx.diagnostics.error(f"Foundry agent step failed: {message}", package=FOUNDRY_TARGET)
