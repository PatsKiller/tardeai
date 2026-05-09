-- Migration: System Facts History
-- Date: 2026-05-09
-- Idempotent: safe to re-run

CREATE TABLE IF NOT EXISTS system_facts_history (
    id bigserial PRIMARY KEY,
    generated_at timestamptz DEFAULT now(),
    facts jsonb NOT NULL,
    drift jsonb,
    checksum text
);
