# Execution Safety Guards (ADR-B3)

**Status:** ACCEPTED — the safety contract of the whole program. Schwab has NO paper environment, so these
guards ARE the environment separation.

## Execution modes (`BrokerExecutionMode`)
| Mode | Meaning | I/O allowed | Who uses it |
|---|---|---|---|
| `SIMULATION` | internal sim only, no broker calls | none | tests, what-ifs |
| `PAPER_TRAINING` | Alpaca paper pipeline (training) | Alpaca paper API | the EXISTING pipeline, unchanged |
| `BROKER_DRY_RUN` | translate + validate + audit, **zero order-endpoint HTTP** (operator decision 2026-06-11) | none on order surface | Schwab previews |
| `BROKER_DISABLED` | adapter registered, everything blocked | none | **Schwab default this phase** |
| `LIVE_ENABLED_FUTURE` | reserved; cannot be reached by config alone | n/a | nobody |

## Guard rules (fail-closed, tested)
1. Missing/unknown config → `BROKER_DISABLED`. Unknown broker → BLOCKED.
2. `LIVE_ENABLED_FUTURE` additionally requires ALL of: env flag `BROKER_LIVE_ENABLED=true` AND a DB
   `system_controls` row AND a signed operator approval record — none exist; checks fail closed; and even
   then this phase's Schwab adapter raises `ExecutionBlocked` unconditionally in `submit()`.
3. Every authorize() decision (grant or block) emits an `intent_state_events` audit row with reason +
   correlation_id.
4. The existing fences are UNTOUCHED and remain authoritative beneath this layer: schwab_transport
   NotProvenWrite (validate_schwab_no_writes 12/12), ALPACA paper-only init checks, LIVE_TRADING_ENABLED,
   live_trading_gate. The guard layer sits ABOVE them; defense in depth, not replacement.
5. `scripts/brokers/` imports neither schwab-py nor transport write methods — verified by the no-writes
   validator continuing to pass (boundary rule) and by test_no_write_imports.

## Non-conflation guarantee
`PAPER_TRAINING` (Alpaca) and Schwab modes are disjoint enum values with disjoint adapters; no registry or
flag flip can re-point the training pipeline at Schwab. The training submitter never consults the Schwab
adapter; the Broker-Orders surface never consults the Alpaca training path.

## Release gating checklist (future live enablement — OUT OF SCOPE now)
operator-signed approval record · 30+ reconciled dry-run translations reviewed · order-event streaming or
≤1-min polling proven · replace/cancel semantics verified on dev account · rate-limit confirmation ·
kill-switch drill · rollback plan · validator extended with live-path assertions BEFORE any unfencing.
