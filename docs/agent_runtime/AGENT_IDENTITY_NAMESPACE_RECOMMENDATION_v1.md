# Agent Identity Namespace Recommendation v1

Status:      ACTIVE
as_of:       2026-07-30T11:19:37-04:00
Measured at: efcc51365 / not measured

Broad renames are out of scope for this tranche.

Recommendation: use subsystem-qualified stable IDs for new storage and APIs while preserving current IDs as aliases until a separate migration is approved.

Proposed namespace shape:

- `agent_runtime:sentinel`
- `agent_runtime:darwin`
- `agent_runtime:iris`
- `agent_runtime:reflection`
- `proposal_review:maria`
- `proposal_review:risk_agent`
- `proposal_review:steph`
- `hermes:hermes`
- `openclaw:concierge`
- `defense:defense_adjudication`
- `broker_oversight:broker_cloud_oversight`

## Collision Risks

| current ID | display name | subsystem | runtime owner | authority | storage/API/UI references | collision risk | recommended future ID | migration impact |
|---|---|---|---|---|---|---|---|---|
| `maria` | Maria | Agent Runtime / proposal review | repository | no financial authority | `config/agent_maturity_catalog.json`, `scripts/proposal_agent_review.py`, `apps/command-center-v3/src/pages/AgentRuntimeHub.tsx` | live proposal-review name overlaps Lane D designed agent identity | `proposal_review:maria` and `agent_runtime:maria` aliases | add aliases before table rewrite |
| `risk_agent` | Guardian Risk / Risk | Agent Runtime / proposal review / broker oversight | repository | no financial authority | `scripts/proposal_agent_review.py`, `scripts/broker_promote_oversight.py`, Agent Runtime catalog | display-name mismatch can hide whether Risk means reviewer seat or Lane D agent | `proposal_review:risk_agent` and `agent_runtime:risk_agent` | requires API/UI alias mapping |
| `steph` | Steph | Agent Runtime / proposal review | repository | no financial authority | `scripts/proposal_agent_review.py`, `scripts/broker_promote_oversight.py` | reviewer seat and Lane D designed portfolio agent share ID/display name | `proposal_review:steph` and `agent_runtime:steph` | requires storage alias migration |
| `concierge` | Concierge | OpenClaw / Agent Runtime | repository plus operator runtime metadata | no financial authority | `config/agent_maturity_catalog.json`, `config/agent_runtime_mvl.json`, OpenClaw runtime inventory | OpenClaw persona and designed Agent Runtime interface can be confused | `openclaw:concierge` and `agent_runtime:concierge` | operator inventory should declare namespace |
| `hermes` | Hermes | Hermes / Agent Runtime catalog | repository | no financial authority | Hermes configs, Agent Runtime catalog | Hermes maturity-v2 is not Agent Runtime MVL; score comparison risk | `hermes:hermes` | keep framework field mandatory |

## Future Migration Plan

1. Add alias tables or config entries without changing current IDs.
2. Make storage writers emit subsystem-qualified IDs while readers accept legacy IDs.
3. Backfill only after an approved dry-run report identifies exact row counts and conflicts.
4. Remove legacy aliases only after UI/API consumers prove compatibility.

No production agent was renamed by this task.
