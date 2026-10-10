#!/usr/bin/env python3
"""llm_retry_monitor.py — track LLM transient-failure / retry rates over time.

READ-ONLY (trims its own event log). Aggregates data/runtime/llm_retry_events.jsonl (one record per LLM call
that needed >=1 retry) into daily counts: incidents, recovered (succeeded after retry), gave_up (exhausted
retries), by error_type. Writes data/runtime/llm_retry_health.json (24h/7d totals + 14-day daily trend +
status). Lets you watch network/provider transient health. No mutation beyond log trim.

  python3 scripts/llm_retry_monitor.py              # aggregate + trim (the cron form, unchanged)
  python3 scripts/llm_retry_monitor.py --no-trim    # aggregate only (dispatcher live form)
  python3 scripts/llm_retry_monitor.py --trim-only  # hygiene step: trim only
  python3 scripts/llm_retry_monitor.py --dry-run    # report both; write nothing

Refactor wave 1 (2026-10-10): the destructive trim (it rewrites the shared event log that llm_net.py
appends to) is split into its own step so a dispatcher can run the monitor without destructive retention
(config/n8n_run_allowlist.json blocked_reasons). The no-flag default still does both, so the cron line is
unchanged. --dry-run computes the health document and the trim count and returns before either write.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _runtime_dir() -> Path:
    """data/runtime on the persistent state root (the release symlinks it there), never a checkout copy."""
    try:
        from lib.persistent_state_root import resolve_durable_dir

        return resolve_durable_dir("data/runtime", ROOT)
    except Exception:  # noqa: BLE001 -- resolution layer unavailable: the code tree (old behaviour)
        return ROOT / "data" / "runtime"


EVENTS = _runtime_dir() / "llm_retry_events.jsonl"
OUT = _runtime_dir() / "llm_retry_health.json"
MAX_KEEP = 5000
RECEIPT_NAME = "llm_retry_monitor"


def load_rows(events: Path) -> list:
    rows = []
    if events.exists():
        for ln in events.read_text().splitlines():
            try:
                r = json.loads(ln)
                r["_t"] = datetime.fromisoformat(r["ts"])
                rows.append(r)
            except Exception:
                continue
    return rows


def build_health(rows: list, now: datetime) -> dict:
    def window(since):
        return [r for r in rows if r["_t"] >= now - since]

    d24, d7 = window(timedelta(hours=24)), window(timedelta(days=7))

    def summarize(rs):
        return {
            "incidents": len(rs),
            "recovered": sum(1 for r in rs if r.get("outcome") == "recovered"),
            "gave_up": sum(1 for r in rs if r.get("outcome") == "gave_up"),
            "by_error": dict(Counter(r.get("error_type", "?") for r in rs)),
            "by_kind": dict(Counter(r.get("kind", "?") for r in rs)),
        }

    # daily trend (14d)
    daily = defaultdict(lambda: {"incidents": 0, "recovered": 0, "gave_up": 0})
    for r in window(timedelta(days=14)):
        k = r["_t"].strftime("%Y-%m-%d")
        daily[k]["incidents"] += 1
        daily[k][r.get("outcome", "recovered")] = daily[k].get(r.get("outcome", "recovered"), 0) + 1
    trend = [{"date": d, **v} for d, v in sorted(daily.items())]

    s24 = summarize(d24)
    status = "HEALTHY"
    notes = []
    if s24["gave_up"] > 0:
        status = "DEGRADED"
        notes.append(f"{s24['gave_up']} LLM call(s) gave up after retries in 24h ({s24['by_error']})")
    elif s24["incidents"] >= 20:
        status = "ELEVATED"
        notes.append(f"{s24['incidents']} transient retries in 24h — network/provider flaky")
    return {
        "updated_at": now.isoformat(),
        "status": status,
        "notes": notes,
        "last_24h": s24,
        "last_7d": summarize(d7),
        "trend_14d": trend,
        "note": "One incident = an LLM call that needed >=1 retry. recovered=succeeded after retry; "
        "gave_up=exhausted retries. Success-first-try not logged. Advisory infra health only.",
    }


def trim_plan(rows: list) -> int:
    """How many parsed rows a trim would drop (oldest first)."""
    return max(0, len(rows) - MAX_KEEP)


def write_trim(events: Path, rows: list) -> None:
    events.write_text("\n".join(json.dumps({k: v for k, v in r.items() if k != "_t"}) for r in rows[-MAX_KEEP:]) + "\n")


def _summary_line(out: dict) -> dict:
    return {
        "status": out["status"],
        "last_24h": out["last_24h"],
        "last_7d_incidents": out["last_7d"]["incidents"],
        "notes": out["notes"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM retry health monitor")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--no-trim", action="store_true", help="aggregate only; never rewrite the event log")
    mode.add_argument("--trim-only", action="store_true", help="hygiene step: trim the event log only")
    ap.add_argument("--dry-run", action="store_true", help="report what would be written/trimmed; write nothing")
    a = ap.parse_args(argv)
    do_health = not a.trim_only
    do_trim = not a.no_trim

    events, out_path = EVENTS, OUT
    now = datetime.now(timezone.utc)
    rows = load_rows(events)
    out = build_health(rows, now) if do_health else None
    would_drop = trim_plan(rows) if do_trim else 0

    if a.dry_run:
        report = {
            "mode": "dry_run",
            "events": str(events),
            "rows_parsed": len(rows),
            "would_write": str(out_path) if do_health else None,
            "would_trim": (
                {"path": str(events), "drop": would_drop, "keep": min(len(rows), MAX_KEEP)} if do_trim else None
            ),
        }
        if out is not None:
            report.update(_summary_line(out))
        print(json.dumps(report, indent=2))
        return 0  # returns before either write is reachable (AGENTS.md §6)

    from lib.lane_last_receipt import write_receipt

    name = RECEIPT_NAME + ("_trim" if a.trim_only else "")
    try:
        if do_health:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(out, indent=2))
        # trim the event log
        if do_trim and would_drop:
            write_trim(events, rows)
    except Exception as exc:
        write_receipt(name, ok=False, started_at=now.isoformat(), error=f"{type(exc).__name__}: {exc}")
        raise
    write_receipt(
        name,
        ok=True,
        started_at=now.isoformat(),
        summary={"status": out["status"] if out else None, "rows_parsed": len(rows), "trimmed": would_drop},
    )
    if out is not None:
        print(json.dumps(_summary_line(out), indent=2))
    else:
        print(json.dumps({"trimmed": would_drop, "kept": min(len(rows), MAX_KEEP)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
