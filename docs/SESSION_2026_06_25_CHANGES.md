# Session 2026-06-25 — Changes Log

Comprehensive record of the 2026-06-25 working session. All changes merged to `main`
(branch `analyst-report-v4-design` → PR #3 → merged; subsequent commits direct to `main`).

---

## 1. Health-agent / outage hardening (thundering-herd class)

Root cause (recurred at 5 spawners): an auto-remediation re-spawning a HEAVY job without single-flight
and orphaning the child on timeout → pile-up starved the deliberately single-threaded
`portfolio_server` (shared non-thread-safe DB conn) → watchdog kill-looped it ("Reconnecting" outage).

- **`log_error_scraper.py`** — offset-based tailing (per-file byte offset state json); stops re-alerting
  on stale tracebacks. Killed the recurring "26 P0/P1 SIEM alerts/24h" flood.
- **`health_agent.py`** — recovery-aware pipeline-failure count; distinct-issue SIEM count; component-based
  enqueue dedup (was message-keyed → 14× pile-up); decision-feeding vs research stuck-jobs split;
  re-score after a successful auto-fix; circuit-breaker for ineffective remediations.
- **`health_agent_policy.json`** — flock-guard all LLM-heavy retry_cmds (single-flight on the cron locks).
- **`claude_escalation_handler.py`** — run retries in a new process group + killpg on timeout (no orphans).
- **5 flock single-flight guards**: process_watchlist_agent_jobs retries, escalation retries,
  hermes_embedding_worker, system_health_agent's `trade_ai_orchestrator` retry (via safe_flock.sh — it had
  PRE-CLEARED the lock), and the `health_agent.py` cron itself (`/usr/bin/flock -n /tmp/health_agent.lock`).
- **`portfolio_server_watchdog.sh`** — de-twitched FAILS 2→3, TIMEOUT 8→12 (was cold-killing a backed-up
  server into a re-wedge loop).
- **`process_reaper.py` + `config/process_reaper_policy.json`** — cron */3 safety net; SIGTERM→SIGKILL
  over-runtime orphans + pile-ups of an ALLOWLISTED batch-job set; hard-guards server/Ollama/Postgres/self.
  Auto-kill **enabled** (operator-approved). Two false-positive bugs found+fixed during the day-watch:
  (a) counting shell/flock/timeout wrappers as pile-up dups → `_matches` requires python argv0;
  (b) bogus `ps etimes` (~2^32 s) → `_ps_snapshot` zeroes etimes <0 or >30d.
- **`/api/v2/trade-ai` disk-cached** (`_compute_trade_ai()` + cache-serving `trade_ai()`,
  `data/runtime/trade_ai_cache.json`, warmed by `warm_caches.py`). 15s+ in-request → 95ms cached.

## 2. Proposal correctness (trading-critical)

- **Stale live R:R** (`broker_thesis_validity.attach_thesis_validity`) — only wrote `live_rr` when
  non-None, so a stale FAVORABLE R:R persisted after price blew past target (WEN "R:R 13.48 live" on an
  at_risk setup). Now always writes the fresh value incl None.
- **Near-stop inflated R:R** — a price hovering near its stop inflates live R:R (tiny risk distance).
  `compute_thesis_validity` now measures true `stop_proximity_pct` and downgrades the zone to
  approaching with a reason ("R:R inflated by small risk distance"). Threshold tuned to **4.0%**.
- **Confidence %** — 0-1 fraction rendered as "0.6%" → normalized to 60%.
- **Confidence-aware catalyst badge** — no ✅ on a 0%-confidence catalyst.
- **Honest catalyst rationale** — a stored approve_case can't claim "Verified catalyst" when the live
  catalyst is unverified (prepends a ⚠ disclaimer).
- **Strategy resolver bug** (`broker_strategy_resolver.resolve_executable_strategy`) — `_ticker_classification`
  was checked FIRST, overriding the explicit signal strategy. **26 symbols** were mislabeled (TECH
  fib→high_yield_income_bdc, WEN fib→core_growth_compounder, etc.). Reordered: explicit `strategy_id` wins;
  classification is fallback only. Fixes UI + Telegram alerts + journal.

## 3. Proposal card UI

- **Decision Summary strip** — Source · Strategy · Hold · Catalyst · R:R (plan→live) · Backtest · Journals.
- **Grade stoplight pills** — A=green, B=teal, C=amber, D/F/INCOMPLETE=red (header, plan-R:R, technical grade).
- **Live-pull stamp** — actual clock time (e.g. "05:16:52 PM") + source, robust fallback to refreshed_at.
- **Source badge** — Automated vs Watchlist (account-agnostic).
- **Journals chip** — selected destination account (only Alpaca/ATM-auto reads "Alpaca (paper)").
- **Backtest chip** — real result from `proposal_backtest_snapshots` (quality/samples/avg_r/win%, color-coded).
- **Expired sub-tab** — Active/Expired toggle; `status=EXPIRED` view, chronological, paginated (281 expired).
- Font polish (bumped 8.5/9/9.5px → 11/11.5 across card components).

## 4. Closed-loop learning

- **`paper_trade_advisory.py`** — automated Grok+ChatGPT post-mortem advisory on closed paper trades via
  the free OAuth lanes (:8645/:8646) with a curated prompt; stores structured advisory in
  `hermes_external_research`. Cron every 6h. Backfilled all 18 closed trades.
- **`wire_advisory_lessons.py`** — extracts LESSON + GRADE per advisory → `trade_lesson_memory`
  (lesson_category external_advisory, deduped per trade+lane, human_review_only) → refreshes
  `strategy_lesson_rollup --apply` → feeds the per-strategy learning digest/recommendations. Cron every 6h.
  Now also records the source (automated/watchlist) per lesson.
- Closed-loop summary: outcomes → `strategy_tilt` (auto sizing/ranking) + external advisory → lessons →
  rollup/digest (advisory-gated).

## 5. Backtest integration

- Engine ran daily but outputs were stale: `strategy_backtest_results` 14d (aggregator unscheduled),
  `proposal_backtest_snapshots` 34d (`proposal_backtest_engine` unscheduled + PENDING-only filter).
- **Fixed**: aggregator caught up 594 runs; engine filter broadened to PENDING + APPROVED_FOR_PAPER_TEST.
- **Scheduled**: `backtest_results_aggregator` daily 06:20; `proposal_backtest_engine --all-pending` every 2h.
- **Health monitor + auto-fix**: `pipeline_freshness_monitor` watches both outputs; `remediation_map` +
  allowlist auto-run the flock-guarded refresh if stale (classified auto-retry, not AI-coder).
- **Surfaced**: `_broker_proposal_row_base` attaches a `backtest` object → card Backtest chip.

## 6. Integrity guards

- **ATM-bypass** (`atm_proposal_bypass`) — health flags any executed trade not linked to a proposal
  (every ATM trade must be presented in Proposals; account-agnostic). Audit: 0/18 recent bypassed.
- **Source in journal** — Automated/Watchlist origin recorded on each lesson.

## 7. Data / ops fixes

- **Fidelity Rollover IRA** cash corrected via SnapTrade re-sync (was $277,333 stale → $217,299; JEPQ
  $59,690 was missing). `snaptrade_cash_stale` was a TRUE positive (SnapTrade snapshot lag, since refreshed).
- **Manual broker stops** (`stop_lifecycle_monitor._manual_stops` + `manual_broker_stops` table) — Fidelity
  has no order API; GCTS 2,000@$2.40 and HPE 1,000@$42.59 recorded (full coverage).
- **TECH company profile** built (`build_symbol_profiles --symbols TECH`); `proposal_enrichment_loop` now
  auto-builds a profile for any new proposal symbol lacking one.

---

## 8. (2026-06-26) Expired-view + Entry-helper technicals

- **Expired cards** — bold **Proposed**/**Expired** timestamps + trade **Result**; a **Would-have**
  outcome for untraded proposals (where the trade would stand now if entered at the plan — move% + %
  to target, from the live price; honest "live snapshot, not intraday path").
- **Backtest expired** — `proposal_backtest_engine --statuses/--limit` (similar-setup analog returns
  NO_DATA for niche income tickers). 72 missing `symbol_profiles` backfilled (stocks get sector; ETFs
  get a description). Funds show **"ETF / Fund · no single sector"** (teal) not red "Sector missing".
- **Honest Technicals** — the panel never silently omits the Technicals section: a watchlist/income
  proposal states it has **no momentum scan** (signal = price vs thesis band), not a blank box.
- **Entry-helper strip (NEW)** — every proposal card now shows **SMA20/50/200** (↑/↓ + absolute
  price derived from live price × Finviz %-from-price), **RSI**, **RVOL**, **ATR%**, **session VWAP**,
  and a plain-English **entry hint** (uptrend → buy pullbacks toward SMA20 / below VWAP → better long
  entry / RSI extremes). Works for watchlist proposals that carry no scanner technicals.
  - `api_v2 _ma_context()` reads `ticker_enrichment_cache.json` (Finviz views 141+171, no cookie) +
    `intraday_vwap_cache.json`; both mtime-memoized.
  - `scripts/enrich_proposal_technicals.py` (cron `15 */2 * * *`) keeps MAs fresh for active proposals.
  - `scripts/compute_intraday_vwap.py` (cron `*/20 13-21 * * 1-5`) computes session VWAP from yfinance
    5m bars (VWAP is intraday-only — can't come from daily Finviz). 164/170 symbols resolve.

---

Reaper day-watch (2026-06-25 16:44Z → 2026-06-26 16:44Z) clean after both false-positive fixes.
