# Autonomous Office Initiative — Phase 6

Status:      ACTIVE
as_of:       2026-08-16T23:13:53-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY`. This phase gives Alex (and participating specialists) an
*autonomous advisory office*: a canonical vocabulary for why an agent woke, a
hard boundary for what an agent may do on its own once awake, a notification
policy that suppresses unchanged replays and re-opens only on new evidence, a
durable next-review binding so no recommendation is left hanging, and a
proactive advisory message format that stays honest about what it knows.

> **Boundary.** This is an **advisory** initiative, not trading authority. The
> office may investigate, retrieve, compose, schedule, and notify — it may
> **never** trade, mutate risk policy, alter external documents/calendars, send
> arbitrary email, mutate broker authentication, or promote a rule it "learned".

## Modules

- `scripts/lib/agent_wake_taxonomy.py` — canonical wake triggers + autonomous action policy
- `scripts/lib/agent_followup.py` — durable next review, reopen policy, proactive advisory message

---

## 1. Wake taxonomy

Every agent wake maps to exactly one canonical trigger. `canonicalize_wake_trigger()`
normalizes case, whitespace, underscores, and hyphens, so `position_opened`,
`Position Opened`, and `position-opened` all resolve to `POSITION_OPENED`.
Unrecognized triggers return `None` (never a guessed category).

### Canonical triggers

| Trigger | Meaning |
|---------|---------|
| `POSITION_OPENED` | a new position was opened |
| `POSITION_CLOSED` | a position was closed |
| `POSITION_SIZE_CHANGED_MATERIAL` | a position size changed materially |
| `CASH_BAND_CHANGED` | the cash band moved |
| `CASH_USE_BECAME_ELIGIBLE` | cash became eligible for use |
| `REENTRY_STATE_CHANGED` | re-entry state changed |
| `REENTRY_ELIGIBILITY_CHANGED` | re-entry eligibility changed |
| `RISK_STATE_CHANGED` | the risk state changed |
| `RESEARCH_DECISION_USE_CHANGED` | how research feeds decisions changed |
| `FRESHNESS_CHANGED` | data freshness changed |
| `DEFER_DUE` | a deferred item is due for revisit |
| `FOLLOW_UP_DUE` | a scheduled follow-up is due |
| `OPERATOR_CHALLENGE_OPENED` | the operator opened a challenge |
| `OPERATOR_CHALLENGE_REVIEWABLE` | a challenge is ready for review |
| `OUTCOME_MATURED` | a prior decision's outcome matured |
| `LESSON_CANDIDATE_CREATED` | a learning candidate was created |

### Material vs follow-up

- `is_followup_wake(trigger)` → `True` for `FOLLOW_UP_DUE` and `DEFER_DUE`
  (scheduling wakes).
- `is_material_wake(trigger)` → `True` for any other recognized trigger (a real
  state change worth reasoning about).

---

## 2. Autonomous investigation — allowed vs denied

The office may act autonomously *only* on the read-only side of the boundary.
`allowed_autonomous_action(action)` classifies a request and **fails closed**:
unrecognized actions are denied.

| Allowed | Denied |
|---------|--------|
| load verified truth | trade |
| search internal research | modify risk policy |
| retrieve memory | edit external docs / calendar |
| use read-only MCP tools | send arbitrary email |
| delegate bounded specialist questions | mutate broker auth |
| create / update advisory case | promote learned rules |
| schedule revisit | |
| prepare notification | |

Denial is structural: a denied action is not "delayed" or "routed around", it is
refused. An action that is not on the allowed list is not permitted.

---

## 3. Notification policy — unchanged replay suppression + reject re-open

`reopen_after_reject(previous_disposition, same_identity, same_evidence)` decides
whether a previously-seen recommendation may be re-sent:

1. **`SUPPRESS`** — an unchanged replay of a prior `REJECT` / `ACK` / `DONE`
   (same identity **and** same evidence digest). Re-sending the identical
   recommendation the operator already rejected/acknowledged is noise.
2. **`WHAT CHANGED SINCE YOUR REJECT`** — a prior `REJECT` exists but the
   evidence digest changed. New evidence may reopen a rejection, but only with
   an explicit "what changed" marker — never silently.
3. **`ALLOW`** — otherwise (no prior suppressing disposition, or a new identity).

This mirrors `evaluate_notification()` in
`scripts/lib/agent_notification_intelligence.py`, which tracks `same_identity`
vs `same_decision` + `evidence_changed` and exposes the `reopen` /
`reopen_label` fields.

---

## 4. Durable next review

A material non-action must not dangle. `build_durable_next_review()` requires a
binding for `WAIT`, `REVALIDATE`, `DATA_UNAVAILABLE`, `DEFER`, and `RESEARCH`.

- A bound review carries `kind` in `{TIME, CONDITION, DATA_FRESHNESS, EVENT}`
  plus `due_at`, `condition`, `revisit_id`, and `lineage` as appropriate.
- The only acceptable alternative is an explicit `NEXT_REVIEW_UNAVAILABLE` with a
  `reason`.
- A bare `"NEXT REVIEW"` with no binding raises `ValueError`.

`validate_durable_next_review()` enforces the same contract on any dict:

| Check | Result |
|-------|--------|
| `kind` present | required |
| `TIME` | requires `due_at` |
| `CONDITION` / `DATA_FRESHNESS` / `EVENT` | requires a condition/event descriptor |
| bound kind | requires `revisit_id` **or** `lineage` |
| `NEXT_REVIEW_UNAVAILABLE` | requires `reason` |
| bare dict / unknown kind | rejected |

---

## 5. Proactive advisory message

`compose_advisory_message()` assembles the proactive advisory format:

```
WHAT CHANGED
…

MY CURRENT ACTION
…

WHY
…

MEMORY-PRIOR-OPERATOR-VIEW        (only when decision-relevant)
…

COUNTER-THESIS
…

WHAT CHANGES MY MIND
…

NEXT REVIEW
…
```

The `MEMORY-PRIOR-OPERATOR-VIEW` line is emitted **only** when a
decision-relevant `memory_view` is supplied and non-empty. Memory is never
mentioned merely to sound intelligent; a missing or irrelevant memory is
omitted, not invented.

---

## Authority

`READ_ONLY_ADVISORY`. Zero broker / order / stop / 2FA / risk-policy mutations.
No network, no secrets, no live side effects. The autonomous office advises; it
does not decide for the operator.
