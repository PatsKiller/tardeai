# Alert Incident Resolution

Status:      ACTIVE
as_of:       2026-09-21
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0

**Related:** `scripts/alert_outbox.py` · `scripts/alert_occurrence_store.py` ·
`scripts/alert_dedupe.py` · `scripts/lib/alert_transition.py` · `scripts/telegram_alert.py`

## Two planes, one recovery signal

There are **two** alert records, and until 2026-09-21 only one of them could close.

| | Plane A | Plane B |
|---|---|---|
| Table | `alert_events` | `alert_incidents` / `alert_occurrences` |
| Written by | `alert_event_writer.save_alert_event` | `alert_outbox.publish_event` |
| Resolved by | `resolve_alert_events`, called from `alert_transition.commit` when `t.recovered` | dedupe decision `is_resolution`, driven by `resolving=True` |
| Entry point | producer calls the writer directly | `publish_legacy_message` — the **only** production entry |

`alert_condition_state` computes `new | ongoing | heartbeat | recovered | reversed |
cleared`, and twelve scripts use it. `alert_transition` turns `recovered` into a plane-A
resolution. **Plane B never heard that signal** because nothing passed it.

## Why the flag must be caller-supplied

Plane B's input is raw message text. `classify_legacy_message` carries **no recovery
vocabulary** — a recovery send is indistinguishable from an alert send by inspection. The
producer is the only thing that knows a condition ended, so `resolving` is a parameter, not
an inference. Inferring it from text would eventually resolve an incident because a message
happened to contain the word "recovered".

## The chain

```
producer (knows t.recovered)
  -> send_telegram(..., resolving=)            scripts/telegram_alert.py
  -> publish_operator_message(..., resolving=)  mode branch: OFF | SHADOW | ACTIVE
  -> publish_legacy_message(..., resolving=)    scripts/alert_outbox.py
  -> publish_event(event, resolving=)           threads to the occurrence store
  -> record_occurrence(..., resolving=)         scripts/alert_occurrence_store.py
  -> should_notify(..., resolving=)             scripts/alert_dedupe.py -> is_resolution
  -> UPDATE alert_incidents SET resolved_at=..., status='resolved'
```

Every parameter defaults to `False`, so a producer that says nothing changes nothing.

## What was wrong

Measured 2026-09-21, before the fix:

| | |
|---|---|
| Open incidents | **41** |
| Distinct dedupe keys | **41** |
| Resolved | **0** |
| Acknowledged | **0** |
| Notified | **41** |
| Oldest | 2026-09-16 |
| Still being touched that day | 11 |

`publish_legacy_message` called `publish_event(event)` **bare**. One missing keyword on one
function. Dedupe itself was working correctly — one incident per condition, occurrence counts
climbing (90, 61, 48) while notifications stayed throttled (7, 5, 3). Conditions were
suppressed properly; they simply never ended.

`job_telemetry` was 27 of the 41 with 58 notifications.

**ACTIVE mode shared the identical gap** (same `publish_legacy_message` call at
`telegram_alert.py:280`), so no `runtime_mode` change would have fixed it. SHADOW does **not**
suppress delivery — `telegram_alert.py:253` calls `_legacy_send` exactly as OFF does.

## Known limit

`send_telegram` short-circuits to `_legacy_send` when `reply_markup`, `chat_ids`, `thread_id`
or `link_preview_options` are set, bypassing publish entirely. **A recovery sent with a
keyboard will not resolve its incident.** Recorded in the code at the call site.

## Wiring a producer

Only `check_data_source_health` supplies the signal today. Any producer already using
`alert_transition` has it for free:

```python
t = evaluate(CONDITION_KEY, fingerprint_state(...), alertable=bool(findings), path=STATE_PATH)
ok = send_telegram(body, message_class="operator_alert", resolving=t.recovered)
```

`t.recovered` is "was bad, now healthy" (`alert_transition.py:136`). No new state is needed.

## Reading the state

```sql
SELECT status, COUNT(*), MIN(first_seen_at), MAX(last_seen_at)
  FROM alert_incidents GROUP BY 1;

SELECT alert_type, COUNT(*) FROM alert_incidents WHERE status='open' GROUP BY 1 ORDER BY 2 DESC;
```

## Not fixed by this change

- **The 41 pre-existing open incidents stay open.** Nothing retroactively signals their
  recovery, and some may be genuinely still-broken. Closing them is an operator decision.
- **`acknowledged_at` is still 0 across every row.** Acknowledgement exists in the API and UI
  but is manual and has been used four times, by hand, in June.
- **Six other producers** already use `alert_transition`, so they have `t.recovered` for
  free and need the same one line as the health check: `check_expected_services`,
  `check_operator_answer_quality`, `check_served_copy_split`, `data_plausibility_monitor`,
  `paper_performance_governance`, `research_lane_health`.
- Every **other** `send_telegram` caller (198 files call it) has no recovery signal at all.
  Those need a condition state machine first, not a parameter — wiring `resolving` there
  without one would just pass a constant `False`.
