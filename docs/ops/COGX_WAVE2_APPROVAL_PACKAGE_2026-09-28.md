# COGX Wave 2 approval package — pkg-20260928-wave-2-enforcement-35c4

```
Status:      ACTIVE (APPROVED all decidable items 2026-09-27 ~21:20 ET by typed reply: "APPROVE pkg-20260928-wave-2-enforcement-35c4 all"; item 7 NEEDS_LOCAL)
as_of:       2026-09-27T21:45:00-04:00
Measured at: main 8e191c4ee / served 8e191c4ee-main-exact-phase2-20260927-210702 (Wave 1 + findings + Wave 2 tranche 1 shadow)
Authority:   READ_ONLY_ADVISORY. Ledger row: persistent-state/data/governance/approval_packages.jsonl (29 rows, chain verified).
Package:     docs/architecture/cognitive_transformation_20260927/ (11, 13); spec docs/ops/COGX_WAVE2_PACKAGE_SPEC.json
```

## Delivery `[VERIFIED]`
Created in the live ledger via `approval_package_cli.py create --apply` (PR #1313 bound), rendered (2,807 chars, one chunk), sent through
`telegram_alert.send_telegram_with_id(bypass_router=True)` after a `split_for_telegram` dry run → message ids 54503/54504; `submit --apply`
recorded SUBMITTED; the operator's typed reply was applied with `decide --apply --by operator:mine:typed` → APPROVED.

## Items and state
| # | Item | State | Execution |
|---|---|---|---|
| 1 | Ring 2 mode flip, per surface, starting with persistent-wake | APPROVED | tranche 2: per-lane `context:<lane_id>` policy rows + fail-closed HOLD path on the wake hook, deployed in SHADOW; the flip to ENFORCED is a one-line policy PR after one live cycle of non-degraded receipts (the first shadow receipts were 100 % degraded on three lanes because of an import-shape defect in the façade loaders, fixed in tranche 2) |
| 2 | six producer adapters through accept_research_result | APPROVED | tranche 3 |
| 3 | commit publishes memory.delta; edge projector consumes it | APPROVED | publish live since tranche 1; consumer = tranche 3 |
| 4 | new lane edge-fanout-consumer | APPROVED | tranche 3 (service grant) |
| 5 | SEC 8-K / 10-Q filings feed | APPROVED | tranche 4 (cron grant; DSA row) |
| 6 | mint symbol sources + monthly Schwab re-ask | APPROVED | sources live in #1312 (c832e7495); the re-ask option is tranche 3 |
| 7 | sudoers allowlist for L1 restarts | NEEDS_LOCAL | operator, when ready (sudo is never granted remotely) |
| 8 | per-URL/day citation index | APPROVED | tranche 3 (db-write grant) |
| 9 | M2 production cutover | APPROVED | dry run 2026-09-27 21:35 ET: `would_apply: true`. Operator runs `TRADEAI_M2_PROD_CUTOVER_CONFIRM=trade_ai $PY scripts/apply_memory_prod_cutover.py --apply` from CURRENT (one transaction, rolled-back smoke, receipt) |
| 10 | Postgres heartbeat upsert | APPROVED | tranche 2: detector + projector upsert into intelligence.heartbeat |
| 11 | effort ≈ 20 agent-days | APPROVED | — |
