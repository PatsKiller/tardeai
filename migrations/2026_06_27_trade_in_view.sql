-- TradeInView: saved filter groups + manual journal entries + tag definitions

CREATE TABLE IF NOT EXISTS journal_saved_filters (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_journal_saved_filters_name ON journal_saved_filters (name);

CREATE TABLE IF NOT EXISTS journal_manual_entries (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    account TEXT NOT NULL DEFAULT 'schwab_taxable',
    open_date DATE,
    close_date DATE,
    trade_type TEXT DEFAULT 'manual',
    shares NUMERIC,
    buy_price NUMERIC,
    sell_price NUMERIC,
    pnl NUMERIC,
    pnl_pct NUMERIC,
    notes TEXT,
    attachments JSONB DEFAULT '[]'::jsonb,
    template_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_journal_manual_symbol ON journal_manual_entries (symbol, close_date DESC);

CREATE TABLE IF NOT EXISTS journal_tag_groups (
    id BIGSERIAL PRIMARY KEY,
    group_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    parent_group TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed default tag groups (editable via API)
INSERT INTO journal_tag_groups (group_key, label, tags) VALUES
  ('strategy', 'Strategy', '["Breakout","Pullback","Earnings","Mean-Reversion","Covered Call","Iron Condor","Swing","Scalp"]'::jsonb),
  ('mistake', 'Mistakes', '["FOMO","Revenge","Oversize","Chased","Moved Stop","Early Exit","No Stop","Overtrading","Ignored Level"]'::jsonb),
  ('psychology', 'Psychology', '["Tilt","Overconfident","Hesitant","Calm","Anxious","Greedy","Fear"]'::jsonb),
  ('regime', 'Market Regime', '["Trending","Choppy","High IV","News Catalyst","Low Volume","Bull","Bear","Range-Bound"]'::jsonb)
ON CONFLICT (group_key) DO NOTHING;