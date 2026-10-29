# Ticker Prospectus — accuracy auditor

```
Status:      DRAFT (shadow; runs on request until the lane row lands)
as_of:       2026-10-27T02:00:00Z
Measured at: branch feat/prospectus-accuracy-auditor-20261026, stacked on fix/prospectus-accuracy-20261026
```

Operator 2026-10-26: "There's still some data that's missing … we need an agent to go through and look at this …
Money is riding on this. We can't have inaccuracies."

## What it does

The data-quality gate (`PROSPECTUS_QUALITY_GATE.md`) checks a facts packet against itself before the model writes.
The accuracy auditor works after the report is written. It re-reads the **primary** stores and recomputes every
number that can be recomputed. It does not use the prospectus code paths to do it.

| Block | Recomputed from |
|---|---|
| Position: shares, average cost, market value, unrealized P/L | position store (`lib.portfolio_positions.load_store`) |
| Stops: level and state per account, stop-plan broker rows, fill dates | `stop_last_known` (read as Risk reads it) + `trade_transactions` |
| Last close, 1W/1M/3M/YTD/1Y returns, 1-year high and low | `ticker_prices`, NYSE sessions only |
| Annual dividend, fund trailing 12 months, distribution history | `ticker_dividends` against `ticker_dividend_data` and the fund profile |
| Fundamentals and peers | the Finviz enrichment cache (the same snapshot only; a later refresh is drift, not a defect) |
| Macro series, dates, rate beta, calendar | `fred_economic_series` |
| Round trips and realized P/L coverage | `trade_transactions` sells |
| Fund profile against look-through, dividends tile | the report's own blocks |
| Charts and prose numbers | the report's chart series, and the gate's layer-3 matcher |

Each defect has these fields:

- `code`, `severity`, `klass`, `block`, `field`, `observed`, `expected`, `fix`
- **severity**: P1 is wrong money, position, stop or price. P2 is missing or stale key data. P3 is cosmetic.
- **klass**: `wrong`, `missing`, `stale`, `contradiction`, `label` or `render`.

A check that raises is itself a defect (`check_error`), never a silent pass.

Code: `scripts/lib/prospectus/accuracy_audit.py`. CLI: `scripts/prospectus_accuracy_audit.py`.
Neither calls a model, except for `--review`. Neither calls a broker. The DB wrapper refuses any statement that is
not a `SELECT`.

## Running it

```
python3 scripts/prospectus_accuracy_audit.py [--dry-run]               # dry run: the latest version of every report
python3 scripts/prospectus_accuracy_audit.py --since 2026-10-27T16:00Z  # only versions written in a run window
python3 scripts/prospectus_accuracy_audit.py --apply                   # + findings, window note, data-gap rows
python3 scripts/prospectus_accuracy_audit.py --state-root /tmp/x       # proofs against a temp root
```

Dry run writes nothing.

`--apply` writes only under `<state>/data/prospectus/accuracy/`:

- `<stamp>.json` and `latest.json`, holding the summary, `note`, `gap_requests`, `rewrite_due` and every
  per-report result.
- `note` is the run window's **P2 line** for the email audit, for example
  `P2 prospectus accuracy: 4 defect class(es) across 12 report(s) (1 P1, 3 P2): …`. It is `null` when the run found no
  P1 or P2 defect.
- One governed data-gap request per (domain, symbol), through `data_broker.gap_hook` with requester
  `prospectus_accuracy_audit`. It is filed only for defects that a data owner can repair: `dividends`,
  `fundamentals`, `technicals`, `quote_price` (two price stores disagree) and `macro`.
  - Code and wiring defects go to the findings file only.
  - A report that no longer matches the book (a trade or a stop change since it was written) is listed in
    `rewrite_due`. The window decides whether to rewrite it. The auditor never touches the queue or a report.

## Monthly prose sample (Opus, at most $2 a month)

`--review` picks 3 reports (holdings first, most defects first). With `--apply` it sends each one, as sections plus
the facts they cite, to process `prospectus_accuracy_review`.

The process:

- runs on Claude Opus 5.5, `long_form` tier, `anthropic_only_processes`;
- is registered in `llm_process_registry.json` and `llm_routing_policy.json` with a $2/day cap;
- returns `{issues: [{section, quote, problem, severity, fact_ids}], overall}`.

The CLI enforces the **$2 per UTC month** cap through `accuracy/review_ledger.json`. It stops before a read whose
estimate ($0.45) would cross the cap. A credit refusal ends the run; it never falls back to another provider. The
review result is written to `accuracy/review_<YYYY-MM>.json`.

## Scheduling (shadow first)

The lane is **`prospectus-accuracy-audit`**, an n8n ingest-class lane that is read-only toward every store.

- **Shadow.** It runs `--dry-run` 30 minutes after each prospectus run window (12:30 and 18:00 ET), and on the 1st of
  each month with `--review` (dry).
- **Live.** After an operator-confirmed shadow week it runs
  `--apply --since <window start>`, and `--review --apply` monthly.

The lane row, the allowlist entry and the health contract go into `config/lane_registry.json`,
`config/n8n_run_allowlist.json` and `config/n8n_health_contracts.json`. PRs #2193 and #2207 hold those files today,
so the row lands after they merge. Until then the CLI runs on request. The window email in #2207
(`scripts/lib/prospectus/delivery.py`) reads `accuracy/latest.json` → `note` for its P2 line.

## What the 2026-10-26 audit found

The full private findings are in `persistent-state/data/coordination/handoffs/prospectus-20261026/ACCURACY_AUDIT.md`.
They stay out of the repo because the repo is public.

- The fixed classes each have a packet-only check in the gate (`check_accuracy`).
- The fixes are on `fix/prospectus-accuracy-20261026`. The stop-state mapping is a separate PR.
