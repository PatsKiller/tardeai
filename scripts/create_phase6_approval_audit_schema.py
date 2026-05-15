#!/usr/bin/env python3
"""create_phase6_approval_audit_schema.py — Create paper proposal approval audit tables.

Additive only. Does not alter existing tables.

Usage:
    .venv/bin/python scripts/create_phase6_approval_audit_schema.py --dry-run
    .venv/bin/python scripts/create_phase6_approval_audit_schema.py --apply
"""
import argparse, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

SCHEMA_SQL = """
-- Phase 6C: Paper proposal approval audit trail
-- Created: 2026-05-15
-- Purpose: Record every approval attempt and gate outcome

CREATE TABLE IF NOT EXISTS paper_proposal_approval_audit (
    id                          BIGSERIAL PRIMARY KEY,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Request identity
    proposal_id                 INTEGER NOT NULL,
    symbol                      TEXT,
    side                        TEXT,
    requested_by                TEXT,
    request_source              TEXT,
    request_ip_hash             TEXT,
    user_agent_hash             TEXT,

    -- Final outcome
    approval_status             TEXT NOT NULL DEFAULT 'started',
    block_reason                TEXT,
    final_message               TEXT,

    -- Gate results (JSONB)
    session_policy_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    market_revalidation_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_gate_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    proposal_snapshot_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    paper_trade_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    alpaca_response_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_json                  JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Key numeric fields (denormalized for fast queries)
    original_entry              NUMERIC,
    adjusted_entry              NUMERIC,
    live_price                  NUMERIC,
    stop_price                  NUMERIC,
    target_price                NUMERIC,
    rr_at_approval              NUMERIC,
    spread_pct                  NUMERIC,
    quote_age_minutes           NUMERIC,

    -- Gate sequence and pass/fail flags
    gate_sequence               TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    passed_session_gate         BOOLEAN NOT NULL DEFAULT FALSE,
    passed_market_revalidation  BOOLEAN NOT NULL DEFAULT FALSE,
    passed_risk_gate            BOOLEAN NOT NULL DEFAULT FALSE,
    paper_trade_created         BOOLEAN NOT NULL DEFAULT FALSE,
    alpaca_submitted            BOOLEAN NOT NULL DEFAULT FALSE,

    -- Safety state capture
    live_trading_enabled        BOOLEAN NOT NULL DEFAULT FALSE,
    alpaca_mode                 TEXT,
    llm_live_execution_disabled BOOLEAN,

    -- Extensible metadata
    metadata_json               JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ppaa_created_at ON paper_proposal_approval_audit (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ppaa_proposal_id ON paper_proposal_approval_audit (proposal_id);
CREATE INDEX IF NOT EXISTS idx_ppaa_symbol ON paper_proposal_approval_audit (symbol);
CREATE INDEX IF NOT EXISTS idx_ppaa_approval_status ON paper_proposal_approval_audit (approval_status);
CREATE INDEX IF NOT EXISTS idx_ppaa_alpaca_mode ON paper_proposal_approval_audit (alpaca_mode);
CREATE INDEX IF NOT EXISTS idx_ppaa_passed_session ON paper_proposal_approval_audit (passed_session_gate);
CREATE INDEX IF NOT EXISTS idx_ppaa_passed_reval ON paper_proposal_approval_audit (passed_market_revalidation);
CREATE INDEX IF NOT EXISTS idx_ppaa_passed_risk ON paper_proposal_approval_audit (passed_risk_gate);

-- Event sub-table for granular gate-by-gate events
CREATE TABLE IF NOT EXISTS paper_proposal_approval_audit_events (
    id              BIGSERIAL PRIMARY KEY,
    audit_id        BIGINT NOT NULL REFERENCES paper_proposal_approval_audit(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type      TEXT NOT NULL,
    event_status    TEXT NOT NULL,
    message         TEXT,
    event_json      JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ppaae_audit_id ON paper_proposal_approval_audit_events (audit_id);
CREATE INDEX IF NOT EXISTS idx_ppaae_event_type ON paper_proposal_approval_audit_events (event_type);
"""

ROLLBACK_SQL = """
-- ROLLBACK: Drop Phase 6C audit tables (audit-only, no production impact)
DROP TABLE IF EXISTS paper_proposal_approval_audit_events;
DROP TABLE IF EXISTS paper_proposal_approval_audit;
"""


def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env.get("DB_HOST", "localhost"),
        dbname=env.get("DB_NAME", "trade_ai"),
        user=env.get("DB_USER", "trade_ai"),
        password=env.get("DB_PASSWORD", ""))


def main():
    p = argparse.ArgumentParser(description="Create Phase 6C approval audit schema")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if args.dry_run:
        print("DRY RUN — SQL that would be executed:")
        print(SCHEMA_SQL)
        print("\n--- ROLLBACK SQL (for reference) ---")
        print(ROLLBACK_SQL)
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(SCHEMA_SQL)
    conn.commit()

    # Verify
    cur.execute("SELECT COUNT(*) FROM paper_proposal_approval_audit")
    count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM paper_proposal_approval_audit_events")
    ev_count = cur.fetchone()[0]
    conn.close()

    print(f"Schema applied successfully.")
    print(f"  paper_proposal_approval_audit: {count} rows")
    print(f"  paper_proposal_approval_audit_events: {ev_count} rows")


if __name__ == "__main__":
    main()
