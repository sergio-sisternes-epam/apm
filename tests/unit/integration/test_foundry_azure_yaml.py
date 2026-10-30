"""azure.yaml merge/ownership tests for the foundry target."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apm_cli.integration.foundry_agents import FoundryAgentError, build_skill_service
from apm_cli.integration.foundry_azure_yaml import merge_foundry_services

USER_AZURE_YAML = """# deployment for the support stack
name: my-app
metadata:
  template: custom
services:
  # hand-written web front end
  web:
    host: containerapp
    project: ./web
infra:
  provider: bicep
"""


def _agent(name: str) -> dict:
    return {"host": "azure.ai.agent", "project": ".foundry", "kind": "prompt", "model": "small"}


def _sidecar(root: Path) -> Path:
    return root / ".foundry" / "apm-services.json"


def test_preserves_user_comments_services_and_keys(tmp_path: Path) -> None:
    (tmp_path / "azure.yaml").write_text(USER_AZURE_YAML, encoding="utf-8")
    services = {"kb-lookup": build_skill_service("kb-lookup"), "support-assistant": _agent("x")}
    merge_foundry_services(tmp_path, "proj", services)
    text = (tmp_path / "azure.yaml").read_text(encoding="utf-8")
    assert text.startswith(USER_AZURE_YAML.split("infra:")[0])
    assert "# hand-written web front end" in text
    assert "infra:\n  provider: bicep\n" in text
    assert text.index("web:") < text.index("kb-lookup:") < text.index("support-assistant:")
    assert json.loads(_sidecar(tmp_path).read_text()) == {
        "services": ["kb-lookup", "support-assistant"]
    }


def test_collision_with_user_service_errors(tmp_path: Path) -> None:
    (tmp_path / "azure.yaml").write_text(USER_AZURE_YAML, encoding="utf-8")
    with pytest.raises(FoundryAgentError, match="web"):
        merge_foundry_services(tmp_path, "proj", {"web": _agent("web")})
    assert (tmp_path / "azure.yaml").read_text(encoding="utf-8") == USER_AZURE_YAML
    assert not _sidecar(tmp_path).exists()


def test_stale_managed_entries_removed_and_in_place_update(tmp_path: Path) -> None:
    (tmp_path / "azure.yaml").write_text(USER_AZURE_YAML, encoding="utf-8")
    merge_foundry_services(
        tmp_path, "proj", {"old-agent": _agent("o"), "support-assistant": _agent("s")}
    )
    merge_foundry_services(tmp_path, "proj", {"support-assistant": {"host": "azure.ai.agent"}})
    text = (tmp_path / "azure.yaml").read_text(encoding="utf-8")
    assert "old-agent" not in text
    assert "support-assistant:\n    host: azure.ai.agent\ninfra:" in text
    assert json.loads(_sidecar(tmp_path).read_text()) == {"services": ["support-assistant"]}


def test_no_agents_removes_managed_entries_and_sidecar(tmp_path: Path) -> None:
    (tmp_path / "azure.yaml").write_text(USER_AZURE_YAML, encoding="utf-8")
    merge_foundry_services(tmp_path, "proj", {"support-assistant": _agent("s")})
    assert merge_foundry_services(tmp_path, "proj", {}) is True
    assert (tmp_path / "azure.yaml").read_text(encoding="utf-8") == USER_AZURE_YAML
    assert not _sidecar(tmp_path).exists()


def test_no_agents_and_no_sidecar_leaves_azure_yaml_untouched(tmp_path: Path) -> None:
    assert merge_foundry_services(tmp_path, "proj", {}) is False
    assert not (tmp_path / "azure.yaml").exists()

    (tmp_path / "azure.yaml").write_text(USER_AZURE_YAML, encoding="utf-8")
    before = (tmp_path / "azure.yaml").stat().st_mtime_ns
    assert merge_foundry_services(tmp_path, "proj", {}) is False
    assert (tmp_path / "azure.yaml").stat().st_mtime_ns == before
    assert not _sidecar(tmp_path).exists()


def test_creates_azure_yaml_with_project_name(tmp_path: Path) -> None:
    merge_foundry_services(tmp_path, "proj", {"support-assistant": {"host": "azure.ai.agent"}})
    assert (tmp_path / "azure.yaml").read_text(encoding="utf-8") == (
        "name: proj\nservices:\n  support-assistant:\n    host: azure.ai.agent\n"
    )
