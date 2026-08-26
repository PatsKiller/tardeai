"""Referential integrity and holdings last-known-good state. No destructive purge."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.lib.canonical_store_registry import load_json_store
from scripts.lib.instrument_normalize import classify_instrument
from scripts.lib.r17_checkpoint_reconciliation import reconcile_store

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def holdings_freshness(doc: dict[str, Any] | None) -> dict[str, Any]:
    d = doc or {}
    if d.get("write_rejected") or d.get("sanity_floor_blocked"):
        state = "WRITE_REJECTED"
        note = "LAST_KNOWN_GOOD — incoming write rejected; prior snapshot preserved"
    elif d.get("conflicted"):
        state = "CONFLICTED"
        note = None
    elif d.get("stale"):
        state = "STALE"
        note = d.get("_freshness_note")
    else:
        state = "CURRENT"
        note = d.get("_freshness_note")
    return {
        "state": state,
        "note": note,
        "exists": bool(d),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def instrument_audit(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    classes: dict[str, int] = {}
    options = []
    for h in holdings:
        if not isinstance(h, dict):
            continue
        c = classify_instrument(str(h.get("symbol") or ""), is_cash=bool(h.get("is_cash")), asset_type=h.get("asset_type"))
        classes[c["instrument_class"]] = classes.get(c["instrument_class"], 0) + 1
        if c["instrument_class"] == "OPTION":
            options.append({"symbol": h.get("symbol"), "underlying": c.get("underlying_symbol")})
    return {"classes": classes, "option_n": len(options), "options_sample": options[:10]}


def orphan_stops(stops: list[dict[str, Any]], holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    held = {(str(h.get("symbol") or "").upper(), str(h.get("account") or "")) for h in holdings if isinstance(h, dict)}
    out = []
    for s in stops:
        if not isinstance(s, dict):
            continue
        key = (str(s.get("symbol") or "").upper(), str(s.get("account") or ""))
        if key[0] and key not in held and (key[0], "") not in {(h[0], "") for h in held}:
            # orphan if symbol not held in that account and not held at all
            if not any(h[0] == key[0] for h in held):
                out.append({"symbol": s.get("symbol"), "account": s.get("account"), "reason": "stop_without_holding"})
    return out


def audit(*, root: Path | str | None = None) -> dict[str, Any]:
    hloc = load_json_store("portfolio.holdings.current", root=root)
    holdings_doc = hloc.get("data") if hloc.get("available") else {}
    holds = list((holdings_doc or {}).get("holdings") or [])
    ck = reconcile_store(root or ".")
    cash_dupes = int((ck.get("counts") or {}).get("SEMANTIC_DUPLICATE") or 0)
    return {
        "schema": "DataIntegrityAudit@v1",
        "holdings": holdings_freshness(holdings_doc if isinstance(holdings_doc, dict) else {}),
        "instruments": instrument_audit(holds),
        "checkpoint_reconciliation": {
            "total": ck.get("total"),
            "counts": ck.get("counts"),
            "bug_duplicates": cash_dupes,
            "deleted": 0,
        },
        "purge_plan": {
            "destructive_changes_applied": False,
            "approval_required": True,
            "note": "SNAPSHOT→INVENTORY→CLASSIFY→QUARANTINE→REBUILD. No delete in this tranche.",
        },
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
