"""Research-qualified underlyings for the Options Desk.

This module is deliberately pure.  Callers collect rows from the watchlist,
re-entry desk, holdings, CIO research, and discovery stores; this module
normalizes and merges them without ranking away a researched name.

No sizing, broker, order, or execution authority lives here.
"""
from __future__ import annotations

from typing import Any, Iterable


RESEARCH_SOURCES = frozenset({
    "watchlist", "watchlist_buy_strong_buy", "reentry", "entry_state",
    "layer4", "fused_signal", "cio_research", "research_intelligence",
    "operator_added", "portfolio_intent",
})


def _sym(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("underlying") or "").strip().upper()


def _source_lanes(row: dict[str, Any]) -> set[str]:
    lanes = set()
    raw = row.get("source_lanes")
    if isinstance(raw, (list, tuple, set)):
        lanes.update(str(x) for x in raw if x)
    for key in ("source", "origin", "research_source"):
        value = row.get(key)
        if value:
            lanes.add(str(value))
    return lanes


def _is_researched(row: dict[str, Any], lanes: set[str]) -> bool:
    if row.get("research_status") == "research_required":
        return False
    if row.get("research_status") in {"researched", "research_qualified"}:
        return True
    if row.get("research_artifact_id") or row.get("research_memo"):
        return True
    # These lanes are already produced from a persisted research/intelligence
    # artifact rather than a raw ticker scan.
    if lanes.intersection(RESEARCH_SOURCES):
        return True
    return False


def merge_research_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge rows by symbol, retaining all research lanes and best evidence.

    The first row wins for ordinary fields, while non-empty fields from later
    rows fill gaps.  This preserves deterministic generation without losing
    the fact that a name is both watchlist and re-entry relevant.
    """
    merged: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        symbol = _sym(raw)
        if not symbol:
            continue
        lanes = _source_lanes(raw)
        current = merged.get(symbol)
        if current is None:
            current = {"symbol": symbol, **raw}
            current["source_lanes"] = sorted(lanes)
            merged[symbol] = current
        else:
            current["source_lanes"] = sorted(set(current.get("source_lanes") or []).union(lanes))
            for key, value in raw.items():
                if key in {"source_lanes", "source", "symbol"}:
                    continue
                if current.get(key) in (None, "", [], {}):
                    current[key] = value
        current["research_status"] = "researched" if _is_researched(current, set(current.get("source_lanes") or [])) else "research_required"
        current["research_qualified"] = current["research_status"] == "researched"
    return list(merged.values())


def reentry_research_rows(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize the read-only re-entry desk snapshot into research rows."""
    out: list[dict[str, Any]] = []
    for row in (snapshot or {}).get("rows") or []:
        if not isinstance(row, dict) or not _sym(row):
            continue
        thesis = row.get("thesis") or row.get("analyst_summary") or row.get("summary")
        out.append({
            "symbol": _sym(row),
            "source": "reentry",
            "source_lanes": ["reentry"],
            "research_artifact_id": row.get("watch_id") or row.get("id") or f"reentry:{_sym(row)}",
            "research_status": "researched" if thesis or row.get("analyst_verdict") or row.get("reentry_signal") else "research_required",
            "summary": thesis or "Re-entry desk candidate; thesis text unavailable.",
            "thesis": thesis,
            "reentry_signal": row.get("reentry_signal") or row.get("status"),
            "reentry_trigger": row.get("reentry_trigger"),
            "invalidated_if": row.get("invalidated_if"),
            "exit_date": row.get("exit_date"),
            "price": row.get("price") or row.get("current_price"),
            "evaluated_at": row.get("evaluated_at") or row.get("as_of"),
        })
    return out


def research_universe_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    normalized = merge_research_rows(rows)
    lane_counts: dict[str, int] = {}
    for row in normalized:
        for lane in row.get("source_lanes") or []:
            lane_counts[lane] = lane_counts.get(lane, 0) + 1
    return {
        "total": len(normalized),
        "research_qualified": sum(1 for row in normalized if row.get("research_qualified")),
        "research_required": sum(1 for row in normalized if not row.get("research_qualified")),
        "source_lane_counts": dict(sorted(lane_counts.items())),
    }
