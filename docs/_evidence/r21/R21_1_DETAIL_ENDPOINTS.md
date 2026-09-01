# R21.1 Detail Endpoints

Status:      ACTIVE
as_of:       2026-08-26T12:48:44-04:00
Measured at: efcc51365 / not measured

Implemented additively on R21 baseline `084674c5`.

- `GET /api/v3/control-plane/agents/{agent_id}` returns registered detail, runtime state, bounded recent artifacts, routes, provenance and explicit unknown/unavailable status.
- `GET /api/v3/control-plane/workflows/{id}` resolves workflow, decision, generation, event, artifact, notification, checkpoint and outcome identifiers when present in canonical trace rows.
- `until`/`as_of` query filters provide timestamp-safe bounded historical projection.
- Missing parents and legacy links are retained as `UNRESOLVED_LINK`; no phantom nodes are created.

Evidence class: `UNIT` (fixture-backed). This is not live deployment proof.
