# Paper Trades — Full Row Export

## All paper_trades (including ghost/closed)
```
 id | symbol |        strategy_id         | entry_price | stop_loss | shares |   account    |          entry_time           |           exit_time           |               exit_reason               | exit_price |        pnl         | signal_id |             reconciliation_status             
----+--------+----------------------------+-------------+-----------+--------+--------------+-------------------------------+-------------------------------+-----------------------------------------+------------+--------------------+-----------+-----------------------------------------------
  1 | SMX    | momentum_scalp             |        1.29 |      1.23 |   1550 | ALPACA_PAPER | 2026-05-06 18:46:13.428516-04 |                               | cancelled_never_submitted_to_broker     |            |                    |           | GHOST_CANCELLED_NEVER_SUBMITTED_TO_BROKER
  2 | MNKD   | gap_and_go                 |        3.56 |      3.38 |    561 | ALPACA_PAPER | 2026-05-06 22:06:43.690992-04 |                               | cancelled_never_submitted_to_broker     |            |                    |           | GHOST_CANCELLED_NEVER_SUBMITTED_TO_BROKER
  3 | XMTR   | swing_breakout             |       79.25 |     75.29 |     26 | ALPACA_PAPER | 2026-05-11 10:37:34.796095-04 |                               | position_closed_in_alpaca               |      82.93 |               95.6 |           | GHOST_POSITION_CLOSED_IN_ALPACA
  4 | EVC    | screener                   |        8.12 |      7.71 |    390 | ALPACA_PAPER | 2026-05-11 10:37:34.796095-04 |                               | position_closed_in_alpaca               |       8.64 |              202.8 |           | GHOST_POSITION_CLOSED_IN_ALPACA
  5 | XMTR   | swing_breakout             |             |     72.49 |     26 | ALPACA_PAPER |                               |                               |                                         |            |                    |           | TRULY_OPEN
  6 | EVC    | screener                   |             |      7.31 |    390 | ALPACA_PAPER |                               |                               | order_canceled_by_alpaca                |            |                    |           | GHOST_ORDER_CANCELED_BY_ALPACA
  7 | INFU   | swing_breakout             |        8.39 |      7.97 |    357 | ALPACA_PAPER | 2026-05-11 11:00:09.148221-04 |                               |                                         |            |                    |           | TRULY_OPEN
  8 | INFU   | swing_breakout             |        8.39 |      7.97 |    357 | ALPACA_PAPER |                               |                               |                                         |            |                    |           | TRULY_OPEN
  9 | INFU   | earnings_catalyst          |        8.39 |      7.97 |    357 | ALPACA_PAPER | 2026-05-11 11:11:11.429028-04 |                               |                                         |            |                    |           | TRULY_OPEN
 10 | FLYW   | swing_trade                |       17.51 |     16.63 |    171 | ALPACA_PAPER | 2026-05-11 11:11:26.599488-04 |                               |                                         |            |                    |           | TRULY_OPEN
 11 | FLYW   | swing_trade                |       17.51 |     16.63 |    171 | ALPACA_PAPER |                               |                               |                                         |            |                    |           | TRULY_OPEN
 12 | FLYW   | swing_trade                |       16.74 |     16.63 |    171 | ALPACA_PAPER | 2026-05-11 11:16:54.342003-04 |                               | position_closed_in_alpaca               |      16.65 |             -15.39 |           | GHOST_POSITION_CLOSED_IN_ALPACA
 13 | INFU   | swing_breakout             |        8.39 |      7.97 |    357 | ALPACA_PAPER | 2026-05-11 11:00:09.148221-04 | 2026-05-13 13:31:49.540198-04 | manual_stale_close                      |       8.58 |              67.83 |           | CLOSED_WITH_TIME
 15 | BLBD   | earnings_catalyst          |       80.24 |     76.23 |     37 | TOS_PAPER    | 2026-05-12 11:53:51.726647-04 |                               |                                         |      68.08 |            -449.92 |           | TRULY_OPEN
 16 | BLBD   | earnings_catalyst          |       68.48 |     76.23 |     37 | ALPACA_PAPER | 2026-05-12 11:53:52-04        |                               | stop_hit_instant                        |      68.08 |             -14.80 |           | GHOST_STOP_HIT_INSTANT
 17 | FLYW   | swing_breakout             |       17.51 |     16.63 |    171 | TOS_PAPER    | 2026-05-12 11:53:58.417993-04 |                               |                                         |            |                    |           | TRULY_OPEN
 18 | FLYW   | swing_breakout             |       17.51 |     16.63 |    171 | ALPACA_PAPER |                               |                               |                                         |            |                    |           | TRULY_OPEN
 19 | FLYW   | momentum_scalp             |       16.75 |           |    171 | ALPACA_PAPER | 2026-05-12 12:00:01.879258-04 |                               | stop_hit                                |      16.63 |             -20.52 |           | GHOST_STOP_HIT
 20 | GCTS   | momentum_scalp             |        1.49 |      1.42 |   1875 | ALPACA_PAPER | 2026-05-13 13:12:50.893708-04 |                               | duplicate_of_22                         |      1.485 |                  0 |           | GHOST_DUPLICATE_OF_22
 21 | INFU   | earnings_catalyst          |        8.61 |      7.97 |    357 | ALPACA_PAPER |                               |                               | target_hit                              |       9.34 |             261.57 |           | GHOST_TARGET_HIT
 22 | GCTS   | momentum_scalp             |        1.49 |      1.42 |   1875 | ALPACA_PAPER | 2026-05-13 15:00:01.842098-04 |                               | stop_hit                                |       1.37 |             -225.0 |           | GHOST_STOP_HIT
 23 | GCTS   | momentum_scalp             |        1.49 |           |   1875 | ALPACA_PAPER | 2026-05-13 16:00:01.913585-04 |                               | bogus_duplicate_no_exit_price           |            |                    |           | GHOST_BOGUS_DUPLICATE_NO_EXIT_PRICE
 24 | FLYW   | dividend_growth_compounder |       16.29 |     15.48 |    171 | ALPACA_PAPER | 2026-05-14 11:14:44.782786-04 |                               | stop_hit                                |      16.45 |              27.36 |           | GHOST_STOP_HIT
 26 | ASPN   | swing_trade                |        5.42 |      5.15 |    553 | TOS_PAPER    | 2026-05-21 11:51:04.818992-04 |                               |                                         |            |                    |           | TRULY_OPEN
 27 | ASPN   | swing_trade                |        5.52 |      5.15 |    553 | ALPACA_PAPER |                               |                               | target_hit                              |      6.015 |             273.74 |           | GHOST_TARGET_HIT
 28 | NWG    | dividend_growth_compounder |       15.84 |     15.05 |    189 | TOS_PAPER    | 2026-05-22 11:30:02.39294-04  |                               |                                         |            |               56.7 |           | TRULY_OPEN
 29 | NVDA   | dividend_growth_compounder |       218.0 |    210.58 |     13 | TOS_PAPER    | 2026-05-22 11:30:05.812707-04 | 2026-05-26 12:30:54.835558-04 | operator_stop_out                       |   213.1001 | -4.899900000000002 |           | CLOSED_WITH_TIME
 30 | AGNC   | reit_income                |       10.22 |      9.71 |    293 | TOS_PAPER    | 2026-05-22 11:30:08.541774-04 |                               | orphan_duplicate_from_partial_fill_race |            |                    |           | GHOST_ORPHAN_DUPLICATE_FROM_PARTIAL_FILL_RACE
 31 | AGNC   | reit_income                |       10.22 |      9.71 |    293 | ALPACA_PAPER |                               |                               |                                         |            |              60.06 |           | TRULY_OPEN
 32 | CMCSA  | dividend_growth_compounder |       24.85 |     23.61 |    120 | TOS_PAPER    | 2026-05-22 11:30:13.251622-04 |                               | orphan_duplicate_from_partial_fill_race |            |                    |           | GHOST_ORPHAN_DUPLICATE_FROM_PARTIAL_FILL_RACE
 33 | CMCSA  | dividend_growth_compounder |       24.97 |     23.61 |    120 | ALPACA_PAPER |                               |                               |                                         |            |               19.8 |           | TRULY_OPEN
(31 rows)

```

## Truly open (exit_time IS NULL AND exit_reason IS NULL)
```
 id | symbol |        strategy_id         | entry_price | stop_loss | shares |   account    |          entry_time           
----+--------+----------------------------+-------------+-----------+--------+--------------+-------------------------------
  5 | XMTR   | swing_breakout             |             |     72.49 |     26 | ALPACA_PAPER | 
  7 | INFU   | swing_breakout             |        8.39 |      7.97 |    357 | ALPACA_PAPER | 2026-05-11 11:00:09.148221-04
  8 | INFU   | swing_breakout             |        8.39 |      7.97 |    357 | ALPACA_PAPER | 
  9 | INFU   | earnings_catalyst          |        8.39 |      7.97 |    357 | ALPACA_PAPER | 2026-05-11 11:11:11.429028-04
 10 | FLYW   | swing_trade                |       17.51 |     16.63 |    171 | ALPACA_PAPER | 2026-05-11 11:11:26.599488-04
 11 | FLYW   | swing_trade                |       17.51 |     16.63 |    171 | ALPACA_PAPER | 
 15 | BLBD   | earnings_catalyst          |       80.24 |     76.23 |     37 | TOS_PAPER    | 2026-05-12 11:53:51.726647-04
 17 | FLYW   | swing_breakout             |       17.51 |     16.63 |    171 | TOS_PAPER    | 2026-05-12 11:53:58.417993-04
 18 | FLYW   | swing_breakout             |       17.51 |     16.63 |    171 | ALPACA_PAPER | 
 26 | ASPN   | swing_trade                |        5.42 |      5.15 |    553 | TOS_PAPER    | 2026-05-21 11:51:04.818992-04
 28 | NWG    | dividend_growth_compounder |       15.84 |     15.05 |    189 | TOS_PAPER    | 2026-05-22 11:30:02.39294-04
 31 | AGNC   | reit_income                |       10.22 |      9.71 |    293 | ALPACA_PAPER | 
 33 | CMCSA  | dividend_growth_compounder |       24.97 |     23.61 |    120 | ALPACA_PAPER | 
(13 rows)

```

## Ghost records (exit_reason set, exit_time NULL)
```
 id | symbol |        strategy_id         |               exit_reason               | exit_price |  pnl   
----+--------+----------------------------+-----------------------------------------+------------+--------
  1 | SMX    | momentum_scalp             | cancelled_never_submitted_to_broker     |            |       
  2 | MNKD   | gap_and_go                 | cancelled_never_submitted_to_broker     |            |       
  3 | XMTR   | swing_breakout             | position_closed_in_alpaca               |      82.93 |   95.6
  4 | EVC    | screener                   | position_closed_in_alpaca               |       8.64 |  202.8
  6 | EVC    | screener                   | order_canceled_by_alpaca                |            |       
 12 | FLYW   | swing_trade                | position_closed_in_alpaca               |      16.65 | -15.39
 16 | BLBD   | earnings_catalyst          | stop_hit_instant                        |      68.08 | -14.80
 19 | FLYW   | momentum_scalp             | stop_hit                                |      16.63 | -20.52
 20 | GCTS   | momentum_scalp             | duplicate_of_22                         |      1.485 |      0
 21 | INFU   | earnings_catalyst          | target_hit                              |       9.34 | 261.57
 22 | GCTS   | momentum_scalp             | stop_hit                                |       1.37 | -225.0
 23 | GCTS   | momentum_scalp             | bogus_duplicate_no_exit_price           |            |       
 24 | FLYW   | dividend_growth_compounder | stop_hit                                |      16.45 |  27.36
 27 | ASPN   | swing_trade                | target_hit                              |      6.015 | 273.74
 30 | AGNC   | reit_income                | orphan_duplicate_from_partial_fill_race |            |       
 32 | CMCSA  | dividend_growth_compounder | orphan_duplicate_from_partial_fill_race |            |       
(16 rows)

```
