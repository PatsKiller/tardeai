#!/usr/bin/env python3
"""defense_deepseek_refresh_job.py — operator-triggered FULL refresh with LLM re-run.

Runs ALL seven defense producers sequentially, then fires a fresh free-seat
oversight build so every LLM seat re-evaluates the new data. The standard
"refresh all" button runs only 4 producers — this runs everything.

Enqueued detached by POST /api/v2/defense/deepseek-refresh; flock guarantees one at a time.
"""
import fcntl
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "runtime" / "defense_deepseek_refresh_job.json"
LOCK = Path("/tmp/defense_deepseek_refresh_job.lock")
PY = sys.executable

STEPS = [
    ("sectors",             ["scripts/sector_momentum_engine.py"]),
    ("industries",          ["scripts/finviz_industry_groups.py"]),
    ("hedging_radar",       ["scripts/options_chain_snapshot.py"]),
    ("inverse_stoplights",  ["scripts/defense_inverse_stoplights.py"]),
    ("cash_alternatives",   ["scripts/defense_cash_alternatives.py"]),
    ("gap_checker",         ["scripts/defense_engine_gap_checker.py"]),
    ("recommendations",     ["scripts/defense_recommendations.py"]),
    # recommendations step auto-triggers free-seat oversight (chatgpt, grok, deepseek)
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write(status: dict):
    STATUS.write_text(json.dumps(status, default=str))


def main() -> int:
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[deepseek-refresh] already running — not queueing a second")
        return 0

    st = {"job_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
          "state": "running", "queued_at": _now(), "started_at": _now(),
          "steps": [{"name": n, "state": "pending"} for n, _ in STEPS]}
    write(st)
    for i, (name, cmd_parts) in enumerate(STEPS):
        st["steps"][i].update(state="running", started_at=_now())
        st["step"] = name
        write(st)
        t0 = time.time()
        try:
            r = subprocess.run([PY] + cmd_parts, cwd=ROOT, capture_output=True, text=True, timeout=900)
            ok = r.returncode == 0
            st["steps"][i].update(state="done" if ok else "error",
                                  seconds=round(time.time() - t0, 1),
                                  tail=(r.stdout or r.stderr or "").strip()[-200:])
            if not ok:
                st.update(state="error", error=f"{name} exited {r.returncode}", finished_at=_now())
                write(st)
                return 1
        except subprocess.TimeoutExpired:
            st["steps"][i].update(state="error", tail="timeout 900s")
            st.update(state="error", error=f"{name} timeout", finished_at=_now())
            write(st)
            return 1
        write(st)
    st.update(state="done", step=None, finished_at=_now())
    write(st)
    elapsed = sum(s.get("seconds", 0) for s in st["steps"])
    print(f"[deepseek-refresh] done — {len(STEPS)} steps in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
