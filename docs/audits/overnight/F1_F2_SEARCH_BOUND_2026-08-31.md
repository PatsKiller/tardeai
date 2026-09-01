# WAVE F1+F2 — Web search callers census + bound to residual-web

**Status:** ACTIVE  
**Authority:** `READ_ONLY_ADVISORY` · behaviour rail = unconditional raise · MBI=0  
**as_of:** 2026-08-31T05:00Z UTC  
**Measured at:** branch `fix/overnight-f1-f2-search-bound` (this PR)  
**Branch:** `fix/overnight-f1-f2-search-bound`  
**No deploy. No cron install. No secrets. STORE SET: none / dry-run.**

Rails enforced:

| rail | value |
|---|---|
| hops / `subject_key` / day | ≤1 (`MAX_HOPS_PER_SUBJECT_PER_DAY`) |
| residual-web daily subject budget | N=3 (`DAILY_SUBJECT_BUDGET`) |
| news path | RSS + Finviz — **not** search API |
| budget on doubt | **never fail open** (`search_budget.check` → DENY) |
| residual-web schedule | **no cron** (operator-sequenced) |

---

## F1 — Every search caller

Census source of truth: `scripts/lib/cio_residual_web.SEARCH_CALLER_CENSUS`  
Projection helper (dry-run, no network, no store writes):
`projected_search_volume(weekdays_per_month=21, as_of=…)`.

| caller | provider | trigger | schedule | calls/run | monthly (pre→bound) | class | empty-result behavior | consumer |
|---|---|---|---|---|---|---|---|---|
| `cio_residual_web` | searxng | gate residual rung | none (no cron) | 3 | **63→63** | residual-web | PARTIAL + still_unresolved; never fabricate | instrument record / CC via `apply_hop` |
| `portfolio_news` | brave→finviz/yahoo | llm_score≥70 enrich | portfolio_orchestrator (**cron DISABLED 2026-08-30**) | 10 | ~210→**0** | legacy-bulk | omit enrich; snapshot still writes | `recovery_watch_daily`, `analyst_report_builder`, `api_v2` |
| `catalyst_intelligence` | brave→finviz/yahoo | per-symbol ollama enrich | `trade_ai_orchestrator` Stage 6 | 10 | variable→**0** | legacy-bulk | prompt without WEB NEWS | `trade_ai_orchestrator.analyze_all_catalysts` |
| `web_news_fetcher` | brave→finviz/yahoo (+ddg scrape) | `fetch_web_news` | library | 5 | variable→**0** | legacy-bulk | [] then DDG; never invent | `portfolio_ai_analyst`, `incubator_llm_screener` |
| `portfolio_weekly_report` | brave→finviz | top-5 commentary | Sunday `run_portfolio_weekly.sh` | 5 | ~20→**0** | legacy-bulk | narrative without block | weekly DOCX |
| `symbol_enrichment` | brave→**retired** (RSS/finviz remain) | Tier 5 A+ | `30 7 * * 1-5` | 3 | ~63→**0** | legacy-bulk | skip source; other tiers continue | cron + orchestrator |
| `topic_ingestion` | brave (opt-in `TOPIC_BRAVE_ENABLED`) | SOURCE 4 | `45 20 * * 1-5`, `45 2 * * *` | 0 default | 0→**0** | legacy-bulk | print retired; RSS continues | `news_articles`→`news_to_catalyst` |
| `aegis_social_sentiment` | brave | `fetch_brave_social` | `0 11,15 * * 1-5` | 10 | **420** (cap) | legacy-bulk | reddit/stocktwits-only | aegis overnight / social store |
| `aegis_transcript_discovery` | brave | yt+article+theme loops | `0 9 * * 1-5` | 12 | **252** (cap) | legacy-bulk | degrade; other sources | aegis transcript store |
| `web_research` | brave (on-demand) | interactive | none | variable | budgeted | legacy-bulk | [] | agents / auto-research |
| `credential_monitor` | brave | key probe | monitor lane | 1 | ~30 | legacy-bulk | counted, never denied | credential status |
| `secret_validators` | brave | key validate | on demand | 1 | sparse | legacy-bulk | counted, never denied | secret_validators |

Pre-bound monthly arithmetic for news/catalyst (illustrative weekday×cap, before F2):

- `portfolio_news` 10/run × 21 ≈ 210 (orchestrator currently disabled; still re-pointed)
- `symbol_enrichment` 3/run × 21 ≈ 63
- `portfolio_weekly_report` 5/run × ~4 Sundays ≈ 20

**Edited callers (named consumer only):** `portfolio_news`, `catalyst_intelligence`, `web_news_fetcher`, `portfolio_weekly_report`, `symbol_enrichment`.  
**Listed, not deleted:** `aegis_social_sentiment`, `aegis_transcript_discovery`, `web_research`, validators, `topic_ingestion` (already opt-in off).

---

## F2 — Bound policy volume (dry-run quote)

```
$ python3 -c "from scripts.lib.cio_residual_web import projected_search_volume; \
  from datetime import datetime, timezone; import json; \
  print(json.dumps(projected_search_volume(as_of=datetime(2026,8,31,5,0,tzinfo=timezone.utc)), indent=2))"
```

**Quoted result** (`as_of=2026-08-31T05:00:00+00:00`, `store_writes=false`):

```
residual_web:
  provider=searxng
  calls_per_day_cap=3
  monthly_projection=63
  arithmetic="3 subjects × 1 hop × 21 weekdays = 63"
  cost_usd_month=0.0

news_catalyst_brave_under_bound:
  monthly_projection=0
  arithmetic="all named news/catalyst Brave sites re-pointed → 0"
  callers=[portfolio_news, catalyst_intelligence, web_news_fetcher,
           portfolio_weekly_report, symbol_enrichment, topic_ingestion]

remaining_legacy_bulk_brave:
  monthly_projection=672
  arithmetic="aegis_social 10×2×21=420 + aegis_transcript 12×21=252 = 672
              (still denied by search_budget when exhausted; never fail open)"
```

Prior art: #719 (`search_budget` never-fail-open + route every Brave site through one ledger). F2 goes further for **news/catalyst**: zero search-API spend; RSS/Finviz only.

Live ledger sample (persistent-state, not mutated by this PR) showed Brave
`2026-08` callers `aegis_social_sentiment` / `aegis_transcript_discovery` only
after #719 — consistent with news paths already partially quiet, now code-forced off.

---

## What changed

| path | change |
|---|---|
| `scripts/lib/cio_residual_web.py` | `SEARCH_CALLER_CENSUS` + `projected_search_volume`; rails constants |
| `scripts/portfolio_news.py` | `_non_search_enrich` via Finviz/Yahoo; no Brave URL / no fail-open fallback |
| `scripts/catalyst_intelligence.py` | Finviz/Yahoo WEB NEWS; drop `brave_search` import |
| `scripts/web_news_fetcher.py` | Finviz→Yahoo→DDG; `_brave_search` stub returns `[]` |
| `scripts/portfolio_weekly_report.py` | commentary from Finviz/Yahoo; no Brave URL |
| `scripts/symbol_enrichment.py` | `pull_brave_aplus` retired no-op (`rss_finviz`) |
| `tests/test_overnight_f1_f2_search_bound.py` | F1+F2 suite |
| `scripts/run_cio_hardening_ci.py` | gate `overnight_f1_f2_search_bound` |

---

## Verification

```
python3 -m pytest tests/test_overnight_f1_f2_search_bound.py -q
# 15 passed
```

Hardening gate: `overnight_f1_f2_search_bound` in `scripts/run_cio_hardening_ci.py`.
