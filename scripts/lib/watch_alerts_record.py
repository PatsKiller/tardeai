"""LQ-20261107-2993c: durable, append-only evaluator record for the Watch alerts lane (no DDL).

The lane receipt (`watch-alerts-eval_last.json`) is overwritten every pass, so it cannot answer "how many
runs in 24 h" or "when did a run last succeed". One jsonl line per pass can. `read_record` derives liveness and a
*certified* armed count (from the newest OK run only) and never turns an unreadable store into zero.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

NAME = "watch-alerts-eval_runs.jsonl"
TAIL_DEFAULT = 600


def _runtime(root=None) -> Path:
    from lib.lane_last_receipt import runtime_dir
    return runtime_dir(root)


def record_path(root=None) -> Path:
    return _runtime(root) / NAME


def append_run(*, armed, fired, composites, rc, error=None, root=None, now=None) -> bool:
    """Append one line. Never raises: a record failure must not stop the alert lane."""
    now = now or datetime.now(timezone.utc)
    try:
        path = record_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": now.isoformat(), "rc": int(rc), "armed": (None if armed is None else int(armed)), "fired": int(fired or 0),
                           "composites": int(composites or 0), "error": (str(error)[:200] if error else None)},
                          sort_keys=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (line + "\n").encode())
        finally:
            os.close(fd)
        return True
    except Exception:  # noqa: BLE001
        return False


def _parse(ts):
    try:
        v = datetime.fromisoformat(str(ts))
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def read_record(*, root=None, now=None, tail=TAIL_DEFAULT) -> dict:
    now = now or datetime.now(timezone.utc)
    base = {"readable": True, "last_run_at": None, "last_ok_at": None, "last_rc": None, "age_s": None,
            "last_error": None, "certified": None, "skipped_lines": 0, "source": NAME}
    try:
        path = record_path(root)
        if not path.exists():
            return base
        lines = path.read_text().splitlines()[-int(tail):]
    except Exception:  # noqa: BLE001
        return {**base, "readable": False}
    runs, skipped = [], 0
    for line in lines:
        try:
            row = json.loads(line)
            ts = _parse(row["ts"])
            if ts is None:
                raise ValueError("ts")
            runs.append((ts, row))
        except Exception:  # noqa: BLE001
            skipped += 1
    base["skipped_lines"] = skipped
    if not runs:
        return base
    runs.sort(key=lambda r: r[0])
    last_ts, last = runs[-1]
    base.update(last_run_at=last_ts.isoformat(), last_rc=last.get("rc"), last_error=last.get("error"),
                age_s=max(0, int((now - last_ts).total_seconds())))
    ok = [r for r in runs if r[1].get("rc") == 0]
    if ok:
        ok_ts, ok_row = ok[-1]
        base["last_ok_at"] = ok_ts.isoformat()
        cutoff = now - timedelta(hours=24)
        day = [r for r in runs if r[0] >= cutoff]
        day_ok = [r for r in day if r[1].get("rc") == 0]
        # armed None = the run could not read its own alert table: the count is UNKNOWN, never 0 (LQ-2993c-v2 R2).
        armed = ok_row.get("armed")
        base["certified"] = {"armed": (None if armed is None else int(armed)),
                             "fired_24h": sum(int(r[1].get("fired") or 0) for r in day_ok),
                             "runs_24h": len(day), "ok_runs_24h": len(day_ok), "as_of": ok_ts.isoformat()}
    return base
