# CIO Agent Runtime Operator Surface

## Authority

`/v3/agents` is a read-only monitoring and maturity view. It has no broker,
order, stop, risk-limit, provider-call, service-control, schedule-change, or
promotion authority. The Control Plane remains the engineering/diagnostic view;
this page is the operator-facing runtime view.

## Runtime state

The banner is sourced from the read-only agent-runtime adapter and uses the
operator vocabulary `LIVE`, `SHADOW`, `FIXTURE`, `UNAVAILABLE`, and `STALE`.
`NOT_CONNECTED` is retained as an adapter diagnostic but is rendered as
`UNAVAILABLE`, never as a proven runtime capability.

Declared catalog posture and runtime-proven evidence are shown in separate
bands. A fixture, preview, missing adapter, or stale read cannot be promoted to
live by the frontend.

## Evidence limits

The surface reports last run, artifact, retrieval, review and score evidence
only when the read contract supplies it. Four proof rows come from
`GET /api/v3/agents/runtime-proof` (`AgentRuntimeProof@v1`, served by
`scripts/api_v3_hermes.py` and `scripts/lib/cio_cross_surface_links.py`). It
reads the production evidence stores through bounded tail windows:

| Row | Source | Attribution |
|---|---|---|
| Last natural wake | `agent_run_traces.jsonl` (completed, non-manual trigger) | `agent` field |
| Last research action | `hermes_research_results.jsonl` | `provenance.agent` |
| Memory retrieval | `aif_memory_retrievals.jsonl` | **none**: rows carry no agent, so this row stays `NOT_EXPOSED` for every agent and shows the unattributed fleet time |
| Decisions contributed to | `agent_run_traces.jsonl` `decision.decision_id`; for Hermes, CIO decisions that recorded consuming its results | `agent` / result consumption |

Each row is rendered as one of four states:

- `RUNTIME`: a store row attributes the proof to this agent.
- `NOT_RECORDED`: the store attributes rows to agents, but none to this one.
- `NOT_EXPOSED`: no store attributes this proof to an agent.
- `UNKNOWN`: the proof read failed. The adapter fails closed to
  `NOT EXPOSED BY READ CONTRACT`.

As of 2026-10-02:

- `alex` exposes last natural wake and decisions contributed.
- `hermes` exposes last research action and decisions contributed.
- All other catalog agents are `NOT_RECORDED` for those rows.
- Memory retrieval is `NOT_EXPOSED` for every agent.

No zero is invented for an unavailable producer. Declared catalog posture
stays in its own band, separate from these rows.

## Read routes

The frontend consumes the GET-only `agent-runtime-command-center-read-api-v1`
routes for runs, artifacts, retrieval evidence, reviews, scores, lessons, and
cases. Non-GET requests are rejected by the backend surface.
