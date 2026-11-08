# LLM paid spend watch

`scripts/llm_paid_spend_watch.py` sends one CRITICAL alert when an LLM process spends real money above a daily line
on too many days in a week.

The operator's directive of 2026-11-07 at 21:08 ET (LQ-20261107-538) reads: "Make sure free is first. Leave the cap at
1.50. Alert when it goes over .75, 3 times in a week."

## What counts as paid

Paid spend is the sum of `llm_consumption_log.estimated_cost_usd`, grouped by America/New_York calendar day, over
rows that meet both conditions:

- the cost is above zero, and
- `metadata_json->>'billing'` is anything other than `free_oauth`. A row with no `billing` key counts as paid: that is
  how DeepSeek and Anthropic rows look.

Two things are not read:

- **Free OAuth calls** to grok and chatgpt.
- **The bridge's reservation projection.** For an OAuth-served call the bridge settles the reservation at the
  projected price (LQ-20261107-531), so that number is not spend.

For example, on 2026-11-07 `due_diligence_questions` made 69 grok-3-mini calls, all `free_oauth`, so its paid spend
that day was $0.

## Configuration: `config/llm_paid_spend_alerts.json`

All the operator's numbers live in this file. The script holds none of them, and a test checks for that.

| Field | Meaning |
|---|---|
| `process_id` | The registry process to watch |
| `source` | Where spend is read from. Only `llm_consumption_log` is supported; any other value is refused. |
| `day_threshold_usd` | A day counts when its paid spend is strictly above this |
| `days_over` | How many counted days raise the alert |
| `window_days` | The rolling window in ET days, today included |
| `dedupe_days` | How long the watch stays quiet after a delivered alert. Defaults to `window_days`. |
| `alert_class` | The class in `config/critical_text_classes.json` |

A malformed config is refused with a named reason; the script never guesses a threshold. The daily *cap* is a
separate setting: it stays in `config/llm_process_registry.json`, and in the DB through `scripts/sync_cio_process_caps.py`.

## Delivery

The alert goes through the critical hub, `scripts/lib/critical_channels.deliver`.

| Channel | When it fires |
|---|---|
| Critical Telegram chat | Always |
| Email | Always |
| Text | Only if the operator enables the class |

The class `llm_paid_spend_watch` ships with `"enabled": false`, so it sends email and the Critical chat but no text. To
add texts, the operator flips that flag.

**Dedupe.** After a delivered alert, the watch stays quiet for `dedupe_days` ET days.

**An alert that reaches no channel** is not stamped. The run exits 1 and tries again on the next run.

**Unreadable dedupe state** fails toward alerting: a duplicate alert is cheaper than a silent breach.

## Running it

```
.venv/bin/python scripts/llm_paid_spend_watch.py --dry-run   # computes and prints; sends and writes nothing
.venv/bin/python scripts/llm_paid_spend_watch.py             # real run
```

A real run writes two files under the persistent state root:

- `data/runtime/llm_paid_spend_watch_state.json`, the dedupe state
- `data/runtime/llm-paid-spend-watch_last.json`, the lane receipt

The DB session is read-only at the server.

## Lane status

The lane is **staged, not active**. `config/n8n_run_allowlist.json` carries the entry `llm-paid-spend-watch` in this
state:

- `live_arg` is `null`
- `env_allowlist_mode` is `report`
- there is no registry row, no cron and no schedule

Activating it, with a once-a-day schedule after the ET day's spend has settled, is the lead's or the operator's call.

## Tests

`tests/test_llm_paid_spend_watch_lq538_20261107.py`, gated by `config/ci_gates/llm_paid_spend_watch_lq538_20261107.json`.
