# CIO DecisionPayload@v1 — Phase 1 (2026-08-21)

Status:      HISTORICAL
as_of:       2026-08-21T11:34:32-04:00
Measured at: efcc51365 / not measured

**READ_ONLY_ADVISORY.** Flag-gated capture only — does not change decisions.

## Flag

`AGENT_DECISION_PAYLOAD` (default **0**)

- OFF → no append (parity with `b04f0016` behavior)
- ON → one completed `AgentRunTrace@v1` per decision with `decision` = `DecisionPayload@v1`

Does **not** flip `MEMORY_BEHAVIOR_INFLUENCE`.

## Emit surfaces (fail-soft)

| Surface | Hook |
|---------|------|
| material_scan | `cio_material_scan._instrument_scan` → `emit_payloads_for_decisions` |
| product_notify / IIC | `cio_product_reassessment._enqueue_material_product_outbox` |
| freeform | `answer_freeform_with_flash` success path |

## Schema

See `scripts/lib/agent_decision_payload.py` (`DecisionPayload@v1`).

Origins: `DETERMINISTIC_RANK` | `FRESH_RESEARCH` | `MEMORY_INFLUENCED` | `OPERATOR_ASK` | `SYNTHESIZED`
(`SYNTHESIZED` must never count toward AIF-28 promotion arithmetic.)

## Enable (after promote)

```bash
# drop-in example — do not set until ready to measure
Environment=AGENT_DECISION_PAYLOAD=1
```

## Acceptance (later)

- Payload coverage ≥ 99% of material wakes over 5 sessions (with flag ON)
- Zero secrets in payloads
- Flag OFF ⇒ no new trace rows from this path

## Tests

`tests/test_agent_decision_payload.py`, flag defaults in `test_agent_feature_flags.py`
