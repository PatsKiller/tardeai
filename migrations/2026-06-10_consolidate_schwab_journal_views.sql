-- Consolidate Schwab journal: paired_trade_transactions (was a stale materialized view, crude
-- row-number pairing, frozen 2026-04-30) -> live VIEW over schwab_round_trips (corrected basis, 5-min
-- agg, FIFO-by-qty). trades view recreated unchanged. Single Schwab source of truth.
BEGIN;
DROP VIEW trades;
DROP MATERIALIZED VIEW paired_trade_transactions;
CREATE VIEW paired_trade_transactions AS
SELECT srt.id AS buy_txn_id, srt.id AS sell_txn_id, srt.symbol, srt.account,
  'schwab'::text AS broker, (srt.entry_time)::date AS entry_date, (srt.exit_time)::date AS exit_date,
  srt.qty AS shares, srt.entry_price, srt.exit_price, srt.net_pnl AS pnl, srt.pnl_pct,
  EXTRACT(day FROM ((srt.exit_time)::timestamp - (srt.entry_time)::timestamp)) AS hold_days,
  'closed'::text AS status, 'Buy'::text AS buy_action
FROM schwab_round_trips srt
WHERE srt.basis_status IS DISTINCT FROM 'basis_unknown' AND srt.entry_time IS NOT NULL;
CREATE VIEW trades AS
 SELECT pt.id AS trade_id,
    'paper_trades'::text AS source_table,
    pt.symbol,
    COALESCE(pt.broker, 'alpaca'::text) AS broker,
    COALESCE(pt.target_account, pt.account, 'alpaca_paper'::text) AS account,
    pt.strategy_id,
    pt.entry_price,
    pt.entry_time::date AS entry_date,
    pt.exit_price,
    pt.exit_time::date AS exit_date,
    pt.shares,
    pt.pnl,
    pt.pnl_pct,
    pt.stop_loss,
    pt.target_1 AS target_price,
    pt.r_multiple,
    pt.exit_reason,
    pt.hold_time_min,
        CASE
            WHEN pt.exit_time IS NOT NULL THEN 'closed'::text
            WHEN pt.exit_reason IS NOT NULL AND pt.exit_reason <> ''::text THEN 'closed'::text
            ELSE 'open'::text
        END AS status,
    pt.created_at
   FROM paper_trades pt
UNION ALL
 SELECT ptt.buy_txn_id AS trade_id,
    'trade_transactions'::text AS source_table,
    ptt.symbol,
    ptt.broker,
    ptt.account,
    NULL::text AS strategy_id,
    ptt.entry_price,
    ptt.entry_date,
    ptt.exit_price,
    ptt.exit_date,
    ptt.shares::integer AS shares,
    ptt.pnl,
    ptt.pnl_pct,
    NULL::numeric AS stop_loss,
    NULL::numeric AS target_price,
    NULL::numeric AS r_multiple,
        CASE
            WHEN ptt.status = 'closed'::text THEN 'sell'::text
            ELSE NULL::text
        END AS exit_reason,
    (ptt.hold_days * 24::numeric * 60::numeric)::integer AS hold_time_min,
    ptt.status,
    ptt.entry_date::timestamp with time zone AS created_at
   FROM paired_trade_transactions ptt
;
COMMIT;
