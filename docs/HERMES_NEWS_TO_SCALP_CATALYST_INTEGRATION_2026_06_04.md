# Hermes News → Scalp Catalyst Integration — STEP 0 Grounding & Revised Plan

**Date:** 2026-06-04
**Status:** STEP 0 complete (read-only grounding). No cron/code wired. Decision pending.
**Author:** Claude Code (grounded in live code + live Postgres, not the original spec's assumptions)

> **Why this document supersedes the original spec.** The original integration spec
> assumed the catalyst pipeline already exists and is consumed (`news_articles →
> news_to_catalyst.py → catalyst_events → proposal_catalyst_quality.py`) and that the
> make-or-break risk was a Docker boundary between Hermes and `news_articles`. STEP 0
> against the real system disproved **both** premises. This document records what is
> actually true so the integration targets the real seam.

---

## 1. Executive summary

- **The catalyst-classifier path the spec is built on is DEAD, not "already consumed."**
  `news_to_catalyst.py` is never invoked (no cron, no caller, no import). `catalyst_events`
  has **0 rows in the last 7 days**; its newest row is **2026-04-27**. The pipeline has been
  dark for ~5 weeks.
- **That dead path is NOT inert — it starves a live consumer.** `signal_fusion.py` reads
  `catalyst_events` per-symbol to score signals. Since 2026-04-27 it has been fusing on an
  empty catalyst table — a silent degradation of signal quality, independent of this
  integration request.
- **The "Docker boundary" is not a boundary.** Hermes writes into the **same** Postgres that
  host cron scripts use (`hermes_research_intelligence`, **421 rows in the last 24h**). Any
  bridge is a DB-internal host script — no container network crossing to build.
- **A live, tiered scalp-catalyst → proposal engine already exists** (`catalyst_momentum_engine.py`,
  premarket/swing/overnight bands) — but it uses **SearXNG + screener candidates**, and does
  **not** consume Hermes's own discovered news.
- **Net:** this is not "schedule an existing pipe." It is a choice among three smaller,
  well-scoped pieces (§7). The original 5–10 min cadence over a believed-connected pipe was
  aimed at the wrong seam.

---

## 2. The two catalyst paths (what actually runs)

### PATH A — `catalyst_momentum_engine.py` (LIVE)
- **Reads:** momentum candidates from `trade_ai_scans` via `hermes_momentum_candidate_reader.py`
  (`rvol >= band.min_rvol`, `score >= band.min_score`, `price BETWEEN 1 AND 50`,
  `run_date >= CURRENT_DATE - 1`).
- **Catalyst news source:** **direct SearXNG HTTP** (`http://127.0.0.1:18888/search`,
  engines: google/bing/duckduckgo news) — independent fetch, **not** `news_articles`, **not**
  Hermes-discovered news.
- **Writes:** (feed #1) `hermes_research_intelligence` rows (`research_type='momentum_catalyst'`,
  **90 in last 24h**); (feed #2) shells out to `auto_proposal_generator.py --symbol X --apply
  --limit 1` for high-conviction (`conf >= 0.6`), gated paper proposals only.
- **Cadence bands** (`BANDS` in the script):

  | Band | min_rvol | min_score | max | gen_proposals | prop_cap | cron |
  |------|----------|-----------|-----|---------------|----------|------|
  | premarket_scalp | 5.0 | 30 | 8 | yes | 3 | `*/30 4-9 * * 1-5` |
  | market_swing | 3.0 | 40 | 6 | yes | 2 | `30 9-15 * * 1-5` |
  | overnight | 5.0 | 30 | 4 | no | 0 | `0 18,22 * * *` |

- **Hermes dependency:** branding only. It writes *to* a Hermes table; it does not consume
  Hermes discovery.

### PATH B — `news_to_catalyst.py` (DEAD since 2026-04-27)
- **Intended flow:** `news_articles` → `news_to_catalyst.py` (keyword-classify into catalyst
  types, score via `catalyst_type_weights`) → `catalyst_events` → consumed by `signal_fusion.py`,
  `research_insight_extractor.py`, dashboard.
- **Reality:** `news_to_catalyst.py` has **no cron, no caller, no import** anywhere in `scripts/`.
- **`news_ingestion.py` also has an inline `_feed_article` that should write `catalyst_events`
  (line ~207)** — but it too has produced **0 rows in 7 days**, so the inline write is also
  broken/not executing.
- **`proposal_catalyst_quality.py`** (the grader) reads `news_articles` **directly**
  (`proposal_catalyst_quality.py:152-167`), *not* `catalyst_events` — so it is not blocked by
  the dead `catalyst_events`, but it is also not scheduled.

---

## 3. The bridge question — answered

- **Who writes `news_articles`:** `news_ingestion.py` (primary), `external_market_data_ingest.py`,
  `symbol_enrichment.py`, `premarket_watcher.py`. **`news_articles` is fresh** (5,518 total,
  **65 in last 24h**).
- **Who writes Hermes discovery:** the Hermes sidecar (Docker) and host agents write
  `hermes_research_intelligence` in the **shared Postgres**. There is **no bridge** from
  `hermes_*` into `news_articles`, and none is needed for a host-side integration — host cron
  scripts already read `hermes_research_intelligence` directly (proven: this audit queried it
  and read 421 fresh rows).
- **Docker reachability (STEP 0.4):** could not be tested from this account
  (`/var/run/docker.sock` permission denied), **but it is moot.** The data Hermes produces is
  already in the shared DB that host scripts reach. The only thing behind the container boundary
  is the Hermes *writer*, which is demonstrably working (291 librarian + 90 catalyst + 30
  ticker-research + 10 youtube rows in 24h).

---

## 4. Live evidence (Postgres, 2026-06-04)

| Metric | Value | Read |
|--------|-------|------|
| `news_articles` total / 24h | 5,518 / **65** | fresh |
| `catalyst_events` total / 7d | 345 / **0** | **DEAD** (max created_at 2026-04-27) |
| `hermes_research_intelligence` total / 24h | 605 / **421** | very active |
| `hri` by agent (24h) | librarian 291, catalyst_momentum_engine 90, ticker_research 30, youtube 10 | — |
| `catalyst_events` consumers | `signal_fusion.py`, `research_insight_extractor.py`, `api_v2.py` | **starved since 2026-04-27** |
| SearXNG (`127.0.0.1:18888`) | http 000 from ad-hoc shell, but engine produced 90 rows/24h | **verify directly before scaling** |

---

## 5. Ticker scope tiers (real sources & counts, 2026-06-04)

> The original spec's `watchlist` table does not exist; the real table is `watchlist_items`.

| Tier | Real source(s) | Count now |
|------|----------------|-----------|
| **SCALP** | `incubator_universe` status=ACTIVE | **1,209** (too broad for per-5-min polling) |
| SCALP (tightened) | incubator ACTIVE w/ verified catalyst | 740 |
| SCALP (tightest) | incubator ACTIVE `latest_score >= 40` | 93 |
| SCALP (live screener) | `trade_ai_scans` today `decision IN (GO,WAIT)` | ~50 (GO 2–6, WAIT ~48, varies by run) |
| **PROPOSALS+AUTOMATED** | open `paper_trade_proposals` (PENDING/APPROVED) + ATM-active | **0** open proposals; ATM TBD |
| PROPOSALS+AUTOMATED (held) | open `paper_trades` (all accounts) | **4** (ALPACA_PAPER 3, TOS_PAPER 1) |
| **WATCHLIST+HELD** | `watchlist_items` active + held | watchlist 2,917 active (10,114 total); held 4; `previously_traded_watchlist` 15 |

**Implication:** the SCALP tier must be the *tight* set (live screener GO/WAIT, ~50, or
incubator score≥40, ~93) — not the 1,209 ACTIVE incubator — or per-5-min news polling is
infeasible on free-tier APIs.

---

## 6. The genuine gaps (vs the spec's assumed gap)

1. **`catalyst_events` is dead → `signal_fusion.py` is degraded.** Repairing the
   `news_articles → catalyst_events` write restores catalyst input to signal scoring. This is a
   **repair**, valuable on its own, independent of Hermes.
2. **Hermes's own discovery (`hermes_research_intelligence`: librarian 291/day, ticker_research
   30/day) is not consumed by the scalp gate.** `catalyst_momentum_engine` does its own SearXNG
   fetch and ignores it. If the goal is "Hermes-discovered catalysts reach scalps," that bridge
   is missing — and it is a **DB-internal host script**, not a Docker crossing.
3. **Scope mismatch.** The live engine scopes to screener momentum candidates, not the
   scalp / proposals+automated / watchlist+held tier model.

---

## 7. Revised integration options (pick by intent)

### Option 1 — Repair PATH B (restore `catalyst_events`)
- Re-enable/fix the `news_articles → catalyst_events` write (schedule `news_to_catalyst.py`, or
  fix the inline `_feed_article` in `news_ingestion.py`).
- **Value:** restores catalyst input to `signal_fusion.py` (dark since 2026-04-27). Smallest,
  highest-certainty win. **Does not** by itself use Hermes discovery or change scalp cadence.
- **Cost:** low. One classifier + a cron. No external-API cadence change (operates on
  already-ingested `news_articles`).

### Option 2 — Bridge Hermes discovery → scalp catalyst gate
- New host script reads `hermes_research_intelligence` (`momentum_catalyst` + `ticker_research`)
  for in-scope tickers and surfaces it as a catalyst signal (write `catalyst_events`, or feed
  the proposal catalyst-quality gate directly).
- **Value:** this is the literal "Hermes-discovered news reaches scalps" the request wants, and
  it reuses 421 rows/day already in the DB.
- **Cost:** medium. No Docker work. No new external-API load (Hermes already paid that cost).

### Option 3 — Re-scope the existing live engine to the tier model
- Drive `catalyst_momentum_engine.py` (or a wrapper) by the scalp / proposals+automated /
  watchlist+held tiers (§5) instead of only screener momentum candidates, at tiered cadence.
- **Value:** tunes what already works toward the desired scope/cadence.
- **Cost:** medium. **This is the one with external-API cadence risk** (SearXNG + the
  `catalyst_enrichment.py` API fan-out). Must verify quota headroom first (§8).

**Recommendation:** **Option 1 first** (cheap, fixes a real live degradation), then **Option 2**
(delivers the actual Hermes→scalp intent using data already in the DB). Treat **Option 3** as a
later cadence-tuning phase, gated on the API-quota check — do not start with the highest-cost,
highest-risk piece.

---

## 8. Risk flags (carried from the spec, validated against reality)

1. **External-API quota (Option 3 only).** `catalyst_enrichment.py` calls Finnhub, NewsAPI,
   Polygon, FMP, Alpha Vantage, Finviz, Yahoo. A 5–10 min scalp cadence × N tickers × multiple
   APIs will exhaust free tiers (Brave was already depleted this session). Tighten SCALP scope
   to ~50–93 tickers and confirm per-API quota headroom **before** enabling. Options 1 & 2 add
   no external-API load.
2. **Cadence ≠ urgency if upstream is slow.** `news_ingestion.py` runs only 3×/day
   (06:30/12:30/18:30 ET). Polling a `news_articles`-based classifier every 5 min just
   re-processes the same articles. The genuinely high-cadence fresh source is SearXNG (Path A)
   and Hermes's own loop (`hermes_research_intelligence`, 421/day). Match cadence to where fresh
   data actually enters.
3. **SearXNG reachability.** Returned http 000 from an ad-hoc shell probe, yet the engine
   produced 90 rows/24h — likely a bind/format mismatch in the probe, not a real outage. Confirm
   directly (`curl` from the engine's exact context) before relying on it for any new cadence.

---

## 9. Open questions / next steps

- [ ] Confirm whether the `catalyst_events` death (2026-04-27) was an intentional disable or a
      silent regression (check git history around that date for `news_to_catalyst` / `news_ingestion`).
- [ ] Decide Option 1 / 2 / 3 (recommendation: 1 → 2 → 3).
- [ ] If Option 3: run the per-API quota audit before any cron.
- [ ] Verify SearXNG directly from the engine context.
- [ ] (If approved) STEP 2 proof: one end-to-end cycle showing a real ticker's Hermes/news row →
      catalyst signal → queryable by the scalp strategy.

---

## 10. What the original spec got wrong (explicit)

| Spec claim | Reality (2026-06-04) |
|------------|----------------------|
| "Catalyst path exists and is consumed (`news_articles → news_to_catalyst → catalyst_events`)" | `news_to_catalyst.py` dormant; `catalyst_events` dead since 2026-04-27 (0 rows/7d) |
| "Docker boundary is make-or-break; Hermes may not reach `news_articles`" | No boundary to cross; Hermes writes the shared Postgres (421 rows/24h), host scripts read it directly |
| "This is scheduling + scoping an existing pipe" | The pipe is dead; choose among repair / bridge / re-scope (§7) |
| `watchlist` table | Does not exist; real table is `watchlist_items` |
| Scalp scope = incubator ACTIVE | 1,209 ACTIVE — too broad; use screener GO/WAIT (~50) or score≥40 (~93) |

---

## 11. Prompt #1 Repair — STEP 0 cause & blast radius (2026-06-04)

> Read-only forensics before any fix. The original framing ("a cron broke on 2026-04-27") was
> close but not exact — the truth is more clear-cut.

### 11.1 Root cause (two compounding facts)
1. **`catalyst_events` was never a scheduled pipeline.** All 345 rows were created on a *single*
   day — **2026-04-27** is the only date in the entire table (one manual run of
   `news_to_catalyst.py`). `news_to_catalyst.py` has **never** appeared in any crontab file; it is
   a manual `__main__` script.
2. **`news_ingestion.py` (scheduled 06:30/12:30/18:30) has an inline `catalyst_events` write that
   silently fails on a schema mismatch.** It INSERTs columns `(symbol, strategy_type,
   catalyst_type, title, description, source, relevance_score)`, but the table has **`headline`**
   (not `title`) and **`impact_score`** (not `relevance_score`). The INSERT raises *"column does
   not exist"* on every article, wrapped in `SAVEPOINT ds_cat` → `ROLLBACK TO SAVEPOINT` →
   `except: pass` (news_ingestion.py:204-213). So it has **never** written a single row — the job
   reports success while the write is silently rolled back.

**So:** not a broken cron — a never-scheduled classifier plus a silently-failing inline write.
The input (`news_articles`) is healthy (100+/day; 9 so far on 2026-06-04). The fix is **not**
upstream.

### 11.2 Blast radius (the enrichment lane is dark end-to-end, but degrades gracefully)

| Table | Last written | Consumer | Failure mode |
|-------|-------------|----------|--------------|
| `catalyst_events` | 2026-04-27 | `signal_fusion.py`, `research_insight_extractor.py`, `api_v2.py` (dashboard freshness) | reads return empty → `catalyst_score = 0` (silent) |
| `fused_signals` | **2026-05-11** (0 in 7d) | `cio_decision_engine.py` (LEFT JOIN) | `signal_fusion.py` itself stopped ~05-11 and is not in cron; CIO gets NULL fused signal (graceful) |
| `catalyst_sentiment_analysis` | **never** (0 rows) | `signal_fusion.py` | neutral default 0.5 (silent) |

Net: CIO decisions have run **without catalyst enrichment since 2026-04-27 and without any fused
signal since 2026-05-11**. Nothing errored — every consumer degrades gracefully (empty list → 0,
LEFT JOIN → NULL), which is exactly why it went unnoticed for ~5 weeks.

### 11.3 Why neither the health agents nor Hermes caught it
- **No monitor checks data-table freshness / write-success.** The health fleet covers ATM
  classifier, overnight, local-LLM, credentials, Finviz, Hermes backlog, job coverage, open
  trades — **none reference `catalyst_events` or `fused_signals`.**
- **Job-level monitoring sees green.** `job_coverage_monitor.py` checks that *jobs ran*.
  `news_to_catalyst` was never a job (nothing missing to flag); `news_ingestion` **succeeds**
  while its catalyst write fails *inside* it (savepoint rollback + `except: pass`).
- **`state_freshness_writer.py` monitors state JSON files, not DB tables.**
- **Consumers fail open, not loud** — empty→0, LEFT JOIN→NULL means no exception ever surfaces.
- **Hermes is a research/challenger fleet, not a data-integrity monitor** — and per §3/Phase 28C,
  `catalyst_events` isn't even exposed to Hermes via a safe view, so it structurally cannot see
  the emptiness.
- **Conclusion:** this is a textbook silent-failure blind spot (a write that fails inside a green
  job, with consumers that degrade gracefully). The STEP 3 staleness alert is the durable fix —
  and it should be **generalized to a data-table write-health monitor** covering `catalyst_events`,
  `fused_signals`, and peers, not just one table.

### 11.4 Fix options (pending operator decision — no changes made yet)
- **Writer:** (a) fix the column names in `news_ingestion.py`'s inline INSERT (minimal; restores
  writes inside an already-scheduled job, but only generic `catalyst_type='news'`); (b) schedule
  `news_to_catalyst.py` (the richer 15-type keyword classifier + weights the integration wants)
  and fix/remove the broken inline INSERT so it stops silently failing; (c) both.
- **Fusion:** `signal_fusion.py` is itself dormant (not in cron since ~2026-05-11). Re-wiring it
  is required to actually "un-starve" fusion/CIO — a separate decision from the catalyst writer.
- **Monitoring (STEP 3):** generalized data-table staleness alert (fire SIEM if an intel table
  gets 0 rows in 24h while its input is fresh).

---

## 12. Prompt #1 Repair — APPLIED (2026-06-04)

Operator decisions: writer = **both run in parallel** (deduped); fusion = **re-wire now**;
monitor = **generalized intel-table monitor**.

> **Correction (§15.1):** "both writers" is not yet live. Today's catalysts are 100% Writer B
> (`news_to_catalyst.py`); Writer A (`news_ingestion`) is fixed but UNTESTED (next run 12:30 ET)
> and the same function has a still-broken `sentiment_observations` insert (twin column bug). The
> pipeline is restored via Writer B alone.

### 12.1 Changes made
| Area | Change |
|------|--------|
| **Backups (IRON RULE)** | `bak_catalyst_events_<ts>` (345 rows), `bak_fused_signals_<ts>` (2362 rows); files in `backups/catalyst_repair_<ts>/`; crontab backed up. |
| **Dedup (schema)** | `CREATE UNIQUE INDEX uniq_catalyst_symbol_headline ON catalyst_events(symbol, headline)`. 0 pre-existing dups; 345 rows unchanged. |
| **Writer A — `news_ingestion.py`** | Inline `_feed_article` INSERT corrected (`title→headline`, `relevance_score→impact_score`); now classifies via `news_to_catalyst._classify` (no generic-only quality loss) and uses `ON CONFLICT (symbol, headline) DO NOTHING`. This was the silent bug (wrong columns → savepoint rollback → `except:pass`). |
| **Writer B — `news_to_catalyst.py`** | INSERT gained `ON CONFLICT (symbol, headline) DO NOTHING` + None-guard so a race with Writer A skips cleanly. |
| **Fusion — `signal_fusion.py`** | Re-wired via cron (`--full`); previously dormant since 2026-05-11. No code change needed (batch driver `fuse_all()` already present). |
| **Monitor — `intel_table_staleness_monitor.py` (new)** | Emits SIEM (`alert_events`, `alert_type='data_integrity'`, uid-deduped 12h) + optional Telegram when an intel table gets 0 rows/24h while its input is fresh. Tracks `catalyst_events←news_articles` and `fused_signals←catalyst_events`. |

### 12.2 Cron (added to live crontab; backup taken)
```
45 6,12,18 * * *   news_to_catalyst.py                 # after each news_ingestion (06:30/12:30/18:30)
0  7,13   * * 1-5  signal_fusion.py --full (timeout 20m, flock)
15 9      * * 1-5  intel_table_staleness_monitor.py --send
```
Cadence matched to `news_articles` refresh (3×/day); fusion 2×/weekday (2,714 active
classifications make `--full` heavy — see tuning note).

### 12.3 Proof (end-to-end, 2026-06-04)
- `news_to_catalyst.py` run: **487 catalyst_events created** from live `news_articles`;
  pre-existing 345 rows **unchanged** (verified count + date).
- `signal_fusion.py --symbol NOC`: **catalyst_score 0.9** (5 catalysts picked up), fused_score
  0.519, severity medium — vs **ZZZZ catalyst_score 0** (no catalyst). `fused_signals` writing
  again (max date moved 2026-05-11 → 2026-06-04).
- Monitor: reports "all tracked intel tables fresh".

### 12.4 Observations / tuning (not bugs introduced here)
- **Classifier precision is low:** ~94% of today's batch classified as `other` (analyst_upgrade
  17, M&A 6, geopolitical 3, ...). The keyword classifier (`_classify`, keyword_v1) under-matches.
  Worth a follow-up to improve keyword coverage or move to an LLM classifier.
- **Fusion score scaling:** `signal_fusion` multiplies `confidence` (0–1) × `impact_score`
  (0–10), so even weak `other` catalysts yield catalyst_score ≈ 0.9. This over-weights
  catalysts; a pre-existing scaling design issue, flagged for a separate fix.
- **`signal_fusion --full` is heavy** (2,714 symbols, per-symbol reconnect). 2×/weekday with a
  20-min timeout for now; consider a `priority_only` cadence or batching if it strains the DB.
- **`catalyst_sentiment_analysis` is still empty** (0 rows ever) — not in scope here; a separate
  dormant producer.

---

## 13. Prompt #2 — Hermes news bridge APPLIED (2026-06-04)

**Goal:** feed Hermes's ticker-level discovered news into the (now repaired) catalyst path.

- **STEP 0:** of 426 `hermes_research_intelligence` rows/24h, only **135 are ticker-level**
  (`momentum_catalyst` 95, `ticker_thesis_challenge` 30, `youtube_discovery` 10; `research_backlog`
  291 has no symbol). `news_articles` had **0 hermes rows** → no existing bridge.
- **Built `scripts/hermes_news_bridge.py`** (READ-ONLY on `hermes_*`; writes ONLY `news_articles`
  — Hermes wall intact). Reads ticker-level `momentum_catalyst` not yet bridged → inserts
  `news_articles` (`source='hermes'`, provenance `raw_payload.hermes_research_id`) → the repaired
  chain (`news_to_catalyst` → `catalyst_events` → `signal_fusion`) takes over.
- **Dedup (TradeAI side, not Hermes):** skip Hermes rows already bridged (`hermes_research_id`)
  and identical `(symbol,title,source='hermes')`; downstream `catalyst_events(symbol,headline)`
  unique index prevents duplicate catalysts.
- **Proof:** 28 bridged (67 intra-Hermes dups skipped, 95 candidates); `ABTS` traced
  `hermes#302 → news_articles → catalyst_events(source=hermes) → signal_fusion catalyst_score 0.9`;
  re-run = **0 bridged** (dedup holds).
- **Cron:** `40 6,12,18 * * *` (just before the `:45` classifier), cadence matched to the
  classify pass.

## 14. Prompt #3 — Tiered cadence + re-scope: STEP 0 & DESIGN (PENDING APPROVAL — no crons enabled)

> Per the prompt's gate, **no urgent crons were enabled.** This is the design + quota math for sign-off.

### 14.1 The quota landmine resolves favorably
The live scalp-catalyst engine (`catalyst_momentum_engine.py` → `hermes_momentum_catalyst_researcher.py`)
uses **SearXNG (`127.0.0.1:18888`, local) — no external-API quota.** External APIs (Finnhub,
NewsAPI, Polygon, FMP, AlphaVantage — all keys set; Brave unset/depleted) are hit only by
`news_ingestion.py` (3×/day) and `catalyst_enrichment.py` (Path B, not in the scalp loop).

**Therefore the urgent scalp tier can be quota-free** if driven by the DB-internal path
(Hermes SearXNG catalysts, already produced `*/30` premarket → `hermes_news_bridge.py` →
`news_to_catalyst.py`), all of which read/write Postgres only.

### 14.2 Tier scope (resolved, 2026-06-04)
| Tier | Source | Count |
|------|--------|-------|
| SCALP (tight) | screener GO/WAIT today | **38** |
| SCALP (broad) | incubator ACTIVE score≥40 | 93 |
| SCALP (already SearXNG-fed) | hermes momentum_catalyst symbols/24h | 17 |
| PROPOSALS+ATM | open proposals (0) + open paper_trades | **3** |
| WATCHLIST+HELD | watchlist_items active + held | **2,747** |

The 2,747 watchlist is the WATCHLIST tier, **not** scalp — confirming a 5-min scalp cadence must
target the tight 38–93 set, never the full watchlist.

### 14.3 Proposed cadence (for approval)
- **SCALP — 04:00–12:00 ET, every 10 min:** `hermes_news_bridge.py` + `news_to_catalyst.py`
  (DB-internal, **quota-free**). Surfaces Hermes's `*/30` SearXNG catalysts into `catalyst_events`
  fast for the tight scalp set. Auto-disable outside the window / on holidays.
- **PROPOSALS+ATM — trading day, every 15–30 min:** `signal_fusion` for proposal+ATM tickers
  (3 symbols). Cheap.
- **WATCHLIST+HELD — 2–3×/day:** existing `signal_fusion --full` (already scheduled 2×/weekday).
- **External enrichment (`catalyst_enrichment`) — LOW cadence only.** Quota math: typical free
  tiers — NewsAPI ~100/day, AlphaVantage ~25/day (verify your plan) — would be **blown by a single
  pass over 38 tickers**. So external enrichment must be limited to cheap-quota APIs
  (Finnhub/Polygon/FMP), a tiny top-N, and ≤1–2×/day. **It cannot drive the 5-min tier.**

### 14.4 Decision — APPROVED & ENABLED (2026-06-04)
Operator approved the **SCALP 10-min quota-free tier, unscoped classify**. Enabled (server TZ
America/New_York / EDT):
```
*/10 4-11 * * 1-5  hermes_news_bridge.py     # 04:00-12:00 ET, quota-free (SearXNG+DB)
*/10 4-11 * * 1-5  news_to_catalyst.py       # same window; flock-guarded, dedup-safe
```
Shares lockfiles with the 3×/day baseline (`40/45 6,12,18`) so they never double-run; the 12:00
and 18:00 baseline runs cover outside the scalp window. PROPOSALS+ATM and WATCHLIST+HELD tiers
remain on existing cadence; external `catalyst_enrichment` stays low-cadence (quota). No code
change (unscoped classify). All three prompts (#1 repair, #2 bridge, #3 tiered cadence) are now
live.

---

## 15. System-wide staleness scan (2026-06-04) — STEP 0 of the monitoring request + a correction to §12

A read-only freshness sweep of every table with a timestamp column. Two outcomes: (a) it
**validates our fix** (`catalyst_events`/`fused_signals` now fresh), and (b) it found a *pattern*
of identical silent failures — including one that **corrects an earlier claim in §12**.

### 15.1 Correction to §12 (honesty)
§12 stated catalyst writers "both run in parallel." That is **not yet true**:
- Today's `catalyst_events` are **100% Writer B** (`news_to_catalyst.py`, `keyword_v1`, 1,477 rows).
- **Writer A** (`news_ingestion._feed_downstream` catalyst insert) is **applied but UNTESTED** —
  `news_ingestion` last ran 06:30 ET on the *old* code; next run 12:30 ET is the first on the fix.
- Worse: the **same function has a second, still-broken insert** — `sentiment_observations` uses
  columns `source/sentiment/score/raw_text` but the table has
  `source_type/overall_sentiment/sentiment_score/raw_text_snippet` (4 of 5 wrong). Frozen since
  **2026-05-10**, silently (savepoint + `except:pass`). My §12 catalyst fix did not touch it.
- **Correct status (at scan time):** the catalyst pipeline was restored **via Writer B alone**;
  Writer A was pending verification and needed the sentiment insert fixed too.
- **RESOLVED (later 2026-06-04):** fixed the `sentiment_observations` column mismatch and ran
  `news_ingestion --priority` to verify on the real path — `sentiment_observations` now writes
  (57 rows, was frozen since 05-10) and Writer-A `catalyst_events` rows appear (`yahoo_rss`,
  `barrons`, `finnhub`, …) alongside Writer-B `keyword_v1`. **Both writers now genuinely run in
  parallel, deduped — verified, not asserted.**

### 15.2 The pattern
A schema migration renamed columns in several tables; multiple ingestion inserts were never
updated and fail **silently** (savepoint rollback + `except: pass`), so the jobs stay green while
the writes vanish. Plus several jobs are simply **not scheduled**. Death-date clusters:
`~2026-04-27` (catalyst_events, research_insights, confidence_calibration_history,
marl_training_episodes), `~2026-05-10` (sentiment_observations), `~2026-05-11` (the learning batch
+ fused_signals).

### 15.3 High-confidence silent failures with consumer impact (beyond the catalyst one)
| Finding | Evidence | Impact |
|---------|----------|--------|
| `sentiment_observations` column mismatch | 4/5 insert cols missing; last row 2026-05-10 | news sentiment lane dead ~25 days (twin of catalyst bug) |
| `signal_fusion` runs on ~2 of 5 lanes | `social_mentions` EMPTY, `catalyst_sentiment_analysis` EMPTY, `research_insights` stale 2026-04-27 | social_score=0, sentiment_score=0.5 default, research_score degraded — even post-repair fusion is partial |
| Learning/self-improvement batch frozen 2026-05-11 | `learning_recommendations/hypotheses/evidence`, `strategy_learning_scores`, `source_learning_scores`, `self_improvement_snapshots`, `backtest_datasets` all 2026-05-11 07:45; `learning_governance.py` not in cron | self-improvement loop dark ~24 days |
| `market_ohlcv_bars` frozen 2026-05-07 | 55,396 rows, last bar 2026-05-07 | daily-bar consumers stale (live quotes come from `ticker_prices`/`market_quote_snapshots`, fresh) |

### 15.4 Honest framing (not crying wolf)
The scan shows ~76 empty + ~90 stale tables, but **most are not failures**: many empties are
event-logs that are sparse by design (`agent_conflicts`, `learning_rollback_events`, `stop_snooze`,
…), and some stale tables are weekly/monthly cadence or side-projects (DOF vehicle-auction tables,
3–5 d). The table above lists only entries with **demonstrated consumer impact**. The rest need
operator judgment (deprecated vs should-be-live) — which is exactly what a freshness *registry*
(expected cadence per table) would encode.

### 15.5 Why this validates the monitor request
The scan caught (a) several multi-week silent failures and (b) **my own incomplete fix**. That is
the argument for detect-and-verify over assurance: a freshness registry + staleness monitor that
**escalates to the operator** would have made each of these loud within an interval. Recommended
build follows the trust contract — **detect + escalate broadly; auto-fix only idempotent,
reversible cases (e.g. re-run an unscheduled read-only classifier), never schema/column/trading
writes** (the root cause here is exactly a column fix that needs a human).

---

## 16. System freshness & silent-failure monitor — BUILT (2026-06-04)

The monitoring request, built to the trust contract: **detect + escalate broadly; auto-fix only
provably-safe/idempotent/reversible cases.** Decisions: fix concrete gaps then build; narrow safe
auto-fix enabled.

### 16.1 Phase A — concrete gaps fixed first
- `sentiment_observations` twin column-bug fixed (`news_ingestion._feed_downstream`); verified
  writing again (see §15.1 RESOLVED).
- Writer A verified end-to-end; both catalyst writers now parallel + deduped.

### 16.2 Phase B — `scripts/system_freshness_monitor.py`
- **Registry-driven** (10 entries): each declares an expected cadence; the engine flags
  deviations. Kinds: `fresh` (table must have a row within max_age), `empty_vs_input` (table 0
  rows while its input is fresh — the catalyst-bug signature), `logfile` (cron success via log
  needle — the gog-PATH signature). Covers news_articles, catalyst_events (+vs-news),
  sentiment_observations, fused_signals (+vs-catalyst), hermes_research_intelligence,
  ticker_prices, cio_decisions, drive-sync mirror.
- **Severity by blast radius** (P0–P3); weekday-cadence entries (`fused_signals`, `ticker_prices`,
  `cio_decisions`) skip weekends to avoid false pages.
- **Escalation:** SIEM (`alert_events`, `data_integrity`, uid-deduped 12h) for all; **Telegram for
  P0/P1** (out-of-band, so the next silent death is loud within ~20 min — the gap that let this
  hide 5 weeks).
- **Narrow safe auto-fix** (`--auto-fix`): allowlist `{news_to_catalyst.py, hermes_news_bridge.py}`
  only — DB-only, idempotent, dedup-guarded, reversible. Capped at 2/day per key; **always logged
  to SIEM AND escalated regardless of outcome**; never schema/column/trading writes (the actual
  root cause needs a human). Everything else is detect + escalate, with the recommended fix in the
  alert.
- **Cron:** `*/20 * * * *` `--send --auto-fix`, flock-guarded. Supersedes
  `intel_table_staleness_monitor.py`.
- **Verified both ways:** reports "all 10 fresh" on the healthy system (no false positives); a
  forced-stale entry fires a P-graded finding (detection proven without a misleading SIEM write).

### 16.3 Honest framing on trust
The 2026-06-04 scan caught several multi-week silent failures **and my own incomplete fix**. This
monitor is the detect-and-verify mechanism for that class — but trust should come from watching it
**catch and page on the next silent failure**, not from this writeup. The remaining stale
subsystems from §15 (learning batch frozen 05-11, `social_mentions`/`catalyst_sentiment_analysis`
empty feeding `signal_fusion`, `market_ohlcv_bars` frozen 05-07) are **left for operator decision**
(revive vs deprecate) rather than auto-revived — reviving a self-improvement loop is a behavior
change, not a safe auto-fix.

## 18. Watchdog fail-test — PASSED, device delivery confirmed (2026-06-04)

The most important verification: a forced failure pushed through the monitor's **real** `run()`
path, proving the whole escalation chain rather than trusting it. A clearly-labeled `[FAIL-TEST]`
synthetic P1 finding was injected; the test SIEM row was deleted and the auto-fix counter reset
afterward (no false alert left in the console).

| Link | Result |
|------|--------|
| Detection fired on forced failure | ✅ 1/10 flagged |
| SIEM written (P1 → `urgent`, `data_integrity`, `requires_agent_review`) | ✅ alert id 466 |
| Auto-fix attempted + **escalated even on success** (`auto_remediation` in SIEM payload) | ✅ ran `news_to_catalyst` rc=0 |
| Auto-fix cap halts at 2 → escalate-to-human | ✅ `"cap-reached (2/2) — escalate to human"` |
| Telegram accepted by API (both operator chats, no error) | ✅ |
| **Message delivered to operator device** (operator confirmed the received text verbatim) | ✅ confirmed |
| Cron actually firing (not just on-demand) | ✅ `*/20` ran 12:00, flock held, logged |

This is the proof point, **not** an assurance: the out-of-band link whose absence hid the
catalyst death for ~5 weeks is now demonstrably working. Trust is earned from here by watching it
catch the **next real** silent failure, not from this test.

**Watch-the-watchman — BUILT (2026-06-04).** The monitor cannot detect its own death, so this is
solved in two complementary layers:
- **In-host (no external dependency):** `system_freshness_monitor` now writes a heartbeat
  (`logs/.freshness_monitor.heartbeat`) only on a completed run. A **separate, self-contained**
  cron — `freshness_watchdog_heartbeat.py` (`*/30`, deliberately does NOT import the monitor, so a
  broken monitor can't break its watcher) — pages **P0** if the heartbeat is >70 min stale (≈3
  missed `*/20` cycles). Verified: fresh→OK; backdated 90 min→STALE + P0 SIEM (id 469) written;
  restored→OK. Catches monitor-down-while-host-alive (the common case).
- **Off-host (the terminus):** if `FRESHNESS_HEARTBEAT_PING_URL` is set, the monitor pings an
  external uptime service each run; if pings stop (total-host death), that service pages you. This
  is the only layer surviving the whole box going down. **Env-gated — set the URL to activate.**
- **Honest limit:** the in-host checker is itself unwatched (turtles stop somewhere); the off-host
  ping is the terminating layer. Setting `FRESHNESS_HEARTBEAT_PING_URL` is the one remaining
  operator step for full coverage.

## 17. Sentiment lane repoint + dormant-subsystem decisions (2026-06-04)

A read-only revive-vs-deprecate review of the three dormant subsystems from §15. Facts corrected
two initial steers; net result: **one small build, the rest left off (the high bar to "wake
something up" at low trust).**

### 17.1 Facts
- **`social_mentions`**: NO producer anywhere — orphaned. `signal_fusion` already reweights for
  "social often empty." → **Deprecate** (reviving = building a scraper, not a revive).
- **Sentiment lane**: `signal_fusion` read `catalyst_sentiment_analysis`, which has **NO producer**
  (always empty → `sentiment_score` stuck at 0.5). Raw sentiment now flows in
  `sentiment_observations` (the §15.1 fix). → **Small build (done).**
- **`market_ohlcv_bars`**: producer (`market_data_snapshot_loader.py`) and strategy consumers
  (`fib_swing_engine`, `opening_range_engine`, `proposal_technical_snapshot`) are **all dormant**;
  only live touchpoint is a rarely-hit volume *fallback* in `proposal_execution_readiness`. →
  **Deprecate/defer** (low blast radius; consumers are off).
- **Learning batch**: writes `config_change_proposals` → **operator-approved via Telegram**
  (`approved_by`), sample-gated tiers — **not a blind auto-tuner**. → **Stay asleep** at current
  trust (or revive insight-only later; never promotion/auto-apply).

### 17.2 The build (done + verified)
`signal_fusion.py` sentiment query repointed `catalyst_sentiment_analysis` →
`sentiment_observations` (same `overall_sentiment`/`confidence` columns; now flowing). One line,
reversible, no new producer/cron. **Verified:** RTX `sentiment_score` 0.5 (default) → **0.567**
with `sentiments=3`; fusion now runs on **3 of 5 lanes** (catalyst+news+sentiment). social stays 0
(deprecated), research stays stale (operator decision).

### 17.3 Decisions recorded
| Subsystem | Decision | Action |
|-----------|----------|--------|
| Sentiment lane | Build | Repointed (done) |
| `social_mentions` | Deprecate | Leave off; not in monitor registry (no false flag) |
| `market_ohlcv_bars` | Deprecate/defer | Leave off; revisit only if fib/ORB engines revived |
| Learning batch | Stay asleep | No schedule; revive insight/shadow-only if ever, never auto-apply |

---
*Grounded in live code under `scripts/` and live Postgres `trade_ai` on 2026-06-04. STEP 0/§15/§17
reviews were read-only; §12–13, §15.1, §16, §17.2 changes (code, crons) were applied with backups
per the IRON RULE. §14 tiers operator-approved. Auto-fix is allowlisted to idempotent DB-only
re-runs; no schema/column/trading writes are ever auto-applied.*
