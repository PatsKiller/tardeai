# AEC parallel agents and memory spines

```
Status: ACTIVE
as_of: 2026-09-19T13:20:00-04:00
Authority: operator license 2026-09-19 (parallel agents + memory granted)
Amended by: docs/architecture/cognitive_transformation_20260927/01_MEMORY_ENFORCEMENT_LAYER.md (2026-09-27, PROPOSED) — the four spines are read through the façade; the "not yet built" items are Waves 1–3 there
See: config/aec_agent_mesh.json, scripts/lib/aec_agent_bus.py, scripts/lib/aec_memory_spines.py
```

## Design

Three agents share **one** bus (`AecAgentBusEvent@v1`) and four memory spines. They do not fork InstrumentRecord; Advisor/Learning link `subject_key` into existing cognition fields.

MBI_BEHAVIOR=0 enforced in bus.publish and memory.append_fact (behavior field names raise).

## Cycle entrypoint

`scripts/aec_command_center_cycle.py` — production consumer (satisfies identity/memory wiring guard for `aec_memory_spines`). Default dry-run; `--apply` appends advisory-only state.

## Not yet

- Narrator → `telegram_transport` (waits #1082 stance + allowlisted brief)
- Scheduled wake loads spines before decide
- AgentView / AGENT_COMMITMENT producers
- Relationship spine populated from granted sources only
