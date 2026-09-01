# Trade AI v12 — Deep Technical & Product Review (2026-06-11)

Status:      ACTIVE
as_of:       2026-06-11T11:57:09-04:00
Measured at: efcc51365 / not measured

**Type:** read-only audit. Four parallel code-tracing audits (intake, integrations, proposals, backtesting) +
direct DB evidence + all 23 strategy YAMLs reviewed individually. Findings cite file:line where confirmed;
hypotheses are labeled. Repo: main @ 1,957 commits; 955 tracked .py, 241 .tsx, 1,907 .md; api_v2.py 27,938 lines.

---

## A. System understanding (end-to-end)

**Purpose:** a single-operator (John) portfolio-intelligence + paper-trading system over a $1.24M real
portfolio (Schwab/Fidelity read-only) and an Alpaca paper account, with a hard live-trading lock.

**Flow:** Finviz Elite screeners (cron 0900–1730, 6×/day) → `trade_ai_orchestrator.py` 23-stage pipeline
(market context → economic calendar → 7-source catalyst enrichment → options flow → short interest → sector
momentum → trend → **scoring: 7 pillars, 65-pt max** → scalp-critic LLM review → GO/WAIT/NOGO) →
`auto_proposal_generator.py` (11 gates) → `paper_trade_proposals` → decision gate → ATM auto-approver
(automation_mode-gated) → Alpaca paper bracket submit → fill verification → atomic stop v2 → news auto-close →
outcome classification → journal → replay grading (`trade_backtest_engine.py`) + execution quality
(`build_trade_execution_quality.py`) + Grok coaching → Execution Coach queue. Hermes research fleet
(YouTube transcripts, catalyst momentum, external LLM lanes) feeds a composite-scored watchlist; operator
directives pin symbols. Safety: Schwab write fence (12/12 validator), `LIVE_TRADING_ENABLED=false`,
paper-only Alpaca, advisory-only LLMs.

**Decision points:** pre-score filter (cuts ~95%), GO threshold (score≥40), critic override, 11 proposal
gates, risk gate (heat/concentration/loss limits), ATM mode, execution readiness (quote freshness/drift/
spread/RSI), submission gates, stop placement, news auto-close.

---

## B. Information-intake audit

### Finviz (primary screener + enrichment)
- Ingestion: `finviz_ingestion.py:162-177` CSV export → `normalize_finviz_columns()` (:73-117) → cache
  `scored_tickers_latest.json` → `trade_ai_scans`. Enrichment via 5 Elite views, 6h TTL cache, ~100 req/hr.
- **Weak:** cookie expiry is silent until the next scheduled run (health check only at run start); **no cache
  staleness check** on the fallback (a failed 0900 silently feeds 1000 with stale data); no post-download
  schema validation (column drift would mis-map silently); duplicates not dropped pre-scoring (same symbol
  from 2 screeners → scored twice → redundant LLM calls).

### Trade AI pipeline
- 23 stages, per-stage try/except with graceful degradation — robust to transient failure, **fragile to silent
  degradation**. Sector momentum is cliff-edged binary buckets (5/3/1/0, orchestrator:97-117) and silently
  zeroes if market-context fails (3–5 pt score swing). No per-source freshness tracking. Pre-score
  `min_pre_score=5` (scoring.py:250) intentionally cuts ~95% — but with no circuit breaker, a broken cookie
  looks identical to a quiet tape (GO collapse undetected; observed "1 GO / 1171 NOGO").

### Hermes
- YouTube transcripts → `hermes_research_intelligence`; curation ladder L0→L5 (`agent_watchlist_engine.py:51-150`).
- **Weak:** `hermes_rss_ingest.py` is a **stub** (dead path — parser never implemented); composite-score
  formula is scattered across scripts (no single source of truth for H-1/H-2 weights); dedup only at
  whiteboard level (same discovery can stage twice from different source types); YouTube cookie expiry halts
  ingestion with manual-only recovery.

### News/catalysts (7 sources)
- Finnhub/NewsAPI/Polygon/FMP/Finviz-news/Yahoo (+Brave separately). Fingerprint dedup = MD5 of first 10
  words — **too coarse** (distinct catalysts collapse) and **intra-run only** (same article re-scored at the
  next run). Alpha Vantage fetcher is dead code. **No unified rate budget** (NewsAPI 500/day untracked; Brave
  has its own 25/day silo). All-source sequential fetch even after enough fresh articles found.

### Market data
- Alpaca SIP (fixed this session: feed + `+00:00`→`Z` URL bug) → Schwab `get_price_history` → Finviz image.
  Pagination hard-capped at 6 pages with silent truncation. Schwab normalizer shapes fixture-proven, flagged
  for wire-time reconciliation (schwab_transport.py:17).

### Watchlist seeding
- 3 sources seeded 119 duplicate symbols (fixed this session at query layer with DISTINCT ON + directive
  pinning); ingestion-time idempotency still absent.

**Verdict:** intake is broad and survives failure, but optimizes for *coverage* over *signal hygiene*:
duplicate scoring, coarse dedup, siloed budgets, and several silent-degradation modes.

---

## C. Integration / OAuth audit

**"Codex" mapped:** there is no Codex API. "Codex" = **ChatGPT via OpenAI free OAuth** (provider
`openai-codex`) through the Hermes CLI — one of three free LLM lanes (grok = xAI OAuth proxy @127.0.0.1:8645;
chatgpt = openai-codex w/ pseudo-TTY workaround, Hermes ≥0.16; local = Ollama gemma3). All advisory-only.

**Solid:** Schwab OAuth Gate-A (Fernet-encrypted tokens, append-only audit, day-5/6 refresh alerts,
fail-closed health, 12/12 write-fence). Alpaca paper-only. Telegram alerts. Redaction layer on external LLM
context.

**Gaps (ranked):**
1. **Unused Schwab READY capabilities:** batch quotes (rate savings), market-hours endpoint, option chains
   (stub), fundamentals — transport exists, never wired.
2. **LLM lanes underused where they'd help most:** no proposal pre-flight challenge (bear case/invalidation),
   no entry-grade vetting at screener time, no auto-generated post-trade lessons (all are pure functions or
   manual today).
3. **Metered-API usage inside the pipeline** despite the free-only OAuth rule: Claude **Haiku re-scores
   ambiguous catalysts** (scoring.py:457-460) and **Sonnet writes A+ trade plans** (stage 14) — flag for
   operator decision (intentional exception vs migrate to grok/local lanes).
4. Cookie fragility ×2 (Finviz, YouTube) with manual-only refresh; no unified refresh calendar.
5. Grok proxy (:8645) is a single point of failure with no health-based failover; no rate-limit tracking on
   any lane.
6. Schwab access-token auto-refresh is a stub (NOT_PROVEN); rate bucket is one shared 100/min default instead
   of split data/trading buckets.

---

## D. Trade-proposal audit

**Good:** the 11-gate chain is real and mostly well-built — strategy-criteria validation w/ YAML screen
filters, liquidity pre-screen, 48h closed-cooldown, risk gate (heat 6%/position 8%/sector 25%, fail-closed),
strategy-aware expiry (8h scalp → 720h compounder), RTH-gating of intraday proposals, multi-provider quote
hierarchy, evidence snapshots, full event log. Paper-only submission is physically locked.

**Weak (ranked):**
1. **Cross-strategy duplicate hole:** Gate-4 dedup is per (symbol, strategy, today) — the same screener hit
   spawns proposals under multiple strategies (confirmed: BWEN ×3 on 2026-06-04 across sector_rotation /
   speculative_growth / swing_breakout, all 0-min scratches). The new DB dedup guard stops duplicate *fills*,
   not duplicate *proposals*.
2. **No feedback loop into scoring:** the 65-pt rubric never sees live win rates, execution quality,
   runner_type, or Hermes evidence. A strategy at 33% live WR scores identically to one at 100%.
3. **Lossy funnel:** 47/55 paper trades link to proposal_id, yet current proposal statuses show only 1
   APPROVED ever (100 REJECTED / 84 EXPIRED) — statuses are overwritten post-execution; the funnel can't be
   reconstructed from state (must use event log). Conversion analytics are therefore wrong by construction.
4. **Strategy labeling noise:** 63/102 recent journal trades "(unclassified)"; day-scalps labeled
   dividend_growth_compounder (BLBD 16-min scratch). Per-strategy stats inherit this noise.
5. R:R thresholds inconsistent across gates (1.2 vs 1.5); stale catalysts (5d old) still score; pillar
   breakdown + LLM reasoning not surfaced (explainability gap); no GO-collapse circuit breaker.

**Bottom line:** proposals are *safe* but not yet *sharp* — the gates prevent disasters; the scoring doesn't
yet learn, dedupe, or explain.

---

## E. Strategy-by-strategy review (23 YAMLs; evidence = live DB counts 2026-06-11)

Schema note: YAMLs are richer than typical (screen_filters, auto_disqualifiers, scoring_weights,
validation_gate) **but section names drift between files** (setup_qualification vs entry_criteria) and the
criteria are **not machine-enforced anywhere** (no evaluator reads entry_criteria at decision time — LLM/
operator interpret them). Validation gates demand 30 closed + 6 months per strategy; the whole book has
**37 closed paper trades total**.

| # | Strategy | Status | Closed n (evidence) | Verdict | Why |
|---|---|---|---|---|---|
| 1 | momentum_scalp | TESTING | 5 (+$380, 1.22R) + operator's 81 real Schwab scalps | **KEEP (core)** | Matches operator style; richest spec (261L); execution coach shows the fixable leak (entry w/o volume ×70) |
| 2 | swing_breakout | TESTING | 7 (+$268, 0.25R) | **KEEP (core)** | Most-traded; well-specified; base-breakout is testable |
| 3 | fib_retracement_bounce | UNVALIDATED | 4 (4/4 wins, **2.36R** — best in book) | **KEEP (core, promote to TESTING)** | Only strategy with strong positive R; n=4 caveat — prioritize its sample growth |
| 4 | earnings_post_momentum | UNVALIDATED | 0 | **REWRITE+KEEP (core #4)** | The testable earnings setup (gap-and-hold after beat); absorb anything useful from pre_buildup |
| 5 | earnings_pre_buildup | UNVALIDATED | 0 | **REMOVE** | Depends on institutional-positioning/options-flow signals the intake doesn't reliably have |
| 6 | earnings_catalyst | **DEPRECATED** | 2 (legacy) | **REMOVE (archive)** | Already superseded by its two children |
| 7 | gap_and_go | TESTING | 0 (20 proposals, none survived) | **MERGE → momentum_scalp** | A gap sub-setup of the same microcap momentum trade; never produced a trade |
| 8 | swing_trade | UNVALIDATED | 6 (33% WR, 0.09R — weakest active) | **MERGE → swing_breakout** | "Continuation" vs "base breakout" distinction isn't earning its keep; schema drift |
| 9 | sector_rotation | TESTING | 1 | **INSUFFICIENT EVIDENCE — park** | Weekly ETF rotation is a portfolio overlay, not a proposal generator; pause from proposal set |
| 10 | speculative_growth | UNVALIDATED | 1 | **REMOVE** | Catch-all ("higher risk tolerance" is not a setup); overlaps momentum/swing |
| 11 | recovery_watch | UNVALIDATED | 1 | **MERGE → Recovery Watch engine** | Duplicates the dedicated stopped-position re-entry system (14 tracked) |
| 12 | dividend_growth_compounder | UNVALIDATED | 5 (−$147, −0.17R) | **KEEP as income-sleeve policy; REMOVE from proposals until classifier fixed** | Its "trades" are mislabeled day-scalps — the negative stats are labeling noise |
| 13 | reit_income | UNVALIDATED | 1 | **MERGE → income sleeve** | Allocation role, not a signal strategy |
| 14 | high_yield_income_bdc | UNVALIDATED | 0 | **MERGE → income sleeve** | Same |
| 15 | international_dividend | UNVALIDATED | 0 | **MERGE → income sleeve** | Same |
| 16 | income_add | TESTING | 0 | **REMOVE** | An *action* on the income sleeve, not a strategy |
| 17 | bond_income | UNVALIDATED | 0 | **RECLASSIFY → allocation policy** | Ballast/allocation; keep doc, exit trading set |
| 18 | cash_or_stable | UNVALIDATED | 0 | **RECLASSIFY → allocation policy** | Same |
| 19 | core_index | UNVALIDATED | 0 | **RECLASSIFY → allocation policy** | Same |
| 20 | core_growth_compounder | UNVALIDATED | 0 | **RECLASSIFY → allocation policy** | Same |
| 21 | defense_thesis | UNVALIDATED | 0 | **KEEP as conviction sleeve** | Operator macro thesis (AI/WWIII); allocation conviction, not signal strategy |
| 22 | covered_call_income | UNVALIDATED | 0 | **PARK** | Options not executable anywhere in the stack (Schwab fenced, Alpaca options not wired) |
| 23 | tax_loss_harvest | UNVALIDATED | 0 | **RECLASSIFY → ops playbook** | A tax process, not a market strategy |

12 of 23 have **zero trades ever**; the proposal funnel engaged 15 but converted almost nothing outside the
core 5. The "22 strategies" are really **4 trading setups + an income/allocation portfolio taxonomy** wearing
strategy YAMLs.

---

## F. Consolidation recommendation: CONCENTRATE

**Recommendation: reduce the active trading set to 4** — `momentum_scalp` (absorbing gap_and_go),
`swing_breakout` (absorbing swing_trade), `fib_retracement_bounce`, `earnings_momentum` (rewritten
post-momentum) — and reorganize the rest into one **income-sleeve policy family** + allocation/conviction/ops
policy docs outside the proposal pipeline.

**The arithmetic forces this:** each validation gate needs ≥30 closed trades + 6 months. Total system
throughput ≈37 closed in ~the last month of active paper. Validating 10+ trading strategies needs 300–690
trades (years); validating 4 needs ~120 (months). Every additional strategy also dilutes the proposal queue,
multiplies the dedup surface (BWEN×3 was three *strategies* claiming one signal), and adds YAML drift. A
4-strategy core makes the system cleaner, the labels honest, and proof reachable.

---

## G. Backtesting credibility review: NOT YET CREDIBLE (and partly honest about it)

**What exists:** (1) `trade_backtest_engine.py` — replay-**grading** of already-closed trades (A–F letter
grades, left-on-table); (2) `enterprise_backtester.py` — deterministic **replay** of fixed entry/stop/target
against daily bars; (3) `backtest_execution_hypotheses.py` — rule-variant deltas, correctly marked
evidence-only/do_not_graft (all 3 hypotheses negative); (4) execution-quality reconstruction (this month's
work) — genuinely good per-trade forensics.

**What's missing for proof:**
1. **No signal-generation simulator** — nothing generates entries from point-in-time data; both engines take
   the entry as input. Edge claims are therefore untestable.
2. **Rules not machine-enforced** — no evaluator executes YAML `entry_criteria` (operator/LLM interpret); the
   same setup can pass or fail by judgment. Unrepeatable.
3. **Look-ahead bug:** `trade_backtest_engine.py:242` uses `df.index <= open_date` — the entry bar's own
   close contaminates entry grades (`<` required; regrade after fix).
4. **No walk-forward / out-of-sample anywhere** (grep-confirmed zero).
5. **No slippage/commission model** (perfect fills assumed; ~0.2–0.5%/RT optimistic).
6. **96% synthetic data:** ~21,217 of 21,700 backtest rows are champion/simulation rows; blended stats are
   dominated by synthetic fills.
7. **Sample collapse:** no strategy is near its own 30-trade gate.
8. **Broken feedback loop (found during this review):** `populate_performance_context.py:116-125` queries
   non-existent columns (`realized_r`,`realized_pnl`; actual `r_multiple`,`pnl`), silently fails, and
   **nightly (02:30 cron) writes `closed_paper_trades: 0` into all 25 YAMLs** — strategy configs and
   governance gates have never seen real performance. (Separately, `paper_performance_governance.py`
   computes correct numbers but doesn't write them to YAML.)

**Minimal credible path (core-4):** fix the column bug + look-ahead `<` → build the entry-criteria evaluator
→ add a −0.3%/RT cost factor → exclude champion rows from default stats → run one walk-forward on
swing_breakout/momentum_scalp once each crosses ~30 closed → reconcile 10–20 real Schwab fills against
replay (<5% deviation). ≈1 week engineering + 3–6 months of focused paper flow.

---

## H. Highest-priority fixes (ranked)

| P | Fix | Why |
|---|---|---|
| **P0-1** | `populate_performance_context.py` column bug (`realized_r/realized_pnl` → `r_multiple/pnl`) | Silent nightly corruption of every strategy config; governance is blind |
| **P0-2** | Cross-strategy proposal dedup (Gate 4.5: one symbol → one proposal across all strategies, 48h) | BWEN×3 class of phantom signals |
| **P0-3** | Strategy-label integrity (fix classifier; 63/102 unclassified; scalps labeled dividend_growth) | Every per-strategy statistic inherits this noise |
| **P1-4** | Look-ahead fix in trade_backtest_engine (`<=`→`<`) + regrade all rows | Entry grades currently untrustworthy |
| **P1-5** | Entry-criteria evaluator (machine-enforce YAML rules at proposal time) | Unlocks repeatability + testability |
| **P1-6** | Strategy consolidation 23→4 core + sleeves (Section F) | Makes proof arithmetically reachable |
| **P1-7** | Cost model in replay (−0.3%/RT) + exclude champion rows from blended stats | Honest numbers |
| **P2-8** | Feedback loop into scoring (strategy scar factor from live WR; runner_type/exec-quality input) | Scoring that learns |
| **P2-9** | Intake hygiene: pre-score symbol dedupe; cache staleness checks; unified rate budget; implement-or-delete hermes_rss stub; remove Alpha Vantage dead path; GO-collapse circuit breaker | Signal hygiene + cost |
| **P2-10** | Wire Schwab READY (batch quotes, market hours); proposal explainability (pillar breakdown in alerts); LLM pre-flight challenge lane | Cheap capability already paid for |
| **P3** | Docs re-proliferation (1,263 active .md again, was 430 on 06-02); funnel-preserving proposal status events | Hygiene |

---

## Implementation status (same day, operator-approved "fix all 5")
P0-1 ✓ c5450b0e · P0-2 ✓ ab3aff8a · P0-3 ✓ 290c7fdc · consolidation ✓ 7251b1f2 (core-4 active, risk-gate
enforced) · free-lane migration ✓ 910f0120 · cadence ✓ (0900/1000 crons retired, backup saved) · Schwab READY
✓ adeddcdc (batch quotes + market hours live). Remaining open from section H: P1-4 look-ahead regrade, P1-5
entry-criteria evaluator, P1-7 cost model, P2 intake hygiene/feedback loop, P3 docs re-proliferation.

## Open questions for the operator
1. Fix **P0-1/P0-2/P0-3 now**, or hold all changes pending your read of this review?
2. Approve the **4-strategy core consolidation** (momentum_scalp, swing_breakout, fib_retracement_bounce,
   earnings_momentum)? Any strategy you want kept active regardless?
3. **Metered Claude inside the pipeline** (Haiku catalyst rescoring, Sonnet A+ trade plans) vs your
   free-OAuth-only rule — intentional exception, or migrate those calls to grok/local lanes?
4. Orchestrator cadence: 6 scheduled runs/day **plus** :01/:04 hourly runs (incl. premarket) — intended?
5. Green-light wiring the Schwab READY read capabilities (batch quotes, market hours)?

*Confirmed findings carry file:line citations; items marked as hypotheses in section text await verification.*
