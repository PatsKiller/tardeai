# Claude Challenger Cohort (A/B) + Analyst Lanes

Status:      ACTIVE
as_of:       2026-06-24T20:36:32-04:00
Measured at: efcc51365 / not measured

Two additions to the discovery/research stack: a weekly Claude-curated **challenger watchlist** tested
head-to-head against the mechanical screener, and **dedicated analyst-aggregator sources**.

## 1. Claude challenger cohort — `scripts/claude_challenger_curator.py`

**Why:** the Finviz screener is mechanical (RVOL/gap/value) — it can't reason about *themes* (AI-datacenter
power, defense supercycle, rate-cut beneficiaries). Claude can. This is a **pure A/B test**: does top-down
thematic curation add edge over bottom-up screening?

**What it does (weekly, Sunday):**
1. Claude (metered, `claude-sonnet-4-6`) curates **100 US-listed names** across diverse themes/trends/
   sectors — batched 4×25 so each call fits the API timeout, deduped across batches.
2. Each pick → `incubator_universe` with `source='claude_challenger'` (roll-on/roll-off tracked like any
   incubator member) + an `incubator_events` roll-on row.
3. Each pick → `rec_ticker_attribution(source_type='claude_challenger')` — this is the **A/B hook**: the
   recommendation-intelligence engine's return-by-origin-source now compares `claude_challenger` vs
   `scan`/`screener` returns directly.
4. The **research scheduler** picks the cohort up as **T2-INCUB** (same tier as screener-originated
   incubator names → a *fair* A/B: both cohorts get identical research treatment — local-gemma always,
   external on catalyst).

**Governance:** Claude stays metered-curation-only — **one call/week**, never in sweeps. Advisory →
paper-tracked → judged by expectancy/return-by-origin before any real consideration. No live-execution change.

**Tunables:** `CHALLENGER_TARGET_N` (100), `CHALLENGER_BATCH_N` (25), `CHALLENGER_MODEL` (sonnet-4-6).

**Cadence:** Sunday (alongside `weekly_incubator_builder`). Run manually: `--apply` (writes), default dry-run.

**The A/B you can read:** after a few weeks, `rec-intel` return-by-origin answers *"did Claude's thematic
picks beat the screener's mechanical picks?"* — keep, tune, or kill the cohort on that evidence.

## 2. Analyst lanes — `scripts/register_analyst_sources.py`

**Why:** Hermes anchors analyst data on **Yahoo consensus** (authoritative) and already surfaces analyst
*commentary* via MarketBeat/GuruFocus/simplywall.st (top trade-converting news sources). But the premier
public analyst aggregators — **TipRanks, Zacks, Morningstar, WallStreetZen, StockAnalysis** — were only
*incidental* web hits, treated as anonymous low-credibility discoveries.

**What it does:** registers those 5 as first-class **`analyst`-type sources** in `research_sources`, active
and credibility-seeded (120–150), with specialty tags. Now the **source-maturity ladder** (daily 05:45)
weights and yield-tracks them as recognized analyst lanes instead of decaying them as noise.

Idempotent / re-runnable (upsert by url). Pins them active so a vetting sweep won't demote known-good
analyst sources.

**Scope note:** these sites are JS-heavy / partly paywalled, so this is *registration + recognition*, not a
bespoke scraper. The existing web/news research lanes already encounter these domains; registration makes
the encounters first-class and tracked. A dedicated per-site analyst fetcher (ratings/target extraction) is
a sensible follow-up if the yield data shows it's worth the fragility.

## How they connect
The challenger cohort gets researched (incl. analyst-source-informed news) by the same 24/7 lanes in
`docs/RESEARCH_PRIORITIZATION.md`, and its performance is attributed by origin — so the whole thing is a
closed measurement loop: **Claude curates → lanes research → paper-tracks → rec-intel scores by origin →
keep/kill.**
