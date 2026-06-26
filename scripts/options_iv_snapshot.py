#!/usr/bin/env python3
"""Daily IV snapshot — persist ATM IV per symbol for true IV rank in options_engine."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _symbols() -> list[str]:
    syms = set()
    try:
        h = json.loads((STATE_DIR / "holdings.json").read_text(encoding="utf-8"))
        for row in h.get("holdings") or []:
            s = (row.get("symbol") or "").upper()
            if s and len(s) <= 6:
                syms.add(s)
    except Exception:
        pass
    try:
        p = json.loads((STATE_DIR / "options_proposals.json").read_text(encoding="utf-8"))
        for row in p.get("proposals") or []:
            s = (row.get("symbol") or "").upper()
            if s:
                syms.add(s)
    except Exception:
        pass
    return sorted(syms)[:40]


def snapshot_symbol(symbol: str) -> dict | None:
    import options_engine as oe
    chain = oe._schwab_chain(symbol, strikes=6)
    spot = float(chain.get("underlying_price") or 0)
    if spot <= 0:
        return None
    best_iv = None
    best_strike = None
    for exp in chain.get("expirations") or []:
        for row in exp.get("strikes") or []:
            if row.get("side") != "call":
                continue
            strike = float(row.get("strike") or 0)
            iv = float(row.get("iv") or 0)
            if iv <= 0:
                continue
            if iv > 3:
                iv = iv / 100.0
            if best_iv is None or abs(strike - spot) < abs((best_strike or spot) - spot):
                best_iv = iv * 100.0
                best_strike = strike
    if best_iv is None:
        return None
    return {"symbol": symbol, "iv_pct": round(best_iv, 3), "atm_strike": best_strike, "underlying": spot}


def persist(rows: list[dict]) -> int:
    if not rows:
        return 0
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return 0
        n = 0
        for r in rows:
            _execute(
                """INSERT INTO options_iv_history (symbol, iv_pct, atm_strike, underlying, source)
                   VALUES (%s,%s,%s,%s,'schwab_chain')""",
                (r["symbol"], r["iv_pct"], r.get("atm_strike"), r.get("underlying")),
            )
            n += 1
        return n
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:160]}))
        return 0


def main():
    rows = []
    for sym in _symbols():
        try:
            row = snapshot_symbol(sym)
            if row:
                rows.append(row)
        except Exception:
            pass
    n = persist(rows)
    # Global retention sweep for vol-surface snapshots (per-insert prune only
    # touches active symbols; this catches tails of names that went quiet).
    prune = {}
    try:
        import options_desk_enterprise as ent
        prune = ent.prune_chain_snapshots()
    except Exception as e:
        prune = {"ok": False, "error": str(e)[:160]}
    print(json.dumps({
        "ok": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": len(_symbols()),
        "rows_written": n,
        "snapshot_prune": prune,
    }))


if __name__ == "__main__":
    main()