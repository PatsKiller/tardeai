# Closed-Loop Step 1 — Execution Lineage (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T22:02:42-04:00
Measured at: efcc51365 / not measured

## Objective
Stamp `signal_id` / `source_signal_id` / `strategy_card_id` (+ candidate, account, broker, environment)
onto executed trade records at submit, and backfill exact proposal links. Additive lineage only — no
change to trading decisions, scoring, proposal generation, routing, or execution.

## Broken join fixed
`paper_trades.signal_id / source_signal_id = 0%` (signal identity lost at execution).

## Architecture — broker/account neutral
Lineage is **execution lineage**, not "Alpaca paper lineage." Account → broker/environment is resolved
from the broker/account model (`broker_accounts`, fallback `accounts`, then conservative inference) — no
literals. First consumer is `paper_trades`; the shape is generic for future Schwab/Fidelity execution.
A generic cross-broker execution table is **Phase 2** (not built here).

## Schema (additive, reversible — ADD COLUMN IF NOT EXISTS on paper_trades)
strategy_card_id, candidate_id, source_proposal_id, execution_account, execution_broker,
execution_environment, lineage_source, lineage_stamped_at, lineage_confidence, lineage_notes (JSONB).
(signal_id, source_signal_id, source_strategy_card_id, proposal_id already existed.)

## Helper (owner: scripts/trade_lineage.py)
`extract_lineage_from_proposal(conn, proposal_id)` → broker/account-neutral lineage dict.
confidence='exact' when sourced from the proposal row; 'missing' when no proposal. New-submit lineage is
exact from proposal metadata (no silent symbol/date inference).

## Submit path changes
- `paper_trade_logger.approve_proposal()` (MAIN path — manual approval + ATM auto-approval) now extracts
  lineage and stamps all columns on INSERT, including `lineage_stamped_at=NOW()`.
- Other creation paths (trade-plan insert, alpaca_paper_adapter sync/submit) unchanged in this step and
  default to lineage NULL / broker_sync; documented for follow-up. No order was submitted during work.

## Backfill (exact proposal_id only; backup data/runtime/paper_trades_backup_prelineage.json)
- `scripts/backfill_trade_lineage.py` — fills missing lineage from the exactly-linked proposal; sets
  proposal.paper_trade_id only on 1:1 matches; no symbol/date fuzzy mutation.
- 43 paper_trades backfilled · skipped_no_proposal 0 · reverse_links_set 0 · reverse_ambiguous 0.

## Coverage before → after
| field | before | after |
|-------|--------|-------|
| proposal_id | 84% | 84% |
| signal_id | 0% | **27%** |
| source_signal_id | 0% | **27%** |
| strategy_card_id | 0% | 0% (no upstream data — flagged, not fabricated) |
| candidate_id | 0% | **84%** |
| execution_account / broker / environment | 0% | **84%** |
| lineage_stamped_at | 0% | 84% |

signal coverage is capped at the upstream proposal capture rate (source_signal_id present on 44% of
proposals); improving upstream signal capture is a separate fix. strategy_card_id is 0% because proposals
do not carry source_strategy_card_id — left blank (never inferred).

## Validation (10/10 PASS — scripts/validate_trade_lineage_step1.py)
schema cols exist; helper returns exact lineage; broker/account neutral (schwab→schwab); no hardcoded
alpaca_paper; exact-proposal trades stamped (43/43); source_signal_id >0%; no conflicting reverse links;
auto-approver still gates on automation_mode; no broker order calls; paper mode / live disabled.

## Safety
ALPACA_MODE=paper · LLM_DISABLE_LIVE_EXECUTION=true. No order submission, no broker writes, no GO/WAIT,
no strategy/threshold mutation, no Phase 205 changes. Additive schema + exact-match backfill only.

## Next step
**Step 2:** stamp Hermes `related_trade_id` / `related_proposal_id` on trade-reflection writes
(hermes_research_intelligence currently 0% trade-linked).
