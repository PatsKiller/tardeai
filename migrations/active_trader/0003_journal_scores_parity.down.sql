-- Active Trader Stage 1 · 0003 journal, score snapshots, parity checks (down)
DROP TABLE IF EXISTS active_trader_parity_checks;
DROP TABLE IF EXISTS active_trader_score_snapshots;
DROP TRIGGER IF EXISTS trg_journal_events_append_only ON active_trader_journal_events;
DROP TABLE IF EXISTS active_trader_journal_events;
