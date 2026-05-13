# Surface: `integrators`

Chaos surface for target-integrator dispatch. Exercises how `apm`
detects which target (Copilot, Claude, VSCode, Windsurf, Cursor,
Codex) is active in a project and how it reacts when the signals
are missing, contradictory, or corrupted. Load this file only when
the chosen vector targets the integrator layer.

## Known invariants

- A project with the documented signal file for a target
  (e.g. `.github/copilot-instructions.md` for `copilot`) is
  detected as that target on the next `apm install`.
- A project with NO signal files exits non-zero with a clear
  "no target detected" stderr on commands that require a target.
- A project with MULTIPLE conflicting signal files either picks
  deterministically (documented priority) or prints a warning
  naming both. It MUST NOT silently pick one.
- `apm.yml` `targets:` overrides auto-detection; an explicit target
  not present in the project signals still works.
- An explicit `targets:` listing a target that does not exist in
  the binary (typo) exits non-zero.

## Likely failure modes

- **silent**: a corrupted signal file is treated as "target present"
  and the install proceeds with no warning.
- **silent**: target priority shifts between releases without a
  changelog entry.
- **uncontrolled**: a signal file containing binary garbage causes
  a decode error and a traceback.
- **uncontrolled**: a symlink loop under `.github/` causes the
  detector to recurse forever (timeout fires).
- **graceful**: clear "no target detected" stderr + non-zero exit.

## Fixture recipes

```python
import pytest
from tests.chaos._harness import run_apm

@pytest.mark.chaos
def test_integrators_no_target_signals(target_project):
    project = target_project("copilot", present=False)
    result = run_apm(["install"], cwd=project, timeout=30)

    assert not result.timed_out
    # contract: either non-zero with a clear message, OR exit 0
    # with a clear "no target detected, continuing" warning.
    if result.returncode == 0:
        assert "no target" in result.stderr.lower() or "no target" in result.stdout.lower()
    else:
        assert "target" in result.stderr.lower()
    assert "Traceback" not in result.stderr


@pytest.mark.chaos
def test_integrators_unknown_target_in_yml(apm_yml_factory):
    project = apm_yml_factory(
        "name: chaos\nversion: 0.0.1\ntargets: [no-such-target]\n"
    )
    result = run_apm(["install"], cwd=project, timeout=30)

    assert not result.timed_out
    assert result.returncode != 0
    assert "no-such-target" in result.stderr or "target" in result.stderr.lower()
```

## Sample chaos inputs

- project with no signal file and no `targets:` in `apm.yml`
- project with two conflicting signal files (e.g. copilot + claude)
- project with a signal file that is actually a directory
- project with a symlink loop under `.github/`
- project with a signal file containing 10 MB of garbage
- `targets:` listing the same target twice
- `targets:` listing an empty string (`targets: [""]`)
- `targets:` listing the literal string `"all"` or `"*"`
- `targets:` as a CSV with mixed whitespace
- a project where `.github/copilot-instructions.md` exists but is
  unreadable (`chmod 0000`)

## Classification mapping

| Observation | Classification |
|---|---|
| non-zero exit + named cause + no traceback | `graceful` |
| exit 0 with explicit warning naming the ambiguity | `graceful` |
| exit 0 with no warning when signals were ambiguous | `silent` |
| traceback in stderr | `uncontrolled` |
| `timed_out=True` (symlink loop, infinite scan) | `uncontrolled` |
| files written outside `cwd` | `uncontrolled` |

## Anti-patterns

- Do NOT rely on the order of `iterdir()` to assert priority --
  the platform's filesystem order is undefined; assert on the
  documented contract.
- Do NOT touch the real repo's `.github/` -- always build the
  scenario under a fixture tempdir.
- Do NOT assume Windows path semantics; the test runs on Linux in
  the gh-aw runner.
