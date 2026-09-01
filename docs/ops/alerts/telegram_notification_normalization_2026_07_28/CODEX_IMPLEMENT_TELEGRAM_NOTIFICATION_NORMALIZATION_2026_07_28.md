# CODEX IMPLEMENTATION PROMPT — Trade AI Telegram Notification Normalization

Status:      HISTORICAL
as_of:       2026-07-29T12:56:50-04:00
Measured at: efcc51365 / not measured

## Authority and objective

You are the implementation agent for the Trade AI notification-normalization program.

Implement the approved notification cleanup and Command Center alert-control design using the Drive evidence package downloaded into:

```text
docs/ops/alerts/telegram_notification_normalization_2026_07_28/
```

The required source files are:

```text
TRADE_AI_TELEGRAM_NOTIFICATION_DUE_DILIGENCE_2026-07-28.md
PROPOSED_OPERATOR_ALERT_POLICY_V2.yaml
telegram_notification_audit_last_7_days.csv
telegram_notification_audit_all_messages.csv
```

The due-diligence report is the controlling functional specification for this task. The YAML is a target-state policy proposal, not a blind replacement for current configuration. Reconcile it against the live repository contracts and preserve all financial and authorization guardrails.

## Controlling repository and architecture

Repository:

```text
/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

Repository remote:

```text
PatsKiller/tardeai
```

Read before editing:

```text
AGENTS.md
all nested AGENTS.md files affecting touched paths
docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md
docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md
config/operator_alert_policy.yaml
scripts/telegram_alert.py
scripts/telegram_alert_router.py
scripts/telegram_alert_routing_policy.py
scripts/telegram_proposal_alert_policy.py
scripts/notification_url_builder.py
scripts/alert_daily_digest.py
scripts/reports_portal.py
docs/ops/alerts/PHASE126_TELEGRAM_ENFORCEMENT_REPORT.md
```

The v3.3 architecture remains controlling. Do not reinterpret financial authority, live-order authorization, session-scoped 2FA, broker safety, or protection behavior.

## Required operating mode

Create or use this implementation branch:

```text
feat/telegram-notification-normalization
```

Do not commit directly to `main`.

Begin by recording:

```text
starting SHA
current branch
working-tree status
active AGENTS.md instructions
current database migration framework
current test commands
current Telegram send-path inventory
current /v3 Reports and System routes
```

Do not overwrite unrelated local changes. If the worktree contains unrelated modifications, preserve them and isolate this work safely.

## Non-negotiable safety boundaries

During this implementation:

```text
REAL ORDER QUEUED: NO
REAL ORDER SUBMITTED: NO
REAL ORDER MODIFIED: NO
REAL ORDER CANCELLED: NO
REAL 2FA REQUESTED: NO
REAL TELEGRAM MESSAGE SENT: NO
PRODUCTION SECRET READ OR PRINTED: NO
BROKER WRITE: NO
PRODUCTION DEPLOYMENT: NO
LIVE FEATURE FLAG ENABLED: NO
FINANCIAL GUARDRAIL CHANGED: NO
/V3 ROUTE REMOVED OR REPLACED: NO
```

Use mocks, fixtures, synthetic chat IDs, outbound-disabled adapters, or test-only send captures. Never use a production Telegram bot token or real chat ID in tests.

Do not expose raw OAuth URLs, state parameters, local paths, shell commands, internal IP addresses, localhost URLs, port 7777 URLs, or secrets in operator messages.

## Functional outcomes

Implement the following end state.

### 1. Two logical Telegram channels

Create server-side logical destinations:

```text
CRITICAL_OPERATIONS
APPROVALS_ONLY
```

`APPROVALS_ONLY` is an explicit allowlist. It may receive only:

```text
live_order_2fa_required
live_session_2fa_required
protective_order_approval_required
material_live_authorization_amendment_required
```

It must never receive:

```text
paper proposal
paper approval
blocked/rebuild/watch/expired/revalidated proposal
research update
entry candidate
scanner GO/WAIT/AVOID
stop warning
general health or SIEM event
```

`CRITICAL_OPERATIONS` may receive immediate alerts only when operator action is time-sensitive and required, including:

```text
orphaned or unprotected live position
protection placement/replacement failure or uncertainty
broker authentication failure blocking active trading or reconciliation
possible partial fill with uncertain protection
failed or uncertain flatten
emergency kill/revoke
confirmed trading-impact outage affecting a live position/session
market-hours stop event that automation cannot safely resolve
```

### 2. Paper workflow cleanup

Paper proposals and automated paper lifecycle events must be Command Center only or digest material. Remove them from both immediate Telegram channels.

Do not infer actionability from message text such as `/ptreject`, `Paper Proposal:`, or a generic `approve/reject` phrase. Route from typed event facts and actual operator authority required.

### 3. Durable alert event/outbox

Implement a single database-backed notification pipeline:

```text
producer
  -> typed alert event
  -> normalization/classification
  -> correlation/dedupe
  -> routing decision
  -> immediate Telegram OR digest queue OR Command Center OR log
  -> delivery/suppression/expiry audit
```

Use additive migrations and rollback migrations.

The data model must support at minimum:

```text
alert/event ID
alert type
source system and source producer
entity/account/symbol
severity
operator action required boolean
operator action type
logical destination
route mode: IMMEDIATE | DIGEST | COMMAND_CENTER | LOG
incident/correlation ID
fingerprint
state version
authorization/order/session reference
created, updated, expires, resolved timestamps
acknowledgement state
suppression reason
last delivery status and timestamp
policy version
payload with redaction controls
```

Use PostgreSQL for persistent correlation and dedupe. Do not rely on process-memory caches for correctness.

Fingerprint inputs should include, where applicable:

```text
alert_type
source_system
entity_id
account_id
symbol
state_version
action_required
authorization_or_order_id
```

Repeated incidents update one record. Send an immediate message only on:

```text
new incident
severity increase
transition to operator action required
configured escalation deadline
useful resolution transition
```

Batch sibling events such as multiple orphaned stops into one incident.

### 4. Real digest queue

`P1_DIGEST` must no longer mean “send immediately unless deduped.”

Write digest-eligible events to a durable queue and send only scheduled, nonempty summaries:

```text
08:45 ET — overnight/risk digest
17:55 ET — operations/trading digest
```

Each digest must include:

```text
unresolved critical incidents
top risk changes
proposal/candidate counts and top five only
repeated system failures collapsed by producer/type
what changed since the prior digest
one fully qualified Command Center link
```

Canonical link:

```text
https://ms01-openclaw.tail163d14.ts.net/v3/reports
```

Do not use `bypass_router=True` as a general digest implementation escape hatch. The digest itself must be a typed, audited delivery through the central outbox.

### 5. Universal Telegram chokepoint

Inventory every sender. Migrate every direct `api.telegram.org/sendMessage` caller and any equivalent raw sender to the central outbox/sender.

Add enforceable tests or lint checks so new direct Telegram API calls fail CI, except for one narrowly documented low-level transport module.

The low-level transport must not be importable as an unrestricted bypass by application producers.

### 6. URL and redaction enforcement

All operator-facing links must use `notification_url_builder.py` or a single successor module.

Reject or sanitize messages containing:

```text
192.168.*
127.0.0.1
localhost
:7777
/v2/
raw OAuth authorization URLs or state parameters
internal filesystem paths
shell commands
```

Add an alert deep-link helper:

```text
https://ms01-openclaw.tail163d14.ts.net/v3/go/alert/<alert_id>
```

Preserve existing canonical proposal and broker-order deep links.

### 7. Seven-day active freshness

Command Center active alerts default to the trailing seven days.

No stale alert may remain active beyond seven days. An unresolved item that is still operationally relevant must become a tracked incident with owner/status/next action rather than remain an old alert.

Implement configurable TTLs consistent with the source report:

```text
market/setup candidate: session cutoff or four hours
live approval intent: intent expiry
critical protection incident: until resolved, maximum 24 hours as alert
queued digest item: 24 hours after digest inclusion
dashboard advisory: seven days
log/debug: one to seven days
```

Retain compact audit metadata according to existing governance; do not indiscriminately delete required evidence.

### 8. Command Center alert settings modal

Add an additive server-authoritative modal under the existing v3 Reports/Alerts surface. Do not replace or remove `/v3` routes.

Per typed alert type expose:

```text
General Telegram: OFF | IMMEDIATE | DIGEST
Approval Telegram: OFF | IMMEDIATE
Command Center: ON | OFF
Digest bucket: RISK | TRADING | OPS
TTL
Dedupe window
Escalate-after interval
Sound enabled
last delivery
last suppression reason
estimated trailing-seven-day volume
```

Safety invariants:

```text
paper approval types cannot be routed to APPROVALS_ONLY
live protection failures cannot be disabled from every surface
chat IDs remain secret-backed and are never stored in preference rows
preference changes are versioned and audited
save preview shows projected before/after seven-day volume
test sends are synthetic, visibly labeled, and cannot use production channels
```

Use optimistic concurrency/version checks for settings updates.

### 9. Immediate containment defaults

Ship defaults equivalent to:

```text
paper proposal Telegram OFF
blocked/rebuild/watch/expired proposal Telegram OFF
approval channel allowlist only
critic BLOCK scalp Telegram OFF
critic DOWNGRADE scalp Telegram OFF
raw real-time scalp Telegram disabled or raised to a conservative reviewed floor
P1 individual sends OFF; digest queue ON
```

Do not enable these changes in production during this Codex run. Implement config/migration defaults, tests, and documented rollout steps. If the repository’s established configuration deployment process permits safe default changes in source, keep all live runtime activation explicitly off until operator deployment.

## Implementation stages

Execute sequentially. Do not stop after producing only a plan.

### Stage 0 — Baseline and gap map

Produce:

```text
docs/ops/alerts/telegram_notification_normalization_2026_07_28/STAGE0_BASELINE.md
docs/ops/alerts/telegram_notification_normalization_2026_07_28/SENDER_INVENTORY.md
docs/ops/alerts/telegram_notification_normalization_2026_07_28/ROUTE_AND_SCHEMA_MAP.md
```

Confirm the count and paths of raw Telegram bypass senders against current repository truth.

### Stage 1 — Typed policy and containment

Implement typed alert taxonomy, logical channel allowlists, paper suppression, scalp containment defaults, and tests.

### Stage 2 — Durable outbox, dedupe, incident correlation, TTL

Implement additive schema, data access layer, routing, suppression audit, incident updates, expiry, and rollback.

### Stage 3 — Digest queue and scheduler integration

Implement nonempty risk and operations/trading digests through the audited outbox.

### Stage 4 — Sender migration and CI enforcement

Migrate all direct senders. Add repository-wide enforcement preventing new bypasses.

### Stage 5 — Command Center APIs and modal

Implement additive `/api/v3` endpoints and v3 UI. Preserve current route behavior and existing reports data.

### Stage 6 — Verification and closeout

Run unit, integration, migration, API, frontend, and regression tests. Create synthetic replay tests using the two CSV evidence files.

## Required replay/evaluation tests

Use the seven-day CSV as the primary acceptance fixture and the full CSV as a scale fixture.

Prove at minimum:

```text
zero paper proposals routed to approvals Telegram
100% approvals Telegram events require explicit live authorization
zero exact duplicate immediate deliveries inside the dedupe window
zero identical delivery to both Telegrams
seven orphaned stops correlate into one immediate incident
repeated broker-auth failures update one incident and escalate only on material transition
P1 items queue instead of sending individually
all active alerts older than seven days expire from the active projection
all generated links are HTTPS Tailscale /v3 links
messages with OAuth URLs, local paths, localhost, internal IPs, :7777, or /v2 are rejected/sanitized
all repository Telegram producers use the central outbox
settings safety invariants cannot be bypassed through API or UI
```

Measure projected output against the due-diligence sample. Report immediate-message count, digest count, dashboard-only count, log-only count, duplicate suppression count, and cross-channel duplicate count.

Target:

```text
approximately nine correlated immediate notifications in the reviewed seven-day sample
zero paper/proposal lifecycle immediate notifications
zero direct sender bypasses
```

Do not hard-code “nine” as business logic; it is an evaluation benchmark for this evidence set.

## Acceptance criteria

The implementation is complete only when:

```text
Approval Telegram contains zero paper proposals and zero research/candidate alerts.
100% of Approval Telegram messages require explicit live operator authorization.
General Telegram projected median is <= 5 immediate messages per trading day, target 1–2.
Zero exact duplicate sends inside the configured dedupe window.
Zero identical messages sent to both Telegrams.
100% of producers use the central outbox.
P1 items are queued and summarized, never sent individually.
100% of user links use the canonical HTTPS Tailscale base and valid /v3 routes.
No active Command Center alert is older than seven days.
Repeated incidents update one record/message.
Every delivery, suppression, expiry, and preference change is auditable.
Current /v3 behavior remains regression-green.
```

## Required closeout artifacts

Write:

```text
docs/ops/alerts/telegram_notification_normalization_2026_07_28/IMPLEMENTATION_CLOSEOUT.md
docs/ops/alerts/telegram_notification_normalization_2026_07_28/TEST_RESULTS.json
docs/ops/alerts/telegram_notification_normalization_2026_07_28/SENDER_MIGRATION_MANIFEST.json
docs/ops/alerts/telegram_notification_normalization_2026_07_28/ALERT_POLICY_DIFF.md
docs/ops/alerts/telegram_notification_normalization_2026_07_28/ROLLBACK.md
docs/ops/alerts/telegram_notification_normalization_2026_07_28/OPERATOR_ROLLOUT_CHECKLIST.md
```

Closeout must state:

```text
START SHA
END SHA
BRANCH
FILES CHANGED
MIGRATIONS
API ROUTES
UI ROUTES/COMPONENTS
SENDERS MIGRATED
DIRECT SENDERS REMAINING
TESTS
BUILD
PROJECTED SEVEN-DAY ROUTING RESULTS
FEATURE FLAGS
DEPLOYED: NO
REAL TELEGRAM SENT: NO
REAL ORDER ACTION: NO
REAL 2FA REQUESTED: NO
PRODUCTION SECRET READ: NO
ROLLBACK
OPEN RISKS
```

Commit completed green stages intentionally. Push the implementation branch and open or update a draft pull request if authenticated. Do not merge, deploy, enable live flags, send production Telegram messages, or change broker/live authorization state.
