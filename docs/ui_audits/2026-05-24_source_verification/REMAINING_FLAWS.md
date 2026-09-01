# Remaining Flaws — Post-Verification Assessment (2026-05-24)

Status:      HISTORICAL
as_of:       2026-05-24T10:35:08-04:00
Measured at: efcc51365 / not measured

## 1. Route Duplication — RESOLVED (legacy redirects)

All duplicates are **intentional legacy redirects** in App.tsx:
- `/v2/approvals` → GovernanceHub (legacy alias, GovernanceHub has `?tab=approvals`)
- `/v2/paper-governance` → GovernanceHub (legacy alias)
- `/v2/paper-journal` → JournalHub (legacy alias)
- `/v2/paper-outcomes` → PaperReview (legacy alias)
- `/v2/pipeline?tab=stage-controller` → PipelineHub (tab param NOT read by component)

**Action taken:** Documented as intentional. No code change — removing legacy routes would break bookmarks/links.
**Exception:** PipelineHub ignores `?tab=` param. Removed from crawler routes.json since it produces duplicate screenshot.

## 2. Weekly Learning — CONFIRMED EMPTY

- Component exists: `apps/command-center-v2/src/pages/WeeklyLearning.tsx`
- API endpoint exists: `/api/v2/weekly-learning-digest`
- Table: `weekly_learning_digests` — empty (no rows)
- Script: `scripts/weekly_learning_export.py` exists but not in crontab
- **Status:** Working code, no data. Not a bug — weekly export hasn't been run yet.
- **Action:** Added to freshness registry at P2. Page shows "No digest generated yet" which is correct empty state.

## 3. Incubator Promotion Diagnostics — DEFERRED

- Promotion logic in `scripts/incubator_proposal_promoter.py` has clear gate checks
- Zero promoted is real: global ceiling (20 pending max), RSI gates, expiry gates
- Per-blocker counts require frontend component work to surface
- **Status:** Correctly deferred — needs UI enhancement, not a backend bug.

## 4. Paper Proposal Stale Quote — EXISTING MECHANISM

- `_paper_proposals_enriched()` already detects stale quotes (STALE_QUOTE verdict)
- Auto-enrichment runner (`scripts/auto_enrichment_runner.py`) refreshes stale proposals
- Stale proposals show orange STALE_QUOTE badge in UI
- **Status:** Working. Stale detection exists. Alert integration deferred.

## 5. ENTRY_MISSED — EXISTING DATA

- Created by `scripts/proposal_lifecycle.py` when `abs(drift_pct) > threshold * 1.5`
- Drift thresholds: intraday 2%, short_swing 5%, medium_swing 8%, position 12%
- Available data per missed entry: entry_price, current_price, drift_pct, strategy
- **Status:** Root cause is always price drift. No additional gate-level data needed.

## 6. Reports Finviz Images — NOT IN REACT CODE

- Searched all .tsx files: No `<img>` tags loading from finviz.com or charts2.finviz.com
- Only reference is `<a>` links to finviz.com quote pages (Technical.tsx:107)
- The 7 network failures in manifest are from the HTML reports endpoint which generates
  inline HTML with chart image URLs — not from React components
- **Status:** Issue is in backend-generated HTML, not React. Backend fix deferred.

## 7. Rebalance Stale-Input Blocking — PARTIALLY ADDRESSED

- Rebalance endpoint already returns `is_stale: true` and `stale_days: N`
- Frontend shows stale badge and "Click Refresh to regenerate" note
- Recommendations still render when stale (not blocked)
- **Status:** Stale is visible but not blocking. Full blocking requires frontend gating.

## 8. Tax-Loss Harvesting → AI Analyst — DEFERRED

- Tax endpoint returns lot-level data but no taxable-only TLH summary
- AI Analyst reads `ai_analysis_cache.json` which is pre-generated
- Adding TLH context requires modifying the AI generation pipeline
- **Status:** Enhancement, not a reliability bug. Deferred to pipeline improvement session.

## 9. Freshness Registry Threshold Adjustments

| Product | Current | Issue | Recommendation |
|---------|---------|-------|---------------|
| topic_monitor | manual, 336h | Too loose for proactive system | Lower to 168h, add to weekly cron |
| watchlist_agent_jobs | 2h | Weekend false-fails | Add weekend awareness (48h on weekends) |
| weekly_learning | P2, 168h | Page visible in nav | Keep P2 but add empty-state explanation |

## 10. Alerts Coverage

Verified synthetic alerts now cover:
- Stale portfolio snapshot (>24h)
- Stale risk snapshot (>24h)
- Agent queue backlog (>50 queued)

NOT yet covered (would need additional synthetic alert generators):
- Stale AI cache
- Missing scheduler runs
- Zero-output jobs
- Stale topic monitor

**Status:** Core stale-data alerts are live. Extended coverage is incremental work.
