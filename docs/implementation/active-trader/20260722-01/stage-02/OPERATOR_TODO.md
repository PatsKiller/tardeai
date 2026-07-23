# Operator TODO — after Stage 2

**Run ID:** 20260722-01 · **Date:** 2026-07-22

## Resolved this stage
- ~~Bitwarden `trade-ai-lab-codex` machine account~~ DONE by operator; isolation gate
  ALL PASS; Stage 1 deviation closed. Lab token in use for all lab secret reads.

## New items from Stage 2 findings (none blocking Stage 3)
1. **Alpaca paper label mismatch** (config `tradeai_automated` vs env/slot `alpaca_paper`):
   choose the canonical label and align `DEFAULT_PAPER_ACCOUNT` — recommendation in
   BROKER_CONFIGURATION_DISCREPANCIES.md. Until then discovery will keep reporting the
   two-sided discrepancy.
2. **Schwab `get_market_hours` read errors** (RuntimeError in the shared read lane):
   worth a look in the production repo at leisure; Stage 2 left SYMBOL_TRADABILITY
   UNKNOWN for Schwab rather than guessing.
3. **Alpaca taxable live READ credentials are active** (***4834) — confirm this is
   intended standing state; execution remains not built (UNSUPPORTED by policy).

## Carried forward
4. Litmus BF-1 (Moomoo disconnect-surviving broker-resident protection) — evidence still
   required before Stage 14; Stage 5 design should begin with it. Moomoo re-confirmed
   NOT_INSTALLED this stage.
5. Stage 0 hygiene items (pilot_caps 9999-vs-5, GATES_REMOVED posture, OPERATIONS.md
   service-scope mismatch, snaptrade_accounts.json absence, pgvector absence,
   future-dated migration filenames) — unchanged, none blocking.
6. Wedged production checkout — QUARANTINED by ruling; untouched again this stage.

## For the Stage 3 authorization prompt
Stage 3 = normalized rejection classifier + notifications + fallback policy, mocks and
captured/synthetic responses ONLY (no broker calls needed at all). The lab DB now holds
real capability rows to build against. No operator prerequisite outstanding.
