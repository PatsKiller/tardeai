#!/usr/bin/env python3
"""Durable proof for the weekly analyst lane (LQ-20261113-3083), for the lead's live-acceptance item ``analyst``.

Exit 0 is not evidence. A weekly analyst run is proven only by what it leaves behind:

1. the n8n coordination ledger row for the newest live fire of ``generate-analyst-reports-autonomous-weekly``
   (``data/governance/n8n_coordination_ledger.sqlite``, table ``runs``: state, exit code, duration, timed_out);
2. the report JSONs the generator rewrites for every refreshed symbol
   (``<reports>/analyst/prospectus_<SYM>_latest.json`` and ``watchlist_<SYM>_latest.json``), whose ``meta`` carries
   ``generation_mode`` (``autonomous_weekly`` / ``autonomous_weekly_watchlist``) and ``generated_at``;
3. the holdings batch log ``<reports>/analyst/prospectus/batch_*.json`` (generated / skipped / failed counts).

Verdict, printed as one JSON object; exit code 0 PASS, 1 FAIL, 2 UNPROVEN:

- PASS: the newest live fire is RUN_DONE, exit 0, within the 1800 s n8n timeout, and at least one report JSON
  stamped with a weekly generation_mode was written inside that run's window.
- FAIL: the fire failed, timed out, ran past the timeout, the holdings batch recorded failures, the run said
  RUN_DONE but left no report and no batch log in its window, or no live fire for more than 8 days.
- UNPROVEN: no live fire recorded, the fire is still running, the fire was skipped (lock held: the work, if any,
  was done by another holder, not by this fire), the run had nothing to refresh, or a store is unreadable.

Read-only: the ledger is opened ``mode=ro``; nothing is written.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LANE = "generate-analyst-reports-autonomous-weekly"
WEEKLY_MODES = frozenset({"autonomous_weekly", "autonomous_weekly_watchlist"})
TIMEOUT_S = 1800  # n8n allowlist: timeout -k 30 1800
MAX_GAP = timedelta(days=8)  # weekly lane (Sun 21:15 ET): no live fire for 8 days is a missed slot
WINDOW_SLACK = timedelta(seconds=60)
LEDGER_REL = Path("data/governance/n8n_coordination_ledger.sqlite")
REPORTS_REL = Path("data/portfolios/reports")
REPORT_GLOBS = ("prospectus_*_latest.json", "watchlist_*_latest.json")
PASS, FAIL, UNPROVEN = True, False, None


def _default_state_root() -> Path:
    for key in ("TRADEAI_STATE_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        if os.environ.get(key):
            return Path(os.environ[key])
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lib.portfolio_reports_root import state_root

        return Path(state_root())
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state"


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def newest_live_run(ledger: Path, lane: str = LANE) -> dict | None:
    """The newest live run row of the lane (any state). Raises on an unreadable ledger."""
    if not ledger.exists():
        raise FileNotFoundError(f"ledger missing: {ledger}")
    conn = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        row = conn.execute(
            "SELECT run_id, state, requested_at, started_at, finished_at, exit_code, duration_s, "
            "json_extract(receipt_json, '$.timed_out'), json_extract(receipt_json, '$.reason'), "
            "json_extract(receipt_json, '$.code_sha') "
            "FROM runs WHERE lane_id = ? AND mode = 'live' ORDER BY requested_at DESC LIMIT 1",
            (lane,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    keys = ("run_id", "state", "requested_at", "started_at", "finished_at", "exit_code", "duration_s",
            "timed_out", "reason", "code_sha")
    return dict(zip(keys, row))


def reports_written(analyst_dir: Path, start: datetime, end: datetime) -> tuple[list[dict], list[str]]:
    """Report JSONs whose meta says a weekly generation wrote them inside [start, end]. Second item: unreadable files."""
    out: list[dict] = []
    unreadable: list[str] = []
    for pattern in REPORT_GLOBS:
        for path in sorted(glob.glob(str(analyst_dir / pattern))):
            try:
                with open(path, encoding="utf-8") as fh:
                    meta = (json.load(fh) or {}).get("meta") or {}
            except (OSError, ValueError):
                unreadable.append(Path(path).name)
                continue
            mode = meta.get("generation_mode")
            at = _ts(meta.get("generated_at"))
            if mode in WEEKLY_MODES and at is not None and start <= at <= end:
                out.append({"file": Path(path).name, "generation_mode": mode, "generated_at": at.isoformat()})
    return out, unreadable


def holdings_batch(analyst_dir: Path, start: datetime, end: datetime) -> dict | None:
    """Newest holdings batch log whose completed_at falls inside [start, end], as counts."""
    best: tuple[datetime, dict] | None = None
    for path in glob.glob(str(analyst_dir / "prospectus" / "batch_*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh) or {}
        except (OSError, ValueError):
            continue
        at = _ts(doc.get("completed_at"))
        if at is None or not (start <= at <= end):
            continue
        if best is None or at > best[0]:
            counts = {k: len(doc.get(k) or []) for k in ("generated", "skipped", "failed", "blocked")}
            best = (at, {"file": Path(path).name, "completed_at": at.isoformat(), "eligible": doc.get("eligible"), **counts})
    return best[1] if best else None


def verdict(run: dict | None, analyst_dir: Path, now: datetime) -> tuple[bool | None, dict]:
    if run is None:
        return UNPROVEN, {"why": f"no live run of {LANE} in the n8n ledger"}
    ev: dict[str, Any] = {k: run.get(k) for k in ("run_id", "state", "requested_at", "started_at", "finished_at",
                                                  "exit_code", "duration_s", "timed_out", "reason")}
    requested = _ts(run.get("requested_at")) or _ts(run.get("started_at"))
    if requested is not None and now - requested > MAX_GAP:
        ev["why"] = f"newest live fire is {(now - requested).days} d old: the weekly slot was missed"
        return FAIL, ev
    state = str(run.get("state") or "")
    started, finished = _ts(run.get("started_at")), _ts(run.get("finished_at"))
    if state == "RUN_SKIPPED_LOCK":
        ev["why"] = ("the n8n fire was skipped: lock held by another holder; whatever that holder wrote is not "
                     "proof that this fire completes inside the n8n timeout")
        return UNPROVEN, ev
    if finished is None:
        ev["why"] = f"fire not finished (state {state or 'unknown'})"
        return UNPROVEN, ev
    if state != "RUN_DONE" or run.get("timed_out") in (1, True, "true"):
        ev["why"] = f"fire ended {state} (exit {run.get('exit_code')}, timed_out {run.get('timed_out')})"
        return FAIL, ev
    if run.get("exit_code") not in (0, None):
        ev["why"] = f"RUN_DONE with exit {run.get('exit_code')}"
        return FAIL, ev
    duration = run.get("duration_s")
    if duration is None and started is not None:
        duration = (finished - started).total_seconds()
    if duration is not None and float(duration) > TIMEOUT_S:
        ev["why"] = f"ran {float(duration):.0f} s, over the {TIMEOUT_S} s n8n timeout"
        return FAIL, ev
    lo = (started or finished) - WINDOW_SLACK
    hi = finished + WINDOW_SLACK
    reports, unreadable = reports_written(analyst_dir, lo, hi)
    batch = holdings_batch(analyst_dir, lo, hi)
    ev.update({"reports_written": len(reports), "reports_sample": reports[:5], "holdings_batch": batch,
               "unreadable_reports": unreadable[:10]})
    if batch and (batch.get("failed") or batch.get("blocked")):
        ev["why"] = f"holdings batch recorded {batch['failed']} failed, {batch['blocked']} blocked"
        return FAIL, ev
    if reports:
        ev["why"] = f"{len(reports)} report(s) written by the weekly generation inside the run window"
        return PASS, ev
    if unreadable:
        ev["why"] = f"no weekly report found and {len(unreadable)} report file(s) unreadable"
        return UNPROVEN, ev
    if batch and not batch.get("generated"):
        ev["why"] = "the run had nothing to refresh (holdings batch generated 0, failed 0): output 0, not proven"
        return UNPROVEN, ev
    ev["why"] = "RUN_DONE exit 0 but no weekly report and no batch log in the run window (exit 0 is not evidence)"
    return FAIL, ev


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state-root", type=Path, default=None)
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--reports-root", type=Path, default=None, help="directory holding analyst/")
    ap.add_argument("--now", default=None, help="ISO time (tests)")
    args = ap.parse_args(argv)
    root = args.state_root or _default_state_root()
    ledger = args.ledger or root / LEDGER_REL
    analyst_dir = (args.reports_root or root / REPORTS_REL) / "analyst"
    now = _ts(args.now) if args.now else datetime.now(timezone.utc)
    try:
        run = newest_live_run(ledger)
    except (OSError, sqlite3.Error) as exc:
        ok, ev = UNPROVEN, {"why": f"ledger unreadable: {type(exc).__name__}: {exc}"}
    else:
        ok, ev = verdict(run, analyst_dir, now)
    ev = {"verdict": {PASS: "PASS", FAIL: "FAIL", UNPROVEN: "UNPROVEN"}[ok], "lane": LANE, **ev}
    print(json.dumps(ev, default=str))
    return {PASS: 0, FAIL: 1, UNPROVEN: 2}[ok]


if __name__ == "__main__":
    sys.exit(main())
