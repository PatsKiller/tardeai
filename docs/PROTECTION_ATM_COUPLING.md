# Protection Adjustments → ATM Coupling (handoff)

**Status:** gaps 1–7 closed (API union, identifier migration module+SQL, Proposals UI, retention,
display rename). First live auto-apply **gated** (`PROTECTION_ATM_AUTO_APPLY_PAPER=0`) until operator
watches one market cycle. **Date:** 2026-06-26 (updated 2026-06-27).

## Problem (operator report)

Grok/Hermes stop-curation recommendations for open positions (e.g. AGNC/NUVL/TMHC) were written to a
**separate** advisory table and were **not** presented in the main proposals system, and were **not**
governed by the ATM. Operator wanted: protection adjustments submitted to ATM **and** the regular
proposals view at the same time; nothing hits paper without a proposal record; **automated account
auto-applies** guarded stop-ups, **real accounts operator-approved**; and "paper" renamed to "automated".

## What was built

| Piece | File | Notes |
|---|---|---|
| `proposal_kind` discriminator (`entry`/`protection`) + `protection_source_id` | `migrations/2026_06_26_proposal_kind.sql` | Backfilled all existing rows to `entry`. Physical mirror **not** used — API union instead. |
| **ATM entry-path guard** | `scripts/atm_auto_approver.py` | `AND COALESCE(proposal_kind,'entry')='entry'`. Protection rows never reach bracket-submit. |
| **ATM protection pass** | `scripts/protection_atm_pass.py` | Automated account auto-applies guarded stop-UPs; real → operator; others advisory. Uses `automated_account.is_automated_account()`. |
| Wired into ATM cycle | `atm_auto_approver.py` (end of `run_cycle`) | Protection pass runs even when entry queue is empty (`70382f04`). Cron `*/15 9-16 * * 1-5` is ATM-only — protection pass is **inside** `atm_auto_approver`, not a separate cron. |
| **API union** | `scripts/api_v2.py` → `GET /api/v2/broker-proposals?kind=all\|protection` | `_fetch_protection_union_rows()` merges protection rows (`queue_kind: protection`, negative ids). Dedicated endpoint `GET /api/v2/protection-proposals` unchanged. |
| **Proposals tab UI** | `BrokerProposals.tsx` + `ProtectionProposalCard.tsx` | Type filter includes Protection; cards show ATM disposition, no broker/cloud actions. |
| **Identifier migration** | `scripts/automated_account.py` + `migrations/2026_06_27_tradeai_automated_account.sql` | Canonical key `tradeai_automated`; legacy `alpaca_paper` accepted via `is_automated_account()` until DB migration runs. |
| Display rename | `TradingHub.tsx`, `ProtectionPanel.tsx`, `broker_config.py` | UI labels say automated; routing uses canonical key. |
| Retention | `scripts/prune_protection_proposals_retention.py` | Wired into `run_protection_pipeline.sh` (default 30d SUPERSEDED). |

### Auto-apply safety model
`protection_atm_pass` only ever calls the **pre-existing** `apply_paper_protection_adjustment.apply()`,
which is hard-guarded: asserts `ALPACA_MODE=paper`, paper endpoint only, **stop-UP only** (risk can
only decrease), via Alpaca order **REPLACE** so the stop is never absent. Allowlisted actions:
`MOVE_STOP_TO_PROFIT_LOCK`, `MOVE_STOP_TO_BREAKEVEN`. Everything else is advisory/operator.

Config flag: `PROTECTION_ATM_AUTO_APPLY_PAPER` (default `1` in code; **set `0` in `.env`** until first
cycle observed). Operator currently has `PROTECTION_ATM_AUTO_APPLY_PAPER=0`.

## Decisions (closed)

1. **API union, not physical mirror** — keeps protection out of `broker_promote_oversight` LLM fleet
   and avoids fake entry sentinels. `proposal_kind` columns remain if physical mirror is ever needed.
2. **Full identifier migration** — `tradeai_automated` is canonical; `automated_account.py` bridges
   legacy keys at runtime; SQL migration updates `accounts`, `broker_accounts`, `paper_trades`,
   `paper_trade_proposals`. Adapter filename `alpaca_paper_adapter.py` unchanged.
3. **First live auto-apply** — intentionally gated; dry-run validated classification.

## Open items

- [ ] Observe/validate the first real automated-account auto-apply; confirm Alpaca REPLACE result.
      Set `PROTECTION_ATM_AUTO_APPLY_PAPER=1` after one watched ATM cycle during market hours.

## Commits
`a3436b46` (ATM protection coupling) · `d2f8551c` (display rename) · `70382f04` (protection pass on
idle entry cycles) · *(pending)* union + migration + UI + retention.