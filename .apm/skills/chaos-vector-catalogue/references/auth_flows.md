# Surface: `auth_flows`

Chaos surface for credential resolution. Exercises `AuthResolver`,
the env-var strategies (`GITHUB_APM_PAT`, `ADO_APM_PAT`), and any
fallback chain that runs before a network call is attempted. Load
this file only when the chosen vector targets auth.

> SECURITY: chaos tests on this surface MUST NEVER use a real PAT.
> The `bogus_pat_env` fixture only emits known-invalid values. Real
> tokens are never written into a chaos fixture, never logged, and
> never committed.

## Known invariants

- An invalid `GITHUB_APM_PAT` value (string but not a real token)
  produces a clear stderr message naming GitHub auth and an exit
  code != 0 on any network-touching subcommand. MUST NOT silently
  fall back to anonymous access without a warning.
- An empty `GITHUB_APM_PAT` (set to `""`) is treated as "no token"
  and the resolver falls through to the next strategy; the user is
  not lied to about anonymous mode.
- A `GITHUB_APM_PAT` for a different host (e.g. github.com value
  used against a `*.ghe.com` dependency) is either rejected by the
  remote (graceful) or the resolver explicitly refuses to send it
  to the wrong host.
- A wrong-host token MUST NOT leak via stdout/stderr/logs (the
  resolver must redact). A chaos test asserts the literal token
  substring does NOT appear in captured output.

## Likely failure modes

- **silent**: an invalid token is accepted at config time and the
  network call later fails with a confusing message that does not
  mention auth.
- **uncontrolled**: a token leaks into stderr or logs (the chaos
  test asserts a known-fake token string does NOT appear in
  captured output).
- **uncontrolled**: a missing token causes a `KeyError` rather than
  a friendly resolver miss.
- **graceful**: clear "GitHub authentication failed: ..." stderr +
  non-zero exit.

## Fixture recipes

Use `bogus_pat_env` together with another fixture that drives a
flow which actually consults credentials. Pure `apm --version` does
not exercise the resolver, so combine with `local_pkg_repo` so a
dependency-resolution path runs.

```python
import pytest
from tests.chaos._harness import run_apm

@pytest.mark.chaos
def test_auth_bogus_github_pat_does_not_leak(
    apm_project, bogus_pat_env, local_pkg_repo
):
    fake_token = "ghp_obviously-fake-token-xxxxxxxxxxxxxxxxxxxx"
    env = bogus_pat_env(value=fake_token, host="github")
    repo_url = local_pkg_repo(name="auth-fake")
    # Rewrite the project to depend on a remote-looking name; we are
    # exercising the resolver path that selects credentials before
    # dispatching to a downloader.
    (apm_project / "apm.yml").write_text(
        f"name: chaos\nversion: 0.0.1\ntargets: [copilot]\n"
        f"dependencies:\n  apm:\n    - {repo_url}\n",
        encoding="utf-8",
    )
    result = run_apm(["install"], cwd=apm_project, env_overrides=env, timeout=30)

    # The bogus token MUST NOT appear in captured output.
    assert fake_token not in result.stdout
    assert fake_token not in result.stderr
```

## Sample chaos inputs

- empty token (`GITHUB_APM_PAT=""`)
- token with leading/trailing whitespace
- token containing newlines
- token of valid length but invalid prefix (`xxx_...`)
- token with non-ASCII (`GITHUB_APM_PAT="ghp_\u2014xxxx"`)
- both `GITHUB_APM_PAT` AND `ADO_APM_PAT` set (resolver should
  pick host-appropriately)
- `ADO_APM_PAT` set when the dependency is on github.com (should
  not be sent)

## Classification mapping

| Observation | Classification |
|---|---|
| non-zero exit + stderr mentions authentication + no token leak | `graceful` |
| token substring appears in stdout/stderr | `uncontrolled` |
| exit 0 but the install obviously did not succeed | `silent` |
| traceback in stderr | `uncontrolled` |

## Anti-patterns

- NEVER use a real token, even temporarily. The test will be
  committed and the value will leak.
- Do NOT assert on token-prefix-validation logic; assert on the
  user-observable contract (exit code, error message, NO leak).
- Do NOT cache the resolver result across iterations; each run
  must build a fresh environment via `bogus_pat_env`.
