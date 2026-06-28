# AI Trade Critique — Persistence & System Integration

## Overview

The AI Trade Critique is a first-class, persistent data asset stored per trade and indexed for search, aggregation, coaching, and risk insights.

Each critique combines:
- **Replay bars** (OHLC + markers from `ohlc_charts.trade_chart`)
- **Journal tags** (setup, regime, mistakes, strengths, psychology)
- **Execution quality** (`trade_execution_quality` grades, MFE/MAE, capture ratio)
- **Indicator snapshots** at entry (VWAP, RSI, MACD, volume)
- **LLM narrative** (Grok via `llm_lane`, with deterministic fallback)

## Storage Model

### Primary: `journal_trade_reviews.payload`

| Field | Purpose |
|-------|---------|
| `ai_critique` | Current structured critique (sections + narrative + `llm_raw`) |
| `ai_critique_meta` | Status, `tag_fingerprint`, `generated_at`, `stale`, `prompt_version` |
| `ai_critique_history` | Up to 10 archived versions with `archived_at` |

### Index: `journal_ai_critiques` table

Queryable mirror for reports, search, and aggregation:

```
trade_key, symbol, setup_family, market_regime, summary, takeaways, strengths,
improvements, search_text, structured, stale, status, generated_at
```

Indexes: `setup_family`, `closed_date`, `status`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v2/journal/ai-critique?trade_key=` | Load persisted critique or generate if missing |
| POST | `/api/v2/journal/ai-critique` | Force regenerate (`{ trade_key, force: true }`) |
| GET | `/api/v2/journal/ai-critique/search?q=&setup_family=&days=` | Full-text search across critiques |
| GET | `/api/v2/journal/ai-critique/insights?days=` | Coaching patterns (top improvements/strengths) |
| GET | `/api/v2/journal/ai-critique/setups?days=` | Aggregate improvements by setup_family |
| GET | `/api/v2/journal/ai-critique/summaries?days=&account=` | Bulk summaries for trade log cards |
| POST | `/api/v2/journal/ai-critique/batch` | Batch generate (`date_from`, `account`, `use_llm`, `skip_existing`) |

GET responses are wrapped: `{ ok: true, data: { critique, meta, stale, persisted, cached } }`.

## Staleness

When journal tags change (strategy, setup, mistakes, etc.), `mark_stale_on_tag_change()` runs on review save (`POST /api/v2/journal/review`). The UI shows a stale banner and one-click regenerate.

Fingerprint fields: `setup_family`, `market_regime`, `setup_types`, `mistake_tags`, `strength_tags`, `emotion_before`, `planned_r`, `realized_r`.

## Consumers

| Area | Integration |
|------|-------------|
| Trade Detail | `AiTradeCritique.tsx` — load/regenerate, stale banner, version meta |
| Advanced Reports | `AiCritiqueInsightsPanel` — search + setup aggregates |
| Behavioral | `BehavioralPanel` — `ai_critique` coaching patterns |
| Execution Coach | `/api/v2/journal/daily-execution-coaching` includes `ai_critique_insights` |
| Morning Brief | `/api/v2/morning-brief` — action items + `ai_critique_insights` |
| Review GET | `/api/v2/journal/review/<key>` — `ai_critique_meta` summary |

## CLI

```bash
# Generate + persist one trade
python3 scripts/journal_ai_critique.py --trade-key GOVX:schwab_rollover_ira:2026-05-18 --apply

# Backfill index from existing payloads
python3 scripts/journal_ai_critique.py --backfill-index --limit 500

# Batch (no LLM for speed)
python3 scripts/journal_ai_critique.py --limit 20 --no-llm --apply

# Batch via API (UI: "Generate AI critiques" on Trades tab)
curl -X POST http://127.0.0.1:7777/api/v2/journal/ai-critique/batch \
  -H 'Content-Type: application/json' \
  -d '{"date_from":"2025-12-31","limit":200,"skip_existing":true,"use_llm":false}'
```

Report readiness (`score_trade_tags`) treats `ai_critique` and `ai_critique_stale` as missing criteria alongside tagging.

## Test Plan

1. **Persistence**: Generate critique for GOVX → refresh page → critique still visible.
2. **Regenerate**: Click Regenerate → `generated_at` updates, history count increments.
3. **Staleness**: Change `setup_family` on trade → stale banner appears → regenerate clears stale.
4. **Search**: Advanced tab → search "premature exit" → matching trades listed.
5. **Behavioral**: Behavioral tab shows AI critique patterns section.
6. **Coaching**: Execution Coach / Morning Brief include critique bullets.
7. **Error state**: Force generation on invalid trade_key → error persisted, Regenerate still works.

## Methodology hardening (P1-4)

The critique is **deterministic-first**. Numbers, times, and indicator values come only from
replay bars + `trade_execution_quality` + journal tags. The LLM contributes *prose only* and
can never overwrite deterministic facts:

- `_deterministic_narrative` is always computed and stored verbatim under the critique's
  `deterministic_facts` key. `_merge_llm_narrative` layers LLM prose on top but retains the
  deterministic summary as `narrative.deterministic_base_summary`.
- **Provenance captured per critique** (in `ai_critique_meta`): `prompt_version`,
  `context_hash` (hash of the deterministic inputs), `response_hash` (hash of the raw LLM
  output, `null` when no LLM ran), and `deterministic_fallback` (true when the LLM did not
  contribute a usable narrative).
- **Replay-integrity dependency**: if replay markers are unresolved or chart time-integrity
  fails, the critique `status` is `degraded` (not clean) with a `status_reason`. See
  `replay_integrity_status`.
- **Stale on tag change**: `tag_fingerprint` / `_stale_from_tags` flip the `stale` flag when
  operator tags change after generation, and clear it when they match again.
- **Invalid trade key**: `build_context` returns `None`; `generate_critique` persists an error
  state that remains regenerable via `force=True`.
- **Batch artifact**: `batch_generate_critiques` writes a machine-readable run record to
  `data/runtime/ai_critique_batch_<date>.json`.
- **Search/index mirror**: `_search_text` + `_upsert_index` keep `journal_ai_critiques` in
  sync with the stored payload.

Covered by `tests/test_journal_ai_critique.py`.

## Version

`PROMPT_VERSION = ai_critique_v2` (in `scripts/journal_ai_critique.py`)