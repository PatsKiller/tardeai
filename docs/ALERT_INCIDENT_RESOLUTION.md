# Alert Incident Resolution

Status:      ACTIVE
as_of:       2026-09-21
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0

**Related:** `scripts/alert_outbox.py` · `scripts/alert_occurrence_store.py` ·
`scripts/alert_dedupe.py` · `scripts/lib/alert_transition.py` · `scripts/telegram_alert.py`

## Alerting framework — as served 2026-10-14

Refreshed 2026-10-14T18:45-04:00 at served `3e9dc5e14` (origin/main `a1b1c5c93`). Status labels: LIVE, MERGED-NOT-SERVED,
PR-OPEN, BRANCH-ONLY, PLANNED, POLICY-ONLY (defined in
`docs/implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md` §0). The sections after this one
are the 2026-09-21 record of the alert outbox and recovery chain and remain accurate for that plane.

### Routing path (LIVE)

```
producer ─► send_telegram(priority, dedupe_minutes, producer)        scripts/telegram_alert.py:706 (the chokepoint)
              ├─ legacy text  ─► telegram_alert_router.classify_alert ─► operator_alert_policy_v2.route_event
              │                     #1732: STOP HEALTH/WARNING/CRITICAL STOP ALERT + NEAR_TRIGGER/TRIGGERED/FILLED
              │                     → P0_INTERRUPT before the v2 router; exempt from the daily budget
              ├─ intent        ─► telegram_alert_router.route_intent (P1/P2/P3; receipts notification_intent_receipts.jsonl)
              └─ owned class   ─► comms gateway (mode CANARY, owned_classes ['ops'])
incidents: n8n fan-in (n8n, */5) ─► incident_notifier.py (cron */5) ─► send_system (ops bot)
SIEM: n8n_siem_bridge.py (cron 1-59/5) ─► system_health_events; siem-critical-notify (health tick, 15 min)
```

| Rule | Value (code default) | Where |
|---|---|---|
| Policy levels | P0_INTERRUPT, P1_DIGEST, P2_DASHBOARD_ONLY, P3_LOG_ONLY; `telegram_mode: actionable_only` | `config/operator_alert_policy.yaml` |
| Immediate types | orphaned_stop, position_unprotected, protection_failure/uncertain, broker_auth_blocking, partial_fill_protection_uncertain, flatten_failed_or_uncertain, emergency_kill_or_revoke, trading_impact_outage, market_hours_stop_unresolved; `platform_availability` / `data_integrity` (sentinel-tagged, hourly dedupe) | `scripts/operator_alert_policy_v2.py` `CRITICAL_IMMEDIATE_TYPES` |
| Intent P1 | never capped or quiet-held; exact-body dedupe 60 min unless `dedupe_minutes=0` (operator-action messages) | `route_intent`; AGENTS.md §9.1 (5.1.0) |
| Intent P2 | held 22:00–07:00 ET to the Reports archive, folded into the advice digest; delivered if the archive write fails | `route_intent`, `_intent_send` |
| Legacy P0 daily budget | 30 non-ops sends | `telegram_alert_router.DAILY_SEND_BUDGET` |
| Incident notifier | P1 immediate, uncapped; P2 batched every 30 min, quiet-held; daily cap 24 messages; dedupe 24 h; flap cooldown 60 min; P3 never sends | `scripts/incident_notifier.py` |
| Digests | advice digest 10:00 / 15:00 / 17:00 ET weekdays (P2 intent); `alert_daily_digest.py` 17:55 | crontab; `config/advice_digest.yaml` |
| Schwab paused | `STOP HEALTH — DEGRADED` P1 once per ET day while `config/schwab_access_mode.yaml` says `forbidden`; health agent `schwab_token_revoked` (#1733) | LIVE |
| Ratchets | `config/telegram_chokepoint_baseline.json` (files empty), `config/provider_chokepoint_baseline.json` (empty), `config/notification_intent_baseline.json` (49 sends without a declared priority) | `scripts/check_comms_gateway_enforcement.py` |

### The operator's five alert classes — coverage

| Class | Today | Status | Gap / finding |
|---|---|---|---|
| Failure | n8n Error Trigger → incident router → fan-in → notifier (6 of 16 workflows); ledger RUN_FAILED/TIMEOUT → DLQ/breach → fan-in; host producers via `send_telegram` | LIVE, partial | 10 workflows have no error workflow (WS1b-05); unit failures and OOM kills raise nothing (WS3-27) |
| SLA breach | freshness contracts → breach detector STALE_OUTPUT; heartbeat-watch for 6 alert-path lanes; `pipeline_freshness_slo.py --telegram` | LIVE, partial | `report_alert_sla_status.py` is a report, not an alert; detection latency 1–8 days for weekday lanes (WS3-29) |
| Performance degradation | none | **missing** | no p95/latency class; no metrics stack |
| Integration failure | `platform_availability` / `data_integrity` sentinels; data-source health (hourly); `broker_auth_blocking`; relay `relay_gateway_unreachable` | LIVE, partial | Schwab auth failure did not page before #1733 (WS3-01); relay refusals are logged as n8n errors, not routed by class |
| AI/LLM exception | `check_llm_provider_health.py` (BILLING/AUTH/TRANSPORT, hourly via health tick); health agent `collect_llm_spend_receipt` | LIVE, availability only | no exception class for bridge refusals, schema failures, cap hits; `check_llm_fleet_alerts.py` not scheduled |

### Known defects that decide what reaches the phone (open)

- The P2 channel is saturated by the platform's own incidents: 943 open P2 at 18:35 ET, 798 from the failure
  diagnoser (WS1-09, CRITICAL).
- `send_telegram` returns True when nothing was delivered; failed sends are not replayed (WS3-21, WS3-24).
- One bot, one chat, no second channel; no off-box dead-man (WS3-20, WS3-18).
- The dead-man (heartbeat-watch) runs inside n8n, whose failure it should report (WS1-15).
- Fills and position changes appear only as suppressed info (WS3-09); the stop half is fixed by #1732.

### Target (PROPOSED)

The four-tier taxonomy — PAGE, DIGEST, DASHBOARD, LOG — keyed on `(domain, kind)` with no default row, a
`runbook_id` on every PAGE row, delivery receipts as the liveness signal, and an independent dead-man chain with an
exit off the box: `~/n8n-maturity-verification/arch-review-20261014/ARCHITECTURE_REVIEW_20261014/ALERT_TAXONOMY.md`
(PROPOSED; not built). The alerting checks every n8n workflow must meet are in AGENTS.md §23.24 (PROPOSED 11.0.0)
and `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` §0.4. Incident handling:
`docs/runbooks/INCIDENT_RESPONSE.md`.

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
