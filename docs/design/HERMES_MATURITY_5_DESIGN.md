# Hermes Maturity-5 Design — Event-Driven Scope + Outcome-Gated Learning

_Status: DESIGN (operator review pending) · 2026-07-02 · Follows the audit of 2026-07-02
(4,171-symbol clock-driven sweep, one proxy-fed learning loop, write-only tagging, maturity 2/5)._

**Goal:** take every audited dimension to 5/5 and make Hermes near-autonomous — meaning it
governs its own scope, learns from realized outcomes, and proposes its own config changes through
an auditable channel — while staying advisory-only and never touching execution gates or 2FA.

**Design law #1 (from the audit): clock-driven breadth is the enemy.** Scoring 4,111 symbols
every 30 minutes 24/7 produced 98.6–100% unchanged rows. The replacement principle everywhere in
this design: **work happens when information changes, not when the clock ticks.**

**Design law #2 (house standard): a 5 is earned, not claimed.** Same rule as strategy maturity —
each dimension's rating is capped by empirical validation sample, computed live by the maturity
dashboard from DB counts, never hardcoded. The design below ships the *mechanisms*; the 5s arrive
when the samples clear their gates.

---

## Phase 0 — Stabilize (prereq, days)

_**IMPLEMENTED 2026-07-02** (uncommitted, live via cron pickup). Verified: buy-tier matches 1,070
(was 0); all 27 holdings in the capped-200 set (was 4); no-change history-skip active (overnight
runs will skip ~all 200); breaker predicate trips on all-403; tagger advances through new rows
(coverage 1735→1744 in two runs) instead of re-churning; retention cron 03:35 `--days 21`
(dry-run: 241,688 rows past window); scorer-liveness check added to pipeline health; new index
`idx_her_lane_time`. Crontab backup: scratchpad `crontab_backup_pre_phase0.txt`._

Fixes to the in-flight retrofit before anything new is built. Coordinate with the concurrent
session that owns the uncommitted governor/cap/retention work.

| # | Fix | Detail |
|---|---|---|
| 0.1 | Buy-tier case bug | `scripts/lib/watchlist_priority.py` binds lowercase recs against `UPPER(...)` — 0 matches. Uppercase the bind params; add a regression test asserting >0 matches against live research cards. |
| 0.2 | Holdings crowd-out | In the capped fetch, holdings/open-positions/open-proposals become **tier 0 unconditionally reserved slots** (never compete with `in_directive_watch`). Directive names rank below and are ordered by composite score. Test: all holdings present in every capped run. |
| 0.3 | No-change write skip | Skip the `hermes_score_history` INSERT when `composite_score` and components hash are unchanged; write one daily heartbeat row per symbol so freshness monitors don't false-alarm. ~97% write reduction independent of capping. |
| 0.4 | Schedule retention | `hermes_score_history_retention.py` in cron at `--days 21` (not 90) + weekly `VACUUM`. With 0.3 in place the table stabilizes near ~100–200 MB. |
| 0.5 | 403 circuit breaker | In `hermes_external_researcher.py`: N consecutive HTTP 403/401 on a lane → open circuit 60 min, log one SIEM event, DEFER jobs (never fall back to paid — existing invariant). Kills the 6K+ error-calls/week burn. |
| 0.6 | psycopg2 crash class | Jul-1 silent all-day scorer outage. Add an import-preflight to `hermes_pipeline_health.py`: any hermes cron script that exits nonzero twice consecutively → Telegram alert. |
| 0.7 | Taxonomy churn loop | Tagger writes `no_match` sentinel instead of NULL so rows aren't re-selected hourly; move `ALTER TABLE IF NOT EXISTS` to a one-time migration. (Whether taxonomy lives at all is Phase 4's call.) |

**Exit criteria:** capped run contains 100% of holdings; score-history writes <8K rows/day;
external error-call rate <5%; zero silent-crash days.

---

## Phase 1 — Event-Driven Scope (kills "4K every 30 min")

_**IMPLEMENTED 2026-07-02** (uncommitted). Schema: `watchlist_items.scope_tier/scope_expires_at/
last_trigger_at/trigger_source`, `scope_governor_audit`, `hermes_score_event_queue` (unique
pending-per-symbol), `config/hermes_scope_governor.yaml`. Governor rewritten (S0=87, S1≤400,
S2≤320, S3=3,330; live=800=cap; deterministic selection; converges to 0 changes on repeat runs —
initial flapping fixed by ordering the directive top-N query and shedding unclaimed TTL-holders
before claimed symbols). Event feeder live (catalyst/news/finviz/directive/proposal → queue +
audited S3→S1 reactivation; 27 events + 8 reactivations on first apply). Scorer tier-aware:
S0 15m / S1 30m market hours, S2 premarket 7h, S0 hourly off-hours, events always; legacy capped
fetch kept as ungoverned-DB fallback. Research scheduler: S3 symbols demoted to T3-COLD
(T1-WATCH 469→256). Cron: scorer `*/15` (llm_priority_guard removed — zero LLM calls), governor
`7,37`, feeder `*/5`. Backup: scratchpad `crontab_backup_pre_phase1.txt`. Known gaps: 7 of 34
holdings absent from watchlist_items (funds — never scoreable, pre-existing); cap-shed can
preempt event-reactivated names between governor runs (the event-lane rescore still happens)._

### 1.1 Universe = ledger with TTLs, not a roach motel

`watchlist_items` gains `scope_tier`, `scope_expires_at`, `last_trigger_at`, `trigger_source`.
The **scope governor** (committed version of today's draft) becomes the sole owner of tier
membership, running every 30 min, fully autonomous within budget:

| Tier | Membership | Target size | Entry | Exit |
|---|---|---|---|---|
| **S0 pinned** | holdings, open positions, open proposals, operator directives | ~80 | automatic | position closed / directive archived |
| **S1 active** | score ≥70, catalyst <48h, active watchlist, GO/approval-queue names | ~200–400 | trigger event | 14d without a fresh trigger → S2 |
| **S2 warm** | incubator, strategy_watchpool, directive top-5-per-directive | ~300 | governor promotion | 30d no trigger → S3 |
| **S3 archived** | everything else (the current 4,005 graveyard) | unbounded | demotion | catalyst/news/finviz event → instant S1 reactivation |

Hard invariants: total S0+S1+S2 ≤ **800** (config); `in_directive_watch` capped at top-5 per
directive by composite score, global ≤200; every `ai_discovered` entry gets a 14-day TTL to earn a
trigger or archive; archive is cheap and reversible (status flip, no deletion) so nothing is lost.
Governor actions land in a `scope_governor_audit` table with before/after and reason — same
auditability standard as `hermes_autotune_audit`.

### 1.2 Scoring becomes tiered + event-driven

Replace the flat 2×/hour full sweep in `hermes_watchlist_scorer.py`:

- **S0:** every 15 min market hours, hourly off-hours. (~80 syms)
- **S1:** every 30 min market hours only. (~400)
- **S2:** once daily (pre-market). (~300)
- **S3:** **never on the clock.** Scored only on an event.
- **Event lane:** a lightweight `score_event_queue` fed by existing pipelines — catalyst_events
  insert, news_articles insert, finviz early-lane hit, directive hit, proposal creation, RVOL/gap
  detection from ticker snapshots. Any event → immediate rescore of that symbol regardless of tier
  (and S3→S1 reactivation via the governor). This is where scalp-speed freshness comes from —
  an S3 name with a 5-min-old Finviz catalyst gets scored within a minute, which the old
  4K sweep could never do despite 48 runs/day.

**Volume math:** market day ≈ 80×26 + 400×13 + 300×1 + ~500 events ≈ **8.1K score computations/day**
(vs ~197K), and with write-on-change ≈ **2–4K rows/day** (vs 157K). Off-hours drops to ~2K
computations. Freshness on names that matter goes *up* (event lane), cost drops ~97%.

### 1.3 Research follows the same shape

`research_scheduler.py` already has the right tiers — bind them to scope tiers (T0-HOLD=S0 …
T3-COLD=S3) so one governor owns both scoring and research scope. Budget guard invariants
unchanged (broad-universe-never-LLM, fail-closed, no paid fallback).

---

## Phase 2 — The Outcome Spine (the thing that makes 5/5 possible)

_**IMPLEMENTED 2026-07-02** (uncommitted). `hermes_outcome_ledger` (UNIQUE subject_type+subject_id)
+ `daily_close_cache` (228K closes from market_quotes/price_cache; SPY calendar to 2020) +
`config/hermes_outcome_grader.yaml` + `scripts/hermes_outcome_grader.py` (seed+grade, zero LLM,
~10-17s/run). Seeded 22,715 claims: 3,385 promotions, 15,738 external recs, 3,400 research rows,
192 trades. Graded so far: promotions 32 hit / 54 miss / 21 neutral (only claims ≥20 sessions old
— May 31–Jun 3 vintage; ~150-300 more mature daily); research 853 actioned-hit / 971 not-actioned;
trades 104 hit / 29 miss on realized R/P&L; `downstream_outcome` filled on 1,824 research rows
(was 100% NULL). Verdict semantics per type: promotions/external recs = ±2% 20-session excess vs
SPY (direction-parsed for recs); research = actioned-within-14d; trades = realized R sign. Math
hand-verified (XOS +40.2 excess). Cron nightly 02:50. External recs all pending — none are 20
sessions old yet (calls exploded Jun 18+); first rec verdicts land ~Jul 16._

One canonical join from Hermes output to money. New table `hermes_outcome_ledger`:

```
(id, subject_type            -- score_promotion | research_row | tag | source | external_rec
 , subject_id, symbol
 , emitted_at                -- when Hermes said it
 , claim                     -- promoted / graded / tagged momentum_scalp / lane=grok said BUY
 , horizon                   -- 5d / 20d / trade-linked
 , outcome_ret_5d, outcome_ret_20d   -- vs SPY, filled by nightly job
 , trade_instance_id, realized_r     -- when a real/paper trade followed
 , graded_at, verdict)               -- hit | miss | neutral
```

Nightly `hermes_outcome_grader.py` (pure SQL + price cache, zero LLM):

1. **Promotions** — every `hermes_promotion_audit` row graded at +5/+20 sessions vs SPY.
   6,488 rows backfillable on day one → immediate statistical power.
2. **Research rows** — populate the existing (100% NULL) `downstream_outcome`: did a proposal /
   trade / directive hit follow within 10 sessions?
3. **Trades** — join `trade_instances` / validation-tracker R-multiples to whatever Hermes context
   existed at entry (score snapshot, research rows, tags, lanes). This is the R-multiple feed the
   audit found structurally missing.
4. **External recs** — grade `hermes_external_research` recommendations the same way (the
   feedback-loop script's design, actually scheduled and actually joined).

**Everything in Phases 3–5 reads only this ledger.** One grader to test, one place outcomes live.

---

## Phase 3 — Learning Loops v2 (outcome-gated, clamped, shadowed)

_**IMPLEMENTED 2026-07-02** (uncommitted). `scripts/hermes_outcome_learning.py` (cron 03:05, after
grader) + `config/hermes_outcome_learning.yaml` + tables `hermes_promotion_thresholds`,
`hermes_lane_usefulness`; ledger gained frozen `components` (17,448 backfilled — retention-proof).
**Ratchet frozen**: self-tune grafts ONLY `OUTCOME_LEDGER|eligible=1` suggestions, needs ≥5
eligible days/14, additive ±0.02 clamp, 0.10 weekly drift cap (verified: `gated_persistence`,
eligible_days=0); drift-calibration cron retired (commented). **Promotion gate live with teeth**:
momentum_catalyst precision 0.32 and ticker_thesis_challenge 0.33 (baseline 0.372) → min_conf
0.75; coordinator promote query joins thresholds (unmeasured types stay ungated per directive B);
staged >7d archives nightly. **Sources**: 8 domains outcome-retired (apnews 4%, cnbc 8%…, baseline
yield 53.5%, retire <28%); nightly curation patched so OUTCOME_LEDGER verdicts outrank
pipeline-throughput yield and markers survive note rewrites; exact source_name matching (substring
ILIKE caused a cross-domain reinstate — fixed). **Lanes**: usefulness table + scheduler weighted
rotation with 0.15 floor (uniform until ≥30 graded recs, ~Jul 16). **Weights**: correctly gated —
0 pairs today because the graded vintage predates Jun-9 component history; pairs accumulate as
post-Jun-9 claims mature._

House lifecycle applies to every loop: **shadow → advisory → auto**, promotion only on evidence,
demotion automatic on degradation, kill switch honored.

### 3.1 Weight calibration (replaces the drift ratchet)

- **Freeze current auto-graft now** (config flag) — the audit showed `analyst` 0.16→0.52 in 4 days
  on 6-hr price drift with a multiplicative ratchet.
- New calibration target: blended forward-return (5d, vs SPY) from the outcome ledger + realized-R
  where trades exist, weighted by sample count — not 6-hour drift.
- Update rule: **additive, clamped** (`w += clip(η·pred, ±0.02)`, per-week total drift cap ±10%,
  weights renormalized). No compounding ratchet.
- Graft gate (reuse `evaluate_shadow_efficacy.py` standard): **n ≥ 20 graded samples per factor
  AND shadow beats live** — shadow scorer runs both weight sets, ledger grades both, graft only on
  outperformance over ≥2 weeks. Retention window must exceed calibration window (fixes the
  30d-purge / 45d-window self-cannibalization).

### 3.2 Promotion gate learns

Auto-promote confidence threshold (currently ungated 0.5) becomes a learned per-`research_type`
threshold from ledger promotion precision: types with hit-rate ≤ baseline get their threshold
raised or drop to staged-for-review. Bad promoters silence themselves.

### 3.3 Source curation on outcome yield

Replace self-referential yield ((promoted+embedded)/total) with **ledger yield**: share of a
source's research that graded `hit` or preceded an actioned proposal. Auto-retire (≥10 samples,
yield <baseline−1σ) actually fires; auto-reinstate on re-test. LLM taste check stays as a floor,
stops being the only demotion path.

### 3.4 Lane routing learns

`usefulness_score` per lane/type from ledger grades finally gets a consumer: the research
scheduler weights lane selection by it (grok vs chatgpt vs local per research_type). Circuit
breaker (0.5) feeds the same table.

---

## Phase 4 — Tagging That Earns Its Keep

_**IMPLEMENTED 2026-07-02** (uncommitted). `scripts/hermes_tag_engine.py` (cron 03:20) +
`config/hermes_tag_engine.yaml` + `hermes_tag_efficacy` table. **Taxonomy cron retired**
(commented; zero readers repo-wide). **strategy_tags v2**: vocabulary = active
`strategy_registry.strategy_type` slugs; rules from config synonyms first, capped local-LLM
refine (temp 0, constrained, 240s wall-clock, symbol-linked rows only), fallback stays
`general_research`; drains ~400 fallback rows/night from the 3,254 backlog (→<15% in ~2 weeks).
**quality_score v2 live**: continuous blend (0.6 rule + 0.4 ledger action prior, shrink k=10) —
stddev 0.109, 29 distinct values (was 2 point masses); pipeline-health check #6 alerts on
re-collapse. **Tags are falsifiable**: first lift numbers — momentum_scalp +0.042 (n=872),
catalyst +0.023 (n=934), social_route +0.489 (n=5, below gate), `general_research` −0.292 and
`holdings` −0.080 FLAGGED. Gotcha: the two-connection retag design is required — the GPU-queued
LLM batch idles the DB connection past its keepalive (first run died on SSL disconnect)._

- **Kill the 3-axis taxonomy cron for market content** (zero readers found repo-wide). Keep slugs
  only where a consumer exists (retirement/tax content for advisory agents). Deleting write-only
  work is a maturity *increase*.
- **strategy_tags v2:** vocabulary = the strategy registry (single source, no ad-hoc regex
  families), assignment = existing local-LLM classify path (gemma, temp 0, constrained to
  registry slugs) **only for rows a consumer can reach** (symbol-linked or report-bound; the 48%
  symbol-less backlog rows get type-level tags only). Owner: cron, not ad-hoc backfills.
  `general_research` fallback target <15% (from 50%).
- **quality_score v2:** continuous 0–100 from the existing critique pipeline features + ledger
  outcome prior of the same research_type/source. Two-point-mass distribution is a bug metric —
  dashboard alerts if stddev collapses.
- **Tag accuracy is graded:** ledger verdicts per tag family; a tag that doesn't out-predict its
  base rate gets flagged for vocabulary revision. Tags become falsifiable.

---

## Phase 5 — Autonomy & Honest Maturity

_**IMPLEMENTED 2026-07-02** (uncommitted) — ALL PHASES 0–5 NOW LIVE. **5.1**
`scripts/hermes_config_governor.py` (cron 03:40): rails-pressure detectors (scope-cap
pressure/underfill, weight-clamp pressure, promotion hard-floor) file `config_change_proposals`
rows with evidence + rollback plans; auto-lane remains the clamped audited loops; one pending
proposal per target_key; alert on filing. **5.2** pipeline health extended with correctness
watchdogs #7–#10 (write-volume >20K/day, error-call burn >20%, promotion-precision <0.25 on n≥50,
S0 coverage <80%); breaches open a daily-deduped `escalation_queue` item (category
hermes_watchdog, smallint severity=2) — verified live: #7 caught the transition-day 81K writes
and opened escalation #339. **5.3** `scripts/hermes_maturity_gates.py` (snapshot cron 07:20) —
six dimensions, ~21 gates, ALL computed live; 5 requires all-gates-pass held 30 consecutive daily
snapshots (`hermes_maturity_history`); board injected into `build_maturity_report` as
`maturity_gates` (API/UI needs a server restart to pick up the changed import). First honest
board: **overall 2.3→2.7 same day** (scope 4, autonomy 3) as Phase-1-4 effects land — matches the
audit's 2/5, confirming the board doesn't flatter. Also fixed this phase: event feeder treated
directive-hit RESTAGES as fresh events (274/window → universe 1,090>cap); now first-ever-pair
only — verified 0 fake events, governor back to exactly 800._

### 5.1 Self-governance channel (near-autonomous, still safe)

Hermes proposes its own config changes through the existing (empty) **`config_change_proposals`**
table instead of editing configs directly: scope budget changes, cadence changes, threshold
moves, source retirements outside auto-bounds. Small pre-bounded moves (weight clamps, per-source
thresholds inside declared rails) auto-apply with audit; anything outside rails or touching
budgets/caps → operator approval via the existing Telegram/web approval surface. Same pattern as
the trading gates: autonomy inside rails, human on the rails themselves.

### 5.2 Self-healing

Extend `hermes_pipeline_health.py` from liveness to **correctness watchdogs**: trigger-coverage %
of scored universe, no-change-write ratio, error-call %, promotion-precision trend, calibration
drift. Breach → auto-open an escalation-queue item (existing coder-dispatch path, advisory PR).

### 5.3 Honest maturity dashboard

Replace hardcoded `autonomy_pct` with computed dimension scores. **A dimension shows 5 only when
its gate clears:**

| Dimension | 5/5 gate (computed live) |
|---|---|
| Scope | ≥80% of scored symbols have an active trigger; 100% holdings coverage every run; universe ≤800; governor actions ≥1/day with 0 manual overrides needed for 30d |
| Research | T0/T1 SLA compliance ≥95%; ≥60% of proposals preceded by Hermes research (from 36%); external error-calls <2% |
| Tagging | fallback tag <15%; ≥1 tag family with statistically significant outcome lift (n≥50); quality_score stddev healthy |
| Efficiency | score rows/day ≤5K; score-history ≤300 MB steady-state; GPU challenger duty <5% idle-tick; $0 unauthorized paid LLM |
| Closed loop | ≥20 graded samples/factor feeding calibration; ≥100 graded promotions with precision > baseline; ≥1 shadow→live graft won on evidence; ≥1 source auto-retired on outcome yield |
| Autonomy | 30 consecutive days: zero silent failures, all config drift via proposal channel, self-healing caught ≥1 real issue |

### Sequencing & effort

P0 days (blocked only on coordinating with the in-flight session) → P1+P2 in parallel (~1 week;
P2 backfill gives instant sample power) → P3 gates start counting the day P2 lands (calendar time,
~4–6 weeks to n≥20 per factor) → P4 anytime after P2 → P5 last. **Honest expectation: mechanisms
in ~2–3 weeks of build; the all-5 board in ~6–10 weeks, because the 5s are sample-gated — exactly
like momentum-scalp's 4.4 cap.** Claiming them sooner would repeat the failure mode this design
exists to fix.

### Non-goals / invariants preserved

Advisory-only; no new live order surfaces; 2FA and execution gates untouched; no paid-LLM
automation; fail-closed budget guard unchanged; kill switch (`HERMES_DISABLED`) honored by every
new job; all destructive-ish actions (archive, retire, graft) reversible with audit rows.
