-- Rename canonical automated-trading account: alpaca_paper → tradeai_automated
-- Idempotent: safe to re-run (only updates rows still on the legacy key).

BEGIN;

UPDATE accounts SET account_label = 'tradeai_automated' WHERE account_label = 'alpaca_paper';
UPDATE broker_accounts SET account_key = 'tradeai_automated', display_name = COALESCE(NULLIF(display_name, ''), 'Automated (Alpaca)')
 WHERE account_key = 'alpaca_paper';
UPDATE paper_trades SET account = 'tradeai_automated' WHERE account IN ('alpaca_paper', 'ALPACA_PAPER', 'paper', 'PAPER');
UPDATE paper_trade_proposals SET target_account = 'tradeai_automated' WHERE target_account IN ('alpaca_paper', 'ALPACA_PAPER', 'paper', 'PAPER');
UPDATE paper_trade_proposals SET proposed_account = 'tradeai_automated' WHERE proposed_account IN ('alpaca_paper', 'ALPACA_PAPER', 'paper', 'PAPER');

COMMIT;