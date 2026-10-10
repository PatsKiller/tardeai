#!/usr/bin/env python3
"""update_lockup_earnings_dates.py — snap earnings-tied IPO-lockup tranches to the REAL report date.

Several SpaceX lockup tranches release on "the second full trading day following" a quarterly earnings
release. Those dates are estimates (approx:true) until the company announces. This watches yfinance for the
next earnings date and, when one appears, updates the earliest still-approx earnings tranche group to
(earnings_date + 2 trading days), flips approx:false, and logs/alerts the change. Idempotent; runs on a
schedule. Conservative: only snaps when the announced date is within ±75 days of the current estimate.

  python3 scripts/update_lockup_earnings_dates.py            # live: rewrite the config + alert rows
  python3 scripts/update_lockup_earnings_dates.py --dry-run  # read-only: print the snaps it would make

A real run writes data/runtime/update_lockup_earnings_dates_last.json (LaneRunReceipt@v1, ok_at only on
success) under the persistent state root and exits 1 on failure. A dry run returns before the config
write and the alert rows are reachable (AGENTS.md §6).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CFG = ROOT / "config" / "ipo_lockups.json"
WINDOW_DAYS = 75
RECEIPT_NAME = "update_lockup_earnings_dates"


def _plus_trading_days(d: date, n: int) -> date:
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:   # Mon-Fri (ignores holidays — close enough for a lockup date)
            added += 1
    return cur


def _next_earnings(symbol: str):
    """Return the next announced earnings date (date) for a symbol, or None."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        info = t.info or {}
        ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
        if ts:
            d = datetime.fromtimestamp(int(ts), timezone.utc).date()
            if d >= date.today():
                return d
        cal = t.calendar
        if isinstance(cal, dict):
            eds = cal.get("Earnings Date") or []
            future = sorted(x for x in eds if hasattr(x, "year") and x >= date.today())
            if future:
                return future[0]
    except Exception:
        pass
    return None


def plan_snaps(cfg: dict) -> list[dict]:
    """Mutates `cfg` in memory only; returns the snaps (one per symbol). Never writes."""
    changed = []
    for sym, rec in cfg.get("lockups", {}).items():
        # earnings-tied tranches still approximate, grouped by current estimated date (earliest first)
        approx = [t for t in rec.get("tranches", [])
                  if t.get("approx") and "earnings" in (t.get("desc", "").lower())]
        if not approx:
            continue
        ed = _next_earnings(sym)
        if not ed:
            continue
        approx.sort(key=lambda t: t.get("date") or "9999")
        target_date = approx[0]["date"]
        group = [t for t in approx if t.get("date") == target_date]
        try:
            est = date.fromisoformat(target_date)
        except Exception:
            continue
        if abs((ed - est).days) > WINDOW_DAYS:
            continue   # announced date too far from the estimate — likely a different quarter; skip
        release = _plus_trading_days(ed, 2).isoformat()   # "second full trading day following"
        if release == target_date:
            continue
        for t in group:
            t["date"] = release
            t["approx"] = False
            t["note"] = f"snapped to announced earnings {ed.isoformat()} (+2 trading days)"
        changed.append({"symbol": sym, "from": target_date, "to": release, "earnings": ed.isoformat(),
                        "tranches": len(group)})
    return changed


def _apply(cfg: dict, changed: list[dict]) -> dict:
    """The only writer: the config file, then one alert_events row per snap."""
    CFG.write_text(json.dumps(cfg, indent=2))
    alert_errors = 0
    try:
        from alert_event_writer import save_alert_event
        for ch in changed:
            save_alert_event(alert_type="strategic_alert", severity="info",
                             source_script="update_lockup_earnings_dates.py", symbol=ch["symbol"],
                             raw_text=f"[lockup] {ch['symbol']} earnings-tied unlock snapped {ch['from']} → "
                                      f"{ch['to']} (earnings {ch['earnings']})",
                             parsed_payload={"kind": "lockup_date_update", **ch})
    except Exception:
        alert_errors += 1   # the config write above is the durable effect; the alert is best-effort
    return {"alert_errors": alert_errors}


def run(dry_run: bool = False) -> dict:
    cfg = json.loads(CFG.read_text())
    changed = plan_snaps(cfg)
    out = {"changed": changed, "config_path": str(CFG)}
    if dry_run:
        out["dry_run"] = True
        out["would_write"] = str(CFG) if changed else None
        out["would_alert"] = len(changed)
        return out
    if changed:
        out.update(_apply(cfg, changed))
    return out


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Snap earnings-tied IPO lockup tranches to announced dates.")
    ap.add_argument("--dry-run", action="store_true", help="read-only: print the snaps; write nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        print(json.dumps(run(dry_run=True), indent=2))
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        res = run()
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"lockup earnings update FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in res.items() if k != "config_path"}, indent=2))
    write_receipt(RECEIPT_NAME, ok=True, started_at=started,
                  summary={"changed": len(res["changed"]), "alert_errors": res.get("alert_errors", 0)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
