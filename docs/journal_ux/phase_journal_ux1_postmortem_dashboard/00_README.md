# JOURNAL-UX-1 — Closed Trade Postmortem Dashboard

**Status:** COMPLETE

## What Was Delivered

1. **Postmortem model** (`scripts/closed_trade_postmortem_model.py`):
   - `classify_exit_quality()` — GOOD_EXIT / ACCEPTABLE_EXIT / BAD_EXIT / EARLY_EXIT / NEEDS_REVIEW
   - `classify_entry_quality()` — GOOD_ENTRY / ACCEPTABLE_ENTRY / WEAK_ENTRY / CHASED_ENTRY
   - `generate_lesson()` — one-line lesson + category + operator action per trade
   - `build_postmortem()` — full dashboard-ready postmortem dict
   - EXIT_TYPE_MAP for normalizing exit reasons

2. **Frontend dashboard** (`apps/command-center-v2/src/pages/AutomatedTradeJournal.tsx`):
   - "Closed Trade Review" section above Strategy Breakdown
   - Columns: Symbol, Strategy, PnL, R, Why Closed, Exit Quality, Lesson
   - Color-coded exit quality badges
   - human_review_only flag on all postmortems

3. **Key design decisions**:
   - `stop_hit_instant` checked before `stop_hit` (substring ordering)
   - All outputs are human_review_only — no automated strategy changes
   - Pure functions, no DB writes, no trades, no strategy activation

## Safety

- No `create_order`, `submit_order`, or `activate_strategy` in postmortem model
- `human_review_only: True` on every postmortem
- Pure classification functions — zero side effects

## Tests

11/11 pass:
- TestPostmortemModel: 7 tests (compile, target_hit, stop_hit_instant, manual_stale, time_stop, all_fields, human_review)
- TestFrontend: 2 tests (dashboard section exists, build exists)
- TestSafety: 2 tests (no trades, no strategy activation)
