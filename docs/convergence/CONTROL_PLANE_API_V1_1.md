# CONTROL_PLANE_API_V1.1

Additive freeze on CONTROL_PLANE_API_V1_BASELINE (`084674c5`).

| Layer | Status | Commit |
|---|---|---|
| R21_SUMMARY | FROZEN | `084674c5` |
| R21_DETAIL | FROZEN | `c3b105a7` |
| R21_LINEAGE | FROZEN | `c3b105a7` |
| Evidence | recorded | `b5f55339` |

**R21_1_ACCEPTED=true**

Outer envelope keys remain pinned:

`ok`, `as_of`, `source_sha`, `freshness`, `data_quality`, `evidence_class`, `data`

No uncoordinated field changes after this point.

## Detail

- GET `/api/v3/control-plane/agents/{agent_id}`
- GET `/api/v3/control-plane/workflows/{id}`

Cross-ID aliases (same workflow identity):

`workflow_id`, `event_id`, `decision_id`, `generation_id`, `artifact_id`, `notification_id`, `checkpoint_id`, `outcome_id`, `research_id`, `council_id`, `entity_guid`

## Lineage

Nodes/edges are projected from stored traces. Missing endpoints stay `UNRESOLVED_LINK`.
Pass-through certainties: `LEGACY_REFERENCE`, `MISSING_PARENT`, `UNAVAILABLE_STORE`, `QUARANTINED_RECORD`.
`until` / `as_of` hide later nodes. No phantom nodes.
