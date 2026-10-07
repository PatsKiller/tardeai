# Approval reminder receipts

Dated 2026-10-07. The live crontab line is `5 * * * *` with `--send --record`. It was not run. An empty hour is not a liveness failure.

## Five facts, kept separate

| Fact | This read |
| --- | --- |
| Cron due | the line is present. The next due instant is minute 5 of the next America/New_York hour. A due line is not a run |
| Process invoked | NOT_MEASURED for any hour after this commit, because this commit is not served. The 2026-10-06 journal had command lines; stdout is not in that journal |
| Plan evaluated | NOT_MEASURED on the served tree. The served script does not write the run receipt |
| Package created | the package ledger under persistent-state exists (46,368 bytes, mtime 2026-09-29T03:05:02Z). It changes only when the plan has actions. Its age is not a missed hour |
| Operator delivery | DELIVERY_UNMEASURED. `--send`, an outbox append, and exit 0 are not a recipient receipt |

`CURRENT/data/runtime` and `persistent-state/data/runtime` resolve to the same directory. The worktree lane output signal `data/runtime/approval_package_reminder_last.json` therefore names one file once the served tree writes it. The file is absent on both sides today. The served registry copy does not yet carry that signal. The signal was not changed again.

## Receipt

`scripts/approval_package_reminder.py` writes `ApprovalReminderReceipt@v1` by a temp file and `os.replace`. A crash before replace leaves the previous file. The builder refuses `SUCCESS`.

Fields: `run_id`, `served_sha` (only a 40-hex `TRADEAI_SERVED_SHA`, otherwise null), `started_at`, `ended_at`, `planner_status`, `outcome`, action and eligible counts, suppressed count, refused count, `send_attempt_count`, `delivery_receipt_count`, `delivery_status`, `error_class`, `next_due`. No reminder text, package id, token, or secret.

An empty valid plan is `outcome=NO_ACTION`, `delivery_status=NO_ACTION`, `run_observed=true`. A caller cannot relabel that plan as delivered. The planner itself cannot emit `DELIVERY_OBSERVED`; only the reconciler can, and only with a provider message id. An actionable plan that the adapter accepts is `PACKAGE_WRITTEN` and `DELIVERY_UNMEASURED`. `sent=true` means the adapter returned. `adapter_return_is_delivery` is false. A timeout or `UncertainSend` is `UNCERTAIN` and does not increment the delivery count. A sender exception is `sender_refusal`.

`scripts/approval_reminder_reconcile.py` can match an existing transport row on `run_id` plus `provider_message_id`. The same provider id counts once. It does not send. With no provider id the status stays `DELIVERY_UNMEASURED`. An empty plan stays `NO_ACTION` even if a transport row is supplied.

## Tests and the natural hour

Unit tests cover the empty hour, a package write, sender refusal, uncertain send, crash before replace, symlink split, a stale timestamp, two overlapping invocations, and the reconciler. They do not call Telegram.

The next natural hourly fire can be compared with the journal, the new receipt, the package ledger, and a transport receipt only after this code is the served release. Until then the served hour is NOT_YET_DUE for this receipt. Do not run `--send` to collect it.

Status for the empty-hour case, once a served natural fire writes `outcome=NO_ACTION`: `NO_ACTION_RUN_OBSERVED`. That label is not available today.
