# ATM Automation Modal — End-to-End Write Test (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T14:56:46-04:00
Measured at: efcc51365 / not measured

**Commit tested:** 491be32 (ATM broker/account correction + Automation Policy modal).
**Statement:** No broker orders submitted; no live writes; no strategy/GO-WAIT mutation.

## Preflight
- ALPACA_MODE=paper · LLM_DISABLE_LIVE_EXECUTION=true · LIVE_TRADING absent · holdings $1,199,712 (>$1M).
- Account under test: alpaca_paper only.

## Baseline policy (alpaca_paper)
automation_mode=AUTO_PAPER · approval=MANUAL_APPROVAL_REQUIRED · risk_per_trade_pct=5.0 ·
max_new_positions_per_day=**25** · max_concurrent=10 · daily_loss_pause_pct=2.5 · source=legacy_import.
audit rows before = 2.

## Negative safety tests
- **A. AUTO_LIVE on alpaca_paper** → **403** (gate-interlock). *(Gap found+fixed: previously returned a
  200 preview because the interlock only blocked live accounts; AUTO_LIVE on a paper account passed
  assert_writable. Now AUTO_LIVE is gate-based-refused on any account without a live+write-capable API.)*
- **B. Schwab AUTO_PAPER** → **403** (live-trading gate not passed).
- **C. no-token write** → **403** (admin guard).

## Modal write (browser → confirm → API → DB → audit)
- Field changed: `max_new_positions_per_day` 25 → **24** via Edit Automation modal → Review change →
  AdminConfirmModal → Confirm → POST /api/v2/admin/broker-account/policy.
- DB after: max_new_positions_per_day=**24**, source=**database**, updated_at advanced.
- Audit: new row inserted (changed_by=e2e-modal-test, new_policy includes max_new_positions_per_day:24).
- Audit rows 2 → 3.

## Rollback (same guarded path)
- Set back to **25** → DB restored to 25, audit rows 3 → 4 (second audit row). Final policy == baseline.

## AUTO_LIVE behavior (operator directive: paper must not be greyed/403)
Gated by ACCOUNT ENVIRONMENT, not the mode label:
- **PAPER/sandbox account (alpaca_paper):** AUTO_LIVE is **selectable AND allowed** (no grey, no 403).
  Verified: POST returns 200/needs_confirm. Safe — alpaca_paper routes to the Alpaca PAPER endpoint
  (ALPACA_MODE=paper), so no real-money order is possible regardless of the label.
- **LIVE account (schwab):** AUTO_LIVE remains **403 gate-interlocked** (verified) until the
  live-trading gate passes. Real-money execution stays independently governed by
  `live_trading_interlock` at order time (untouched). No live arming performed.

## Guardrail state (after rollback)
- broker_accounts: only alpaca_paper api_write_enabled=true (paper); schwab/fidelity api_read/write=false,
  connection_status=no_trading_api. AUTO_LIVE not applicable to any account now.
- No live trading state changed · no strategy changed · no GO/WAIT changed · no orders submitted ·
  Phase 205 untouched.

## Evidence
Screenshots: /tmp/atm_e2e_confirm.png, /tmp/atm_e2e_after.png, /tmp/atm_autolive_selectable.png.
