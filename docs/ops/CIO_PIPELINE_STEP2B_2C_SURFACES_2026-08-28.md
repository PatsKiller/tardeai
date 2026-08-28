# CIO Pipeline Step 2B+2C — surfaces + CASE_SUMMARY as labeled A-context

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MEMORY_BEHAVIOR_INFLUENCE: 0
Promotion ceiling: REVIEW_READY
Branch: `feat/cio-pipeline-step2b-2c-surfaces-and-case-context`

## What this slice did

P9.5 already had the work. The operator product dropped it.

- **2B earnings:** `data/portfolios/state/earnings_dates.json` (~55 symbols) now fills `product.earnings` — held names with a dated event first, cap 10, class **D**, `as_of` stamped. Empty list only when the file is missing/unreadable (`DATA_UNAVAILABLE`), not a fake quiet night. No new scrape. No transcript dump.
- **2B new names:** `vs_re == "not_former"` is kept. Re-entry book stays former-holdings. `NEW_POSITION_IF` / `opportunity_book.not_former` take a bounded defense/advisory slice (cap 8), labeled `source` + `vs_re`. Decision language stays IF / WATCH / AVOID. No invented buy. Dedup against held + reentry. Honest empty list + reason when the queue has none.
- **2B cash:** `HOLD_CASH_FOR.why` is no longer the `portfolio_implication` template constant. It carries live `cash_pct` / `total_cash` + attention band (class **D**). `temperament.cash` is filled when the cash domain is present.
- **2C:** `case_summaries` / `research_cases` on `CIOInvestmentProduct@v1` and `CIOOperatorProduct@v1` from durable **CASE_SUMMARY ACTIVE** only (cap 10, newest first). Banner: `A-context · NON_AUTHORITATIVE · does not change action`. Command Center Investment Books renders the section. Morning/EOD mention count + top 3 symbols, not full text. Not in `DO_NOW`. Does not set recommendation / fire_reasons / material_changed.

Provenance: T = rule/template, D = deterministic compute, A = agent/memory context. Earnings dates and cash_pct are D. CASE_SUMMARY on a surface is A-context, never a price/holding/cash fact.

## What this slice did not do

- No notify / no new Telegram producer. `CIO_TELEGRAM_INTERDICT` left as found.
- No ThesisDecisionGate change. Research still cannot create action.
- No ROTATE bucket (rotation was never built).
- No merge of the two reentry books.
- No AGENT_COMMITMENT producer.
- No stop-management / quote-time / 2FA panel edits.
- No new LLM spend.

## Before (CURRENT `dab79750` / P9.5)

| Field | Value |
|---|---|
| `product.earnings` length | **0** (source file present; renderer gap) |
| `NEW_POSITION_IF` | **0** (NKE/PFSI/PRIM/SH/XLU already in `collect_queue`, ranked out) |
| `HOLD_CASH_FOR.why` | hardcoded `portfolio_implication` constant |
| `temperament.cash` | `None` (holdings.json has no top-level `cash` key) |
| `case_summaries` on product | **absent** (322 CASE_SUMMARY ACTIVE in durable memory) |
| rotation bucket | absent |

## After (worktree dry `build_product` / `build_operator_product` persist=False vs CURRENT data)

| Field | Value |
|---|---|
| `product.earnings` length | **10** held dated (NOC, RTX, BAH, V, CSWC, LDOS, SPCX, …) class D |
| `NEW_POSITION_IF` | **5** — NKE, PFSI, PRIM, SH, XLU (`vs_re=not_former`, source=defense, action=WATCH) |
| `HOLD_CASH_FOR.why` | `cash_pct 44.88 total_cash 578107.5 is above band 20; staged deploy vs hold reserve` |
| `temperament.cash` | `578107.5` / `cash_pct 44.88` class D |
| `case_summaries` count | **10** (newest first; banner A-context; not in DO_NOW) |
| rotation bucket | still absent |
| notify / gate / MBI | unchanged (0) |

## After promote (fill live)

| Metric | After promote |
|---|---|
| SOURCE / health | *(filled live)* |
| `/v3/cio` | *(must be 200)* |
| earnings length | *(must be > 0 or DATA_UNAVAILABLE)* |
| NEW_POSITION_IF | *(live count)* |
| HOLD_CASH_FOR why snippet | *(must not be the implication constant)* |
| case_summaries count | *(must be > 0 given 322 ACTIVE)* |
| new Telegram from these sections | none |
| CIO_TELEGRAM_INTERDICT | left as found |

## Explicit

- no notify
- no gate change
- rotation still absent
- CASE_SUMMARY is labeled A-context, never a trade
