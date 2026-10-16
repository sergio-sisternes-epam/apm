#!/usr/bin/env python3
"""Fetch and filter triage candidates; never write GitHub or authorize work.

Reads already-fetched records (`--records-json`) or lists them via `gh`.
Prints the issue-shaped batch JSON that `triage_state.py` consumes.
`--kind pr` uses the same schema; `number` is the pull request number.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import runpy
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

plan_batch = runpy.run_path(str(Path(__file__).resolve().with_name("triage_state.py")))[
    "plan_batch"
]

PAGE_SIZE = 100
URL_RE = re.compile(r"https?://\S+", re.ASCII)
SCOPE_RECORD_KEYS = ("has_scope_record", "scope_record")
IDENTICAL_RUN_RE = re.compile(r"(.)\1{49}")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE_MARKUP_RE = re.compile(
    r"```.*?```|`[^`]+`|!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\([^)]*\)",
    re.DOTALL,
)
LINE_MARKUP_RE = re.compile(r"^[#>*].*$", re.MULTILINE)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s.*$", re.MULTILINE)
BOLD_HEADING_RE = re.compile(r"^\s*\*\*[^*]+\*\*\s*$", re.MULTILINE)
PLACEHOLDER_RE = re.compile(
    r"a clear and concise description.*$|"
    r"steps to reproduce the behavior:.*$|"
    r"please complete the following information.*$|"
    r"if applicable, add any error logs.*$|"
    r"add any other context.*$|"
    r"reporting and investigating a bug need no permission.*$",
    re.IGNORECASE | re.MULTILINE,
)


def scope_marker(contract: dict[str, Any] | None = None) -> str:
    """Return the maintainer scope-record marker from the label contract."""
    loaded = contract if contract is not None else _load_contract()
    return str(loaded["processing"]["scope_record_marker"])


def comments_have_scope_record(comments: Any, marker: str) -> bool:
    """True when any comment body contains the maintainer scope-record marker."""
    if isinstance(comments, str):
        return marker in comments
    if not isinstance(comments, list):
        return False
    for item in comments:
        if isinstance(item, str) and marker in item:
            return True
        if isinstance(item, dict):
            body = item.get("body")
            if isinstance(body, str) and marker in body:
                return True
    return False


def resolve_scope_record(raw: dict[str, Any], marker: str) -> bool:
    """True when prefetched comments or an explicit flag show a scope record."""
    if comments_have_scope_record(raw.get("comments"), marker):
        return True
    for key in SCOPE_RECORD_KEYS:
        value = raw.get(key)
        if value is True or value == "true":
            return True
    return False


def sweep_exclude_labels(contract: dict[str, Any]) -> list[str]:
    """Labels a sweep search must exclude before download."""
    processing = contract["processing"]
    names = [str(name) for name in processing["read_reviewed"]]
    for name in processing["sweep_exclude_labels"]:
        text = str(name)
        if text not in names:
            names.append(text)
    return names


def decided_skip_reason(record: dict[str, Any], contract: dict[str, Any]) -> str | None:
    """Return a sweep skip token for a maintainer decision, or None."""
    labels = set(record.get("labels") or [])
    for name in contract["processing"]["sweep_exclude_labels"]:
        if str(name) not in labels:
            continue
        if name == "status/accepted":
            return "accepted"
        if name == "status/declined":
            return "declined"
        return "decided"
    if record.get("has_scope_record") is True:
        return "scope-record"
    return None


def _alnum_count(text: str) -> int:
    """Count ASCII alphanumeric characters."""
    return sum(char.isalnum() for char in text)


def strip_markup(body: str) -> str:
    """Remove comments, fences, links, and heading markers for body heuristics."""
    text = HTML_COMMENT_RE.sub(" ", body)
    text = FENCE_MARKUP_RE.sub(" ", text)
    text = LINE_MARKUP_RE.sub(" ", text)
    return text


def is_empty_body(body: str | None) -> bool:
    """True when the body is missing or only whitespace."""
    return body is None or not body.strip()


def is_template_only(body: str) -> bool:
    """True when the body is issue-form scaffolding without reporter content."""
    if is_empty_body(body):
        return False
    has_scaffold = bool(
        HTML_COMMENT_RE.search(body)
        or HEADING_RE.search(body)
        or BOLD_HEADING_RE.search(body)
        or PLACEHOLDER_RE.search(body)
    )
    if not has_scaffold:
        return False
    text = HTML_COMMENT_RE.sub(" ", body)
    text = HEADING_RE.sub(" ", text)
    text = BOLD_HEADING_RE.sub(" ", text)
    text = PLACEHOLDER_RE.sub(" ", text)
    return _alnum_count(text) < 20


def is_spam_shaped(body: str) -> bool:
    """True when the body matches the published spam heuristics."""
    if is_empty_body(body):
        return False
    if IDENTICAL_RUN_RE.search(body):
        return True
    total = len(body)
    url_chars = sum(len(match.group(0)) for match in URL_RE.finditer(body))
    if total and url_chars / total > 0.8:
        return True
    if total >= 3:
        best = 0
        for index in range(total - 2):
            token = body[index : index + 3]
            best = max(best, body.count(token))
        if (best * 3) / total > 0.7:
            return True
    return _alnum_count(strip_markup(body)) < 20


def skip_reason(record: dict[str, Any], mode: str) -> str | None:
    """Return a skip token, or None when state/body filters pass.

    Bot-authored issues and PRs stay eligible so automations are
    triaged like any other contribution.

    Completed-advice markers stay eligible; `triage_state.plan_batch` owns
    that sweep skip plus the per-author quota. Sweep also skips maintainer
    decisions (`status/accepted`, `status/declined`, and scope records).
    Explicit requests keep those items.
    """
    if record["state"] != "open":
        return "closed" if not record.get("merged") else "merged"
    if record.get("merged"):
        return "merged"
    if record.get("locked"):
        return "locked"
    body = record.get("body")
    if not isinstance(body, str) or is_empty_body(body):
        return "empty"
    if is_template_only(body):
        return "template-only"
    if mode == "sweep" and record.get("draft"):
        return "draft"
    if mode == "sweep" and is_spam_shaped(body):
        return "spam"
    if mode == "sweep":
        return decided_skip_reason(record, _load_contract())
    return None


def normalize_record(raw: dict[str, Any], kind: str) -> dict[str, Any]:
    """Map a GitHub REST issue or pull item into the planner's record shape."""
    user = raw.get("user") or raw.get("author") or {}
    if isinstance(user, str):
        login, author_type = user, "User"
    else:
        login = str(user.get("login") or user.get("name") or "")
        author_type = str(user.get("type") or user.get("__typename") or "User")
    labels_raw = raw.get("labels") or []
    labels = []
    for label in labels_raw:
        if isinstance(label, str):
            labels.append(label)
        elif isinstance(label, dict) and label.get("name"):
            labels.append(str(label["name"]))
    state = str(raw.get("state") or "open").lower()
    merged = bool(raw.get("merged") or raw.get("merged_at") or state == "merged")
    if merged:
        state = "closed"
    marker = scope_marker()
    return {
        "number": int(raw["number"]),
        "author": login,
        "author_type": author_type,
        "labels": labels,
        "body": raw.get("body"),
        "state": "open" if state == "open" else "closed",
        "locked": bool(raw.get("locked")),
        "draft": bool(raw.get("draft") or raw.get("isDraft")),
        "merged": merged,
        "kind": kind,
        "has_scope_record": resolve_scope_record(raw, marker),
    }


def build_batch(
    records: Sequence[dict[str, Any]],
    mode: str,
    repository_labels: list[str],
) -> dict[str, Any]:
    """Annotate eligibility and emit `triage_state.py` stdin JSON."""
    if mode not in {"sweep", "label-event", "dispatch"}:
        raise ValueError("mode must be sweep, label-event, or dispatch")
    issues: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for record in records:
        reason = skip_reason(record, mode)
        item = {
            "number": record["number"],
            "author": record["author"],
            "labels": list(record["labels"]),
            "eligible": reason is None,
            "has_scope_record": record.get("has_scope_record") is True,
        }
        issues.append(item)
        if reason is not None:
            skipped.append({"number": record["number"], "reason": reason})
    return {
        "mode": mode,
        "repository_labels": list(repository_labels),
        "issues": issues,
        "skipped": skipped,
    }


def attach_scope_records_for_sweep(
    records: list[dict[str, Any]],
    repo: str,
    repository_labels: list[str],
    contract: dict[str, Any],
    runner: Callable[[list[str]], Any] | None = None,
) -> None:
    """Fetch issue comments until the sweep batch is full or input ends.

    Labels already on each record skip accepted and declined items. Scope
    records live in comments, so they are collected here before planning
    rather than discovered while advising.
    """
    call = runner or _gh_json
    marker = str(contract["processing"]["scope_record_marker"])
    considered: list[dict[str, Any]] = []
    for record in records:
        tentative = dict(record)
        tentative["has_scope_record"] = False
        if skip_reason(tentative, "sweep") is not None:
            record["has_scope_record"] = record.get("has_scope_record") is True
            considered.append(record)
            continue
        path = f"/repos/{repo}/issues/{record['number']}/comments?per_page={PAGE_SIZE}"
        raw = call(["api", "--paginate", path])
        if not isinstance(raw, list):
            raise ValueError("GitHub comments response must be a JSON array")
        record["has_scope_record"] = comments_have_scope_record(raw, marker)
        considered.append(record)
        batch = build_batch(considered, "sweep", repository_labels)
        if plan_batch(batch, contract)["batch_full"]:
            break


def _trusted_gh() -> str:
    """Resolve gh via get_gh_executable, never a project-controlled binary."""
    src_root: Path | None = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "apm_cli" / "utils" / "git_env.py").is_file():
            src_root = parent / "src"
            break
    if src_root is not None and str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    try:
        from apm_cli.utils.git_env import get_gh_executable
    except ImportError as error:
        raise ValueError("gh is not runnable") from error
    try:
        return get_gh_executable()
    except FileNotFoundError as error:
        raise ValueError("gh is not runnable") from error


def _gh_json(args: list[str]) -> Any:
    """Run `gh` and parse JSON; raise ValueError on failure."""
    gh = _trusted_gh()
    try:
        completed = subprocess.run(  # noqa: S603
            [gh, *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ValueError(f"gh is not runnable: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "gh failed").strip()
        raise ValueError(detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"gh returned invalid JSON: {error}") from error


def _search_items(raw: Any) -> list[Any]:
    """Flatten a GitHub issue-search payload into a list of items."""
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return list(raw["items"])
    if isinstance(raw, list):
        items: list[Any] = []
        for page in raw:
            if isinstance(page, dict) and isinstance(page.get("items"), list):
                items.extend(page["items"])
            elif isinstance(page, dict) and "number" in page:
                items.append(page)
            else:
                raise ValueError("GitHub search response must include items")
        return items
    raise ValueError("GitHub search response must include items")


def list_pages(
    kind: str,
    repo: str,
    runner: Callable[[list[str]], Any] | None = None,
    exclude_labels: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Paginate open issues or pulls oldest-first via `gh api`.

    Sweep passes reviewed and decided labels so already-advised and
    already-decided items are excluded at GitHub and never downloaded.
    """
    call = runner or _gh_json
    if exclude_labels:
        kind_token = "is:issue" if kind == "issue" else "is:pr"
        negatives = " ".join(f'-label:"{name}"' for name in exclude_labels)
        search = f"repo:{repo} {kind_token} is:open {negatives}"
        path = (
            f"/search/issues?q={quote(search, safe='')}&sort=created&order=asc&per_page={PAGE_SIZE}"
        )
        raw = call(["api", "--paginate", path])
        items = _search_items(raw)
    else:
        rest_path = "issues" if kind == "issue" else "pulls"
        query = (
            f"/repos/{repo}/{rest_path}?state=open&sort=created&direction=asc&per_page={PAGE_SIZE}"
        )
        raw = call(["api", "--paginate", query])
        if not isinstance(raw, list):
            raise ValueError("GitHub list response must be a JSON array")
        items = raw
    records = []
    for item in items:
        if not isinstance(item, dict) or "number" not in item:
            raise ValueError("GitHub list items must include number")
        if kind == "issue" and item.get("pull_request"):
            continue
        records.append(normalize_record(item, kind))
    return records


def get_one(
    kind: str,
    repo: str,
    number: int,
    runner: Callable[[list[str]], Any] | None = None,
) -> dict[str, Any]:
    """Fetch one issue or pull by number."""
    call = runner or _gh_json
    path = "issues" if kind == "issue" else "pulls"
    raw = call(["api", f"/repos/{repo}/{path}/{number}"])
    if not isinstance(raw, dict) or "number" not in raw:
        raise ValueError("GitHub item response must include number")
    if kind == "issue" and raw.get("pull_request"):
        raise ValueError(f"#{number} is a pull request; use --kind pr")
    return normalize_record(raw, kind)


def list_repo_labels(
    repo: str,
    runner: Callable[[list[str]], Any] | None = None,
) -> list[str]:
    """Return repository label names."""
    call = runner or _gh_json
    raw = call(["api", "--paginate", f"/repos/{repo}/labels?per_page={PAGE_SIZE}"])
    if not isinstance(raw, list):
        raise ValueError("GitHub labels response must be a JSON array")
    names = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return names


def accumulate_for_plan(
    records: Sequence[dict[str, Any]],
    mode: str,
    repository_labels: list[str],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Keep oldest-first records until `plan_batch` is full or input ends."""
    chosen: list[dict[str, Any]] = []
    last_batch: dict[str, Any] | None = None
    for record in records:
        chosen.append(record)
        last_batch = build_batch(chosen, mode, repository_labels)
        if mode == "sweep" and plan_batch(last_batch, contract)["batch_full"]:
            break
    if last_batch is None:
        last_batch = build_batch([], mode, repository_labels)
    return last_batch


def _load_contract() -> dict[str, Any]:
    """Read the label contract next to this script."""
    path = Path(__file__).resolve().parent.parent / "assets/label-contract.json"
    return json.loads(path.read_text(encoding="ascii"))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: filter records or fetch them, then print a planner batch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("issue", "pr"), required=True)
    parser.add_argument("--mode", choices=("sweep", "label-event", "dispatch"), required=True)
    parser.add_argument("--repo", default="")
    parser.add_argument("--number", type=int, action="append", dest="numbers")
    parser.add_argument(
        "--records-json",
        default="",
        help="Path or '-' for a JSON array of REST-shaped items (skips gh list)",
    )
    parser.add_argument(
        "--labels-json",
        default="",
        help="Path or '-' for a JSON array of label names (skips gh labels)",
    )
    args = parser.parse_args(argv)
    try:
        if args.mode != "sweep" and not (args.numbers or args.records_json):
            raise ValueError("Explicit requests require --number or --records-json")
        if args.mode != "sweep" and args.numbers and len(args.numbers) != 1:
            raise ValueError("Explicit requests require exactly one --number")
        contract = _load_contract()
        records: list[dict[str, Any]]
        repo = args.repo
        if args.records_json:
            payload = (
                sys.stdin.read()
                if args.records_json == "-"
                else Path(args.records_json).read_text(encoding="utf-8")
            )
            raw_items = json.loads(payload)
            if not isinstance(raw_items, list):
                raise ValueError("--records-json must be a JSON array")
            records = [normalize_record(item, args.kind) for item in raw_items]
        elif args.numbers:
            repo = args.repo or _default_repo()
            records = [get_one(args.kind, repo, args.numbers[0])]
        else:
            repo = args.repo or _default_repo()
            exclude = sweep_exclude_labels(contract) if args.mode == "sweep" else []
            records = list_pages(args.kind, repo, exclude_labels=exclude)
        if args.labels_json:
            label_payload = (
                sys.stdin.read()
                if args.labels_json == "-"
                else Path(args.labels_json).read_text(encoding="utf-8")
            )
            repository_labels = json.loads(label_payload)
            if not isinstance(repository_labels, list):
                raise ValueError("--labels-json must be a JSON array")
            repository_labels = [str(name) for name in repository_labels]
        elif args.records_json:
            repository_labels = [contract["processing"]["active_write_reviewed"]]
        else:
            repository_labels = list_repo_labels(repo or _default_repo())
        if args.mode == "sweep" and not args.records_json:
            attach_scope_records_for_sweep(
                records,
                repo or _default_repo(),
                repository_labels,
                contract,
            )
        batch = accumulate_for_plan(records, args.mode, repository_labels, contract)
        if args.mode != "sweep" and len(batch["issues"]) != 1:
            raise ValueError("Explicit requests require exactly one issue")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"[x] Triage queue fetch failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(batch, sort_keys=True))
    return 0


def _default_repo() -> str:
    """Resolve owner/name from GITHUB_REPOSITORY or `gh`."""
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env:
        return env
    data = _gh_json(["repo", "view", "--json", "nameWithOwner"])
    if not isinstance(data, dict) or not data.get("nameWithOwner"):
        raise ValueError("Unable to resolve --repo")
    return str(data["nameWithOwner"])


if __name__ == "__main__":
    sys.exit(main())
