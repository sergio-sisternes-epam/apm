# `tests/chaos/` -- regression-trap suite for the chaos-monkey loop

Tests in this directory are authored by the `chaos-monkey` agent
(see `.apm/agents/chaos-monkey.agent.md` and
`.apm/skills/chaos-vector-catalogue/`). Each test captures one
specific failure-mode discovery: an exact argv + env + scratch
project that produced a graceful, silent, or uncontrolled failure
in the `apm` CLI.

## Marker contract

Every test in this directory uses `@pytest.mark.chaos`. The default
pytest selector in `pyproject.toml` deselects this marker:

```
addopts = "-m 'not benchmark and not live and not chaos'"
```

So `tests/chaos/` runs **only** when the suite is invoked with an
explicit `-m chaos` selector. CI does not run chaos tests by default.

To run them locally:

```
uv run pytest -m chaos tests/chaos/
```

## Why opt-in?

The chaos suite shells out to the installed `apm` CLI and may
exercise long-running or hang-prone code paths under a wall-clock
timeout. It is exploratory by nature; it is not appropriate for
every PR's CI lane. Maintainers can run it on demand or wire it into
a dedicated lane.

## Authoring shape

Tests follow a fixed shape so reproductions are bit-identical
between the chaos-monkey discovery run and CI:

```python
import pytest
from tests.chaos._harness import run_apm

@pytest.mark.chaos
def test_install_with_bogus_apm_yml(apm_yml_factory):
    project = apm_yml_factory("targets: [does-not-exist]")
    result = run_apm(["install"], cwd=project, timeout=30)

    assert not result.timed_out, "regression: command now hangs"
    assert result.returncode != 0, "regression: command now exits 0 silently"
    assert "does-not-exist" in result.stderr
```

Hard rules for authored tests:

- import `run_apm` from `tests.chaos._harness`; never call
  `subprocess.run` directly;
- pass `cwd=` (always a fixture-supplied path; never `Path.cwd()`);
- pass an explicit `timeout=` (default 60s; lower it when the vector
  is fast);
- assert against the captured `ChaosResult` fields only -- do not
  re-shell out for evidence;
- one vector per test file; file name encodes the surface and
  sub-vector (e.g. `test_apm_yml_unknown_target.py`).

## Layout

- `_harness.py` -- the `run_apm` subprocess contract. Single source
  of truth.
- `_fixtures.py` -- pure-function recipes (`apm_project`, `apm_yml`,
  `bogus_pat_env`, `local_pkg_repo`, `target_project`, `mcp_config`).
- `conftest.py` -- pytest wrappers exposing the recipes as fixtures.
- `test_<surface>_<sub_vector>.py` -- one regression-trap per file.

## Out of scope here

- The chaos-monkey agent itself (see `.apm/agents/`).
- The vector catalogue and surface references (see
  `.apm/skills/chaos-vector-catalogue/`).
- The autoloop program that schedules the agent (see
  `.autoloop/programs/chaos-monkey.md`).
