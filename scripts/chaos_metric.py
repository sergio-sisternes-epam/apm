#!/usr/bin/env python3
"""Emit the chaos-monkey metric for autoloop.

Counts regression-trap tests under ``tests/chaos/`` carrying the
``chaos`` pytest marker. The count is the only metric autoloop tracks
for the ``chaos-monkey`` program; it is monotonic-upward and serves
as the keep-iteration ratchet.

Usage:

    python scripts/chaos_metric.py [--tests-dir tests/chaos]

Stdout: one JSON object on a single line, e.g. ``{"hardened_findings": 7}``.
Stderr: diagnostics only (count of files scanned, pytest errors).
Exit code: 0 on success; non-zero on a collection error.

The script is non-interactive (no prompts, no TTY required) so it is
safe to run from autoloop's evaluation step.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _collect_via_pytest(tests_dir: Path) -> int:
    """Use ``pytest --collect-only -m chaos`` to count tests.

    Preferred path. Honours conftest, parametrisation, and skip
    markers exactly the way the test runner will. Returns -1 on any
    pytest invocation error so the caller can fall back.
    """
    try:
        completed = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "pytest",
                str(tests_dir),
                "-m",
                "chaos",
                "--collect-only",
                "-q",
                "--no-header",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=str(REPO_ROOT),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"pytest collection failed: {exc}", file=sys.stderr)
        return -1

    if completed.returncode not in (0, 5):
        # 5 = "no tests collected" which is a valid zero count, not
        # an error.
        print(
            f"pytest exited with code {completed.returncode}; stderr:\n{completed.stderr}",
            file=sys.stderr,
        )
        return -1

    # ``pytest --collect-only -q`` prints one test id per line plus a
    # trailing summary like "7 tests collected in 0.12s". Parse the
    # summary first; fall back to line counting.
    summary_match = re.search(r"(\d+)\s+tests?\s+collected", completed.stdout)
    if summary_match:
        return int(summary_match.group(1))

    return sum(
        1
        for line in completed.stdout.splitlines()
        if line.strip() and "::" in line and not line.startswith("=")
    )


def _collect_via_filesystem(tests_dir: Path) -> int:
    """Fallback: grep ``@pytest.mark.chaos`` decorators directly.

    Used only when pytest is unavailable (e.g. a barebones runner
    without the dev extras installed). Reports a CONSERVATIVE count
    that ignores parametrisation, but never lies upward.
    """
    if not tests_dir.exists():
        return 0
    count = 0
    pattern = re.compile(r"^\s*@pytest\.mark\.chaos\b")
    for path in tests_dir.rglob("test_*.py"):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"skipped {path}: {exc}", file=sys.stderr)
            continue
        count += sum(1 for line in content.splitlines() if pattern.match(line))
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit hardened_findings count as JSON for autoloop.",
    )
    parser.add_argument(
        "--tests-dir",
        default="tests/chaos",
        help="Directory containing chaos regression-trap tests (default: tests/chaos).",
    )
    args = parser.parse_args(argv)

    tests_dir = (REPO_ROOT / args.tests_dir).resolve()
    if not tests_dir.exists():
        print(f"tests directory not found: {tests_dir}", file=sys.stderr)
        json.dump({"hardened_findings": 0}, sys.stdout)
        sys.stdout.write("\n")
        return 0

    count = _collect_via_pytest(tests_dir)
    if count < 0:
        print("falling back to filesystem scan", file=sys.stderr)
        count = _collect_via_filesystem(tests_dir)

    json.dump({"hardened_findings": count}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
