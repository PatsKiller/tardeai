#!/usr/bin/env python3
"""create_phase5_feedback_schema.py — Create Phase 5 feedback/learning tables. Additive only."""
import argparse, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_feedback_observations (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    observation_date DATE,
    source_table TEXT,
    source_id TEXT,
    workflow TEXT,
    symbol TEXT,
    model_role TEXT,
    model_name TEXT,
    prompt_hash TEXT,
    output_hash TEXT,
    decision_action TEXT,
    confidence NUMERIC,
    evidence_count INTEGER,
    source_diversity NUMERIC,
    latency_ms INTEGER,
    fallback_used BOOLEAN DEFAULT FALSE,
    outcome_type TEXT,
    outcome_value NUMERIC,
    outcome_label TEXT,
    human_review_label TEXT,
    quality_score NUMERIC,
    safety_score NUMERIC,
    notes TEXT,
    metadata_json JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_lfo_workflow ON llm_feedback_observations(workflow);
CREATE INDEX IF NOT EXISTS idx_lfo_model ON llm_feedback_observations(model_role);
CREATE INDEX IF NOT EXISTS idx_lfo_symbol ON llm_feedback_observations(symbol);
CREATE INDEX IF NOT EXISTS idx_lfo_created ON llm_feedback_observations(created_at);

CREATE TABLE IF NOT EXISTS llm_learning_recommendations (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    recommendation_type TEXT,
    workflow TEXT,
    model_role TEXT,
    current_behavior TEXT,
    proposed_change TEXT,
    evidence_summary TEXT,
    supporting_observation_ids BIGINT[],
    estimated_impact TEXT,
    risk_level TEXT,
    status TEXT DEFAULT 'pending_human_review',
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    applied BOOLEAN DEFAULT FALSE,
    applied_at TIMESTAMPTZ,
    metadata_json JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_llr_status ON llm_learning_recommendations(status);
CREATE INDEX IF NOT EXISTS idx_llr_workflow ON llm_learning_recommendations(workflow);

CREATE TABLE IF NOT EXISTS llm_prompt_experiments (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    workflow TEXT,
    model_role TEXT,
    model_name TEXT,
    baseline_prompt_hash TEXT,
    candidate_prompt_hash TEXT,
    candidate_prompt_text TEXT,
    test_status TEXT DEFAULT 'draft',
    result_summary TEXT,
    score_delta NUMERIC,
    safety_notes TEXT,
    status TEXT DEFAULT 'pending_human_review',
    metadata_json JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_lpe_status ON llm_prompt_experiments(status);
CREATE INDEX IF NOT EXISTS idx_lpe_workflow ON llm_prompt_experiments(workflow);
"""

def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))

def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if args.dry_run:
        print("DRY RUN — would execute:\n" + SCHEMA[:500] + "...")
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(SCHEMA)
    conn.commit()
    for t in ["llm_feedback_observations", "llm_learning_recommendations", "llm_prompt_experiments"]:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"{t}: {cur.fetchone()[0]} rows")
    conn.close()
    print("Phase 5 schema applied.")

if __name__ == "__main__":
    main()
