#!/usr/bin/env python3
"""ipo_lockup_alert.py — fire a Telegram/SIEM alert ahead of each IPO lockup-expiry tranche.

A lockup unlock is a real supply catalyst (insiders/employees become free to sell). This watches the
tranches in config/ipo_lockups.json and fires once per tranche when it's within LEAD_DAYS, with the
price-conditional context (e.g. SpaceX's +10% bonus tranche only triggers if SPCX ≥ $175.50). Fired
tranches are remembered in data/runtime/lockup_alerts_fired.json so it doesn't repeat.

  python3 scripts/ipo_lockup_alert.py            # check + fire due alerts
  python3 scripts/ipo_lockup_alert.py --list      # show upcoming unlocks
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
FIRED = ROOT / "data" / "runtime" / "lockup_alerts_fired.json"
LEAD_DAYS = 14   # alert this many days before a tranche


def _fired():
    try:
        return set(json.loads(FIRED.read_text()))
    except Exception:
        return set()


def _save_fired(s):
    FIRED.parent.mkdir(parents=True, exist_ok=True)
    FIRED.write_text(json.dumps(sorted(s), indent=2))


def _live_price(sym):
    try:
        # Data Broker (2026-07-31): canonical quote waterfall, not a raw yfinance call —
        # see config/data_registry.yaml:quote_last_price.
        from market_quote_provider import get_best_quote
        q = get_best_quote(sym) or {}
        return float(q.get("last_price") or 0)
    except Exception:
        return None


def check(lead_days=LEAD_DAYS):
    import ipo_lockups
    fired = _fired()
    new_fires = []
    for sym in ipo_lockups.all_symbols():
        info = ipo_lockups.lockup_info(sym)
        if not info:
            continue
        for t in info["tranches"]:
            du = t.get("days_until")
            if du is None or du < 0 or du > lead_days:
                continue
            key = f"{sym}:{t['date']}"
            if key in fired:
                continue
            # price-conditional context (e.g. SPCX +10% bonus needs >= $175.50)
            cond = ""
            if "≥$" in (t.get("desc") or ""):
                px = _live_price(sym)
                cond = f" (live {sym} ${px:.2f})" if px else ""
            msg = (f"[lockup] {sym} ({info['company']}) unlock in {du}d on {t['date']}: "
                   f"{t.get('pct_unlocked','?')}% — {t['desc']}{cond}"
                   + (" [date approximate]" if t.get("approx") else ""))
            try:
                from alert_event_writer import save_alert_event
                save_alert_event(alert_type="strategic_alert", severity="urgent",
                                 source_script="ipo_lockup_alert.py", symbol=sym, raw_text=msg,
                                 parsed_payload={"kind": "ipo_lockup", "symbol": sym, "date": t["date"],
                                                 "pct": t.get("pct_unlocked"), "days_until": du})
                fired.add(key)
                new_fires.append(msg)
            except Exception:
                pass
    if new_fires:
        _save_fired(fired)
    return new_fires


def upcoming():
    import ipo_lockups
    rows = []
    for sym in ipo_lockups.all_symbols():
        info = ipo_lockups.lockup_info(sym)
        for t in (info or {}).get("tranches", []):
            if t.get("days_until") is not None and t["days_until"] >= 0:
                rows.append((t["days_until"], sym, t["date"], t.get("pct_unlocked"), t["desc"][:60]))
    return sorted(rows)


if __name__ == "__main__":
    if "--list" in sys.argv:
        for du, sym, d, pct, desc in upcoming():
            print(f"  {sym} {d} (in {du}d, {pct}%): {desc}")
    else:
        fires = check()
        print(json.dumps({"fired": fires}, indent=2))
