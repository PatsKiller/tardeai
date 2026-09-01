# PHASE 192B — Profit-Protection Adjustment Preflight

Status:      HISTORICAL
as_of:       2026-06-02T12:10:31-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~11:40 ET · Alpaca **paper** only

| Check | Result |
|---|---|
| git status (mine) | clean before phase; pre-existing dirty `config/strategies/*` untouched |
| ALPACA_MODE / account mode | **paper** (`ALPACA_MODE=paper`, account PA3E93QWASV1) |
| Live endpoint blocked | ✅ paper-api only; engine hard-asserts paper base |
| Live trading disabled | ✅ ZERO live trades |
| Level 7 | PROHIBITED |
| Open paper positions | 6 (NWG, AGNC, CMCSA, SNOW, TMHC, ANY) |
| Broker stop orders | 6 (all `status=new`, re-verified) |
| Profit-protection advisories | present (ANY=URGENT, SNOW=TAKE_PROFIT, 4×NO_ACTION) |
| Hermes opinions | present (caution on ANY/SNOW) |
| ANY/SNOW/TMHC `stop_order_id` in DB | ✅ all tracked |
| Current take-profit orders | **none** (TP missing on all 6) |

## Per-position snapshot (live quotes)
| Sym | id | qty | entry | px | broker stop | stop_order_id | TP | uPnL | uPnL% | locked | giveback | TradeAI | Hermes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ANY | 48 | 619 | 3.23 | ~4.1 | 3.07 | ✅ | none | +$501 | +20% | $0 | ~$501 | URGENT_PROTECTION_REVIEW | caution |
| SNOW | 43 | 8 | 236.50 | ~256 | 254.38 | ✅ | none | +$158 | +8% | ~$143 | ~$13 | TAKE_PROFIT_ADVISORY | caution |
| TMHC | 47 | 27 | 71.61 | ~71.6 | 68.02 | ✅ | none | ~$0 | -0.1% | $0 | ~$97 | NO_ACTION | agree |
| NWG | 28 | 189 | 15.84 | ~15.9 | 15.05 | ✅ | none | +$64 | +2% | $0 | — | NO_ACTION | agree |
| AGNC | 31 | 293 | 10.22 | ~10.3 | 9.71 | ✅ | none | +$25 | +0.8% | $0 | — | NO_ACTION | agree |
| CMCSA | 33 | 120 | 24.97 | ~24.9 | 23.61 | ✅ | none | -$16 | -0.5% | $0 | — | NO_ACTION | agree |

Marks are live-quote-dependent. No order was placed or modified during preflight.
