# Layer-4 Inference / Synthesis Engine

_Activated 2026-06-21._

Cross-source synthesis that fuses news + regime + cross-market (regional) + portfolio + valuation (CEF/ETF
NAV) into structured, auditable **inferences** — advisory only, free LLM lanes only, config-driven. Built
as a standalone subsystem; this doc covers what it does and how it's wired.

## Pipeline (one cycle = one `inference_run`)
```
IngestionLayer   → structures news (region-tagged), topics, proposals, positions, closed trades
FeatureLayer     → market regime (VIX + news sentiment → risk_on/off/high_vol/neutral) + confidence
RegionalLayer    → cross-market signals (Asia/Europe/EM → US impact), per-region, LLM-classified
HigherOrderLayer → fuses the above + journal edge + NAV premium/discount + Hermes RAG into inferences,
                   with proactive_query() filling gaps (its "mind of its own")
```
Each layer writes rows to `inference_results` (layer, inference_type, subject, title, body, confidence,
severity, source_lane, **reasoning_trace**, evidence, payload). The run header is `inference_runs`.

## Modules (`scripts/inference_*.py`)
| Module | Role |
|--------|------|
| `inference_layer_engine.py` | orchestrator: `--run [--trigger T] [--account A]`, persists runs/results/memory |
| `inference_layers.py` | the 4 layer classes (real logic, ~600 lines) |
| `inference_hermes_query.py` | salience-escalated LLM (local gemma3 → free grok/chatgpt), `proactive_query()`, `classify_region()` |
| `inference_financial_modeling.py` | CEF/ETF NAV premium/discount (`measured=false` when no NAV feed — honest) |
| `inference_sizing.py` | risk-adjusted tilt via `account_policy` + `risk_gate` — **never auto-applies** |
| `inference_api.py` | `/api/v2/inference/*` read-only router (delegated from api_v2) |
| `inference_telegram.py` | digest builder/sender |
| `create_inference_schema.py` | DDL: `inference_runs/results/regional_signals/sizing_recommendations/memory/proactive_queries` + news region cols |

## Config — `config/inference_layers.yaml`
All tunables (lookback windows, max rows, salience thresholds, account, layer enable flags). No hardcodes in
the engine. `account: rollover` (active trading account).

## Safety
- **Advisory only** — zero order/execution/trading code (safety-scanned). Sizing recommendations are written
  for operator review and re-validated through the existing `risk_gate`; they never place or modify orders.
- **Free LLM lanes only** — local gemma3 primary, free OAuth grok/chatgpt escalation by salience. No metered keys.

## Schedule & wiring
- **Cron** (`linux_launchers/run_inference_cycle.sh`, flock-guarded, 25m timeout): weekday
  **08:00 pre-open / 13:00 midday / 16:30 post-close**.
- The launcher first runs **`region_tag_news.py`** (cheap keyword pass, no LLM) so the RegionalLayer has
  real region-tagged news — initial backfill tagged 3,964 articles (255 Asia / 80 Europe / 19 EM / 3,610 US).
- **API:** `GET /api/v2/inference/latest|runs|results|regional|sizing|nav|memory` (read-only), via a 10-line
  delegating hook in `api_v2.handle()`.
- **Telegram:** `inference_telegram.send_inference_digest()` (engine calls it on completion).

## Verified (2026-06-21)
Full cycle runs end-to-end: regime=risk_off (conf 60%), cross-regional signals across 2 regions, PTY NAV
signal, 16 inferences in run #3. `/api/v2/inference/latest` serves them.

## Multi-LLM ensemble validator (`scripts/inference_ensemble.py`)

A real hybrid ensemble over the **free lanes only** — grok (xAI-OAuth proxy :8645) + chatgpt (codex-OAuth
proxy :8646) + local gemma, via `llm_lane.py`. **No metered keys, no anthropic/xai/ollama SDKs** (the
pasted "ensemble" that used `ANTHROPIC_API_KEY`/`XAI_API_KEY` + uninstalled SDKs was rejected — it violated
the iron LLM policy).

- `ensemble_validate(content, context, task)` → each available lane returns `{score, decision, confidence,
  reasoning}`; aggregates to a final verdict via **majority + (consensus_threshold OR min_score)**. Skips
  unavailable/failed lanes; if every lane is down it returns a **safe block** (never guesses).
- Config: `inference_layers.yaml → ensemble:` (`lanes`, `consensus_threshold` 0.66, `min_score` 6.0, `timeout`).
- Verified: demo → grok 8.5 / chatgpt 8.4 / local 7.5 → avg 8.1, 3/3 approve, consensus.

**Curator escalation** — `topic_curator.py --ensemble`: opt-in second opinion that re-rates only the
borderline `low_quality` rejects through the ensemble and upgrades consensus-approved ones (so only borderline
items pay the 3-lane cost — single-lane still decides the bulk). Verified: 1/3 rescued. Default behavior
unchanged when the flag is off.

## Roadmap (not yet built — deferred from the enhancement spec)
Multi-modal ingestion (SEC filings/PDFs), A/B curation testing, self-adjusting ingestion cadence from
outcome feedback, and a dashboard hub for the inference results. (Multi-LLM ensemble — DONE above.)

See also `HERMES_RESEARCH_LIFECYCLE_AND_SOURCE_RATINGS.md`, `MASTER_SYSTEM_DOCUMENTATION.md` §6b.
