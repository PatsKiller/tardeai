<!-- Lifecycle fact base C — Watchlist, proposal and learning lifecycles. Re-measurement of LIFECYCLE_FACTBASE_C_WATCHLIST_2026-09-14.md. -->

# Trade AI — Family C: Watchlist, Proposal and Learning Lifecycles (re-measured 2026-10-04)

Status: ACTIVE
as_of: 2026-10-04T20:58-04:00 (Sunday evening ET; weekday-only producers last ran Fri 10-02)
Measured at: 4f932b88a (dev tree HEAD = live CURRENT `4f932b88a-main-exact-phase2-20261004-202102`; API `_serving.pin_match=true`)

Method: read-only. DB SELECT only inside `SET TRANSACTION READ ONLY` (statement_timeout 90 s); `crontab -l`; `systemctl --user list-timers` / `journalctl --user`; log greps under `CURRENT/logs`; jsonl readers under `persistent-state/data/{cio,runtime}`; GET `:7777/api/v3/{cio/lessons/digest, agents/calibration, cio/counterfactuals}`; `git log --since=2026-09-14`. No writes, no LLM, no broker calls.

Labels:
- **MEASURED**: observed now with a query, log, file or API read.
- **DOCUMENTED**: taken from a commit message, code comment, config or the 09-14 baseline. It was not re-observed at runtime.
- **BLOCKED**: could not be measured read-only.

Caveats:
- The worker log `CURRENT/logs/watchlist_agent_jobs_offpeak.log` starts 2026-09-27 15:00Z, so log statistics cover only 09-27 → now. **MEASURED**
- `watchlist_agent_jobs` now holds rows from 09-03 onward only (6,719 rows), so retention pruning applies. All-time counts are not comparable with the 09-14 baseline. **MEASURED**

The anatomy and the C1–C4 lifecycle list are reused from the baseline. Execution beyond the approval boundary is out of scope (⊘ AGENTS.md §0/§1).

---

## 0. The seven 09-14 breaks: where they stand now

| # | 09-14 break | Now | Label |
|---|---|---|---|
| B1 | An identity-gate rejection permanently excluded the symbol from auto-queue | **Fixed for auto-queue.** `auto_queue_valid_symbols` (`process_watchlist_agent_jobs.py:3408`, commit af662a0ad) skips unvalidated symbols *before* insert, so they stay eligible later. Other producers still enqueue unvalidated symbols: 43 `invalid_symbol` failures in 7 d. `event_router` "PORTFOLIO_FRESH_NEEDED" is 20 of them (bad ticker shape). | MEASURED |
| B2 | A silent synthesis loop re-stamped a stale verdict "actionable" | **Symptom gone, defect remains.** WMT is now `routed/pending`. The log shows 18 "Pending synthesis detected" lines in the whole 09-27→now window (10 symbols). But `_check_pending_synthesis` (`:3384-3405`) still calls `persist_safety` whatever `run_synthesis` returns. | MEASURED (code + log) |
| B3 | The agent-job lane completed 2.9% of what it was handed | **Fixed.** Of 1,244 jobs created in the last 7 d, 1,183 completed (**95.1%**). Created→completed median **0.26 h**, p90 **1.74 h** (14 d, n=2,738). Daily completions are 115–579 on weekdays since 09-21. | MEASURED |
| B4 | The global COST_CAP starved the watch lane | **Fixed.** COST_CAP 0, INPUT_LIMIT 0, CIRCUIT_OPEN 0 in the worker log 09-27→now. Watch-lane spend 7 d: maria $0.32 (483 calls), steph $0.43 (411), risk $0.41 (380), CIO synthesis cron $0.35 (213). All-process spend 7 d is $5.59. | MEASURED |
| B5 | Proposal agent reviews never close | **Worse.** `proposal_agent_reviews` pending is **9,392**, all of them older than 2 d (09-14: 6,336). In 7 d: 371 pending vs 192 reviewed. **55 of 55** proposals approved in 30 d still have an open pending review. | MEASURED |
| B6 | The incubator → proposal lane was dead | **Still dead in the ledger.** `proposal_promotions` has 0 rows. The promoter log ends in a run of "Promoted: 0 Skipped: 12" lines (50 such lines in the current log; a few earlier "Promoted: 1" lines exist). Blocks: `quote_extremely_stale` (BCAR 3,218 h, CBRS 665 h, JCAP 1,144 h) and `invalid_strategy_id: 'swing_trade' not in YAML`. 19 proposals in 30 d carry `discovery_source=incubator`. | MEASURED |
| B7 | The learning loop does not close | **Partially re-plumbed, still open.** The KB application `hit` field is non-null on 6 of 3,331 rows (all `False`). Lessons are still ratified only by `iris_auto_safe`/`iris_bootstrap`, never by a human. The new CIO lesson queue was archived in full (633 → ARCHIVED), with 0 digest candidates. Calibration: 1 agent MEASURED. Counterfactual ledger: NO_LEDGER_YET. See C3. | MEASURED |

**New breaks found in this re-measurement:**
- **N1. AFPT – PENDING thrash grew from 266 to 2,107 flips in 30 d.** The worst proposal flipped 149 times (BAX #10684, flips seconds apart on 09-21). In the last 3 days: 410 flips across at most 19 proposals (3 + 9 + 7 distinct per day, 09-30..10-02). **MEASURED**
- **N2. The watch decision ticket queue stalled after 09-30.** 706 QUEUED, 0 COMPLETE since 2026-09-30 14:00, and 4 `RUNNING` rows orphaned since 09-30. The scheduler keeps adding 40 tickets per run. **MEASURED**
- **N3. 10,217 outcome checkpoints are SCHEDULED with `due_at=null` (`horizon=event-relative`).** They can never come due. 16,068 of 18,259 checkpoints have `entity_type=UNRESOLVED`. **MEASURED**

---

## C1 · Symbol / watchlist item

### (a) Purpose, actors, stores
- **Purpose:** unchanged from the baseline. Turn a noticed ticker into a researched, gated view, then a directive, a re-entry plan, a proposal, or retirement. **DOCUMENTED**
- **Actors:** as in the baseline, plus these changes:
  - `/api/v2/watchlist` now serves active ticker `watch_directives` through a projection, and the legacy `watchlist_items` writers are retired (PRs #1195/#1196, 5c21305a2, b362ecd3d). **DOCUMENTED**
  - Operator watchlist asks stay watched and researched (1746ac82c). **DOCUMENTED**
  - The Maria/CIO watch-review automation is on main (4d3f6e78d). Cron M/W/F 16:05 and 16:20 runs `run_watch_review_workers.py --mode execute`. **MEASURED (crontab)**
- **Stores:** unchanged. **MEASURED** row counts:

| Store | Now | 09-14 |
|---|---|---|
| `watchlist_items` | removed 7,118 · researched 6,860 · active 170 | 7,620 · 5,970 · 142 |
| `symbol_profiles` | 3,299 | 2,980 |
| `watchlist_agent_results` | 3,973, newest 10-03 18:00 | 917 |
| `watchlist_analysis_maturity` | 1,552 rows | 2,446 (pruned) |
| `watchlist_final_synthesis` | 894 | 1,145 |
| `watch_directives` | active 458 · archived 412 · expired 329 · paused 6 | |

### (b) State machines
- `watchlist_items.status` vocabulary is unchanged. `researched` is still a sink: 5,970 → 6,860. **MEASURED**
- `watchlist_agent_jobs.status`:
  - New transition: `deferred → queued`. `requeue_deferred_llm_retries` (`:2877`, commit a21b2b371) re-queues retryable deferred jobs, so COST/CIRCUIT failures defer instead of failing. **DOCUMENTED (code)**
  - In practice: 0 deferred since 09-14 16:51, so the path has not been exercised in the window. **MEASURED**
  - 0 queued/pending/processing at rest. **MEASURED**
- Maturity `analysis_stage`:

| Stage | Now | 09-14 |
|---|---|---|
| final_synthesis_complete | 838 | 1,055 |
| specialist_review_partial | 464 | 575 |
| failed | 238 | 459 |
| routed | 4 | 353 |
| specialist_review_complete | 4 | |
| full_chain_complete | 4 | |

  **MEASURED**
- `final_synthesis_status`: completed 837 · pending 711 · failed 4. **MEASURED**
- Maturity `decision_quality_status`: pending 719 · unsafe 699 · actionable 134. On 09-14 actionable was 457. **MEASURED**
- `watchlist_final_synthesis.decision_quality_status` is still **pending on 894 of 894** rows. The verdict is still written only to the maturity table. **MEASURED**
- `watch_decision_refresh_jobs.state` (this is **N2**):

| State | Now | 09-14 |
|---|---|---|
| SKIPPED_CURRENT | 40,904 | |
| COMPLETE | 16,841 (newest 09-30 14:00) | |
| SKIPPED_LOCKED | 6,377 | |
| FAILED | 3,465 | |
| QUEUED | **706** | 80 |
| RUNNING | **4** (all since 09-30) | |

  **MEASURED**

### (c) Flow (deltas only)
```
intake ══▶ enrich/card ══▶ ENQUEUE (auto-queue validates first ✓ B1) ══▶ gate ══▶ AGENT CALL (95% complete ✓ B3/B4)
   ══▶ maturity ══▶ CIO synthesis (log: AVOID 86 · HOLD 3 · SELL 3 starred verdicts 09-27→now) ══▶ safety (persist_safety unguarded ▓ B2)
   ══▶ 8a directives (servicing ok; defense writer rejected 125× ticker_spec_symbol_missing)
   ══▶ 8b re-entry desk · 8b' decision tickets ✗ STALLED since 09-30 (N2)
   ══▶ 8c bridge (created 0 on 10-02 run; watchlist-source proposals 159/d on 09-21 → 5–16/d since 09-28)
```
**MEASURED**

### (d) Iterations

| Loop | Closes? | Evidence |
|---|---|---|
| Worker drain */15 10-20 ET | yes | 44 runs/day; 100–180 ✓ per weekday 09-28..10-02 (MEASURED) |
| Deferred retry | built, unexercised | 0 deferred since 09-14 (MEASURED) |
| Auto-queue | yes (B1 fixed) | code `:3408` (MEASURED) |
| Pending-synthesis sweep | runs, safety unguarded | 18 detections in 8 d (MEASURED) |
| Decision tickets | **no** | 0 COMPLETE since 09-30 (MEASURED) |
| Hygiene (Sun 09:30) | yes | 10-04: "89 removed, 68 flagged for review" (MEASURED) |
| Directive hygiene (Sun 10:30) | yes, tier 3 waits on operator | "Approve via … --tier 3" (MEASURED) |

### (e) Questions
- **Answered better than on 09-14:** "What does Maria / Steph / Risk conclude?" — 95% of jobs now complete. **MEASURED**
- **Still dropped:**
  - "Is the synthesis verdict any good?" — the WFS quality column is 100% pending. **MEASURED**
  - "Should `researched` rows retire?" — the sink grew by 890 rows. **MEASURED**
  - "Is it at a decision point now?" — tickets are stalled (N2). **MEASURED**

### (f) Measurements
- **7 d jobs by origin (MEASURED):**

| Origin | Completed | Failed |
|---|---|---|
| watchlist_agent_auto_queue | 560 | 4 |
| proposal_agent_queue | 406 | 14 |
| social_scalp_scanner | 120 | 10 |
| advisory_desk_holdings_enqueue | 39 | 3 |
| event_router | 12 | 20 |

- **7 d jobs by agent (MEASURED):**

| Agent | Completed | Failed |
|---|---|---|
| maria | 454 | 14 |
| risk_agent | 358 | 21 |
| steph | 330 | 15 |
| tax_agent | 21 | 4 |
| full_chain | 17 | 0 |

- **7 d failure reasons:** `invalid_symbol` 43 (shape 21, 1–2-char ambiguous 14, not in profiles 8); `off-hours tail deprioritized` 7 expired. **MEASURED**
- **Synthesis verdict skew:** worker log 09-27→now shows `Synthesis: AVOID` 112 vs `HOLD` 4. **MEASURED** This is an unvalidated skew; see risk R4.

### (g) Failure paths now
1. Non-auto-queue producers still enqueue invalid symbols, chiefly `event_router` topic/fresh-needed events. **MEASURED**
2. The safety gate can still re-stamp a stale verdict when synthesis fails silently (B2 code path). **MEASURED (code)**
3. Decision-ticket stall: the orphaned `RUNNING` rows correlate with `SKIPPED_LOCKED` continuing (8–9 per day). **MEASURED**; that the orphans *cause* the stall is INFERRED.
4. `defense` directive writes are rejected (`ticker_spec_symbol_missing`) 125× in the current log. **MEASURED**
5. Two synthesis exceptions: `can't adapt type 'dict'` and `server closed the connection`. **MEASURED**

### (h) Maturity per stage (09-14 → now)

| Intake | Enrich | Enqueue | Gate | Agents | Maturity | Synthesis | Safety | Directives | Re-entry | Decision tickets | Removal |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 | L1 | L1→**L2** (validated before insert) | L1 | L1→**L2** (95% completion, grounded provenance) | L1 | L1 | L1 / integrity L0→**L1** (symptom gone, guard missing) | L1 | L2 | L1→**L0** (stalled) | L1 |

Evidence for each cell is in (b)–(g). **MEASURED**

### (i) Target and exit
- The 09-14 target is unchanged. **DOCUMENTED**
- Exits met:
  - "Symbol never permanently excluded by auto-queue." **MEASURED**
  - "0 COST_CAP refusals on agent jobs for 3 weekdays." **MEASURED**
- Exits still open:
  - `persist_safety` runs only on a synthesis written in this run.
  - Removal covers `researched`.
  - WFS `decision_quality_status` is non-pending.
  - The decision ticket queue drains.

### Delta since 2026-09-14
- Fixed or improved (MEASURED):
  - Agent-job completion went from 2.9% to 95.1%.
  - COST_CAP refusals went to 0.
  - The auto-queue exclusion is fixed.
  - The WMT spin is gone.
  - `routed` backlog went from 353 to 4.
- Fixed in code (DOCUMENTED, PRs #1027/#1031 and later):
  - Retry/defer of capped jobs (a21b2b371).
  - The drain obeys the host cap file (227155390).
  - The watchlist read surface serves directives (#1196).
- Regressed (MEASURED): decision tickets stalled since 09-30 (N2).

---

## C2 · Proposal (to the approval boundary)

### (a) Purpose, actors, stores
- **Purpose:** unchanged. **DOCUMENTED**
- **Actors that changed:**
  - **Scalp lane split (2026-10-03/04, MEASURED crontab line 346-348):**
    - The 9-16 `auto_proposal_generator.py` line now carries `AUTO_PROPOSAL_EXCLUDE_STRATEGIES=momentum_scalp`.
    - A new line `*/10 6-11 * * 1-5 AUTO_PROPOSAL_STRATEGIES=momentum_scalp … auto_proposal_generator.py --today --apply` writes `logs/auto_proposal_momentum_scalp.log`, so the last slot is 11:50.
    - Lane `momentum-scalp-advisory-alerts` is declared in `config/lane_registry.json` (#1430, 464818d95). **MEASURED**
  - **Paper submit is OFF for scalps:**
    - `momentum_scalp.yaml`: `delivery: advisory_alert`, `fast_path_auto_approve: false`, `trading_window_et 06:00–12:00`, `max_spread_pct 8.0`. **MEASURED (config)**
    - Commit b11fd0a69 states that a gated scalp signal becomes one Telegram alert plus a `ScalpAdvisoryAlert@v1` receipt, with no `paper_trade_proposals` row, and that the fast path cannot submit while `fast_path_auto_approve=false`, "whatever the cron's submit flags say". **DOCUMENTED**
    - The 9-16 line still sets `MOMENTUM_SCALP_VALIDATION_SUBMIT=1`. It is neutralised by the exclusion plus the code guard. **MEASURED (crontab)**; the guard is **DOCUMENTED**.
    - The fast-path line `*/2 6-11` runs `--dry-run`. **MEASURED**
  - **Not yet exercised:**
    - `logs/auto_proposal_momentum_scalp.log` does not exist.
    - `data/scalp/scalp_advisory_alerts.jsonl` does not exist in either the persistent or the CURRENT root.
    - The first slot is Mon 10-05 06:00. **MEASURED**
- **Stores:** unchanged. **MEASURED**

### (b) State machine
- Status vocabulary unchanged. **MEASURED**

| Status | All-time | 30 d |
|---|---|---|
| EXPIRED | 8,128 | 1,423 |
| REJECTED | 2,551 | 725 |
| RISK_BLOCKED | 473 | 246 |
| APPROVED | 111 | 46 |
| PENDING | 13 | 13 |
| APPROVED_FOR_PAPER_TEST | 9 | 9 |
| CANCELLED | 1 | 0 |

- **30 d transitions (`proposal_status_events`, MEASURED):**

| From → To | Now | 09-14 |
|---|---|---|
| ∅ → PENDING | 2,462 | 3,251 |
| PENDING → AFPT | **2,211** | 298 |
| AFPT → PENDING | **2,107** | 266 |
| PENDING → EXPIRED | 1,392 | |
| PENDING → REJECTED | 708 | |
| PENDING → RISK_BLOCKED | 246 | |
| AFPT → APPROVED | 50 | |
| AFPT → EXPIRED | 31 | |
| AFPT → REJECTED | 21 | |

- `status` and `lifecycle_status` still disagree: 385 rows in 30 d are EXPIRED/ACTIVE. **MEASURED**
- `expired_at` is set on 2 of 1,423 expired rows, and `expired_reason` is null on 1,421. **MEASURED**

### (c) Flow
```
P0 promoter (0 in ledger ✗) ─▶ P1 create (bridge + pullback_macd; scalp → advisory alert, no row)
 ══▶ P2 enrich/readiness ══▶ P3 agent review (9,392 pending ✗✗) ══▶ P4 approval (median 5.6 min)
 ══▶ AFPT ⟳ PENDING thrash (2,107 / 30 d; 149 on one proposal) ══▶ ⊘ boundary
```
**MEASURED**

### (d)–(e) Iterations and questions
- **Revalidation:** `cleanup_stale_proposals` logs a bounded "revalidation 1/3" (10-01/10-02). **MEASURED**
  - The second-scale flips (BAX #10684: AFPT→PENDING 12:33:03, →AFPT 12:33:16, →PENDING 12:33:16) come from another writer.
  - The event table has no actor column, so the writer is **BLOCKED**.
- **"Do the specialists agree?"** is still not a precondition: 55 of 55 approvals in 30 d have open reviews. **MEASURED**
- **Critic question:** `signal_decision` and `critic_verdict` are null on 755 of 755 proposals created in 14 d. **MEASURED**

### (f) Measurements
- Created 30 d: 2,462. Daily creation fell from ~200 (09-14..09-22) to 34–62 (09-23..10-02), mostly because watchlist-source proposals dropped from 128–159/d to 4–31/d. **MEASURED**
- The last bridge run (10-02 15:31) reported `candidates 18, created 0, refreshed 8, skipped 28`. **MEASURED**
- 30 d sources: watchlist 1,595 · pullback_macd 683 · null 165 · incubator 19. **MEASURED**
- 30 d exits: EXPIRED 1,423 (57.8%) · REJECTED 725 (29.4%) · RISK_BLOCKED 246 (10.0%) · APPROVED/AFPT 55 (2.2%). On 09-14 the shares were 84.1% expired and 0.8% approved. **MEASURED**
- The 9 AFPT rows are all `pullback_macd_reversal` and `not_submitted`, created 10-01..10-02. `updated_at` is re-touched at 10-04 20:15. **MEASURED**
- All 111 APPROVED rows are `execution_status=not_submitted`. **MEASURED**
- Create→approve median: 5.6 min. **MEASURED**
- `momentum_scalp` proposals in 14 d: 1 (EXPIRED 09-24). **MEASURED**

### (g) Failure paths
1. Reviews never close (B5, worse).
2. Approve-before-review: 100% of approvals.
3. AFPT thrash with an unattributed writer (N1).
4. Promoter blocked by stale incubator quotes and YAML drift (`swing_trade`).
5. Critic fields are unpopulated.
6. The expiry clock is unrecorded (`expired_at` 2 of 1,423).

All **MEASURED**.

### (h) Maturity (09-14 → now)

| Stage | Level |
|---|---|
| P0 promoter | L0 → L0 |
| P1 create | L1 → L1 (scalp advisory path L0: unexercised) |
| P2 enrich/readiness | L1 |
| P3 review | L0 effective (worse) |
| P4 approval gate | L1, revalidation integrity **L0** (thrash ×8) |

### (i) Target and exits
- Unchanged from 09-14. **DOCUMENTED**
- Additional exits:
  - An actor column on `proposal_status_events`.
  - A first `ScalpAdvisoryAlert@v1` receipt during 06:00–11:50 ET with 0 new `momentum_scalp` proposal rows.

### C2b · Strategy weekly review gate (Sun 10:30)
- The cron runs `strategy_weekly_review.py`. Last run 10-04 10:30: 30 strategies, **0 transitions**, 0 errors. Every log line is printed twice (duplicate handler). **MEASURED**
- **momentum_scalp:** TESTING, signals 473, real 83 (all `real_family`, journal tag `scalp`), real_exact **0**, paper **3**. The gating total is therefore **3/30** "attributed closed trades for VALIDATED". Only exact-id trades gate (`strategy_weekly_review.py:316-348`). **MEASURED** (`data/portfolios/state/strategy_weekly_review_latest.json` + code)
- With scalp paper submit OFF and delivery `advisory_alert`, the paper count can no longer grow from the scalp lane. **INFERRED** from config plus gate code. The gate cannot reach 30 unless exact-id `momentum_scalp` real trades are journaled.
- **pullback_macd_reversal:** UNVALIDATED with **0 signals** but **109 closed paper trades** and 46 approvals in 30 d. Promotion to TESTING keys on `strategy_signals` only, so the most-approved strategy cannot advance. **MEASURED**
- **swing_trade:** TESTING, 78 real trades, all family-attributed, 0 exact. **MEASURED**
- Maturity: L1. It is deterministic and runs, but it is structurally unable to transition the two strategies that carry evidence.

### Delta since 2026-09-14 (C2)
- Expiry share went from 84% to 58% and approval share from 0.8% to 2.2%. **MEASURED**
- Creation volume fell by about 75% since 09-23. **MEASURED**
- Thrash grew 8×. **MEASURED**
- Pending reviews grew from 6,336 to 9,392. **MEASURED**
- Scalp lane split and paper-submit OFF: installed, not yet exercised. **MEASURED** / **DOCUMENTED**
- Pullback/watchlist expire-on-arrival fix (a464ca7c7) and bridge re-create guard (fead70ee0). **DOCUMENTED**

---

## C3 · Review and learning (advisory side)

### (a) Actors and stores (MEASURED unless noted)

| Actor / store | Now (newest · 7 d) | 09-14 |
|---|---|---|
| `journal_trade_reviews` | 282 · 10-02 · 11 | 231 · 5 |
| `paper_trade_multi_reviews` | 128 · **08-30** · 0 | same (dark) |
| `trade_llm_reviews` | 2,328 · 10-02 · 48 | 2,184 · 36 |
| `trade_thesis_reviews` / `trade_thesis_outcomes` | 2,412 · 500 in 7 d / 129 · **09-16** · 0 | 970 / 94 |
| `agent_recommendation_outcomes` | 7,269 · scored 10-04 11:00 · 108. 30 d verdicts: NEUTRAL 823 · PARTIAL 28 · CORRECT 2 | 7,006 |
| `agent_calibration` (DB) | 364 · 10-04 11:00 · 23. `accuracy_pct` null for maria/steph/risk/alex; tax_agent 100.0 (90 d, n=147); full_chain 100.0 "DECLINING" | 298; steph 95-96% |
| `agent_calibration_events` / `_run_log` | 39,106 · 10-04 12:00 / **0 rows** | 33,106 / 0 |
| `agent_outcome_scores` (declared) | **does not exist** | same |
| `decision_outcomes` | 1,101 · 10-02 · 200 | 1,391 |
| `exit_advisory_outcomes` / `round_trip_outcomes` | 0 / 0 | 0 / 0 |
| `strategy_lesson_rollup` | 977 | 767 |
| KB `advisory_kb_lessons.jsonl` | 3,595 rows, **270 MB**, 14 distinct ids; ratified 3,470 · retired 125; `ratified_by` iris_auto_safe 3,419 · iris_bootstrap 176 · human 0; newest 10-02 | 1,686 rows |
| KB applications | 3,331; `hit` non-null **6** (all False); newest 10-02 | 1,520; 0 |
| CIO lesson queue `data/cio/lesson_promotions.jsonl` | 633 QUEUED (09-28) → **633 ARCHIVED** 10-04 11:36Z by `policy:lesson_queue_p2` | new |
| CIO `lesson_candidates.jsonl` | 782, all PROVISIONAL | 414 |
| Outcome checkpoints `data/cio/outcome_checkpoints.jsonl` | 18,259 distinct. SCHEDULED 15,907 · NOT_PRICE_RESOLVABLE 1,867 · RESOLVED 477 · PENDING_DATA 8 | new |
| Outcome observations | 8,556 rows, newest 10-04 20:20Z | new |
| Darwin `darwin_scorecards.jsonl` | 274 rows, newest 10-02 13:22Z; artifact-quality dimensions (completeness/sentinel/fence), not market outcome | new |
| Darwin runtime timer (hourly, SHADOW) | 10-04 20:01: dispatch total 8 → **REFUSED_STALE 8**, COMPLETED 0 | new |
| CIO nightly reflection | 10-03: cases 3,338 · scored 3,032 · proposals 1 · auto_promotions 0 | cases 2,278 |
| Counterfactual ledger | GET `/api/v3/cio/counterfactuals` → `NO_LEDGER_YET`, 0 rows. Lane `counterfactual-ledger` is `NEVER_SCHEDULED` awaiting a cron grant. Commit 7ed3d90a4 dry run: 289 blocked ideas in 30 d (DOCUMENTED) | new |

### (b) State machines
- **CIO lesson promotion** (`scripts/lib/lesson_promotion.py:31`): QUEUED → PROMOTED | REFUTED | RETIRED | ARCHIVED | RETIRE_PROPOSED. **MEASURED (code)**
  - New rule: a lesson is queued only with ≥ 3 independent, quality-checked settled outcomes. CASE_SUMMARY is never queued. Promotion is operator-only (`lesson_promotion_cli.py decide`). **DOCUMENTED** (be3d55a33) and **MEASURED** (API `rule`, `promotion` fields).
  - 10-04 archive reasons: `case_summary_context` 609 · `no_settled_outcomes` 19 · `insufficient_quality_outcomes` 5. **MEASURED**
- **Lesson digest** (`GET /api/v3/cio/lessons/digest`): `status_counts {ARCHIVED: 633}`, `eligible_total 0`, `candidates []`, `retire_proposed []`, `price_checks LIVE`. **MEASURED**
- **Outcome checkpoint:** SCHEDULED → RESOLVED | NOT_PRICE_RESOLVABLE | OUTCOME_PENDING_DATA. **MEASURED**
  - Of SCHEDULED: 10,217 have `due_at=null` and `horizon=event-relative`. 0 are overdue among those with a due date; the earliest due is 10-05 13:45Z. **MEASURED**
  - RESOLVED by creation month: Aug 302 · Sep 173 · Oct 2. **MEASURED**
- **ExpectationPolicy@v1** (6e87e6898): every new checkpoint carries a stated or `POLICY_DEFAULT` expectation. **DOCUMENTED**
  - In practice: checkpoints created 10-04 are 103 POLICY_DEFAULT vs 49 none; 10-05Z so far 60 vs 1; 10-02/10-03 0 of 309. The policy took effect on 10-04 and is not backfilled. **MEASURED**
- **Darwin:** scores only POSITIVE/NEGATIVE/FLAT. EXPIRED is `UNSCORED_NO_MARKET_OUTCOME`, and 3,032 legacy scores were withdrawn in the projection. **DOCUMENTED** (be3d55a33). Nightly reflection "scored 3,032" matches that count. **MEASURED**

### (c) Flow
```
⊘ trades ─▶ R1 review: journal █ · LLM review █ · thesis reviews █ (500/7 d) · multi-tier ✗ (08-30) · thesis outcomes ✗ (09-16)
 ══▶ R2 outcomes: agent_recommendation_outcomes █ (but 96% NEUTRAL) · checkpoints ▓ (477 resolved / 18,259; 10,217 undatable)
 ══▶ R3 calibration: DB agent_calibration ▓ (accuracy null for 4 core agents; tax 100%) · AgentCalibration@v1 API ▓ (1 agent MEASURED, 8,536 unscored)
 ══▶ R4 lessons: KB reflect █ (auto-ratify) · CIO queue → 633 ARCHIVED · digest 0 eligible
 ══▶ R5 return: calibration_block read per agent call (process_watchlist_agent_jobs.py:1329-1454) · KB → desk (applications to 10-02) · digest → operator UI (cb1ce1652)
 ⊘ counterfactual ledger: built, not scheduled ✗ · Darwin runtime: REFUSED_STALE ✗
```
**MEASURED**, except the code line refs, which are **DOCUMENTED**.

### (d) Iterations

| Loop | Closes? | Evidence |
|---|---|---|
| KB lessons-reflect 19:40 daily | runs (60 s) and self-ratifies | journal 10-03/10-04 Finished; 0 human ratifications (MEASURED) |
| Advisory outcome scorer 18:30 | runs (≈15 min) | journal 10-04 (MEASURED) |
| Outcome scorer → calibration → prompt | runs, signal is empty | 30 d: 2 CORRECT of 853 scored; accuracy null for the core agents (MEASURED) |
| CIO lesson queue → operator promotion | gate works and admitted 0 | digest eligible 0 (MEASURED) |
| Checkpoint resolver hourly :20 | runs, resolves almost nothing | last log tail: `resolved 0 · expired 0 · pending 8 no_price_history_either_end` (MEASURED) |
| Darwin runtime hourly | **no** | REFUSED_STALE 8/8 (MEASURED) |
| Counterfactual | **not scheduled** | NO_LEDGER_YET (MEASURED) |
| Multi-tier reviewer | **dark since 08-30** (35 d) | table newest 08-30 (MEASURED) |

### (e) Questions
- "Did the call work?" can now be asked of new calls (ExpectationPolicy, 10-04 onward). Older calls stay unscorable. **MEASURED**
- "Is this lesson true?" now has an evidence gate (≥ 3 quality outcomes), but **0 lessons pass it**. **MEASURED**
- "What did blocking cost us?" is built but has no ledger. **MEASURED**
- "How reliable is each agent?" has 1 MEASURED agent (alex, n=20, hit 0.75) in the new API; the DB calibration is null or 100%. **MEASURED**

### (f) Measurements
- **7 d throughput (MEASURED):**
  - journal reviews 11
  - LLM trade reviews 48
  - thesis reviews 500
  - multi-tier 0
  - thesis outcomes 0
  - recommendation outcomes 108
  - calibration rows 23
  - checkpoints created 10-02..10-04: 133 / 176 / 152
- **Stuck beyond 2× cadence (MEASURED):**
  - multi-tier reviewer (35 d)
  - thesis outcomes (18 d)
  - `agent_calibration_run_log` (never written)
  - Darwin runtime (refusing stale)
  - 10,217 undatable checkpoints

### (g) Failure paths
1. Outcome scoring is dominated by NEUTRAL (96%), so calibration has no signal.
2. Checkpoints with no due date can never resolve.
3. KB lesson ids collapse: 3,595 rows map to 14 distinct ids in a 270 MB file. Commit c468301d5 says it now streams and caches the file, which used to cost ~910 MB per request. **MEASURED / DOCUMENTED**
4. Self-ratification continues: `iris_auto_safe` only.
5. The counterfactual ledger is unscheduled.
6. The multi-tier reviewer is dark.
7. Darwin refuses stale dispatch.

### (h) Maturity (09-14 → now)

| Stage | 09-14 | Now | Reason |
|---|---|---|---|
| R1 journal / LLM review | L1 | L1 | |
| R1 multi-tier | L0 | L0 | |
| R1 thesis review | | L1 | 500/7 d |
| R2 outcome scoring | L1–L2 | **L1** | NEUTRAL-dominated; checkpoints 2.6% resolved |
| R3 calibration | L1 | L1 | API honest about sample size = L2 on provenance; signal L0 |
| R4 lesson generation | L1 | L1 | |
| R4 lesson evaluation | L0 | **L2** | Evidence gate exists and correctly archived 633 unbacked lessons, but nothing passes it |
| R5 return to prompts | L1 calibration only | L1 | Digest reaches the operator UI |
| Counterfactual | — | L0 | |
| Darwin | — | L0 | |

### (i) Target and exits
- The 09-14 target is unchanged. **DOCUMENTED**
- New concrete exits:
  - Digest `eligible_total > 0` with an operator PROMOTED decision.
  - `/api/v3/agents/calibration` shows ≥ 4 agents MEASURED.
  - The counterfactual ledger is non-empty after the cron grant.
  - Checkpoints with `due_at=null` reach 0, or are re-horizoned.
  - The Darwin dispatcher reaches COMPLETED > 0.

### Delta since 2026-09-14 (C3)
- New governed plumbing (DOCUMENTED + MEASURED present):
  - ExpectationPolicy@v1
  - AgentCalibration@v1 API
  - Lesson-quality P2 gate plus the 633-lesson archive
  - Lesson digest API and UI
  - Darwin market-only scoring (3,032 withdrawn)
  - Counterfactual ledger code and API
  - Commitment settlement / instrument beliefs (804b68651, d2a247dc8)
- Measured effect so far: **0 promoted lessons, 1 calibrated agent, 0 counterfactual rows, 477 resolved checkpoints**. The loop is better instrumented but still does not close.

---

## C4 · Agent-job budget admission

### (a)–(b) Actors and failure classes
- Global cap `LLM_GLOBAL_DAILY_USD_CAP` is loaded from `~/.config/tradeai/llm_global_daily_usd_cap.env`; the worker logs `LLM_GLOBAL_DAILY_USD_CAP_ok=yes (kept)` on every run. **MEASURED**
- The worker runs inside the off-peak gate (`window=off-peak gate=OFFPEAK`). **MEASURED**
- Retryable classes now defer and re-queue (a21b2b371). **DOCUMENTED**

### (c)–(f) Measurements
- Refusals in the worker log 09-27→now: COST_CAP 0 · INPUT_LIMIT 0 · CIRCUIT_OPEN 0. **MEASURED**
- 7 d watch-lane spend: about $1.50 across the 4 paid watch processes, against a $5.59 all-process total. **MEASURED**

### (g)–(i) Maturity
- Global admission: L3 (held).
- Refusal record on the job: L0 → **L1** (deferred note tag + retry path; unexercised).
- Per-lane floor: L0.
- The 09-14 exit "0 global-cap refusals on agent jobs for 3 weekdays" is **met** (09-28..10-02). **MEASURED**

### Delta since 2026-09-14
- The budget starvation is resolved in practice. **MEASURED**

---

## Family maturity score (0–5)

| Lifecycle | 09-14 | 10-04 | Driver |
|---|---|---|---|
| C1 Watchlist item | 1.0 | **1.5** | Jobs 95% complete; gate fix; decision tickets stalled |
| C2 Proposal | 0.8 | **0.8** | Reviews and thrash worse; scalp split safer but unexercised; strategy gate cannot transition |
| C3 Review and learning | 0.9 | **1.2** | Honest evidence gates and APIs exist; measured signal still near zero |
| C4 Budget admission | 1.5 (post-#1015) | **2.0** | 0 refusals for a week; retry path present |
| **Family C** | **≈1.0** | **≈1.4** | |

The scores are DERIVED: the mean of per-stage L-levels, with L0 stages counted. The 09-14 figure is reconstructed from the baseline stage tables. No stage reaches L4.

## Top 5 risks
1. **R1 Approval without review.** 55 of 55 approvals in 30 d have open agent reviews, and 9,392 reviews are pending. The approval gate is effectively unreviewed. **MEASURED**
2. **R2 AFPT – PENDING thrash by an unattributed writer.** 2,107 flips in 30 d, up to 149 on one proposal, seconds apart. The audit trail has no actor column. **MEASURED**
3. **R3 The decision-ticket queue has been stalled since 09-30.** 706 QUEUED and 4 orphaned RUNNING rows, so watch decisions go stale silently. **MEASURED**
4. **R4 The learning signal is empty, which can be misread as learning.**
   - Recommendation outcomes are 96% NEUTRAL.
   - DB calibration is null or 100%.
   - 1 agent is calibrated.
   - 0 lessons are eligible.
   - Synthesis is 112 AVOID vs 4 HOLD, an unvalidated skew.
   - 10,217 checkpoints can never come due.
   **MEASURED**
5. **R5 The strategy lifecycle cannot advance.** momentum_scalp is at 3/30 exact trades while scalp paper submit is OFF (advisory only), and pullback_macd_reversal is stuck UNVALIDATED with 0 signals despite 109 paper trades. The VALIDATED gate is unreachable for the strategies with evidence. **MEASURED** (the momentum_scalp consequence is INFERRED)

## Top 5 recommendations
1. Make P3 a hard precondition of P4. Close a review row as `review_unavailable` with its reason when the job fails, defers or is superseded. Add an approve-before-review alarm (target 0).
2. Add `changed_by` / `source` to `proposal_status_events` through the trigger. Cap AFPT–PENDING flips per proposal (for example 3) with operator escalation, then identify the second-scale writer.
3. Reap `watch_decision_refresh_jobs` RUNNING rows older than N minutes, and alarm when QUEUED rises with 0 COMPLETE for 24 h. Verify the ticket worker that drained the queue before 09-30.
4. Re-horizon or time-box `event-relative` checkpoints (`due_at` required). Then schedule the counterfactual ledger, which needs the operator cron grant, and re-check the AgentCalibration API weekly against ≥ 4 agents. Treat NEUTRAL-dominated scoring as a calibration defect, not as data.
5. Align strategy gating with how evidence is actually produced:
   - Count `strategy_signals` for pullback_macd_reversal, or gate UNVALIDATED→TESTING on closed paper trades.
   - Decide, as an operator decision (§17), how momentum_scalp can reach VALIDATED with advisory-only delivery: exact-id real journal tags or a manual-decision outcome ledger.
   - Guard `persist_safety` on a synthesis written in the same run (closes B2 structurally).

## BLOCKED
- The writer causing the sub-minute AFPT–PENDING flips: there is no actor column.
- The worker log before 09-27: the release-local log was rotated.
- The first scalp advisory alert: not yet scheduled to run (Mon 10-05 06:00).
- Whether the 4 orphaned RUNNING tickets are the cause of N2.
