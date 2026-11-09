#!/usr/bin/env python3
"""update_lockup_earnings_dates.py — snap earnings-tied IPO-lockup tranches to the REAL report date.

Several SpaceX lockup tranches release on "the second full trading day following" a quarterly earnings
release. Those dates are estimates (approx:true) until the company announces. This watches Finviz (view 161) for the
next earnings date and, when one appears, updates the still-approx earnings tranche group whose
estimate is nearest that date to (earnings_date + 2 trading days), flips approx:false, and logs/alerts
the change. Idempotent; runs on a
schedule. Conservative: only snaps when the announced date is within ±75 days of the current estimate.

  python3 scripts/update_lockup_earnings_dates.py            # live: rewrite the config + alert rows
  python3 scripts/update_lockup_earnings_dates.py --dry-run  # read-only: print the snaps it would make

A real run writes data/runtime/update_lockup_earnings_dates_last.json (LaneRunReceipt@v1, ok_at only on
success) under the persistent state root and exits 1 on failure. A dry run returns before the config
write and the alert rows are reachable (AGENTS.md §6).

The snapped config is written under the persistent state root (config/ipo_lockups.json). The checkout
copy is the seed, read only when the state copy is absent, and is never written. An earnings-lookup
error exits 1. No announced date is a finding, exit 0.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SEED_CFG = ROOT / "config" / "ipo_lockups.json"
# Tests point CFG at their own file. Production leaves it on the seed; the write then goes to state.
CFG = SEED_CFG
WINDOW_DAYS = 75
RECEIPT_NAME = "update_lockup_earnings_dates"


def _state_cfg() -> Path:
    from lib.persistent_state_root import good_persistent_root
    return good_persistent_root() / "config" / "ipo_lockups.json"


def _read_write_paths() -> tuple[Path, Path]:
    """(read_path, write_path). A CFG other than the seed is a test file, used for both.
    Production reads the state copy when it exists, else the shipped seed, and writes only state."""
    if CFG != SEED_CFG:
        return CFG, CFG
    state = _state_cfg()
    return (state if state.is_file() else SEED_CFG), state


def _plus_trading_days(d: date, n: int) -> date:
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:   # Mon-Fri (ignores holidays — close enough for a lockup date)
            added += 1
    return cur


def parse_finviz_earnings(raw, today: date | None = None) -> date | None:
    """Parse a Finviz 'Earnings Date' cell ('Nov 12 AMC', '11/12/2026', '2026-11-12', '-') to a date or None."""
    import re

    today = today or date.today()
    s = str(raw or "").strip()
    if not s or s == "-":
        return None
    s = re.sub(r"\s+(AMC|BMO|DMH)\s*$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM)?\s*$", "", s, flags=re.I).strip()   # '11/2/2026 4:30:00 PM'
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        d = datetime.strptime(f"{s} {today.year}", "%b %d %Y").date()
    except ValueError:
        return None
    if (today - d).days > 180:      # 'Jan 28' read in November is next year's report
        d = d.replace(year=d.year + 1)
    return d


def _next_earnings(symbol: str):
    """Return the next announced earnings date (date) for a symbol, or None when none is announced.

    Source: the Finviz export view 161 'Earnings Date' column, through the existing finviz_enrichment
    client (credentials stay inside it). A symbol with no row at all is a lookup failure and raises, so
    main() exits 1 instead of reporting a quiet 'nothing announced'."""
    import finviz_enrichment as fe

    # A narrow col_map: the view's default map files this column under earnings_date2, which the client
    # drops (SKIP_DUPLICATES). Other callers keep the default map.
    rows = fe._fetch_view([symbol], 161, ROOT, col_map={"Ticker": "ticker", "Earnings Date": "earnings_date"})
    row = rows.get(symbol.upper()) or rows.get(symbol)
    if row is None:
        raise RuntimeError(f"finviz returned no row for {symbol}")
    d = parse_finviz_earnings(row.get("earnings_date"))
    return d if d is not None and d >= date.today() else None


def _tranche_day(t: dict) -> date | None:
    """The tranche's estimate as a date, or None when it is absent or unparseable."""
    try:
        return date.fromisoformat(str(t.get("date") or ""))
    except ValueError:
        return None


def plan_snaps(cfg: dict) -> list[dict]:
    """Mutates `cfg` in memory only; returns the snaps (one per symbol). Never writes."""
    changed = []
    for sym, rec in cfg.get("lockups", {}).items():
        # earnings-tied tranches still approximate
        approx = [t for t in rec.get("tranches", [])
                  if t.get("approx") and "earnings" in (t.get("desc", "").lower())]
        if not approx:
            continue
        ed = _next_earnings(sym)
        if not ed:
            continue
        # The group to snap is the one the announced date belongs to: the estimate nearest the
        # announcement, inside ±WINDOW_DAYS. The old rule took the earliest still-approx estimate,
        # which on 2026-11-07 was a Q2 tranche from 2026-08-05 — so the window then rejected every
        # announced date and the lane could only ever snap a three-month-old tranche (measured:
        # announced 2026-11-12 and 2027-01-28 both produced changed=[], LQ-20261107-354).
        today = date.today()
        window = [(d, t) for t in approx if (d := _tranche_day(t)) is not None
                  and abs((ed - d).days) <= WINDOW_DAYS]
        if not window:
            continue   # announced date is near no estimate — likely a different quarter; skip
        # Nearest wins; on an equal distance prefer a still-future estimate, because an announcement
        # usually precedes the estimate it replaces. A passed estimate stays the candidate when it is
        # the nearer one: a delayed report belongs to the quarter whose estimate has slipped past, and
        # preferring any future estimate over it would snap the wrong quarter.
        est, first = min(window, key=lambda pair: (abs((ed - pair[0]).days),
                                                   pair[0] < today, pair[0]))
        target_date = first["date"]
        group = [t for t in approx if t.get("date") == target_date]
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


def _apply(cfg: dict, changed: list[dict], dest: Path) -> dict:
    """The only writer: the state config file, then one alert_events row per snap."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(cfg, indent=2))
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
    read_path, write_path = _read_write_paths()
    cfg = json.loads(read_path.read_text())
    changed = plan_snaps(cfg)
    out = {"changed": changed, "config_path": str(write_path)}
    if dry_run:
        out["dry_run"] = True
        out["would_write"] = str(write_path) if changed else None
        out["would_alert"] = len(changed)
        return out
    if changed:
        out.update(_apply(cfg, changed, write_path))
    return out


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Snap earnings-tied IPO lockup tranches to announced dates.")
    ap.add_argument("--dry-run", action="store_true", help="read-only: print the snaps; write nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        print(json.dumps(run(dry_run=True), indent=2))
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt

    started = now_iso()
    try:
        res = run()
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_lane_receipt(
            RECEIPT_NAME,
            ok=False,
            exit_code=1,
            error=f"{type(exc).__name__}: {exc}",
            started_at=started,
            script="scripts/update_lockup_earnings_dates.py",
        )
        print(f"lockup earnings update FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in res.items() if k != "config_path"}, indent=2))
    n_changed = len(res["changed"])
    # Contract empty_allowed_reasons: nothing_due / no_new_input. Without empty_reason the grader
    # treats changed=0 as empty_violation → FAIL_RUN (LQ-20261107-1409).
    write_lane_receipt(
        RECEIPT_NAME,
        ok=True,
        exit_code=0,
        started_at=started,
        script="scripts/update_lockup_earnings_dates.py",
        summary={"changed": n_changed, "alert_errors": res.get("alert_errors", 0)},
        produced_count=n_changed,
        empty_reason=None if n_changed else "nothing_due",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
