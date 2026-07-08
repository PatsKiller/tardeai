#!/usr/bin/env python3
"""Inference ensemble — background job worker.

Drains queued rows from inference_ensemble_jobs, runs the multi-LLM ensemble
(`inference_ensemble.ensemble_validate`, free lanes only), persists the verdict to
inference_ensemble_results, and links it back on the job. Kept OFF the dashboard
request path because each job runs ~3 sequential LLM calls (~10-40s) — the single-
threaded portfolio_server must never block on that.

Usage (cron, flock-guarded):
    */3 9-16 * * 1-5 cd $PROJ && bash linux_launchers/run_ensemble_worker.sh
    python scripts/inference_ensemble_worker.py --run --limit 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

(PROJECT_ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(PROJECT_ROOT / "logs" / "ensemble_worker.log"),
              logging.StreamHandler()],
)
log = logging.getLogger("ensemble_worker")


def _load_env() -> None:
    import os
    f = PROJECT_ROOT / ".env"
    if not f.exists():
        return
    for raw in f.read_text(errors="ignore").splitlines():
        s = raw.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _db():
    from db_adapter import _execute, USE_DB
    return _execute, USE_DB


def claim_jobs(limit: int) -> list:
    """Atomically claim up to `limit` queued jobs (status queued -> running)."""
    _execute, use_db = _db()
    if not use_db:
        return []
    rows = _execute(
        """UPDATE inference_ensemble_jobs
           SET status='running', started_at=now()
           WHERE id IN (
             SELECT id FROM inference_ensemble_jobs
             WHERE status='queued' ORDER BY requested_at LIMIT %s
             FOR UPDATE SKIP LOCKED)
           RETURNING id, target_type, target_id, subject, content, task, lanes""",
        (limit,), fetch="all")
    return rows or []


def _persist_result(job: dict, verdict: dict) -> int | None:
    _execute, _ = _db()
    chash = hashlib.sha256((job.get("content") or "").encode()).hexdigest()[:16]
    row = _execute(
        """INSERT INTO inference_ensemble_results
           (target_type, target_id, subject, task, content_hash, final_decision,
            final_score, final_confidence, consensus_reached, lanes_used, votes,
            reasoning_summary)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (job.get("target_type"), str(job.get("target_id")), job.get("subject"),
         job.get("task"), chash, verdict.get("final_decision"),
         verdict.get("final_score"), verdict.get("final_confidence"),
         bool(verdict.get("consensus_reached")),
         json.dumps(verdict.get("lanes_used", [])),
         json.dumps(verdict.get("votes", [])),
         (verdict.get("reasoning_summary") or "")[:2000]),
        fetch="one")
    return row["id"] if row else None


def process(limit: int = 5) -> dict:
    _execute, use_db = _db()
    if not use_db:
        log.warning("DB disabled")
        return {"claimed": 0, "done": 0, "errors": 0}
    try:
        from inference_ensemble import ensemble_validate
    except Exception as e:
        log.error("inference_ensemble unavailable: %s", e)
        return {"claimed": 0, "done": 0, "errors": 0}

    jobs = claim_jobs(limit)
    done = errors = 0
    for job in jobs:
        try:
            lanes_raw = job.get("lanes")
            lanes = None
            if lanes_raw:
                if isinstance(lanes_raw, str):
                    try:
                        lanes = json.loads(lanes_raw)
                    except Exception:
                        lanes = None
                elif isinstance(lanes_raw, (list, tuple)):
                    lanes = list(lanes_raw)
            task = job.get("task") or "inference_quality"
            verdict = ensemble_validate(
                content=job.get("content") or "",
                context=job.get("subject") or "",
                task=task,
                lanes=lanes,
                manual_trigger=True)
            rid = _persist_result(job, verdict)
            _execute(
                "UPDATE inference_ensemble_jobs SET status='done', result_id=%s, finished_at=now() WHERE id=%s",
                (rid, job["id"]), fetch=None)
            done += 1
            log.info("job %s [%s:%s] -> %s score=%s consensus=%s (%d lanes)",
                     job["id"], job.get("target_type"), job.get("target_id"),
                     verdict.get("final_decision"), verdict.get("final_score"),
                     verdict.get("consensus_reached"), len(verdict.get("lanes_used", [])))
        except Exception as e:
            errors += 1
            _execute("UPDATE inference_ensemble_jobs SET status='error', error=%s, finished_at=now() WHERE id=%s",
                     (str(e)[:1000], job["id"]), fetch=None)
            log.warning("job %s failed: %s", job["id"], e)
    return {"claimed": len(jobs), "done": done, "errors": errors}


def main() -> int:
    _load_env()
    ap = argparse.ArgumentParser(description="Inference ensemble job worker")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=5, help="max jobs per run")
    a = ap.parse_args()
    if not a.run:
        ap.print_help()
        return 0
    out = process(a.limit)
    log.info("ensemble worker: claimed=%d done=%d errors=%d", out["claimed"], out["done"], out["errors"])
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
