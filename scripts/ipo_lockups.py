#!/usr/bin/env python3
"""ipo_lockups.py — IPO lockup-expiration lookup (when insiders can sell, per the S-1).

Source of truth: config/ipo_lockups.json. Consumers: portfolio_ask (so "when can insiders sell SPCX?"
answers with the real dates), and a near-expiry alert. A lockup expiry is a genuine supply catalyst.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

_CFG = Path(__file__).resolve().parent.parent / "config" / "ipo_lockups.json"


def _load() -> dict:
    try:
        return json.loads(_CFG.read_text()).get("lockups", {})
    except Exception:
        return {}


def lockup_info(symbol: str) -> dict | None:
    """Return the lockup record for a symbol (with days_until per tranche), or None."""
    rec = _load().get((symbol or "").strip().upper())
    if not rec:
        return None
    today = date.today()
    out = dict(rec)
    tranches = []
    for t in rec.get("tranches", []):
        d = t.get("date")
        try:
            du = (date.fromisoformat(d) - today).days if d else None
        except Exception:
            du = None
        tranches.append({**t, "days_until": du, "passed": (du is not None and du < 0)})
    out["tranches"] = tranches
    out["next_unlock"] = next((t for t in tranches if t.get("days_until") is not None and t["days_until"] >= 0), None)
    return out


def all_symbols() -> list[str]:
    return sorted(_load().keys())


if __name__ == "__main__":
    import sys
    syms = sys.argv[1:] or all_symbols()
    for s in syms:
        info = lockup_info(s)
        if not info:
            print(f"{s}: no lockup data"); continue
        print(f"{s} ({info['company']}) — IPO {info['ipo_date']} @ ${info['offer_price']}")
        for t in info["tranches"]:
            tag = "PASSED" if t["passed"] else f"in {t['days_until']}d"
            print(f"   {t['date']} ({t['days']}d, {tag}): {t['desc']}")
