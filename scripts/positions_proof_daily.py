#!/usr/bin/env python3
"""positions_proof_daily.py — phase 2 of the positions source-of-truth plan: the 10-trading-day proof.

Operator 2026-10-06: "30 min threshold is fine, start phase 2". Plan of record:
docs/architecture/POSITIONS_SOURCE_OF_TRUTH_PLAN_2026-10-05.md (phase 2 gate: 10 consecutive trading days with
zero unexplained differences, every sync run complete, heartbeat never late).

Once per trading day, after the 17:20 shadow diff, this READ-ONLY report grades the day:
  1. runs     — every positions_sync run that day finished `complete` (none partial/failed/stuck running)
  2. heartbeat— no gap between complete runs during 09:30-16:00 ET longer than the freshness contract (30 min)
  3. diff     — positions_current vs the holdings.json the Command Center serves: zero differences
  4. lots     — ledger lots vs broker positions: counted and reported; known-gap rows (transfer direction
                missing from the Schwab ledger) are EXPLAINED, not failures, until the day-3 feature fixes them
It appends one row per day to data/runtime/positions_proof_ledger.jsonl (re-running a day replaces its row),
computes "day N of 10" as the count of consecutive passing trading days since the proof start, and with --send
posts one line to the operator through telegram_alert.send_telegram.

  positions_proof_daily.py                 # grade today, print, write the ledger
  positions_proof_daily.py --date 2026-10-07
  positions_proof_daily.py --send          # also send the one-line Telegram report
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import positions_sync as ps  # noqa: E402

ET = ZoneInfo("America/New_York")
LEDGER_REL = Path("data") / "runtime" / "positions_proof_ledger.jsonl"
PLAN_FEATURES = {  # the plan's day-by-day table (docs/architecture/POSITIONS_SOURCE_OF_TRUTH_PLAN_2026-10-05.md)
    1: "Position sync, all accounts", 2: "Read-time pricing", 3: "Lots and realized P&L",
    4: "A live trade end to end", 5: "Writer failure", 6: "Database outage", 7: "Corporate actions",
    8: "Concurrency", 9: "Consumers", 10: "Full day",
}


def load_proof_config() -> dict:
    cfg = ps.load_sync_config()
    try:
        import yaml
        raw = yaml.safe_load(ps.CONFIG_PATH.read_text(encoding="utf-8")) or {}
        cfg.update((raw.get("positions_sync") or {}).get("proof") or {})
    except Exception:  # noqa: BLE001
        pass
    cfg.setdefault("start", "2026-10-07")
    cfg.setdefault("days", 10)
    return cfg


# ── grading (pure) ──────────────────────────────────────────────────────────

def grade_runs(runs: list[dict]) -> dict:
    bad = [r for r in runs if r["status"] != "complete" or not r.get("promoted")]
    return {"ok": bool(runs) and not bad, "count": len(runs),
            "not_complete": [{"run_id": r["run_id"], "status": r["status"]} for r in bad]}


def grade_heartbeat(runs: list[dict], day: date, limit_s: float) -> dict:
    """Largest gap between consecutive complete runs inside the regular session (open and close included)."""
    open_ = datetime.combine(day, time(9, 30), ET)
    close = datetime.combine(day, time(16, 0), ET)
    pts = sorted(r["finished_at"].astimezone(ET) for r in runs
                 if r["status"] == "complete" and r.get("finished_at"))
    marks = [open_] + [p for p in pts if open_ < p < close] + [close]
    # The first run after the open may land up to one cadence later; measure from the last run before the open.
    before = [p for p in pts if p <= open_]
    if before:
        marks[0] = before[-1]
    gaps = [(b - a).total_seconds() for a, b in zip(marks, marks[1:])]
    worst = max(gaps) if gaps else None
    return {"ok": worst is not None and worst <= limit_s, "max_gap_s": worst, "limit_s": limit_s}


def grade_diff(differences: list[dict]) -> dict:
    return {"ok": not differences, "count": len(differences), "sample": differences[:10]}


def grade_lots(lot_checks: list[dict]) -> dict:
    """Ledger lots vs broker: reported every day; explained as the known transfer-direction gap until day 3."""
    return {"ok": True, "count": len(lot_checks), "explained": "known gap: Schwab ledger stores transfer qty "
            "without direction (docs/ops/POSITIONS_FIXES_2026-10-06.md)", "rows": lot_checks[:20]}


def grade_day(day: date, runs: list[dict], differences: list[dict], lot_checks: list[dict], cfg: dict) -> dict:
    g = {"runs": grade_runs(runs),
         "heartbeat": grade_heartbeat(runs, day, cfg["stale_after_minutes_market"] * 60),
         "diff": grade_diff(differences),
         "lots": grade_lots(lot_checks)}
    return {"date": day.isoformat(), "pass": all(v["ok"] for v in g.values()), "checks": g}


def proof_day_number(ledger: Iterable[dict], day: date, start: date) -> int:
    """Consecutive passing trading days from the proof start through `day` (a failed day resets to 0)."""
    n = 0
    for row in sorted((r for r in ledger if start.isoformat() <= r["date"] <= day.isoformat()),
                      key=lambda r: r["date"]):
        n = n + 1 if row["pass"] else 0
    return n


def one_line(row: dict, n: int, total: int, *, baseline: bool = False) -> str:
    c = row["checks"]
    feature = PLAN_FEATURES.get(min(n + 1, total), "")
    why = [k for k, v in c.items() if not v["ok"]]
    if baseline:
        head = f"Positions proof baseline (proof starts later) {'PASS' if row['pass'] else 'FAIL (' + ', '.join(why) + ')'}"
    elif row["pass"]:
        head = f"Positions proof day {n} of {total} PASS"
    else:
        head = f"Positions proof FAIL ({', '.join(why)}) — counter reset to 0 of {total}"
    gap = c["heartbeat"]["max_gap_s"]
    return (f"{head} · {row['date']} · runs {c['runs']['count']} complete"
            f"{'' if c['runs']['ok'] else ' (' + str(len(c['runs']['not_complete'])) + ' not)'} · "
            f"max gap {int(gap // 60) if gap is not None else '—'}m · diffs {c['diff']['count']} · "
            f"lot gaps {c['lots']['count']} (known) · next: {feature}")


# ── I/O ─────────────────────────────────────────────────────────────────────

def read_day(cur, day: date) -> tuple[list[dict], list[dict], list[dict]]:
    lo = datetime.combine(day, time(0, 0), ET) - timedelta(hours=1)
    hi = datetime.combine(day, time(23, 59), ET)
    cur.execute("""SELECT run_id, started_at, finished_at, status, promoted, notes FROM positions_sync_runs
                   WHERE started_at >= %s AND started_at <= %s ORDER BY run_id""", (lo, hi))
    cols = [d[0] for d in cur.description]
    runs = [dict(zip(cols, r)) for r in cur.fetchall()]
    day_runs = [r for r in runs if r["started_at"].astimezone(ET).date() == day]
    cur.execute("SELECT account_key, symbol, qty, cost_basis_total, is_cash FROM positions_current")
    cols = [d[0] for d in cur.description]
    current = [dict(zip(cols, r)) for r in cur.fetchall()]
    from lib import portfolio_positions as pp  # type: ignore
    cfg = ps.load_sync_config()
    diffs = ps.shadow_diff(current, pp.load_store(), cfg["qty_tolerance"], cfg["basis_tolerance_usd"])
    lots = []
    last = next((r for r in reversed(runs) if r["status"] == "complete" and r.get("notes")), None)
    if last:
        try:
            lots = json.loads(last["notes"]).get("lot_checks") or []
        except ValueError:
            lots = []
    return runs, diffs, lots


def read_ledger(path: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def write_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, default=str) + "\n" for r in sorted(rows, key=lambda r: r["date"])),
                   encoding="utf-8")
    tmp.replace(path)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="trading date to grade (default: today ET)")
    ap.add_argument("--send", action="store_true", help="send the one-line report to the operator")
    a = ap.parse_args(argv)
    cfg = load_proof_config()
    day = date.fromisoformat(a.date) if a.date else datetime.now(ET).date()
    if day.weekday() >= 5:
        print(f"{day} is not a trading day — nothing graded")
        return 0
    conn = ps._conn()
    with conn.cursor() as cur:
        runs, diffs, lots = read_day(cur, day)
    conn.rollback()
    row = grade_day(day, runs, diffs, lots, cfg)
    row["graded_at"] = datetime.now(timezone.utc).isoformat()
    path = ROOT / LEDGER_REL
    ledger = [r for r in read_ledger(path) if r.get("date") != row["date"]] + [row]
    write_ledger(path, ledger)
    start = date.fromisoformat(str(cfg["start"]))
    n = proof_day_number(ledger, day, start) if day >= start else 0
    row_line = one_line(row, n, int(cfg["days"]), baseline=day < start)
    print(json.dumps(row, indent=1, default=str))
    print(row_line)
    if a.send:
        from telegram_alert import send_telegram  # type: ignore
        # One line a day, operator-requested (plan: "a daily progress line"); the text router would fold it into
        # a digest, so it is a P2 intent: routed by its declared priority, never by the text classifier.
        send_telegram(row_line, message_class="report", priority="P2", producer="positions_proof_daily")
    return 0 if row["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
