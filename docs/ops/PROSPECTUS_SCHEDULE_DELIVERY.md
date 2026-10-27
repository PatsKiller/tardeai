# Ticker Prospectus — run windows and delivery

```
Status:      DRAFT (go-live PR; lane at shadow until the steps in "Going live")
as_of:       2026-10-27T03:30:00Z
Measured at: branch feat/prospectus-schedule-live-20261026 (supersedes #2193 and #2207), on main 25d759908; not live
```

Operator 2026-10-26: "Those new reports shouldn't just run ad hoc independently. They should be queued up and run a
certain time of the day, like if something moves plus or minus the 8% threshold; also those reports should be sent
out both in Word and PDF as a notification [on] Telegram and [email]." Email is the run audit; at go-live the same
day the operator added the PDF and Word files of HOLDINGS reports as attachments (Watch reports linked), with a size
cap per email and links beyond it.

## What runs when

The n8n lane `prospectus-build` fires every 15 minutes and runs `scripts/prospectus_window.py`. Each fire does one of:

| Fire | What it does |
|---|---|
| A window is due | Collect finished Watch batch results, evaluate cadence and triggers, **enqueue** what is due with a reason, submit queued Watch rows to the batch (watch windows), then drain the queue |
| No window, an operator "Rewrite now" row is queued | Drain only operator rows (at most `operator_rewrite.max_per_fire`, default 3) |
| Neither | Read the queue file and exit; no house store is read |

Windows (`config/prospectus.json` → `run_windows`, America/New_York wall clock, so DST needs no change):

| Window | Time (ET) | Days | Scopes | Triggers | Max reports |
|---|---|---|---|---|---|
| `post_close` | 17:45 | Mon–Fri | holdings + watch | all | 12 |
| `pre_market` | 07:00 | Mon–Fri | holdings | missing, earnings-after, material news, stop event, CIO stance change | 6 |

- A window runs once per day, from its start until `catch_up_minutes` (120) later, so a late or missed fire still runs it.
- `weekend: true` on a window adds Saturday and Sunday.
- The record of runs and the month's prospectus spend is `<state>/data/prospectus/windows.json`.

## Triggers (enqueue only)

| Reason | Scope | Rule |
|---|---|---|
| `missing` | both | no report yet |
| `monthly_due` / `quarterly_due` | holdings / watch | report older than `cadence.<scope>.full_days` (30 / 90) |
| `after_earnings` | both | a recorded earnings date passed since the last report |
| `day_move ±N% close <date>` | holdings (`day_move_scopes`) | the last two daily closes moved ≥ 8%, and that close (16:00 ET) is after the last report — one close fires once |
| `material_news` | both | a catalyst newer than the last report |
| `stop_event` | holdings | the recorded stop levels differ from the ones the last report used |
| `cio_stance_change` | holdings | CIO stance differs from the last report's |
| `promoted_to_proposal` | watch | CIO stage reached proposal since the last report |
| `weekly_delta` | holdings | nothing else due and the report is ≥ 7 days old (short delta) |

## Draining

- Order: operator rewrites (priority 1), then holdings by $ value (premium top 5 first), then the watch list.
- A window takes at most `max_reports`. The governed credit path stops it at the daily cap (`QueueLater`).
- Rows a window may not take (watch rows in `pre_market`) are parked as `held_for_window` for the run and restored after. Every fire restores any parked row first.
- Leftovers stay queued for the next window.
- Watch rows use the Message Batches API (`run_windows.watch_batch.enabled`, default on; 50% price;
  `scripts/lib/prospectus/batch.py`). A window covering the watch scope submits up to `watch_batch.max_submit` (20)
  queued Watch rows (`batch.submit_due`: data-quality gate and web planning first); `pipeline.run_queue` skips them.
  Every window first collects finished results (`batch.collect` -> `pipeline.persist_doc`, which also writes the CIO
  memory), and those reports are delivered with that window's run. Holdings and operator rewrites stay synchronous.
  `enabled: false` makes the window write Watch rows synchronously.
- Receipt `empty_reason` when a live fire wrote nothing: `no_new_input`, `deferred_to_batch`, `credit_cap_reached`,
  `data_blocked`; failures with nothing written carry no reason (RUN_FAILED `empty_output`, health contract).

## Delivery

The lane sends nothing (AGENTS.md §23.14, §24.1). Each run that wrote or failed a report writes one record to
`<state>/data/prospectus/delivery/outbox/`. The host sender `scripts/prospectus_deliver.py` reads it. It runs from the
systemd timer `tradeai-prospectus-deliver.timer` every 10 minutes (lane `prospectus-deliver`; the unit files are in
`config/systemd/user/`, and installing them is the coordinator's or operator's step).

**Telegram** goes through `telegram_alert.send_telegram` and `send_telegram_document` as P2 intents.

- One summary message per run. Each report line shows: symbol, scope, CIO conviction, gate status, trigger reason, a
  verdict-changed flag, the verdict line and a link to `https://ms01-openclaw.tail163d14.ts.net/v3/prospectus/<SYM>`.
- Then each report's PDF and Word file are sent as documents.
- If a run has more than 10 reports, only the holdings' files are attached; the rest are linked.
- A file over 50 MB is linked instead of attached.

**Email** goes through `email_notifier.send_email` (gog Gmail; `attachments=` passes one `--attach` per file). It is
one plain-text audit per run, plus the PDF and Word files of the run's HOLDINGS reports:

- `delivery.email.attach_scopes` (default `["holding"]`), `formats` (`pdf`, `docx`), `attachments` (on).
- `delivery.email.max_attachment_bytes` (20 MB): reports are attached whole (PDF + Word), in run order (holdings by $
  value), while the total fits; a report that does not fit is linked and listed under "Over the 20 MB email cap".
- Watch reports are linked, never attached (they still get their files in Telegram).

The audit contains:

- the reports written, with each one's trigger reason, gate status, status and CIO conviction
- each verdict, and for a changed verdict both the old and new text
- each report's cost, the run's cost and the month-to-date prospectus spend
- failures
- links

**Toggles:**

- `delivery.telegram.enabled` and `delivery.email.enabled`.
- `delivery.scopes.watch` (default on). Holdings always deliver.
- `delivery.on_operator_rewrite` (default on).

**Idempotency:** `<state>/data/prospectus/delivery/ledger.json` keys every report by `SYMBOL@version`. It records the
Telegram summary, each file sent, and the email per run.

- A rerun sends only what is missing.
- A completed outbox record moves to `delivery/sent/`; nothing is deleted.
- A record still failing after `delivery.max_attempts` (3) sends one P2 failure alert, and the job exits 1.

Accounts never appear in either message.

## Running it

```
python3 scripts/prospectus_window.py                                   # dry run: due window, would-enqueue, writes nothing
python3 scripts/prospectus_window.py --now 2026-10-27T21:50:00Z         # what-if at an instant
python3 scripts/prospectus_window.py --apply --window post_close        # operator: run a window now
python3 scripts/prospectus_deliver.py                                  # dry run: the delivery plan, sends nothing
python3 scripts/prospectus_deliver.py --apply                          # send pending outboxes
```

`scripts/prospectus_build.py` remains the operator CLI for first builds and named symbols. The lane no longer calls it.

## Going live (operator steps, in order)

The PR ships the lane at **shadow** (`live_arg` null, dispatch `dry_run`) and the delivery timer **not installed**
(registry row `prospectus-deliver` `NEVER_SCHEDULED`). The health contract `prospectus-build` is `REVIEWED`.

1. **Merge** (shared-infra: operator squash-merge), then let the host deploy poller promote the merged `main` SHA
   (§25.10) and confirm `CURRENT` serves it.

   ```bash
   gh pr merge 2215 --squash
   readlink -f ~/trade-ai-releases/portfolio-server/CURRENT      # must name the merged SHA before step 2
   ```

2. **Install and enable the delivery timer** (needs a `service` grant). Copy from the served release, never a worktree.

   ```bash
   cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild && G=bin/guard && SHA=$(git rev-parse origin/main)
   $G grant service --for 4h --uses 4 --reason "PR #2215 sha $SHA: install + enable tradeai-prospectus-deliver.timer from CURRENT; never delete"
   CUR=$(readlink -f ~/trade-ai-releases/portfolio-server/CURRENT)
   for u in tradeai-prospectus-deliver.service tradeai-prospectus-deliver.timer; do install -m 0644 $CUR/config/systemd/user/$u ~/.config/systemd/user/$u; done
   systemctl --user daemon-reload && systemctl --user enable --now tradeai-prospectus-deliver.timer
   systemctl --user list-timers --all | grep prospectus-deliver
   cd $CUR && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/prospectus_deliver.py   # dry run: the plan, sends nothing
   ```

3. **Flip the lane live** (config-write; a follow-up PR the operator merges, then deploy): in
   `config/n8n_run_allowlist.json` set `prospectus-build` `live_arg` to `["--apply"]`; in `config/lane_registry.json`
   set row `prospectus-build` `scheduler.stage` `canary` and `dispatch.mode` `live` (the executor's stage clamp keeps
   a `shadow` row at `dry_run` whatever `live_arg` says), and row `prospectus-deliver` `state` `ACTIVE`
   (`state_since` the install date). Update `tests/test_prospectus_build_lane_20261026.py` (it pins shadow /
   `live_arg` null) in the same PR.

   Proof after the first window (17:45 or 07:00 ET): `jq '{ok_at, produced_count, empty_reason, summary}'
   $STATE_ROOT/data/runtime/prospectus-build_last.json`, one `delivery/outbox` record moved to `delivery/sent/`, the
   Telegram summary + files, the email with the holdings PDF + Word attached, and
   `$STATE_ROOT/data/runtime/prospectus-deliver_last.json` `ok: true`.
