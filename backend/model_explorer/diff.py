"""Model Explorer run-to-run changes (v2.40.0, ADR-035) — pure functions.

A cell is (model_id, api_id). Against the previous completed run, a cell of the current run is a change when its
status or its code_sha differs:
  catalog  — the previous run had no such cell (a new model or a new API tab)
  example  — the example code changed (code_sha differs), whatever the status — a release that changed an example
             shows whether the new code still passes
  measured — same code, different status
Cells only the previous run had (a model that left monitoring) are ignored, like the Claude API Features and parity
diffs. Output is sorted by (model_id, api_id); the page orders models itself.
"""

from __future__ import annotations

from typing import Mapping

KINDS = ("catalog", "example", "measured")


def diff_cells(prev: Mapping[tuple[str, str], Mapping], cur: Mapping[tuple[str, str], Mapping]) -> list[dict]:
    """prev/cur: {(model_id, api_id): {"status", "code_sha", "model_name", "api"}} -> change items."""
    changes: list[dict] = []
    for key in sorted(cur):
        after = cur[key]
        before = prev.get(key)
        if before is None:
            kind = "catalog"
        elif before["code_sha"] != after["code_sha"]:
            kind = "example"
        elif before["status"] != after["status"]:
            kind = "measured"
        else:
            continue
        model_id, api_id = key
        changes.append({
            "model_id": model_id, "model_name": after["model_name"], "api_id": api_id, "api": after.get("api", api_id),
            "before": None if before is None else before["status"], "after": after["status"], "kind": kind,
        })
    return changes
