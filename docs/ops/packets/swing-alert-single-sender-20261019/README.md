# Swing entry alerts: one sender (2026-10-19)

Operator approval 2026-10-19. ENTRY APPROACHING / HIGH CONVICTION ENTRY alerts had two senders:

| sender | schedule (crontab, unchanged) | card |
|---|---|---|
| `scripts/watchlist_entry_planner.py` `_alert` | `35 17 * * 1-5` (watchlist) and `45 17 * * 1-5` (`--scope proposals`) | incomplete before FIX 1 |
| `scripts/cio_entry_state_runner.py --apply` | `*/10 9-16 * * 1-5` (market-day gate) | company, catalyst, CIO verdict |

## Change

- `config/swing_entry_alerts.yaml` `single_sender: true` (the default, and the value used when the file is
  missing or unreadable).
- The planner still plans and INSERTs every `watchlist_entry_plans` row. Each plan now carries
  `plan.alert_eligible` (false only for pre-promotion buy-rated names, which never paged). With the flag on,
  `run()` passes no alerter: the planner sends nothing, and its summary says `alerts_handed_to: cio_entry_state_runner`.
- `cio_entry_state_runner.gather()` adds to its universe every symbol with an alert-eligible `near_entry` / `ready`
  plan from the last 7 days (`lib/entry_alert_context.PLANNER_PLAN_SQL`). It already used those plans as its
  first plan source. Its existing rules still apply: one page per symbol, state and day (`cio_entry_states`
  transition key); BUY_READY always pages; ENTRY_NEAR pages only for starred symbols (operator 2026-09-21).
- Both producers read identity, catalyst and the latest CIO decision through `scripts/lib/entry_alert_context.py`.

## Behaviour the operator will see

- No 17:35 / 17:45 evening entry alerts from the planner. Its plans are paged by the runner from the next
  market-day run (09:xx ET), against the data-broker price at that moment.
- ENTRY_NEAR for a symbol that is not starred is no longer paged. The runner's 2026-09-21 rule applies, and
  the planner's NEAR-ENTRY page for such names used to bypass it.

## Cron

No crontab, systemd or n8n change is needed. Both cron lines keep their current argv. The behaviour switch
is the config flag, which is read on every run.

## Rollback (one line)

`config/swing_entry_alerts.yaml`: `single_sender: false`. The planner pages through `_alert` again, and the
runner stops adding planner-only symbols. Both take effect on the next run. No deploy is needed beyond the file.

## Proof

`tests/test_active_trader_alert_completeness_20261019.py` `test_fix6*` (registered in
`scripts/run_cio_hardening_ci.py`, anchor `ACTIVE_TRADER_ALERT_COMPLETENESS_20261019`). All are hermetic: fake
cursor, capture sender.
