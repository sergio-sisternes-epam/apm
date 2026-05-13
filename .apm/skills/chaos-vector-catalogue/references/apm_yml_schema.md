# Surface: `apm_yml_schema`

Chaos surface for the `apm.yml` manifest. Exercises the loader,
validator, and any code path that reads project metadata before
target detection or dependency resolution kicks in. Load this file
only when the chosen vector targets the manifest layer.

## Known invariants

- Invalid YAML (syntax error) exits non-zero with a stderr message
  citing the file path and a line/column hint. MUST NOT print a
  Python traceback.
- A missing required key (e.g. `name`) exits non-zero with a stderr
  message that names the missing key.
- A field of the wrong type (e.g. `version: [1, 2, 3]` where a
  string is expected) exits non-zero with a stderr message that
  names the offending key and the expected type.
- An unknown top-level key is either accepted with a warning OR
  rejected with a non-zero exit; the contract MUST NOT silently
  swallow it.
- `targets:` accepts either a CSV string or a YAML list. Both forms
  load successfully when the named targets exist.

> Note: a prior version of the schema used singular `target:`. The
> current contract is plural `targets:`. Cross-check
> `src/apm_cli/core/target_detection.py` and
> `src/apm_cli/commands/_helpers.py` before authoring a test that
> asserts on the legacy form.

## Likely failure modes

- **silent**: an unknown top-level key is dropped without log or
  warning; the user assumes their config applied.
- **uncontrolled**: a non-string value in a required string field
  raises an uncaught `AttributeError` (e.g. `value.strip()` on a
  list) and leaks a traceback.
- **uncontrolled**: a YAML alias loop or unsafe tag (e.g.
  `!!python/object`) is loaded without rejection.
- **graceful**: clear `"apm.yml is malformed: ..."` stderr with
  non-zero exit.

## Fixture recipes

```python
import pytest
from tests.chaos._harness import run_apm

@pytest.mark.chaos
def test_apm_yml_invalid_yaml(apm_yml_factory):
    project = apm_yml_factory("name: chaos\nversion: 0.0.1\ntargets: [\n")
    result = run_apm(["install"], cwd=project, timeout=20)

    assert not result.timed_out
    assert result.returncode != 0, "malformed YAML silently accepted"
    assert "Traceback" not in result.stderr
    assert "apm.yml" in result.stderr.lower()


@pytest.mark.chaos
def test_apm_yml_unknown_target(apm_yml_factory):
    project = apm_yml_factory(
        "name: chaos\nversion: 0.0.1\ntargets: [does-not-exist]\n"
    )
    result = run_apm(["install"], cwd=project, timeout=20)

    assert not result.timed_out
    assert result.returncode != 0
    assert "does-not-exist" in result.stderr or "target" in result.stderr.lower()
```

## Sample chaos inputs

- empty file (`""`)
- only whitespace (`"  \n  \n"`)
- only a YAML tag (`"---\n"`)
- top-level scalar (`"chaos"`)
- top-level list (`"- name: chaos\n  version: 0.0.1\n"`)
- duplicate keys (`"name: a\nname: b\n"`)
- non-string version (`"name: chaos\nversion: [1, 2]\n"`)
- unsafe YAML tag (`"name: !!python/object/apply:os.system [echo]\n"`)
- targets as a CSV string with whitespace (`"targets: copilot , vscode , windsurf\n"`)
- targets as an empty list (`"targets: []\n"`)
- unicode in name beyond ASCII (`"name: chaos\u2014mon\nversion: 0.0.1\n"`)
- extremely long name (1024+ chars)

## Classification mapping

| Observation | Classification |
|---|---|
| non-zero exit + `"apm.yml"` in stderr + no traceback | `graceful` |
| exit 0 + the malformed file was silently accepted | `silent` |
| traceback in stderr | `uncontrolled` |
| arbitrary code execution from YAML tag (file written outside `cwd`, network call) | `uncontrolled` |
| `timed_out=True` | `uncontrolled` |

## Anti-patterns

- Do NOT modify the project's real `apm.yml`. Always write into a
  fixture tempdir via `apm_yml_factory`.
- Do NOT assert specific error messages -- assert on stable
  substrings (`"apm.yml"`, target name, key name).
