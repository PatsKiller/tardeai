# Inference Layers — Modular Higher-Order Reasoning

**Status:** Live (v1, 2026-06-21) · advisory-only · local-LLM-first
**Owner module:** `scripts/inference_layer_engine.py`
**Config:** `config/inference_layers.yaml`

The Inference Layers system is a reusable, layered reasoning pipeline that sits **on
top of** the existing Trade AI intelligence stack — Hermes, RAG, LLM enrichment,
journal analytics, topic curation, the risk gate and proposal lifecycle — and
synthesizes all of it into **higher-order, actionable inferences**. It is designed
to have a "mind of its own": it proactively queries Hermes when it detects gaps,
surfaces multi-region news impacts (especially Asia → US ETFs/CEFs like PTY),
performs deep journal analysis, and produces risk-appropriate proposal sizing.

It **never places orders.** Every output is advisory and lands in `inference_*`
tables, the dashboard (`/api/v2/inference/*`), and Telegram for the human/approval
path to consume.

---

## 1. Architecture — four reusable layers

Each layer is an independently importable class (`scripts/inference_layers.py`) with
a single contract: `run(ctx: InferenceContext) -> LayerResult`. They compose into a
pipeline; each reads every prior layer's structured output from `ctx.store`.

| # | Layer | Module class | Consumes | Produces |
|---|-------|--------------|----------|----------|
| 1 | **Ingestion & Structuring** | `IngestionLayer` | `news_articles`, `topic_monitor`, `paper_trade_proposals`, `paper_trades`, `holdings.json` | structured data models + region-tagged news |
| 2 | **Feature Extraction** | `FeatureLayer` | L1 | regime (`risk_on/neutral/risk_off/high_vol`), sentiment, VIX, concentration, momentum |
| 3 | **Cross-Regional Synthesis** | `RegionalLayer` | L1, L2 | `regional_impact` inferences + `inference_regional_signals` (Asia→US transmission) |
| 4 | **Higher-Order & Autonomy** | `HigherOrderLayer` | L1–L3 | journal patterns, NAV premium/discount signals, opportunity/risk synthesis, **risk-appropriate sizing**, proactive gap queries |

The orchestrator (`InferenceEngine.run`) persists each layer's results, reaps stale
runs, indexes salient inferences, and pushes a prioritized Telegram digest.

```
            ┌────────── config/inference_layers.yaml ──────────┐
            ▼                                                   │
  L1 Ingestion ─► L2 Features ─► L3 Regional ─► L4 Higher-Order │
     │  structure    │ regime       │ Asia→US      │ journal     │
     │  region-tag   │ sentiment    │ NAV channel  │ NAV signals │
     │               │ concentration│ affected     │ opportunity │
     │               │              │  symbols     │ /risk       │
     │               │              │              │ SIZING ─────┼─► inference_sizing_recommendations
     └───────────────┴──────────────┴──────────────┴────────────┘
                              │
              inference_runs / inference_results / inference_regional_signals
              inference_memory / inference_proactive_queries
                              │
          ┌───────────────────┼─────────────────────┐
          ▼                   ▼                     ▼
   /api/v2/inference/*   Telegram digest      RAG (research_finding)
```

## 2. Reasoning substrate (`inference_hermes_query.py`)

All layers reason through one interface so behavior is consistent and auditable:

- **`llm_text` / `llm_json`** — primary local **gemma3** via `local_llm.generate`
  (toll-gated). `llm_json` returns parsed JSON with a `confidence` and a `reasoning`
  trace. It escalates to a **free OAuth lane (grok / chatgpt)** only when
  `llm.use_external_lane` is set **and** the call's salience clears
  `proactive.salience_threshold` — otherwise everything stays local.
- **`rag_block`** — injects prior intelligence via `rag_retrieval.get_rag_context`
  so inferences are grounded in what the system already knows.
- **`proactive_query`** — the "mind of its own" primitive. A layer decides on its own
  to ask Hermes a follow-up when it detects a gap/high-salience signal; the exchange
  is persisted to `inference_proactive_queries` and accumulated in `inference_memory`.
- **`classify_region`** — cheap keyword region tagging for Layer 1's news capture.

## 3. Multi-region news & impact inference (Layer 3)

Layer 1 region-tags every ingested news item (`news_articles.region` /
`geo_keywords`, added by `create_inference_schema.py`). Layer 3 buckets news by
region and, for each non-US region, asks the LLM for the **single most important
transmission channel to US markets** — naming the specific US equities, semiconductor
ETFs, or income CEFs affected and through what channel (supply chain, rates/yen
carry, flows, USD).

**Asia is the priority mandate.** If Asia news is thin, Layer 3 fires a *proactive*
Asia macro scan (BOJ/yen, China/PBOC, semis/TSMC, export controls → US equities,
semi ETFs, PTY) rather than going silent. Output → `inference_regional_signals`
(region, theme, headline, `us_impact`, direction, `affected_symbols` with `held`
flags) and `regional_impact` inferences.

## 4. Risk-appropriate sizing (`inference_sizing.py`)

Single source of truth is preserved — shares always come from
`account_policy.compute_sizing()` (the same engine `risk_gate` trusts). Synthesized
signals only move the **tilt** knob within a hard clamp:

```
tilt = base · regime_tilt · confidence_factor · journal_edge_factor · fomo_penalty
       clamped to [tilt_floor, tilt_ceiling]
```

- `regime_tilt` — risk_on 1.15 / neutral 1.0 / risk_off 0.70 / high_vol 0.60
- `confidence_factor` — scales up only above `min_confidence_for_uptilt`
- `journal_edge` — per-strategy expectancy from the journal (Layer 4) in [-1, 1]
- `fomo_penalty` — applied to high-RVOL chases in a non-risk-on tape

The recommended plan is **re-validated through `risk_gate.RiskGate.check()`** — a
recommendation can never exceed the account's risk envelope; if the gate rejects,
the recommendation is forced to 0 with the gate's reason. Output is advisory →
`inference_sizing_recommendations` (never mutates a proposal).

## 5. Deep journal analysis (Layer 4)

Calls `journal_analytics_engine.run()` (which joins `schwab_round_trips`,
`paper_trades`, `journal_trade_reviews`) and synthesizes the highest-value patterns
(best/worst setup, emotional edge, repeat/stop). It derives a per-strategy
`journal_edge` that feeds directly into sizing — historically winning setups get
more risk budget, losers get trimmed.

## 6. Autonomy & persistence

- **Proactive querying** — budgeted per run (`proactive.max_queries_per_run`); fires
  on regional gaps, NAV estimates with no feed, and salient holdings risks.
- **Persistent memory** — `inference_memory` accumulates salience across cycles
  (`regime:*`, `regional:*`, `journal:*`, `gap:*`), so recurring signals strengthen.
- **Stale-run reaper** — every cycle marks runs left `running` > 60 min as `error`
  so a killed cron tick can't poison `/latest`.

## 7. Data model (`create_inference_schema.py`)

| Table | Purpose |
|-------|---------|
| `inference_runs` | one row per cycle (status, regime, layers_run, summary) |
| `inference_results` | unified actionable inference store (type, subject, confidence, severity, reasoning_trace, evidence, payload) |
| `inference_regional_signals` | Layer 3 detail (region, theme, us_impact, affected_symbols) |
| `inference_sizing_recommendations` | advisory risk-adjusted sizing |
| `inference_memory` | persistent salience state |
| `inference_proactive_queries` | self-initiated Hermes follow-ups |
| `news_articles.region/country/geo_keywords` | region tagging (added) |

## 8. Surfaces

**Dashboard** (`/api/v2/inference/*`, served by `portfolio_server` via a 5-line
delegating hook in `api_v2.handle()` → `inference_api.handle_inference`):
`/latest`, `/runs`, `/results?type=`, `/regional`, `/sizing`, `/nav`, `/memory`.
Frontend widget: `InferenceLayersPanel` on the Intelligence hub.

**Telegram** (`inference_telegram.send_inference_digest`): prioritized, confidence-
tagged digest of medium+ inferences via the existing `telegram_alert.send_telegram`.

## 9. Operation

```bash
# one-time / upgrades
python scripts/create_inference_schema.py --apply

# run a cycle
python scripts/inference_layer_engine.py --run                       # full
python scripts/inference_layer_engine.py --run --layers regional,higher_order
python scripts/inference_layer_engine.py --run --dry-run --no-telegram  # safe test
python scripts/inference_layer_engine.py --latest                    # inspect

# cron (flock-guarded)
bash linux_launchers/run_inference_cycle.sh cron_preopen
```

Crontab — **installed 2026-06-21** (weekday pre-open / midday / post-close ET),
flock-guarded via the launcher; live crontab backed up under `backups/crontab/`
and mirrored in the repo's `crontab_backup.txt` (block `INFERENCE-LAYERS-1`):
```
0 8  * * 1-5 cd $PROJ && bash linux_launchers/run_inference_cycle.sh cron_preopen   >> logs/inference_cron.log 2>&1
0 13 * * 1-5 cd $PROJ && bash linux_launchers/run_inference_cycle.sh cron_midday    >> logs/inference_cron.log 2>&1
30 16 * * 1-5 cd $PROJ && bash linux_launchers/run_inference_cycle.sh cron_postclose >> logs/inference_cron.log 2>&1
```

## 10. Example trace (real — run #1, 2026-06-21, account=rollover)

```
regime = risk_off  (conf 60%, sentiment -0.67, 160 news / 24 Asia-tagged)

[high  | 0.80 | local]     risk            portfolio  Top risk (synthesized):
        "Continued Risk-Off Sentiment & NAV Weakness"
[high  | 0.60 | heuristic] market_regime   portfolio  Market regime: risk off
        news sentiment -0.67 (risk-off skew)
[medium| 0.80 | heuristic] risk            other      Concentration: 83.5% in 'other'
[medium| 0.75 | local]     opportunity     portfolio  Top opportunity (synthesized): JEPI
[medium| 0.55 | local]     nav_signal      SCHD       SCHD: premium to NAV (qualitative est.)
[low   | 0.55 | local]     nav_signal      PTY        PTY: Neutral — prior intel flags AVOID
                                                       for Roth conversions (RAG-grounded)
[low   | 0.50 | local]     regional_impact Asia/BOJ   Asia: BOJ monetary policy → US transmission
[medium| 0.50 | local]     journal_pattern journal    best 'scalp' +$20.36 (50%/38t),
                                                       worst 'swing' -$522.25  → journal_edge feeds sizing
```

Note the PTY NAV inference surfaced prior intelligence (avoid for Roth conversions)
via RAG — the layers genuinely synthesize across the existing stack rather than
reasoning in isolation. Inference quality scales with the local model tier
(gemma3:4b here); escalate high-salience synthesis to grok/chatgpt by setting
`llm.use_external_lane: true`.

## 11. Due diligence — GitHub finance resources

The `inference_financial_modeling.py` valuation object (source-attributed,
confidence-tagged, with an explicit `measured` vs `llm_estimate` flag) is adapted in
**pure Python** from the open-source finance-skills pattern
(`anthropics/financial-services` "Market Researcher" + valuation skills, Apache-2.0)
and the `quant-sentiment-ai/claude-equity-research` fundamentals+technicals+risk
structure. Only the **logic/prompt structure** was refactored to run against this
repo's local data and Ollama/Hermes — no Claude-plugin install. The Market-Researcher
pattern also informs Layer 3's regional synthesis prompt and the autonomous
follow-up querying. **Honesty guarantee:** NAV is reported as `measured=True` only
from a real feed; with no feed the module produces a *qualitative* read at reduced
confidence and never fabricates a precise NAV number.

## 12. Safety

Advisory-only; no execution path. All sizing re-validates through the existing
`risk_gate`. No hardcoded values (everything in `config/inference_layers.yaml`).
Heavy type hints, per-layer exception isolation (a layer crash never kills the
cycle), full logging to `logs/inference_layer.log`, audit trail in `inference_runs`.
