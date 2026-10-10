#!/usr/bin/env python3
"""ipo_lockup_alert.py — fire a Telegram/SIEM alert ahead of each IPO lockup-expiry tranche.

A lockup unlock is a real supply catalyst (insiders/employees become free to sell). This watches the
tranches in config/ipo_lockups.json and fires once per tranche when it's within LEAD_DAYS, with the
price-conditional context (e.g. SpaceX's +10% bonus tranche only triggers if SPCX ≥ $175.50). Fired
tranches are remembered in data/runtime/lockup_alerts_fired.json so it doesn't repeat.

  python3 scripts/ipo_lockup_alert.py            # check + fire due alerts
  python3 scripts/ipo_lockup_alert.py --list      # show upcoming unlocks
  python3 scripts/ipo_lockup_alert.py --dry-run   # what would fire; writes/sends nothing

Refactor wave 2 (cron -> n8n, 2026-10-10; cron:L488). This lane is a SENDER: an alert_events row is
the operator alert. Nothing here changes what it sends.
- ``--dry-run`` returns from ``check`` before ``save_alert_event``, ``_save_fired`` and the yfinance
  price lookup are reachable, and prints the alerts that would fire. No receipt.
- A tranche is remembered as fired only when ``save_alert_event`` returned an id; before this a DB
  failure (it returns None, it does not raise) still marked the tranche fired, so the alert was lost
  for good.
- The fired-set file resolves to the SERVED data/runtime (persistent root first).
- A real run writes data/runtime/ipo_lockup_alert_last.json (LaneRunReceipt@v1, ok_at only on success)
  and exits 1 when any due alert could not be written. Nothing due is a finding, not a failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _runtime_dir() -> Path:
    try:
        from lib.persistent_state_root import resolve_durable_dir

        return resolve_durable_dir("data/runtime", ROOT)
    except Exception:  # noqa: BLE001 -- resolution layer unavailable: the code tree (old behaviour)
        return ROOT / "data" / "runtime"


FIRED = _runtime_dir() / "lockup_alerts_fired.json"
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
        import yfinance as yf
        return float(yf.Ticker(sym).info.get("regularMarketPrice") or 0)
    except Exception:
        return None


def check(lead_days=LEAD_DAYS, *, dry_run: bool = False, failures: list | None = None):
    """Due tranches -> alert rows. ``dry_run`` returns the would-fire messages before any write/fetch."""
    import ipo_lockups
    fired = _fired()
    due = []
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
            due.append((key, sym, info, t, du))
    if dry_run:
        # Before any yfinance lookup, alert row or fired-set write is reachable (AGENTS.md §6).
        return [_message(sym, info, t, du, "") for _key, sym, info, t, du in due]
    from alert_event_writer import save_alert_event

    for key, sym, info, t, du in due:
        # price-conditional context (e.g. SPCX +10% bonus needs >= $175.50)
        cond = ""
        if "≥$" in (t.get("desc") or ""):
            px = _live_price(sym)
            cond = f" (live {sym} ${px:.2f})" if px else ""
        msg = _message(sym, info, t, du, cond)
        try:
            alert_id = save_alert_event(alert_type="strategic_alert", severity="urgent",
                                        source_script="ipo_lockup_alert.py", symbol=sym, raw_text=msg,
                                        parsed_payload={"kind": "ipo_lockup", "symbol": sym, "date": t["date"],
                                                        "pct": t.get("pct_unlocked"), "days_until": du})
        except Exception as exc:  # noqa: BLE001 -- reported below, never silently dropped
            alert_id = None
            msg_err = f"{type(exc).__name__}: {exc}"
        else:
            msg_err = "save_alert_event returned no id"
        if alert_id is None:
            if failures is not None:
                failures.append({"key": key, "error": msg_err[:200]})
            continue  # not remembered: the next run retries this tranche
        fired.add(key)
        new_fires.append(msg)
    if new_fires:
        _save_fired(fired)
    return new_fires


def _message(sym, info, t, du, cond):
    return (f"[lockup] {sym} ({info['company']}) unlock in {du}d on {t['date']}: "
            f"{t.get('pct_unlocked','?')}% — {t['desc']}{cond}"
            + (" [date approximate]" if t.get("approx") else ""))


def upcoming():
    import ipo_lockups
    rows = []
    for sym in ipo_lockups.all_symbols():
        info = ipo_lockups.lockup_info(sym)
        for t in (info or {}).get("tranches", []):
            if t.get("days_until") is not None and t["days_until"] >= 0:
                rows.append((t["days_until"], sym, t["date"], t.get("pct_unlocked"), t["desc"][:60]))
    return sorted(rows)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--list" in argv:
        for du, sym, d, pct, desc in upcoming():
            print(f"  {sym} {d} (in {du}d, {pct}%): {desc}")
        return 0
    if "--dry-run" in argv:
        would = check(dry_run=True)
        print(json.dumps({"mode": "dry_run", "would_fire": would,
                          "would_write": {"alert_events": len(would), "fired_set": str(FIRED) if would else None}},
                         indent=2))
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started_at = now_iso()
    failures: list = []
    try:
        fires = check(failures=failures)
    except Exception as exc:
        write_receipt("ipo_lockup_alert", ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    print(json.dumps({"fired": fires, "failed": failures}, indent=2))
    ok = not failures
    write_receipt("ipo_lockup_alert", ok=ok, started_at=started_at,
                  summary={"fired": len(fires), "failed": len(failures)},
                  error=None if ok else f"{len(failures)} due alert(s) not written")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
