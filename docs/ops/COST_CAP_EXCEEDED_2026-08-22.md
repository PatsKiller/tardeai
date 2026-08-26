# COST_CAP_EXCEEDED 2026-08-22 — what did not run, and why 895 ≠ 312

**Do not raise the cap.** 895 sent vs ~312 scheduled demand is extra producers + retry-on-cap + skip-gate not live on the crontab tree. The 600-call cap bound; the extras are the bug.

READ_ONLY_ADVISORY. Numbers from live `hermes_external_research` / `llm_cost_reservations` ET Saturday 2026-08-22.

## Bind

| | |
|---|---|
| First `COST_CAP_EXCEEDED: daily request cap` | **11:31:13 ET** (`NXPI`) |
| Pre-bind successful DeepSeek rows | **120** (118 symbols) |
| Effective soft cap at bind | **120** (not 600 — 600 was restored at 20:40 ET after ignore-cap) |
| After bind, scheduler kept calling | 426 error rows in ~90 minutes, same process family |

Pre-bind mix: T0-HOLD 24, T0-PROP 22, T1-WATCH 60, T3-COLD 14. Roll-forward by priority: holdings cleared, then proposals, then T1, then the tail.

Live `llm_process_config.hermes_external_research` at 20:58 ET: `daily_soft_cap=600`, `daily_cost_cap_usd=$0.30`, `updated_at=20:40:02 ET` (restore). Reservations settled Saturday: **917**.

## The 441 rejections — tiers

441 `status=error` rows, 441 distinct symbols, all `[ERROR] COST_CAP_EXCEEDED: daily request cap`.

| Live universe tier | n | Share |
|---|---|---|
| T1-WATCH | 250 | 245 scheduler + 5 high_rank |
| T2-INCUB | **141** | entire incubator |
| T3-COLD | 42 | 32 scheduler + 10 high_rank |
| T0-PROP | 8 | NXPI RCL STLD STX SW TPL TXN UAL |
| T0-HOLD | **0** | cleared before bind |

Operator expectation (T1 + tail) is right on T1 and T3. Missed: **all 141 T2-INCUB** also ate the cap. T2 is supposed to be catalyst-only; 0 T2 catalysts are live now. That burst was not the catalyst gate.

**Correction vs “never ran”:** every one of those 441 also has a `status=sent` row later Saturday after ignore-cap. They were throttled at 11:31, not left dark for the day. Full lists: `docs/ops/COST_CAP_SKIPPED_2026-08-22.json`.

## 895 vs ~312 — where the extra 583 came from

Today is Saturday. Weekday crontab (`1-5`) should not have run. T3 cold-floor is **commented** on current crontab (catalyst-only). Theoretical **weekday** demand with skip-on:

- T0-HOLD 23 × (1 if skip, 3 if T0 always-due) ≈ 23–69
- T1-WATCH 312 × 4/7 ≈ 178
- T2 catalyst 0, T3 catalyst 10
- **≈ 211–312**

Without skip, weekday max is holdings 69 + priority 7×40 + watchlist 50 = **399**.

What actually ran ET Saturday:

| Window (ET) | Producer (`trigger_reason`) | Attempts | Distinct symbols | Notes |
|---|---|---|---|---|
| 10:00 | cron cold-floor budget 20 | 0 externals | — | log: `done: 218 symbols, 0 external calls` |
| **11:01–12:43** | `research_scheduler` | **971** | **544** | 427 symbols called **twice**. Not in `research_scheduler.log` (mtime still 10:00) — side-channel invocation of the same script, not the weekday cron. |
| 18:37–19:54 | `high_rank_watchlist` + `holdings` | 364 + 22 | 349 + 22 | Second producer. Question text is the scheduler template, not `hermes_top20` (that cron is grok/chatgpt and deferred 3210). |
| **ET day total** | | **1336** (895 sent + 441 error) | | |

Decomposition of extra vs 312:

1. **Skip gate is not live on the crontab tree.** Crontab prefixes `RESEARCH_SKIP_GATE=1`. Live `$PROJ` is rebuild `feat/two-way-watchlist-curation`; `research_scheduler.py` there has **zero** `skip_gate_enabled` / source-index code. `data/cio/research_skip_ledger.jsonl` does not exist. origin/main (this branch) has the gate; crontab does not run this tree. Env var is a no-op.
2. **Retry-on-cap.** Scheduler did not stop at the first `COST_CAP_EXCEEDED`. 427/544 symbols in the 11:01 burst were called twice. That is the 3× smell, not three scheduled lanes.
3. **Saturday backfill-sized walk** (544 symbols) vs ~312 due. T2 141 + extra T3 got DeepSeek — catalyst-only was not in effect for that invocation (it landed on origin/main after the cap was set; live rebuild still the dispatcher).
4. **Second producer** `high_rank_watchlist` 349 names in the evening, after ignore-cap reopened the window.

917 reservations / 895 sent is one paid call per send, not a hidden retry inside the reservation ledger. The triple is **dispatch retry + second producer + skip gate absent**.

## Item 3 — code (this branch, not live)

`COST_CAP_EXCEEDED` now writes `status=skipped` / `[SKIPPED_BUDGET] {symbol} …`, not `[ERROR]`. Lane health:

- `error_rate_24h` counts lane-broken rows only
- `budget_throttled:N/M` fires on SKIPPED_BUDGET
- Scheduler stops remaining externals on first throttle this run

Not merged. Not promoted. CURRENT pin untouched.

## Authoritative accounting contract (2026-08-23 implementation)

Historical reconstruction above remains the source for 2026-08-22. New runs emit
`ResearchCallAccountingEvent@v1` to one append-only ledger through
`scripts/lib/research_call_accounting.py`.

Identity is mandatory: `producer + family + run_id + call_id`. Family A is
`research_scheduler` / governed DeepSeek. Family B is
`hermes_top20_external_intel` / OAuth ChatGPT or Grok. Direct invocations are
`MANUAL`; other named producers are `REGISTERED`, never unclassified.

The daily formula is:

- `calls_scheduled = count(distinct call_id where event=SCHEDULED)`
- `calls_actually_attempted = count(distinct call_id where event=ATTEMPTED)`
- retry and fallback are explicit events on the same `call_id`
- freshness/source-hash suppression is `DEDUPED`
- catalyst, data-quality, circuit, and per-run budget suppression is `SKIP_GATED`
- pre-provider paid-cap rejection is `COST_CAP_EXCEEDED` and does **not** count as attempted
- a cost reservation older than the recovery window with no consumption/terminal event is
  `RESERVATION_ONLY`
- a report is reconciled only when every call has a terminal event and the reservation DB was read

Command: `python scripts/research_call_accounting_daily.py --hours 24`. `--no-db` is an
explicit offline view and reports reservation reconciliation as skipped. The ledger is advisory
observability only: `authority=READ_ONLY_ADVISORY`, `financial_writes=0`.

Implementation is in the stacked call-accounting PR and is not live while GitHub CI remains blocked
before job start by repository billing. CURRENT, cron, and systemd remain unchanged.

Read-only acceptance against the live DB at 2026-08-23 09:35 ET found one 24-hour orphan:
reservation `2177`, created 2026-08-22 12:00:10 ET, `settled`, DeepSeek V4 Flash,
projected/actual `$0.001618`, with no matching `llm_consumption_log.metadata_json.reservation_id`.
The reporter classifies it as Family A `RESERVATION_ONLY`; it does not count it as attempted.

## Item 4 — overnight (check after 22:35 ET)

- Unit files rewritten **2026-08-22 13:20 ET**. `ExecStart=...hermes_deep_research_local.py --apply --max-rows 3 --model chatgpt`
- `OnCalendar=*-*-* 22,23,00,01,02,03,04,05:35:00 America/New_York`
- Next fire at write-up: **Sat 22:35:34 EDT**
- Journal after 13:20: **empty** (correct — first US tick is 22:35)
- Pre-13:20 daytime ticks `gemma3:27b apply=False targets=[]` are the **old** unit. Last fire of that unit: 12:35 ET. No second gemma timer found.
- Last `deep_research_local` row: **2026-08-20** Flash — two days, not three months.

Tomorrow first thing: non-error rows from 22:35, model ChatGPT vs gemma. Zero or still gemma = retarget failed.
