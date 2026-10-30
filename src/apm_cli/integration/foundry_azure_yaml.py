"""Merge APM-managed Foundry services into the project-root ``azure.yaml``.

APM owns only the service entries it lists in the ``.foundry/apm-services.json``
sidecar. User-authored services, comments, ordering, and other top-level keys
are preserved through a ruamel.yaml round-trip. ``azure.yaml`` itself is never
recorded as an APM-deployed file, so uninstall never deletes it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apm_cli.integration.foundry_agents import FOUNDRY_PROJECT_DIR, FoundryAgentError

AZURE_YAML = "azure.yaml"
SIDECAR_RELPATH = f"{FOUNDRY_PROJECT_DIR}/apm-services.json"


def read_managed_services(project_root: Path) -> set[str]:
    """Return the service names APM managed on the previous foundry install."""
    sidecar = project_root / SIDECAR_RELPATH
    if not sidecar.is_file():
        return set()
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return {str(name) for name in data.get("services", [])}
    except (ValueError, AttributeError) as exc:
        raise FoundryAgentError(f"{SIDECAR_RELPATH} is not valid JSON: {exc}") from exc


def _write_if_changed(path: Path, content: str) -> bool:
    from apm_cli.utils.yaml_io import write_yaml_text_atomic

    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_text_atomic(path, content)
    return True


def _write_sidecar(project_root: Path, names: list[str]) -> bool:
    sidecar = project_root / SIDECAR_RELPATH
    if not names:
        if sidecar.is_file():
            sidecar.unlink()
            return True
        return False
    return _write_if_changed(sidecar, json.dumps({"services": names}, indent=2) + "\n")


def merge_foundry_services(
    project_root: Path,
    project_name: str,
    services: dict[str, dict[str, Any]],
) -> bool:
    """Upsert *services* into ``azure.yaml`` and prune stale managed entries.

    Returns ``True`` when ``azure.yaml`` or the sidecar changed on disk.

    Raises:
        FoundryAgentError: A produced name collides with a user-authored
            service, or ``azure.yaml`` has a non-mapping ``services`` key.
    """
    from apm_cli.utils.yaml_io import load_yaml_roundtrip, yaml_roundtrip_to_str

    managed = read_managed_services(project_root)
    if not services and not managed:
        return False

    azure_path = project_root / AZURE_YAML
    if azure_path.is_file():
        doc = load_yaml_roundtrip(azure_path)
    elif services:
        doc = {"name": project_name}
    else:
        return _write_sidecar(project_root, [])
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        raise FoundryAgentError(f"{AZURE_YAML} must be a YAML mapping")

    existing = doc.get("services")
    if existing is None:
        if not services:
            return _write_sidecar(project_root, [])
        doc["services"] = existing = {}
    if not isinstance(existing, dict):
        raise FoundryAgentError(f"'services' in {AZURE_YAML} must be a mapping")

    collisions = sorted(name for name in services if name in existing and name not in managed)
    if collisions:
        raise FoundryAgentError(
            f"{AZURE_YAML} already defines service(s) not managed by APM: "
            f"{', '.join(collisions)}. Rename or delete your entry so APM can manage it."
        )
    for name in [name for name in existing if name in managed and name not in services]:
        del existing[name]
    for name in sorted(services):
        existing[name] = services[name]

    changed = _write_if_changed(azure_path, yaml_roundtrip_to_str(doc))
    return _write_sidecar(project_root, sorted(services)) or changed
