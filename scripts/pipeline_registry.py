"""
pipeline_registry.py — Lightweight heartbeat module for pipeline scripts.
Non-fatal: never blocks calling scripts.

Usage:
    from scripts.pipeline_registry import PipelineRun
    with PipelineRun('news_ingestion') as run:
        articles = ingest()
        run.rows(len(articles))
"""
import logging, os

# --- .env autoload (no hardcoded secrets) ---
import os as _os
if not _os.getenv("DB_PASSWORD"):
    try:
        from pathlib import Path as _P
        for _l in (_P(__file__).resolve().parent.parent / ".env").read_text().splitlines():
            if _l.startswith("DB_PASSWORD="): _os.environ["DB_PASSWORD"] = _l.split("=",1)[1].strip()
    except Exception: pass
from contextlib import contextmanager
from typing import Optional

log = logging.getLogger(__name__)

_DB_CONFIG = dict(host='127.0.0.1', port=5432, dbname='trade_ai', user='trade_ai',
                  password=os.getenv('DB_PASSWORD', ''))


def _get_conn():
    try:
        import psycopg2
        return psycopg2.connect(**_DB_CONFIG)
    except Exception:
        return None


def run_start(script_name: str, run_label: str = None, triggered_by: str = 'cron') -> Optional[int]:
    try:
        import uuid
        conn = _get_conn()
        if not conn: return None
        cur = conn.cursor()
        _run_id = f"{script_name}_{uuid.uuid4().hex[:8]}"
        cur.execute("""INSERT INTO pipeline_runs (run_id, pipeline_key, run_label, trigger_source, started_at, status)
            VALUES (%s, %s, %s, %s, NOW(), 'running') RETURNING id""", [_run_id, script_name, run_label, triggered_by])
        run_id = cur.fetchone()[0]
        conn.commit(); conn.close()
        return run_id
    except Exception as e:
        log.debug(f"pipeline_registry run_start error: {e}")
        return None


def run_complete(run_id: Optional[int], rows_processed: Optional[int] = None):
    """Record success. `rows_processed=None` means NOT MEASURED, and is written
    as JSON null rather than 0.

    Measured 2026-09-06: 20 scripts use PipelineRun and only 4 ever call
    `.rows()`. The other 16 wrote `{"rows_produced": 0}` on every successful run,
    because the default was 0 — so `pipeline_zero_rows` fired on five pipelines
    that had NEVER reported a row in their entire history, including
    cio_decision_engine at 3,010 runs in 7 days. Only 7 of 44 pipeline keys had
    ever recorded a non-zero.

    0 meant both "I produced nothing" and "nobody told me", so the alarm carried
    no information in either direction: it could not fire on a real outage and it
    could not stop firing on a healthy pipeline. AGENTS.md — two states cannot
    express "no input". Unknown now has its own value.
    """
    if not run_id: return
    try:
        conn = _get_conn()
        if not conn: return
        cur = conn.cursor()
        cur.execute("""UPDATE pipeline_runs SET status='success', finished_at=NOW(),
            duration_seconds=EXTRACT(EPOCH FROM (NOW()-started_at)),
            summary=jsonb_build_object('rows_produced', %s::bigint) WHERE id=%s""",
            [rows_processed, run_id])
        conn.commit(); conn.close()
    except Exception:
        pass


def run_fail(run_id: Optional[int], error_message: str = ''):
    if not run_id: return
    try:
        conn = _get_conn()
        if not conn: return
        cur = conn.cursor()
        cur.execute("""UPDATE pipeline_runs SET status='failed', finished_at=NOW(),
            duration_seconds=EXTRACT(EPOCH FROM (NOW()-started_at)),
            summary=jsonb_build_object('errors', %s) WHERE id=%s""",
            [str(error_message)[:500], run_id])
        conn.commit(); conn.close()
    except Exception:
        pass


class PipelineRun:
    def __init__(self, script_name: str, run_label: str = None, triggered_by: str = None):
        self.script_name = script_name
        self.run_label = run_label
        # Auto-detect if running from cron or interactive
        if triggered_by is None:
            import sys
            self.triggered_by = 'cron' if not sys.stdin.isatty() else 'manual'
        else:
            self.triggered_by = triggered_by
        self.run_id = None
        #: None = not measured. Do NOT default this to 0 — see run_complete().
        self._rows = None

    def __enter__(self):
        self.run_id = run_start(self.script_name, self.run_label, self.triggered_by)
        return self

    def rows(self, count: int):
        self._rows = count

    def __exit__(self, exc_type, exc_val, exc_tb):
        # SystemExit(0)/SystemExit(None) is a CLEAN success, not a failure. The idiom
        # `with PipelineRun(...): raise SystemExit(main())` was recording every exit-0 success as
        # failed with errors="0", flooding pipeline_critical alerts. Real failures (sys.exit(non-zero)
        # or a genuine exception) still record as failed. return False so SystemExit still propagates.
        if exc_type is not None and issubclass(exc_type, SystemExit):
            code = exc_val.code if exc_val is not None else 0
            if code in (0, None):
                run_complete(self.run_id, self._rows)
                return False
        if exc_type is not None:
            run_fail(self.run_id, str(exc_val))
        else:
            run_complete(self.run_id, self._rows)
        return False
        return False


def seed_schedule(conn):
    """Seed pipeline_schedule with known critical scripts."""
    cur = conn.cursor()
    schedules = [
        ('news_ingestion', 'News Ingestion', 6, 30, 15, 5, True,
         'cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/news_ingestion.py', '1-5'),
        ('finviz_enrichment', 'Finviz Enrichment', 7, 10, 20, 5, True,
         'cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/finviz_enrichment.py', '1-5'),
        ('finviz_screener_runner', 'Finviz Screener', 10, 0, 20, 0, True,
         'cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/finviz_screener_runner.py --run', '1-5'),
        ('social_ingest', 'Social Ingest', 7, 30, 20, 0, False,
         'cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/social_ingest.py', '1-5'),
        ('rag_indexer', 'RAG Indexer', 6, 50, 20, 0, False,
         'cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/rag_indexer.py --hours 2', '1-5'),
        ('premarket_watcher', 'Pre-Market Watcher', 5, 30, 20, 0, False,
         'cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/premarket_watcher.py', '1-5'),
        ('agent_outcome_scorer', 'Agent Outcome Scorer', 5, 30, 20, 0, False,
         'cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/agent_outcome_scorer.py', '1-5'),
        ('pipeline_health_monitor', 'Pipeline Health Monitor', 7, 0, 15, 0, False,
         'cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/pipeline_health_monitor.py', '1-5'),
    ]
    for s in schedules:
        cur.execute("""INSERT INTO pipeline_schedule (script_name, display_name, expected_hour, expected_min,
            max_latency_min, min_rows, critical, command, run_days, active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
            ON CONFLICT (script_name) DO UPDATE SET display_name=EXCLUDED.display_name, command=EXCLUDED.command""",
            [s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8]])
    conn.commit()
    print(f"Seeded {len(schedules)} pipeline schedules")
