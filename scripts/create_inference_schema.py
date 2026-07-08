#!/usr/bin/env python3
"""Inference Layers — database schema (idempotent).

Creates the tables the modular Inference Layers system writes to, and extends
news_articles with region tagging columns so Layer 3 (cross-regional synthesis)
can capture Asia/Europe/EM provenance.

All DDL is CREATE ... IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so it is safe to
re-run. Tables align with existing conventions (BIGSERIAL ids, JSONB payloads,
TIMESTAMPTZ, account_key strings, advisory-only — never an execution path).

Usage:
    python scripts/create_inference_schema.py --apply
    python scripts/create_inference_schema.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("inference_schema")

DDL = [
    # ── Run header: one row per inference engine cycle ───────────────────────
    """
    CREATE TABLE IF NOT EXISTS inference_runs (
        id              BIGSERIAL PRIMARY KEY,
        run_label       TEXT,
        trigger         TEXT,                       -- cron | manual | event:<name>
        account         TEXT,                       -- account_key the cycle reasoned about
        status          TEXT DEFAULT 'running',     -- running | complete | error
        regime          TEXT,                       -- risk_on | neutral | risk_off | high_vol
        layers_run      JSONB DEFAULT '[]'::jsonb,  -- ordered list of {layer, ok, ms, n}
        summary         TEXT,
        metrics         JSONB DEFAULT '{}'::jsonb,
        error           TEXT,
        started_at      TIMESTAMPTZ DEFAULT now(),
        finished_at     TIMESTAMPTZ
    )
    """,
    # ── Unified higher-order inference store (the actionable output) ─────────
    """
    CREATE TABLE IF NOT EXISTS inference_results (
        id              BIGSERIAL PRIMARY KEY,
        run_id          BIGINT REFERENCES inference_runs(id) ON DELETE CASCADE,
        layer           TEXT,                       -- ingestion|features|regional|higher_order
        inference_type  TEXT,                       -- regional_impact|journal_pattern|nav_signal|
                                                    -- opportunity|risk|sizing|data_gap
        subject         TEXT,                       -- symbol, "Asia/semiconductors", region, etc.
        title           TEXT,
        body            TEXT,
        confidence      NUMERIC,                    -- 0.0 - 1.0
        severity        TEXT DEFAULT 'low',         -- low|medium|high|critical
        source_lane     TEXT DEFAULT 'local',       -- local|grok|chatgpt|heuristic|measured
        reasoning_trace JSONB DEFAULT '[]'::jsonb,  -- ordered explanation steps
        evidence        JSONB DEFAULT '[]'::jsonb,  -- [{title,url,kind}]
        payload         JSONB DEFAULT '{}'::jsonb,  -- structured extras (numbers, symbols)
        created_at      TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_inf_results_run ON inference_results(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_inf_results_type ON inference_results(inference_type, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_inf_results_subject ON inference_results(subject, created_at DESC)",
    # ── Cross-regional signals (Layer 3 detail table) ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS inference_regional_signals (
        id               BIGSERIAL PRIMARY KEY,
        run_id           BIGINT REFERENCES inference_runs(id) ON DELETE CASCADE,
        region           TEXT,                      -- US|Asia|Europe|EmergingMarkets|Global
        theme            TEXT,                      -- "BOJ policy", "semiconductors", ...
        headline         TEXT,
        us_impact        TEXT,                      -- the inference: how it reaches US markets
        direction        TEXT,                      -- bullish|bearish|mixed|neutral
        affected_symbols JSONB DEFAULT '[]'::jsonb, -- [{symbol, channel, held}]
        confidence       NUMERIC,
        source_lane      TEXT DEFAULT 'local',
        source_urls      JSONB DEFAULT '[]'::jsonb,
        created_at       TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_inf_regional_run ON inference_regional_signals(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_inf_regional_region ON inference_regional_signals(region, created_at DESC)",
    # ── Risk-appropriate sizing recommendations (advisory) ───────────────────
    """
    CREATE TABLE IF NOT EXISTS inference_sizing_recommendations (
        id                BIGSERIAL PRIMARY KEY,
        run_id            BIGINT REFERENCES inference_runs(id) ON DELETE CASCADE,
        proposal_id       BIGINT,                   -- paper_trade_proposals.id (nullable)
        symbol            TEXT,
        strategy_id       TEXT,
        account           TEXT,
        base_shares       INT,
        recommended_shares INT,
        tilt              NUMERIC,
        regime            TEXT,
        confidence        NUMERIC,
        risk_gate_result  TEXT,                     -- APPROVED|REJECTED|...
        risk_flags        JSONB DEFAULT '[]'::jsonb,
        rationale         TEXT,
        sizing_basis      JSONB DEFAULT '{}'::jsonb,
        applied           BOOLEAN DEFAULT false,    -- did the operator/engine write it back?
        created_at        TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_inf_sizing_run ON inference_sizing_recommendations(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_inf_sizing_prop ON inference_sizing_recommendations(proposal_id)",
    # ── Persistent inference memory ("mind of its own" state) ────────────────
    """
    CREATE TABLE IF NOT EXISTS inference_memory (
        id          BIGSERIAL PRIMARY KEY,
        mem_key     TEXT UNIQUE,                    -- stable key e.g. "regional:Asia:semis"
        kind        TEXT,                           -- regime|regional|journal|gap|watch
        value       JSONB DEFAULT '{}'::jsonb,
        salience    NUMERIC DEFAULT 0.5,            -- how much it should drive future action
        hit_count   INT DEFAULT 1,
        first_seen  TIMESTAMPTZ DEFAULT now(),
        updated_at  TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_inf_memory_kind ON inference_memory(kind, salience DESC)",
    # ── Proactive Hermes queries the engine decided to fire itself ───────────
    """
    CREATE TABLE IF NOT EXISTS inference_proactive_queries (
        id           BIGSERIAL PRIMARY KEY,
        run_id       BIGINT REFERENCES inference_runs(id) ON DELETE SET NULL,
        subject      TEXT,
        question     TEXT,
        trigger      TEXT,                          -- why the engine asked (gap, salience, ...)
        lane         TEXT,                          -- local|grok|chatgpt
        salience     NUMERIC,
        answer       TEXT,
        confidence   NUMERIC,
        status       TEXT DEFAULT 'asked',          -- asked|answered|failed
        created_at   TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_inf_proactive_run ON inference_proactive_queries(run_id)",
    # ── Extend news_articles with region tagging (Layer 3 capture) ───────────
    "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS region TEXT",
    "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS country TEXT",
    "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS geo_keywords JSONB",
    "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS region_tagged_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_news_region ON news_articles(region, created_at DESC)",
    # ── Multi-LLM ensemble validation (background-computed, displayed in the UI) ──
    """
    CREATE TABLE IF NOT EXISTS inference_ensemble_jobs (
        id            BIGSERIAL PRIMARY KEY,
        target_type   TEXT,                         -- 'inference' | 'proposal' | 'signal' | ...
        target_id     TEXT,                         -- id of the thing being validated
        subject       TEXT,                         -- display subject (symbol/topic)
        content       TEXT,                         -- the text the ensemble rates
        task          TEXT DEFAULT 'inference_quality',
        status        TEXT DEFAULT 'queued',        -- queued | running | done | error
        result_id     BIGINT,                       -- -> inference_ensemble_results.id
        error         TEXT,
        requested_by  TEXT DEFAULT 'operator',
        requested_at  TIMESTAMPTZ DEFAULT now(),
        started_at    TIMESTAMPTZ,
        finished_at   TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ens_jobs_status ON inference_ensemble_jobs(status, requested_at)",
    "CREATE INDEX IF NOT EXISTS idx_ens_jobs_target ON inference_ensemble_jobs(target_type, target_id, requested_at DESC)",
    "ALTER TABLE inference_ensemble_jobs ADD COLUMN IF NOT EXISTS lanes JSONB",
    """
    CREATE TABLE IF NOT EXISTS inference_ensemble_results (
        id                BIGSERIAL PRIMARY KEY,
        target_type       TEXT,
        target_id         TEXT,
        subject           TEXT,
        task              TEXT,
        content_hash      TEXT,
        final_decision    TEXT,                     -- approve | block
        final_score       NUMERIC,                  -- 0-10 avg
        final_confidence  NUMERIC,                  -- 0-1
        consensus_reached BOOLEAN,
        lanes_used        JSONB DEFAULT '[]'::jsonb,
        votes             JSONB DEFAULT '[]'::jsonb, -- [{lane,score,decision,confidence,reasoning}]
        reasoning_summary TEXT,
        created_at        TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ens_results_target ON inference_ensemble_results(target_type, target_id, created_at DESC)",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Create/upgrade Inference Layers schema")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="execute the DDL")
    g.add_argument("--dry-run", action="store_true", help="print the DDL only")
    args = ap.parse_args()

    if args.dry_run:
        for stmt in DDL:
            print(stmt.strip().splitlines()[0] + " ...")
        log.info("DRY RUN — %d statements", len(DDL))
        return 0

    from db_adapter import _execute, USE_DB
    if not USE_DB:
        log.error("DB disabled (USE_DB=False) — cannot apply schema")
        return 1

    ok = 0
    for stmt in DDL:
        res = _execute(stmt, fetch=None)
        if res:
            ok += 1
        else:
            log.warning("statement may have failed: %s", stmt.strip().splitlines()[0])
    log.info("applied %d/%d statements", ok, len(DDL))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
