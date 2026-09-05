# Command Center — Agent Memory view (proposal)

Status: DRAFT
as_of: 2026-09-05T15:37:00Z
Measured at: not measured

## Scope

This is a **proposal only**. No frontend code is changed. It specifies a new
Command Center view — the **Agent Memory view** — that answers one question
per recommendation: *which agent consumed which artifact, and what did it
produce?*

The backing data already exists in `scripts/lib/comms/agent_contracts.py`
(`AgentConsumptionReceipt@v1`). This proposal describes the read surface; it
does not build it, and it changes no runtime path.

## What the view shows

For each agent (`cio`, `advisory`, `hermes`, and future agents via
`allow_unknown`), one row per consumption receipt:

| field | source | provenance class |
|---|---|---|
| agent | `receipt.agent_id` | `D` (deterministic) |
| agent version | `receipt.agent_version` | `D` |
| consumed event / thread / artifacts | `receipt.event_id`, `receipt.thread_id`, `receipt.artifact_ids` | `D` |
| purpose | `receipt.purpose` | `D` |
| policy decision | `receipt.policy_decision` | `D` |
| retrieved at | `receipt.retrieved_at` | `D` |
| derived artifacts produced | `receipt.derived_artifact_ids` | `D` |
| influence declaration | `receipt.influence_declaration` | `A` (agent-originated) |
| influencing events | `receipt.influence_event_ids` | `D` |

This gives CIO / Advisory / Hermes a concrete, per-recommendation trace of
**which communications informed a recommendation** — the M4 consistency and
M3 feedback evidence the maturity bar (§15) demands, without a hand-written
lineage note.

## Knowledge-status gate rendered, never flattened

The view must render provenance honestly (§9.5, §13.4). A consumed event that
is a **Hermes hypothesis** (`knowledge_status = none`, eligibility `eligible`)
is shown as *hypothesis*, **not** as verified fact. Only an event the
Librarian has gated to `knowledge_status = ACCEPTED` renders as *verified
fact*. This is the same rule the backend already enforces via
`assert_no_truth_claim_without_knowledge_gate` / `event_is_verified_fact` —
the view is the read-side projection of that gate, so a hypothesis is never
presented as truth on screen.

## Data sources

- Subscriptions: `register_subscription` / `list_subscriptions` (the read API
  `eligible_events_for_agent` returns only policy-eligible events — expired and
  unauthorized content excluded).
- Receipts: `get_consumption_receipt` (per receipt) — no aggregate listing
  endpoint exists yet; the view would need a new read-only
  `list_consumption_receipts(agent_id)` or equivalent, **proposed here, not
  built**.

## Explicitly out of scope

- No broker, order, stop, sizing, or behavior fields — `MBI_BEHAVIOR = 0` is
  unaffected; this is a provenance read, not an action surface.
- No new `@v1` type or store: `AgentConsumptionReceipt@v1` already exists.
- No frontend business logic for runtime, materiality, notification, or
  maturity decisions — this view only *displays* the receipt rows.

## Open questions for the operator

- Whether a read-only `list_consumption_receipts(agent_id)` aggregate should be
  added to `agent_contracts.py` (new backend API surface — see §13.7 "who
  consumes it").
- Whether the view is read-only by default or gated behind a role (§2B); the
  proposal assumes **read-only by default**, consistent with §13.
