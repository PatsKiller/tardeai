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
```

## Test Plan

1. **Persistence**: Generate critique for GOVX → refresh page → critique still visible.
2. **Regenerate**: Click Regenerate → `generated_at` updates, history count increments.
3. **Staleness**: Change `setup_family` on trade → stale banner appears → regenerate clears stale.
4. **Search**: Advanced tab → search "premature exit" → matching trades listed.
5. **Behavioral**: Behavioral tab shows AI critique patterns section.
6. **Coaching**: Execution Coach / Morning Brief include critique bullets.
7. **Error state**: Force generation on invalid trade_key → error persisted, Regenerate still works.

## Version

`PROMPT_VERSION = ai_critique_v2` (in `scripts/journal_ai_critique.py`)