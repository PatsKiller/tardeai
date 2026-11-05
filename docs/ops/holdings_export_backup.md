# holdings.json is a generated backup (Step 1)

Operator, 2026-11-03: the database `positions_current` is the holdings source of truth; `holdings.json` becomes a
generated backup. `scripts/holdings_export.py` is the **only** writer of that file.

## What it does

- Renders the document from `positions_current` on every run — **the existing file is never opened or read as input**, so
  a 0-byte or corrupt file is simply replaced by the next good render.
- Writes atomically: unique temp in the target directory, `fsync`, `os.replace`, mode `600`.
- Refuses on a database failure or a zero-row result **before any write**; the last good file is left byte-identical.
- Carries, per position and with provenance:
  - **sector / industry** from `symbol_profiles` (`source`, `updated_at`);
  - **fund look-through** from `etf_holdings_snapshot` when that table exists. It is **not applied live** today, so the
    document carries a stated gap and an empty look-through rather than an invented one. The migration to apply is
    `migrations/2026_10_31_etf_holdings_snapshot.sql` (no new table).
  - **price, price time, session, prior close, day change** from the latest `market_quotes_extended` row per symbol
    (`bar_end`/`inserted_at`, `session`, `reference_close` + `reference_basis`, `change_pct`). No migration is needed for
    these; the remaining work is that the repricer writes the DB instead of the file (separate change).
- Retention under `<store dir>/backups/`: last **48 hourly** and **30 daily** snapshots, pruned oldest-first with a size
  cap (default 64 MiB).
- Telegram **P1** when the export is **empty**, **older than 30 minutes during US market hours**, or its
  `portfolio_totals.total_value` differs from `SUM(broker_market_value)` by **more than $1**.

## Running it

    .venv/bin/python scripts/holdings_export.py --dry-run    # render and print, write nothing
    .venv/bin/python scripts/holdings_export.py --apply      # write the store and the backups

Exit `1` means the export refused (database unreachable or empty) — the last good file is intact and the freshness check
still pages if it is stale. A refusal is a **failed unit run**, not a successful tick: the service does not mask it with
`SuccessExitStatus`. The unit that runs it is `ops/systemd/tradeai-holdings-export.{service,timer}`; **it is not
installed** — enabling a schedule is operator-only (AGENTS.md §17).

## Authority

Read-only against the database. No broker call, no credential in code, no order, no schedule install.
