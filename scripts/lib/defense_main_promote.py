"""Defense → MAIN promote bridge (policy 1C).

Soft-auto: SCHD + defensive-lean sector ETFs when on Defense get_into.
Cyclical (XLK…): click-only. Lands MAIN WAIT via origin_system=defense_rotation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFENSE_CFG = PROJECT_ROOT / "config" / "defense_recommendations.json"
ADMISSION_CFG = PROJECT_ROOT / "config" / "watch_lane_admission.json"

SECTOR_ETF = {
    "technology": "XLK", "financials": "XLF", "health care": "XLV", "healthcare": "XLV",
    "energy": "XLE", "industrials": "XLI", "consumer discretionary": "XLY",
    "consumer staples": "XLP", "utilities": "XLU", "materials": "XLB",
    "real estate": "XLRE", "communication services": "XLC",
}


def _load_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def load_promote_policy() -> dict[str, Any]:
    defense = _load_json(DEFENSE_CFG)
    admission = _load_json(ADMISSION_CFG)
    pairs = defense.get("rotation_pairs") or {}
    lean = pairs.get("defensive_lean") or {}
    promote = admission.get("defense_main_promote") or {}
    income = str(pairs.get("income_destination") or "SCHD").upper()
    soft = {income}
    if lean.get("enabled", True) or promote.get("respect_defensive_lean", True):
        for sec in lean.get("defensive_sectors") or []:
            etf = SECTOR_ETF.get(str(sec).lower())
            if etf:
                soft.add(etf)
    for s in promote.get("soft_auto_symbols") or []:
        if s:
            soft.add(str(s).upper())
    click = {str(s).upper() for s in (promote.get("click_only_symbols") or [])}
    click -= soft
    return {
        "soft_auto_symbols": sorted(soft),
        "click_only_symbols": sorted(click),
        "income_destination": income,
        "main_cap": int(admission.get("main_cap") or 60),
    }


def is_soft_auto_symbol(symbol: str, policy: dict | None = None) -> bool:
    p = policy or load_promote_policy()
    return str(symbol or "").upper() in set(p["soft_auto_symbols"])


def extract_destination_symbols(cards: list[dict] | None) -> list[str]:
    out: list[str] = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        if str(card.get("group") or "") not in ("get_into", "income"):
            continue
        for key in ("etf", "symbol", "ticker", "destination", "dest"):
            v = card.get(key)
            if isinstance(v, str) and v.replace(".", "").isalnum() and 1 <= len(v) <= 8:
                out.append(v.upper())
        for dest in card.get("destinations") or []:
            if isinstance(dest, str):
                out.append(dest.upper())
            elif isinstance(dest, dict) and dest.get("symbol"):
                out.append(str(dest["symbol"]).upper())
    return sorted({s for s in out if s})


def soft_auto_candidates(cards: list[dict] | None, policy: dict | None = None) -> list[str]:
    p = policy or load_promote_policy()
    soft = set(p["soft_auto_symbols"])
    return [s for s in extract_destination_symbols(cards) if s in soft]


def _exec(db_execute: Callable, sql: str, params=None, fetch=None):
    try:
        if fetch:
            return db_execute(sql, params, fetch=fetch)
        return db_execute(sql, params)
    except TypeError:
        return db_execute(sql, params)


def promote_to_main(
    db_execute: Callable,
    symbol: str,
    *,
    mode: str = "soft",
    provenance: dict | None = None,
    main_count: int | None = None,
) -> dict[str, Any]:
    p = load_promote_policy()
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "error": "symbol required"}
    mode = "click" if str(mode) == "click" else "soft"
    if mode == "soft" and not is_soft_auto_symbol(sym, p):
        return {"ok": False, "error": "not_soft_auto", "symbol": sym, "hint": "use mode=click"}

    if main_count is not None and main_count >= int(p["main_cap"]) and mode == "soft":
        return {"ok": False, "error": "main_cap", "symbol": sym, "main_cap": p["main_cap"]}

    now = datetime.now(timezone.utc).isoformat()
    prov = {
        **(provenance or {}),
        "origin_system": "defense_rotation",
        "main_promote_mode": mode,
        "main_promoted_at": now,
    }
    marker = f"[defense_main_promote {mode} {now}] {json.dumps(prov)}"

    row = _exec(
        db_execute,
        """SELECT id FROM watchlist_items
           WHERE upper(symbol)=%s AND status <> 'removed'
           ORDER BY updated_at DESC LIMIT 1""",
        (sym,),
        fetch="one",
    )
    if isinstance(row, list):
        row = row[0] if row else None

    try:
        if row and isinstance(row, dict) and row.get("id") is not None:
            _exec(
                db_execute,
                """UPDATE watchlist_items
                   SET source = CASE WHEN source IS NULL OR source = '' THEN 'operator' ELSE source END,
                       origin_system = 'defense_rotation',
                       in_directive_watch = TRUE,
                       status = 'active',
                       notes = left(COALESCE(notes,'') || E'\n' || %s, 4000),
                       updated_at = now()
                   WHERE id = %s""",
                (marker, row["id"]),
            )
        elif row and not isinstance(row, dict):
            _exec(
                db_execute,
                """UPDATE watchlist_items
                   SET origin_system = 'defense_rotation', in_directive_watch = TRUE,
                       notes = left(COALESCE(notes,'') || E'\n' || %s, 4000), updated_at = now()
                   WHERE id = %s""",
                (marker, row[0] if isinstance(row, (list, tuple)) else row),
            )
        else:
            _exec(
                db_execute,
                """INSERT INTO watchlist_items
                   (symbol, source, status, bucket, in_directive_watch, origin_system, notes, first_seen_at, updated_at)
                   VALUES (%s, 'operator', 'active', 'defense_rotation', TRUE, 'defense_rotation', %s, now(), now())""",
                (sym, marker),
            )
    except Exception as e:
        return {"ok": False, "error": str(e)[:240], "symbol": sym}

    return {"ok": True, "symbol": sym, "mode": mode, "provenance": prov, "main_promoted": True}


def run_soft_auto_from_cards(db_execute: Callable, cards: list[dict], *, main_count: int | None = None) -> dict[str, Any]:
    p = load_promote_policy()
    candidates = soft_auto_candidates(cards, p)
    results = [promote_to_main(db_execute, sym, mode="soft", main_count=main_count) for sym in candidates]
    return {
        "ok": True,
        "policy": {"soft_auto_symbols": p["soft_auto_symbols"], "main_cap": p["main_cap"]},
        "candidates": candidates,
        "results": results,
        "promoted": [r["symbol"] for r in results if r.get("ok")],
    }
