# CIO cash fossil — Saturday proof (2026-08-29)

Status:      HISTORICAL
as_of:       2026-08-29T08:38:23-04:00
Measured at: efcc51365 / not measured

Authorized by operator John Whiting to prove, without waiting for Monday
16:10, that the repricer writer from #635 closes the `total_cash` gap on the
served product.

**Result: PASS.** File and live payload both flipped.

## Pin

| item | value |
|---|---|
| PR | #635 |
| merge commit | `7ad62f7b9a601e92b316be7bf6e5d18b7a942cfa` |
| merged at | 2026-08-29T12:13:36Z |
| CURRENT | `7ad62f7b-main-exact-phase2-20260829-081457` |
| promote | `PROMOTE OK live=7ad62f7b…` 12:16:08, health 200 + /v3/cio 200 |

### Pin truth is file content, not `git log`

`git log` inside a release dir reports the *deploy worktree's* HEAD, because
the release dirs share a gitdir. Before the promote it already printed
`d9e6b6b7`, which made the fix look deployed when it was not. The grep is the
only proof:

```
$ grep -n total_cash CURRENT/scripts/portfolio_repricer.py
578:    _total_cash = round(sum(float(h.get("market_value") or 0) for h in _cash_rows), 2)
590:        "total_cash":            _total_cash,
591:        "total_cash_source":     "position_rows",
592:        "total_cash_written_at": _utc_now_iso(),
```

## Write targets

`portfolio_repricer.py --print-targets` resolves to a single shared path —
not a per-release directory:

    /home/johnclaw/trade-ai-releases/persistent-state/data/portfolios/state

`CURRENT/data/portfolios/state` is a symlink to it.

## Backups (taken before any write, verified byte-identical by md5)

    data/cio/backups/holdings.json.pre-sat-cashproof-20260829T121644Z
    data/cio/backups/finviz_quote_cache.json.pre-sat-cashproof-20260829T121644Z
    data/cio/backups/cio_investment_brief.json.pre-sat-cashproof-20260829T121644Z

## Before / after — served `holdings.json`

| field | before | after |
|---|---|---|
| `total_cash` | **578,107.50** | **630,784.82** |
| cash row sum (5 lots) | 630,784.82 | 630,784.82 |
| `total_mv_excluded` | 630,784.82 | 630,784.82 |
| `cash_gap` | **52,677.32** | **0.00** |
| `total_cash_source` | *(missing)* | `position_rows` |
| `total_cash_written_at` | *(missing)* | `2026-08-29T12:17:31.576058+00:00` |
| `last_repriced` | 2026-08-28 16:45:01 ET | 2026-08-29 08:17:31 ET |
| `reprice_source` | finviz_afterhours | finviz_afterhours |
| shares fingerprint | `e98c9b42…` | `e98c9b42…` **unchanged** |

`written_at` is today's UTC stamp, not the document `as_of` (still
2026-08-26) — which is why `_utc_now_iso()` was used: `_recalc_totals` runs at
line 680, four lines before `last_repriced` is stamped.

## The run

`python3 scripts/portfolio_repricer.py` — the same argv cron uses. Exit 0. No
50% price-jump reject, no 25% total sanity abort, no #634 cash-safety abort.
After-hours as expected (`2026-08-29 08:17:31 ET (after-hours)`).

## Live payload — the second half of the proof

The file flipped but `/v3/cio/home` still served 578,107.50. **This was not a
stale persisted product** — a fresh `build_operator_product(persist=False)`
also returned the fossil.

Root cause: `temperament` comes from the persisted brief store
`cio.product.current` (`data/cio/cio_investment_brief.json`, producer
`cio_investment_product.build_product`). That brief had been regenerated at
**12:16:41**, during the promote restart — 50 seconds *before* the 12:17:31
reprice — so it captured the fossil.

Fixed by rebuilding the brief once (dry first, then persist). No fourth cash
writer was added.

| surface | before | after |
|---|---|---|
| `temperament.cash` | 578,107.50 | **630,784.82** |
| `cash.cash_usd` | 630,784.82 | 630,784.82 |
| `/api/v2/overview` `total_cash` | 630,784.82 | 630,784.82 |
| `temperament.cash_pct` | 44.88 | 48.97 |

All three agree. In the live payload: `578107` absent, `UNRECONCILED` absent,
`DATA_UNAVAILABLE_UNTIL_RECONCILED` absent.

`cash_total_sources()` on CURRENT:

    cash_for_s5                630784.82      (a number, not DATA_UNAVAILABLE…)
    cash_row_sum               630784.82
    portfolio_totals_total_cash 630784.82
    delta_rows_minus_declared  0.0
    sources_agree              True

## Side effects (recorded, not reverted — PASS)

- `generated_at` / `last_repriced` moved to 2026-08-29 08:17:31 ET.
- `account_summaries.fidelity_rollover_ira.residual_as_of` timestamp moved.
  That is the **only** account_summaries change.
- `finviz_quote_cache.json` — **byte-identical, untouched**. No
  `FINVIZ_API_TOKEN`, so 0/31 symbols priced; the totals recalc still ran,
  which is all this proof needs.
- `ticker_prices` Saturday upserts — **did not happen**. The sync failed:
  `password authentication failed for user "trade_ai"`. Recorded as a
  pre-existing environment condition, unrelated to this change.
- Positions/shares unchanged (md5 fingerprint identical).

## Follow-ups (not done in this pass, deliberately)

- `api_v2.py:2593` read-site recompute left in place, as instructed.
- `cash_total_sources()` still reports `writer_identified: False` and a
  `next_slice` string saying "identify the totals writer". That prose is now
  stale — the writer is identified: `portfolio_repricer._recalc_totals`.
  Cosmetic; not changed here.

## Scoreboard

    cash writer   = portfolio_repricer._recalc_totals
    proof         = Saturday after-hours reprice, 2026-08-29
    cash_gap live = 0.00
    S5            = 630,784.82 (released from DATA_UNAVAILABLE_UNTIL_RECONCILED)
