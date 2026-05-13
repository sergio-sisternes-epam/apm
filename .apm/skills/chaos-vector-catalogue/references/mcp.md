# Surface: `mcp`

Chaos surface for MCP (Model Context Protocol) server config
generation and validation. Exercises what `apm` writes to / reads
from the integrator-specific MCP config path (e.g. `.vscode/mcp.json`
for the Copilot target, `.mcp.json` for the Claude target). Load
this file only when the chosen vector targets MCP config handling.

## Known invariants

- A malformed MCP config (invalid JSON) exits non-zero with a stderr
  message naming the file path and the parse error. MUST NOT print
  a Python traceback.
- A config containing a server with a non-recognised hostname is
  either rejected or has its credential injection disabled. The
  recognised GitHub MCP hostnames are `github.com`, `*.ghe.com`,
  `*.github.com`, `*.githubcopilot.com` (see
  `src/apm_cli/adapters/client/copilot.py:1234-1243` for the live
  list).
- An MCP server entry with a missing required field exits non-zero
  with a clear stderr identifying the missing field.
- An MCP server URL with an obviously-fake token in the headers
  MUST NOT have that token echoed back in stderr or logs.

## Likely failure modes

- **silent**: a malformed MCP entry is dropped from the rendered
  config without a warning; the user thinks their server was
  registered.
- **silent**: an unknown hostname is allowed to receive credential
  injection (the security boundary leaks).
- **uncontrolled**: a deeply nested JSON object trips a recursion
  limit and crashes with a traceback.
- **graceful**: clear "MCP config is malformed: ..." stderr.

## Fixture recipes

```python
import pytest
from tests.chaos._harness import run_apm

@pytest.mark.chaos
def test_mcp_invalid_json(mcp_config):
    project = mcp_config("{ not valid json", target="copilot")
    result = run_apm(["install"], cwd=project, timeout=30)

    assert not result.timed_out
    assert "Traceback" not in result.stderr


@pytest.mark.chaos
def test_mcp_unknown_hostname_does_not_leak_token(mcp_config):
    fake_token = "ghp_obviously-fake-token-xxxxxxxxxxxxxxxxxxxx"
    project = mcp_config(
        '{"servers": {"evil": {"url": "https://evil.example.com/mcp", '
        f'"headers": {{"Authorization": "Bearer {fake_token}"}}}}}}',
        target="copilot",
    )
    result = run_apm(["install"], cwd=project, timeout=30)

    assert fake_token not in result.stdout
    assert fake_token not in result.stderr
```

## Sample chaos inputs

- invalid JSON (truncated, missing braces, etc.)
- valid JSON but wrong top-level type (a list where an object is
  expected)
- a server entry with a hostname that is a subdomain-trick on a
  recognised host (`github.com.evil.example`)
- a server entry with `url: ""` (empty)
- a server entry with `url: null`
- a server entry whose `command` references a non-existent binary
- a config with 10 000 server entries (stress)
- a config whose JSON contains a 4 MB string in one value
- duplicate server names with different URLs
- mixed-case hostname matching (`GITHUB.COM`)

## Classification mapping

| Observation | Classification |
|---|---|
| non-zero exit + named cause + no traceback | `graceful` |
| exit 0 with explicit warning naming the dropped entry | `graceful` |
| exit 0 with no warning when an entry was dropped | `silent` |
| token substring appears in stdout/stderr | `uncontrolled` |
| credentials injected against an unrecognised host | `uncontrolled` |
| traceback in stderr | `uncontrolled` |
| `timed_out=True` | `uncontrolled` |

## Anti-patterns

- NEVER use a real PAT in an MCP config -- the value will be
  written into a committed test file. Use the obvious fake-token
  pattern above.
- Do NOT assert specific JSON schema error strings; assert on
  user-observable contract (exit code, no leak, file path named).
- Do NOT mutate the real repo's MCP config; always go through the
  `mcp_config` fixture.
