# Surface: `cli_commands`

Chaos surface for the top-level `apm` command argv. Exercises help
text, subcommand dispatch, flag parsing, and exit codes. Load this
file only when the chosen vector targets the CLI argv layer.

## Known invariants

These are the contract claims the regression-trap test asserts
against. If a future change to `src/apm_cli/cli.py` weakens them, the
chaos test goes red and the team is told.

- An unknown subcommand exits non-zero and prints a stderr message
  that names the unknown command and the closest known subcommand
  (or at least lists available commands). Exit code MUST NOT be 0.
- A known subcommand invoked without required arguments exits
  non-zero with a stderr message naming the missing argument. It
  MUST NOT print a Python traceback.
- `apm --help` and `apm <subcommand> --help` exit 0 and write the
  help text to stdout (not stderr). Output is ASCII (per repo
  encoding rule).
- A flag value of the wrong type (e.g. a non-integer where an
  integer is expected) exits non-zero with a stderr message that
  identifies the flag.
- An unknown flag exits non-zero, naming the offending flag.

## Likely failure modes

- **silent**: command echoes the help text and exits 0 when the
  user clearly meant to invoke a real subcommand (e.g. typo).
- **uncontrolled**: argv parsing crashes with a `KeyError` or
  unhandled `click.exceptions.UsageError.format_message` path,
  leaking a Python traceback to stderr.
- **graceful**: clear "Unknown command: ..." stderr + non-zero exit.

## Fixture recipes

For CLI-only vectors, no project state is needed; pass a fresh
tempdir as `cwd` so any accidental file write is captured under it.

```python
import pytest
from pathlib import Path
from tests.chaos._harness import run_apm

@pytest.mark.chaos
def test_cli_unknown_subcommand(tmp_path: Path):
    result = run_apm(["nope-not-a-real-command"], cwd=tmp_path, timeout=15)

    assert not result.timed_out
    assert result.returncode != 0, "unknown subcommand silently succeeded"
    assert "nope-not-a-real-command" in result.stderr.lower() or \
           "no such command" in result.stderr.lower()
    assert "Traceback" not in result.stderr, "uncontrolled: traceback leaked"
```

## Sample chaos inputs

Combine these in argv to widen coverage. Each line is a candidate
sub-vector.

- `["nope-not-a-real-command"]`
- `["install", "--no-such-flag"]`
- `["install", "--max-parallel=not-an-int"]`
- `["install"]` (no apm.yml in cwd)
- `["init", "--no-such-flag"]`
- `["help"]` (instead of `--help`; verifies absence of git-style
  help subcommand)
- `[""]` (empty-string argv)
- `[" "]` (single-space argv)
- argv with embedded null byte: `["install\x00install"]`
- argv with unicode that may not encode to cp1252: `["install\u2014"]`

## Classification mapping

| Observation | Classification |
|---|---|
| non-zero exit + named cause in stderr + no traceback | `graceful` |
| exit 0 with no observable effect | `silent` |
| exit 0 with a destructive side effect outside `cwd` | `uncontrolled` |
| any traceback in stderr | `uncontrolled` |
| `timed_out=True` (no progress in `timeout` seconds) | `uncontrolled` |

## Anti-patterns

- Do NOT assert exact stderr strings; use stable substrings.
- Do NOT assert exit code `== 1` -- non-zero is the contract;
  Click and other frameworks use various non-zero codes.
- Do NOT shell out to `bash -c "apm ..."` -- always pass argv as a
  list to `run_apm`.
