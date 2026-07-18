#!/usr/bin/env python3
"""defense_refresh_job.py — Defense v4: operator-triggered QUEUED refresh.

Runs the four defense producers sequentially, writing per-step status to
data/runtime/defense_refresh_job.json so the page can poll progress — the UI
never live-waits. Enqueued detached by POST /api/v2/defense/refresh; flock
guarantees one job at a time (a second enqueue reports already_running).

Industries run WITHOUT --close here: an operator refresh is a display refresh —
state persistence/debounce stays owned by the 16:18 close cron.
"""
import fcntl
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "runtime" / "defense_refresh_job.json"
LOCK = Path("/tmp/defense_refresh_job.lock")
PY = str(ROOT / ".venv" / "bin" / "python")

STEPS = [
    ("sectors", ["scripts/sector_momentum_engine.py"]),
    ("industries", ["scripts/finviz_industry_groups.py"]),
    ("hedging_radar", ["scripts/options_chain_snapshot.py"]),
    ("recommendations", ["scripts/defense_recommendations.py"]),
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
        print("[refresh-job] already running — not queueing a second")
        return 0

    st = {"job_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
          "state": "running", "queued_at": _now(), "started_at": _now(),
          "steps": [{"name": n, "state": "pending"} for n, _ in STEPS]}
    write(st)
    for i, (name, cmd) in enumerate(STEPS):
        st["steps"][i].update(state="running", started_at=_now())
        st["step"] = name
        write(st)
        t0 = time.time()
        try:
            r = subprocess.run([PY] + cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
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
    print(f"[refresh-job] done in {sum(s.get('seconds', 0) for s in st['steps']):.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
