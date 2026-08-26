# CIO Notification Policy — Signal over Spam

Authority: `READ_ONLY_ADVISORY`. This policy governs **delivery**, not
financial truth. It never gains execution authority and never mutates broker /
order / stop / 2FA / risk policy.

**R11:** Missing policy is no longer a forever-silent `POLICY_REQUIRED` suppress
when the book is independently material. That becomes a bounded `POLICY_GAP`
operator question (semantic-deduped). Operator messages must include HEADLINE /
WHY NOW / verified situation / CIO view — never raw JSON. Interactive
“why haven’t you told me anything today?” reads the same notification state.

## Problem statement

The ten-minute material scanner (`tradeai-cio-material-scan.timer`) was acting
as a periodic **publisher**, not an event backstop. On Aug 17, 2026 the CIO Desk
emitted 54 machine-like messages (19 cash HOLD/WAIT, 19 SCHD blocked TRIM,
15 re-entry WAIT, 1 deferred review) — roughly 2–3 messages every ten minutes
that repeated the same operator conclusion under fresh `decision_id`s.

Root causes were structural, not cosmetic:

1. **Timer as publisher** — `scan_office()` delivered every `select_publications()`
   result on every tick.
2. **Unstable cash identity** — `dec_cash_<digest(status,action,cash_digest)>`
   churned on tiny mark/balance drift.
3. **Unstable re-entry identity** — `dec_reentry_<digest(action,ready[:12],near[:12])>`
   churned on READY↔NEAR membership.
4. **Literal dedupe** — `decision_dedupe_key` bound `decision_id` + input digest +
   evidence digest + material state, so a new `decision_id` always re-paged.
5. **Materiality too broad** — `is_material_event()` treated any WAIT / HOLD_CASH /
   blocked TRIM with a nontrivial `why_now` as material.
6. **REJECT suppression gap** — `rejected_unchanged()` required exact digest
   equality; identity churn defeated it.
7. **Renderer gibberish** — `HOLD_CASH CASH`, `RE_ENTER REENTRY`, `READY=N NEAR=N
   WAIT=N`, `ACT_NOW=0`, `operator_challenge_status=OPEN`, mid-word truncation
   (`(Re-`).

## Four identities

`scripts/lib/cio_notification_signal.py` separates four identities. They are
never overloaded onto `decision_id`.

| Identity | Function | Changes when | Drives |
|---|---|---|---|
| Decision lineage | `decision_lineage_id()` | the operator question changes | dedupe + REJECT binding |
| Evidence generation | `evidence_generation_id()` | raw evidence evolves | trace / Command Center |
| Material generation | `material_generation_id()` | operator meaning changes | notification decision |
| Notification identity | `NotificationStateStore` record | operator was told this generation | delivery decision |

### Lineage examples

- `cash_posture:CASH` — does not change for $50 of cash drift.
- `reentry:BOOK` — does not change for READY list ordering.
- `position:SCHD:CONCENTRATION` — a concentration TRIM.
- `position:<SYM>:<STANCE>` — other canonical position decisions.
- `freshness:BOOK` — board freshness.

### Material generation (semantic only)

- **Cash**: `(posture_status, action, deploy_now>0)`.
- **Re-entry**: `(action)` — WAIT stays WAIT across list churn.
- **Position**: `(standing, current_action, act_now, blocking, delta_bucket)`.

`delta_bucket` quantizes to `MATERIAL_DELTA_THRESHOLD_USD` (default $5,000), so
a $50 drift never opens a new generation.

## Notification state machine

`decide_notification()` produces a `NotificationDecision@v1` with fields
`notification_id`, `decision_id`, `decision_lineage_id`,
`material_generation_id`, `evidence_generation_id`, `wake_id`, `trace_id`,
`notification_class`, `materiality_reason`, `suppressed_reason`,
`standing_recommendation`, `current_action`, `act_now`, `blocking_state`,
`operator_disposition`, `reopen`, `reopen_reason`, `previous_notification_id`,
`previous_material_generation_id`, `next_review`, `evidence_digest`, `created_at`.

Decision table:

| Condition | Class |
|---|---|
| generation unchanged | `SUPPRESSED` (`unchanged_replay` / `prior_operator_reject_unchanged`) |
| prior REJECT + genuine semantic change (actionable / standing moved / blocking changed) | `IMMEDIATE` with `reopen=True` |
| prior REJECT + no semantic change | `SUPPRESSED` (`post_reject_unchanged_semantically`) |
| material (act_now advisory / actionable standing) | `IMMEDIATE` |
| new blocking-state transition | `IMMEDIATE` (pages once) |
| non-action state changed but not actionable | `DIGEST` |

## Material change policy

### Cash

`HOLD_CASH` with `ACT_NOW=false` is **not** an immediate notification on every
scan. A fresh immediate notification requires: `HOLD_CASH → DEPLOY_CASH` (or
reverse), band entry/exit, `deploy_now` 0→>0, a reserve/funding constraint
materially changing the call, or a true risk transition. Tiny drift while the
call stays `HOLD_CASH` is internal state only.

### Re-entry

If no candidate-specific governed `RE_ENTER` exists, `current_action=WAIT`,
`act_now=false`, READY/NEAR churn alone is not immediate. Immediate only for a
governed transition (WAIT→RE_ENTER, RE_ENTER→blocked, candidate actionability
becomes true, or a prior actionable candidate loses eligibility).

### Concentration / SCHD

If standing view stays `TRIM` but current action stays WAIT/REVALIDATE,
`ACT_NOW=false`, or blocked/stale, do not repeatedly page. A prior `REJECT`
suppresses the unchanged recommendation; it reopens only on a genuine semantic
change and must include `WHAT CHANGED SINCE YOUR REJECT`. A new hash alone is
not a material change.

### Deferred review

A due defer may notify once. It is not re-created every timer cycle; the same
due event repeats only on a new due generation or renewed schedule.

## Delivery classes

- `IMMEDIATE` — operator attention required now (new ACT_NOW, material risk
  transition, new actionable re-entry, material recommendation change, reopen).
- `DIGEST` — cash above band but HOLD_CASH, re-entry lists changed with no
  governed action, standing blocked TRIM unresolved, nonurgent research.
- `COMMAND_CENTER_ONLY` — minor cash drift, READY/NEAR churn, quote refreshes,
  trace metadata, unchanged blocked recommendation, scanner heartbeat.
- `SUPPRESSED` — unchanged replay, prior REJECT unchanged.

Default digest cadence: one morning CIO brief and one end-of-day brief **only if
something meaningful changed**. Never send a digest to say "nothing happened".

## Durable semantic dedupe

`NotificationStateStore` persists per-lineage state in JSONL:

- **index** (`cio_notification_state.jsonl`) — one line per lineage, rewritten
  atomically (`tmp` + `fsync` + `os.replace`), bounded to `MAX_LINEAGES`.
- **audit** (`cio_notification_audit.jsonl`) — append-only history, bounded to
  `MAX_AUDIT_LINES`.
- **metrics** (`cio_notification_metrics.jsonl`) — bounded counters.

Properties: persistent across restarts, shared across scheduler invocations,
atomic, corruption-safe (malformed lines skipped), fail-closed, bounded
retention, traceable suppression reason. This is **not** a six-hour exact-key
cache.

## Universal chokepoint

The scanner's proactive path (`scan_office()`) is the single governed chokepoint:
every candidate passes through `decide_notification()` before delivery; only
`IMMEDIATE` decisions are delivered, using the human renderer. The legacy
`publish_material_decision` / `deliver_decision` / outbox delivery-worker path
remains for the defer-revisit and conversation subsystems; reconciling them onto
this single gate is tracked as the explicit AIF↔CIO integration follow-up
(no parallel competing gates are created in this pass).

## Rollback

Switch the notification gate to prior delivery mode without reverting canonical
decisions:

```bash
# Disable the semantic gate (parity escape hatch) — canonical decisions unchanged
# Pass notification_gate=False to scan_office, or:
export CIO_NOTIFICATION_GATE=0
```

Live → interdict/shadow:

```bash
systemctl --user stop tradeai-cio-material-scan.timer
systemctl --user set-environment CIO_TELEGRAM_INTERDICT=1
```
