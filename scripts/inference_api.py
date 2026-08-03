#!/usr/bin/env python3
"""Inference Layers — /api/v2/inference/* router.

Self-contained handler so the giant api_v2.handle() only needs a 5-line delegating
hook. Returns (status:int, body:dict) tuples exactly like api_v2 routes, or None if
the path is not an inference route. Read-only.

Routes:
    GET /api/v2/inference/latest                  most recent run + top inferences
    GET /api/v2/inference/runs?limit=N            recent run headers
    GET /api/v2/inference/results?run_id=&type=&limit=   inference rows
    GET /api/v2/inference/regional?limit=N        latest cross-regional signals
    GET /api/v2/inference/sizing?limit=N          latest sizing recommendations
    GET /api/v2/inference/nav?limit=N             latest NAV premium/discount signals
    GET /api/v2/inference/memory?kind=&limit=     persistent inference memory
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("inference_api")


def _q(sql, params=None, fetch="all"):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception as e:
        log.warning("inference_api query failed: %s", e)
        return None


def _clean(rows):
    try:
        from api_v2 import _json_clean
        if isinstance(rows, list):
            return [{k: _json_clean(v) for k, v in r.items()} for r in rows]
        if isinstance(rows, dict):
            return {k: _json_clean(v) for k, v in rows.items()}
    except Exception:
        pass
    return rows


def _int(query, key, default, cap=500):
    try:
        return min(int((query or {}).get(key, default)), cap)
    except (TypeError, ValueError):
        return default


def _db_write(sql, params=None, fetch=None):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception as e:
        log.warning("inference_api write failed: %s", e)
        return None


def handle_inference(path: str, method: str = "GET", body: dict = None, query: dict = None):
    """Return (status, dict) for /api/v2/inference/* or None if not ours."""
    if not path.startswith("/api/v2/inference"):
        return None

    # ── POST: enqueue an ensemble validation job (fast — just a DB insert; the
    #    worker runs the 3 LLM lanes off the request path so the server never blocks)
    if method == "POST":
        if path == "/api/v2/inference/ensemble/request":
            b = body or {}
            content = (b.get("content") or "").strip()
            if not content:
                return 400, {"ok": False, "error": "content required"}
            target_type = b.get("target_type", "inference")
            target_id = str(b.get("target_id") or "")
            # de-dupe: reuse an open job for the same target instead of stacking
            existing = _q("""SELECT id FROM inference_ensemble_jobs
                             WHERE target_type=%s AND target_id=%s AND status IN ('queued','running')
                             ORDER BY requested_at DESC LIMIT 1""",
                          (target_type, target_id), fetch="one")
            if existing:
                return 200, {"ok": True, "job_id": existing["id"], "status": "queued",
                             "deduped": True}
            raw_lanes = b.get("lanes")
            lanes_json = None
            if raw_lanes is not None:
                if isinstance(raw_lanes, str):
                    try:
                        raw_lanes = json.loads(raw_lanes)
                    except Exception:
                        raw_lanes = [x.strip() for x in raw_lanes.split(",") if x.strip()]
                if isinstance(raw_lanes, (list, tuple)):
                    picked = [str(ln).strip().lower() for ln in raw_lanes
                              if str(ln).strip().lower() in ("deepseek-flash", "grok", "chatgpt", "local")]
                    lanes_json = json.dumps(picked) if picked else None
            row = _db_write(
                """INSERT INTO inference_ensemble_jobs
                   (target_type, target_id, subject, content, task, requested_by, lanes, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'queued') RETURNING id""",
                (target_type, target_id, (b.get("subject") or "")[:300], content[:8000],
                 b.get("task", "inference_quality"), b.get("requested_by", "operator"), lanes_json),
                fetch="one")
            if not row:
                return 500, {"ok": False, "error": "could not enqueue"}
            return 200, {"ok": True, "job_id": row["id"], "status": "queued"}
        return 405, {"ok": False, "error": "method not allowed"}

    if method != "GET":
        return 405, {"ok": False, "error": "method not allowed"}
    q = query or {}

    # ── GET ensemble: latest result + pending-job status for a target ──────────
    if path == "/api/v2/inference/ensemble":
        tt = q.get("target_type", "inference")
        tid = str(q.get("target_id") or "")
        if not tid:
            rows = _q("""SELECT * FROM inference_ensemble_results
                         ORDER BY created_at DESC LIMIT %s""", (_int(q, "limit", 30),)) or []
            return 200, {"ok": True, "data": _clean(rows)}
        result = _q("""SELECT * FROM inference_ensemble_results
                       WHERE target_type=%s AND target_id=%s
                       ORDER BY created_at DESC LIMIT 1""", (tt, tid), fetch="one")
        job = _q("""SELECT id, status, error, requested_at, finished_at
                    FROM inference_ensemble_jobs WHERE target_type=%s AND target_id=%s
                    ORDER BY requested_at DESC LIMIT 1""", (tt, tid), fetch="one")
        return 200, {"ok": True, "result": _clean(result), "job": _clean(job)}

    if path == "/api/v2/inference/ensemble/jobs":
        rows = _q("""SELECT id, target_type, target_id, subject, task, status, error,
                            requested_at, finished_at
                     FROM inference_ensemble_jobs ORDER BY requested_at DESC LIMIT %s""",
                  (_int(q, "limit", 30),)) or []
        return 200, {"ok": True, "data": _clean(rows)}

    try:
        if path == "/api/v2/inference/latest":
            # prefer the most recent COMPLETE run so a half-finished/errored cycle
            # never fronts the dashboard; fall back to the newest of any status
            run = _q("SELECT * FROM inference_runs WHERE status='complete' "
                     "ORDER BY id DESC LIMIT 1", fetch="one")
            if not run:
                run = _q("SELECT * FROM inference_runs ORDER BY id DESC LIMIT 1", fetch="one")
            if not run:
                return 200, {"ok": True, "run": None, "results": []}
            results = _q(
                """SELECT id, layer, inference_type, subject, title, body, confidence,
                          severity, source_lane, created_at
                   FROM inference_results WHERE run_id=%s
                   ORDER BY (severity='critical') DESC, (severity='high') DESC,
                            confidence DESC LIMIT 40""",
                (run["id"],)) or []
            return 200, {"ok": True, "run": _clean(run), "results": _clean(results)}

        if path == "/api/v2/inference/runs":
            rows = _q("SELECT * FROM inference_runs ORDER BY id DESC LIMIT %s",
                      (_int(q, "limit", 20),)) or []
            return 200, {"ok": True, "data": _clean(rows)}

        if path == "/api/v2/inference/results":
            where, params = ["1=1"], []
            if q.get("run_id"):
                where.append("run_id=%s"); params.append(int(q["run_id"]))
            if q.get("type"):
                where.append("inference_type=%s"); params.append(q["type"])
            if q.get("subject"):
                where.append("subject=%s"); params.append(q["subject"])
            params.append(_int(q, "limit", 50))
            rows = _q(f"""SELECT * FROM inference_results WHERE {' AND '.join(where)}
                          ORDER BY created_at DESC LIMIT %s""", params) or []
            return 200, {"ok": True, "data": _clean(rows)}

        if path == "/api/v2/inference/regional":
            rows = _q("""SELECT * FROM inference_regional_signals
                         ORDER BY created_at DESC LIMIT %s""", (_int(q, "limit", 30),)) or []
            return 200, {"ok": True, "data": _clean(rows)}

        if path == "/api/v2/inference/sizing":
            rows = _q("""SELECT * FROM inference_sizing_recommendations
                         ORDER BY created_at DESC LIMIT %s""", (_int(q, "limit", 40),)) or []
            return 200, {"ok": True, "data": _clean(rows)}

        if path == "/api/v2/inference/nav":
            rows = _q("""SELECT * FROM inference_results WHERE inference_type='nav_signal'
                         ORDER BY created_at DESC LIMIT %s""", (_int(q, "limit", 30),)) or []
            return 200, {"ok": True, "data": _clean(rows)}

        if path == "/api/v2/inference/memory":
            where, params = ["1=1"], []
            if q.get("kind"):
                where.append("kind=%s"); params.append(q["kind"])
            params.append(_int(q, "limit", 50))
            rows = _q(f"""SELECT * FROM inference_memory WHERE {' AND '.join(where)}
                          ORDER BY salience DESC, updated_at DESC LIMIT %s""", params) or []
            return 200, {"ok": True, "data": _clean(rows)}

        return 404, {"ok": False, "error": "unknown inference route"}
    except Exception as e:
        return 500, {"ok": False, "error": str(e)}
