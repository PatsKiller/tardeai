# Day-Scalp Pipeline — Fixes & Enhancements (2026-08-19)

**Status:** Implemented + unit-tested + dry-tested. Pending publish.
**Owner:** John (operator) + agent.
**Root cause:** `docs/incidents/DAY_SCALP_PIPELINE_OUTAGE_2026-08-19.md`.
**Source inventory:** `docs/diligence/current/DAY_SCALP_SOURCE_INVENTORY_2026-08-19.md`.

This document records **what changed** and **what was done to fix or enhance** each broken
lane. It is the implementation counterpart to the root-cause doc: read that first for *why*,
this for *what was touched and how*.

---

## TL;DR

| # | Lane | Root cause | Fix | File(s) |
|---|---|---|---|---|
| 1 | Finviz handoff | `strategy_signal_sync` rejected every gapper on a 3% live-price drift gate | Re-price entry to live quote; reject only at a 25% hard ceiling | `scripts/strategy_signal_sync.py` |
| 2 | Social (Reddit) | Reddit public JSON returned 403 | Replace Reddit path with StockTwits fetcher | `scripts/aegis_social_sentiment.py` |
| 3 | Social (Hermes) | Hermes never wrote `social_sentiment_history` | New Hermes producer via SearXNG forum/social search | `scripts/hermes_social_sentiment.py` (new) |
| 4 | Web (`yahoo_finance`) | Orphaned health marker (never ran; Alpaca covers) | Report `yahoo_finance` healthy/covered when higher-priority quotes cover the universe | `scripts/external_market_data_ingest.py` |
| 5 | Finviz news (finnhub) | Expired key → 401; wrong auto-retry mapping | Operator key rotation (runbook) + source-aware `data_source_stale` auto-retry | `scripts/health_agent.py`, `config/health_agent_policy.json`, `docs/runbooks/FINNHUB_KEY_ROTATION.md` |
| 6 | Incubator refresh | `connection already closed` on commit after slow catalyst loop | Commit scan work before the slow loop; reconnect-on-demand | `scripts/daily_incubator_refresh.py` |
| 7 | Social-only cap opacity | GO/A+ silently capped to WAIT with no reason | Surface `SOCIAL_ONLY_CATALYST_CAP` reason code | `scripts/social_scalp_scanner.py` |
| 8 | Scalp auto-fix stuck | `fail_count ≥ 4` + `low_max_score_regime` hold never re-diagnosed | Reset the runtime hold/fail-count so it re-diagnoses fresh | `data/runtime/health_root_cause_memory.json` (runtime) |

---

## 1. Finviz handoff — `strategy_signal_sync.py` live-price drift gate

**Problem.** GO rows existed in `trade_ai_scans` (`go=10`) but `strategy_signals` stayed at
`inserted: 0`. The sync script compared the screener discovery price against a live Alpaca
quote and **rejected any signal that drifted >3%**. Micro-float momentum names routinely move
40–110% intraday, so every gapper tripped the gate and the whole lane produced nothing.

**What changed.** The gate no longer rejects on a 3% drift. It now **re-prices the entry to the
live quote** and only skips when drift exceeds a 25% hard ceiling (a signal of stale/corrupt
data, not a normal volatile fade). Fill-time drift is still enforced downstream by
`momentum_scalp.yaml intraday_execution.max_price_drift_pct`.

- `insert_strategy_signal(...)` gained `max_signal_drift_pct: float = 25.0`.
- Removed the outright-reject-at-3% branch; added the re-price + 25%-ceiling logic.

**Validation.** Dry-run of `strategy_signal_sync.py` now re-prices instead of `skip`ping
volatile names (see §9).

## 2. Social sentiment — Reddit 403 → StockTwits

**Problem.** `social_sentiment_history` had exactly one writer (`aegis_social_sentiment.py`)
which depended on the Reddit public JSON API. Reddit began returning `403` ~Aug 17, so the
writer persisted `0` records and `social_data_stale` (228h) fired.

**What changed.** Added `fetch_stocktwits_mentions()` to `aegis_social_sentiment.py`, which
reads the unauthenticated StockTwits per-symbol stream (bull/bear sentiment entities, no key).
`normalize_sentiment()` and `persist_sentiment()` now incorporate `reddit + stocktwits + brave`
and attribute sentiment per-source. Reddit remains a soft source if it recovers.

## 3. Social sentiment — Hermes as a producer (new)

**Problem.** Hermes was expected to contribute social sentiment but never wrote
`social_sentiment_history`. Its scalp catalyst lane is SearXNG news-only, and its general web
probe blocklists reddit/twitter/youtube.

**What changed.** New `scripts/hermes_social_sentiment.py` makes Hermes a direct
`social_sentiment_history` producer:
- `search_forum()` runs SearXNG queries targeting forum/community domains and **ranks actual
  forum-domain results (reddit/stocktwits/wallstreetbets/seekingalpha) ahead of generic quote
  pages** (SearXNG honors `site:` inconsistently).
- `classify()`/`normalize()` compute per-symbol sentiment score, bull/bear counts, theme tags,
  and a confidence floor based on mention count.
- `persist()` writes to `social_sentiment_history`, mirroring the existing schema.

This is a **redundant** feed — it augments, not replaces, `aegis_social_sentiment.py`.

## 4. Web lane — `yahoo_finance` false-stale marker

**Problem.** `report_source("yahoo_finance", ...)` only fired inside `ingest_yfinance_quotes()`,
a last-resort fallback. Alpaca prices the whole universe, so yfinance never ran, its
`data_source_health` marker never updated, and the health agent reported `yahoo_finance 183h
stale` — a monitoring false-positive, not an outage.

**What changed.** `external_market_data_ingest.ingest_quotes()` now calls
`report_source("yahoo_finance", True)` when yfinance was **not needed** (Alpaca/Finviz covered
all symbols), marking it healthy/covered. When yfinance *did* run, its own
`ingest_yfinance_quotes()` still reports the real ok/error state.

## 5. Finnhub 401 + wrong auto-retry mapping

**Problem (two layers).**
1. `FINNHUB_API_KEY` is expired → `HTTP 401` → `data_source_health.finnhub` in `error` since
   Jul 27. (Operator action: rotate the key.)
2. The generic `data_source_stale` finding was mapped to
   `external_market_data_ingest.py --quotes` for **every** source — a quote ingest that cannot
   touch non-quote sources (finnhub news, sec_edgar, youtube_api), so any non-quote stale
   source retried the wrong producer forever.

**What changed.**
- **Key rotation (operator):** documented in `docs/runbooks/FINNHUB_KEY_ROTATION.md`
  (corrected: the finnhub health marker is reported by `symbol_enrichment.pull_finnhub_news`
  inside the orchestrator, not `news_ingestion.py`).
- **Source-aware auto-retry (code):** added `_data_source_retry_cmd()` to
  `scripts/health_agent.py`, used by both `run_auto_remediation()` and `enqueue_escalations()`.
  For `data_source_stale` it resolves a per-source producer from a new
  `config/health_agent_policy.json` `data_source_remediation` map, keeps the quote ingest only
  for quote sources (`yahoo_finance`/`finviz`/`alpaca`), and **skips auto-retry (escalates) for
  non-quote sources without an explicit producer** (e.g. `finnhub`, whose 401 is already
  operator-action and whose non-401 stall is the orchestrator lane covered by
  `pipeline_failures`).

Note: `data_source_auth_failed` (401/403) was already correctly gated to operator action
(never-auto) in the 2026-08-12 sprint; this change only closes the remaining generic-stale gap.

## 6. `daily_incubator_refresh.py` connection lifecycle

**Problem.** The script held a transaction open across a slow catalyst-refresh loop (up to 30
symbols × 7 news providers). PostgreSQL's idle guard killed the connection, so the final
`conn.commit()` raised `psycopg2.InterfaceError: connection already closed`.

**What changed.**
- Added `_ensure_conn()` — returns the connection if still open, else a fresh one.
- Commit the scan-refresh work **before** the slow catalyst HTTP loop (no more held-open
  transaction across minutes of network calls).
- Re-establish the connection before each catalyst write, then commit catalyst updates after.

## 7. `social_scalp_scanner.py` — surface the social-only cap

**Problem.** A GO/A+ candidate capped to WAIT for lack of a verified catalyst was downgraded
silently, with no reason code distinguishing "capped after scoring GO" from a plain watch-only
candidate.

**What changed.** When a candidate is capped, `route_reason_codes` now includes
`SOCIAL_ONLY_CATALYST_CAP`, so operators/UI can see *why* a GO was downgraded. The existing
`SOCIAL_ONLY_UNVERIFIED` route policy is unchanged; this only adds transparency.

## 8. Scalp auto-fix — unstick the remediation hold (runtime)

**Problem.** `remediate_scalp_go_dark.py` had diagnosed `low_max_score_regime` (max_score 24,
market quiet) and, with `fail_count ≥ 4`, entered an unconditional hold in
`collect_scalp_catalyst_health`. Because re-diagnosis is gated by the hold, the memory stayed
stale even after the underlying feeds were fixed.

**What changed.** Reset the runtime record for `scalp_catalyst_verification_dead` in
`data/runtime/health_root_cause_memory.json`: cleared `hold_until`, reset `fail_count` to 0,
and cleared the stale `last_root_cause`/`last_strategy_id` so the next cycle re-diagnoses
fresh. (Runtime file is gitignored; audit history preserved.)

**Residual risk (documented, not yet coded).** `diagnose()` classifies a dead *social* feed as
`low_max_score_regime` when news is fresh (it only checks `news_age_h`, not social-feed
freshness). Fixing that diagnostic gap is a follow-up, not required for this repair since the
sources themselves are now fixed.

---

## 9. Test / validation matrix

| Fix | Unit test | Dry test |
|---|---|---|
| 1 signal_sync re-price | — | `strategy_signal_sync.py --dry-run --today` re-prices instead of skipping |
| 2/3 social (StockTwits + Hermes) | — | `aegis_social_sentiment.py` + `hermes_social_sentiment.py` persist >0 rows |
| 4 yahoo_finance marker | — | `external_market_data_ingest.py --quotes` marks yahoo_finance covered |
| 5 source-aware auto-retry | `tests/test_health_agent_data_source_remediation.py` (6 cases) | helper exercised against live policy JSON |
| 6 incubator connection | — | `daily_incubator_refresh.py` commits without InterfaceError |
| 7 social-only cap reason | `tests/test_social_scalp_decision_alerts.py` (updated keys) | — |
| 8 scalp hold reset | — | runtime memory reset + `summary_for` confirms `hold_until=None, fail_count=0` |

---

## 10. What was NOT changed (deliberately preserved)

- **No change to any source's underlying behavior** — Finviz/Hermes/Social/Web lanes still feed
  the desk exactly as before; only the broken glue (gates, producers, markers) was repaired.
- `data_source_auth_failed` remains operator-action (never auto) — 401/403 cannot self-heal.
- The scalp remediation ladder's `low_max_score_regime` hold logic is unchanged (only the stale
  runtime state was reset).
- No broker/execution path, no risk gates, no advisory desk code was touched.

## 11. Deployment / git isolation

Committed as an atomic, day-scalp-only change set, isolated from unrelated in-flight work on the
branch (CIO/investment-office/symbol-thesis files left untouched). See commit message.
