-- v4.2 Unified Trades View
-- Pairs Buy/Sell from trade_transactions (Schwab, all brokers)
-- Unions with paper_trades (Alpaca automated)
-- Creates a single "trades" view for all brokers

-- Step 1: Materialized paired trades from trade_transactions
CREATE MATERIALIZED VIEW IF NOT EXISTS paired_trade_transactions AS
WITH buys AS (
    SELECT id as buy_txn_id, symbol, account, trade_date as entry_date,
           quantity as buy_qty, price as entry_price, amount as buy_amount,
           ROW_NUMBER() OVER (PARTITION BY symbol, account ORDER BY trade_date, id) as rn
    FROM trade_transactions
    WHERE action = 'Buy' AND price > 0 AND quantity > 0
),
sells AS (
    SELECT id as sell_txn_id, symbol, account, trade_date as exit_date,
           quantity as sell_qty, price as exit_price, amount as sell_amount,
           ROW_NUMBER() OVER (PARTITION BY symbol, account ORDER BY trade_date, id) as rn
    FROM trade_transactions
    WHERE action = 'Sell' AND quantity > 0
)
SELECT
    b.buy_txn_id,
    s.sell_txn_id,
    b.symbol,
    b.account,
    CASE
        WHEN b.account LIKE 'schwab%' THEN 'schwab'
        WHEN b.account LIKE 'alpaca%' THEN 'alpaca'
        WHEN b.account LIKE 'fidelity%' THEN 'fidelity'
        ELSE split_part(b.account, '_', 1)
    END as broker,
    b.entry_date,
    s.exit_date,
    LEAST(b.buy_qty, COALESCE(s.sell_qty, 0)) as shares,
    b.entry_price,
    COALESCE(s.exit_price, 0) as exit_price,
    ROUND((COALESCE(s.exit_price, 0) - b.entry_price) * LEAST(b.buy_qty, COALESCE(s.sell_qty, 0)), 2) as pnl,
    CASE WHEN b.entry_price > 0
        THEN ROUND(((COALESCE(s.exit_price, 0) - b.entry_price) / b.entry_price * 100)::numeric, 2)
        ELSE 0
    END as pnl_pct,
    EXTRACT(DAY FROM (COALESCE(s.exit_date, b.entry_date)::timestamp - b.entry_date::timestamp)) as hold_days,
    CASE WHEN s.sell_txn_id IS NULL THEN 'open' ELSE 'closed' END as status
FROM buys b
LEFT JOIN sells s ON b.symbol = s.symbol AND b.account = s.account
    AND s.exit_date >= b.entry_date AND s.rn = b.rn;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ptt_buy_txn ON paired_trade_transactions(buy_txn_id);
CREATE INDEX IF NOT EXISTS idx_ptt_symbol ON paired_trade_transactions(symbol);
CREATE INDEX IF NOT EXISTS idx_ptt_broker ON paired_trade_transactions(broker);
CREATE INDEX IF NOT EXISTS idx_ptt_account ON paired_trade_transactions(account);

-- Step 2: Unified trades view — all brokers, single interface
CREATE OR REPLACE VIEW trades AS
-- Alpaca automated trades (from paper_trades)
SELECT
    pt.id as trade_id,
    'paper_trades' as source_table,
    pt.symbol,
    COALESCE(pt.broker, 'alpaca') as broker,
    COALESCE(pt.target_account, pt.account, 'alpaca_paper') as account,
    pt.strategy_id,
    pt.entry_price,
    pt.entry_time::date as entry_date,
    pt.exit_price,
    pt.exit_time::date as exit_date,
    pt.shares,
    pt.pnl,
    pt.pnl_pct,
    pt.stop_loss,
    pt.target_1 as target_price,
    pt.r_multiple,
    pt.exit_reason,
    pt.hold_time_min,
    CASE WHEN pt.exit_time IS NOT NULL THEN 'closed'
         WHEN pt.exit_reason IS NOT NULL AND pt.exit_reason != '' THEN 'closed'
         ELSE 'open' END as status,
    pt.created_at
FROM paper_trades pt

UNION ALL

-- All broker trades (from paired trade_transactions)
SELECT
    ptt.buy_txn_id as trade_id,
    'trade_transactions' as source_table,
    ptt.symbol,
    ptt.broker,
    ptt.account,
    NULL as strategy_id,
    ptt.entry_price,
    ptt.entry_date,
    ptt.exit_price,
    ptt.exit_date,
    ptt.shares::integer,
    ptt.pnl,
    ptt.pnl_pct,
    NULL as stop_loss,
    NULL as target_price,
    NULL as r_multiple,
    CASE WHEN ptt.status = 'closed' THEN 'sell' ELSE NULL END as exit_reason,
    (ptt.hold_days * 24 * 60)::integer as hold_time_min,
    ptt.status,
    ptt.entry_date::timestamptz as created_at
FROM paired_trade_transactions ptt;
