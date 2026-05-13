---
schedule: daily
timeout-minutes: 40
---

# Chaos Monkey

Open-ended program: continuously discover failure modes in the `apm`
CLI by exercising it in undocumented, malformed, or adversarial ways.
No `target-metric` is set; the goal is to keep extending the
regression-trap suite under `tests/chaos/` forever.

## Goal

Maximise `hardened_findings`, the count of regression-trap pytest
tests under `tests/chaos/` carrying the `@pytest.mark.chaos` marker.
Each iteration adds at least one test that captures a newly observed
graceful, silent, or uncontrolled failure of the `apm` CLI.

The chaos-monkey agent (`.apm/agents/chaos-monkey.agent.md`) and the
vector catalogue (`.apm/skills/chaos-vector-catalogue/`) define HOW
to discover, reproduce, classify, and capture findings. This program
file declares only the scheduling, target surface, and metric.

## Target

The iteration may modify files under:

- `tests/chaos/` -- add new `test_<surface>_<sub_vector>.py` files;
  may add helpers under `_fixtures.py` only when a vector cannot be
  expressed with existing fixtures (rare).
- `.apm/skills/chaos-vector-catalogue/references/` -- when the
  iteration discovers a new sub-vector worth recording for future
  runs.

The iteration MUST NOT modify:

- `src/apm_cli/` -- chaos-monkey reproduces and traps, it does not
  fix bugs.
- `tests/unit/`, `tests/integration/`, `tests/test_console.py` --
  out of scope for chaos.
- workflow files, CI configuration, lockfile, or anything outside
  `tests/chaos/` and the catalogue references.

## Evaluation

```
python scripts/chaos_metric.py
```

Emits a single line of JSON on stdout, for example:

```
{"hardened_findings": 7}
```

The metric is monotonic-upward (adding a new chaos test increments
it by one; removing one would decrement it). Autoloop's
keep-iteration ratchet therefore keeps every iteration that
successfully adds a new regression-trap.

## Iteration contract (summary; full body in the skill)

For each iteration the chaos-monkey agent:

1. Reads prior findings from gh-aw memory and the existing tests
   under `tests/chaos/` so duplicate vectors are skipped.
2. Picks a `(surface, sub_vector)` from the catalogue that has not
   yet been hardened.
3. Builds a hermetic scratch project using
   `tests/chaos/_fixtures.py` helpers.
4. Invokes `apm` via `tests/chaos/_harness.run_apm` and captures the
   real exit code, stdout, stderr, and timeout flag.
5. Classifies the outcome as graceful / silent / uncontrolled using
   the captured evidence (never recall).
6. Writes one new `test_<surface>_<sub_vector>.py` that re-runs the
   same recipe and asserts the same outcome.
7. Verifies the new file with `uv run ruff check tests/chaos/`,
   `uv run ruff format --check tests/chaos/`, and `uv run pytest
   -m chaos -k <new_test_name> tests/chaos/`.
8. Returns; autoloop runs `scripts/chaos_metric.py`, accepts the
   iteration if the metric increased, and emits a SafeOutput issue
   and draft PR via the autoloop substrate.

The agent does NOT call `gh`, `git push`, or any GitHub-write CLI.
The autoloop workflow owns externalisation.
