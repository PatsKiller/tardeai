# First Real Option Position — Acceptance Runbook (v1.1 Phase 10)

**No fixtures.** The first GENUINE Alpaca paper option position runs the whole
chain; the first real Schwab option gets READ-ONLY intake + monitoring
verification before any lifecycle action.

## Alpaca paper path (the intended first run)

1. **Origin** — approve an options proposal in the desk queue (or operator
   manual), mark it ready: `alpaca_paper_options_executor.py --mark-ready <id>`.
   Gates that must be true: `alpaca_paper_enabled` (operator flips it),
   1-contract cap, LIMIT-only, BTO-only. Market hours required for a fill.
2. **Submit** — `--submit --proposal-id <id> --confirm` (the paper-locked lane;
   the lifecycle desk itself never submits).
3. **Fill** — hourly reconcile (`reconcile_alpaca_paper_options.sh`) records the
   fill; the NEXT lifecycle cron (*/20) intake picks the position up as NEW →
   OPEN journal event → trade_instances row appears
   (`trade_uid options_strategy_positions:<spid>`).
4. **Verify, in order** (each is an acceptance checkpoint):
   - [ ] intake classified the strategy correctly (not unknown_multi_leg)
   - [ ] basis resolved from broker fill (basis_source='broker_fill'), NOT operator
   - [ ] snapshot has exact-match quotes (economics.flags empty)
   - [ ] policy decision + single primary recommendation renders on the card
   - [ ] alert (if amber/red) carries the full identity header + delivery evidence
   - [ ] build a close ticket → TIF change rebuilds → approve → Telegram 2FA
         pill names the exact order → arm (NO submission)
   - [ ] execute the close manually in Alpaca paper → reconcile evidence →
         `ticket-evidence` records it → position closes, outcome row written
   - [ ] `v_options_journal` row complete; trade_instances status=closed with pnl
   - [ ] `ticker-attribution` for the underlying reconciles (invariant_ok=true)
   - [ ] portfolio attribution sum includes the ticker
5. **Record** the results in docs/_findings/ as the first OPERATIONAL
   VERIFICATION (full) evidence. OUTCOME VALIDATED stays NO until the
   pre-registered minimum sample (policy tuning.min_closed_positions_per_strategy=20).

## First real Schwab option (later)

READ-ONLY first: let intake register it, watch 2+ days of snapshots/decisions
for correctness, verify basis came from broker data, THEN allow tickets
(which remain manual-execution anyway — the pilot lane stays disarmed).
