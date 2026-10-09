#!/usr/bin/env python3
"""run_trade_ai_scalp_live.py — Trade-AI scalp scan every 5 minutes in RTH (operator 2026-10-09).

"these are scalps should be every 5 minutes at least … same should be feeding both tradeai and also active trader".

One deterministic live cycle (continuous_runner.run_live_cycle; no paid LLM — catalysts come from the 20-minute
catalyst cache / local enrichment) over the scalp screeners only (assets/screeners.yaml run window `scalp`),
written to trade_ai_scans under its own run_label `scalp` so it never merges with the slot runs. Scoring is the
same score_all as every other run, so GO rules (incl. the 40+-with-catalyst runner GO) are identical.

The cycle's "already GO / already alerted" memory is saved between runs (persistent state, reset each day), so a
GO alerts once, not every 5 minutes. Market-day gated by the cron wrapper; outside 09:30-16:00 ET it exits.

    python3 scripts/run_trade_ai_scalp_live.py            # one cycle (cron: */5 9-15 * * 1-5)
    python3 scripts/run_trade_ai_scalp_live.py --force    # ignore the RTH window (testing)
    python3 scripts/run_trade_ai_scalp_live.py --dry-run  # plan only: no scan, no write, no send (n8n shadow)

Every completed run (a cycle, or an outside-RTH exit) writes the receipt
$TRADEAI_STATE_ROOT/data/runtime/trade_ai_scalp_live_last.json (TradeAIScalpLiveReceipt@v1): the n8n run
executor's output_signal and the incident fan-in's stall source (last_ok_at older than 12 min in RTH).

Every RTH cycle also appends ScalpCycleReceipt@v1 records (scripts/lib/scalp_cycle_receipt.py) to
$TRADEAI_STATE_ROOT/data/runtime/scalp_cycle_receipts/<day>.jsonl: ``started`` before any work, then ``ok`` /
``error`` / ``killed`` (SIGTERM from the 295 s timeout) with the phase reached, symbols scanned, signals, alerts
sent/deduped and the budget used. A ``started`` with no final record is a cycle lost to SIGKILL. Log lines are
line-buffered and timestamped, so a killed cycle no longer vanishes from the log (n8n maturity B4, 2026-10-09).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

def _process_age_s() -> float:
    """Seconds since this PID started. market_day_gate.sh `exec`s python, so the PID is the one `timeout` spawned:
    its start is when the 295 s cron/executor clock started (gate + interpreter start-up included)."""
    try:
        with open("/proc/self/stat", encoding="ascii") as fh:
            start_ticks = int(fh.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/uptime", encoding="ascii") as fh:
            uptime_s = float(fh.read().split()[0])
        age = uptime_s - start_ticks / os.sysconf("SC_CLK_TCK")
        return age if 0 <= age < 3600 else 0.0
    except Exception:  # noqa: BLE001 — non-Linux / no procfs: count from module import
        return 0.0


# Monotonic instant the process started: the per-cycle deadline counts from here, not from enrichment.
PROCESS_T0 = time.monotonic() - _process_age_s()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

ET = ZoneInfo("America/New_York")
RUN_LABEL = "scalp"
RTH = ((9, 30), (16, 0))


def _state_root() -> Path:
    from scalp_cycle_receipt import state_root

    return state_root()


def projection_path() -> Path:
    """The shared scalp universe both engines read (one Finviz pull, one writer: this lane)."""
    return _state_root() / "data" / "trade_ai" / "scalp_universe_latest.json"


def write_projection(scored, now: datetime) -> int:
    rows = [{"symbol": str(t.get("symbol") or "").upper(), "decision": t.get("decision"), "score": t.get("score"),
             "float_m": t.get("float_m"), "price": t.get("price"), "setup_class": t.get("setup_class")}
            for t in (scored or []) if t.get("symbol")]
    p = projection_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema": "TradeAIScalpUniverse@v1", "as_of": now.isoformat(), "run_label": RUN_LABEL,
                               "writer": "run_trade_ai_scalp_live", "rows": rows}), encoding="utf-8")
    tmp.replace(p)
    return len(rows)


def state_path() -> Path:
    return _state_root() / "state" / "trade_ai_scalp_live_state.json"


def receipt_path() -> Path:
    return _state_root() / "data" / "runtime" / "trade_ai_scalp_live_last.json"


def write_receipt(status: str, now: datetime, *, universe: int | None = None, go: int | None = None,
                  seconds: float | None = None) -> dict:
    """Atomic receipt. last_ok_at carries over from the previous receipt until a cycle completes again."""
    p = receipt_path()
    try:
        prev = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — first run or a torn file: no previous ok
        prev = {}
    doc = {"schema": "TradeAIScalpLiveReceipt@v1", "lane_id": "trade-ai-scalp-live", "as_of": now.isoformat(),
           "status": status, "run_label": RUN_LABEL, "universe": universe, "go": go,
           "seconds": None if seconds is None else round(seconds, 1),
           "last_ok_at": now.isoformat() if status == "ok" else prev.get("last_ok_at")}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
    return doc


def dry_run_plan(now: datetime) -> dict:
    """What a live run would do, read-only: no scan, no state/projection/receipt write, no send."""
    def _age_min(path: Path, key: str):
        try:
            then = datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8"))[key])
            return round((now - then).total_seconds() / 60, 1)
        except Exception:  # noqa: BLE001 — missing/torn file reads as unknown
            return None
    rth = in_rth(now)
    return {"mode": "dry_run", "now": now.isoformat(), "in_rth": rth, "run_label": RUN_LABEL,
            "would": ("run_live_cycle(publish_dashboard=False) + state + projection + receipt" if rth
                      else "exit outside RTH (receipt status outside_rth)"),
            "projection_age_min": _age_min(projection_path(), "as_of"),
            "last_ok_age_min": _age_min(receipt_path(), "last_ok_at")}


def in_rth(now: datetime) -> bool:
    """Regular session per scripts/market_session (holidays and 13:00 early closes included); the fixed
    09:30-16:00 window only if the calendar cannot be read."""
    try:
        from market_session import current_market_session

        return current_market_session(now) == "regular"
    except Exception:  # noqa: BLE001 — a broken calendar falls back to the fixed window
        m = now.hour * 60 + now.minute
        return RTH[0][0] * 60 + RTH[0][1] <= m < RTH[1][0] * 60 + RTH[1][1]


def load_state(day: str):
    from continuous_runner import CycleState

    try:
        d = json.loads(state_path().read_text(encoding="utf-8"))
        if d.get("date") == day:
            return CycleState.from_dict(d.get("state") or {})
    except Exception:  # noqa: BLE001 — a missing/old state is a fresh day
        pass
    return CycleState()


def save_state(day: str, st) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"date": day, "saved_at": datetime.now(ET).isoformat(), "state": st.to_dict()}),
                   encoding="utf-8")
    tmp.replace(p)


def enrich_budget() -> Optional[float]:
    """Seconds of catalyst lookups per cycle (config/trade_ai_scalp_lane.yaml); None = unbounded."""
    try:
        import yaml

        v = (yaml.safe_load((ROOT / "config" / "trade_ai_scalp_lane.yaml").read_text(encoding="utf-8")) or {}).get(
            "enrich_budget_s")
        return float(v) if v else None
    except Exception:
        return None


def post_enrich_reserve() -> float:
    """Seconds kept for scoring + persist + send after catalyst lookups (config post_enrich_reserve_s)."""
    try:
        import yaml

        v = (yaml.safe_load((ROOT / "config" / "trade_ai_scalp_lane.yaml").read_text(encoding="utf-8")) or {}).get(
            "post_enrich_reserve_s")
        return float(v) if v is not None else 100.0
    except Exception:  # noqa: BLE001
        return 100.0


def cycle_deadline() -> float:
    """Hard per-cycle deadline in seconds (config/trade_ai_scalp_lane.yaml cycle_deadline_s; the cron timeout)."""
    try:
        import yaml

        v = (yaml.safe_load((ROOT / "config" / "trade_ai_scalp_lane.yaml").read_text(encoding="utf-8")) or {}).get(
            "cycle_deadline_s")
        return float(v) if v else 295.0
    except Exception:  # noqa: BLE001 — unreadable config keeps the cron line's timeout
        return 295.0


def _cycle_receipt(status: str, day: str, slot: str, t0: datetime, stats: dict, *, deadline_s: float,
                   enrich_s: Optional[float], go_before: set, finished: Optional[datetime] = None,
                   extra_errors: tuple = ()) -> None:
    """Append one ScalpCycleReceipt@v1 record; a ledger failure never breaks the cycle."""
    try:
        import scalp_cycle_receipt as scr

        go_now = set(stats.get("go_now") or ())
        triggers = stats.get("triggers")
        scr.append(scr.build(
            status, day=day, slot=slot, started_at=t0, finished_at=finished, phase=stats.get("phase"),
            symbols_scanned=stats.get("symbols_scanned"), signals=stats.get("signals"), triggers=triggers,
            alerts_sent=(None if triggers is None else (int(triggers) if stats.get("alert_sent") else 0)),
            alerts_deduped=len(go_now & go_before) if status == "ok" else None,
            deadline_s=deadline_s, enrich_budget_s=enrich_s,
            errors=list(stats.get("errors") or []) + list(extra_errors), phase_s=stats.get("phase_s"),
            budget_skips=stats.get("budget_skips") or (), release=ROOT.name))
    except Exception as e:  # noqa: BLE001 — the receipt is evidence, not a dependency of the cycle
        print(f"[scalp-live] cycle receipt write failed: {type(e).__name__}: {e}")


def bulk_catalysts() -> Optional[dict]:
    """`catalysts` block of config/trade_ai_scalp_lane.yaml (bulk catalyst read); None when absent."""
    from scalp_catalyst_bulk import load_config

    return load_config(ROOT) or None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="run outside 09:30-16:00 ET")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; no scan, write or send")
    a = ap.parse_args(argv)
    try:  # cron appends stdout to a file: block buffering lost every line of a killed cycle
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001 — a replaced stream without reconfigure keeps its buffering
        pass
    now = datetime.now(ET)
    if a.dry_run:
        print(f"[scalp-live] dry-run {json.dumps(dry_run_plan(now), sort_keys=True)}")
        return 0
    if not a.force and not in_rth(now):
        print(f"[scalp-live] {now:%H:%M} ET outside RTH — nothing to do")
        write_receipt("outside_rth", now)
        return 0
    import scalp_cycle_receipt as scr

    day = now.date().isoformat()
    slot = scr.slot_of(now)
    if not a.force and scr.fold(scr.read_day(day)).get(slot, {}).get("status") == "ok":
        # cron and n8n share the flock, which stops two cycles at once but not two in a row in one slot
        print(f"[scalp-live] {now:%H:%M:%S} ET slot {slot} already has an ok cycle — skipped (slot done)")
        return 0
    deadline_s, enrich_s = cycle_deadline(), enrich_budget()
    stats: dict = {"phase": "start", "errors": []}
    t0 = datetime.now(ET)
    go_before: set = set()
    print(f"[scalp-live] {t0:%Y-%m-%d %H:%M:%S} ET cycle start slot={slot} pid={os.getpid()} release={ROOT.name}")
    _cycle_receipt("started", day, slot, t0, stats, deadline_s=deadline_s, enrich_s=enrich_s, go_before=go_before)

    def _on_term(signum, _frame):  # the cron/executor timeout: record the kill before dying
        _cycle_receipt("killed", day, slot, t0, stats, deadline_s=deadline_s, enrich_s=enrich_s,
                       go_before=go_before, finished=datetime.now(ET), extra_errors=(f"signal {signum}",))
        try:
            write_receipt(scr.LEGACY_STATUS["killed"], datetime.now(ET),
                          seconds=(datetime.now(ET) - t0).total_seconds())
        except Exception:  # noqa: BLE001 — dying anyway; the ledger record above is the evidence
            pass
        print(f"[scalp-live] {datetime.now(ET):%H:%M:%S} ET killed by signal {signum} in phase "
              f"{stats.get('phase')} after {(datetime.now(ET) - t0).total_seconds():.0f}s")
        os._exit(128 + int(signum))

    prev_handler = None
    try:
        prev_handler = signal.signal(signal.SIGTERM, _on_term)
    except (ValueError, OSError):  # not the main thread: no handler, the receipt still covers ok/error
        pass
    try:
        return _run_cycle(day, slot, now, t0, stats, deadline_s, enrich_s, go_before, PROCESS_T0 + deadline_s)
    finally:
        if prev_handler is not None:
            signal.signal(signal.SIGTERM, prev_handler)


def _run_cycle(day: str, slot: str, now: datetime, t0: datetime, stats: dict, deadline_s: float,
               enrich_s: Optional[float], go_before: set, deadline_mono: Optional[float] = None) -> int:
    import scalp_cycle_receipt as scr

    def _failed(reason: str) -> int:
        # #1589 fail-closed: no state save, no projection, no heartbeat; last_ok_at is carried, not advanced.
        finished = datetime.now(ET)
        _cycle_receipt("error", day, slot, t0, stats, deadline_s=deadline_s, enrich_s=enrich_s, go_before=go_before,
                       finished=finished, extra_errors=(reason,))
        write_receipt(scr.LEGACY_STATUS["error"], finished, seconds=(finished - t0).total_seconds())
        print(f"[scalp-live] cycle failed label={RUN_LABEL}: {reason} (phase {stats.get('phase')}, "
              f"at={finished:%Y-%m-%dT%H:%M:%S}, slot={slot})", file=sys.stderr)
        return 1

    try:
        from continuous_runner import run_live_cycle

        st = load_state(day)
        go_before.update(st.prev_go)
        scored = run_live_cycle(ROOT, RUN_LABEL, day, st, now.strftime("%H:%M"), publish_dashboard=False,
                                enrich_budget_s=enrich_s, bulk_catalysts=bulk_catalysts(), cycle_stats=stats,
                                state_saver=lambda s: save_state(day, s), deadline_monotonic=deadline_mono,
                                post_enrich_reserve_s=post_enrich_reserve())
    except Exception as e:  # noqa: BLE001 — record the failure, then let cron see a non-zero exit
        return _failed(f"{type(e).__name__}: {e}")
    if not isinstance(scored, list) or any(not isinstance(row, dict) for row in scored):
        return _failed("no valid scored result")
    stats["go_now"] = sorted(st.prev_go)
    save_state(day, st)
    n = write_projection(scored, datetime.now(ET))     # a completed empty cycle publishes a known-empty result
    finished = datetime.now(ET)
    secs = (finished - t0).total_seconds()
    _cycle_receipt("ok", day, slot, t0, stats, deadline_s=deadline_s, enrich_s=enrich_s, go_before=go_before,
                   finished=finished)
    write_receipt(scr.LEGACY_STATUS["ok"], finished, universe=n, go=len(st.prev_go), seconds=secs)
    print(f"[scalp-live] heartbeat ok label={RUN_LABEL} go={len(st.prev_go)} universe={n} seconds={secs:.0f} "
          f"budget_pct={100 * secs / deadline_s:.0f} at={finished:%Y-%m-%dT%H:%M:%S} slot={slot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
