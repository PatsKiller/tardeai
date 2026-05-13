#!/usr/bin/env python3
"""Create deep_overnight_llm_queue and deep_overnight_llm_results tables.

Safe to run repeatedly — uses IF NOT EXISTS for all DDL.
Does not delete, truncate, or modify existing data.
Does not touch broker, holdings, execution, or trading tables.
"""

import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

def get_db_connection():
    import psycopg2
    env_path = PROJ / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS deep_overnight_llm_queue (
    id                    SERIAL PRIMARY KEY,
    job_type              TEXT NOT NULL,
    symbol                TEXT,
    trade_id              INTEGER,
    journal_id            INTEGER,
    account               TEXT,
    priority_tier         TEXT NOT NULL DEFAULT 'P4',
    priority_score        INTEGER NOT NULL DEFAULT 0,
    reason_codes          TEXT[] DEFAULT ARRAY[]::TEXT[],
    source_script         TEXT,
    source_table          TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    queued_at             TIMESTAMPTZ DEFAULT NOW(),
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    attempt_count         INTEGER DEFAULT 0,
    last_error            TEXT,
    input_hash            TEXT,
    last_deep_review_hash TEXT,
    last_qwen_summary     TEXT,
    last_qwen_confidence  NUMERIC,
    last_gemma_model      TEXT,
    last_gemma_runtime_sec NUMERIC,
    result_table          TEXT,
    result_id             INTEGER,
    metadata_json         JSONB DEFAULT '{}'::JSONB,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);
"""

QUEUE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_dolq_status ON deep_overnight_llm_queue (status);
CREATE INDEX IF NOT EXISTS idx_dolq_priority_tier ON deep_overnight_llm_queue (priority_tier);
CREATE INDEX IF NOT EXISTS idx_dolq_priority_score ON deep_overnight_llm_queue (priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_dolq_job_type ON deep_overnight_llm_queue (job_type);
CREATE INDEX IF NOT EXISTS idx_dolq_queued_at ON deep_overnight_llm_queue (queued_at);
CREATE INDEX IF NOT EXISTS idx_dolq_symbol ON deep_overnight_llm_queue (symbol);
CREATE INDEX IF NOT EXISTS idx_dolq_status_priority ON deep_overnight_llm_queue (status, priority_score DESC);
"""

RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS deep_overnight_llm_results (
    id                    SERIAL PRIMARY KEY,
    queue_id              INTEGER REFERENCES deep_overnight_llm_queue(id),
    job_type              TEXT NOT NULL,
    symbol                TEXT,
    trade_id              INTEGER,
    journal_id            INTEGER,
    model                 TEXT,
    prompt_version        TEXT,
    summary               TEXT,
    findings_json         JSONB DEFAULT '{}'::JSONB,
    recommendations_json  JSONB DEFAULT '{}'::JSONB,
    risk_flags_json       JSONB DEFAULT '{}'::JSONB,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);
"""

RESULTS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_dolr_queue_id ON deep_overnight_llm_results (queue_id);
CREATE INDEX IF NOT EXISTS idx_dolr_job_type ON deep_overnight_llm_results (job_type);
CREATE INDEX IF NOT EXISTS idx_dolr_symbol ON deep_overnight_llm_results (symbol);
"""


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN — showing DDL only ===\n")
        print(QUEUE_DDL)
        print(QUEUE_INDEXES)
        print(RESULTS_DDL)
        print(RESULTS_INDEXES)
        return

    conn = get_db_connection()
    cur = conn.cursor()

    print("Creating deep_overnight_llm_queue...")
    cur.execute(QUEUE_DDL)
    cur.execute(QUEUE_INDEXES)
    print("  Table and indexes: OK")

    print("Creating deep_overnight_llm_results...")
    cur.execute(RESULTS_DDL)
    cur.execute(RESULTS_INDEXES)
    print("  Table and indexes: OK")

    conn.commit()
    cur.close()
    conn.close()

    # Verify
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM deep_overnight_llm_queue;")
    qcount = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM deep_overnight_llm_results;")
    rcount = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"\nVerification:")
    print(f"  deep_overnight_llm_queue:   {qcount} rows")
    print(f"  deep_overnight_llm_results: {rcount} rows")
    print("\nSchema creation complete.")


if __name__ == "__main__":
    main()
