# Surface: `deps_marketplace`

Chaos surface for dependency resolution, the lockfile, and the
package downloader. Exercises what happens when an `apm.yml` lists
something the downloader cannot or should not fetch. Load this file
only when the chosen vector targets dependency resolution.

> NETWORK: chaos tests on this surface MUST run offline. Use
> `local_pkg_repo` to produce `file://` URLs the downloader can
> reach without leaving the runner. No external GitHub URLs, no
> ghcr.io references, no `*.azure.com`.

## Known invariants

- A dependency entry whose URL points at a non-existent local repo
  (`file:///nonexistent/path`) exits non-zero with a stderr
  message naming the URL and the resolution failure mode.
- A dependency entry whose target repo exists but lacks an
  `apm.yml` exits non-zero with a clear "not an APM package"
  stderr.
- A dependency entry requesting a non-existent git ref (e.g.
  `@nope`) exits non-zero with a clear ref-not-found stderr.
- The lockfile produced by `apm install` is byte-identical across
  re-runs with the same inputs (deterministic).
- The lockfile name is `apm.lock.yaml`; the file is YAML and
  parseable on every supported platform.

## Likely failure modes

- **silent**: dependency resolution returns "success" but no files
  were copied / no lockfile entry written.
- **silent**: a partial install leaves the lockfile in an
  inconsistent state without flagging it.
- **uncontrolled**: a non-existent git ref produces a
  `subprocess.CalledProcessError` traceback rather than a clean
  error message.
- **uncontrolled**: the downloader hangs when the URL is a
  malformed `file://` (timeout fires).
- **graceful**: clean "dependency <name> not found: ..." stderr.

## Fixture recipes

```python
import pytest
from pathlib import Path
from tests.chaos._harness import run_apm

@pytest.mark.chaos
def test_deps_missing_apm_yml_in_dep(apm_project, local_pkg_repo):
    bad_repo_url = local_pkg_repo(name="not-an-apm-pkg", include_apm_yml=False)
    (apm_project / "apm.yml").write_text(
        f"name: chaos\nversion: 0.0.1\ntargets: [copilot]\n"
        f"dependencies:\n  apm:\n    - {bad_repo_url}\n",
        encoding="utf-8",
    )
    result = run_apm(["install"], cwd=apm_project, timeout=60)

    assert not result.timed_out
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "apm.yml" in result.stderr.lower() or "package" in result.stderr.lower()


@pytest.mark.chaos
def test_deps_nonexistent_ref(apm_project, local_pkg_repo):
    repo_url = local_pkg_repo(name="real-pkg")
    (apm_project / "apm.yml").write_text(
        f"name: chaos\nversion: 0.0.1\ntargets: [copilot]\n"
        f"dependencies:\n  apm:\n    - {repo_url}#nope\n",
        encoding="utf-8",
    )
    result = run_apm(["install"], cwd=apm_project, timeout=60)

    assert not result.timed_out
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
```

## Sample chaos inputs

- dependency URL pointing at `file:///nonexistent/path`
- dependency URL with malformed scheme (`htp://...`, `:::`, etc.)
- dependency URL with embedded credentials (`https://user:pass@...`)
- dependency name colliding with an installed package
- dependency listed twice (duplicate)
- dependency name = empty string
- lockfile pre-corrupted to invalid YAML before `apm install` runs
- lockfile present but read-only (`chmod 0444`)
- lockfile referring to a dep no longer in `apm.yml`
- a circular file:// dep (`a` depends on `b`, `b` depends on `a`)

## Classification mapping

| Observation | Classification |
|---|---|
| non-zero exit + named cause + no traceback | `graceful` |
| exit 0 + nothing actually installed (no files under `.apm/` in `cwd`) | `silent` |
| traceback in stderr | `uncontrolled` |
| `timed_out=True` | `uncontrolled` |
| files written outside `cwd` | `uncontrolled` |

## Anti-patterns

- NEVER point at a real network URL. The chaos suite is offline.
- Do NOT delete the project lockfile in the real repo; mutate only
  inside the fixture tempdir.
- Do NOT assert deterministic-lockfile byte equality across
  vectors that intentionally fail -- the lockfile may not be
  produced.
