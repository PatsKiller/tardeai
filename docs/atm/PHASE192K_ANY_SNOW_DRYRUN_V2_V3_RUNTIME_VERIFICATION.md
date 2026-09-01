# PHASE 192K — ANY/SNOW Dry-Run + v2/v3 Runtime Verification

Status:      HISTORICAL
as_of:       2026-06-02T12:10:31-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~11:45 ET · Alpaca **paper** only · **No order submitted.**

---

## Dry-run adjustment candidates

### ANY (trade 48) — URGENT
| Candidate | Stop | Profit locked | Giveback | Allowed (exec)? |
|---|---|---|---|---|
| KEEP_CURRENT_STOP | 3.07 | $0 | $501 | n/a |
| MOVE_STOP_TO_BREAKEVEN | 3.07→3.23 | $0 | $501→$402 | ✅ |
| **MOVE_STOP_TO_PROFIT_LOCK** | 3.07→**3.555** | $0→**$201** | $501→**$201** | ✅ (dry-run passed all guards) |
| ADD_FIXED_TAKE_PROFIT | TP ~4.27 | $0 | $501 | review-only |
| CONVERT_TO_TRAILING_STOP | trailing | $0 | $501 | review-only |

Engine dry-run on the profit-lock candidate → `DRY_RUN_PREVIEW`, all guards PASSED, **broker stop
unchanged (3.07)**. Not submitted (held for operator `confirm=true`).

### SNOW (trade 43) — TAKE_PROFIT
| Candidate | Stop | Profit locked | Giveback | Notes |
|---|---|---|---|---|
| KEEP_CURRENT_STOP | 254.38 | ~$143 | ~$13 | already protective |
| MOVE_STOP_TO_PROFIT_LOCK | 254.38→~256 | ~$143→~$157 | small | marginal (stop already locks) |
| ADD_FIXED_TAKE_PROFIT | TP ~282 | ~$143 | — | primary advisory for SNOW |

SNOW's urgency is low (stop already locks profit) → take-profit is the relevant candidate.

## v2 runtime verification
| Check | Result |
|---|---|
| API loads | ✅ proposals 200 (22), advisory 200 |
| Panel visible (`/v2/paper-status`) | ✅ bundled + served |
| ANY proposal visible | ✅ URGENT + profit-lock candidate |
| SNOW proposal visible | ✅ TAKE_PROFIT |
| Evidence visible (TradeAI + Hermes) | ✅ |
| Paper-only badge | ✅ |
| No unauthorized order modification | ✅ buttons disabled; broker unchanged |

## v3 runtime verification
| Check | Result |
|---|---|
| API loads (same endpoints) | ✅ (shared backend) |
| Panel visible | ⏳ route `/v3/trading` exists; panel pending (192H plan — operator merge) |
| ANY/SNOW visible if applicable | via shared API once panel added |
| Evidence / paper-only badge | per 192H spec (identical to v2) |
| No unauthorized order modification | ✅ (no execution controls anywhere) |

**v2/v3 parity:** API parity **PASS**; UI parity **v2 shipped, v3 specified + route-ready** (not
v2-only). Full v3 visual parity is one component + build away, deferred to avoid the in-flight v3
rebuild conflict.

No stop modified, no order placed, no live endpoint touched.
