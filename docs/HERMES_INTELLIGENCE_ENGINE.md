# Hermes Intelligence Engine — ranked, intelligence-driven watchlist (canonical)

**Status:** shipped 2026-06-09 (H-1 → H-5). Advisory-only — never gates execution. Paper mode.
Builds on the Watch Directives feature ([`WATCH_DIRECTIVES.md`](WATCH_DIRECTIVES.md)) + the watchlist
enrichment sweep.

**Goal:** a dynamic, ranked watchlist that surfaces the highest-conviction opportunities by combining
news/social, analyst, sector, competition, momentum, and trade-setup quality into one tunable score.

## Data foundation (reused, not reinvented)
- `watchlist_items` (rsi/trend/score/price from the **enrichment sweep**, `watchlist_enrichment_sweep.py`)
- `intelligence_entities` (per-ticker social_score/sentiment, rvol, confluence, catalyst, sector, industry)
- `data/runtime/pro_analyst_pills_latest.json` (analyst consensus, target upside, internal-vs-Street divergence)
- sector ETF vs SPY momentum from `market_quotes` (same as `/api/v2/sectors/monitor`)
- `hermes_research_intelligence` (Hermes's own research/theses)

## H-1 — Composite scorer (`scripts/hermes_watchlist_scorer.py`, cron `*/15 * * * *`)
**Tier-mode since Phase 1 (2026-07-02,** [`docs/design/HERMES_MATURITY_5_DESIGN.md`](design/HERMES_MATURITY_5_DESIGN.md)**):**
the universe is no longer a flat 4.1k active/researched sweep. `hermes_scope_governor.py`
(cron `:07/:37`) owns `watchlist_items.scope_tier` — S0 pinned (holdings/positions/proposals/operator
tickers, scored every 15m), S1 active (trigger-earned, every 30m market hours), S2 warm (premarket
daily), S3 archived (never on the clock; `hermes_score_event_feeder.py` cron `*/5` enqueues immediate
rescoring + audited S3→S1 reactivation on catalyst / news / finviz / first-ever directive hit /
proposal). Hard rails in `config/hermes_scope_governor.yaml` (S0+S1+S2 ≤ 800); every tier change
lands in `scope_governor_audit`. History INSERTs are skipped when composite+rank are unchanged
(20h heartbeat), and `hermes_score_history_retention.py` (cron 03:35, 21d) prunes the table —
together ~157K rows/day → ~3-6K. One weighted 0-100 score per name, ranked highest-first. Factors
(each normalized 0-100):

| Factor | Source |
|---|---|
| technical_momentum | rsi posture + trend + rvol + confluence |
| setup_quality | sweep score + Bucket-2/3 classifier qualification |
| analyst | pro-analyst pills: consensus + target upside + divergence |
| social_sentiment | intelligence_entities social score + sentiment |
| sector_strength | sector ETF vs SPY |
| news_catalyst | verified catalyst presence |
| risk_reward | target/stop from watchlist_strategy_cards |

- **Weights** live in `config/hermes_score_weights.yaml` — auto-grafted only by the outcome-gated
  loop (see H-4).
- **No fabrication:** missing factors are dropped and remaining weights re-normalized.
- **Coverage-confidence penalty:** `composite = raw * (0.55 + 0.45 * coverage)` so a name strong across
  many dimensions beats a thin 2-factor RVOL pop. Confidence = `0.4 + 0.6*coverage`.
- Writes `hermes_composite_score` / `hermes_rank` / `hermes_score_components` (jsonb) / `hermes_scored_at`
  on `watchlist_items`, plus an append-only snapshot to `hermes_score_history`.

## H-2 — Intel card + ranked board
- `GET /api/v2/hermes/intel/{symbol}` — structured card: composite/rank/confidence, factor breakdown,
  analyst / sector / social views, **trade-setup recommendation** (type · entry · invalidation ·
  conviction · why, via `_hermes_setup`), catalysts, risks (`_hermes_risks`), provenance.
- `/v3/watchlist` sorts by `?sort=hermes` (highest-first), shows a **★#rank · score** badge per card,
  dedups symbols, and drills into the intel card.

## H-3 — Competition / peer analysis (`_hermes_competition`)
In the intel card: peer group from the same **industry** (fallback **sector**), relative rank +
strength by Hermes score (e.g. "#1 of 3 in Semiconductors, leading peers"; peers AMD/MOBX/MX/IPWR).
Honest "no peers" when there's no intelligence coverage (limited to ~88 names with industry data).

## H-4 — Training / calibration (outcome-gated since Phase 3, 2026-07-02)
**The drift calibrator (`hermes_score_calibration.py`, 6-hour price-drift pairs) is RETIRED** — its
cron is commented out and `hermes_autonomous_self_tune.py` no longer grafts its suggestions (the
multiplicative ratchet tripled a weight in 4 days on a ~0.4% proxy edge). The feedback loop is now
`scripts/hermes_outcome_learning.py` (cron 03:05, after the outcome grader): per-factor
predictiveness from **graded 20-session excess returns + realized R (2x)** in
`hermes_outcome_ledger`, additive suggestions clamped ±0.02, shadow-vs-live spread check →
`hermes_weight_calibration` rows tagged `OUTCOME_LEDGER`. Self-tune grafts **only** eligible rows,
needs ≥5 eligible days in 14, and respects a 0.10 weekly total-drift cap — all audited in
`hermes_autotune_audit`. Gated `insufficient_samples` until ≥10 high + ≥10 low graded pairs exist
per factor. The same nightly run also learns **promotion thresholds** per research_type
(`hermes_promotion_thresholds`, enforced by the coordinator — momentum_catalyst measured 0.32
precision → 0.75 confidence gate), **source retirement on outcome yield**, and **lane usefulness**
(`hermes_lane_usefulness` → weighted external rotation in the research scheduler).

## H-5 — Alerting (`scripts/hermes_score_alerts.py`, cron `15,45 * * * *` `--send`)
Compares each symbol's two latest snapshots and flags: composite **spike/drop** (≥8), **rank surge**
(≥20), **analyst divergence flip**, **sector/setup factor regime shift** → `alert_events` (idempotent
`alert_uid`, no re-spam) + Telegram to both chat IDs (`6993102664`, `8797974247`).

## H-6 — Top-N external-LLM curation, badges, full theses
`scripts/hermes_top20_external_intel.py` curates the **top-20 Hermes-ranked** names into a well-formatted
context (rank, composite, factor reads, RSI/trend) and sends each to the **FREE external LLM lanes** via
`hermes_external_researcher.py`, storing the verdict in `hermes_external_research`. **No API keys — OAuth only.**

- **Grok** (free xAI OAuth, xai proxy) — headless; the **automated** lane, cron `5 */2 * * *` (`--lanes grok`).
- **ChatGPT** (free **openai-codex OAuth** — your ChatGPT subscription, NOT the metered OpenAI API). The
  v0.16 codex one-shot returns "no final response" headless because it needs a real terminal; wrapping it
  in a **pseudo-TTY** (`script -qec 'hermes -z … --provider openai-codex -m gpt-5.4' /dev/null`) makes it
  finalize. So ChatGPT is **manual/optional** via the **`✦ Run ChatGPT on Top 20`** button on
  `/v3/watchlist` → `POST /api/v2/hermes/curate-top20` (launches the run in the background, lockfile-guarded;
  `GET` returns `running` + `N/20`). Codex headless-readiness is tracked in
  `data/runtime/hermes_llm_capabilities.json`.

Skips a (symbol, lane) pair curated in the last 12h. **Surfacing:**
- `GET /api/v2/hermes/external-intel-map` → per-symbol `{lane, model, recommendation, at}` (14d) → `/v3/watchlist`
  renders a **`✦ Grok` / `✦ ChatGPT` badge** per curating LLM (tooltip = verdict + curation date).
- The **intel-card drawer** (`/api/v2/hermes/intel/{symbol}` → `external_intel`) shows each LLM's **full
  thesis**: recommendation, evidence bullets, counter-view, risk flags, confidence, timestamp — alongside
  the Hermes trade-setup recommendation + competition peers.

## H-7 — Site-wide subject enhancement (free Grok/ChatGPT everywhere)
`scripts/hermes_subject_enhance.py` — one generic engine enhances ANY subject with the free OAuth lanes
(reuses `hermes_external_researcher`: OAuth-only, $/secret redaction, advisory). `$`-free context +
subject-specific question per item; per-type freshness (scalp 4h, rest 12h); stored in
`hermes_external_research` with `trigger_reason='enh_<type>'`. Grok-auto crons per type; ChatGPT manual.

| Type | Question | Surface |
|---|---|---|
| `scalp` | gap-and-go/momentum: go/wait/avoid + trap risk + entry/stop | Trading → **Scalp** tab (READ-ONLY — screeners untouched) |
| `proposal` | pre-approval challenge: bear case, R:R, invalidation | **Proposals** card (`ProposalCard`) |
| `position` | hold/trim/exit + risks | **Open Trades** + **Protection** cards |
| `closed_trade` | post-mortem + one lesson | **Journal** closed-trade rows |
| `sector` | tailwind/headwind narrative | **Sectors** hub card badge |
| `report` | second read / focus | **Home → Morning Command** ("Hermes second read" panel) |

**Generic surfacing:** `GET /api/v2/hermes/subject-intel?type=&key=` (full theses) + `subject-intel-map?type=`
(badges). `DetailDrawer` fetches subject-intel whenever a drill passes `subjectType`/`subjectKey`, so each
surface is a one-line wire showing the **✦ Grok / ✦ ChatGPT** badge (tooltip = verdict + date) + the full
thesis (recommendation, evidence, counter-view, risks, confidence) in the drawer.

## Schema (additive)
- `migrations/2026-06-09_hermes_composite_score.sql` — score/rank/components/scored_at on watchlist_items.
- `migrations/2026-06-09_hermes_score_history.sql` — `hermes_score_history` (append-only) +
  `hermes_weight_calibration`.

## The closed-loop map — every outcome→behavior edge, in one place

Each loop below is **automated** (no human in the loop inside its rails), reads ONLY
`hermes_outcome_ledger` (graded nightly by `hermes_outcome_grader.py`), is **sample-gated**
(does nothing but report until its gate clears), and leaves an audit trail:

| # | Outcome signal | What it changes | Where enforced | Audit trail | Gate / state |
|---|---|---|---|---|---|
| 1 | 20-session excess return + realized R per factor | live scoring weights (`config/hermes_score_weights.yaml`) | `hermes_outcome_learning.py` → `hermes_autonomous_self_tune.py` graft (additive ±0.02, ≥5 eligible days/14, 0.10 weekly drift cap, shadow-beats-live) | `hermes_weight_calibration` + `hermes_autotune_audit` | n≥10 hi + n≥10 lo graded pairs per factor |
| 2 | promotion precision per research_type | auto-promote confidence gate | coordinator promote query joins `hermes_promotion_thresholds` | table rows w/ reason + `hermes_promotion_audit` | n≥10/type (live: momentum_catalyst 0.32 → 0.75 gate) |
| 3 | per-domain actioned yield | `research_sources.active` (research depth by source) | `hermes_outcome_learning.py`; nightly curation cannot override (`OUTCOME_LEDGER` markers) | `notes` markers | n≥10/domain (live: 8 retired) |
| 4 | per-lane rec hit-rate | external lane rotation weight (grok vs chatgpt) | `research_scheduler._lane_rotation()` (0.15 floor) | `hermes_lane_usefulness` | ≥30 graded recs (pending ~Jul 16) |
| 5 | per-tag actioned lift + avg realized R | tag vocabulary review (negative-lift tags flagged) + quality prior | `hermes_tag_engine.py` | `hermes_tag_efficacy` (`lift`, `trade_n`, `avg_realized_r`) | n≥15/tag (live: 2 flagged) |
| 6 | research_type actioned rate | continuous `quality_score` (ranks which research reaches prompts/reports) | `hermes_tag_engine.quality_v2` blend | `quality_score` distribution (health check #6 guards collapse) | live |
| 7 | trigger freshness / catalyst events | scope tier membership (what gets scored & researched at all) | `hermes_scope_governor.py` + event feeder | `scope_governor_audit` | live, every 30 min + events |
| 8 | rails-pressure (any loop pinned at its clamp/cap) | **proposals only** — `config_change_proposals` for operator approval | `hermes_config_governor.py` | proposal rows w/ evidence + rollback | live nightly |

**Compounding evidence** is measured, not asserted: `hermes_maturity_gates.py` snapshots all ~21
gates daily into `hermes_maturity_history` and reports `trend_vs_7d` (score + gates-passed deltas
per dimension). A maturing system trends up; a wheel-spinner is flat. Dashboard:
`GET /api/v2/hermes/maturity-dashboard` → `maturity_gates`.

## Scope governance is an active agent, not a policy file

`hermes_scope_governor.py` runs every 30 minutes with **authority to promote/demote any symbol**
between S0–S3 based on live edge signals — holdings/positions/proposals (S0 pins), composite ≥70,
catalyst <48h, capped directive hits (S1), incubator/watchpool freshness (S2), TTL expiry and cap
pressure (demotions) — plus the `*/5` event feeder reactivating archived names within minutes of a
catalyst/news/Finviz/first-directive/proposal event. Every decision is a `scope_governor_audit`
row with reason. It converges (0 changes on a quiet re-run) and its rails live in
`config/hermes_scope_governor.yaml`; when the rails themselves bind, it cannot widen them — that
goes through the config-proposal channel (loop 8).

## Tagging metrics & downstream consumers (honest ledger)

- **Coverage:** strategy_tags ~99.9%; fallback-only (`general_research`) 49.7% → draining ~400
  rows/night toward the <15% target (registry-vocabulary retag, capped local-LLM refine).
- **Tag→outcome correlation** (`hermes_tag_efficacy`, updated nightly): momentum_scalp **+0.042
  lift** (n=872, z>1.96), swing +0.040 (n=783, significant), catalyst +0.023 (n=934);
  `general_research` **−0.292 FLAGGED**, `holdings` −0.080 FLAGGED. `avg_realized_r`/`trade_n`
  per tag joins ledger trades to prior tagged research (sparse today — fills with the validation
  tracker sample).
- **Real consumers:** `hermes_data_access.py` (quality-ranked top-3 per symbol → all LLM prompts),
  `analyst_report_builder` (quality-ordered), news bridge (`strategy_tags[0]` →
  `news_articles.strategy_type`), directive discovery (tag text search), maturity gates.
- **Phase 6 consumers (2026-07-02) — the former write-only surfaces now read back:**
  **AI Trade Critique** (`journal_ai_critique.py`, `ai_critique_v3_hermes`) appends the symbol's
  Hermes block (score/rank, graded research, lane opinions) to the coach prompt — advisory,
  deterministic facts stay ground truth; **Stop Management advisory**
  (`holding_protection_advisor.py`, `protection_advisor_v2_hermes`) gets a 700-char Hermes block
  for rationale color, explicitly subordinate to the HARD RULES / family bands;
  **Validation Tracker** (`momentum_scalp_validation_tracker.py`) reports
  `hermes_context` — share of confirmed trades with prior Hermes research (first reading: **0/2**,
  a real coverage finding) + scalp-relevant tag efficacy incl. `avg_realized_r`. All three
  fail-open (a Hermes outage never blocks a critique/stop/validation run).

## Resource efficiency — measured before/after (2026-07-02 cutover)

| Metric | Before (audit) | After (tier-mode) | Ongoing tracking |
|---|---|---|---|
| Score computations/day | ~197K (4,111 syms × 48 runs) | ~8K (tier plans + events) | gate `score_rows_per_day` |
| `hermes_score_history` writes/day | ~157K (98.6–100% unchanged dupes) | ~3–6K (no-change skip + cap) | same gate, daily snapshot |
| Table size | 1.85 GB (#2 in DB), unbounded | 21d retention → ~100–200 MB steady | gate `score_history_size_mb` |
| External LLM calls/day | 6,008 peak (Jun 29), 38% errors | ~130–550, breaker holds errors ≈0 | gates `external_error_rate` / `error_call_rate_7d` |
| Scored universe | 4,171 flat | 800 governed (87 S0 / ≤400 S1 / ≤320 S2) + event lane | gate `universe_within_cap` |
| Paid LLM | 39-45 calls/30d (authorized lane only) | unchanged, gated | gate `no_unauthorized_paid_llm` |

The efficiency dimension of the maturity board recomputes these **daily** into
`hermes_maturity_history` — the trend is queryable, not anecdotal.

## Near-24/7 cron summary
```
*/30 9-15 + 16:15   watchlist_enrichment_sweep   (rsi/trend/score)
*/30 (all hours)    hermes_directive_discovery   (trend leads → staging → governed promotion)
*/15 (all hours)    hermes_watchlist_scorer      (tier-mode: S0 15m / S1 30m mkt / S2 premarket / events)
*/5  (all hours)    hermes_score_event_feeder    (catalyst/news/finviz/directive/proposal → rescore)
:07,:37 (all hours) hermes_scope_governor        (S0-S3 tier ledger, caps + TTLs, audited)
15,45 (all hours)   hermes_score_alerts --send   (Telegram both chat IDs)
02:50 nightly       hermes_outcome_grader        (ledger seed + grade vs money)
03:05 nightly       hermes_outcome_learning      (weights/promotion/sources/lanes, sample-gated)
03:20 nightly       hermes_tag_engine            (registry tags + quality v2 + tag efficacy)
03:35 nightly       hermes_score_history_retention (21d prune)
03:40 nightly       hermes_config_governor       (rails-pressure → config_change_proposals)
07:20 daily         hermes_maturity_gates --snapshot (honest board → hermes_maturity_history)
```

Advisory throughout — scalp + Hermes firewalls intact, holdings untouched, no execution.
