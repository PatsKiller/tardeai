# ATM Re-enable Gate Checklist

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

## Safety Gates
- [x] ALPACA_MODE=paper
- [x] LLM_DISABLE_LIVE_EXECUTION=true
- [x] Live trading disabled
- [x] ATM currently frozen/dry_run
- [x] Quote failure fail-closed verified
- [x] Audit logging verified (event_type column fixed)
- [x] No unresolved broker/API errors

## Stop Management Gates
- [x] Broker GTC stops reconciled (5/5)
- [x] planned_stop present for all open trades
- [x] stop_order_id present for all open trades
- [x] Unified supervisor active (*/3 market hours)
- [x] Old racing monitor crons disabled
- [x] STOP-V2.3 trailing tiers dry-run verified
- [x] No unprotected positions
- [x] No critical reconciliation findings

## Strategy / Proposal Gates
- [x] Route audit capability present
- [x] Strategy_id validation active
- [x] Quote freshness check active (enrichment pipeline)
- [x] R:R validation active (≥2.0)
- [x] Classifier health gate active (currently 0.0 temp bypass)
- [x] Enrichment pre-check prevents un-enriched evaluation
- [ ] **Strategy proof sufficient** — NOT MET (3.5/10)

## Operational Gates
- [x] Telegram alerts working (both IDs)
- [x] Dashboard shows ATM state + predicted decisions
- [x] Operator can freeze ATM immediately (dashboard + Telegram)
- [x] Rollback documented (STOP-V2.2 rollback script)
- [x] Enrichment status panel live

## Blockers for Full Active
- [ ] Strategy proof ≥ 6.0 (currently 3.5)
- [ ] min_classifier_health restored to 0.50 (currently 0.0)
- [ ] B-1 observation complete (expires 2026-05-25)
- [ ] 3+ strategies with classifier health baseline
- [ ] Burn-in observation (3-5 days dry-run)
