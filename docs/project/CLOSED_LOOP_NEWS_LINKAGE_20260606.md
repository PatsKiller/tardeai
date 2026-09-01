# Closed-Loop Structured News Linkage (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T00:08:45-04:00
Measured at: efcc51365 / not measured

## Gap (from all-trades cert re-audit)
News had no structured FK to trades — only symbol/date correlation. The closed loop could not answer
"what news surrounded this trade's entry/exit?" in a queryable way.

## Change (additive, read-only analysis; broker/account-neutral)
- New table **`trade_instance_news`** (structured FK: trade_instance_id ↔ news_article_id, classified by
  lifecycle `relation`: pre_entry / entry_window / hold_window / exit_window; carries published_at,
  sentiment, relevance_score, is_attention_spike). UNIQUE(trade_instance_id, news_article_id, relation).
- Summary counts on `trade_instances`: news_pre_entry_count / news_entry_count / news_hold_count /
  news_exit_count.
- `scripts/link_trade_instance_news.py` (--apply, idempotent rebuild). Matches any trade_instance
  (paper OR imported) to ticker news by symbol + published_at window.

## Window rules
- pre_entry [entry-3d, entry-1d) · entry_window [entry-1d, entry+1d] · exit_window [exit-1d, exit+1d]
  (closed only) · hold_window (entry+1d, exit-1d).
- **Open trades are capped at entry+1d** (entry/pre_entry only) — otherwise long-held open Schwab
  positions vacuum the entire recent-news corpus into a meaningless hold_window (first pass produced
  15,108 such rows; capped run produces the meaningful 35).

## Result
- trade_instance_news: **35** links across 27 trade_instances (schwab_import 32, alpaca_paper 3).
- by relation: entry_window 16, pre_entry 13, hold_window 4, exit_window 2.
- instances with entry news 12, hold 2, exit 1. Samples: SCHD/PFLT entry_window, BND pre_entry.

## Honest limitation
The news corpus is recent (~6 weeks: 2026-04-27 → 06-05); trades span back to 2022. Older imported trades
have no in-window news — left unlinked, never fabricated. Coverage grows as the news corpus deepens.
Many news rows are topic/strategy items (non-ticker `symbol`) and are excluded by the ticker filter.

## Safety
ALPACA_MODE=paper, live disabled. Writes only trade_instance_news + 4 count columns. No broker/order/
stop/proposal/GO-WAIT/strategy/live/Phase-205. No production learning graft.
