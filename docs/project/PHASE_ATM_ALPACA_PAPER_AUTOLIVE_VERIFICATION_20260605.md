# ATM — alpaca_paper AUTO_LIVE Policy-Mode Verification (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T15:39:25-04:00
Measured at: efcc51365 / not measured

**Operator request:** "set alpaca paper to AUTO_LIVE and verify" (explicitly approved; paper account
routes only to Alpaca paper mode, so AUTO_LIVE carries no real-money risk; live accounts stay blocked).

**Statement:** AUTO_LIVE is set only on `alpaca_paper`; account environment remains `paper`; no live
broker endpoint was enabled; no broker orders were submitted.

## Preflight
ALPACA_MODE=paper · LLM_DISABLE_LIVE_EXECUTION=true · LIVE_TRADING absent · holdings $1,199,712 (>$1M).

## Baseline (alpaca_paper)
broker=alpaca · env=paper · api_write=true · automation_mode=**AUTO_PAPER** · approval=MANUAL_APPROVAL_REQUIRED
· max_new=25 · source=database · audit rows=4.

## Negative control
schwab_rollover_ira AUTO_LIVE → **403** (interlock live_trading_gate). Schwab/Fidelity remain
api_read=false, api_write=false, connection_status=no_trading_api.

## Write (guarded preview → confirm)
POST /api/v2/admin/broker-account/policy {account:alpaca_paper, automation_mode:AUTO_LIVE,
reason:"operator-approved paper-account AUTO_LIVE mode verification"} → preview 200 needs_confirm →
confirm 200 ok. Only alpaca_paper touched; approval/risk preserved; no order submitted.

## Verification
- **API:** automation_mode=AUTO_LIVE · broker=alpaca · environment=**paper** · api_write=true · only
  alpaca_paper is API-capable.
- **DB:** environment=paper · automation_mode=AUTO_LIVE · approval=MANUAL_APPROVAL_REQUIRED · max_new=25.
- **Audit:** old_mode=AUTO_PAPER → new_mode=AUTO_LIVE · changed_by=operator-approved · reason as above ·
  audit rows 4 → 5.
- **UI** (`/tmp/alpaca_paper_autolive_policy.png`): mode AUTO_LIVE · "alpaca · paper" · LIVE TRADING
  PROHIBITED banner present · "Accounts with trading APIs (1)" (Schwab/Fidelity not API-capable).

## Final safety guardrails
ALPACA_MODE=**paper** · paper_validation_policy.live_trading_allowed=**False** (real live execution
still interlocked) · Schwab/Fidelity all no_trading_api / MANUAL_REVIEW/DISABLED · no orders submitted ·
no GO/WAIT mutation · no strategy mutation · Phase 205 untouched.

**Key acceptance:** alpaca_paper shows AUTO_LIVE, but environment=paper, ALPACA_MODE=paper, and all real
live accounts remain blocked/no-trading-api. Real-money live trading remains impossible (paper endpoint
+ live_trading_allowed=False).
