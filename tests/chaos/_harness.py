"""Subprocess contract for chaos vector reproduction.

Single source of truth for invoking the installed ``apm`` CLI from
both the chaos-monkey agent (during discovery, inside a gh-aw runner)
and the regression-trap pytest tests it writes. Reproductions must
be bit-identical between discovery and CI, so both call ``run_apm``.

Hard rules baked into ``run_apm``:

- every call passes ``cwd`` (the agent always supplies a hermetic
  scratch tempdir; never the repo working copy);
- every call passes a SANITISED environment (see ``_sanitised_env``)
  so real PATs, ``~/.gitconfig``, ``~/.netrc`` never leak into the
  reproduction;
- every call is bounded by ``timeout`` and a ``TimeoutExpired`` is
  surfaced as a structured outcome rather than an exception (a hang
  is a classification, not a crash);
- output is always captured (text mode, UTF-8 with ``errors="replace"``
  so non-decodable bytes do not mask the real stderr).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChaosResult:
    """Captured outcome of one chaos subprocess invocation.

    All fields are FACTS (truth #2 CONTEXT EXPLICIT). The classifier
    in the chaos-monkey skill body asserts against these and only
    these; LLM-asserted failure claims are forbidden.
    """

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    elapsed_seconds: float
    argv: tuple[str, ...]
    cwd: str


def _sanitised_env(scratch_home: Path, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Build a minimal environment for the chaos subprocess.

    Starts from an empty dict, adds back only what the CLI needs to
    locate its interpreter and resolve a hermetic HOME. ``overrides``
    is applied last so a vector can deliberately set a bogus
    ``GITHUB_APM_PAT``, malformed ``XDG_CONFIG_HOME``, etc.
    """
    env: dict[str, str] = {}
    # PATH is required so ``apm`` (and any helper it shells out to)
    # is discoverable. Anything else from the host is deliberately
    # excluded.
    path = os.environ.get("PATH")
    if path:
        env["PATH"] = path

    home = scratch_home
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    # XDG dirs scoped under the scratch home so no user config leaks.
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    # Force git into a hermetic mode where global config is ignored.
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    # Locale to keep stderr strings stable across runners.
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"

    if overrides:
        env.update(overrides)
    return env


def _resolve_apm_binary() -> str:
    """Locate the ``apm`` binary the test should exercise.

    Precedence:
    1. ``APM_BINARY_PATH`` environment variable (the runner exports it
       after building from src).
    2. ``apm`` on PATH.

    Raises ``FileNotFoundError`` if neither is available, so the
    chaos suite fails loudly rather than silently skipping.
    """
    env_path = os.environ.get("APM_BINARY_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    found = shutil.which("apm")
    if found:
        return found
    raise FileNotFoundError(
        "apm CLI not found. Set APM_BINARY_PATH or install apm on PATH before running chaos tests."
    )


def run_apm(
    args: list[str],
    cwd: Path,
    env_overrides: dict[str, str] | None = None,
    timeout: float = 60.0,
    stdin: str | None = None,
) -> ChaosResult:
    """Invoke the installed ``apm`` CLI and capture the outcome.

    Parameters
    ----------
    args
        Argv tail (without the binary name). Example: ``["install"]``.
    cwd
        Working directory the subprocess will execute in. The caller
        MUST supply a hermetic scratch tempdir; never the repo
        working copy.
    env_overrides
        Vector-specific environment additions / overrides (for
        example ``{"GITHUB_APM_PAT": "invalid"}``). Real host env
        vars are not inherited.
    timeout
        Wall-clock seconds before the call is killed. A timeout is
        surfaced as ``timed_out=True`` rather than raised, because a
        hang is a valid "uncontrolled failure" classification.
    stdin
        Optional stdin payload (rare; most chaos vectors are argv- or
        config-driven).

    Returns
    -------
    ChaosResult
        Structured outcome. Use the ``returncode``, ``stdout``,
        ``stderr``, and ``timed_out`` fields to classify (see the
        chaos-vector-catalogue SKILL.md for the classification rules).
    """
    cwd = Path(cwd)
    if not cwd.exists():
        raise FileNotFoundError(f"cwd does not exist: {cwd}")

    scratch_home = cwd / "_chaos_home"
    env = _sanitised_env(scratch_home, env_overrides)
    binary = _resolve_apm_binary()
    argv = [binary, *args]

    start = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = -1
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )

    elapsed = time.monotonic() - start

    return ChaosResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        elapsed_seconds=elapsed,
        argv=tuple(argv),
        cwd=str(cwd),
    )
