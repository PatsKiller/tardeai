# Cross-Asset Decision Intelligence — Test Plan

Status: ACTIVE  
as_of: 2026-09-29  
Authority: Implementation Plan + Backlog CADI-*  

## Unit Tests

| ID | Case | Pass |
|---|---|---|
| U1 | `new_symbol_decision` has all field groups | keys present |
| U2 | `validate_symbol_decision` rejects missing identity.symbol | raises/returns ok=False |
| U3 | persist + load_latest roundtrip | equal symbol |
| U4 | assemble NFLX fixture sets research_state from Hermes result | result_id linked |
| U5 | Buy signal routes shares+long_call+CSP+debit_spread | four families |
| U6 | Hold routes covered_call+protective_put; collar unavailable | honest status |
| U7 | Reentry routes shares+CSP+spread | three families |
| U8 | Sell routes sell_shares+protective_put; collar unavailable | honest |
| U9 | Shadow flag off → event hook no ledger write | no file growth |
| U10 | Missed opportunity when chosen≠top | ledger row |

## Integration Tests

| ID | Case | Pass |
|---|---|---|
| I1 | Shadow cycle dry-run over 2 symbols returns ranked objects | ok |
| I2 | Assemble with empty stores still validates | incomplete but valid |

## Scheduler Tests

| ID | Case | Pass |
|---|---|---|
| S1 | CLI exit 0 dry-run | documented; timer not installed until Phase 8 READY |

## Persistence Tests

| ID | Case | Pass |
|---|---|---|
| P1 | Append never truncates prior rows | line count +1 |
| P2 | Corrupt line skipped on load_latest | no raise |

## CIO / Research / Options / Re-entry / Watchlist

| ID | Case | Pass |
|---|---|---|
| C1 | cio_state passthrough on assemble | equals fixture |
| R1 | hermes result_id / research_id on research_state | linked |
| O1 | options_state embeds packet schema name when provided | OptionsDecisionPacket@v2 |
| E1 | reentry signal_kind drives CSP candidates | present |
| W1 | watch provenance → identity.subject_guid when present | linked |

## Historical Replay

| ID | Case | Pass |
|---|---|---|
| H1 | 30d with no archive → metrics `data_quality=INSUFFICIENT_DATA` | honest |
| H2 | 60d/90d same honesty path until archives wired | honest |

## Regression

| ID | Case | Pass |
|---|---|---|
| G1 | Existing options_strategy_matrix tests unaffected | green |
| G2 | No broker import in cross_asset package | grep gate |

## Evidence log

| Date | Suite | Result | Commit |
|---|---|---|---|
| 2026-09-29 | unit CADI (8 tests) | **8 passed** | _(set on commit)_ |
| 2026-09-29 | shadow dry-run NFLX buy | ok=true top=shares ranked=4 | CLI |
| 2026-09-29 | historical 30/60/90 | INSUFFICIENT_DATA (honest) | `/tmp/cadi_hist_metrics.json` |
| 2026-09-29 | broker import grep on cross_asset | clean | — |
