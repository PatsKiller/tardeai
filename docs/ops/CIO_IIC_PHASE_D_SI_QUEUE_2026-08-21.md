# CIO IIC Phase D — Symbol Intelligence dossier + research queue age (2026-08-21)

**READ_ONLY_ADVISORY.** No broker / orders / stops.

## Answer (operator ask)

Does the Symbol Intelligence page show Hermes / research queue amount and how long it has been in queue?

**Before Phase D:** No. Queue jobs existed via `load_symbol_research_queue` (`created_at` only); SI page was SHADOW and only fetched watch-intelligence detail.

**After Phase D:** Yes — **open queue count + oldest wait time**.

- Chip: `RESEARCH QUEUE 2 open · oldest 3h` (or `idle`)
- Source: `GET /api/v3/cio/intelligence/{SYM}` → `research_queue.open_count` / `oldest_wait_human`

## API

- `scripts/lib/symbol_thesis_queue.py` — `open_count`, `oldest_wait_seconds`, `oldest_wait_human`; per-active `waiting_age_*`
- `scripts/api_v3_cio.py` — attaches `research_queue` on intelligence GET (fail-soft)
- `scripts/lib/symbol_thesis_cc.py` — thesis card `research_queue_open_count` / `*_oldest_wait_*`

## CC

- `SymbolIntelligencePage.tsx` — dossier banner (no SHADOW); second fail-soft CIO intel fetch; queue chip (`data-research-queue`); Operator journal; Thesis timeline
- `SymbolThesisCard.tsx` + `CioHub.tsx` — optional queue chip when summary fields present

## Tests

- `tests/test_symbol_thesis_queue_age.py` (new)
- Updates: canary queue, operator ticker feedback, watchlist intelligence static UI asserts

## Deploy

CURRENT exact-main promote after merge (`cio_phase2_exact_main_deploy.sh`). Dual-root docs sync from `origin/main` `docs/` only.
