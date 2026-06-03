#!/usr/bin/env python3
"""Log error scraper → alert_events (so file-only failures reach SIEM).

Many failures only ever hit logs/*.log (youtube 429s, ollama 503s, tracebacks, cron stderr)
and are invisible to the SIEM dashboard. This tails a curated set of logs, extracts critical
error lines, and writes deduped rows into alert_events (which the SIEM endpoint unions).

Dedup: skip if the same (source, signature) was written in the last 25 min, so a log that
spews the same error repeatedly produces at most one SIEM row per window.

Cron: every 20 min.
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
LOGS = PROJECT_ROOT / "logs"

# (filename, default severity). Tail-scanned for the patterns below.
WATCH = [
    ("youtube_ingest.log", "warning"), ("atm.log", "critical"),
    ("hermes_coordinator.log", "warning"), ("watchlist_agent_jobs.log", "warning"),
    ("aegis_overnight.log", "warning"), ("drive-sync.log", "warning"),
    ("taxonomy_tagger.log", "info"), ("catalyst_momentum_engine.log", "warning"),
]
PATTERNS = [
    (re.compile(r"connection already closed|InterfaceError|OperationalError", re.I), "DB_CONNECTION", "critical"),
    (re.compile(r"Traceback \(most recent call last\)", re.I), "PYTHON_EXCEPTION", "critical"),
    (re.compile(r"HTTP Error 429|Too Many Requests", re.I), "RATE_LIMITED", "warning"),
    (re.compile(r"HTTP Error 503|Service Unavailable|timed out", re.I), "LLM_SATURATION", "warning"),
    (re.compile(r"\bFAILED\b|\bERROR\b.*(fail|exception|refus)", re.I), "ERROR", "warning"),
]
TAIL_LINES = 60


def _tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 20000))
            return f.read().decode("utf-8", "replace").splitlines()[-n:]
    except Exception:
        return []


def main():
    from db_adapter import get_connection
    conn = get_connection(); cur = conn.cursor()
    inserted = 0
    for fname, _sev in WATCH:
        p = LOGS / fname
        if not p.exists():
            continue
        seen = set()
        for line in _tail(p, TAIL_LINES):
            for rx, atype, sev in PATTERNS:
                if rx.search(line):
                    sig = f"{fname}:{atype}"
                    if sig in seen:
                        break
                    seen.add(sig)
                    # dedup vs recent alert_events (match on source + error class in raw_text)
                    cur.execute("""SELECT 1 FROM alert_events
                                   WHERE source_script=%s AND raw_text LIKE %s
                                   AND created_at > NOW() - INTERVAL '25 minutes' LIMIT 1""",
                                (fname, atype + ":%"))
                    if cur.fetchone():
                        break
                    # alert_type is CHECK-constrained → use 'system_health'; the error class goes
                    # in raw_text so the SIEM endpoint's _classify still types it (DB_CONNECTION, etc.)
                    cur.execute("""INSERT INTO alert_events (alert_type, severity, source_script, raw_text, created_at)
                                   VALUES ('system_health',%s,%s,%s,NOW())""",
                                (sev, fname, f"{atype}: {line[:280]}"))
                    conn.commit(); inserted += 1
                    break
    conn.close()
    print(f"[log-scraper] inserted {inserted} new error events into alert_events")


if __name__ == "__main__":
    main()
