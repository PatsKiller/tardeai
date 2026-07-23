-- Active Trader Stage 1 · 0001 sessions (down)
DROP TABLE IF EXISTS active_trader_session_accounts;
DROP TABLE IF EXISTS active_trader_session_authorizations;
DROP TRIGGER IF EXISTS trg_session_drafts_append_only ON active_trader_session_drafts;
DROP TABLE IF EXISTS active_trader_session_drafts;
DROP FUNCTION IF EXISTS active_trader_forbid_mutation();
