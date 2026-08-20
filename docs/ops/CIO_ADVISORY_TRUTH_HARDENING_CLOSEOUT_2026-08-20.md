# CIO/Advisory truth + presentation hardening — closeout 2026-08-20

Authority: **READ_ONLY_ADVISORY**. No broker / order / stop / 2FA mutation.

Branch: `feat/cio-advisory-truth-hardening` (from `origin/main` @ `b74d94fc`).

## Why this batch existed

Two earlier ships closed desk completeness (#403) and YouTube full-asset-class coverage (#404). This batch closes the remaining **truth contradictions** and **presentation** gaps from the operator audit (SCHD Telegram mis-attribution, receipts tab vs reality, research 97% failure, DATA CONFLICT wall, JSON/snake_case UI, capital-plan honesty).

## What shipped

### P0 — Truth

| Item | Result |
|------|--------|
| Telegram receipts | Collector unifies dedicated CIO paths + outbox `DELIVERY_CONFIRMED` + generic `system_telegram_sends`. UI shows which bot delivered; PREPARE_ONLY ≠ "never sent". |
| Research 97% failure | Root cause documented: missing global daily USD cap → Flash fail-closed → circuit-open. Ops strip surfaces Flash attempted/actual/fallback + `dominant_failure_class`. No silent re-queue. See `docs/ops/RESEARCH_ENGINE_FLASH_FIRST_FAILURE_2026-08-20.md`. |
| DATA CONFLICT | Stale Finviz vs today's broker MV → **STALE** (prefer broker after-hours), not CONFLICTED. Same-session dual marks still CONFLICTED + action suppressed. |
| Notification attribution | Subject **BOOK** when trigger symbol's own row did not change; filter `NON_TICKER_SYMBOLS`; demote `reentry_added → AVOID`. |

### P1 — Data quality

| Item | Result |
|------|--------|
| Non-ticker universe | `HEALTH` / category labels filtered or OTHER in `symbol_thesis_cc`. |
| Opportunity dedupe | `build_opportunity_book` dedupes by symbol; zone/pct floats rounded. |
| Thesis-driven scheduler | `research_scheduler` + `AGENT_JOB_PRODUCER_MAP` → `thesis_driven` + `rag_first`. |
| Bounded canary | Dry-run SCHG/CSCO/ANET → all `no_existing_summary_will_not_invent`. **No apply.** Evidence under `docs/ops/` + `evidence/`. |
| SENSES providers | Unconfigured/DENIED providers labeled honestly (shadow/unconfigured). |

### P2 — Presentation

- Zone / `pct_above_exit` rounded to 2 decimals.
- SENSES / TELEGRAM tabs: tables/cards instead of raw JSON dumps.
- `cioLabels.ts` humanizes snake_case; As-of renders ET (+ UTC suffix).
- Opportunity chips: symbol + verdict spaced; provenance hashes collapsed.

### P3 — Math honesty

- Capital plan: total deploy reconciles; sector rotation labeled **notional**; deploy-vs-investable **funding gap** explicit.
- Sector targets: load from existing `config/model_portfolio.json` when present; identical 18% fallbacks labeled **placeholder**.
- Benchmark: full 55% SPY / 20% ITA / 25% AGG blend + ITA sleeve source note. **No invented IPS numbers.**

## Tests

- Python: 141 related unit tests passed (P0–P3 suites listed in PR).
- Frontend: `cioLabels` 11/11; design-guard + `tsc` + vite build required green before merge.

## Operator follow-ups (not blocking this PR)

1. ~~Set / fix `LLM_GLOBAL_DAILY_USD_CAP` so Flash-first can succeed~~ — **resolved 2026-08-20**: cap was already sourced via the offpeak/market wrappers; the real gates were the canonical containment flag (absent → `exit=78`) and the maria `daily_soft_cap` request cap (exhausted overnight → `COST_CAP_EXCEEDED`). See `docs/ops/FLASH_ACTIVATION_AND_THESIS_CANARY_2026-08-20.md`.
2. ~~Produce seed summaries for SCHG/CSCO/ANET, then re-run canary with `CANARY_THESIS_APPLY=1`~~ — **superseded then shipped**: the gap-driven research → RAG → Flash synthesis → reconcile → apply path is now a **live autonomous pipeline** (`run_symbol_thesis_acquisition.py` + governed wrapper). SCHG/CSCO/ANET remain `BLOCKED_PENDING_ACQUISITION_AND_CURATION` (empty RAG); `DIV`/`DIVI`/`JEPI` (sufficient RAG) published `symbol_*@v1`. See `docs/ops/SYMBOL_THESIS_ACQUISITION_PIPELINE_LIVE_2026-08-20.md`.
3. Confirm model-portfolio sector targets are the intended IPS (now loaded, not invented).

## Final live status (2026-08-20 ~17:27 UTC)

- **Release promoted** `5209c820` → **`8db42725`** (current `origin/main`, merge of #410) via `cio_phase2_exact_main_deploy.sh`. `CURRENT` symlink updated, server restarted, health + `/v3/cio=200`. Frontend rebuilt (`ui_version 3.14+mt1slm3k`). Holdings `data/portfolios/state` symlink to canonical confirmed intact.
- **Portfolio freshness verified**: `portfolio_value $1,279,003.95`, `as_of 2026-08-20`, `last_repriced 2026-08-20 13:15:00 ET` (`finviz_live`), 20 positions.
- **Telegram proactive non-financial canary delivered**: `cio_phase13_telegram_live_canary.py` → `delivered: true`, `REAL_TELEGRAM_SENDS: 1`, `GENERAL_TELEGRAM_RECEIVED: false`, CIO-only channel (`telegram_cio`), 3 allowlisted chats, durable receipt `dec_phase13_live_canary` (message id 197). No portfolio action.
- **Telegram interactive converse verified**: `tradeai-cio-telegram.service` restarted on the promoted code (ExecStart → `CURRENT/scripts/cio_telegram_bot.py --loop`). Dry-run `process_operator_message` proves free-text query → `READ_ONLY_ADVISORY` structured reply with desk-thesis pin + CC deep links; `/cio status` deterministic dashboard; non-allowlisted chat fails closed (`not_allowlisted`).

## Drive sync

Ops closeout + finding docs land under `docs/ops/` and are mirrored by the hourly docs→Drive cron after merge to canonical `docs/`.
