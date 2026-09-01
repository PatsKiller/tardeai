# CIO leftover closeout (2026-08-29)

Status:      HISTORICAL
as_of:       2026-08-29T15:08:51-04:00
Measured at: efcc51365 / not measured

No new wave. Four leftovers closed.

> The instruction arrived with a header saying "fix the question_id contract and
> re-run the critique" and a body saying **NO WAVE 3F** with item 5 forbidding a
> 3D hop. Re-running the critique *is* a 3D hop, so the body was followed and
> the header flagged rather than silently chosen between.

## 1. `api_v2.py:2593` read-site recompute — **deleted**

Both release conditions met on live data:

    stored total_cash      630,784.82
    is_cash row sum        630,784.82
    cash_gap                     0.00
    total_cash_source      position_rows
    /v2/overview           630,784.82
    /v3/cio temperament    630,784.82

The 2026-07-21 workaround derived cash at the READ site because the stored
field was a fossil nothing refreshed. #635 made `portfolio_repricer.
_recalc_totals` write it every pass, and the Saturday proof showed agreement to
the cent. Readers now take the stored field.

Two places deriving one number is precisely how the original drift hid for
three months — the read site papered over a writer that had stopped writing.
A `None` stored value now surfaces `0` rather than silently reconstructing,
so a real gap stays visible.

The guard test was **inverted**: it asserted the workaround must survive; it now
asserts it is gone and that `api_v2` reads the stored field.

## 2. Vacuous tests — 3 found, 3 fixed, guard added

An AST guard against `or True` already existed and is correct. It scanned
**two source files** and never `tests/`, which is why all of these survived:

| test | was | now |
|---|---|---|
| `test_cio_whatsapp_p4` | `assert not sent or ... or True` on a **`dry_run=False` send path** | `assert not sent` |
| `test_cio_action_ledger::test_zero_provider_calls` | `assert True` under a docstring claiming no provider imports | reads its own source, fails on a real import |
| `test_cio_agent_handoff_queue::test_zero_provider_calls` | same | same |

The WhatsApp one was the dangerous one: it would have passed **even if a
message had actually been sent**, which is the single thing it existed to
prevent. It passes now with the real assertion — production behaviour was
correct; only the test was blind.

New `tests/test_no_vacuous_assertions.py` extends the AST check across the
cash / loader / cio / holdings / portfolio / research / wave3 / secrets suites:

- `or True` anywhere inside an assertion
- unfalsifiable constant assertions (`assert True`, `assert 1`, `assert "x"`)
- a **negative control** that plants a bad file and confirms the detector fires
- a scope test, so the guard cannot pass by matching nothing
- the pre-existing two-file source guard still asserted, so this complements
  rather than replaces it

475 checks across the scoped suites.

## 3. Interdict canary — expectation corrected, delivery untouched

`test_invariant_notification_delivery_fail_closed_no_credentials` pinned
`DELIVERY_BLOCKED_CREDENTIALS`. CURRENT returns `DELIVERY_INTERDICTED` because
the interdict fires first — the system behaving **more** safely than the test
demanded, reading as a regression for days.

The invariant is *delivery fails closed*, not *which guard stopped it*. It now
accepts either recognised fail-closed reason. **No credentials delivery was
enabled to satisfy the old name.** This was the last pre-existing failure being
carried.

## 4. Seasonality surface — already French, pin recorded

    seasonality resolver -> us_equity_monthly_french_1926.csv
    is the French series : True
    is the synthetic file: False

Completed in Wave 3A.3; BEFORE/AFTER table already in
`CIO_SEASONALITY_FRENCH_SURFACE_2026-08-29.md`. Skipped per instruction.

## Verification

665 tests green across the affected surface; acceptance green; `api_v2.py`
parses. `cio_command_center.py` and the two CRLF test files edited via
`safe_text_edit` — 0 stray LF.

## Not done

No 3D hop, no Grok allowlist, no enqueue, no notify-on, no 3F, no digest cron,
no new Telegram producer, MBI 0, ROTATE advisory-only.
