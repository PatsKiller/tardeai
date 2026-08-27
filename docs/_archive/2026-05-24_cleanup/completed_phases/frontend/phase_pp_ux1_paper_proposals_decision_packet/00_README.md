# PP-UX-1 — Paper Proposals Decision Packet Redesign

**Status:** COMPLETE

## Purpose

Upgrades Paper Proposals from thin trade cards to full operator decision packets
so each proposal explains itself before the operator can act.

## Changes

### API (scripts/api_v2.py)
- Added strategy YAML metadata: description, entry criteria, risk rules, disqualifiers
- Added entry/stop/target rationale computed from strategy config + scan data
- Added staleness policy per timeframe class
- Added structured approval blockers array
- Added incubator diagnostics to summary

### Frontend (apps/command-center-v2/src/pages/PaperProposals.tsx)
- **Header**: sector/industry, strategy timeframe, staleness badge
- **Decision Banner**: structured blocker list with actions
- **Why This Setup?**: strategy description, catalyst summary
- **Trade Plan Rationale**: entry/stop/target with reasoning
- **Evidence Tiles**: preserved and enhanced
- **Missing Data**: visible in main card, not just details drawer
- **Guided Workflow**: numbered steps (1. Refresh, 2. Check, 3. AI, 4. Approve)
- **Approval Gating**: disabled when execution/RSI blockers exist
- **Details Drawer**: strategy entry criteria, disqualifiers, risk rules, sector metrics, news
- **Run Health Panel**: incubator diagnostics, underfilled explanation, promotion blockers

## Safety

- Read-only enrichment only
- No execution logic changes
- No approval bypass
- Approve button disabled when gates incomplete
- Missing data shown as "Missing", not hidden

## Files

- `pp_ux1_preflight.md` — preflight output
- `pp_ux1_design_gap_audit.md` — gap analysis
- `pp_ux1_api_contract.md` — API field contract
- `pp_ux1_safety_audit.md` — safety verification
- `pp_ux1_test_results.md` — test output
