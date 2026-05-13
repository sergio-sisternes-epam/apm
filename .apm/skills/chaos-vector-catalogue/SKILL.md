---
name: chaos-vector-catalogue
description: >-
  Use this skill when the user wants to harden the APM CLI by exploring
  undocumented usage, fuzzing inputs, or discovering uncontrolled or silent
  failure modes -- even when the user says "find edge cases", "stress test",
  "break apm", "fuzz the cli", "what happens if I ...", "discover failure
  modes", "regression-trap a bug", or asks how the tool behaves on malformed
  input. Reproduces each vector through the actual terminal against the
  installed apm binary, classifies the failure as graceful, silent, or
  uncontrolled from captured stdout/stderr/exit-code, writes one
  regression-trap pytest under tests/chaos/, and emits a SafeOutput issue
  plus draft PR with the new test. Does NOT fix bugs; does NOT review PRs;
  does NOT chase line-coverage gaps.
---

# chaos-vector-catalogue

Discover and trap failure modes in the `apm` CLI by exercising it in
undocumented or adversarial ways. Each iteration adds one
regression-trap pytest that captures the observed behaviour so a
future change cannot silently regress it.

This skill is the body of the recurrent chaos-monkey agent. It is
also useful inside an ad-hoc maintainer session ("find a chaos
vector for the integrator surface"). The chaos-monkey persona at
`.apm/agents/chaos-monkey.agent.md` supplies the lens (hostile
tester, NOT fixer); this skill supplies the procedure.

## Hard constraints (re-read at every chaos attempt)

1. The classification of a vector MUST cite the captured
   `(returncode, stdout, stderr, timed_out)` from one specific
   `run_apm()` call in THIS attempt. LLM-asserted failure claims
   are forbidden.
2. The agent NEVER modifies `src/apm_cli/`. Only `tests/chaos/`
   and `.apm/skills/chaos-vector-catalogue/references/`.
3. The agent NEVER invokes `gh`, `git push`, or any GitHub-write
   CLI. Externalisation is owned by the gh-aw SafeOutputs stage.
4. Every subprocess invocation goes through
   `tests/chaos/_harness.run_apm`, with a hermetic scratch
   `cwd` from `_fixtures.py` and a sanitised env.
5. The objective is REPRODUCE + TEST + RAISE. The objective is
   NOT to fix the bug -- if a fix is obvious, that goes into the
   issue body for a human reviewer, not into a patch.

## Procedure

Run these steps in order. After each step, before proceeding,
confirm the previous step's evidence is real (terminal output
captured, file actually written, lint actually green). Truth #1
PLAN BEFORE EXECUTION + truth #7 RE-INJECT GOAL apply: re-read
this list at the top of every attempt.

### 1. Read memory; build the "already hardened" set

The gh-aw memory branch carries past findings as
`memory/chaos-monkey/findings.md`. Each entry has a
deterministic VECTOR SIGNATURE: the SHA-256 hash of
`(surface, sub_vector_label, argv, sorted env override keys)`.
Read the file (substrate gives a single tool call); build the
set of signatures. Also list `tests/chaos/test_*.py` and treat
any file whose name matches an existing signature as already
hardened.

### 2. Pick a not-yet-hardened (surface, sub_vector)

Surfaces in this catalogue (load only the one chosen):

| Surface | Reference | When to pick |
|---|---|---|
| `cli_commands` | [references/cli_commands.md](references/cli_commands.md) | argv-shaped vectors: unknown subcommands, wrong flag types, malformed argv |
| `apm_yml_schema` | [references/apm_yml_schema.md](references/apm_yml_schema.md) | manifest-shaped vectors: invalid YAML, wrong types, missing keys, unsafe tags |
| `auth_flows` | [references/auth_flows.md](references/auth_flows.md) | credential-shaped vectors: bogus PAT, wrong host, token leak via logs |
| `deps_marketplace` | [references/deps_marketplace.md](references/deps_marketplace.md) | dependency-shaped vectors: missing repo, missing ref, malformed url, lockfile corruption |
| `integrators` | [references/integrators.md](references/integrators.md) | target-detection-shaped vectors: ambiguous signals, corrupted signal files |
| `mcp` | [references/mcp.md](references/mcp.md) | MCP-config-shaped vectors: malformed JSON, wrong hostnames, missing required fields |

Pick the surface whose count of hardened sub-vectors is the
LOWEST among those still relevant. Tie-break by random pick. The
reference for the chosen surface lists candidate sub-vectors.

LAZY-LOAD TRIGGER: read `references/<surface>.md` ONLY for the
chosen surface. Do not load the other five.

### 3. Build a hermetic scratch workspace

Open a fresh `tempfile.TemporaryDirectory()` (or the gh-aw
runner equivalent). Use the helpers in
`tests/chaos/_fixtures.py` -- never hand-roll setup, because the
regression-trap test will reuse the SAME helpers and divergence
breaks reproduction.

Helper API (single source of truth):

- `apm_project(tmp)` -> Path to a minimal valid project
- `apm_yml(tmp, content)` -> Path to a project with a chosen body
- `bogus_pat_env(value, host)` -> env-overrides dict
- `local_pkg_repo(tmp, name, include_apm_yml, ref)` -> file:// URL
- `target_project(tmp, target, present)` -> Path to a target-shaped project
- `mcp_config(tmp, content, target)` -> Path with an mcp.json written

### 4. Reproduce via `run_apm`

```python
from tests.chaos._harness import run_apm
result = run_apm(
    args=[...],                  # the chaos argv
    cwd=project,                 # the scratch workspace
    env_overrides={...} or None, # vector-specific overrides
    timeout=60,                  # 60s default; raise if needed
)
```

`result` is a frozen `ChaosResult` with fields `returncode`,
`stdout`, `stderr`, `timed_out`, `elapsed_seconds`, `argv`,
`cwd`. These ARE the evidence. Nothing else is.

### 5. Classify

| Observation | Classification |
|---|---|
| `returncode != 0` AND stderr names the cause AND no `Traceback` in stderr | `graceful` |
| `returncode == 0` AND the expected effect did not occur | `silent` |
| `returncode != 0` AND stderr is empty | `silent` |
| `Traceback` substring in stderr | `uncontrolled` |
| `timed_out == True` | `uncontrolled` |
| file written outside `cwd` | `uncontrolled` |
| secret / token substring leaked into stdout or stderr | `uncontrolled` |

A `graceful` finding is still a finding: trap it so a future
change cannot weaken the error message.

### 6. Write the regression-trap test

File path: `tests/chaos/test_<surface>_<sub_vector>.py` where
`<sub_vector>` is a slug describing the vector (lowercase, no
spaces, ASCII only).

Use this template VERBATIM (calibrated prescriptiveness:
fragile structure, do not improvise):

```python
"""Regression trap for: <surface> / <sub_vector>.

Observed at: <ISO date>.
Classification: <graceful|silent|uncontrolled>.
Evidence: returncode=<rc>, timed_out=<bool>,
stderr fragment cited below.
"""

import pytest

from tests.chaos._harness import run_apm


@pytest.mark.chaos
def test_<surface>_<sub_vector>(<fixture_name>):
    # Hermetic scratch workspace built by the fixture.
    project = <fixture_name>

    # Chaos input: identical argv/env/stdin to the discovery run.
    result = run_apm(
        ["<subcommand>", "<flag>", "<value>"],
        cwd=project,
        env_overrides={"GITHUB_APM_PAT": "invalid"},
        timeout=60,
    )

    # Classification asserted against REAL evidence captured at
    # discovery time. Update only when the underlying bug is fixed.
    assert not result.timed_out, "regression: command now hangs"
    assert result.returncode != 0, "regression: command now exits 0 silently"
    assert "<stable stderr fragment>" in result.stderr
    assert "Traceback" not in result.stderr
```

Rules:

- Assert STABLE substrings of stderr, never exact strings.
- Assert `result.returncode != 0` (not `== 1`) unless the contract
  specifies a particular code.
- Always include the `"Traceback" not in result.stderr` assertion
  for `graceful` findings so a future regression that turns
  graceful into uncontrolled is caught.
- ASCII only in the source file (repo encoding rule).

### 7. Verify with the deterministic tool bridge (S4 + S7)

Run, in this order:

```
uv run --extra dev ruff check tests/chaos/
uv run --extra dev ruff format --check tests/chaos/
uv run pytest tests/chaos/ -m chaos -k test_<surface>_<sub_vector>
```

All three MUST succeed (the pytest run MUST pass, i.e. the
assertions hold against the same evidence captured in step 4).
If any fails, fix the new test only; do not touch `src/`. If the
test still cannot be made to pass without modifying `src/`, the
vector is "uncontrolled and not reproducible deterministically"
-- record this and skip emitting SafeOutputs.

### 8. Append finding to memory

Append a section to `memory/chaos-monkey/findings.md`:

```
## <ISO date> -- <surface> / <sub_vector>

- vector signature: <sha256>
- classification: <graceful|silent|uncontrolled>
- argv: <argv as JSON list>
- env keys: <sorted list>
- returncode: <int>; timed_out: <bool>; elapsed: <seconds>
- stderr excerpt: <first 200 chars, ASCII-safe>
- test file: tests/chaos/test_<surface>_<sub_vector>.py
- lesson: <one line; what future agents should know>
```

### 9. Emit SafeOutputs

ONE `create-issue` and ONE `create-pull-request` per iteration
(workflow enforces `max: 1` on each). Use the templates below.

Issue body template:

```
## Chaos finding: <surface> / <sub_vector>

**Classification**: <graceful|silent|uncontrolled>

**How to reproduce locally**:
```bash
uv run pytest tests/chaos/test_<surface>_<sub_vector>.py -m chaos
```

**Captured evidence** (do not edit; this is the discovery trace):
- returncode: `<rc>`
- timed_out: `<bool>`
- elapsed_seconds: `<float>`
- stderr (first 500 chars):
```
<excerpt>
```

**Recommended hardening** (for a human reviewer; chaos-monkey does
not patch source):
- <one or two concrete suggestions>

**Regression trap**: `tests/chaos/test_<surface>_<sub_vector>.py`
in the companion draft PR.

---
Filed automatically by chaos-monkey. Vector signature `<sha256>`.
```

PR body template:

```
## Regression trap for chaos finding `<surface>/<sub_vector>`

Adds `tests/chaos/test_<surface>_<sub_vector>.py` capturing the
behaviour observed at <ISO date>. Companion issue: <link>.

This PR DOES NOT fix the underlying behaviour; it locks the
current behaviour in place so a regression toward a worse
classification (e.g. silent -> uncontrolled) is caught.

To run only this trap:
```bash
uv run pytest tests/chaos/test_<surface>_<sub_vector>.py -m chaos
```

The chaos test marker is opt-in (`-m chaos`); regular `pytest`
runs continue to ignore `tests/chaos/`.

---
Filed automatically by chaos-monkey.
```

## Bundled scripts

- `scripts/chaos_metric.py` -- counts `@pytest.mark.chaos` tests
  under `tests/chaos/` and emits `{"hardened_findings": N}` on
  stdout. Used by the autoloop program at
  `.autoloop/programs/chaos-monkey.md`. Non-interactive;
  `--help` documented.

## Substrate cited by this skill

- `tests/chaos/_harness.py` -- `run_apm()` is the only entry
  point for the subprocess contract; the agent and the test it
  writes both call it.
- `tests/chaos/_fixtures.py` -- recipe functions for hermetic
  scenario setup; thin pytest wrappers in
  `tests/chaos/conftest.py`.
- `tests/chaos/README.md` -- marker contract and authoring notes.

## What this skill does NOT do

- Does not fix bugs in `src/apm_cli/`.
- Does not review human-authored PRs (that is `pr-review-panel`).
- Does not chase generic line-coverage gaps (that is
  `daily-test-improver`).
- Does not call `gh` or `git push` directly.
- Does not run against any real network endpoint; the
  `local_pkg_repo` fixture serves `file://` URLs for offline
  dependency exercise.
