# Trade AI v12 — Focused Improvement Plan: Automated Trading Engine
**Architect Review (Corrected)** | **2026-05-12** | **Supersedes:** TRADE_AI_ARCHITECT_ASSESSMENT_AND_TRADING_ENGINE_REDESIGN.md

---

## Corrected System Score: ~6.5 / 10

The previous assessment underscored the system by fabricating gaps that don't exist. After reading the actual documentation, the execution pipeline is substantially more mature than initially described. This plan documents only **verified true gaps** and does not propose rewriting things that already work.

---

## What the Previous Assessment Got Wrong (Retraction)

| Claim | Actual State |
|-------|-------------|
| "No stop-breach check in sweep" | FALSE — `alpaca_paper_adapter.py` has hard-block: `price <= stop_price` |
| "No price drift block" | FALSE — revalidator blocks at >= 3% drift, adapter hard-blocks at > 5% |
| "RECALIBRATE path doesn't exist" | FALSE — `paper_execution_revalidator.py` recalculates shares at > 2% drift; NEEDS_REVALIDATION state exists |
| "No strategy-aware staleness thresholds" | FALSE — thresholds documented in MASTER_SYSTEM_DOCUMENTATION section 10 (scalp 30m -> position 10d) |
| "Alpaca hardcoded everywhere, no abstraction" | PARTIALLY TRUE — `alpaca_paper_adapter.py` is already modular; registry doesn't exist but isn't urgently needed |
| "No execution audit trail" | FALSE — `risk_params_at_fill` JSONB column exists in `paper_trades`; full event log in `proposal_event_log` |
| "Broker adapter framework from scratch" | PARTIALLY TRUE — direction is right but starting point is better; refactor not rewrite |

---

## Verified True Gaps

These are confirmed by MASTER_SYSTEM_DOCUMENTATION, SYSTEM_FACTS_LATEST, and cross-referenced session notes. Each is a real gap, not a guess.

---

### Gap 1 — Agent Calibration Not Feeding Proposal Scoring

**Source:** MASTER_SYSTEM_DOCUMENTATION S11 + S10

**What exists:** `feedback_loop_processor.py` updates `agent_calibration` table daily. Agent accuracy (win rate) is tracked per agent.

**What's missing:** `proposal_intelligence_analyzer.py` and `proposal_agent_review.py` vote agents equally regardless of their calibrated accuracy. An agent with a 40% track record has identical vote weight to one with a 72% track record.

**Fix location:** `scripts/proposal_intelligence_analyzer.py`

**Caveat:** With limited closed trades per agent, calibration is statistically thin. Implement the code but don't expect it to change behavior until 20+ closed trades accumulate. This is wiring, not a live fix.

---

### Gap 2 — Strategy Performance Not Gating New Proposals

**Source:** MASTER_SYSTEM_DOCUMENTATION S8, S10

**What exists:** `strategy_registry` table, strategy performance snapshots, weekly aggregation.

**What's missing:** `auto_proposal_generator.py` and `incubator_proposal_promoter.py` do not suppress proposal generation for strategies that are consistently losing.

**Fix location:** `scripts/auto_proposal_generator.py` + `scripts/incubator_proposal_promoter.py`

**Same caveat as Gap 1:** This doesn't change anything until sample size grows. Implement as infrastructure now.

---

### Gap 3 — Outcome Provenance Not Written Back to Originating Proposal

**Source:** MASTER_SYSTEM_DOCUMENTATION S10, confirmed `paper_trade_proposals` schema

**What exists:** `paper_trades` has full outcome data. `agent_curation_hooks.on_paper_trade_closed()` fires on close and writes to multiple tables.

**What's missing:** No columns in `paper_trade_proposals` linking back to the trade outcome. The proposal that generated a trade has no record of how that trade turned out. This breaks the proposal-level learning loop and makes it impossible to run proposal-quality analytics ("proposals with intel_score > 80 — what's the win rate?").

**Fix:** Migration to add outcome columns to `paper_trade_proposals`, then write-back in `agent_curation_hooks.on_paper_trade_closed()`.

---

### Gap 4 — Granular R-Multiple Trailing Stop Tiers

**STATUS: ALREADY RESOLVED**

**Verification (2026-05-12):** `paper_trade_monitor.py` lines 211-228 already implements the full 4-tier R-multiple trailing stop:
- R >= 1.0: breakeven
- R >= 1.5: lock 0.5R
- R >= 2.0: lock 1.0R
- R >= 3.0: lock 2.0R

This runs every 5 minutes during market hours via cron. A simpler 50%-lock version also exists in `open_trade_monitor.py` (every 15 min) as a backup, but the 5-min granular version dominates.

**No action needed.** The previous assessment and this plan's original text incorrectly claimed this was missing.

---

### Gap 5 — Documentation Drift

**Source:** `SYSTEM_FACTS_LATEST.md` — confirmed stale metric claims across 7 docs

**Confirmed mismatches (real numbers vs. claimed):**

| Document | Metric | Claimed | Actual |
|----------|--------|---------|--------|
| CHEAT_SHEET.md | table_count | 299 | 320+ |
| CHEAT_SHEET.md | python_script_count | 3 | 358+ |
| ARCHITECTURE_OVERVIEW.md | frontend_page_count | 55 | 61 |
| MASTER_SYSTEM_DOCUMENTATION.md | python_script_count | 90 | 358+ |

**Fix:** A1A protocol (docs/A1A.md) now requires full doc audit on every change. Dedicated number-update script recommended.

---

### Gap 6 — Telegram Re-Approval UX for NEEDS_REVALIDATION

**Source:** MASTER_SYSTEM_DOCUMENTATION S10 — NEEDS_REVALIDATION state exists; no Telegram UX confirmed

**What exists:** When `paper_execution_revalidator.py` returns NEEDS_REVALIDATION (price drifted > 3%), the proposal is blocked and the state is written to the DB.

**What's missing:** A Telegram notification when NEEDS_REVALIDATION fires, with inline re-approval keyboard. This directly addresses the stale-entry experience — operator would be alerted instead of discovering it post-fill.

**Fix location:** `scripts/proposal_paper_submitter.py` — after revalidator returns NEEDS_REVALIDATION, send Telegram alert with recalibrated plan and inline [Approve] / [Skip] buttons.

**Prerequisite:** Check if `telegram_command_handler.py` already handles inline callbacks.

---

### Gap 7 — Heuristics Audit Trail Missing from paper_trades

**Source:** `paper_trades` schema

**What exists:** `risk_params_at_fill` JSONB column captures prices at fill time. `execution_eligibility_status` and `execution_eligibility_reason` captured in proposals table.

**What's missing:** `paper_trades` doesn't capture what the revalidator decided at submission time. The journal's "Execution" section can't show revalidation score/flags without cross-table joins.

**Fix:** Migration to add `revalidation_verdict`, `revalidation_score`, `revalidation_flags`, `price_at_approval`, `staleness_at_submit_min` to `paper_trades`. Write during INSERT in `alpaca_paper_adapter.py`.

---

## What NOT to Build (Explicitly)

| Item | Why |
|------|-----|
| Full broker abstraction layer | `alpaca_paper_adapter.py` is already modular. No second broker planned. Refactor when needed. |
| Rewriting `paper_execution_revalidator.py` | Already does drift blocking, staleness, recalculation. Extend, don't replace. |
| New `entry_heuristics_evaluator.py` | The revalidator IS the heuristics engine. Add Telegram UX (Gap 6) and audit trail (Gap 7). |
| RSI/EMA/VWAP blocking at submission | Already enforced at proposal generation. Redundant at submission. |
| Granular R-multiple trailing (Gap 4) | Already implemented in paper_trade_monitor.py. |

---

## Implementation Sequence

### Done (Implemented 2026-05-12, commit 6ad5fc7)

| Gap | File | Status |
|-----|------|--------|
| Gap 3: Outcome provenance write-back | `agent_curation_hooks.py` + migration `20260512_gap3_proposal_outcome_provenance.sql` | **DONE** — 8 outcome columns on proposals, write-back in on_paper_trade_closed() |
| Gap 6: Telegram NEEDS_REVALIDATION alert | `proposal_paper_submitter.py` | **DONE** — Telegram alert with drift/price/re-approval commands on NEEDS_REVALIDATION and blocked_safety |
| Gap 7: Revalidation snapshot columns | `alpaca_paper_adapter.py` + migration `20260512_gap7_revalidation_snapshot.sql` | **DONE** — 5 columns on paper_trades, full recheck result persisted |

### Do Next Session

| Gap | File | Impact |
|-----|------|--------|
| Gap 5: Doc drift fix | All docs + update script | Operational hygiene |

### Wire Up Later (Needs sample data)

| Gap | File | Trigger |
|-----|------|---------|
| Gap 1: Calibration-weighted voting | `proposal_intelligence_analyzer.py` | After 20+ closed trades |
| Gap 2: Strategy performance gating | `auto_proposal_generator.py` | After 10+ closed trades per strategy |

---

## The Real Constraint: Sample Size

Every learning mechanism in the system is correctly wired. The limiting factor is not code — it's sample size. The primary operational goal for the next 30-60 days is generating and closing more paper trades, not adding more code.

---

## Corrected Maturity Path

| State | Score | Key Unlock |
|-------|-------|------------|
| ~~Pre-gaps~~ | ~~6.5 / 10~~ | ~~Execution pipeline mostly solid~~ |
| **Current (Gaps 3, 6, 7 done)** | **7.0 / 10** | Silent stale-entry problem solved, outcome provenance active |
| + 30 closed trades | **7.8 / 10** | Learning loops activate meaningfully |
| + Gaps 1 & 2 (after data) | **8.2 / 10** | Agent calibration feeds proposals |
| + 6-month paper validation | **8.8 / 10** | Live trading gate opens |

---

*This document supersedes the original architect assessment. That document contained factual errors about existing systems. Archived at: `docs/_archive/ARCHITECT_ASSESSMENT_V1_SUPERSEDED.md`*
