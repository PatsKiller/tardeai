# Phase 112 — Self-Learning Dashboard Actionability Fix

Status:      HISTORICAL
as_of:       2026-06-01T15:50:38-04:00
Measured at: efcc51365 / not measured

## Defects Fixed

### 1. Drilldown Filter Correctness (112A-B)
**Before**: `?type=ops_backlog` returned 42 mixed items (RESEARCH, STRATEGY, symbols, etc.)
**Root cause**: Drilldown function read `QUERY_STRING` env var which was never set by the portfolio server. Query params were silently ignored — every request returned ALL items.
**Fix**: Changed drilldown to read from `_current_query` dict set by the handle() dispatcher. Added `category=` filter for post-query display_category filtering with subcategory prefix matching.
**After**: `?type=ops_backlog` returns 3 items (OPS_LLM, OPS_AGENT, OPS_FEED). `?category=OPS` returns 4 items (matching OPS_*). `?category=STRATEGY` returns 5 items.

### 2. Workflow Context Fields (112C)
Every drilldown item now includes:
- `display_category` — typed: OPS_FEED, OPS_AGENT, OPS_LLM, OPS_PIPELINE, STRATEGY, RESEARCH, SOURCE_DISCOVERY, PORTFOLIO, {SYMBOL}
- `domain` — human-readable domain name
- `workflow_stage` — where in the pipeline (New, Staged, Ready for Review, Embedded, Promoted)
- `workflow_stage_order` — numeric sort order
- `owner_agent` — who/what agent owns this item
- `operator_priority` — HIGH/MEDIUM/LOW based on category and confidence
- `why_it_matters` — one-line explanation of significance
- `recommended_next_action` — what should happen next
- `blocker_reason` — why it's stuck (if applicable)

### 3. Actionable Card Layout (112D)
Cards now show:
- Top row: category badge (color-coded), status badge, priority badge
- Title: full topic text
- Why it matters: one-line significance
- Next action: blue text with recommended step
- Footer: workflow stage, owner agent, confidence score

### 4. Detail Drawer Workflow Explanation (112E)
Drawer now has structured sections:
1. What is this? (topic + summary)
2. Workflow Position (stage, domain, owner, priority)
3. Why it matters (significance explanation)
4. Next action (green box with recommended step)
5. Blocker (red box if applicable)
6. Status badges
7. Quality scores (confidence, evidence)
8. Metadata (ID, type, agent, timestamps)

## Files Changed
- `scripts/api_v2.py` — drilldown filter fix, workflow context enrichment, _current_query dispatch
- `apps/command-center-v2/src/pages/SelfLearningOverview.tsx` — card layout, drawer, DrillItem interface, category filters

## Build
- Python compile: PASS
- TypeScript: PASS
- Vite build: PASS

## Safety
- Proposal creation: ZERO
- Journal mutation: ZERO
- Holdings mutation: ZERO
- Level 7: PROHIBITED
- No write/action controls on any card or drawer
