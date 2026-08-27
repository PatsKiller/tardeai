# Extend News Coverage to Traded Symbols (2026-06-08)

## Problem
Source attribution (Gate 1) + catalyst calibration were starved because the news↔trade universes barely
overlapped: only **1 of 44 traded symbols had any news**. Root cause in `news_ingestion._get_symbols()`:
the universe was active classifications + portfolio watchlist + incubator, then truncated to `symbols[:30]`
— scalp-traded microcaps (INFU/BWEN/MRVL) were either unclassified or beyond the cap.

## Fix (news_ingestion.py only)
1. **Actionable/traded universe prepended (priority-first):** UNION of recent paper trades (30d) + open
   proposals + today's GO/WAIT scalp + active watchlist, placed at the FRONT of the symbol list so the
   per-run cap can never truncate them.
2. **Cap raised 30 → 60** (env `NEWS_INGEST_MAX`), enough to cover the ~80-symbol actionable set first.
3. Bug fixed: the optional incubator query could leave the transaction aborted, silently killing the
   actionable query — added `conn.rollback()` before it.

## Result (verified)
- Actionable symbols now lead the universe (INFU pos 33, BWEN pos 15, MRVL pos 44 — all within cap; were
  2491 / absent / 1227).
- One ingestion run: 1330 new articles across 60 symbols.
- **Traded-symbol fresh-news coverage: 16/19 (was 1/44).** (The 3 remaining are illiquid microcaps with no
  news anywhere.)

## Downstream effect (forward-looking, honest)
This closes the gap GOING FORWARD: future trades on these symbols will have preceding news, so source
attribution (source_performance trade win-rate) and catalyst calibration (forward returns on news-covered
symbols) will populate with real data over the coming sessions. It does NOT retroactively add news before
past entries. No schedule change needed (news_ingestion already runs frequently; it now covers traded names).

## Safety
news_ingestion.py only; read-then-write to news_articles (its normal job); no trades/holdings/scoring/schema
change. Reversible (revert the function; NEWS_INGEST_MAX env override).
