# Trade AI Telegram Notification Due-Diligence Report

Status:      HISTORICAL
as_of:       2026-07-29T12:56:50-04:00
Measured at: efcc51365 / not measured

**Review date:** 2026-07-28  
**Source chats:** `TradeAI Proposal Decisions` and `tradeai_bigjohn718_bot`  
**Data window:** 2026-05-18 through 2026-07-28  
**Freshness window used for active-state analysis:** trailing seven days, ending 2026-07-28 16:05:02 EDT  
**Repository configuration reviewed:** `PatsKiller/tardeai`, connector snapshot at commit `a51ddd72f75b9fbe5dac749bc786396c9b558104`

## Executive verdict

The Telegram system is not functioning as an actionable notification channel. It is functioning as a duplicate event stream.

Across both exports there are **13,004 messages**:

- `TradeAI Proposal Decisions`: **7,129**
- `tradeai_bigjohn718_bot`: **5,875**
- Exact repeated deliveries inside a chat: **2,851** (21.9%)

In the strict trailing seven-day window there are **3,586 messages**, including **731 within-chat exact duplicates** and **60 deliveries of messages duplicated across both chats**.

A conservative routing review marks only **23 raw messages** as immediate critical/approval candidates. After incident correlation and batch aggregation, the same seven-day sample should have produced about **9 phone notifications**, plus one or two scheduled digests per day. That is a projected **99.7% reduction** in immediate phone traffic.

## What is actually spamming the phone

### Approval Telegram

During the trailing seven days, the approval chat received:

| Message family | Count | Recommended treatment |
|---|---:|---|
| Trade proposals | 832 | Command Center only unless an exact live order intent requires 2FA |
| Holding research updates | 521 | Command Center only |
| Entry alerts | 296 | Command Center; top items in digest |
| Stop warnings | 21 | Risk digest; never approval channel |
| Protective/trailing stop approvals | 6 | Approval Telegram |
| Messages containing `/ptapprove` | 0 | None in this seven-day sample |
| “Gates failed or incomplete” messages | 754 | Command Center only |

The approval channel was therefore almost entirely non-approval traffic. Paper proposals are automated and should not reach this channel.

### General Telegram

The largest seven-day sources were:

| Message family | Count | Recommended treatment |
|---|---:|---|
| Hung/piled-up job reaper notices | 329 | Command Center/log only |
| Revalidation required | 214 | Trading digest |
| Automated trade cancelled | 233 | Trading digest |
| SIEM P1 | 175 | Ops digest unless confirmed trading/protection impact |
| System-health output invalid | 162 | Command Center; page only when protection/execution is impaired |
| Escalation analysis failed | 117 | Command Center only |
| ATM proposal expired | 79 | Command Center/log only |
| Near-stop warnings | 103 | Risk digest |
| Orphaned stops | 7 | Immediate critical alert, batched as one incident |
| Stop-trigger messages | 8 | Most were explicitly after-hours/pre-market and said not to act immediately; put in risk digest unless protection is uncertain |
| Re-auth failures | 4 | One immediate incident notification, then update the same incident |

## Root causes in the current configuration

1. **The proposal destination is too broad.** The routing policy sends `ACTIONABLE_READY`, blocked, rebuild, price-moved, watchpool, and stale proposal states to the proposal channel. It routes by broad alert type instead of actual operator authority required.

2. **Paper workflow semantics are outdated.** The proposal policy labels `ACTIONABLE_READY` as high urgency and builds approve/reject controls even for the automated paper lane.

3. **The P0 pattern is structurally overbroad.** Any `Paper Proposal:` is P0. Any message containing `/ptapprove` or `/ptreject` is P0. Because even blocked messages include `/ptreject`, blocked paper/proposal states become phone interrupts.

4. **“P1_DIGEST” is not a digest queue.** The current send gate permits P1 items to send immediately if they are not deduplicated. The daily digest exists, but it does not replace individual P1 sends.

5. **Dedupe is volatile.** The central router uses an in-memory cache. Separate jobs, process restarts, and direct senders do not share state.

6. **There is no universal Telegram chokepoint.** A repository enforcement report documents 34 scripts that call Telegram directly and bypass routing.

7. **Scalp alert settings are explicitly noisy.** Real-time scalp alerts are enabled at score 18, critic BLOCK and DOWNGRADE still send, and up to ten live alerts per hour are allowed.

8. **The channel model is only “proposal” versus “general.”** It has no per-alert operator preference, digest bucket, TTL, state-change rule, escalation policy, or “dashboard only” persistence contract.

9. **Security and usability data leaks into Telegram.** Re-auth failures include raw OAuth URLs/state, internal filesystem paths, and shell instructions. Telegram should contain one safe fully qualified Command Center link instead.

## Target routing policy

### Telegram 1 — Critical Operations

Send immediately only when operator action is both required and time-sensitive:

- orphaned or unprotected live position;
- protection placement/replacement failed or uncertain;
- broker/account authentication failure that blocks current trading or reconciliation;
- live order rejection after a possible partial fill;
- emergency kill/revoke or unresolved flatten;
- confirmed market-hours stop event only when automation/protection cannot safely resolve it;
- severe trading-impact outage while a live session or live protected position exists.

Everything else is digest, Command Center, or log.

### Telegram 2 — Approvals Only

Permit only:

- exact live order 2FA approval;
- exact live session authorization;
- protective/trailing-stop approval when operator authority is actually required;
- material amendment to an already authorized live envelope.

Never permit:

- paper approvals;
- paper proposals;
- blocked/rebuild/watch proposals;
- research updates;
- entry candidates;
- stop warnings;
- general system health;
- scanner GO/WAIT alerts.

### Digest

Use an event queue, not immediate Telegram sends.

Recommended schedule:

- **08:45 ET risk/overnight digest**, only when items exist;
- **17:55 ET operations/trading digest**, only when items exist.

Each digest should show:

- unresolved critical incidents;
- top risk changes;
- proposals/candidates summarized by counts and top five;
- repeated system failures collapsed by source;
- what changed since the prior digest;
- one fully qualified link: `https://ms01-openclaw.tail163d14.ts.net/v3/reports`.

### Command Center only

Keep current and searchable:

- all paper proposals and automated paper lifecycle;
- blocked/rebuild/expired/revalidated proposal states;
- research updates;
- entry alerts and scanner candidates;
- LLM/escalation failures;
- pipeline and job telemetry;
- near-stop and non-immediate stop states;
- health and SIEM events without confirmed trading impact.

## Freshness and retention

“Seven days” should apply to the active operator surface, not destroy the audit trail prematurely.

| Event class | Active TTL | After TTL |
|---|---:|---|
| Market/setup candidate | Until session cutoff or 4 hours | Expire from active feed |
| Live approval intent | Intent expiry, usually minutes | Mark expired |
| Critical protection incident | Until resolved, max 24 hours as alert | Convert to incident/case; remove alert |
| Digest item | 24 hours after digest | Keep in seven-day Reports history |
| Dashboard advisory | 7 days | Purge from active feed; retain compact audit metadata if required |
| Log/debug | 1–7 days | Operational log retention policy |

No unresolved alert should remain active beyond seven days. If still relevant, it must be a tracked incident with owner, status, and next action—not a stale notification.

## Persistent dedupe and correlation

Replace text/in-memory dedupe with a durable event identity:

```text
fingerprint =
  alert_type
  + source_system
  + entity/account/symbol
  + state_version
  + action_required
  + authorization_or_order_id
```

Rules:

- update the existing alert when the same incident changes;
- send Telegram only on NEW, severity increase, action-required transition, or escalation deadline;
- never send identical content to both Telegrams;
- batch sibling events, such as seven orphaned stops, into one incident message;
- maintain one Telegram message per incident and edit it where supported;
- suppress retries and “still failing” messages until escalation threshold;
- record every suppression decision in the database.

## Alert-settings modal

Add a server-side settings modal under Command Center → Reports/Alerts.

Each alert type should expose:

- General Telegram: `OFF | IMMEDIATE | DIGEST`
- Approval Telegram: `OFF | IMMEDIATE`
- Command Center: `ON | OFF`
- Digest bucket: `RISK | TRADING | OPS`
- TTL
- Dedupe window
- Escalate-after time
- Sound
- Current seven-day estimated volume
- Last delivery and last suppression reason

Safety controls:

- live protection failures cannot be disabled from every surface;
- paper approval types cannot be routed to Approval Telegram;
- chat IDs remain secret-backed; the modal stores logical channels only;
- every change is versioned and audited;
- save shows a before/after projected message count;
- test sends use synthetic content and are visibly labeled.

## URL contract

All notification links must go through the central URL builder and use:

```text
https://ms01-openclaw.tail163d14.ts.net
```

No user-facing Telegram message should contain:

- `192.168.*`
- `127.0.0.1`
- `localhost`
- `:7777`
- legacy `/v2/`
- raw OAuth authorization URLs
- internal filesystem paths
- shell commands

Recommended deep links:

- proposal: `https://ms01-openclaw.tail163d14.ts.net/v3/go/proposal/<id>`
- live order approval: `https://ms01-openclaw.tail163d14.ts.net/v3/go/order/<intent_id>`
- alerts/digests: `https://ms01-openclaw.tail163d14.ts.net/v3/reports`
- risk incident: create `https://ms01-openclaw.tail163d14.ts.net/v3/go/alert/<alert_id>`

## Implementation sequence

### Phase 0 — Immediate containment

- Paper proposal Telegram: OFF.
- Blocked/rebuild/watch/expired proposal Telegram: OFF.
- Approval Telegram allowlist: live 2FA/session/protective authorization only.
- Set critic BLOCK/DOWNGRADE scalp sends to OFF.
- Disable raw real-time scalp Telegram or raise the floor sharply until the new policy exists.
- Stop P1 items from sending individually; queue them for digest.
- Remove re-auth raw URLs and local paths from messages.
- Route both chats through one central sender.

### Phase 1 — Durable alert outbox

Implement one database-backed event/outbox pipeline for every producer:

```text
producer → alert event → normalize/classify → correlate/dedupe
         → route decision → Telegram/digest/Command Center/log
         → delivery/suppression audit
```

Direct Telegram API calls become prohibited by test/lint policy.

### Phase 2 — Command Center and settings modal

- alerts feed with seven-day default;
- unresolved/current filters;
- channel/digest/TTL modal;
- preview of projected volume;
- full incident details and audit history;
- freshness countdown and automatic expiry.

### Phase 3 — Migration and cleanup

- migrate all direct senders;
- backfill logical alert types;
- retire legacy `/v2/` and local links;
- collapse old notifications to seven-day active data;
- preserve only the audit metadata required by governance.

## Acceptance criteria

- Approval Telegram contains zero paper proposals and zero research/candidate alerts.
- 100% of Approval Telegram messages require explicit live operator authorization.
- General Telegram median is at most five immediate messages per trading day; target is one to two.
- Zero exact duplicate sends inside a dedupe window.
- Zero identical messages sent to both Telegrams.
- 100% of producers use the central outbox; zero direct Telegram API senders.
- P1 items are queued and summarized, never sent individually.
- 100% of user links use the canonical Tailscale HTTPS base and valid `/v3` routes.
- No active Command Center notification is older than seven days.
- Repeated incidents update one record/message.
- Every delivery, suppression, expiry, and preference change is auditable.
