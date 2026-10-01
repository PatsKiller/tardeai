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

The surface reports last run, artifact, retrieval, review, and score evidence
only when the read contract supplies it. Natural wake, research action, memory
retrieval, and CIO-decision contribution remain `UNKNOWN` when the current
read contract does not expose those receipts. No zero is invented for an
unavailable producer.

## Read routes

The frontend consumes the GET-only `agent-runtime-command-center-read-api-v1`
routes for runs, artifacts, retrieval evidence, reviews, scores, lessons, and
cases. Non-GET requests are rejected by the backend surface.
