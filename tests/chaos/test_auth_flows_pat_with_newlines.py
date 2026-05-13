"""Regression trap for: auth_flows / pat_with_newlines.

Observed at: 2026-05-13.
Classification: uncontrolled (credential leak) + silent (exit 0 on failure).
Evidence: returncode=0, timed_out=False, stdout contains the post-newline
portions of the multi-line PAT verbatim; stderr is empty.

Discovery vector: ``apm install`` with ``GITHUB_APM_PAT`` containing
embedded ``\\n`` characters (classic HTTP header injection shape).
git rejects the URL with ``credential url cannot be parsed`` and echoes
the unredacted post-newline portion of the password into its own stderr,
which apm bubbles up onto its stdout. Pre-newline portion is ``***``-
redacted; post-newline portion is NOT.

This trap locks in the CURRENT behaviour. When either of the underlying
issues is fixed (returncode flipped to non-zero OR post-newline portions
redacted), this test will fail; that is the signal to update the trap
prose and assertions to the new (better) contract.

Recommended hardening (NOT applied here per chaos-monkey constraint 2):
  1. Sanitise ``GITHUB_APM_PAT`` at resolver intake: reject values
     containing control characters with a clear stderr message; do NOT
     pass them to ``git``.
  2. Aggregate per-package failures into the install command exit code
     so ``returncode == 0`` cannot coexist with ``Installation failed``.
"""

from __future__ import annotations

import pytest

from tests.chaos._harness import run_apm


@pytest.mark.chaos
def test_auth_flows_pat_with_newlines_currently_leaks_and_silently_succeeds(
    apm_project,
    bogus_pat_env,
):
    project = apm_project

    # Multi-line PAT: first line looks valid, subsequent lines carry
    # attacker-controlled markers we use to detect leakage. Each marker
    # is a CONTIGUOUS, UNIQUE TOKEN (no spaces) so APM's console
    # line-wrapping cannot split it across multiple lines and obscure
    # the leak.
    fake_token_first_line = "ghp_obviously-fake-token-with-newline-INJ"
    leaked_marker_a = "pwned-chaos-marker-aaa001-unique"
    leaked_marker_b = "trail-chaos-marker-bbb002-unique"
    fake_token = (
        f"{fake_token_first_line}\nX-Injected: {leaked_marker_a}\nX-Trail: {leaked_marker_b}"
    )

    # apm.yml overridden to depend on a non-existent github-shaped repo so
    # the auth resolver path runs (a file:// dependency would be rejected
    # by the dependency-syntax validator before auth is consulted).
    (project / "apm.yml").write_text(
        "name: chaos\n"
        "version: 0.0.1\n"
        "targets: [copilot]\n"
        "dependencies:\n"
        "  apm:\n"
        "    - this-org-does-not-exist-xyz/this-repo-does-not-exist-xyz\n",
        encoding="utf-8",
    )
    env = bogus_pat_env(value=fake_token, host="github")

    result = run_apm(["install"], cwd=project, env_overrides=env, timeout=30)

    assert not result.timed_out, "regression: install now hangs on newline-poisoned PAT"
    assert "Traceback" not in result.stderr, (
        "regression: chaos vector now produces a Python traceback (uncontrolled)"
    )

    combined = result.stdout + result.stderr

    # CURRENT BUG #1 (silent): exit code 0 while user-visible output
    # reports failure. A future fix flipping this to non-zero is the
    # desired outcome and SHOULD break this assertion.
    assert result.returncode == 0, (
        "BEHAVIOUR CHANGE: returncode is no longer 0. If a fix landed that "
        "propagates per-package install failures into the process exit "
        "code, update this trap to assert result.returncode != 0."
    )
    assert "Installation failed" in combined, (
        "discovery invariant: stdout no longer reports 'Installation failed'"
    )

    # CURRENT BUG #2 (uncontrolled / credential leak): the post-newline
    # portions of the PAT appear verbatim in captured output. A future
    # redaction fix is the desired outcome and SHOULD break these
    # assertions.
    assert leaked_marker_a in combined, (
        "BEHAVIOUR CHANGE: post-newline portion of GITHUB_APM_PAT no "
        "longer leaks. If a redaction fix landed, flip this assertion to "
        "'leaked_marker_a not in combined' and assert the same for "
        "leaked_marker_b. Verify the first-line redaction is still in place."
    )
    assert leaked_marker_b in combined, (
        "BEHAVIOUR CHANGE: trailing newline portion of GITHUB_APM_PAT no "
        "longer leaks. See companion assertion above."
    )

    # Invariant that MUST hold regardless of fix direction: the first
    # line of the PAT is and remains redacted. If this ever flips, the
    # leak surface has widened.
    assert fake_token_first_line not in combined, (
        "REGRESSION: first-line redaction of GITHUB_APM_PAT has broken; "
        "the full token prefix now appears in captured output."
    )
