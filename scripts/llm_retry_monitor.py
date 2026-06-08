#!/usr/bin/env python3
"""llm_retry_monitor.py — track LLM transient-failure / retry rates over time.

READ-ONLY (trims its own event log). Aggregates data/runtime/llm_retry_events.jsonl (one record per LLM call
that needed >=1 retry) into daily counts: incidents, recovered (succeeded after retry), gave_up (exhausted
retries), by error_type. Writes data/runtime/llm_retry_health.json (24h/7d totals + 14-day daily trend +
status). Lets you watch network/provider transient health. No mutation beyond log trim.

  python3 scripts/llm_retry_monitor.py
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "runtime" / "llm_retry_events.jsonl"
OUT = ROOT / "data" / "runtime" / "llm_retry_health.json"
MAX_KEEP = 5000


def main():
    now = datetime.now(timezone.utc)
    rows = []
    if EVENTS.exists():
        for ln in EVENTS.read_text().splitlines():
            try:
                r = json.loads(ln); r["_t"] = datetime.fromisoformat(r["ts"]); rows.append(r)
            except Exception:
                continue
    def window(since):
        return [r for r in rows if r["_t"] >= now - since]
    d24, d7 = window(timedelta(hours=24)), window(timedelta(days=7))

    def summarize(rs):
        return {"incidents": len(rs), "recovered": sum(1 for r in rs if r.get("outcome") == "recovered"),
                "gave_up": sum(1 for r in rs if r.get("outcome") == "gave_up"),
                "by_error": dict(Counter(r.get("error_type", "?") for r in rs)),
                "by_kind": dict(Counter(r.get("kind", "?") for r in rs))}
    # daily trend (14d)
    daily = defaultdict(lambda: {"incidents": 0, "recovered": 0, "gave_up": 0})
    for r in window(timedelta(days=14)):
        k = r["_t"].strftime("%Y-%m-%d"); daily[k]["incidents"] += 1
        daily[k][r.get("outcome", "recovered")] = daily[k].get(r.get("outcome", "recovered"), 0) + 1
    trend = [{"date": d, **v} for d, v in sorted(daily.items())]

    s24 = summarize(d24)
    status = "HEALTHY"
    notes = []
    if s24["gave_up"] > 0:
        status = "DEGRADED"; notes.append(f"{s24['gave_up']} LLM call(s) gave up after retries in 24h ({s24['by_error']})")
    elif s24["incidents"] >= 20:
        status = "ELEVATED"; notes.append(f"{s24['incidents']} transient retries in 24h — network/provider flaky")
    out = {"updated_at": now.isoformat(), "status": status, "notes": notes,
           "last_24h": s24, "last_7d": summarize(d7), "trend_14d": trend,
           "note": "One incident = an LLM call that needed >=1 retry. recovered=succeeded after retry; "
                   "gave_up=exhausted retries. Success-first-try not logged. Advisory infra health only."}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    # trim the event log
    if len(rows) > MAX_KEEP:
        EVENTS.write_text("\n".join(json.dumps({k: v for k, v in r.items() if k != "_t"}) for r in rows[-MAX_KEEP:]) + "\n")
    print(json.dumps({"status": status, "last_24h": s24, "last_7d_incidents": out["last_7d"]["incidents"], "notes": notes}, indent=2))


if __name__ == "__main__":
    main()
