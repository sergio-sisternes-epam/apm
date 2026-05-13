"""Pytest fixtures exposing chaos recipes.

Thin wrappers over the pure-function recipes in
``tests/chaos/_fixtures.py``. The chaos-monkey agent builds scenarios
by calling the underlying functions; the regression-trap tests it
authors use these fixtures so CI reproduces the same scenario.

Keeping both surfaces driven by the same recipe module is the
single-source-of-truth invariant for chaos reproduction.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.chaos import _fixtures


@pytest.fixture
def apm_project(tmp_path: Path) -> Path:
    """Yield a minimal valid APM project rooted under ``tmp_path``."""
    return _fixtures.apm_project(tmp_path)


@pytest.fixture
def apm_yml_factory(tmp_path: Path) -> Callable[[str], Path]:
    """Yield a factory that writes an arbitrary ``apm.yml`` body."""

    def _make(content: str) -> Path:
        return _fixtures.apm_yml(tmp_path, content)

    return _make


@pytest.fixture
def bogus_pat_env() -> Callable[..., dict[str, str]]:
    """Yield the env-override helper directly."""
    return _fixtures.bogus_pat_env


@pytest.fixture
def local_pkg_repo(tmp_path: Path) -> Callable[..., str]:
    """Yield a factory that initialises a local file:// APM package repo."""

    def _make(
        *,
        name: str = "fake-pkg",
        include_apm_yml: bool = True,
        ref: str = "main",
    ) -> str:
        return _fixtures.local_pkg_repo(
            tmp_path, name=name, include_apm_yml=include_apm_yml, ref=ref
        )

    return _make


@pytest.fixture
def target_project(tmp_path: Path) -> Callable[..., Path]:
    """Yield a factory that builds a project for a chosen target."""

    def _make(target: str, *, present: bool = True) -> Path:
        return _fixtures.target_project(tmp_path, target, present=present)

    return _make


@pytest.fixture
def mcp_config(tmp_path: Path) -> Callable[..., Path]:
    """Yield a factory that writes a synthetic MCP config."""

    def _make(content: str, *, target: str = "copilot") -> Path:
        return _fixtures.mcp_config(tmp_path, content, target=target)

    return _make
