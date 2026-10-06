# SIEM incident visibility and recovery

Status: IMPLEMENTED IN SOURCE; runtime acceptance recorded separately
Owner: platform
as_of: 2026-10-06
Measured at: base 6ada80cbc01b971cfc08b766fac30c806d0d690b

The October 6 investigation found three independent defects. The SIEM reader
suppressed every row of an incident after more than three repeats, making its
urgent count fall to zero. Free-text classification mistook “near trigger” and
“on trigger” advice for a triggered stop, while an urgent oversized stop could
fall through to P3. Finally, stop-health events stayed active after newer saved
observations showed their original condition had recovered.

## Implemented behavior

`api_v2._system_siem_dashboard` now counts each visible group once, retains its
highest priority, and counts only duplicate rows as suppressed. Repeat counts,
first/last timestamps, and raw event totals remain available. Structured stop
conditions determine the displayed event type; urgent source evidence cannot be
downgraded by a lower-priority condition. Separate accounts, orders, and
conditions have separate opaque incident keys.

`lib.siem_incident_identity` uses complete saved stop identity before an existing
condition key, so adding a key does not split legacy and new observations. Other
sources retain their source-scoped condition key or full text and durable row
identity. The only log normalization removes the validated leading timestamp
from the observed `DB_CONNECTION` log format, preserving the entire error
context. Keys do not expose account or order identifiers.

`health_agent.collect_risk_protection` counts incidents across all qualifying
24-hour rows and labels them according to their actual urgent/critical source
severity. Its existing five-incident escalation threshold and acknowledged /
resolved exclusions remain unchanged. An unavailable read is visible as a
warning. Dashboard priority and this source-severity measure remain different
projections; the dashboard also has a 14-day, source-row-limited view.

`stop_health_check` persists stable keys and keeps the existing two-hour dedupe
window, batched delivery, stop scan, and authorization process. Recovery requires
a newer exact account/order/symbol observation. Working orphaned/oversized stops
additionally require fresh, completed, promoted position-sync evidence for that
account and matching quantities. The existing positions freshness policy and
filled-stop alert window are reused. Missing, failed, duplicate, conflicting,
future, stale, or unpersisted observations never establish recovery.

The natural producer reconciles only keyed incidents that match its newly
persisted scan. Historical rows require a capped explicit-ID plan from
`plan_stop_recovery`; `apply_stop_recovery` rereads evidence before invoking the
existing canonical alert writer. `resolve_alert_event_ids` updates only named
active rows from the exact source that predate the observation, preserves audit
history, and raises on database failure. Working near-trigger recovery remains
blocked without defensible price freshness evidence.

## Evidence and limits

OBSERVED from saved data on October 6: the historical filled-stop, orphaned-stop,
and oversized-stop incidents had newer exact-order recovery evidence. A newer
orphaned-stop observation initially conflicted with a newer holding snapshot;
it was not treated as recovered until a subsequent natural lifecycle snapshot
agreed. Historical ATM connection failures also remained active after later
successful protection-pass logs. Rolling-window expiry was not resolution.

Fixture verification covers repeated alerts, independent account/order/condition
identity, malformed payloads, timestamps, severity preservation, data failures,
recovery refusal and replay. A PostgreSQL temporary-table test verifies that
unreviewed IDs, other sources, acknowledged/resolved rows, and newer/equal-time
evidence survive a bounded update; a repeat apply changes nothing. Unit tests
replace production connection, scan, delivery and writer boundaries.

No broker call, stop change, authentication request, or order is part of this
repair's verification. No live fill is inferred. Production lifecycle updates
require a separate exact-ID database grant, and code release requires the
established exact-SHA CI and release grant. Local receipts record the reviewed
plan, changed rows, served release, service pins, and observed API/UI results;
this source document does not assert those operations have happened.

## Release and rollback

Run the registered SIEM/recovery tests, Ruff, local acceptance, and the isolated
PostgreSQL proof (`SIEM_PG_TEST=1` with a guarded `m2_shadow_test_*` database).
Publish the completed tranche once, obtain exact-head merge authorization, and
prepare/promote only the CI-passing exact main SHA. Verify CURRENT, every bound
service working directory, and a natural health/stop-monitor cycle.

Code rollback uses the release script and the prior CURRENT pin. Resolved alert
rows remain in history with resolution attribution; do not reopen them merely
to roll code back. A subsequently observed real condition produces a new event
through the existing producer and review process.
