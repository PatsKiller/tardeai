#!/usr/bin/env python3
"""migrate_llm_review_health.py — additive schema + error classification for the LLM-review health gate.

Creates llm_review_runs (run-level status incl SKIPPED_LLM_UNHEALTHY) + adds error_class/retryable/
retry_after/retry_count/llm_review_run_id/trade_instance_id to trade_llm_reviews, then BACKFILLS
error_class + retryable from existing error_message text. Additive/idempotent. No trading writes.
  python3 scripts/migrate_llm_review_health.py            # dry-run (classification preview)
  python3 scripts/migrate_llm_review_health.py --apply
"""
import os, sys, json, psycopg2, psycopg2.extras

RUN_TABLE = """
CREATE TABLE IF NOT EXISTS llm_review_runs (
  id BIGSERIAL PRIMARY KEY,
  run_type TEXT NOT NULL, source TEXT, model TEXT,
  started_at TIMESTAMPTZ DEFAULT now(), completed_at TIMESTAMPTZ,
  status TEXT NOT NULL, health_status JSONB DEFAULT '{}'::jsonb,
  attempted_count INTEGER DEFAULT 0, completed_count INTEGER DEFAULT 0,
  infrastructure_error_count INTEGER DEFAULT 0, parser_error_count INTEGER DEFAULT 0,
  null_review_count INTEGER DEFAULT 0, skipped_count INTEGER DEFAULT 0,
  notes JSONB DEFAULT '{}'::jsonb
);"""

ALTER = """
ALTER TABLE trade_llm_reviews
  ADD COLUMN IF NOT EXISTS error_class TEXT,
  ADD COLUMN IF NOT EXISTS retryable BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS retry_after TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS llm_review_run_id BIGINT,
  ADD COLUMN IF NOT EXISTS trade_instance_id BIGINT;"""

# (error_class, retryable) by error_message pattern (ILIKE)
RULES = [
    ("%timed out%", "ollama_timeout", True),
    ("%timeout%", "ollama_timeout", True),
    ("%connection refused%", "ollama_connection_refused", True),
    ("%[errno 111]%", "ollama_connection_refused", True),
    ("%remote end closed%", "ollama_connection_closed", True),
    ("%connection closed%", "ollama_connection_closed", True),
    ("%http error 500%", "ollama_http_500", True),
    ("%500: internal%", "ollama_http_500", True),
    ("%json_parse%", "parse_error", False),
    ("%parse%", "parse_error", False),
    ("%empty%", "empty_review", True),
    ("%null%", "empty_review", True),
]


def main():
    apply = "--apply" in sys.argv
    c = psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                         user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"])
    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if apply:
        cur.execute(RUN_TABLE); cur.execute(ALTER); c.commit()
        # classify error rows by first matching rule (only those not yet classified)
        for pat, klass, retry in RULES:
            cur.execute("""UPDATE trade_llm_reviews SET error_class=%s, retryable=%s
                           WHERE status='error' AND error_class IS NULL AND error_message ILIKE %s""",
                        (klass, retry, pat))
        # any remaining error rows → unknown (non-retryable)
        cur.execute("UPDATE trade_llm_reviews SET error_class='unknown', retryable=FALSE WHERE status='error' AND error_class IS NULL")
        c.commit()

    rep = {"mode": "apply" if apply else "dry-run"}
    cur.execute("select count(*) c from information_schema.tables where table_name='llm_review_runs'")
    rep["llm_review_runs_table"] = cur.fetchone()["c"] > 0
    try:
        cur.execute("select coalesce(error_class,'(unclassified)') ec, count(*) n, bool_or(retryable) any_retry from trade_llm_reviews where status='error' group by 1 order by 2 desc")
        rep["error_class_breakdown"] = [{"class": r["ec"], "count": r["n"], "retryable": r["any_retry"]} for r in cur.fetchall()]
        cur.execute("select count(*) c from trade_llm_reviews where retryable is true")
        rep["retryable_total"] = cur.fetchone()["c"]
    except Exception as e:
        c.rollback(); rep["note"] = f"columns not yet present (run --apply): {str(e)[:60]}"
    print(json.dumps(rep, indent=2))
    c.close()


if __name__ == "__main__":
    main()
