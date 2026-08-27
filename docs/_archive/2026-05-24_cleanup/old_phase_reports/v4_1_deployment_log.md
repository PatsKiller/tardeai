# LLM Fleet v4.1 — Deployment Log

## ATP-1B — Research Workflow Answers — 2026-05-20

Direct operator answers: current vs target schedule, candidate breakdown (619 no-fit,
327 family gate blocks, 39 ready for review, 186 watchpool). Paper Proposals renamed
to Automated Trade Proposals. Page/menu recommendations documented. ATP-2 gaps
identified for future overnight/premarket research cadence. Tests: 11/11.

---

## AFTERHOURS-READY-1 — After-Hours Candidate Preparation — 2026-05-20

Full after-hours readiness runner evaluates 1,311 symbols against ARCH-4 strategy-fit
data. Root cause: 17:30 RUN_UNDERFILLED was intentional narrow pass. Added readiness
snapshot tables, cron wrapper, API endpoint. 39 ready, 186 watchpool, 619 needs-data.
Tests: 17/17. Runtime verification: PASS (5/5).

---

## JOURNAL-UX-2B — Digest Formatting + Cron — 2026-05-20

Cleaned digest format (no padded actions). Cron installed: 16:30 ET M-F.
TEST digest sent and validated. Rollback script available. Tests: 20/20.

---

## JOURNAL-UX-2 — Persistent Lessons + Digest — 2026-05-20

Lesson memory: 10 lessons persisted, 6 strategy rollups, 1 repeated pattern detected.
Digest builder + sender with P1_DIGEST routing through OPS-HYGIENE. 3 tables created.
API: lesson-memory/summary + strategy-lessons/summary. Tests: 24/24.

---

## VERIFY-1 + SCREENER-ARCH-5 — Implementation Proof + Schedule — 2026-05-19

All 10 implementation claims verified REAL with 3+ evidence types. 27 active screeners,
0 stale, 0 orphaned. Schedule registry + health alert + API endpoint. Tests: 16/16.

---

## SCREENER-ARCH-4 — Full Universe Strategy-Fit Audit — 2026-05-19

30,015 audit rows: 1,305 symbols x 23 strategies. STRONG: 42, MODERATE: 341.
Top matches: earnings_pre_buildup (835), swing_trade (244), recovery_watch (120).
16 zero-match strategies. API: strategy-fit/summary. Tests: 18/18.

---

## OPS-HYGIENE-1 — Operator Alert Surface — 2026-05-19

Central alert router with P0/P1/P2/P3 policy. ~93% Telegram reduction estimate.
telegram_alert.py patched to route through router. Config: operator_alert_policy.yaml.
5 operator reports. Tests: 34/34.

---

## SCREENER-ARCH-3D — Falloff Lifecycle Apply — 2026-05-19

993 safe lifecycle state updates: 885 source_missing, 153 active, 89 needs_refresh.
136 expire candidates blocked (requires --operator-approved-expire). Tests: 21/21.

---

## JOURNAL-UX-1B — Closed Trade Action Dashboard — 2026-05-19

Dashboard-first action view: 6 summary cards, action queue, upgraded verdicts.
10 dashboard verdicts, 9 mistake types, 0 generic lessons. 3 read-only API endpoints.
Tests: 29/29.

---

## Cron Wrapper DB Fix — 2026-05-19

All 8 wrapper scripts + 9 cron entries fixed to load .env for DB credentials.
Verified by actual cron runs (watchpool, telegram, quote refresh).

---

## SCREENER-ARCH-3C — Membership Transition Lifecycle — 2026-05-19

Prior-vs-current comparison: 5,035 events created. 727 dropped, 55 reentered.
Mass-drop protection: 8 runs protected. 3 read-only API endpoints + dashboard card.
Tests: 23/23.

---

## SCREENER-ARCH-3B — Membership Backfill — 2026-05-19

Backfilled 1,941 symbols from 2,951 scan pairs. Membership table populated with all
present status + entered events. Catalog reports: 5,071 classified, 5,242 watchlist.
7/13 done, 6 deferred (dropped/reentered detection, API). Tests: 11/11 + regression.

---

## SCREENER-ARCH-3 — Ticker Catalog Lifecycle — 2026-05-19

Membership tables created (screener_symbol_membership + _history). Falloff policy
added (retain by TTL, no silent deletion). Catalog report: 1,139 incubator, 4,872
classified, 5,043 watchlist. 8/15 done, 5 deferred to ARCH-3B (importer write).
Tests: 12/12 + ARCH-2B regression.

---

## SCREENER-ARCH-2B — Broad Screener Cap Overrides — 2026-05-19

Per-screener 10,000 cap for 4 broad ETF/income screeners. All 4 now fully EXHAUSTED:
bond_etf 5,230, covered_call 5,230, high_yield 6,367, ira_friendly 6,367. Zero data loss.
27/27 screeners now exhaust their full result sets.

---

## SCREENER-ARCH-2 — Full FinViz Ingestion — 2026-05-19

Full ingestion proven: ~41,000 rows, 2,973 new tickers, 23/27 screeners exhausted.
Removed 50-row and 500-row caps. Emergency 5,000 cap for 4 broad ETF/income screeners.
All 27 screeners now freshly run. 7/22 deliverables done, 14 deferred to ARCH-2B/3/4/5.
Catalog, membership lifecycle, strategy-fit, schedule, coverage alerts are deferred.
Tests: 55/55 regression.

---

## SCREENER-ARCH-1 — Full Screener Coverage — 2026-05-19

Critical fix: 50-row hard cap in finviz_screener_runner.py raised to 500. The cap
was Python-side truncation (`tickers[:50]`), not a Finviz API limit. 25/27 screeners
were capped. 8 stale screeners identified. Inventory/freshness report added.

---

## SCALP-COUNT-1 — Fix Live Scalp Current-Run Counts — 2026-05-19

GO/WAIT/NO GO cards now show current-run counts filtered by run_label, not universe.
Header shows "X scanned this run · Y universe". ALL tab renamed to Universe.
Root cause: DB query pulled today+yesterday distinct symbols (~1418) but run scanned 64.

---

## WATCH-2 — Watchpool Maturity Alerts — 2026-05-19

Watchpool maturity + no-leads diagnostic. 200 candidates audited: 98 need quote
refresh, 69 maturing, 31 stale, 1 near trigger. No-leads: system_quiet_but_explained
(64 scanned, 0 GO, 79 incubator ready). Cron 5x/day M-F. Tests: 16/16 + regression.

---

## ALERT-3C — Dedicated Proposal Channel Configured — 2026-05-18

Dedicated Telegram group "TradeAI Proposal Decisions" (***5571) configured and
verified. Test alert sent successfully — arrived in dedicated channel only, not
general. Blocked DWSN has no approve. Poller restored. 46/46 tests pass.

---

## ALERT-3 — Dedicated Proposal Channel and Page — 2026-05-18

Proposal alerts routed to dedicated Telegram channel via TRADEAI_PROPOSAL_ALERT_CHAT_ID.
Proposal Alerts page added at /proposal-alerts under Trading tab. Chat IDs redacted.
Tests: 14/14 + ALERT-2/MISS-1 regression. Frontend build clean.

---

## MISS-1 — Missed Opportunity and Alert SLA Audit — 2026-05-18

Missed opportunity audit: 32 proposals, 8 rebuild required, 12 missed (price moved),
31 alerts missing (pre-ALERT-1). DWSN classified as avoided bad trade (R:R 1.95 at
creation). SLA tracking added. Tests: 10/10 + ALERT-2/Q-1 regression.

---

## ALERT-2 — Telegram Proposal Callbacks — 2026-05-18

Telegram callback handling: approve/reject/rebuild/watch/details. DWSN approve
correctly blocked (5 blockers). DWSN rebuild allowed. Alert messages now include
/ptapprove and /ptreject commands. Tests: 17/17 + ALERT-1/Q-1 regression.

---

## ALERT-1 — Telegram Proposal Decision Alerts — 2026-05-18

Telegram alerts for paper proposal decisions: ready/blocked/rebuild/review.
DWSN dry-run: BLOCKED with rebuild action, no approve. Wired into promoter.
Blocked proposals never show approve. Token redacted. Tests: 15/15 + PROMOTE-1 regression.

---

## PROMOTE-1 — Pre-Promotion Readiness Gate — 2026-05-18

Pre-promotion gate blocks candidates with R:R < 2.0, price drift > 8%, wide
spread, or invalid strategy from becoming actionable proposals. DWSN root cause:
promoted with R:R 1.95, price moved 14%, spread 14.8%. Gate wired into both
incubator promoter and auto proposal generator. Tests: 15/15 + Q-1/SP-2C regression.

---

## B-1E — Navigation Audit + Bucket 3 — 2026-05-18

5 orphan pages added to menu: Approvals (Trading), Paper Journal/Outcomes/Reports
(Journal), Paper Governance (System). Bucket 3: 12 LONG_CYCLE strategies validated,
no migration needed. 16 low-priority orphans documented. Frontend build clean.

---

## Q-1 — Proactive Quote Refresh — 2026-05-18

Provider trust policy + target selection + scheduled refresh for pending proposals
and incubator candidates. Cron: */5 9-15 M-F pending, 09:20/12:00/15:30 incubator.
6 targets identified (1 pending DWSN, 5 incubator stale). Finviz/yfinance remain
display-only. Tests: 20/20 + R-2 15/15 regression. No trades/orders/approval changes.

---

## R-2 — Strategy Family and Liquidity Gates — 2026-05-18

Eligibility, liquidity, and strategy family gates added before YAML-weighted scoring.
1,162 incompatible family evaluations blocked. Distribution: momentum_scalp 51,
swing_trade 25, +4 others. DIVIDEND_CORE_COMPOUNDER blocked for intraday candidates.
Tests: 15/15 + R-5 15/15 + SP-2C 17/17 regression. No YAML/activation/trade changes.

---

## R-5 — Wire YAML Scoring Weights into Router — 2026-05-18

Router now uses YAML scoring_weights instead of flat +10. 9 strategies have
weights, 14 fall back. Shadow comparison: earnings_post_momentum dropped from
72/81 top-match to 0. Distribution now momentum_scalp 69, gap_and_go 11,
swing_trade 1. No YAML changes. Tests: 15/15 + SP-2C/SP-2B regression.

---

## STRAT-ARCH-1 — Strategy Architecture Due Diligence — 2026-05-18

Deep architecture audit: 5 areas, 22 gaps identified, prioritized roadmap.
Key finding: YAML scoring_weights exist but router uses flat +10 (R-5 critical fix).
Router: momentum_scalp too broad (no family gating), no score normalization.
Quotes: no proactive refresh, 47% proposals with bad/missing quotes.
Taxonomy: 1 strategy with zero criteria invisible to router.
Tests: 15/15 + PAR-1 15/15 regression. No mutations. All human_review_only.

---

## PAR-1 — Parallel Hardening (No Backup) — 2026-05-18

Quote freshness: 42/83 exec-eligible, 22 stale. Route mismatches: 70 (mostly needs_more_data).
Source attribution: all 83 from allowed sources, no leakage. Watchpool: 1 active (DWSN).
Invalid strategy workflow designed (6 screener proposals). Canonical regression runner added.
Operator morning packet consolidates governance/maturity/A-5 status.
Tests: 15/15 + 10/10 regression suites. No backup/encryption work.

---

## B-1C — Bucket 2 Migration and Scalp Boundary Guard — 2026-05-18

Bucket 2 watchpool operational: 9 MULTI_DAY strategies, DWSN first entry today.
Scalp boundary: clean, no leakage. Trade AI momentum_scalp YAML preserved.
Migration dry-run: no missing strategies, no blockers. DB sync deferred.
SP-2C: still awaiting first live proposal. Tests: 13/13 + 17/17 regression.

---

## A-5 Monday Observation — 2026-05-18

Observation-only. NOT the final A-5 review.
- Day 3 of A-5 (1 market day). A-5 final blocked until 2026-05-22.
- 22 proposals since A-5 start (all May 15). 0 Monday proposals yet (market just opened).
- 9 closed trades: 2W/7L, +$44.95. Too few for conclusions.
- 2 GO candidates today (GOVX, DWSN). Promoter not yet fired.
- SP-2C route audit: wired but awaiting first live exercise.
- Maturity 7.1/10. All strategies blocked_a5_incomplete.
- Tests: 63/63. Safety: paper, LLM_DISABLE=true, holdings $1.19M.

---

## SP-2C — Wire Route Audit into Proposal Creation Pipeline — 2026-05-18

Wired `ensure_route_audit_for_proposal()` into all 4 proposal creation paths:
auto_proposal_generator, incubator_promoter, paper_trade_logger (scan + manual).
Every future proposal now gets 23-strategy evaluation at creation time.
Original strategy_id preserved. Invalid strategy_id flagged as blocker.
Tests: 17/17, SP-2B 17/17 regression. No strategy/YAML/trade/execution changes.

---

## SP-2B — Route Audit Backfill and Strategy Assignment Repair — 2026-05-18

Root cause: neither auto_proposal_generator nor incubator_proposal_promoter calls
store_setup_matches. 74/83 proposals missing route audit.
- Root cause report: confirmed 3 bypass paths
- Backfill dry-run: 72 processed, 46 mismatches, 2 skipped
- Invalid strategy: 6 proposals with strategy_id='screener'
- Config drift: 3 drifted (gap_and_go, momentum_scalp, swing_breakout)
- API blockers added: route_audit_missing, invalid_strategy
- Backfill --apply NOT run (deferred to operator)
- Tests: 17/17, SP-2 16/16, PP-UX-2 21/21 regression. No mutations.

---

## SP-2 — Strategy Watch Horizon and Finviz Screener Audit — 2026-05-18

Read-only strategy intelligence and screener quality audit:
- Watch horizon policy: 23 strategies with min/max watch days, required confirmations
- Watch horizon report: 1,139 candidates, 12 strategies, 28 expired momentum_scalp
- Screener quality audit: 18 screeners, cross-reference naming gap found
- Assignment engine audit: 74/83 proposals missing route audit, 6 "screener" strategy, 9 YAML/DB drift
- Screener optimization design: human-review-only, shadow A/B testing framework
- Tests: 16/16, SP-1 regression 13/13. No mutations, no screener changes.

---

## PP-UX-2 — Proposal Trust Audit — 2026-05-18

Added trust audit layer proving quote source, strategy fit, and technical evidence:
- Quote trust classifier: Finviz/yfinance display-only, Alpaca/Polygon execution-eligible
- Strategy fit audit: match scores, YAML rule pass/fail, alternatives, mismatch warnings
- Technical/backtest audit: Fib/ORB/EMA/VWAP status, backtest quality, missing sections
- Trust Audit panel on each card + compact summary line
- Approval blocker when quote is display-only or stale
- Tests: 21/21, PP-UX-1 regression 20/20, frontend build clean
- Safety: all read-only, no execution/trading changes

---

## PP-UX-1 — Paper Proposals Decision Packet Redesign — 2026-05-18

Upgraded Paper Proposals from thin trade cards to full operator decision packets:
- Sector/industry display (or explicit "Missing" flag)
- Strategy description, entry criteria, disqualifiers from YAML
- Entry/stop/target rationale with reasoning
- Structured approval blockers with action steps
- Guided workflow (1. Refresh, 2. Check Execution, 3. AI Review, 4. Approve)
- Staleness policy per timeframe class with STALE badge
- Evidence tiles + missing data visible in main card
- Run-health panel with incubator diagnostics and underfilled explanation
- Approve disabled when execution/RSI blockers exist
- News, sector metrics, strategy risk rules in details drawer
- Tests: 20/20, regression 50/50, frontend build clean
- Safety: read-only enrichment, no execution/trading changes

---

## BR-2A — Existing Drive Backup Target Validated — 2026-05-18

rclone NOT required. Existing GOG/Google Drive validated as offsite transport.
- Method: local backup → GPG encrypt → gog drive upload → Trade_AI_Backups/
- GPG 2.4.8 available. GOG authenticated. Drive access confirmed.
- BR-2 readiness: ready_for_encrypted_backup_apply (pending operator approval)
- No secrets uploaded. No trading changes.

---

## Phase 9B — Maturity Control Board — 2026-05-18

Consolidated maturity board: 7.1/10 overall.
- Healthy: execution safety (9.0), architecture (8.7), governance (8.0), operational (8.0)
- Blocked: strategy proof (4.0), backup (5.3 P0), agent learning (weak), live readiness
- Phase 8D: blocked until A-5 complete
- BR-2: operator_required (rclone)
- Live trading: BLOCKED
- Tests: 168/168. No trading changes.

---

## GOV-1 — Scheduled System Facts + A1A Checks — 2026-05-18

Operationalized governance with scheduled cron:
- System facts: 07:40 M-F + Sun 18:00
- A1A check: 07:45 M-F + Sun 18:05
- Governance status: 07:50 M-F + Sun 18:10
- All wrappers: safety guards, flock, logs, rollback
- Smoke test: healthy (0 A1A findings)
- Tests: 157/157. No trading changes.

---

## SP-1 — Strategy Proof Governance — 2026-05-18

Read-only strategy evidence funnel + proof policy + A-5 readiness.
- 11 strategies tracked through proposal→close funnel
- All 11: blocked_a5_incomplete (A-5 ends 2026-05-22)
- Proof statuses: blocked/insufficient/observing/preliminary/review_ready/decision_ready
- All decisions: human_review_only, never auto-activate
- Tests: 145/145 pass (13 SP-1 + 132 prior)
- No strategy activation, no trades, no orders, no cron

---

## DOC-CLEAN-1B — Archive Apply — 2026-05-17

401 files archived to docs/_archive/. 0 deleted. 0 errors.
Active tree: 246 docs. Archive: 526 docs. Canonical docs verified intact.
Duplicate deletion deferred. Drive sync pending.
Tests: 132/132. Safety: paper, live exec disabled.

---

## DOC-CLEAN-1 — Documentation Cleanup (Stage 1) — 2026-05-17

Inventory + classification of 767 local docs. Dry-run only.
- Active keep: 123 (10 canonical + 113 current phase)
- Archive candidates: 490
- Artifacts: 34
- Duplicate groups: 7
- Hygiene score: 3.5/10
- Drive sync script fixed: folder hierarchy + deletion cleanup
- Stage 2 (local archive apply) pending operator approval

---

## BR-1 — Backup and Restore Hardening — 2026-05-17

Backup readiness scoring + RPO/RTO policy + restore drill runbooks + offsite plan.

- Readiness: 5.3/10. DB backup healthy (daily 2 AM, 867MB). Offsite: P0 gap.
- rclone installed but no remotes configured — operator must run `rclone config`.
- RPO/RTO, restore runbooks, offsite plan documented.
- Tests: 132/132 pass. No secrets exposed. No trading changes.

---

## Phase 9A — Maturity Hardening — 2026-05-17

Reports for proof, reliability, and governance:
- Strategy sample governance: ALL 7 strategies blocked (insufficient closed trades, A-5 incomplete)
- Agent learning evidence gate: BLOCKED (evidence quality "weak", 9 closed outcomes)
- Data source fragility: Finviz healthy (513), Alpaca healthy (19), News healthy (610), YouTube unknown
- System facts: 358 tables, 455 scripts, 99 crons, trading BLOCKED
- Tests: 124/124 pass
- No strategy activation, no auto-learning, no live trading, no cron added

---

## Phase 8C — Lifecycle Dashboard Reporting — 2026-05-16

Read-only API endpoints + report for operator visibility into Phase 8B lifecycle data.

- GET /api/v2/phase8/lifecycle-summary
- GET /api/v2/phase8/strategy-scorecards
- GET /api/v2/phase8/outcome-review-queue
- Report: scripts/report_phase8_dashboard_readiness.py
- Tests: 7 Phase 8C + 114 total regression pass
- Dashboard UI: deferred (API-only for now)
- A-5 not complete → scoring "preliminary"
- All scorecards: human_review_only

---

## Phase 8B — Lifecycle Outcome Scoring — 2026-05-16

Additive outcome labeling and preliminary strategy scorecards from Phase 8A lifecycle data.

- Schema: paper_trade_lifecycle_outcomes + paper_strategy_scorecards
- Backfill: 23 trades → 23 outcome records (9 closed, 14 cancelled/open)
- Scorecards: 6 strategies, all "insufficient" sample (< 5 trades each)
- Labels: win/loss/stopped/target_hit/breakeven/cancelled/open
- All scorecards: human_review_only
- A-5 observation not complete → scoring is PRELIMINARY
- Tests: 107/107 pass (83 Phase 6 + 15 Phase 7 + 9 Phase 8B)
- No strategy activation changes, no order submission, no cron

---

## Phase 8A — Lifecycle Discovery — 2026-05-16

Read-only discovery of paper trade lifecycle: proposal → approval → trade → close → outcome.

Key findings:
- 83 proposals, 11 linked to trades, 9 closed with complete data
- All 9 closed have exit_reason + pnl + r_multiple + closed_at
- 18/23 trades link back to proposal_id
- Main gap: outcome_label column (trivially computed)
- Phase 8B ready after A-5 observation window (2026-05-22)

No mutations. No scoring. No labels created.

---

## Phase 7 — Approval Simulator — 2026-05-16

Read-only approval simulation: runs all Phase 6 gates (freshness, session, revalidation, risk) without creating trades, submitting orders, or mutating proposal state.

- CLI: `scripts/simulate_paper_proposal_approval.py`
- API: `POST /api/v2/paper-proposals/simulate-approval`
- Returns: overall_status, blocking_gate, gate-by-gate results, paper_order_preview, next_action
- Tests: 15/15 Phase 7 + 83/83 Phase 6 = **98/98 pass**
- Dashboard: deferred (API-only for now)

---

## Full Session Summary — 2026-05-15

### 25 commits across 6 work streams:

**Phase 6 Execution Safety (5 commits):**
- 6A: Live market revalidation gate (f310f61)
- 6B: Market session policy gate (6ef555e)
- 6C: Approval audit trail (7ce7c4a)
- 6D: Proposal stale-time sweeper (cadcd5c)
- 6E: Scheduled sweeper cron (c6d0192)

**A-Track Pipeline (4 commits):**
- A-1: Hard risk governance gates (109d8b7)
- A-2: 5 strategies activated (b41a013)
- A-3.5: Morning brief automation (1db185f)
- A-4: Systemic pipeline defect fix (79ffb31)

**Promoter Quality (4 commits):**
- RSI gate: screener strategy added to momentum group (aab9eab)
- Spread gate + $3 price floor at promotion (58c908c)
- Classification-based promoter for diversity (72a04df)
- Hard price floor in auto_proposal_generator (cdd12fb)

**Screener Overhaul (4 commits):**
- Wire 8 quality screeners into run_windows + PM diversity (db8e631)
- Screener reference docs (cf2a680)
- Screener config modal with CRUD + gap analysis (9a29f6f)
- 6 gap-fill screeners — 0 gaps remaining (059d479)

**UI Fixes (4 commits):**
- Morning brief render crash + paper account zeros + newly-activated endpoint (6ce832d)
- Dashboard humanize crash + debug cleanup (42affa7)
- TaxLots hooks, StrategyDesk Decimal, scoreboard PF, plan adherence (42846b6)
- Datetime serialization in screener API (a4cd98e)

**Documentation (5 commits):**
- Post-A-4 observation Day 1 (2440f25)
- Phase 6 README + deployment log updates (08999ec)
- Promoter quality gate docs (52ae32b)
- UI stabilization session summary (4ad1f13)

### Final State
- 83/83 Phase 6 tests passing
- 18 Finviz screeners, 0 strategy gaps
- Approval flow: Audit → Freshness → Session → Revalidation → Risk Gate → Paper Trade → Alpaca
- Pipeline producing proposals hourly
- A-5 observation clock running (ends 2026-05-22)

---

## Promoter Quality Gates — Spread + Price Floor — 2026-05-15

### Summary
7/7 proposals on Day 1 were blocked by execution readiness (spread, price drift, missing technicals). Root cause: the incubator promoter was surfacing illiquid micro-caps with 30%+ spreads and sub-$3 penny stocks. Phase 6 safety gates correctly caught them, but they shouldn't have been promoted.

### Fixes
1. **Spread gate at promotion**: blocks if live spread > 3%
2. **Strategy-aware price floor**: momentum/scalp/screener/gap_and_go require $3+ (was $1)

### Promoter Gate Chain (complete)
```
Candidate → Already pending? → Price lookup → Penny < $1? → Momentum < $3? → Spread > 3%? → RSI overbought? → INSERT
```

### Verification
5/7 bad proposals would now be caught at promotion. Remaining 2 (MLGO, RCEL) had tight spreads and $5+ prices — blocked later for price drift (timing, not quality).

### Test: 83/83 pass

---

## Post-A-4 Pipeline Observation Day 1 — 2026-05-15

First live-market evidence after A-4 pipeline repair. 4 proposals generated hourly (08-11 AM ET). 19 scan signals across 6 hours. 1/5 activated strategies (speculative_growth) produced a proposal. Pipeline is firing as designed. Morning brief renders correctly after 6ce832d fix. Paper account shows real equity (~$100K). Phase 6 tests: 83/83 clean. A-5 deferred pending 3-5 trading day observation window (through 2026-05-22).

---

## Phase 6E — Scheduled Stale Proposal Sweeper — 2026-05-15

### Summary
Operationalized the Phase 6D stale sweeper with a safe scheduled wrapper and cron entries.

### Schedule
| Time (ET) | Mode | Purpose |
|-----------|------|---------|
| 08:15 M-F | dry-run | Pre-market freshness report |
| 08:25 M-F | apply | Mark stale proposals before market open |
| 16:10 M-F | report-only | End-of-day summary |

### Files Added
- `scripts/run_scheduled_stale_proposal_sweeper.sh` — wrapper with flock, safety gates, logging
- `scripts/rollback_phase6e_stale_sweeper_cron.sh` — cron rollback helper
- `tests/test_phase6e_scheduled_stale_sweeper.py` — 12 unit tests

### Safety
- Wrapper verifies ALPACA_MODE=paper + LLM_DISABLE=true + holdings > $1M
- Defaults to dry-run (no args = dry-run)
- Uses flock to prevent overlap
- Never approves, creates trades, submits orders, or deletes proposals
- Rollback removes only Phase 6E cron entries

### Tests: 12/12 passed, 83/83 total regression

### Production Impact
Paper proposals only. Stale marking only. No execution changes.

---

## Phase 6D — Proposal Stale-Time Sweeper — 2026-05-15

### Summary
Stale proposals are now flagged before an operator clicks approve. Strategy-aware freshness thresholds ensure old proposals don't hit the approval gates.

### Approval Flow (complete)
```
Approve → Audit → Freshness Gate → Session Gate → Revalidation → Risk Gate → Paper Trade → Alpaca
```

### Stale Thresholds
| Strategy | Stale After |
|----------|-------------|
| momentum_scalp, gap_and_go, scalp | 60 min |
| screener, day_trade, momentum | 4 hours |
| swing, swing_breakout | 3 trading days |
| recovery_watch, defense_thesis | 5 trading days |
| income, dividend, position | 10 trading days |
| unknown | 24 hours |

### Files Added
- `scripts/phase6_proposal_staleness_policy.py` — pure classifier
- `scripts/sweep_stale_paper_proposals.py` — sweeper (dry-run default)
- `scripts/report_phase6_stale_proposals.py` — summary report
- `scripts/create_phase6_stale_sweeper_schema.py` — audit table
- `tests/test_phase6_proposal_stale_sweeper.py` — 18 unit tests

### Test Results
- Unit tests: **18/18 passed**
- Full regression: **71/71 passed** (24 + 12 + 17 + 18)

### Safety Audit: 20/20 PASSED

### Production Impact
Paper proposals only. Sweeper never deletes proposals, creates trades, or submits orders. Cron not scheduled — manual only until Phase 6E.

---

## Incubator Promoter RSI Gate Fix — 2026-05-15

### Summary
Fixed RSI gate gap that allowed FLYW to be promoted at RSI 83 as a `screener` strategy. The `screener` strategy was not in any RSI gate group, so only the catch-all at RSI >= 85 applied. FLYW then dropped below its stop loss within an hour.

### Changes
- Added `screener` to the momentum RSI gate group in `_check_rsi_gate()` — now blocks at RSI >= 80
- RSI value is now stored on the proposal record (`rsi` column) at promotion time
- `_check_rsi_gate()` returns 3 values: `(allowed, reason, rsi_value)` for audit/display

### RSI Gate Thresholds (updated)

| Strategy Group | Threshold | Strategies |
|----------------|-----------|------------|
| Momentum | >= 80 | momentum_scalp, gap_and_go, earnings_catalyst, speculative_growth, core_growth_compounder, **screener** |
| Swing | >= 75 | swing_breakout, swing_trade, sector_rotation, defense_thesis |
| Catch-all | >= 85 | Any non-exempt strategy |
| Exempt | N/A | income_add, dividend_growth_compounder, high_yield_income_bdc, covered_call_income, bond_income, cash_or_stable, recovery_watch |

### Root Cause
FLYW was promoted by `incubator_proposal_promoter.py` with `strategy_id = 'screener'`. The RSI gate checked:
1. Is `screener` in `_MOMENTUM`? No (was not listed)
2. Is `screener` in `_SWING`? No
3. Is RSI >= 85? No (was 83)
4. Result: allowed — **incorrect**

### Verification
After fix: `_check_rsi_gate('FLYW', 'screener', conn)` returns `(False, 'RSI_83_overbought_blocks_screener', 82.9)`

### Production Impact
Paper proposals only. No broker/execution changes.

---

## Phase 6B — Market Session Approval Policy — 2026-05-15

### Summary
Paper proposal approvals are now blocked outside regular trading hours. Only regular session (09:30-16:00 ET, Mon-Fri, non-holiday) is allowed.

### Session Policy
| Session | Allowed |
|---------|---------|
| Regular (9:30-16:00 ET Mon-Fri) | YES |
| Pre-market | NO |
| After-hours | NO |
| Weekend | NO |
| Holiday | NO |
| Unknown/error | NO (fail-closed) |

### Audit Integration
The session gate fills the Phase 6C audit trail slot that was previously "not_implemented". Real session policy results are now recorded for every approval attempt.

### Test Results
- Unit tests: **17/17 passed**
- API mock validation: **9/9 passed**
- Regression: **53 total tests pass** (24 6A + 12 6C + 17 6B)

### Safety Audit: 19/19 PASSED

### Production Impact
**Paper proposals only.** No broker, execution, or live-trading changes. Extended-hours approvals are not enabled.

---

## Phase 6C — Paper Approval Audit Trail — 2026-05-15

### Summary
Every paper proposal approval attempt is now recorded in a durable audit trail with gate-by-gate outcomes. The operator can query exactly what happened at each gate for any approval attempt.

### What Was Added
- **DB schema**: `paper_proposal_approval_audit` (main) + `paper_proposal_approval_audit_events` (granular)
- **Helper module**: `scripts/phase6_approval_audit.py` — create, update, finalize, append events
- **Endpoint wiring**: `POST /api/v2/paper-proposals/approve` now creates audit row before gates, records each gate outcome, and returns `approval_audit` with `audit_id`
- **Report script**: `scripts/report_phase6_approval_audit.py` — summary, filtering, JSON/MD output
- **Tests**: 12 unit tests (all pass), 6 API mock scenarios (all pass)

### Audit Flow
```
Request → Create audit (fail-closed if fails)
  → Session gate → update audit
  → Market revalidation → update audit
  → Risk gate → update audit
  → Paper trade creation → update audit
  → Alpaca submission → update audit
  → Finalize audit with outcome
```

### Fail-Closed Behavior
If audit creation fails, the approval is blocked. Audit update/event failures are non-critical (logged, don't block).

### Safety Audit
- ALPACA_MODE=paper: CONFIRMED
- LLM_DISABLE_LIVE_EXECUTION=true: CONFIRMED
- No .env change: CONFIRMED
- No secrets stored: CONFIRMED (IP/UA hashed)
- All existing gates preserved: CONFIRMED

### Production Impact
**Paper proposals only.** Additive DB tables. No existing tables altered. No approval logic changed. No broker/holdings/execution changes.

---

## Phase 6A — Paper Approval Market Revalidation Hardening — 2026-05-15

### Summary
Added mandatory live market revalidation gate to paper proposal approval flow. No proposal can be approved on stale pricing or unfavorable conditions.

### Approval Flow Change
```
BEFORE: Approve → Risk Gate → Create Paper Trade → Submit to Alpaca
AFTER:  Approve → Live Market Revalidation → Risk Gate → Create Paper Trade → Submit to Alpaca
```

### Block Conditions
| Condition | Threshold |
|-----------|-----------|
| No live quote | BLOCK |
| Stale quote | > 15 min → BLOCK |
| Price drift | > 3% → BLOCK |
| Stop breached | price <= stop → BLOCK |
| Wide spread | > 1.5% → BLOCK |
| R:R degraded | < 1.2:1 → BLOCK |
| Moderate drift | 1.5-3% → WARN, adjust entry |

### Test Results
- Unit tests: **24/24 passed** (`tests/test_phase6_market_revalidation.py`)
- API mock validation: **7/7 passed** (`scripts/test_phase6_market_revalidation_api.py`)

### API Response Change
`/api/v2/paper-proposals/approve` now returns `market_revalidation` object with live_price, drift, R:R, spread, blockers, warnings, and human-readable message.

### Dashboard Change
`PaperProposals.tsx` — approval success/failure now displays market revalidation summary (live price, drift, R:R, warnings) via alert dialog.

### Safety Audit
- ALPACA_MODE=paper: CONFIRMED
- LLM_DISABLE_LIVE_EXECUTION=true: CONFIRMED
- No .env change: CONFIRMED
- No broker/holdings/execution change: CONFIRMED
- All errors fail closed: CONFIRMED
- No bypass path exists: CONFIRMED

### Files Changed
- `scripts/paper_trade_logger.py` — added `validate_paper_proposal_live_market()`, `_revalidate_market_conditions()`, modified `approve_proposal()`
- `scripts/api_v2.py` — added `market_revalidation` to response
- `apps/command-center-v2/src/pages/PaperProposals.tsx` — display revalidation in alerts
- `tests/test_phase6_market_revalidation.py` — NEW (24 tests)
- `scripts/test_phase6_market_revalidation_api.py` — NEW (7 scenarios)
- `docs/execution_safety/phase6_market_revalidation/` — NEW (9 documents)

### Production Impact
**Paper proposals only.** No broker, execution, live-trading, or holdings changes. Existing risk gate preserved and strengthened with pre-gate market validation.

### Rollback
```bash
git revert <phase6a-commit>
```

---

## Gate Results — 2026-05-11 17:50 ET

### Gate 0 — Live Environment Discovery: PASSED (with notes)
- pwd: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`
- git HEAD: `30dce44` — Update Trade Supervision Methodology
- Discovery artifacts saved to `docs/v4_1_discovery/`

### Gate 1 — Documentation Read: PASSED
All three docs read in full.

### Gate 2 — Clean Working Tree: DISCREPANCY
Working tree has modified files (tsconfig build info, youtube_cookies, docs updates) and untracked files (archive dirs, v4.1 docs themselves, DOF xlsx). **None are LLM scripts or config files.** Proceeding — these are pre-existing non-LLM changes.

### Gate 3 — Holdings Integrity: PASSED
Holdings: $1,191,456 across 47 positions.

### Gate 4 — Paper Mode: PASSED (with deviation)
- `ALPACA_MODE=paper` — present
- `LIVE_TRADING` — NOT in .env (paper mode enforced by code, not env var)
- `LLM_DISABLE_LIVE_EXECUTION` — NOT in .env (will add during Phase 0.6)

**Deviation:** The prompt expects all three vars. The system is paper-only by hardcoded design. Will add `LLM_DISABLE_LIVE_EXECUTION=true` as an additive .env change in Phase 0.6.

### Gate 5 — Backup Verification: PASSED
- Full backup: `docs/backups/trade_ai_backup_20260511.zip` (143MB, today)
- DB dump: `/home/johnclaw/db_backups/trade_ai_20260511_020003.sql.gz` (91MB, today 2AM)
- Backup script supports `--dry-run` only, NOT `--tag` or `--include-*` flags

**Deviation from plan:** `full_system_backup.py` does not support `--tag`, `--include-state`, `--include-rag-index`, `--include-env`, or `--include-crontab`. Output path is `docs/backups/trade_ai_backup_YYYYMMDD.zip`. The plan's backup command must use the simpler form: `.venv/bin/python scripts/full_system_backup.py`

### Gate 6 — Ollama Health: PASSED
Ollama alive at localhost:11434. Running models: qwen3:14b (9624MB), nomic-embed-text (551MB).

### Gate 7 — Database Connectivity: PASSED

### Gate 8 — Provider Map: RECONCILED
**Live .env providers:**
- `ANTHROPIC_API_KEY` — set (Claude)
- `OPENAI_API_KEY` — set (OpenAI)
- `XAI_API_KEY` — set (xAI/Grok)
- No `LLM_*` process-type vars exist yet

**Live Ollama models:**
- `qwen3:14b` — resident, 9624MB
- `nomic-embed-text` — resident, 551MB

**Deviation:** The plan references `grok-4.3`, `gpt-5-mini` — these are NOT in .env. Live cloud model IDs are:
- OpenAI fallback: `gpt-4o-mini` (hardcoded in local_llm.py line 27)
- Anthropic fallback: `claude-sonnet-4-6` (hardcoded in local_llm.py line 28)
- xAI: API key present but no model ID hardcoded in local_llm.py

### Gate 9 — Config Hub Decision: RESOLVED
**`scripts/local_llm_config.py`** is the config hub. It:
- Centralizes model selection via `get_local_llm_model()`
- Reads from `.env` (`LOCAL_LLM_MODEL`, default `qwen3:14b`)
- Provides Ollama runtime env setup

**`scripts/local_llm.py`** is the execution path. It:
- Imports from `local_llm_config.py`
- Uses file-based toll gate (`fcntl` lock)
- Has hardcoded fallback model names: `gpt-4o-mini`, `claude-sonnet-4-6`
- All callers use `generate()` function
- Does NOT have `execute()` method — it has `generate()`

**`scripts/llm_router.py`** also exists (21KB). Needs inspection to determine if it routes production calls.

**Decision:** Extend `local_llm_config.py` with process-type constants. Create `llm_config.py` only as a thin wrapper that imports from it. Do NOT replace `local_llm_config.py`.

### Gate 10 — Operator Authorization: PASSED
Operator said "Begin Phase 0 only."

## Detected Service Units

**User units:**
- `openclaw-gateway.service` (active)
- `tradeai-continuous.timer` (active)
- Multiple portfolio/aegis timers

**System units:**
- `ollama.service` (active)
- `tradeai-portfolio-server.service` (active)
- `tradeai-continuous.timer` (active)
- `tradeai-reprice.timer` (active)

**Rollback restart targets (verified):**
- `sudo systemctl restart ollama.service`
- `systemctl --user restart tradeai-continuous.timer`
- Kill/restart `portfolio_server.py` (runs as process, not always via systemd)

## LLM Reference Scan Summary
- 524 total references found across scripts/apps/config
- Primary config: `scripts/local_llm_config.py` (source of truth)
- Primary execution: `scripts/local_llm.py` (generate() function)
- Router: `scripts/llm_router.py` (exists, needs classification)
- Direct Ollama callers: need full inventory (Phase 0 deliverable)

## Direct Ollama Callers (Migration List)
To be populated during Phase 0 implementation.

## Phase 0 Follow-Up — 2026-05-11 20:15 ET

### A. Audit Log Validation: PROVEN
- Path: `logs/llm_routing_audit.jsonl`
- `_log_audit()` in `scripts/local_llm.py:43-62` writes JSONL entries
- File auto-created on first audited call (directory auto-created via `mkdir(parents=True)`)
- Fields: ts, caller, process_type, model, provider, latency_ms, status, fallback, phase
- No prompts, secrets, holdings, or account details are logged
- Failures are logged (status=local_failed, all_failed)
- Validation command:
  ```bash
  ls -lh logs/llm_routing_audit.jsonl && tail -5 logs/llm_routing_audit.jsonl | python3 -m json.tool --no-ensure-ascii
  ```

### B. System-Health local.available Fix: FIXED
- **Root cause:** `health_check()` in `llm_router.py` called `_call_local()` with a generate probe.
  Two bugs: (1) success threshold required >20 chars but probe asked for 1-word answer;
  (2) qwen3:14b with thinking takes 50-120s, far exceeding the 30s effective HTTP timeout.
- **Fix:** Replaced generate-based probe with `/api/ps` model residency check (~50ms).
  If qwen3:14b is resident in VRAM, `local.available=true`. This matches how `gpu-status` works.
- **Trade-off:** Residency check confirms model is loaded, not that generation works.
  Generation latency issues are surfaced separately by `verify_llm_providers.py` live probes.

### C. Provider Verification Upgrade: DONE
- `scripts/verify_llm_providers.py` now reports four-level status per provider:
  - **configured** — key/env present
  - **reachable** — endpoint/network responds
  - **usable** — tiny live test succeeds (Ollama generate, OpenAI/Anthropic chat)
  - **degraded** — quota/billing/rate-limit/auth error
- Anthropic is NOT marked usable if API returns billing/credit/auth errors
- No secrets printed (keys redacted to first 8 + last 4 chars)
- Summary table at bottom shows all four dimensions per provider
- Validation command:
  ```bash
  .venv/bin/python scripts/verify_llm_providers.py
  ```

### D. qwen3:14b Generation Latency — OBSERVATION (superseded by Phase 0B)

See Phase 0B below for full diagnosis.

## Phase 0B — Local LLM Diagnostics — 2026-05-11 20:47 ET

### Root Cause: Queue Saturation, NOT Model Failure

**qwen3:14b is healthy.** The observed 83-120s latency was caused entirely by
**Ollama request queue saturation** from concurrent cron processes.

### Evidence — Clean Queue Direct Tests

| Test | think:false | num_predict | eval_count | eval_time | total_time | tok/s |
|------|------------|-------------|------------|-----------|------------|-------|
| Tiny (/no_think ok) | yes | 3 | 3 | 0.19s | 12.2s | 15.8 |
| 2-sentence | yes | 100 | 35 | 3.3s | 5.6s | 10.5 |
| Agent-sized (w/ /no_think) | yes | 300 | 114 | 11.5s | 14.6s | 9.9 |
| Agent-sized (no prefix) | yes | 300 | 125 | 12.6s | 16.2s | 9.9 |
| **Thinking ENABLED** | **no** | 800 | **460** | **48.0s** | **57.0s** | 9.6 |

Key findings:
- **9.6-15.8 tok/s** — normal for qwen3:14b Q4_K_M on Intel Arc B50 Vulkan
- **`think:false` works correctly** — reduces token count from 460 to ~120 for same prompt
- **No `<think>` tags** in any output (DB confirmed across 8 recent results)
- **`/no_think` prefix has no measurable effect** — `think:false` API param is sufficient
- **local_llm.generate() works**: 11.9s on clean queue, audit logged as `status=ok`

### Queue Saturation Mechanism

```
Cron: */5 20-23 * * 1-5  process_watchlist_agent_jobs.py --limit 25
```

- Fires every 5 minutes → ~25 LLM calls per invocation
- Each call takes ~15s with think:false, ~57s with thinking enabled
- Processes accumulate because they can't finish before the next cron fires
- **Peak observed: 10 concurrent processes** (from 20:00-20:45, none finished)
- Ollama serializes generation → queue depth × 15s per request = catastrophic wait
- Fallback chain catches this: local timeout → Claude (billing fail) → Grok (succeeds in 13-28s)

### Diagnostic Fields Added to llm_router.py

`_call_local()` now captures Ollama internals on success:
- `eval_count`, `prompt_eval_count`, `eval_duration_s`, `prompt_eval_duration_s`
- `total_duration_s`, `tok_per_s`
- Written to `logs/llm_router.log` as `ollama_*` fields when provider=local

### Provider Status (at time of testing)

| Provider | Status | Detail |
|----------|--------|--------|
| Local (qwen3:14b) | **USABLE** (when queue is clear) | 9.9 tok/s, ~15s per agent call |
| OpenAI | USABLE | 1.84s probe response |
| Anthropic | DEGRADED | Credit balance too low (HTTP 400) |
| xAI/Grok | CONFIGURED | Actively handling fallback traffic (~$0.0002/call) |

### Recommendations for Phase 1

1. ~~**Add flock guard to watchlist cron**~~ — Done in Phase 0C
2. **Reduce cron frequency** during evening hours (*/15 instead of */5) — optional, flock handles it
3. **No model changes needed** — qwen3:14b performance is normal at 9.9 tok/s
4. **`think:false` is working** — no `/no_think` prefix needed in prompts
5. **Anthropic billing** should be resolved before relying on Claude as fallback
6. **Grok fallback is functioning** and keeping the system operational during queue saturation

## Phase 0C — Cron Concurrency Guard — 2026-05-11 21:01 ET

### Change: flock guard on all process_watchlist_agent_jobs.py cron entries

**Lock file:** `/tmp/tradeai_watchlist_agent_jobs.lock`
**Mechanism:** `flock -n -E 99` (non-blocking, exit 99 on conflict)
**Skip logging:** On conflict, writes timestamped `[flock] skipped` to `logs/watchlist_agent_jobs.log`

### Cron entries modified (4 of 4)

| Schedule | Hours | Limit | Status |
|----------|-------|-------|--------|
| `*/15 6-19 * * 1-5` | Market hours | --limit 10 | flock guarded |
| `*/5 20-23 * * 1-5` | Evening | --limit 25 | flock guarded |
| `*/5 0-5 * * 2-6` | Overnight | --limit 25 | flock guarded |
| `*/10 * * * 0,6` | Weekend | --limit 15 | flock guarded |

### Crontab backup
- Pre-change backup: `docs/v4_1_discovery/crontab_pre_phase0c.txt`
- Also at: `/tmp/crontab_backup_20260511_phase0c.txt`

### Flock contention test: PASSED
- First lock acquired → second flock correctly returned exit code 99
- Skip logging confirmed functional

### Validation
- `crontab -l | grep process_watchlist_agent` — all 4 entries show `flock -n -E 99`
- No overlapping agent processes observed after installation
- `system-health`: `local.available=true`, `latency=0.001s`
- `gpu-status`: qwen3:14b resident, 9.94 GB VRAM used
- Safety: `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, holdings $1,191,456

### What was NOT changed
- No model routing changes
- No model pulls
- No cron frequency changes (still */5 evening, */15 market hours)
- No --limit reductions
- No broker, holdings, or execution changes

## Phase 0D — Runtime Cap and Batch-Size Control — 2026-05-11 21:25 ET

### Evidence prompting this change
- Phase 0C flock is working: `[flock] skipped` logged at 21:10 and 21:15
- But the 21:05 process ran for 14+ minutes, monopolizing Ollama for one batch
- Single-job runtime remains too long for other callers to get queue time

### Changes applied

**1. Runtime cap:** `timeout 12m` added inside flock, outside the Python process.
- flock acquires lock → timeout caps the job at 12 minutes → Python runs inside both
- If job exceeds 12m, timeout sends SIGTERM (exit 124) and logs `[timeout]` entry
- flock is outside timeout so lock-skip detection (exit 99) still works independently

**2. Batch size reduced to --limit 10 across all schedules:**

| Schedule | Hours | Old limit | New limit |
|----------|-------|-----------|-----------|
| `*/15 6-19 * * 1-5` | Market hours | 10 | 10 (unchanged) |
| `*/5 20-23 * * 1-5` | Evening | 25 | **10** |
| `*/5 0-5 * * 2-6` | Overnight | 25 | **10** |
| `*/10 * * * 0,6` | Weekend | 15 | **10** |

**3. Exit code handling:** `rc=$?` captured once, checked for both 99 (flock skip) and 124 (timeout).

### Crontab backup
- Pre-change: `docs/v4_1_discovery/crontab_pre_phase0d.txt`

### Validation
- `crontab -l | grep process_watchlist_agent` — all 4 entries show `flock`, `timeout 12m`, `--limit 10`
- `timeout 2s bash -lc 'sleep 5'` → exit 124 confirmed
- Safety: `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, holdings $1,191,456

### Monitoring commands
```bash
# Check for timeout kills
grep '\[timeout\]' logs/watchlist_agent_jobs.log

# Check for flock skips
grep '\[flock\]' logs/watchlist_agent_jobs.log

# Confirm single-process at any time
ps -ef | grep process_watchlist_agent_jobs.py | grep -v grep | wc -l
```

### What was NOT changed
- No model routing or model pull changes
- No cron frequency changes (still */5 evening, */15 market hours)
- No broker, holdings, or execution changes

## Phase 0E — Watchlist Agent Batch Tuning — 2026-05-11 22:15 ET

### Reason
Phase 0D set `--limit 10` with a 12-minute timeout cap. The watchlist agent still
hit the timeout consistently — 10 jobs × ~2 min/job (including queue wait and Grok
fallback) exceeds 12 minutes. Reducing to `--limit 5` targets ~10 minutes per batch.

### Change
All 4 `process_watchlist_agent_jobs.py` cron entries: `--limit 10` → `--limit 5`.

| Schedule | Hours | Old limit | New limit |
|----------|-------|-----------|-----------|
| `*/15 6-19 * * 1-5` | Market hours | 10 | **5** |
| `*/5 20-23 * * 1-5` | Evening | 10 | **5** |
| `*/5 0-5 * * 2-6` | Overnight | 10 | **5** |
| `*/10 * * * 0,6` | Weekend | 10 | **5** |

### Preserved
- `flock -n -E 99` — overlap prevention
- `timeout 12m` — runtime cap
- `[flock] skipped` logging (exit 99)
- `[timeout]` logging (exit 124)
- Cron frequencies unchanged

### Crontab backup
- `docs/v4_1_discovery/crontab_pre_phase0e.txt`

### Monitoring
```bash
# Check for timeouts (should stop appearing with --limit 5)
grep '\[timeout\]' logs/watchlist_agent_jobs.log | tail -10

# Check for flock skips (expected during adjacent cron windows)
grep '\[flock\]' logs/watchlist_agent_jobs.log | tail -10

# Check process count
ps -ef | grep process_watchlist_agent_jobs.py | grep -v grep | wc -l
```

## Phase 1 Pilot — gemma3:27b BATCH_OVERNIGHT Test — 2026-05-11 22:00 ET

### Result: CONDITIONAL GO

gemma3:27b was tested as a BATCH_OVERNIGHT model. Full report: `docs/v4_1_phase1_pilot_report.md`

### Key metrics
- **VRAM**: 13.75 GB allocated (75.3% GPU), 4.51 GB CPU spillover
- **Throughput**: 5.3 tok/s (vs qwen3:14b at 9.9 tok/s) — ~53% throughput
- **Pilot script**: `multi_strategy_classifier.py --batch --llm --limit 1` — classified ACH in 99s
- **Restore**: qwen3:14b + nomic-embed-text fully restored (9.94 GB, matching pre-pilot state)

### Method
- Model override via `LOCAL_LLM_MODEL=gemma3:27b` in shell only (not persisted to .env)
- BATCH_OVERNIGHT was NOT changed persistently
- GPU lifecycle: cooldown(qwen) → smoke test(gemma) → pilot run → cooldown(gemma) → warmup(qwen+nomic)

### Next steps for Phase 1 expansion (NOT started)
1. ~~Create `gemma3-overnight` Modelfile~~ — Done in Phase 1B
2. Set `LLM_BATCH_OVERNIGHT=gemma3-overnight` in `.env` (when operator approves)
3. ~~Create lifecycle wrapper script~~ — Done in Phase 1B
4. Run one controlled overnight test with wrapper before expanding

## Phase 1B — Overnight Model Preparation — 2026-05-11 22:09 ET

### Deliverables created

**1. `gemma3-overnight` named model** (via `config/Modelfile.gemma3-overnight`)
- Based on gemma3:27b
- `num_ctx=4096`, `temperature=0.2`, `top_p=0.9`, `num_predict=500`
- Concise classification system prompt
- `keep_alive=0` handled at request time by lifecycle wrapper
- Built: `ollama create gemma3-overnight -f config/Modelfile.gemma3-overnight`
- Verified: `ollama list` shows `gemma3-overnight:latest` (17 GB)

**2. Smoke test: PASSED**
- Prompt: "Classify AAPL: growth, value, or income?"
- Response: "Growth." — 5.5s total, 8.3 tok/s
- VRAM: 13.64 GB (74% GPU), same profile as raw gemma3:27b

**3. `scripts/run_batch_overnight_gemma_pilot.sh` wrapper** (not scheduled)
- Sets `LOCAL_LLM_MODEL=gemma3-overnight` inside script only
- Safety: checks ALPACA_MODE, LLM_DISABLE_LIVE_EXECUTION, holdings guard
- Active hours gate: refuses during 9:30-16:00 ET
- GPU lifecycle: evict qwen → run pilot → unload gemma → restore qwen + nomic
- Fail-closed: exit 2 with manual intervention instructions if restore fails
- Timeout: 10 minutes default
- Logs to: `logs/gemma_overnight_pilot.log`
- Default: `--batch --llm --limit 1`

### What was NOT changed
- `.env` was NOT modified
- `LLM_BATCH_OVERNIGHT` remains unset (defaults to qwen3:14b)
- No cron entries added or modified
- No routing changes to STANDARD, REALTIME, EMBEDDING, or any other process type
- No broker, holdings, or execution changes
- qwen3:14b + nomic-embed-text fully restored (9.94 GB)

### Validation commands for controlled overnight test
```bash
# Run wrapper manually (outside market hours only)
./scripts/run_batch_overnight_gemma_pilot.sh

# Or with more symbols (max 3 in Phase 1C)
./scripts/run_batch_overnight_gemma_pilot.sh --limit 3

# Check results
tail -50 logs/gemma_overnight_pilot.log
curl -s http://localhost:7777/api/v2/gpu-status | python3 -m json.tool
```

## Phase 1C — Controlled Expansion (2 symbols) — 2026-05-12 08:10 ET

### Script fix
- `--limit` argument parsing was broken (only captured `$1`, dropped value)
- Replaced with proper while/case parser supporting `--limit N`
- Added `MAX_LIMIT=3` enforcement (hard cap for Phase 1C)
- Default remains `--limit 1`

### Pilot run: --limit 2

| Metric | Value |
|--------|-------|
| Symbols classified | 2 |
| Runtime | 2 min 42 sec |
| Per-symbol time | ~1 min 21 sec avg |
| gemma3-overnight VRAM | 13.64 GB GPU + 4.79 GB CPU |
| Pilot exit code | 0 |
| qwen3 restore | ok |
| nomic restore | ok |

### Post-run validation: ALL PASSED
- GPU: qwen3:14b (9.4 GB) + nomic-embed-text (0.54 GB)
- verify_llm_providers.py: Local usable=True
- ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true
- Holdings: $1,191,948

### Limit 3 recommendation: YES
- 2-symbol at 2m42s leaves wide margin under 10m timeout
- Extrapolated 3-symbol: ~3m13s
- GPU lifecycle clean on both 1-symbol and 2-symbol runs

### What was NOT changed
- No cron entries added or modified
- No .env routing changes (BATCH_OVERNIGHT not set)
- No changes to STANDARD, REALTIME, EMBEDDING, MEDIA_CONTENT, CRITICAL_CLOUD
- No broker, holdings, or execution changes
- Full report: `docs/v4_1_phase1c_controlled_expansion_report.md`

## Phase 1D — Controlled Limit-5 Expansion — 2026-05-12 08:57 ET

### Script change
- `MAX_LIMIT` raised from 3 to 5 in `run_batch_overnight_gemma_pilot.sh`
- Default remains `--limit 1`
- All safety gates preserved (ALPACA_MODE, LLM_DISABLE, holdings, active hours, timeout, shell-only override, fail-closed restore)
- Phase references updated from 1C to 1D in comments/logs

### Pilot run: --limit 5

| Metric | Value |
|--------|-------|
| Symbols classified | 5 (ACH, ACNT, ACTU, ADNT, ADUR) |
| Wall time | **7 min 41 sec** (461s) |
| Timeout cap | 10 min |
| Under timeout? | YES — 2 min 19 sec margin |
| Per-symbol avg | ~91s |
| gemma3-overnight VRAM | 13.64 GB GPU + 4.79 GB CPU |
| Pilot exit code | 0 |
| qwen3 restore | ok |
| nomic restore | ok |

### Post-run validation: ALL PASSED
- GPU: qwen3:14b (9.4 GB) + nomic-embed-text (0.54 GB) — matches pre-swap
- ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true
- Holdings: $1,192,663
- No cron entries added
- No persistent .env routing changes
- LOCAL_LLM_MODEL=qwen3:14b (unchanged)
- STANDARD, REALTIME, EMBEDDING, MEDIA_CONTENT, CRITICAL_CLOUD: not set (unchanged)

### Scaling ceiling
- --limit 5 at 7m41s is the practical max under 10m timeout
- --limit 7 would extrapolate to ~10m47s (TIMEOUT risk)

### Recommendation
Phase 1 should stop at manual --limit 5. Before scheduling a nightly cron:
1. Add Ollama queue drain check before GPU swap
2. Add model-swap lock to pause other LLM callers during gemma window
3. Schedule at 2-3 AM when cron traffic is lowest
4. Require operator approval before enabling cron

### What was NOT changed
- No cron entries added or modified
- No .env routing changes
- No changes to STANDARD, REALTIME, EMBEDDING, MEDIA_CONTENT, CRITICAL_CLOUD
- No broker, holdings, or execution changes
- Full report: `docs/v4_1_phase1d_limit5_report.md`

## Phase 1H — Daily Deep Overnight LLM Window — 2026-05-12 20:40 ET

### Summary
Enabled a daily 23:00–03:00 deep overnight LLM processing window using
gemma3-overnight to process a prioritized queue of high-value jobs.

### Files created
- `scripts/create_deep_overnight_llm_queue.py` — schema creation (safe idempotent)
- `scripts/build_deep_overnight_llm_queue.py` — queue builder with priority scoring
- `scripts/run_deep_overnight_llm_queue.py` — queue runner with time budget/hard stop
- `scripts/run_deep_overnight_llm_window.sh` — daily wrapper (lock, safety, swap, restore)
- `docs/v4_1_phase1h_daily_deep_overnight_llm_window.md` — full Phase 1H documentation
- `docs/v4_1_discovery/phase1h_2300_0300_schedule_audit.md` — schedule conflict audit
- `docs/v4_1_discovery/crontab_pre_phase1h.txt` — crontab backup before changes
- `docs/v4_1_discovery/crontab_post_phase1h.txt` — crontab after changes

### Schedule enabled
```
0 23 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && ./scripts/run_deep_overnight_llm_window.sh >> logs/deep_overnight_llm_window.log 2>&1
```

### Cron changes
1. Added daily 23:00 deep window entry
2. Modified `*/5 20-23` watchlist agent entry — added deep-llm-lock check
3. Modified `*/5 0-5` watchlist agent entry — added deep-llm-lock check

### Queue schema
- `deep_overnight_llm_queue` — created with 7 indexes
- `deep_overnight_llm_results` — created with 3 indexes
- Initial queue: 100 items (46 P0, 32 P1, 8 P2, 14 P3)
- Job types queued: strategy_classification (48), closed_trade_review (34), manual_journal_review (18)

### Dry-run results
- Queue builder: 100 jobs across 3 types, priority scoring correct
- Queue runner: 5 jobs shown in priority order
- Deep wrapper: Window gate, safety gates, lock, and dry-run exit all correct

### Safety validation
- ALPACA_MODE=paper ✓
- LLM_DISABLE_LIVE_EXECUTION=true ✓
- Holdings guard: $1,192,934 ✓
- qwen3:14b resident (9.4 GB) ✓
- nomic-embed-text resident (0.54 GB) ✓
- Ollama alive ✓
- No persistent routing changes ✓
- No broker/holdings/execution changes ✓

### Rollback command
```bash
# Disable nightly schedule
crontab -l | grep -v "run_deep_overnight_llm_window" | crontab -
# Or restore from backup:
crontab docs/v4_1_discovery/crontab_pre_phase1h.txt
```

### Next step recommendation
- Monitor first nightly run (tonight at 23:00)
- Check `logs/deep_overnight_llm_window.log` after 03:15 for completion
- Verify qwen3:14b/nomic-embed-text restoration after window
- After 7 consecutive successful nights, consider Phase 2 readiness

## Phase 1H Capacity Tune — 2026-05-12 21:00 ET

### Summary
Raised nightly deep queue target from conservative 120 (unrestricted) to an
operator-tuned 70 default / 75 hard max based on 4-hour window throughput analysis.

### Rationale
- Phase 1D: ~91s per symbol, ~2–3 min per job with overhead
- 4-hour window: ~80–120 jobs theoretical capacity
- Operational target: 70 to preserve ~30 min restore/reporting buffer
- Hard max: 75 (override: `--allow-over-75`, not recommended)
- Time cap always beats count cap — 03:00 hard stop is non-negotiable
- P0/P1 journal/closed-trade jobs share the budget (30–45 min reserved)

### Files changed
- `scripts/run_deep_overnight_llm_window.sh` — MAX_JOBS 120→70, HARD_MAX_JOBS=75, --allow-over-75
- `scripts/run_deep_overnight_llm_queue.py` — --limit default 120→70
- `docs/v4_1_phase1h_daily_deep_overnight_llm_window.md` — capacity policy updated
- `docs/v4_1_deployment_log.md` — this entry

### What was NOT changed
- No cron/timer changes
- No .env changes
- No routing changes (STANDARD, BATCH_OVERNIGHT, EMBEDDING, etc.)
- No broker, holdings, execution, or trading behavior changes
- 03:00 hard stop and 03:15 restore deadline unchanged
- All safety gates preserved

## Phase 1H Expansion — 5 New Job Types — 2026-05-12 22:30 ET

### New job types added
- `rag_content_curation`: nightly P1, up to 20 items. gemma3 128K context re-evaluates pending/low-quality news and YouTube for novelty. Writes verdict back to source table.
- `risk_synthesis`: nightly P0, single job. Portfolio-level risk narrative saved to `risk_synthesis_results`, feeds morning brief.
- `recovery_watch_review`: Tue/Thu only P1, up to 12 items. Thesis validity for `stopped_out_watch` items (THESIS_INTACT/INVALIDATED/NEEDS_MORE_DATA).
- `covered_call_scoring`: Sunday only P1, up to 15 items. Strike/yield scoring for `aegis_covered_call_candidates`.
- `weekly_behavioral_review`: Sunday only P2, gated at 20+ closed trades. Currently inactive (4 closed trades).

### New tables/columns
- `risk_synthesis_results` (new table)
- `deep_overnight_llm_results`: +10 new columns (source_table, source_id, curation_verdict, curation_weight, risk_narrative, reentry_verdict, cc_verdict, cc_strike_target, cc_yield_estimate, behavioral_patterns)
- `news_articles`: +3 deep_curation columns
- `youtube_transcripts`: +3 deep_curation columns
- `deep_overnight_llm_queue`: +1 source_id column

### Budget impact
- Weeknights (Tue/Thu): +31 jobs (1 risk + 20 RAG + 10 recovery)
- Weeknights (Mon/Wed/Fri): +21 jobs (1 risk + 20 RAG)
- Sundays: +21-36 jobs (1 risk + 20 RAG + 0-15 CC + 0-1 behavioral)
- Original 70-job cap was too low to accommodate — raised to 100 (see fix below)

### Morning brief integration
- `aegis_morning_brief_delivery.py` now surfaces overnight risk synthesis priority action

### What was NOT changed
- No cron/timer changes
- No .env changes
- No routing changes
- No broker, holdings, execution, or trading behavior changes
- Existing job type handlers unchanged

## Fix: Deep Overnight Queue — Job Cap 70→100 — 2026-05-13 08:00 ET

### Root cause
risk_synthesis (P0, score=100) and all other Phase 1H expansion job types never
ran despite being correctly queued. The nightly cap of 70 jobs was entirely consumed
by higher-scored original types: journal reviews (170), strategy classifications
(130), closed trade reviews (115-125). Expansion types were jobs #71+.

### Observed throughput
Last night processed 70 jobs in 47 minutes (23:00–23:47). Average ~40 sec/job,
not the estimated 2.5 min/job from Phase 1D. The 240-minute budget had 193 minutes
of unused headroom.

### Fix
- `run_deep_overnight_llm_window.sh`: MAX_JOBS 70→100, HARD_MAX_JOBS 75→100
- `run_deep_overnight_llm_queue.py`: default --limit 70→100, added --force-job-types flag
- `v4_1_phase1h_daily_deep_overnight_llm_window.md`: capacity policy updated

### Smoke test
- Dry run: `--force-job-types risk_synthesis,rag_content_curation --limit 3` found all 3 jobs
- Live run: risk_synthesis dispatched correctly, timed out (expected — gemma not loaded during daytime)
- Job returned to pending with attempt_count=1, will succeed at tonight's 23:00 window

## Fix: .env Quoting + Direct Parser Audit — 2026-05-13 08:20 ET

### Root cause
`FINVIZ_USER_AGENT` and `FINVIZ_COOKIE` contained unquoted parentheses, spaces,
and semicolons — characters that break `bash source .env`. Additionally, 5 Python
scripts with direct `.env` file parsers (using `split("=",1)[1].strip()`) did not
strip quotes, causing them to send literal quote characters in HTTP Cookie headers.

### .env fix
- `FINVIZ_USER_AGENT`: wrapped in single quotes (has `(Windows NT 10.0; Win64; x64)`)
- `FINVIZ_COOKIE`: wrapped in single quotes (has `(Eastern Daylight Time)`)
- python-dotenv (used by 80+ scripts) correctly strips quotes — no impact
- Backup preserved at `.env.backup.20260513_082028`

### Parser fixes (5 scripts)
All direct `.env` readers that handle Finviz credentials now `.strip("'\"")`

| Script | Issue | Impact |
|--------|-------|--------|
| `system_preflight_check.py` | `.strip()` only | Finviz CSV check was FAILING (got HTML login page) |
| `credential_monitor.py` | `.strip()` only | Reported 102KB "ok" (was actually HTML, not CSV) |
| `finviz_validator.py` | `.strip()` only | Would send quoted cookie to Finviz |
| `finviz_health_check.py` | `.strip('"')` only | Would not strip single quotes |
| `finviz_enrichment.py` | `_load_env` did `.strip('"')` | Would not strip single quotes in `os.environ` |

### Verification (all pass)
- Cookie auth: health_check 1,370 rows, credential_monitor 27KB CSV, preflight CSV+tickers, validator 2/2 screeners, screener_runner 20 screeners
- API token auth: finviz_news (200, 36KB), finviz_enrichment (6 views AAPL/MSFT/TSLA)
- Holdings guard: $1,192,258 ✓

## Phase 0 Migration — LLM Hardcoding Audit — 2026-05-13

### Discovery results
- 25+ hardcoded model references across scripts (excluding config hub, tests, validators)
- 18 direct Ollama callers bypassing local_llm.py
- 15+ direct Anthropic callers (most are CRITICAL_CLOUD — correct, not migrated)

### Scripts migrated to local_llm.generate() with process_type routing

| Script | Process Type | Previous Pattern | Notes |
|--------|-------------|-----------------|-------|
| `morning_digest.py` | STANDARD | Direct urllib /api/chat | 2 narrative calls |
| `portfolio_news.py` | STANDARD | Direct requests.post /api/chat | ~31 scoring calls/run |
| `scalp_critic_agent.py` | STANDARD | Direct urllib /api/chat | ~10-50 critique calls |
| `stop_decision_brief.py` | STANDARD | Direct requests.post /api/chat | 1 call per stop alert |
| `post_trade_thesis_reviewer.py` | STANDARD | Direct urllib /api/generate (old) | 1 call per closed trade |
| `catalyst_intelligence.py` | STANDARD | scoring._ollama_serialized fallback | ~50 scoring calls |
| `scoring.py` | STANDARD | Threading lock + direct urllib | ~50-80 calls, was serialization hub |

### What changed
- All 7 scripts now call `local_llm.generate(prompt, caller=X, process_type="STANDARD")`
- All calls now go through the toll gate (fcntl flock), audit logging, and cloud fallback chain
- No model names hardcoded in any migrated script
- `scoring._ollama_serialized()` preserved as function signature but now delegates to local_llm

### What was NOT changed
- No .env changes, no model routing changes (still qwen3:14b for STANDARD)
- `aegis_synthesis.py`, `process_watchlist_agent_jobs.py`, `multi_strategy_classifier.py` — NOT migrated (complex, pilot separately)
- `multi_tier_trade_reviewer.py`, `portfolio_orchestrator.py` — NOT migrated (complex dispatch)
- Direct Anthropic callers (CRITICAL_CLOUD scripts) — correct, not migrated
- No broker, holdings, execution, or trading behavior changes

## LLM Queue Manager Page + Enhanced Ops Console — 2026-05-13 08:30 ET

### Summary
Built `/v2/ops` LLM Queue tab (5 sub-tabs: overview, pending, completed, failed,
schedule & controls) with 9 new API endpoints. Enhanced Ops Console with LLM routing
audit table and cron health grid. Added Friday 4PM extended cron (400 jobs).

### New API endpoints
- `GET /api/v2/queue/summary` — pending/done/cap/budget breakdown
- `GET /api/v2/queue/pending` — 300 pending jobs sorted by priority
- `GET /api/v2/queue/completed` — last 24h completions with duration stats
- `GET /api/v2/queue/failed` — failed/error jobs
- `POST /api/v2/queue/boost` — bump priority_score
- `POST /api/v2/queue/cancel` — cancel pending job
- `POST /api/v2/queue/retry` — reset failed job to pending
- `GET /api/v2/ops/llm-audit` — last 100 LLM routing audit entries
- `GET /api/v2/ops/cron-health` — 13 scheduled crons from pipeline_schedule

### Frontend files
- `LLMQueue.tsx` — new page with budget bar, job type breakdown, filters, actions
- `Ops.tsx` — added LLM Routing Audit and Cron Health sections
- `OpsHub.tsx` — added LLM Queue tab

### Cron addition
```
0 16 * * 5  flock -n ... run_deep_overnight_llm_window.sh --force-window --max-jobs 400
```

## Event-Driven Requeue Engine — 2026-05-13 09:15 ET

### Summary
Added `_requeue_on_events()` to `build_deep_overnight_llm_queue.py`. Detects material
changes since last gemma3 analysis and fills unused nightly slots.

### Triggers
| Trigger | Job Type | Score | Condition |
|---------|----------|-------|-----------|
| Staleness | strategy_classification | 75+10 | >14d since last run |
| Price move | strategy_classification | 75+10-20 | >5% week move |
| RVOL spike | strategy_classification | 75+15 | RVOL >5x |
| Earnings | strategy_classification | 75+25 | Earnings within 14d |
| Price recovery | recovery_watch_review | 95 | Price within 2% of exit |
| CC price move | covered_call_scoring | 85 | >3% week move |

### Dry-run results
7 requeues: 5 strategy (AVAV, RKLB, KTOS, ARKG, IRDM) + 2 CC (PFLT, ARKG)

## Strategy Diversity Fix — 2026-05-13 09:30 ET

### Problem
12 of 21 strategies had 0 proposals. Momentum screeners starved all other types.

### Fix
- 4 new Finviz screeners: income_candidates, oversold_reversion, sector_leaders, defense_momentum
- New job type: `strategy_opportunity_scan` — Sunday nights, gemma3 evaluates top 40
  watchlist symbols against 11 underutilized strategies

## gemma3 Calibration Loop — 2026-05-13 09:45 ET

### Summary
Calibration layer grading gemma3 overnight predictions against actual outcomes.

### New assets
- `gemma3_calibration_events` table + `gemma3_accuracy_by_job_type` view
- `scripts/gemma3_calibration_scorer.py` — seeds PENDING events, grades outcomes
- `GET /api/v2/queue/calibration` endpoint
- Cron: `30 21 * * 1-5` nightly scoring
- 41 strategy_classification events seeded, grading begins as trades close

## Strategy-Aware Overnight Analysis — 2026-05-13 10:30 ET

### Summary
3 new overnight job types, strategy-aware incubator grading, 7 new screeners,
16 static symbols. All 20 strategies now have a path into the proposal pipeline.

### Part A — 3 new overnight job types
| Job Type | Day | Strategy Focus |
|----------|-----|----------------|
| `income_strategy_scan` | Monday | income_add, dividend_growth_compounder, high_yield_income_bdc, covered_call_income |
| `growth_strategy_scan` | Wednesday | core_growth_compounder, sector_rotation, defense_thesis |
| `reversion_strategy_scan` | Saturday | swing_trade retracement, bond_income, cash_or_stable |

### Part B — Strategy-aware incubator grader
- `incubator_llm_screener.py` now detects `strategy_id` on each symbol
- 4 strategy groups: INCOME, GROWTH, REVERSION, MOMENTUM (default)
- 3 new prompt builders: income (no RVOL penalty), growth (EPS/sector focus), reversion (rewards oversold)
- Existing momentum grader completely unchanged

### Part C — Screener universes (27 total)
- 3 new Finviz screeners: dividend_aristocrats, high_yield_bdc_reit, quality_compounders
- 16 static symbols in watchlist_items: bond ETFs (BND, TLT, IEF, SHY, etc.), BDCs (ARCC, MAIN, HTGC), REITs (O, STAG), cash (SGOV, BIL, SHV, USFR)

### Problem solved
Before: 10 of 19 strategies had zero proposals (income, defense, bond, recovery, etc.)
After: all strategies have source universe, strategy-appropriate screening, overnight LLM analysis

## Fix: paper_trades lifecycle_state Never Transitioning to 'closed' — 2026-05-13 11:00 ET

### Root cause
5 of 6 paper trade close paths set `status='closed'` but missed
`lifecycle_state='closed'`. Only `open_trade_monitor.py` (stop/target hit auto-close)
set it correctly. The Automated Trade Journal page showed 0 closed trades and 0% win
rate because it filtered on `status IN ('open','closed')` — which found the rows,
but the lifecycle_state inconsistency caused downstream issues.

### Close paths fixed (added `lifecycle_state='closed'`)
| Script | Close Path |
|--------|-----------|
| `paper_trade_monitor.py:188` | Target hit fallback |
| `open_trade_monitor.py:406` | Critical news auto-close |
| `paper_trade_closer.py:232` | Manual/scheduled close |
| `paper_trade_logger.py:376` | Telegram-triggered close |
| `alpaca_paper_adapter.py:135` | Alpaca sync position-gone |

`open_trade_monitor.py:183` (stop/target auto-close) already correct — no change needed.

### Migration
- 5 rows fixed: `status='closed'` → `lifecycle_state='closed'`, outcome_verdict from pnl
- 12 rows fixed: `status='cancelled'` → `lifecycle_state='cancelled'`
- INFU remains correctly `lifecycle_state='open'` (live position)

### XMTR clarification
The expected +$134 XMTR win is in the `trade_closed` table (historical Schwab IRA),
not `paper_trades` (Alpaca paper). The XMTR paper trade was a phantom that never
filled — correctly cleaned up as BREAKEVEN.

### After fix
Automated Journal: 1 open, 5 closed, 2 losses, $-30.19 PnL (was 0/0/0 before)

## Proposal Pipeline — Auto-Expiry, Strategy Gate, Frequency — 2026-05-13 11:20 ET

### Summary
Proposal pipeline was stale: 7 PENDING proposals with no operator action for 3+ days,
promoter had no cron entry, Finviz screener ran only 2x/day.

### Auto-expiry
Added `_auto_expire_stale_proposals()` to `incubator_proposal_promoter.py`:
- PENDING >3 days no action → EXPIRED
- Past `expires_at` → EXPIRED
- PENDING >2 days AND price drift >8% → EXPIRED
- Runs before every promotion cycle. First run expired 5 stale proposals.

### Strategy-aware gate
- Global ceiling: 20 PENDING proposals max (was unlimited)
- Per-strategy: max 5 per strategy_id
- `expiry_reason` column added to `paper_trade_proposals`

### Frequency increase
- Finviz screener: 2x/day → 7x/day (7,8,10,12,14,16,18 weekdays, flock-protected)
- Incubator promoter: no cron → 5x/day (9,11,13,15,17 weekdays)

### Proposals API enhancement
- `summary.by_strategy`: per-strategy proposal count, win rate, PnL, trade count
- Per-proposal: `strategy_win_rate`, `strategy_total_pnl`, `strategy_trade_count`, `age_hours`

## Proposal Operator UX + Approval Re-Verification — 2026-05-13 12:00 ET

### Proposals API — operator_verdict
Every proposal now includes computed operator-facing fields:
- `operator_verdict`: READY / NEEDS_REVIEW / STALE_QUOTE / ENTRY_MISSED
- `operator_verdict_color`: green / yellow / orange / red
- `operator_verdict_reason`: plain English explanation
- `age_hours`, `age_display` ("2d 3h ago"), `age_color`
- `sort_order`: READY first → NEEDS_REVIEW → STALE_QUOTE → ENTRY_MISSED
- Summary: `ready_count`, `needs_review_count`, `stale_count`, `entry_missed_count`
- `pipeline_health_message`: surfaces when no proposals are READY

### Approval re-verification (check #7)
Added `_verify_live_strategy_conditions()` to `approval_revalidator.py`:

| Check | Condition | Severity |
|-------|-----------|----------|
| RSI overbought | >80 momentum strategies | **BLOCK** |
| RVOL collapsed | <1.5x momentum strategies | **BLOCK** |
| Catalyst freshness | time-sensitive >48h old | Warning |
| VWAP extended | >5% above for intraday | Warning |
| Negative news | >2 articles since creation | Warning |

`condition_snapshot` (RSI, RVOL, timestamp) written to approval audit trail.

### PaperProposals.tsx — complete card rebuild (2053 → 932 lines)
6-row card layout — operator decision in 5 seconds, no clicks required:

| Row | Content |
|-----|---------|
| 1. Status Bar | Colored verdict badge + symbol + strategy + grade + age |
| 2. Key Numbers | Entry / Current (±drift%) / Stop / Target — always visible |
| 3. Trade Metrics | R:R / Risk $ / Shares / RVOL / RSI — color-coded |
| 4. Timestamps | Created / Price check / AI review / Risk gate — color-coded |
| 5. Thesis | One-line from agent narrative (max 160 chars) |
| 6. Actions | Refresh Price / Check Execution / AI Review / Approve / Reject |

API additions:
- Specific verdict reasons: "Risk gate not checked — click Check Execution (10 sec)"
- `live_price_timestamp_display`, `ai_review_completed_at_display`, `risk_gate_display`
- `current_price_display`, `price_drift_display`, `price_drift_color`

Removed: 8 pipeline badges, packet progress bar, tab bar, support/reject boxes,
LLM status tag — all moved to collapsed Full Details drawer.
1121 lines of old card code removed.

## Fix: Stop Breach Auto-Block + Risk Gate Conn — 2026-05-13 13:00 ET

### Stop breach auto-block
- If `current_price <= proposed_stop`, verdict = `BLOCKED` (red, approve disabled)
- Example: GCTS at $1.88 with stop $1.88 → "STOP BREACHED — price $1.88 at or below stop"
- Added to auto-expiry: stop-breached proposals auto-expire

### Specific verdict reasons
Verified working after server restart. Maps generic "Review data completeness" to:
- `risk_gate_result` is None → "Risk gate not checked — click Check Execution (10 sec)"
- `llm_review_status` NOT_REQUESTED → "AI not reviewed — click Run AI Review (30 sec)"
- stop breached → "STOP BREACHED — price $X at or below stop $Y"

### Orchestrator risk_gate fix
`trade_ai_orchestrator.py` line 631: `RiskGate(conn)` used undefined bare `conn`.
Replaced with `_rg_get_conn()` from `db_adapter`. Was causing risk_gate stage to
fail silently on every orchestrator run (12PM, 2PM, 4PM, 5:30PM).

## Fix: Proposal Pipeline Quality — 2026-05-13 13:30 ET

### Problems found (live browser audit)
| Issue | Root Cause |
|-------|-----------|
| Current price $-- on fresh proposals | `current_price` NULL, promoter doesn't set it |
| RSI missing | API didn't read from `ticker_snapshot_daily` |
| Generic thesis ("GCTS is a recovery_watch proposal") | No data-driven fallback |
| Same symbol ×4 dominating page | Per-symbol cap without strategy group awareness |
| OSS symbols failing with no_price | No penny stock / volume filter |

### Fixes applied
- **Price fallback chain**: API tries proposal → snapshot → scan price. RSI/RVOL
  also sourced from `ticker_snapshot_daily` when missing on proposal.
- **thesis_display**: Built from data when setup_thesis is generic:
  "GCTS: Recovery Watch | RVOL 8.7x | Score 40pts | Catalyst verified | RSI 65"
- **Strategy-group dedup**: Max 1 proposal per symbol per group
  (MOMENTUM/INCOME/GROWTH/REVERSION), max 2 total per symbol.
  Prevents GCTS×4 domination.
- **Penny stock filter**: Skip symbols with price <$1.00.
- **Multi-strategy warning**: API returns `multi_strategy_symbols` in summary.
  Frontend shows header warning + per-card "+1 other strategy" badge.
- **Stop breach auto-expiry**: Added rule 4 to promoter auto-expiry.

## RSI Overbought Auto-Block at Proposal Promotion — 2026-05-13 14:15 ET

### Promoter RSI gate (`_check_rsi_gate`)
Blocks at promotion time — overbought symbols never reach the proposals page:

| Strategy Group | RSI Threshold | Action |
|---------------|---------------|--------|
| Momentum (scalp, gap_and_go, earnings, speculative) | >= 80 | BLOCKED |
| Swing (breakout, swing_trade, sector_rotation) | >= 75 | BLOCKED |
| Any non-exempt | >= 85 | BLOCKED |
| Income, recovery, bond, cash | N/A | **Exempt** |

### Auto-expiry Rule 5
RSI >= 80 auto-expires PENDING proposals on every promoter cycle.
LIFE (RSI 93.89) expired immediately on first run.

### API fields
- `rsi_flag`: OVERBOUGHT/ELEVATED/OVERSOLD/null
- `rsi_flag_blocks_approval`: true when RSI blocks for this strategy
- Overrides `operator_verdict` to BLOCKED with red background

### Frontend
Row 3 RSI display: red "RSI 94 OVERBOUGHT" badge when >=80, orange "RSI 73 ↑" when >=70.

## Fix: Three Pipeline Bugs Causing RUN_FAILED — 2026-05-13 14:30 ET

### Bug 1: finviz_ingestion — No screener URLs for PM run_labels
`screeners.yaml` only defined run_windows for 0400/0700/0900/1000. The PM crons
(1200/1400/1600/1730) passed run_labels that had no entry, causing `pick_active_screeners`
to return empty → 0 tickers → RUN_FAILED.
**Fix**: Added 5 PM run_windows (1200/1400/1600/1730/test-fix) mapping to
prime_setups + watchlist_setups screeners.

### Bug 2: symbol_enrichment — `get_connection` import
`trade_ai_orchestrator.py:375` imports `from db_adapter import get_connection` but
`db_adapter.py` only exported `_get_conn`. The import failed on every run.
**Fix**: Added `get_connection = _get_conn` alias in `db_adapter.py`.

### Bug 3: risk_gate — `conn` not defined (confirmed already fixed)
Already fixed in commit 74a8652. The 12PM log error was from the pre-fix run.

## risk_gate Safe Float + Pipeline Manual Test — 2026-05-13 15:00 ET

### risk_gate float fix
`risk_gate.py` had 7 bare `float()` calls crashing on JSONB dict values from
trade plan data. Added `_safe_float()` helper. Manual test confirmed:
`risk_gate: 3 approved 3 flagged, 0 errors` (was 5 exceptions before).

### Manual pipeline test (run_label 1400)
Confirmed all three prior bugs fixed:
- `finviz_ingestion`: 15 tickers | 2 screeners (was 0/RUN_FAILED)
- `risk_gate`: 3 approved 3 flagged (was `name 'conn' is not defined`)
- `symbol_enrichment`: no import errors (was `get_connection` not found)

### GCTS trade approval audit (13:12 ET)
Full flow verified end-to-end:
1. Proposal #69 approved → `APPROVED_FOR_PAPER_TEST`, `ELIGIBLE`
2. Paper trade #20 created → `opened_via=proposal_approved`
3. Alpaca market buy 1,875 shares submitted → filled at $1.49
4. Position live: GCTS 1,875 shares, INFU 357 shares (2 positions total)

Write-back gaps fixed by operator:
- `broker_status`, `broker_order_id`, `submitted_at`, `filled_at` populated
- Lifecycle events and curation hooks verified

## Fix: Stop Recalculation on Fill + Pending→Open Promotion — 2026-05-13 15:30 ET

### Problem: GCTS position running with no stop loss
GCTS proposal had `proposed_entry=$1.60, proposed_stop=$1.52`. Market order filled at
$1.49 (7% below proposed entry). Stop of $1.52 was carried unchanged, meaning stop >
entry. Alpaca correctly rejected: "stop price must be less than current price ($1.48)".
**GCTS ran unprotected until manually caught in audit.**

### Immediate fix
Stop manually placed at $1.42 (5% below $1.49 fill) on Alpaca + DB updated.

### Code fixes in `alpaca_paper_adapter.py`

**1. Stop recalculation on fill** (`submit_entry`):
When market order fills below proposed_entry and stop > fill price, recalculates
`effective_stop = fill_price * 0.95`. Applied to both Alpaca stop order placement
and paper_trades DB insert.

**2. Pending→open promotion** (`sync_positions`):
Detects Alpaca-filled trades stuck at `status='pending'` (adapter created row but
didn't update status on fill). Promotes to `open` with correct fill price. Also
recalculates stop if above fill.

**3. DB insert uses effective_stop**:
INSERT now writes recalculated `effective_stop` instead of original `stop_price`,
and computes `dollar_risk` from actual fill-to-stop distance.

### Safety chain update
Paper trading safety chain now: RSI gate → risk gate → approval revalidation →
market hours → **fill verification + stop recalculation** → atomic stop → R-multiple
trailing → **time stop** → phantom detection → critical news auto-close → reconciliation

## TIME STOP Auto-Close — 2026-05-13 16:00 ET

Added to `open_trade_monitor.py`. Checks hold duration against per-strategy max on
every 15-min monitoring cycle. Uses same close path as stop_hit (Alpaca liquidate +
DB update + on_paper_trade_closed hook).

| Strategy | Max Hold | Note |
|----------|----------|------|
| momentum_scalp | 0d (intraday) | Already enforced by market hours |
| gap_and_go | 1d | |
| earnings_catalyst | 7d | |
| swing_breakout, swing_trade, speculative_growth | 21d | |
| sector_rotation, defense_thesis | 56d (8 weeks) | |
| Income, recovery, bond, cash strategies | No limit | Hold indefinitely |

Verdict based on P&L at close: WIN if profitable, LOSS if not, BREAKEVEN if flat.
Telegram: "⏰ TIME STOP: SYMBOL closed after Nd (max: Md for strategy). P&L: $X"

INFU was manually closed today (+$67.83 WIN) after 6 STALE_TRADE alerts — the time
stop would have caught it at day 21 automatically.

## Paper Trades Data Audit — 2026-05-13 16:30 ET

### Problems found
- R-multiples wrong on 5 closed trades (phantom trades had stale R values)
- INFU #21: new Alpaca position created by adapter sync after close — real trade, needed stop/target in DB
- BLBD #15: cancelled row had -$449.92 PnL (proposal entry, never actually filled). Real loss is #16 at -$14.80.

### Fixes (direct DB updates, Alpaca = source of truth)
| Trade | Fix |
|-------|-----|
| XMTR #3 | R 1.3→0 (phantom, pnl=0) |
| EVC #4 | R -1.95→0 (phantom, pnl=0) |
| FLYW #12 | R 7.0→-0.82 (recalculated from pnl -$15.39) |
| FLYW #19 | R→0 (phantom, pnl=0) |
| BLBD #16 | R→-0.05 (recalculated from pnl -$14.80) |
| INFU #21 | stop=$7.97 (matches Alpaca), target=$9.23 |

### Correct state after audit
- Open: 2 (GCTS @ $1.49, INFU @ $8.61)
- Closed: 6 (1 WIN, 2 LOSS, 3 BREAKEVEN)
- Realized P&L: +$37.64
- Principle confirmed: **Alpaca is source of truth**, DB follows

## PM Crons --allow-underfilled + risk_gate Dict Keys — 2026-05-13 17:00 ET

- All 4 PM crons (1200/1400/1600/1730) now pass `--allow-underfilled`
- `risk_gate._safe_float()` expanded to search `price` and `score` dict keys

## Paper Trades Data Integrity Guards — 2026-05-13 17:15 ET

### _fix_integrity_issues() in paper_trade_monitor.py
Runs at start of every 5-min cycle before position processing:
1. Auto-cancels open records never filled after 30min
2. Closes phantom DB records not on Alpaca
3. Fixes stuck closed_at records still marked open

### Journal API integrity
- Filtered: excludes unfilled open records (`filled_at IS NULL AND broker_status != 'filled'`)
- `_journal_integrity_warnings()`: detects unfilled opens, missing verdicts, duplicate symbols
- Warnings returned in API response as `integrity_warnings`

## Architectural Fix: Broker as Source of Truth — 2026-05-13 17:30 ET

**Principle**: Active broker (currently Alpaca paper) is sole source of truth for trades.
Database is a mirror of broker state — nothing written until broker confirms fill.

### Changes to alpaca_paper_adapter.py

| Component | Before | After |
|-----------|--------|-------|
| Unfilled limit orders | Created paper_trades row (`status='pending'`) | No row created. Returns `{status:'pending'}` — sync detects fill later |
| Filled market orders | INSERT missing `filled_at`, `submitted_at` | Both set to `NOW()` |
| Sync-detected positions | INSERT missing `lifecycle_state`, `broker_status`, `filled_at` | All set: `open`, `filled`, `NOW()` |

### broker_confirmed column
`ALTER TABLE paper_trades ADD COLUMN broker_confirmed BOOLEAN GENERATED ALWAYS AS (filled_at IS NOT NULL) STORED`
- TRUE = broker confirmed fill. FALSE = phantom/unconfirmed.
- Used by journal API and monitor integrity checks.
- Historical trades backfilled: INFU #13 and BLBD #16 got `filled_at` from `entry_time`.

## Fix: Win Rate Phantom Dilution + Reconciler Broker Exit — 2026-05-13 18:00 ET

### Win rate was 17% — should be 33%
3 phantom breakeven trades ($0 PnL, never filled on Alpaca) were diluting the win rate.
Journal API now calculates from `_real_closed` (trades with non-zero PnL only):
- Before: 1W / 6 total = 16.7%
- After: 1W / 3 real trades = 33.3%
- `real_trade_count` added to API summary

### Reconciler reads exit from broker order history
`detect_closed_positions` now fetches actual sell order `filled_avg_price` and `filled_at`
from broker instead of fabricating exit price from current market data. Computes real PnL
and sets correct `outcome_verdict` from broker-confirmed values.

## Fix: paper-journal Endpoint + Empty Positions API Guard — 2026-05-13 18:30 ET

### paper-journal win rate was 14% (should be 33%)
Frontend reads `/api/v2/paper-journal` (not `automated-trade-journal`). This endpoint
counted ALL closed trades including $0 phantom breakevens in win rate denominator.
Fixed: `real_closed` excludes zero-PnL trades. Now 1W/3 real = 33%.

### GCTS repeatedly phantom-closed
`detect_closed_positions` marked GCTS as closed whenever Alpaca positions API returned
empty (API hiccup, not real close). GCTS reopened 3 times during this session.
**Root cause fix**: if positions API returns empty while DB has open trades, skip close
detection entirely — log warning instead of closing everything.

### Final verified state (Alpaca = DB = API)
- Open: 2 (GCTS 1875sh @ $1.49, INFU 357sh @ $8.61) — both on Alpaca with stops
- Closed: 6 (3 real: 1W +$67.83, 2L -$30.19; 3 phantom breakevens)
- Win Rate: 33% (real trades only)
- Realized P&L: +$37.64

## Data-Enriched LLM Prompts + Context Engine — 2026-05-13 19:00 ET

### Root cause: hallucination from data-sparse prompts
gemma3 received "Review closed trade for SPRC. Trade ID: 158. Triggers: loss" — no
prices, P&L, stop usage, or history. It invented "third instance in last quarter"
(actually 2 losses, not 3). Every prompt that passes only IDs/triggers risks this.

### Fix: `llm_context_engine.py` — centralized data context for all LLM calls
Any script can now import `build_context(symbol, context_type, ...)` to get
680–1,213 chars of actual DB data + anti-hallucination block.

| Context Type | Data Included | Chars |
|-------------|---------------|-------|
| `strategy_classification` | RSI, RVOL, price, sector, beta, P/E, SMA50/200, trade history | 680 |
| `trade_review` | Entry/exit prices, P&L, stop, hold days, R-multiple, past symbol trades | 924 |
| `risk_synthesis` | All portfolio positions with market values, %, day change | 1213 |
| `recovery_watch` | Exit price, days out, recovery %, thesis at exit, current RSI | 942 |
| `covered_call` | Price, RSI, beta, div yield, RVOL, Aegis verdict | 775 |
| `proposal` | Entry/stop/target, R:R, catalyst, score, current snapshot | 1015 |

### Overnight queue prompts enriched (inline)
All 6 core job types in `run_deep_overnight_llm_queue.py` now query actual data:
- `closed_trade_review`: entry/exit/P&L/stop/hold + past symbol history
- `strategy_classification`: RSI/RVOL/price/sector + current classification
- `proposal_review`: entry/stop/target/R:R/catalyst + current RSI/RVOL
- `recovery_watch_review`: exit price/current/days out/recovery %
- `covered_call_scoring`: price/RSI/beta/RVOL/Aegis verdict
- `risk_synthesis`: already had portfolio context (no change)

### 129 jobs requeued for re-run with enriched prompts
All previously-completed jobs (79 strategy + 32 trade review + 17 journal)
reset to pending with `requeue_enriched_prompt` reason code. Will re-run
tonight with full data context.

### Scripts already data-rich (no migration needed)
- `process_watchlist_agent_jobs.py` — loads scan intel, RAG, sentiment, research
- `stop_decision_brief.py` — holdings, enrichment, stops, news, technicals
- `scoring.py` — actual headlines for catalyst scoring
- `incubator_llm_screener.py` — 4 strategy-specific builders with inline data

### Anti-hallucination block on all prompts
"Use ONLY the data above. Do NOT invent, estimate, or assume numbers not
explicitly provided. Do NOT claim patterns unless the data supports them."

## Time Stop Fixes + Strategy ID Cleanup — 2026-05-13 19:30 ET

### GCTS closed after 1 hour by time_stop_max_0d
momentum_scalp had `MAX_HOLD_DAYS=0`, which fired on the first 15-min check
after entry. Correct behavior for intraday — but wrong strategy was on the trade.

### Fixes
- Intraday strategies (momentum_scalp, gap_and_go) now close at 3:45 PM ET,
  not by day count. Moved to `INTRADAY_STRATEGIES` set.
- Time stop dedup: 30-min window prevents repeated close attempts
- Removed `'momentum_scalp'` hardcoded default in adapter sync INSERT
- `max_per_symbol` changed from 2 to 1 — only strongest strategy promoted
- Duplicate symbol guard: adapter blocks second position on same symbol

## Site Audit Fixes — 2026-05-13 20:00 ET

- Trade AI: `market_regime` field added from breadth (was None)
- Cron health: shows "scheduled" with expected times (was all "unknown")
- Phantom trades hidden from closed list (XMTR, EVC, FLYW breakevens)
- GCTS phantom-close root cause: empty positions API guard in adapter

## Strategy Intelligence API + Agent Performance Feedback — 2026-05-13 20:30 ET

### GET /api/v2/strategy-intelligence
Health dashboard for all 20 strategies: governance state, trade count, win rate,
profit factor, YAML quality flags (entry_criteria, auto_disqualifiers, vix_rules),
active proposals, trades to validation, performance verdict.

### Agent prompt performance injection
Every watchlist agent call now receives strategy performance data after the
playbook block: governance state, win rate, profit factor, avg R, confidence
adjustment guidance (PERFORMING: +0.05-0.10, UNDERPERFORMING: -0.10-0.15).

### YAML audit exported
63 issues across 20 strategies. All missing vix_rules and technical_indicators_required.
earnings_catalyst and gap_and_go have 0 entry_criteria. Full audit at
~/strategy_yaml_audit.md (2,359 lines). Enhancement deferred to dedicated session.

---

## Session 31 Summary — 2026-05-13

**55 commits** across 12+ hours. Major builds: LLM Queue Manager, event-driven
requeue, strategy diversity (27 screeners), gemma3 calibration loop, proposal
pipeline overhaul (card rebuild, RSI gate, auto-expiry, operator verdict UX),
lifecycle_state fix, broker source of truth architecture, time stop, data
integrity guards, LLM context engine (6 types), strategy intelligence API.

**Trades:** GCTS approved and closed by time_stop (-$9.38). INFU closed
manually (+$67.83) then re-entered via earnings_catalyst. 4 real closed trades,
1W 3L, 25% WR, +$28.26 realized. 2 positions open (GCTS + INFU).

**System:** 360+ scripts, 336 tables, 290+ endpoints, 160+ crons, 15 overnight
job types, 13-step safety chain, broker_confirmed column, LLM context engine.

## Session 33: Strategy YAML Patch Package — 2026-05-13 18:30 ET

### Summary
Resolved 63 YAML audit issues from Session 32. All 22 strategies now have
vix_rules, technical_indicators_required, and performance_context blocks.

### Changes
- **22 strategy YAMLs patched**: 3 new blocks each (vix_rules, technical_indicators,
  performance_context). 6 v1.0 files converted to v1.0.0 schema.
- **3 new strategies**: fib_retracement_bounce, earnings_pre_buildup,
  earnings_post_momentum (split from deprecated earnings_catalyst)
- **8 new screeners** in assets/screeners.yaml: quality_pullback, oversold_quality,
  dividend_value_pullback, post_earnings_gappers, sector_leadership_rs,
  covered_call_candidates, speculative_growth_breakouts, defensive_quality
- **6 deployment scripts**: deploy_yaml_patches.py, bulk_patch, convert, validate,
  patch_screeners, populate_performance_context
- **Nightly cron**: populate_performance_context.py at 2:30 AM refreshes
  performance stats from paper_performance_governance into YAMLs

### Verification
- Holdings: $1,190,695 / 47 positions (unchanged pre/post)
- vix_rules present: 23 files | technical_indicators: 23 | performance_context: 25
- earnings_catalyst.yaml: status=DEPRECATED
- All backups at backups/session33_pre_deploy_*, schema_convert_*, strategy_yaml_*

## Session 34 Hotfix: Overnight Queue Crash — 2026-05-13 18:45 ET

### Context
Manual 150-job overnight run crashed at job 73 with `psycopg2.errors.InvalidTextRepresentation:
invalid input syntax for type numeric: "1.5-3.0"`. The 23:00 auto window would hit the same bug.

### Fixes (4)

| Fix | Root Cause | Change |
|-----|-----------|--------|
| covered_call crash | LLM returned range "1.5-3.0" for NUMERIC `cc_yield_estimate` | Added `_safe_cc_float()` — handles ranges (midpoint), None, bad strings |
| Stuck running job | Job #309 (ARKG) stuck since 17:36, blocking queue | Reset to `failed` |
| Timeout | gemma3 heavy jobs timing out at 180s | Bumped default to 300s |
| RAG SQL | `youtube_transcripts` has `ingested_at` not `created_at` | Fixed ORDER BY column |

### Queue state after fix
pending: 441 | running: 0 | done: 14 | failed: 1

### Iron Rule
$1,190,695 / 47 positions — identical pre and post

---

## Phase 1J: Mixed Queue Enforcement + Overnight Dashboard — 2026-05-14 08:45 ET

### Changes
1. **Wrapper forced mixed job types** — `run_deep_overnight_llm_window.sh` now passes
   `--force-job-types risk_synthesis,recovery_watch_review,rag_content_curation,closed_trade_review,auto_journal_review,manual_journal_review,journal_pattern_review,proposal_review`
   to the queue runner. Strategy classification fills remaining capacity.

2. **Capacity policy** — Daily max 100, hard max 125, hard stop 03:00.
   HARD_MAX_JOBS changed from 100 to 125.

3. **Flag rename** — `--allow-over-75` → `--allow-over-hard-max` (backward compat kept).

4. **Friday extended cron preserved** — Reduced from 400 to 200 jobs with safe gates.
   Uses `--allow-over-hard-max`. 400 requires future Phase 1K approval.

5. **Overnight Intelligence Dashboard** — New page `/v2/overnight` with API endpoint
   `/api/v2/overnight-dashboard`. 12-section morning briefing. Telegram digest script added.

### Crontab
- Daily: `0 23 * * *` — unchanged, 100 jobs max
- Friday: `0 16 * * 5` — changed from 400 to 200 jobs, updated flag naming

### Validation
- bash -n: PASS
- py_compile: PASS
- Dry run with forced types: 20 jobs queued (rag_content_curation prioritized)
- API endpoint: 165 done, 1 failed, 9 job types, all sections populated
- Safety: ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true
- GPU: qwen3:14b (9.4GB) + nomic-embed-text (0.54GB) resident
- Holdings: $1,191,050

### Iron Rule
$1,191,050 / 43 positions — no broker, holdings, execution, or embedding changes

---

## Phase 1 Finalization: Deep Overnight Governance & Closeout — 2026-05-14 09:15 ET

### Changes

**Phase 1K — Queue Mix Balancing:**
- Added `--quota-policy balanced` and `--job-type-quotas` args to `run_deep_overnight_llm_queue.py`
- Per-type soft quotas: risk_synthesis=1, recovery=10, rag=15, closed_trade=15, journal=15, proposal=10
- Strategy classification fills remaining capacity after forced types
- Wrapper updated to pass `--quota-policy balanced`

**Phase 1L — Queue Status Reporter:**
- Created `scripts/report_deep_overnight_queue_status.py`
- Outputs: queue counts, job mix, failed jobs, model residency, lock, cron, risk synthesis
- Supports --summary, --json, --pending-top N

**Phase 1M — Health Checks & Alerting:**
- Created `scripts/check_deep_overnight_health.py`
- 11 checks: lock stuck, gemma/qwen/nomic residency, risk synthesis, P0 pending, failed jobs, provider, safety, holdings
- Integrates with alert_dispatcher for FAIL conditions
- All 11 checks: PASS

**Phase 1N — Documentation:**
- `docs/v4_1_phase1_final_audit.md`: full system state audit
- `docs/v4_1_phase1_final_closeout_report.md`: complete closeout with rollback instructions

### Validation
- All py_compile: PASS
- bash -n: PASS
- Balanced dry run: 15 RAG + 1 journal + 34 strategy (mixed, not all one type)
- Queue reporter: 660 total, 165 done, 1 failed, 494 pending
- Health checker: 11/11 PASS
- Safety: ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true
- Holdings: $1,190,957

### Cron (unchanged)
- Daily: `0 23 * * *` — 100 jobs, balanced quotas
- Friday: `0 16 * * 5` — 200 jobs, --allow-over-hard-max

### Model routing (unchanged)
- STANDARD/REALTIME: qwen3:14b
- DEEP_OVERNIGHT: gemma3-overnight (wrapper only)
- EMBEDDING: nomic-embed-text

### Phase 2A readiness
Go — pending operator approval and 7 clean nightly runs. No embedding promotion yet.

### Iron Rule
$1,190,957 / 43 positions — no broker, holdings, execution, or embedding changes

---

## Self-Healing Data Gap Orchestration — 2026-05-14 09:35 ET

### Changes

**Recovery watch prompt fix (HIGH):**
- Replaced manual sparse query with `llm_context_engine.build_context('recovery_watch')`
- Full context: snapshot, news, trade history, recovery data, anti-hallucination block
- Strict JSON output with `data_gaps` array and `INSUFFICIENT_DATA` verdict
- Should eliminate 10-identical-template-fallback pattern

**Queue dedup cooldowns:**
- Per-job-type cooldown in `build_deep_overnight_llm_queue.py`
- closed_trade_review: 7d, strategy_classification: 3d, recovery_watch: 24h
- Prevents AGMH 8x, PFE 6x type clusters
- Blank symbol jobs skipped

**Self-healing gap orchestration:**
- `data_gap_registry` + `gap_resolution_outcomes` tables created
- `_extract_and_register_gaps()` in queue runner: scans every gemma3 response
  for explicit data_gaps + 7 implicit gap patterns
- `data_gap_resolver.py`: dispatches enrichment/agent jobs via watchlist_agent_jobs,
  re-queues source jobs at P1:80 after resolution
- Dashboard gap intelligence section: open/enriching/resolved/abandoned counts
- API: gap_summary + gap_stats in overnight-dashboard

### Validation
- 3 test gaps (V div_yield, RTX/LMT catalyst) → resolved → 3 agent jobs dispatched
- All py_compile: PASS
- React build: OK
- Holdings: $1,191,013

### Iron Rule
$1,191,013 / 43 positions — no broker, holdings, execution, or embedding changes

---

## Session 35 — Gap Resolver Scheduling + Documentation — 2026-05-14 09:49 ET

**Cron entries deployed:**
- `0 10-16 * * 1-5` — hourly market-hours gap resolution
- `0 18 * * 1-5` — pre-overnight sweep
- `0 8 * * 0` — weekly audit

**Documentation updated (7 files):**
- MASTER_SYSTEM_DOCUMENTATION.md — new §5.5 Self-Healing Data Gap Orchestration
- SYSTEM_ARCHITECTURE_COMPLETE.md — background processes + cron count 152→155
- PROJECT_DOC_INDEX.md — Session 35 change log entry
- CHEAT_SHEET.md — gap resolver + health check + queue reporter quick refs
- RESTORE_GUIDE.md — cron entries + critical tables
- v4_1_deployment_log.md — this entry
- SYSTEM_FACTS_LATEST.md — Session 35 facts

**Verification:** 3 cron entries in crontab, resolver exits 0, logs created.

### Iron Rule
$1,190,653 / 43 positions — no broker, holdings, execution, or embedding changes

---

## Phase 2A: Embedding A/B Baseline & RAG Discovery — 2026-05-14 10:00 ET

### Preflight
All gates PASS. ALPACA_MODE=paper, LLM_DISABLE=true, holdings=$1,190,653, no deep lock.

### Candidate Model
**qwen3-embedding:8b INSTALLED** (4.7 GB, pulled 2026-05-14 10:05 ET)

### Current Production
nomic-embed-text: 768 dims, 14,784 embeddings, 14 source types, 23ms avg latency.

### A/B Baseline Results
- 40 queries tested against 1,000 docs, both models
- nomic: 768d, 23ms avg, 0 empty, 5 source types in top-5
- qwen3-embedding: 4096d, 295ms avg, 0 empty
- VRAM: qwen3-embed (5.67GB) + qwen3:14b (9.4GB) = 15.07GB — fits but evicts nomic
- Verdict: INCONCLUSIVE — quality comparison needs Phase 2B parallel index
- Phase 2B: GO recommended
- Production models restored: qwen3:14b + nomic-embed-text confirmed resident

### What Changed
- New script: `scripts/embedding_ab_baseline.py`
- New docs: A1A scope, preflight, RAG discovery, candidate check, A/B queries, A/B report, A/B results JSON, Phase 2B/2C/2D design docs

### What Did NOT Change
- Production embeddings: UNCHANGED
- Production RAG routing: UNCHANGED
- Cron: UNCHANGED
- .env: UNCHANGED
- Broker/holdings/execution: UNCHANGED
- nomic-embed-text: RETAINED as production default

### Recommended Next Step
Phase 2B parallel index test. Operator command: `Begin Phase 2B limited parallel embedding index test.`

### Iron Rule
$1,190,653 / 43 positions — no production embedding or routing changes

---

## Phase 2B: Parallel Embedding Index Test — 2026-05-14 10:41 ET

### Table Created
`content_embeddings_qwen3_test` — 1,000 rows, 4096 dims, 5 source types

### Index Build
- agent_result: 576, fused_signal: 399, trade_review: 11, news: 8, trade_outcome: 6
- Avg embedding latency: ~190ms
- 0 failures
- qwen3:14b + nomic-embed-text restored after build

### Retrieval Comparison (40 queries)
| Metric | nomic (production) | qwen3 (parallel) |
|--------|-------------------|------------------|
| Avg similarity | 0.613 | 0.609 |
| Avg latency | 28ms | 321ms |
| Source diversity | 1.4 types | 2.1 types |
| Empty results | 0/40 | 0/40 |
| Top-5 overlap | 0.6% | — |
| Top-10 overlap | 1.3% | — |

### Verdict: HYBRID_RECOMMENDED
Models find completely different documents. Both produce relevant results.
qwen3 has 50% better source diversity. Hybrid approach combining both recommended.

### Production Impact
- content_embeddings: UNCHANGED (14,787 rows)
- RAG routing: UNCHANGED
- Cron: UNCHANGED
- .env: UNCHANGED
- Models restored: qwen3:14b + nomic-embed-text

### Recommended Next Step
`Begin Phase 2C limited hybrid retrieval pilot.`

### Iron Rule
$1,191,288 / 43 positions — no production embedding or routing changes

---

## Three-Tier Alert Architecture — 2026-05-14 10:50 ET

### Changes
- `alert_dispatcher.py` enhanced with DIGEST + DASHBOARD_ONLY tiers, 17 classified alert types
- `send_alert_digest.py` created — morning/evening consolidated Telegram briefs
- `alert_dispatch_log` + `digest_queue` tables created
- `/api/v2/alerts-dashboard` endpoint + `/v2/alerts` React page
- 2 cron entries: 8 AM morning digest, 4 PM evening digest

### Tier Rules
URGENT (7): stop_triggered, iris_block, credential_expired, api_credits_depleted, pipeline_failure, proposal_approved_ready, sector_event
DIGEST (6): premarket_catalyst, topic_ingestion, rag_curation_summary, covered_call_candidates, iris_library_audit, new_go_normal
DASHBOARD_ONLY (4): youtube_backfill_progress, pipeline_run_ok, duplicate_recap, go_confirmation_repeat

### Verification
Test dispatches: dashboard_only and queued_morning_digest both route correctly. API returns live data.

### Live System Facts (introspected)
Tables: 344 | Scripts: 401 | Crons: 85 | Pages: 76 | Embeddings: 14,791

### Iron Rule
$1,191,263 / 43 positions — no broker, holdings, execution changes

---

## Phase 2C: Hybrid Retrieval Pilot — 2026-05-14 11:02 ET

### Pilot
- `hybrid_rag_retrieval_pilot.py` queries both nomic (14,792) + qwen3 (1,000) indexes
- 40 queries, weighted reranking, merge/dedupe

### Results
| Metric | Value |
|--------|-------|
| Verdict | HYBRID_MARGINAL |
| Consensus (both) | 2.5% |
| Nomic-only | 41% |
| Qwen3-only | 56.5% |
| Source diversity | 1.88 types/query |
| Latency | 1,713ms total |
| Empty | 0/40 |

### Recommendation
Expand qwen3 index to 5,000+ docs. Re-evaluate hybrid with matched coverage.

### Production Impact
UNCHANGED — no routing, embedding, cron, .env, or broker changes.

### Iron Rule
$1,191,538 / 43 positions — no production changes

---

## Phase 2B-Expanded — 2026-05-14

### What Changed
Expanded qwen3-embedding:8b parallel test index from 1,000 → 4,897 documents (13 source types). Re-ran retrieval comparison and hybrid pilot.

### Build Results
| Metric | Value |
|--------|-------|
| Rows added | 3,897 |
| Total qwen3 test rows | 4,897 |
| Source types covered | 13 of 14 |
| Build time | 1,066s (~18 min) |
| Avg latency | 267.9ms |
| Failures | 0 |

### Parallel Retrieval (40 queries)
| Metric | 1K Index | 5K Index |
|--------|----------|----------|
| Qwen3 similarity | 0.609 | 0.647 (+6.2%) |
| Nomic similarity | 0.613 | 0.612 |
| Qwen3 diversity | 2.08 | 3.0 (+44%) |
| Verdict | HYBRID_RECOMMENDED | **QWEN3_BETTER** |

### Hybrid Retrieval (40 queries)
| Metric | 1K Index | 5K Index |
|--------|----------|----------|
| Source diversity | 1.88 | 2.73 (+45%) |
| Consensus | 2.5% | 0.5% |
| Qwen3-only items | 56.5% | 71.5% |
| Latency | 1,713ms | 6,881ms |

### Recommendation
Begin Phase 2C offline integration pilot for deep overnight jobs only.
Phase 2D production promotion remains BLOCKED.

### Production Impact
UNCHANGED — no routing, embedding, cron, .env, or broker changes.

### Model Residency
nomic-embed-text + qwen3:14b resident. qwen3-embedding:8b unloaded after build.

### Iron Rule
$1,187,937 — no production changes

---

## Phase 2C Offline Integration Pilot — 2026-05-14

### What Changed
Created hybrid_rag_context_adapter.py and wired it into run_deep_overnight_llm_queue.py behind explicit --use-hybrid-rag opt-in flag. Ran 5-job manual pilot.

### Pilot Results
| Metric | Value |
|--------|-------|
| Jobs processed | 5/5 |
| Failures | 0 |
| Runtime | 4.8 min |
| Job types | manual_journal_review (1), strategy_classification (4) |
| Fallback used | Yes (qwen3-embedding not loaded during daytime) |
| RAG latency overhead | 0.3-2.3s per job (0.4-5.2% of total) |
| Source diversity | 1-6 types (previously 0, jobs had no RAG) |

### Key Finding
Deep overnight jobs currently use NO RAG context — only SQL-derived data. Adding even nomic-only RAG context provides new evidence (prior analyses, outcomes, news, signals) that was previously unavailable to gemma3.

### Recommendation
Enable hybrid RAG for nightly deep queue behind wrapper flag. Run 20-job pilot during deep overnight window where qwen3-embedding can be loaded. Phase 2D blocked.

### Production Impact
UNCHANGED — no routing, embedding, cron, .env, or broker changes.

---

## Phase 2C Offline Integration — Two-Stage 20-Job Pilot — 2026-05-14

### What Changed
Implemented two-stage lifecycle: Stage A prefetches hybrid context (qwen3-embedding + nomic), Stage B runs gemma generation with cached context. Hard rule enforced: qwen3-embedding:8b and gemma3-overnight never co-resident.

### New Scripts
- scripts/prefetch_hybrid_rag_context.py — Stage A prefetch
- scripts/run_phase2c_hybrid_offline_pilot.sh — Two-stage orchestrator (updated)
- scripts/run_deep_overnight_llm_queue.py — --hybrid-rag-cache flag for prefetched context

### Results
| Metric | Value |
|--------|-------|
| Stage A: Jobs prefetched | 20/20 |
| Stage A: Time | 6.8s |
| Stage A: Avg RAG latency | 341ms |
| Stage B: Jobs processed | 20/20 |
| Stage B: Time | 20.1 min |
| Stage B: Failures | 0 |
| Co-residency violations | 0 |
| Context source | Prefetched cache (no live embedding during gemma) |

### Key Finding
Deep overnight jobs previously had ZERO RAG context. Two-stage lifecycle safely adds 10 RAG results per job from 2-6 source types without model co-residency conflicts.

### Production Impact
UNCHANGED — no routing, embedding, cron, .env, or broker changes.

### Model Residency
Final: qwen3:14b + nomic-embed-text (production). All pilot models unloaded.

---

## Phase 2C Nightly Enablement — 2026-05-14

### What Changed
Daily 23:00 deep queue cron updated to include `--enable-hybrid-rag` flag.
Friday extended cron UNCHANGED (no hybrid).

### Cron Change
**Old:** `./scripts/run_deep_overnight_llm_window.sh >> logs/...`
**New:** `./scripts/run_deep_overnight_llm_window.sh --enable-hybrid-rag >> logs/...`

### Two-Stage Lifecycle
Stage A: nomic + qwen3-embedding → prefetch → unload qwen3-embedding
Stage B: gemma3-overnight → deep reasoning with cached context → restore qwen3:14b + nomic

### Safety
- qwen3-embedding and gemma3-overnight never co-resident
- Production RAG routing unchanged
- .env unchanged
- Broker/holdings/execution unchanged
- Phase 2D blocked

### Observation
```bash
./scripts/monitor_phase2c_hybrid_nightly.sh
```

### Rollback
Preferred: `./scripts/rollback_phase2c_hybrid_nightly.sh` (restores pre-change crontab backup).
Manual fallback removes all hybrid flags via sed. See `v4_1_phase2c_nightly_enable_scope.md`.

---

## Phase 2 Finalization — 2026-05-14

### What Changed
- Friday extended hybrid RAG enabled (`--enable-hybrid-rag` added to Friday cron)
- Phase 2D formalized as bounded offline/deep-queue hybrid RAG approval
- Phase 2 closed

### Cron
**Daily:** `... --enable-hybrid-rag >> logs/deep_overnight_llm_window.log` (unchanged)
**Friday:** `... --enable-hybrid-rag --force-window --max-jobs 200 --allow-over-hard-max >> logs/deep_llm_friday_extended.log` (NEW)

### Phase 2D Status
APPROVED: bounded offline/deep-queue hybrid RAG only.
BLOCKED: global production embedding promotion.

### Production Impact
- Global RAG routing: UNCHANGED
- Production embedding: nomic-embed-text (UNCHANGED)
- .env: UNCHANGED
- Broker/holdings/execution: UNCHANGED

### Rollback
- `./scripts/rollback_phase2c_hybrid_nightly.sh --daily` — daily only
- `./scripts/rollback_phase2c_hybrid_nightly.sh --friday` — Friday only
- `./scripts/rollback_phase2c_hybrid_nightly.sh --all` — both

### Next Phase
Phase 3: Small media/prose model pilot.

---

## Phase 2E Global Shadow Index — 2026-05-14

### What Changed
Built full qwen3-embedding:8b shadow index covering entire production corpus.

### Results
| Metric | Value |
|--------|-------|
| Production rows | 14,888 |
| Shadow rows | 14,874 |
| Coverage | 100% |
| Source types | 14/14 |
| Seeded from test | 4,897 |
| Newly embedded | 9,977 |
| Failed | 0 |
| Build time | 90.4 min |
| Avg latency | 537.5ms |

### Table
`content_embeddings_qwen3_shadow` — full corpus, shadow only, not production.

### Production Impact
UNCHANGED — no routing, embedding, cron, .env, or broker changes.

### Next
Phase 2F: Global shadow retrieval comparison.

---

## Phase 2F Global Shadow Retrieval — 2026-05-14

### Results (100 queries, 25 categories)
| Metric | Nomic | Qwen3 | Hybrid |
|--------|-------|-------|--------|
| Avg similarity | 0.688 | 0.634 | 0.699 |
| Avg diversity | 2.4 | 2.7 | 2.6 |
| Avg latency | 93ms | 1,285ms | — |
| Empty rate | 0% | 0% | 0% |

| Method | Winner Count |
|--------|-------------|
| nomic | 74 |
| hybrid | 35 |
| qwen3 | 21 |
| tie | 5 |

Overlap: 1.6%, Consensus: 2.9%

### Key Finding
Nomic wins on similarity (higher relevance scores). Qwen3 wins on diversity (finds different source types). Hybrid combines both advantages. Models are strongly complementary — 97% of results are unique to one model. This confirms hybrid is the right approach for deep/offline queues where both perspectives add value.

### Production Impact
UNCHANGED — no routing, embedding, cron, .env, or broker changes.

### Recommendation
Phase 2G limited canary can begin if operator approves.

---

## Phase 2G Limited Canary — 2026-05-14

### What Changed
Added bounded Phase 2G hybrid RAG canary with policy config, enforcement, batch runner, audit, and rollback.

### Config
`config/phase2g_hybrid_canary.yaml` — 12 allowed workflows, 9 blocked workflows

### Canary Batch
- 16/16 queries OK, 0 errors, 34.8s
- 6 workflows tested: risk_synthesis, recovery_watch_review, closed_trade_review, manual_journal_review, proposal_review, rag_content_curation
- Source diversity: 2.4 types/query
- Fallback: 16/16 (nomic-only — qwen3-embedding not loaded during daytime)
- Blocked workflow test: correctly refused

### Policy Enforcement
- Allowed: risk_synthesis → ALLOWED
- Blocked: telegram_realtime → BLOCKED (correct)

### Production Impact
UNCHANGED — no routing, embedding, cron, .env, or broker changes.

### Rollback
`./scripts/rollback_phase2g_canary.sh --disable`

---

## Phase 2G Continuation — 2026-05-14

### Expanded Canary
- 40/40 queries OK, 0 errors, 16.9s
- 10 workflows tested
- Avg diversity: 2.1, Avg latency: 421ms
- Fallback: 40/40 (nomic-only — qwen3-embedding not loaded daytime)

### Blocked Workflow Tests
- telegram_realtime: BLOCKED (correct)
- broker_execution: BLOCKED (correct)
- risk_gate: BLOCKED (correct)

### Scheduled Observation
- 3 deep runs in last 72h, 0 with hybrid flag yet
- First hybrid deep run expected tonight 23:00 UTC

### Production Impact
UNCHANGED — no routing, embedding, cron, .env, or broker changes.

### Recommendation
Prepare Phase 2H bounded approval proposal. Global promotion remains blocked.

---

## Phase 2H Bounded Offline Hybrid Approval — 2026-05-14

### Status
APPROVED — bounded offline/deep/read-only hybrid RAG is production behavior.

### What Is Approved
14 offline workflows including daily/Friday deep queue, risk synthesis, recovery watch,
journal reviews, proposal reviews, RAG curation, and offline report context.

### What Is NOT Approved
Global/default RAG routing. Market-hours. Real-time. Telegram/OpenClaw. Broker/execution/risk gates.

### Policy
`config/phase2h_bounded_hybrid_rag_policy.yaml`

### Audit
`.venv/bin/python scripts/audit_phase2h_bounded_approval.py` — ALL PASS

### Production Model State
- Production embedding: nomic-embed-text (unchanged, global default)
- Shadow embedding: qwen3-embedding:8b (bounded hybrid only)
- Standard inference: qwen3:14b
- Deep reasoning: gemma3-overnight (via two-stage wrapper)

### Production Impact
No global RAG routing change. No production embedding change. No .env change.
No broker/holdings/execution change.

### Phase 2 Final Status
COMPLETE — all phases 2A through 2H.
Global production embedding promotion remains a separate future decision.

### Next Phase
Phase 3: Small media/prose model pilot.

---

## Phase 3 Media/Prose Model — Discovery — 2026-05-14

### Candidate
`gemma4:e4b` — ~3-4 GB, documented in LLM Fleet Strategy v4.1 as Phase 3 MEDIA_CONTENT model

### Status
NOT INSTALLED. Pull required:
```
ollama pull gemma4:e4b
```

### Discovery
7 media/content scripts identified as Phase 3 pilot candidates:
youtube_transcript_ingest, transcript_slow_processor, content_scoring,
topic_ingestion, topic_curator, aegis_morning_brief_delivery, agent_curation_hooks

### Production Impact
None. Discovery only.

### Recommendation
Approve pull gemma4:e4b. Then run smoke tests and limited offline pilot.

---

## Phase 3 Guarded Pull — gemma4:e4b — 2026-05-14

### Pull Result
SUCCEEDED — but model is 9.6 GB (documented estimate was 3-4 GB).

### Smoke Test
POOR — produced irrelevant output instead of following summarization instruction.
- Generation: 120 tokens in 8.2s
- Load time: ~54s
- Output: off-topic, did not follow "summarize in 3 bullets" prompt

### VRAM Impact
9.6 GB — cannot coexist with qwen3:14b (10 GB) on 16 GB VRAM.
Same evict/restore lifecycle burden as gemma3-overnight.

### Production Models Restored
qwen3:14b + nomic-embed-text restored after smoke test.

### Recommendation
HOLD Phase 3. Options: additional smoke tests, try smaller model, keep qwen3:14b for all tasks, or wait for gemma4 maturity (2026-08-11).

### Cleanup Option
`ollama rm gemma4:e4b` to reclaim 9.6 GB disk.

---

## Phase 3A Quick Smoke Test — gemma4:e4b — 2026-05-14

### Patch
Stopped slow full-matrix run. Patched script: /no_think baseline, 90s timeout, lock, quick mode.

### Results
| Metric | Baseline (qwen3 /no_think) | Candidate (gemma4) |
|--------|---------------------------|-------------------|
| Avg score | 3.36 | 3.51 |
| Avg latency | 15,918ms | 15,830ms |
| Tests | 5 | 11 |
| Timeouts | 0 | 1 |
| Verdict | — | **TIE** |

### Key Findings
1. gemma4 quality matches qwen3 (TIE at ~3.4-3.5)
2. First call timeout on cold load (~90s), subsequent calls fast (6-16s)
3. "system" prompt style produced best results (score 4.0)
4. Initial poor result was likely cold-load + wrong prompt format
5. gemma4 is 9.6 GB — cannot coexist with qwen3:14b (fails lightweight goal)
6. qwen3 baseline with /no_think returned empty for 4/5 tests (possible issue)

### Production Impact
None. qwen3:14b + nomic-embed-text restored.

### Recommendation
Reject gemma4:e4b for Phase 3 lightweight content model — it's too large (9.6 GB).
Keep qwen3:14b for content tasks or test a truly small model (~2-4 GB).
Remove gemma4:e4b to reclaim disk: `ollama rm gemma4:e4b`

---

## Phase 3B — gemma3:4b Smoke Test — 2026-05-14

### gemma4:e4b
REJECTED and REMOVED. 9.6 GB reclaimed.

### gemma3:4b
PULLED — 3.3 GB. Fits alongside qwen3:14b (13.3 GB total < 16 GB VRAM).

### Smoke Test Results
| Metric | Baseline (qwen3 /no_think) | Candidate (gemma3:4b) |
|--------|---------------------------|----------------------|
| Avg score | 3.2 | **3.9** |
| Avg latency | 28,221ms | **6,870ms** |
| Tests | 4 (1 timeout) | 12 (0 timeouts) |
| Verdict | — | **CANDIDATE_BETTER** |

### Key Finding
gemma3:4b is lightweight (3.3 GB), 4x faster, and produces better media/prose output than qwen3 /no_think.

### Production Impact
None. qwen3:14b + nomic-embed-text restored.

### Recommendation
Continue Phase 3 pilot with gemma3:4b for approved media/prose workflows.

---

## Phase 3C — Media/Prose Routing to gemma3:4b — 2026-05-14

### Config
`config/phase3_media_prose_routing.yaml` — 14 approved, 12 blocked workflows.

### Router Test
- Approved (youtube_transcript_summary): gemma3:4b, 4.3s, 341 chars, no fallback
- Blocked (broker_execution): REFUSED correctly

### Model State
| Role | Model | Status |
|------|-------|--------|
| STANDARD/REALTIME | qwen3:14b | Unchanged |
| MEDIA/PROSE | gemma3:4b | NEW — 3.3 GB, coexists with qwen3:14b |
| DEEP reasoning | gemma3-overnight | Unchanged |
| Embedding | nomic-embed-text | Unchanged |
| Hybrid offline | qwen3-embedding:8b | Unchanged |

### Production Impact
No global routing change. qwen3:14b remains STANDARD/REALTIME. Media/prose routing is opt-in via Phase 3C policy.

### Rollback
`./scripts/rollback_phase3_media_prose_routing.sh --disable`

---

## Phase 3D — Expand Media/Prose Routing — 2026-05-14

### Expansion
4 new approved workflows: markdown_cleanup, plain_language_rewrite, meeting_note_summary, newsletter_digest.
Total approved: 18. Blocked: 12 (unchanged).

### Pilot
15/15 items OK, 0 fallbacks, 0 failures.
Avg latency: 4,815ms. All using gemma3:4b.
Workflows tested: 15 distinct types.

### Model Residency
All 3 models co-resident: nomic (0.6 GB) + qwen3:14b (10 GB) + gemma3:4b (4.3 GB) = ~15 GB.

### Production Impact
None. qwen3:14b remains STANDARD/REALTIME. nomic remains embedding. Phase 2H unchanged. No .env/cron/broker changes.

### Recommendation
Keep enabled. Expand further as content integrations accumulate. Phase 3 is functionally complete.

---

## Phase 4 — LLM Fleet Observability — 2026-05-14

### Added
- Fleet status report: scripts/report_llm_fleet_status.py
- Alert rules + checker: config/llm_fleet_alert_rules.yaml, scripts/check_llm_fleet_alerts.py
- Daily summary: scripts/write_daily_llm_fleet_summary.py
- Rollback: scripts/rollback_phase4_observability.sh
- API/dashboard: deferred (CLI sufficient)

### Fleet Status
OK. 3 models resident (qwen3:14b + gemma3:4b + nomic). VRAM 13.9/16GB. 0 alerts.

### Production Impact
None. Read-only observability. No routing, .env, cron, or execution changes.

### Next Phase
Phase 5: Feedback/learning loop.

---

## Phase 5 — Feedback/Learning Loop — 2026-05-14

### Added
- Feedback schema: llm_feedback_observations, llm_learning_recommendations, llm_prompt_experiments
- Observation collector: 317 observations from deep_overnight_llm_results
- Recommendation generator: 1 recommendation (pending_human_review)
- Human review queue reporter
- Rollback helper

### Key Result
Feedback pipeline operational. 1 recommendation pending human review:
"Review deep_overnight output quality and add outcome labels" [low risk]

### Safety
- All recommendations are pending_human_review only
- No auto-applied changes
- No .env/cron/routing/execution changes

### Production Impact
None. Read-only feedback collection.

### Next
Review human queue. Schedule collector. Build approval workflow later.

---

## Proposal Pipeline Fix — 2026-05-14

### Changes
1. **Stale proposal cleanup cron** — NEW
   - `scripts/cleanup_stale_proposals.py` auto-rejects blocked (>4h), missing data (>48h), and stale (>24h) proposals
   - Runs at 10:00 AM and 3:00 PM weekdays
   - Keeps proposal queue fresh instead of accumulating dead entries

2. **End-of-day auto-proposals** — CHANGED
   - Removed `--skip-auto-proposals` from 17:30 orchestrator run
   - Strong incubator candidates can now auto-promote at end of day
   - Earlier runs (12:00, 14:00, 16:00) still skip auto-proposals

3. **Dashboard BLOCKED verdict fix** — FIXED
   - `proposal_execution_readiness.py` now syncs `action_state` when writing execution results
   - `api_v2.py` verdict logic now checks `action_state` for BLOCKED instead of falling through to NEEDS_REVIEW
   - Dashboard correctly shows BLOCKED when execution gates fail

### Cron
**Old 17:30:** `--run-label 1730 --no-alerts --skip-auto-proposals --allow-underfilled`
**New 17:30:** `--run-label 1730 --no-alerts --allow-underfilled`
**New cleanup:** `0 10,15 * * 1-5 ... cleanup_stale_proposals.py --apply`

### Production Impact
Paper proposals only. No broker/execution/live-trading changes.

---

## Hourly Auto-Proposals + Incubator Promoter — 2026-05-15

### Changes
1. **All orchestrator runs now have auto-proposals enabled** — removed `--skip-auto-proposals` from 12:00, 14:00, 16:00 runs (17:30 was already enabled)
2. **Incubator promoter now runs hourly** — changed from every 2 hours (9,11,13,15,17) to hourly (7-17) during trading days
3. **Stale cleanup unchanged** — still runs at 10:00 and 15:00

### Schedule Summary
| Time | Action |
|------|--------|
| 7:00-17:00 hourly | Incubator promoter (promote qualifying candidates) |
| 10:00, 15:00 | Stale proposal cleanup (reject blocked/stale) |
| 12:00, 14:00, 16:00 | Orchestrator scan + auto-proposals |
| 17:30 | End-of-day orchestrator + auto-proposals |

### Why
Proposals were going stale because auto-proposals were disabled on most runs and the incubator promoter only ran every 2 hours. Now fresh opportunities are promoted hourly and stale ones are cleaned twice daily.

---

## 2026-05-22 — ATM Context Sync and Safety Reclassification

### Summary
- Today's ATM documentation was read and ingested from Google Drive
- ATM active mode executed paper trades/orders (NWG, NVDA, AGNC, CMCSA)
- audit_log schema mismatch discovered (event column missing)
- Quote fetch 404 fallback issue discovered (wrong API URL — paper-api vs data.alpaca.markets)
- Partial-fill race condition in alpaca_paper_adapter.py discovered and fixed
- Stale proposal retry loop discovered and fixed (expiry logic added)
- Stop management system fully mapped (discovery only, no changes)

### Current Status
- ATM-SAFE-1 containment required before further enhancements
- Do not proceed with feature work before containment
- No live trading enabled by this context-sync phase
- This phase made documentation/context updates only (plus 3 P1 bug fixes and UI improvements)

### Maturity Impact
- Prior estimate: 7.6 / 10
- Revised: 6.4 / 10
- Reason: paper execution governance issue — ATM active mode executed without all safety gates hardened
- Not live-money critical, but paper execution automation crossed expected boundaries

### Fixes Applied (code)
1. `alpaca_paper_adapter.py`: partial-fill race condition fixed
2. `alpaca_paper_adapter.py`: quote endpoint switched to data.alpaca.markets
3. `atm_auto_approver.py`: stale proposal expiry logic added (4h age, 5 failures, enrichment failed)
4. `api_v2.py` + frontend: last_updated_at timestamps on journal/open-trades
5. `Shell.tsx`: ATM moved to Trading menu, Backtesting to Strategy, orphaned pages added

### DB Changes Applied
- 5 columns added to paper_trade_proposals (atm_evaluation_count, atm_last_evaluation_at, atm_last_failure_reason, atm_expired_at, atm_expiry_reason)
- Index idx_proposals_atm_active created
- NWG/NVDA paper_trades synced to open status with stops
- Orphan pending stubs #30, #32 closed
- ARM/BCS evaluation counts backfilled from decision log
