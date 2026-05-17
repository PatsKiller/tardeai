#!/usr/bin/env python3
"""create_phase8_lifecycle_outcome_schema.py — Phase 8B outcome tables.

Usage:
    .venv/bin/python scripts/create_phase8_lifecycle_outcome_schema.py --dry-run
    .venv/bin/python scripts/create_phase8_lifecycle_outcome_schema.py --apply
"""
import argparse, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS paper_trade_lifecycle_outcomes (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    proposal_id INTEGER NULL,
    approval_audit_id BIGINT NULL,
    paper_trade_id INTEGER NULL,
    symbol TEXT NOT NULL,
    strategy_name TEXT NULL,
    side TEXT DEFAULT 'long',
    entry_price NUMERIC NULL,
    stop_price NUMERIC NULL,
    target_price NUMERIC NULL,
    fill_price NUMERIC NULL,
    close_price NUMERIC NULL,
    quantity NUMERIC NULL,
    opened_at TIMESTAMPTZ NULL,
    filled_at TIMESTAMPTZ NULL,
    closed_at TIMESTAMPTZ NULL,
    holding_minutes INTEGER NULL,
    status TEXT NOT NULL DEFAULT 'open',
    close_reason TEXT NULL,
    outcome_label TEXT NULL,
    pnl NUMERIC NULL,
    pnl_pct NUMERIC NULL,
    r_multiple NUMERIC NULL,
    planned_risk_amount NUMERIC NULL,
    mfe_pct NUMERIC NULL,
    mae_pct NUMERIC NULL,
    mfe_r NUMERIC NULL,
    mae_r NUMERIC NULL,
    gate_summary_json JSONB DEFAULT '{}'::jsonb,
    outcome_source TEXT NULL,
    confidence TEXT DEFAULT 'low',
    requires_human_review BOOLEAN DEFAULT TRUE,
    human_review_status TEXT DEFAULT 'pending_review',
    notes TEXT NULL,
    metadata_json JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ptlo_proposal ON paper_trade_lifecycle_outcomes(proposal_id);
CREATE INDEX IF NOT EXISTS idx_ptlo_trade ON paper_trade_lifecycle_outcomes(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_ptlo_symbol ON paper_trade_lifecycle_outcomes(symbol);
CREATE INDEX IF NOT EXISTS idx_ptlo_strategy ON paper_trade_lifecycle_outcomes(strategy_name);
CREATE INDEX IF NOT EXISTS idx_ptlo_status ON paper_trade_lifecycle_outcomes(status);
CREATE INDEX IF NOT EXISTS idx_ptlo_outcome ON paper_trade_lifecycle_outcomes(outcome_label);
CREATE INDEX IF NOT EXISTS idx_ptlo_closed ON paper_trade_lifecycle_outcomes(closed_at);

CREATE TABLE IF NOT EXISTS paper_strategy_scorecards (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scorecard_date DATE NOT NULL DEFAULT CURRENT_DATE,
    lookback_days INTEGER NOT NULL,
    strategy_name TEXT NOT NULL,
    closed_count INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    win_rate NUMERIC NULL,
    avg_r_multiple NUMERIC NULL,
    total_pnl NUMERIC NULL,
    expectancy_r NUMERIC NULL,
    sample_quality TEXT DEFAULT 'insufficient',
    recommendation TEXT NULL,
    recommendation_status TEXT DEFAULT 'human_review_only',
    metadata_json JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_pss_date ON paper_strategy_scorecards(scorecard_date);
CREATE INDEX IF NOT EXISTS idx_pss_strategy ON paper_strategy_scorecards(strategy_name);
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
        print("DRY RUN:\n" + SCHEMA_SQL[:500] + "\n...")
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(SCHEMA_SQL)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM paper_trade_lifecycle_outcomes")
    o = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM paper_strategy_scorecards")
    s = cur.fetchone()[0]
    conn.close()
    print(f"Schema applied. outcomes={o}, scorecards={s}")


if __name__ == "__main__":
    main()
