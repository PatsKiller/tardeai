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


def conviction_bias(row: dict[str, Any]) -> str:
    """Normalize persisted direction; conflicting evidence requires review."""
    if row.get("direction_conflict"):
        return "conflict"
    directions = set()
    for key in ("bias", "direction", "verdict", "severity", "inference_type"):
        value = str(row.get(key) or "").lower().replace("-", "_").replace(" ", "_")
        if value in {"bullish", "long", "buy", "strong_buy", "up", "opportunity", "positive"}:
            directions.add("bullish")
        if value in {"bearish", "short", "sell", "strong_sell", "down", "risk", "negative"}:
            directions.add("bearish")
    return "conflict" if len(directions) > 1 else next(iter(directions), "neutral")


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
        direction = conviction_bias(raw)
        current = merged.get(symbol)
        if current is None:
            current = {"symbol": symbol, **raw}
            current["source_lanes"] = sorted(lanes)
            current["direction_evidence"] = list(raw.get("direction_evidence") or [])
            merged[symbol] = current
        else:
            current["source_lanes"] = sorted(set(current.get("source_lanes") or []).union(lanes))
            for key, value in raw.items():
                if key in {"source_lanes", "source", "symbol"}:
                    continue
                if current.get(key) in (None, "", [], {}):
                    current[key] = value
        evidence = current["direction_evidence"]
        for item in raw.get("direction_evidence") or []:
            if item not in evidence:
                evidence.append(item)
        if direction != "neutral" and not raw.get("direction_evidence"):
            item = {"direction": direction, "source": raw.get("source"),
                    "artifact_id": raw.get("research_artifact_id"),
                    "as_of": raw.get("research_as_of") or raw.get("evaluated_at")}
            if item not in evidence:
                evidence.append(item)
        directions = {e["direction"] for e in evidence}
        current["direction_conflict"] = "conflict" in directions or len(directions) > 1
        lanes_now = set(current.get("source_lanes") or [])
        qualified = _is_researched(current, lanes_now)
        # Operator 2026-09-27: a lane membership qualifies a name for the desk; it is not
        # itself research. Say which one the card is looking at.
        if raw.get("research_status") in {"researched", "research_qualified"}:
            current["_explicit_researched"] = True
        has_artifact = bool(current.get("research_memo") or current.get("_explicit_researched")
                            or (current.get("research_artifact_id")
                                and current.get("research_status") != "research_required"))
        current["research_lane_status"] = "lane_qualified" if lanes_now.intersection(RESEARCH_SOURCES) else "unqualified"
        current["research_status"] = ("researched" if has_artifact else
                                      ("lane_qualified" if qualified else "research_required"))
        current["research_qualified"] = qualified or has_artifact
    for row in merged.values():
        row.pop("_explicit_researched", None)
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
            "evaluated_at": row.get("evaluated_at") or row.get("as_of") or (snapshot or {}).get("computed_at"),
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
