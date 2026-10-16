#!/usr/bin/env python3
"""Plan advisory metadata from JSON on stdin; never call GitHub or authorize work."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def plan_batch(data: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Select from accumulated oldest-first pages and plan only permitted labels.

    Input issues have number, author, labels (names), eligible (the caller's
    body/state filter), optional has_scope_record, and optional proposed_labels.
    Sweep skips completed-advice markers, status/accepted, status/declined,
    scope records, and a third issue from the same author. Explicit requests
    ignore those sweep skips, but never eligibility or label-availability checks.
    The sweep cap is contract processing.sweep_cap (3 to 5).
    """
    mode = data["mode"]
    if mode not in {"sweep", "label-event", "dispatch"}:
        raise ValueError("mode must be sweep, label-event, or dispatch")
    processing = contract["processing"]
    marker = processing["active_write_reviewed"]
    repository_labels = set(data["repository_labels"])
    if marker not in repository_labels:
        raise ValueError(f"Active processing label {marker} is unavailable; no labels created")
    if mode != "sweep" and len(data["issues"]) != 1:
        raise ValueError("Explicit requests require exactly one issue")

    completed = set(processing["read_reviewed"])
    decided = {str(name) for name in processing["sweep_exclude_labels"]}
    sweep_cap = processing["sweep_cap"]
    if type(sweep_cap) is not int or sweep_cap < 3 or sweep_cap > 5:
        raise ValueError("Sweep cap must be an integer from 3 to 5")
    allowed = set(contract["classification_labels"]) & repository_labels
    aliases = contract["legacy_read_aliases"]
    selected = []
    per_author: dict[str, int] = {}
    seen: set[int] = set()
    for issue in data["issues"]:
        number = issue["number"]
        if type(number) is not int or number <= 0:
            raise ValueError("Issue number must be a positive integer")
        if number in seen:
            continue
        seen.add(number)
        existing = set(issue["labels"])
        if issue["eligible"] is not True or (mode == "sweep" and existing & completed):
            continue
        if mode == "sweep" and (existing & decided or issue.get("has_scope_record") is True):
            continue
        author = issue["author"]
        if mode == "sweep" and per_author.get(author, 0) >= 2:
            continue
        normalized = existing | {aliases.get(label, label) for label in existing}
        occupied = {label.split("/", 1)[0] for label in normalized}
        proposed = set(issue.get("proposed_labels", [])) & allowed
        additions = {label for label in proposed if label.split("/", 1)[0] not in occupied}
        for dimension in ("type", "theme"):
            values = sorted(label for label in additions if label.startswith(f"{dimension}/"))
            if len(values) > 1:
                raise ValueError(f"Conflicting proposed {dimension} labels")
        if len(additions) > 6:
            raise ValueError("At most six classification labels may be proposed")
        additions.add(marker)
        selected.append(
            {
                "number": number,
                "add_labels": sorted(additions - existing),
                "remove_labels": sorted(existing & set(processing["removable"])),
            }
        )
        per_author[author] = per_author.get(author, 0) + 1
        if mode == "sweep" and len(selected) == sweep_cap:
            break
    return {
        "selected": selected,
        "batch_full": mode == "sweep" and len(selected) == sweep_cap,
        "implementation_authorized": False,
    }


def main() -> int:
    """Read a normalized batch and emit a JSON plan or an actionable error."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        contract = json.loads(
            (Path(__file__).resolve().parent.parent / "assets/label-contract.json").read_text(
                encoding="ascii"
            )
        )
        result = plan_batch(json.load(sys.stdin), contract)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"[x] Triage metadata planning failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
