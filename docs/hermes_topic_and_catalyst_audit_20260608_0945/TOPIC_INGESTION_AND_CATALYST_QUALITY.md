# Topic Ingestion Audit + Catalyst Typing/Scoring Fix (2026-06-08)

## A. How topic ingestion is handled — TradeAI vs Hermes
**Tables:** `user_research_topics` (6 user topics) · `topic_monitor` (17 monitored topics, all enabled, each
with an `owner` route) · `topic_curation_feedback`. (No `research_topics` table — earlier audit name was wrong.)

**TradeAI lanes (cron):**
- `iterate_research_topics.py` (08:00 weekdays) — re-researches active USER topics, Telegram updates (retirement-planner role). Ran today 08:03 ("Processed 5 topics").
- `topic_ingestion.py` (09:00 daily) — LLM generates queries → search cascade (YouTube API→Google News RSS→Brave→DDG) → download/transcribe → LLM rates RAG-worthy/low/blocked → news_articles/youtube_transcripts. Ran today 09:25.
- `topic_curator.py` — post-ingestion LLM curation (rate + entity extraction → content_entity_links).
- `intel_auto_discovery.py` (06:40 & 12:40 weekdays) — auto-discovers NEW **tickers** from news/YT/social mentions not yet in watchlist → auto-adds with strategy classification. Ran today 06:40 ("No new tickers meeting criteria").

**Hermes lane (cron):**
- `hermes_topic_monitor_bridge.py` (07:30 daily) — reverse bridge: topics in `topic_monitor` with
  `owner IN ('hermes','shared')` → enqueued into `hermes_research_intelligence` (research_type='topic_research')
  → Hermes coordinator researches + auto-promotes + embeds. Ran today 07:30. (All 17 topics are owner='shared'.)

## B. How topics are automatically discovered/added
- **Tickers** (not topics) are auto-discovered by `intel_auto_discovery.py` from cross-source mentions → watchlist.
- **Topics** are seeded by the user (Telegram/UI → user_research_topics) and registered in `topic_monitor`
  with an owner route; `owner='shared'` means BOTH TradeAI ingestion and the Hermes bridge research them.
  There is no fully-autonomous net-new TOPIC creation today — topics are user/system-seeded then monitored;
  Hermes researches the shared ones. (Gap/opportunity: autonomous topic proposal — not built.)

## C. CORRECTED finding — topic_ingestion is ALIVE (not a dead lane)
Prior audit said "topic_ingestion 630h / 26 days dead." **Wrong.** Live: topic_monitor 17 topics, **16/17
fresh within 72h**, oldest 72h, newest today 09:24; all four topic jobs ran today. The freshness monitor
flags it only because the single OLDEST of 17 topics crosses the 72h SLA by ~0.1h (worst-case metric).
**Decision: do NOT retire.** Optional (needs approval): tune the monitor's topic check to lane-health
(e.g. flag if no topic searched in 24h, or >40% stale) instead of worst-case-oldest; or ensure full rotation.

## D. Catalyst typing/scoring quality — FIXED (forward-only)
**Problem:** `news_to_catalyst.py` keyword classifier needs directional phrases ("earnings beat"), but
Hermes-bridged titles are bare categories ("earnings: NRIX", "news_momentum: QTEX", "regulatory: GRAN") →
all fell through to `other` / weight 0.3 → flat impact_score 3.0.
**Fix:** added `HERMES_PREFIX_WEIGHTS` + `_prefix_type()` — a bare "<category>: SYMBOL" title maps directly to
a typed, **non-directional** category + moderate in-code weight (no schema/config-table change; no beat/miss
or upgrade/downgrade assumption). Keyword classifier unchanged for normal news.
- regulatory 7.5 · fda 8.5 · merger 7.5 · contract 7.0 · partnership 6.5 · guidance 6.5 · earnings 6.0 ·
  dividend/insider 5.5 · analyst/buyback/product 5.0 · news_momentum 4.0 · sentiment 3.5.
**Verified:** live run created typed catalysts (SKYQ analyst 5.0, STTK earnings 6.0) instead of other/3.0.
Forward-only (existing rows untouched via ON CONFLICT DO NOTHING). The */30 --active fusion will propagate the
improved catalyst scores automatically.
**Blast radius:** impact_score feeds fused_signals.catalyst_score → fusion severity → advisory only. No
GO/WAIT or strategy-scoring change; non-directional weights avoid injecting false directional signals.

## Remaining (operator approval)
1. Backfill existing 'other'/3.0 Hermes catalysts to the new typing (bulk re-score of history) — optional.
2. Tune freshness-monitor topic check off worst-case-oldest — optional.
3. Autonomous net-new topic discovery — not built (design only).
