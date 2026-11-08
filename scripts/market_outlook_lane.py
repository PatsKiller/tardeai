#!/usr/bin/env python3
"""market-outlook-weekly lane entry (LQ-20261107-1122; FABLE-OUTLOOK-METHODOLOGY-LQ-946 §4.1/§4.7).

The n8n dispatcher fires this lane Sun 20:00 ET and Mon 07:00 ET. One run is two existing steps, in order:

1. the engine, ``scripts/market_outlook_evaluate.py --mode <mode>``: ``--apply`` on a live run (writes the
   record row, ``data/runtime/market_outlook/{latest,run_last}.json``), ``--dry-run`` otherwise;
2. the brief, ``scripts/market_outlook_brief.py`` on THAT record: live = ``--deliver --record <record_id>``
   (email + Telegram + Fi text, deduped per ``record_id:channel``); dry = ``--dry-run --record-file <tmp>``,
   so a dry run renders the record it just evaluated and writes nothing durable.

A live re-fire for the same ET day + mode (an executor retry, a manual rerun) reuses the stored record: the lane
reads the newest ``outlook:<day>:<mode>:<n>`` read-only, skips the engine, and runs ``--deliver --record <id>``,
so only unsent channels go out and no ``:<n+1>`` is minted (LQ-20261107-1177). A failed lookup refuses the run.

The brief owns the lane's LANE_OUTPUT line and LaneRunReceipt@v2. This file only adds the refusal for a step
that never reached the brief (engine failed, record id missing), so a broken engine is a refused run with a
named reason, not a silent success.

Mode comes from the ET clock: Sunday -> ``sunday``, Monday -> ``monday``. Any other day is refused unless
``--mode`` is passed (a manual run). Advisory only: nothing here sizes, orders, stops, weights or writes to a
broker (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (PROJECT_ROOT, PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LANE_ID = "market-outlook-weekly"
SCRIPT_REL = "scripts/market_outlook_lane.py"
RECEIPT_REL = f"data/runtime/{LANE_ID}_last.json"
ET = ZoneInfo("America/New_York")
MODE_BY_WEEKDAY = {6: "sunday", 0: "monday"}  # datetime.weekday(): Mon=0 .. Sun=6
ENGINE_TIMEOUT_S = 240
BRIEF_TIMEOUT_S = 240

Runner = Callable[[Sequence[str], int], "subprocess.CompletedProcess[str]"]


def _run(argv: Sequence[str], timeout: int) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout,
                          check=False)


def mode_for(now: datetime) -> Optional[str]:
    """The scheduled mode for an instant, read on the ET calendar; None off the Sun/Mon schedule."""
    return MODE_BY_WEEKDAY.get(now.astimezone(ET).weekday())


def _state_root(override: Optional[str]) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415 — call time

    return good_persistent_root()


def _refuse(reason: str, *, live: bool, started: str, state_root: Path, exit_code: int,
            summary: Optional[dict[str, Any]] = None) -> int:
    """A run that never reached the brief: one LANE_OUTPUT refusal, and on a live run the v2 receipt."""
    print(f"{LANE_ID}: {reason}", file=sys.stderr)
    from lib import lane_output  # noqa: PLC0415

    lane_output.emit(LANE_ID, "live" if live else "dry_run", lane_output.output_block(
        produced=0, attempted=1, skipped={"refused": 1}, empty_reason=reason[:120], unit="briefs"),
        started_at=started)
    if live:
        from lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415

        write_lane_receipt(LANE_ID, ok=False, exit_code=exit_code, started_at=started, script=SCRIPT_REL,
                           summary=summary or {}, error=reason, path=state_root / RECEIPT_REL, produced_count=0,
                           attempted_count=1, skipped_reasons={"refused": 1}, empty_reason=reason[:120])
    return exit_code


def _tail(text: str, n: int = 400) -> str:
    return (text or "").strip()[-n:]


Lookup = Callable[[str, str], Optional[str]]


def newest_record_id(day: str, mode: str) -> Optional[str]:
    """The newest ``outlook:<day>:<mode>:<n>`` record id already stored, or None (LQ-20261107-1177).

    Read-only: the engine's own reader (``sources._app_conn`` sets the session read-only), one SELECT. Newest is
    the largest numeric suffix, compared as a number so ``:10`` beats ``:9``. Any error propagates: the caller
    refuses rather than guessing that no record exists."""
    from scripts.lib.market_outlook import sources  # noqa: PLC0415 — call time; tests inject a fake

    conn = sources._app_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT record_id FROM market_outlook_records WHERE record_id LIKE %s",
                        [f"outlook:{day}:{mode}:%"])
            ids = [str(r[0]) for r in cur.fetchall()]
        finally:
            cur.close()
    finally:
        conn.close()

    def _n(rid: str) -> int:
        tail = rid.rsplit(":", 1)[-1]
        return int(tail) if tail.isdigit() else -1

    return max(ids, key=_n) if ids else None


def main(argv: Optional[list[str]] = None, *, runner: Runner = _run, now: Optional[datetime] = None,
         lookup: Optional[Lookup] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--deliver", dest="live", action="store_true", help="apply the record and deliver the brief")
    g.add_argument("--dry-run", dest="live", action="store_false", help="evaluate and render only (default)")
    ap.set_defaults(live=False)
    ap.add_argument("--mode", choices=("sunday", "monday", "daily"),
                    help="override the clock's mode (manual run); default: Sun -> sunday, Mon -> monday")
    ap.add_argument("--channels", default="email,telegram,text")
    ap.add_argument("--state-root", help="state root override (tests)")
    args = ap.parse_args(argv)

    now = now or datetime.now(timezone.utc)
    started = now.isoformat()
    state_root = _state_root(args.state_root)
    mode = args.mode or mode_for(now)
    if mode is None:
        return _refuse(f"off schedule: {now.astimezone(ET):%a %H:%M} ET is not a Sunday or Monday run; pass --mode",
                       live=args.live, started=started, state_root=state_root, exit_code=2)

    py = sys.executable
    if args.live:
        # LQ-20261107-1177: a re-fire for the same ET day + mode (executor retry, manual rerun) must not mint
        # ``:<n+1>`` and resend. If the day's record exists, skip the engine and hand the brief that record: its
        # per ``record_id:channel`` dedupe sends only the channels that have not gone out yet.
        day = now.astimezone(ET).date().isoformat()  # the engine's own day (market_outlook_evaluate._seq)
        try:
            existing = (lookup or newest_record_id)(day, mode)
        except Exception as exc:  # noqa: BLE001 — an unproven "no record" must not mint a duplicate
            return _refuse(f"record lookup failed for outlook:{day}:{mode}: {type(exc).__name__}: {exc}"[:240],
                           live=True, started=started, state_root=state_root, exit_code=3, summary={"mode": mode})
        if existing:
            print(f"{LANE_ID}: {existing} already recorded for {day} {mode}; engine skipped, "
                  f"delivering unsent channels only")
            return _brief(py, args.channels, state_root, existing, runner=runner, started=started, mode=mode)

    engine = [py, str(PROJECT_ROOT / "scripts/market_outlook_evaluate.py"), "--mode", mode,
              "--apply" if args.live else "--dry-run", "--json", "--state-root", str(state_root)]
    try:
        eng = runner(engine, ENGINE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _refuse(f"engine timed out after {ENGINE_TIMEOUT_S}s", live=args.live, started=started,
                       state_root=state_root, exit_code=3, summary={"mode": mode})
    if eng.stderr:
        sys.stderr.write(eng.stderr)
    try:
        payload = json.loads(eng.stdout or "")
        record = payload["record"]
        record_id = str(record["record_id"])
    except (ValueError, KeyError, TypeError):
        return _refuse(f"engine rc {eng.returncode}, no record: {_tail(eng.stderr, 160) or 'empty output'}",
                       live=args.live, started=started, state_root=state_root, exit_code=3, summary={"mode": mode})
    if eng.returncode != 0:
        problems = payload.get("problems") or (payload.get("apply") or {}).get("refused") or []
        return _refuse(f"engine rc {eng.returncode} for {record_id}: {'; '.join(map(str, problems))[:200]}",
                       live=args.live, started=started, state_root=state_root, exit_code=3,
                       summary={"mode": mode, "record_id": record_id})
    print(f"{LANE_ID}: engine {'applied' if args.live else 'evaluated'} {record_id} "
          f"(S {record.get('score')}, {record.get('band')}, mode {mode})")

    if args.live:
        return _brief(py, args.channels, state_root, record_id, runner=runner, started=started, mode=mode)
    fd, name = tempfile.mkstemp(prefix="market-outlook-record-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh, default=str)
    tmp = Path(name)
    try:
        return _brief(py, args.channels, state_root, record_id, runner=runner, started=started, mode=mode,
                      record_file=tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _brief(py: str, channels: str, state_root: Path, record_id: str, *, runner: Runner, started: str, mode: str,
           record_file: Optional[Path] = None) -> int:
    """Run the brief on one record: live = ``--deliver --record <id>``; dry = ``--dry-run --record-file <tmp>``."""
    live = record_file is None
    argv = [py, str(PROJECT_ROOT / "scripts/market_outlook_brief.py"), "--channels", channels,
            "--state-root", str(state_root)]
    argv += ["--deliver", "--record", record_id] if live else ["--dry-run", "--record-file", str(record_file)]
    try:
        out = runner(argv, BRIEF_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _refuse(f"brief timed out after {BRIEF_TIMEOUT_S}s for {record_id}", live=live, started=started,
                       state_root=state_root, exit_code=3, summary={"mode": mode, "record_id": record_id})
    # The brief's own LANE_OUTPUT line (stderr) is what the executor grades, so both streams pass through unchanged.
    sys.stdout.write(out.stdout or "")
    sys.stderr.write(out.stderr or "")
    return out.returncode


if __name__ == "__main__":
    raise SystemExit(main())
