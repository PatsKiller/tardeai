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

The census above is the **pre-fix snapshot**. One further incident opened between that
measurement and the closure pass later the same day, so every total below is stated against
**42**. The two figures are not in conflict; they are hours apart.

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

- **39 of the 42 pre-existing incidents stay open**, and that is the correct outcome, not a
  shortfall. The forward fix cannot reach them: `incident_id_for()` hashes `source_system`,
  which `alert_occurrences` never persists, so the originating event is unreconstructable
  and a resolution event would mint a *new* incident rather than close the old one
  (`alert_dedupe.py:110`, `resolution_without_prior_occurrence`). Three were closed by
  direct UPDATE on 2026-09-21, each against named evidence — see "Closing a pre-existing
  incident" below.
- **`acknowledged_at` is still 0 across every row.** Acknowledgement exists in the API and UI
  but is manual and has been used four times, by hand, in June.
- **Six other producers** already use `alert_transition`, so they have `t.recovered` for
  free and need the same one line as the health check: `check_expected_services`,
  `check_operator_answer_quality`, `check_served_copy_split`, `data_plausibility_monitor`,
  `paper_performance_governance`, `research_lane_health`.
- Every **other** `send_telegram` caller (198 files call it) has no recovery signal at all.
  Those need a condition state machine first, not a parameter — wiring `resolving` there
  without one would just pass a constant `False`.

## Closing a pre-existing incident

The forward path (`publish_event(..., resolving=True)`) **cannot** close a row that already
exists. `incident_id_for()` hashes `source_system`; `alert_occurrences` never persists it
(`payload ? 'source_system'` is false on every row), so the originating event is
unreconstructable — six candidate values produced six non-matching ids. A resolution event
published today mints a *new* incident and returns `resolution_without_prior_occurrence`
(`alert_dedupe.py:110`), adding noise while leaving the target untouched. A pre-existing
incident is therefore closed by direct UPDATE plus an `admin_audit_log` row.

**Two terminal statuses, both already legal** under `alert_incidents_status_check`
(`open | resolved | expired`) — only `open` had ever been used:

| Status | Meaning | The test that justifies it |
|---|---|---|
| `resolved` | the condition was verified to have ended | ask the producer **now**, read-only |
| `expired` | an event-shaped notification aged out | quiet longer than its own `DEFAULT_TTLS` entry |

**Staleness alone is never sufficient.** Measured 2026-09-21: the longest gap between
consecutive occurrences *inside* one incident is **96.0h** (`scanner_candidate`; 95.9h for
`job_telemetry` over 391 occurrences). Silence of 59–96h is therefore inside normal
recurrence and proves nothing. `expires_at` is also not a closure signal — it is a
*delivery* TTL fixed at incident creation, so a `scanner_candidate` can sit 95.8h past
expiry and still have fired 3.8h ago.

**Closure is self-correcting — but only since 2026-09-21, and the earlier claim here was
wrong.** This document previously stated that the UPDATE at the end of `record_occurrence`
(`resolved_at = CASE WHEN %s THEN %s ELSE NULL END`) meant the next non-resolving
occurrence reopened the incident and `alert_dedupe` fired `NOTIFY_RECURRED_AFTER_RESOLUTION`.
Both halves of that were real, and both were unreachable: `load_prior_state` selected
`WHERE status = 'open'`, so a resolved or expired incident was never loaded, the code took
its "new incident" branch, and the INSERT collided with the still-existing row on
`alert_incidents_pkey`. The occurrence was delivered to the operator and **dropped** —
9,223 times across 64 log files, logged only as "shadow persist skipped".

Reproduced against an isolated Postgres: unpatched, the recurrence raises
`UniqueViolation … alert_incidents_pkey` and the incident stays at `occurrence_count=1`
with one row; patched, it records `decision_reason='recurred_after_resolution'`, returns
the incident to `status='open'` with `resolved_at` cleared, and continues the occurrence
sequence (`occurrence_count=2`, `max(occurrence_seq)=2`).

**Do not treat closure as reversible on any deployment predating that fix.**

Closed 2026-09-21, each against named evidence:

| Incident | Type | Status | Evidence |
|---|---|---|---|
| `a71e498cc5b2106a399d` | `platform_availability` | resolved | `check_expected_services --json` reports `off=0`; the four timers named in the alert no longer exist |
| `1b23f2df678db8d1719d` | `stop_warning` | resolved | LYB absent from `schwab_positions_live` (48 rows) and from `stop_lifecycle` |
| ~~`4e25f628fd9c854dbb30`~~ | `scanner_candidate` | **RETRACTED — reopened** | quiet 101.3h against a 4h TTL, but this incident appears **57 times** in `alert_incidents_pkey` collision logs; dropped occurrences never advance `last_seen_at`, so "quiet" measured lost writes, not a dormant condition |

The retraction is the point: `occurrence_count` and `last_seen_at` are a **floor**, not a
census, on any incident that ever collided. Staleness-based closure is only safe once an
incident is known to be collision-free — check the logs for its `incident_id` first.

Left open deliberately: `data_integrity` (**still VIOLATION** — `analyst_data_history.payload`,
12,636 of 12,636 rows empty, severity BLOCK), two `siem_without_trading_impact` whose
components fired again the same day (`alpaca_reconciler` 11:10, `journal_review_builder`
11:00), and the `job_telemetry` bucket, several still incrementing (`ENRD` occ=105,
quiet 0.1h). That bucket was 28 at the time of the closure pass and 32 three hours later;
see the growth rate at the end of this document before reading any count here as fixed.

## The protection channel carried exactly one alert, and it was false

`classify_legacy_message` matched `orphan(?:ed|s)` as a bare substring, so
`research_lane_health`'s lane state token `lane-registry: ORPHANED,SILENT` classified a
research-lane health report as `orphaned_stop` — a `CRITICAL_IMMEDIATE_TYPES` member
carrying `operator_action_required=True` and `PROTECTION_REPAIR`. Measured the same day, it
is the **only** occurrence that alert type has ever recorded: the capital-protection
channel's entire history was this one false positive.

Fixed by requiring `stop`/`position` anywhere in the text. Deliberately **not** adjacency —
the genuine producer shape is `STOP HEALTH — ORPHANED: ANET`, where the tokens are
separated, so an adjacency rule would have converted a misrouting bug into a silent false
negative on the one channel that must never miss.

## Nothing applies expiry — and expiry alone is not safe to apply

`job_telemetry` has no entry in `DEFAULT_TTLS` and is the classifier's fallback branch, so
it inherits the 7-day default. **Adding a TTL entry for it would close nothing:** measured
2026-09-21, 0 of 32 open `job_telemetry` incidents are quiet beyond 168h, and the longest
inter-occurrence gap ever seen for the type is 95.9h. The inherited default already exceeds
observed recurrence.

The real defect is that **no reaper exists**. Nothing in cron or systemd closes an incident
when its declared `expires_at` passes; 6 of the 45 open at 12:00 on 2026-09-21 are already
past theirs. (41 at first measurement, 42 at the closure pass, 45 by 12:00 — the totals in
this document are timestamps, not constants.)

But an **expiry-only** reaper would be actively harmful, because `expires_at` is fixed at
incident creation and says nothing about the condition:

- `data_integrity` `f1c73c0dab579996a168` is 77.8h past expiry **and still violating** —
  `data_plausibility_monitor --json` reports `analyst_data_history.payload` at 12,636 of
  12,636 rows empty, severity BLOCK. A naive reaper would close a live BLOCK finding.
- Two `scanner_candidate` rows are 96.6h past expiry but **fired 4.6h ago**.

A reaper must therefore carry the event-vs-condition split: expire event-shaped types on
their own TTL, and for condition-shaped types ask the producer, read-only, before closing.

Two further cautions for whoever builds it. `alert_type` does **not** identify a condition:
`[DATA_INTEGRITY]` is emitted by at least three different producers, and the two open
`data_integrity` incidents are unrelated conditions (a column-scale violation and an
operator-answer-quality report). And plane B cannot attribute an incident to the script that
raised it — all 45 open incidents carry `source_producer='legacy_send_telegram'`, and 0 of
503 occurrences store `source_system` at all.

Finally, the backlog grows faster than manual closure: roughly 1.8 new incidents per hour
(+1, +1, +2, +5, +2 over the hours to 12:00 on 2026-09-21). Closing rows by hand is bailing.
