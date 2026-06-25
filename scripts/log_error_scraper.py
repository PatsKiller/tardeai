#!/usr/bin/env python3
"""Log error scraper → alert_events (so file-only failures reach SIEM).

Many failures only ever hit logs/*.log (youtube 429s, ollama 503s, tracebacks, cron stderr)
and are invisible to the SIEM dashboard. This tails a curated set of logs, extracts critical
error lines, and writes deduped rows into alert_events (which the SIEM endpoint unions).

Dedup: skip if the same (source, signature) was written in the last 25 min, so a log that
spews the same error repeatedly produces at most one SIEM row per window.

Staleness guard (offset-based tailing): we persist a per-file byte offset and only ever scan
bytes APPENDED since the previous run. This stops the scraper from re-alerting on an OLD
traceback that lingers in the file tail long after the underlying bug was fixed (the cause of
the recurring "26 P0/P1 SIEM alerts in 24h" floods — one stale atm.log traceback re-fired ~1-2×
/hour for 16h). On first sight of a file (no stored offset) we adopt EOF and alert nothing, so a
pre-existing backlog never floods. Truncation/rotation (size < offset) resets the offset to 0.

Cron: every 20 min.
"""
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
LOGS = PROJECT_ROOT / "logs"
OFFSET_STATE = PROJECT_ROOT / "data" / "portfolios" / "state" / "log_error_scraper_offsets.json"

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
MAX_NEW_BYTES = 2_000_000  # cap one run's scan so a sudden multi-MB burst can't stall the cron


def _load_offsets() -> dict:
    try:
        return json.loads(OFFSET_STATE.read_text())
    except Exception:
        return {}


def _save_offsets(offsets: dict):
    try:
        OFFSET_STATE.parent.mkdir(parents=True, exist_ok=True)
        OFFSET_STATE.write_text(json.dumps(offsets, indent=2))
    except Exception:
        pass


def _read_new_lines(path, prev_offset):
    """Return (new_lines, new_offset). Only bytes appended since prev_offset are scanned.
    prev_offset is None on first sight → adopt EOF (alert nothing for pre-existing backlog).
    size < prev_offset means the file was truncated/rotated → re-read from 0."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if prev_offset is None:
                return [], size  # first sight: skip existing backlog
            if size < prev_offset:
                return [], size  # truncated/rotated: old content is gone — re-adopt EOF, don't re-flood
            start = prev_offset
            if size - start > MAX_NEW_BYTES:
                start = size - MAX_NEW_BYTES  # only the most recent slice of a huge burst
            f.seek(start)
            data = f.read(size - start)
            return data.decode("utf-8", "replace").splitlines(), size
    except Exception:
        return [], prev_offset


def main():
    from db_adapter import get_connection
    conn = get_connection(); cur = conn.cursor()
    offsets = _load_offsets()
    inserted = 0
    for fname, _sev in WATCH:
        p = LOGS / fname
        if not p.exists():
            continue
        new_lines, new_offset = _read_new_lines(p, offsets.get(fname))
        offsets[fname] = new_offset  # always advance, even when nothing matched
        seen = set()
        for line in new_lines:
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
    _save_offsets(offsets)
    print(f"[log-scraper] inserted {inserted} new error events into alert_events")


if __name__ == "__main__":
    main()
