# Hermes Discovery Inbox — Current Coverage & Discovery Mechanics (2026-07-05)

What the Discovery Inbox watches today, and exactly how new items enter it. Companion to the
mission log and the Discovery tab (Hermes → Discovery). All intake is advisory-only; promotion is
operator-gated (autonomous promotion OFF).

## In scope today — four ingestors (`scripts/hermes_discovery_ingestors.py`)

| Candidate type | Data source (existing producer) | How a NEW item is discovered |
|---|---|---|
| **SOURCE_CANDIDATE** | `research_sources` registry, populated by `hermes_source_curation.py`'s autonomous source lifecycle (web sites, RSS/feeds, analyst pages it encounters during graded research) | Registry rows in candidate state (not yet active) are mirrored into the inbox with source_type, credibility score, specialty, active/dormant status. The curation lifecycle keeps hunting; the inbox is where its finds now wait for review. |
| **CONNECTOR_CANDIDATE** | Same registry | Key-gated or dormant connectors (APIs/feeds needing credentials or setup) are classed separately and stay CONNECTOR until a key exists. |
| **TREND_CANDIDATE** | `hermes_directive_hits_staging`, fed by `hermes_directive_discovery.py` and `think_tank_prospect_discovery.py` (directive-driven symbol hunting + think-tank/challenger theme output) | Staged hits are grouped per directive/theme; label + keywords + seed symbols + source refs become one trend candidate, with momentum = average narrative strength of the underlying hits. Near-duplicate labels cluster (Jaccard ≥ 0.6) instead of duplicating; operator-created directives are never auto-merged. |
| **TICKER_CANDIDATE** | Recent news rows + Hermes research text, re-scanned with `intel_auto_discovery.extract_tickers_from_text` (the previously shape-accepted extractor) | Every extracted symbol passes the validation gate: denylist (AI, CEO, USA, GDP, CPI, ETF, SEC, IRA, FDA, EPS, FCF, R&D, …) → must match `symbol_profiles` → company/profile attach. Valid → READY_FOR_REVIEW; junk (live proof: "YOUR", "SEEMS") → NEEDS_VALIDATION quarantine. Default window: 2 days, ≥2 independent mentions. |
| **TOPIC_CANDIDATE** | `hermes_research_intelligence` topics | A topic recurring ≥2× in 14 days that is not already registered in `topic_monitor` becomes a research-topic candidate. |

## Discovery mechanics (shared)
- **Idempotent intake**: same (type, normalized_key) bumps `seen_count`/`last_seen_at` and merges evidence — repeat sightings strengthen a candidate rather than duplicating it; novelty decays with each re-sighting.
- **Transparent scoring**: every candidate carries `score_json.parts` (novelty, source quality, cross-source confirmation, ticker validation, trend momentum, outcome-bus alignment, operator-history lift, minus duplicate/noise/stale/risk penalties). Components without a live signal yet are stubbed neutral (0.5) and say so.
- **Learning**: operator decisions write `hermes_discovery_feedback`; source/trend weight deltas (bounded ±0.3) persist to `data/runtime/hermes_discovery_weights.json` and shape future scores. Daily scorecard + do-no-harm (tighten/pause) at `data/runtime/hermes_discovery_scorecard.json` and `/api/v2/hermes/discovery-scorecard`.

## Not yet wired (spec'd, future intake)
- Social/news **entity-spike** trend detection (Part D "social/news entity spikes").
- **Outcome-bus tag-lift** as a live trend signal (currently a stubbed scoring component).
- Scheduled ingestor cron (today: manual/CLI `hermes_discovery_ingestors.py --run`; schedule after the 30-day evidence gates).
