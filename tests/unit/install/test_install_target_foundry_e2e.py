"""CliRunner tests for the experimental skills-only ``foundry`` target."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from apm_cli.cli import cli

_ENV = {"APM_E2E_TESTS": "1"}


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

    pkg = tmp_path / "pkg"
    (pkg / ".apm" / "skills" / "demo").mkdir(parents=True)
    (pkg / ".apm" / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\nBody\n", encoding="ascii"
    )
    (pkg / ".apm" / "instructions").mkdir()
    (pkg / ".apm" / "instructions" / "rule.instructions.md").write_text(
        '---\napplyTo: "**"\n---\nRule\n', encoding="ascii"
    )
    (pkg / "apm.yml").write_text("name: pkg\nversion: 1.0.0\n", encoding="ascii")

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "apm.yml").write_text(
        "name: proj\nversion: 1.0.0\ndependencies:\n  apm:\n    - ../pkg\n",
        encoding="ascii",
    )
    yield proj, apm_dir
    monkeypatch.setattr(conf, "_config_cache", None)


def _enable(apm_dir: Path) -> None:
    (apm_dir / "config.json").write_text(
        json.dumps({"experimental": {"foundry": True}}), encoding="ascii"
    )


def _install(proj: Path, *args: str):
    import os

    cwd = os.getcwd()
    os.chdir(proj)
    try:
        return CliRunner().invoke(cli, ["install", *args], env=_ENV)
    finally:
        os.chdir(cwd)


def test_flag_off_refuses_with_enable_hint(project) -> None:
    proj, _ = project
    result = _install(proj, "--target", "foundry")
    assert "apm experimental enable foundry" in " ".join(result.output.split())
    assert not (proj / ".foundry").exists()


def test_flag_on_deploys_skills_only(project) -> None:
    proj, apm_dir = project
    _enable(apm_dir)
    result = _install(proj, "--target", "foundry")
    assert result.exit_code == 0, result.output
    assert (proj / ".foundry" / "skills" / "demo" / "SKILL.md").is_file()
    files = {p.relative_to(proj).as_posix() for p in (proj / ".foundry").rglob("*") if p.is_file()}
    assert all(f.startswith(".foundry/skills/") for f in files)
    assert not (proj / "azure.yaml").exists()
    assert not (proj / ".github").exists()
    assert not (proj / ".agents").exists()


def test_global_scope_is_unsupported(project) -> None:
    proj, apm_dir = project
    _enable(apm_dir)
    result = _install(proj, "--target", "foundry", "--global")
    home = Path.home()
    assert not (home / ".foundry").exists()
    assert not (proj / ".foundry").exists()
    assert "without native user-level support: foundry" in " ".join(result.output.split())
