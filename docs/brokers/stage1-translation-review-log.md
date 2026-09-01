# Stage-1 Translation Review Log

Status:      ACTIVE
as_of:       2026-06-11T18:20:34-04:00
Measured at: efcc51365 / not measured

**Run:** repeatable via `scripts/brokers/translation_review.py` · **Cases:** 30 · **Defects:** 0 · **Guard grants:** 0 expected/0 allowed

Real recent symbols/prices from paper_trades ground every case. Every preview persisted as
an audited draft (broker_order_intents) — inspect via GET /api/v2/broker-orders/drafts.

| # | Case | Intent summary | Verdict | Notes |
|---|---|---|---|---|
| 1 | bracket_ELVN | LONG ELVN LIMIT @41.65 qty=2 tif=DAY sess=NORMAL | **CLEAN** | root=TRIGGER |
| 2 | bracket_ATOS | LONG ATOS LIMIT @2.56 qty=2 tif=DAY sess=NORMAL | **CLEAN** | root=TRIGGER |
| 3 | bracket_BLBD | LONG BLBD LIMIT @68.73 qty=2 tif=DAY sess=NORMAL | **CLEAN** | root=TRIGGER |
| 4 | bracket_NUVL | LONG NUVL LIMIT @123.43375 qty=2 tif=DAY sess=NORMAL | **CLEAN** | root=TRIGGER |
| 5 | market_bracket_NUVL | LONG NUVL MARKET qty=2 tif=DAY sess=NORMAL | **CLEAN** | root=TRIGGER |
| 6 | stop_entry_INFU | LONG INFU STOP qty=2 tif=DAY sess=NORMAL | **CLEAN** | ok |
| 7 | stop_limit_entry_BWEN | LONG BWEN STOP_LIMIT @4.095 qty=2 tif=DAY sess=NORMAL | **CLEAN** | ok |
| 8 | trail_LAST_PERCENT_BWEN | LONG BWEN LIMIT @4.16 qty=2 tif=DAY sess=NORMAL | **CLEAN** | trail={'basis': 'LAST', 'type': 'PERCENT', 'offset': 3.0} |
| 9 | trail_BID_VALUE_BWEN | LONG BWEN LIMIT @4.16 qty=2 tif=DAY sess=NORMAL | **CLEAN** | trail={'basis': 'BID', 'type': 'VALUE', 'offset': 0.5} |
| 10 | trail_MARK_TICK_MRVL | LONG MRVL LIMIT @284.49 qty=2 tif=DAY sess=NORMAL | **CLEAN** | trail={'basis': 'MARK', 'type': 'TICK', 'offset': 5} |
| 11 | trail_ASK_PERCENT_MRVL | LONG MRVL LIMIT @284.49 qty=2 tif=DAY sess=NORMAL | **CLEAN** | trail={'basis': 'ASK', 'type': 'PERCENT', 'offset': 2.5} |
| 12 | multi_target_MRVL | LONG MRVL LIMIT @284.49 qty=2 tif=DAY sess=NORMAL | **CLEAN** | ok |
| 13 | ladder2_ELVN | LONG ELVN LIMIT @41.65 qty=2 tif=DAY sess=NORMAL | **CLEAN** | order_count=2 |
| 14 | ladder3_ELVN | LONG ELVN LIMIT @41.65 qty=2 tif=DAY sess=NORMAL | **CLEAN** | order_count=3 |
| 15 | short_bracket_ATOS | SHORT ATOS LIMIT @2.56 qty=2 tif=DAY sess=NORMAL | **CLEAN** | ok |
| 16 | short_market_ATOS | SHORT ATOS MARKET qty=2 tif=DAY sess=NORMAL | **CLEAN** | ok |
| 17 | bid_link_entry_BLBD | LONG BLBD LIMIT @68.73 qty=2 tif=DAY sess=NORMAL | **CLEAN** | ok |
| 18 | entry_range_NUVL | LONG NUVL LIMIT qty=2 tif=DAY sess=NORMAL | **CLEAN** | ok |
| 19 | session_AM_NUVL | LONG NUVL LIMIT @123.53 qty=2 tif=DAY sess=AM | **CLEAN** | ok |
| 20 | session_PM_INFU | LONG INFU LIMIT @9.08 qty=2 tif=DAY sess=PM | **CLEAN** | ok |
| 21 | session_SEAMLESS_BWEN | LONG BWEN LIMIT @4.095 qty=2 tif=DAY sess=SEAMLESS | **CLEAN** | ok |
| 22 | tif_GTC_BWEN | LONG BWEN LIMIT @4.16 qty=2 tif=GTC sess=NORMAL | **CLEAN** | ok |
| 23 | tif_FOK_BWEN | LONG BWEN LIMIT @4.16 qty=2 tif=FOK sess=NORMAL | **CLEAN** | ok |
| 24 | tif_IOC_MRVL | LONG MRVL LIMIT @284.49 qty=2 tif=IOC sess=NORMAL | **CLEAN** | ok |
| 25 | moc_MRVL | LONG MRVL MARKET_ON_CLOSE qty=2 tif=DAY sess=NORMAL | **CLEAN** | ok |
| 26 | stop_only_MRVL | LONG MRVL LIMIT @284.49 qty=2 tif=DAY sess=NORMAL | **CLEAN** | root=TRIGGER |
| 27 | target_only_MRVL | LONG MRVL LIMIT @284.49 qty=2 tif=DAY sess=NORMAL | **CLEAN** | root=TRIGGER |
| 28 | reject_bad_stop | LONG ELVN LIMIT @41.65 qty=2 tif=DAY sess=NORMAL | **REJECTED-AS-EXPECTED** | expect_invalid=below entry |
| 29 | blocked_options | LONG NVDA LIMIT @5.0 qty=2 tif=DAY sess=NORMAL | **REJECTED-AS-EXPECTED** | expect_invalid=BLOCKED_CAPABILITY |
| 30 | blocked_notional | LONG ELVN LIMIT @41.65 qty=2000.0 tif=DAY sess=NORMAL | **BLOCKED-AS-EXPECTED** | expect_blocked_cap=fractional |

## Verdict: ZERO TRANSLATION DEFECTS — Stage-1 gate criteria met

Operator sign-off required to advance to Stage 2 (dev-account validation of UNVERIFIED items).