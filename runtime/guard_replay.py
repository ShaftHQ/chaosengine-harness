#!/usr/bin/env python3
"""Replay recorded hook events through an injected protocol. Commands are not run.

`run_protocol(event, revision)` must only parse the event. The default policy
`fail` marks a missing state snapshot unreplayable. Policy `live` is labeled
non-reproducible and is not for a PR gate.
"""

from __future__ import annotations

from typing import Any, Callable

Protocol = Callable[[dict[str, Any], str], dict[str, Any]]


def replay(
    events: list[dict[str, Any]],
    *,
    baseline: str,
    candidate: str,
    run_protocol: Protocol,
    policy: str = "fail",
    max_unreplayable_share: float = 0.0,
) -> dict[str, Any]:
    if policy not in {"fail", "live"}:
        raise ValueError("policy must be fail or live")
    diff: list[dict[str, Any]] = []
    unreplayable = 0
    non_reproducible = 0
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or not event.get("id"):
            raise ValueError("event id required")
        snapshot = event.get("state_snapshot")
        if not snapshot:
            if policy == "fail":
                unreplayable += 1
                rows.append({"id": event["id"], "status": "unreplayable"})
                continue
            non_reproducible += 1
        base = run_protocol(event, baseline)
        cand = run_protocol(event, candidate)
        row = {
            "id": event["id"],
            "baseline": base,
            "candidate": cand,
            "status": "non-reproducible" if not snapshot and policy == "live" else "replayed",
        }
        rows.append(row)
        if base != cand:
            diff.append({"id": event["id"], "baseline": base, "candidate": cand})
    share = (unreplayable / len(events)) if events else 0.0
    return {
        "rows": rows,
        "diff": diff,
        "unreplayable": unreplayable,
        "non_reproducible": non_reproducible,
        "ok": not diff and share <= max_unreplayable_share,
    }
