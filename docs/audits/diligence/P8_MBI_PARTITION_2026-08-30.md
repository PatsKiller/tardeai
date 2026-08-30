# P8 — Outcome / lesson MBI partition

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0 (immutable)  
**MBI_COGNITION:** 1 (research / priority / narrative / eligibility only)  
**Gap:** G-MBI-01  
**Package:** Diligence Phase 8 (master plan § PHASE 8)

## Claim

Lessons and outcome cognition may change **what the desk asks, when it looks,
notify priority, and CC narrative**. They must **never** change size, orders,
stops, broker actions, or `recommended_delta_usd`. Product and instrument
records stamp `memory_behavior_influence = 0`. A CI-oriented suite refuses any
raise of the ceiling.

## Code under audit

| Artifact | Path |
|----------|------|
| InstrumentRecord partition | `scripts/lib/cio_instrument_record.py` (`apply_cognition`, `BEHAVIOR_FIELDS`, `COGNITION_FIELDS`) |
| Operator product stamp | `scripts/lib/cio_operator_product.py` (`MBI = 0`) |
| Situation bridge stamp | `scripts/lib/cio_situation_notify_bridge.py` |
| Baseline unit tests | `tests/test_cio_instrument_record.py` |
| P8 CI suite | `tests/test_cio_diligence_p8_mbi_partition.py` |

## Cognition vs behavior

| Allowed (cognition) | Refused (behavior) |
|---------------------|--------------------|
| `next_research_question` | `recommended_delta_usd` |
| `next_eligible_at` | `size_usd` / `shares` / `qty` |
| `notify_priority` | `order` / `trade` / `execution` |
| `cc_narrative` | `stop` / `limit` / `target_weight_pct` |

Lessons attach as `support_only=True`, `applied_to=cognition`. A write that
moves none of the cognition fields is a **failed persist** (`CognitionNoOp`),
not a silent success.

## G-MBI-01 closure path

| Check | How |
|-------|-----|
| Stamp on mint | `new_record(...)["memory_behavior_influence"] == 0` |
| Stamp on product module | `MBI = 0` + `"memory_behavior_influence": MBI` |
| Reject behavior kwargs | `BehaviorWriteRefused` for every `BEHAVIOR_FIELDS` entry |
| AST hardcode | `MBI_BEHAVIOR` constant parses to `0` |
| Grep gate | stamp modules must not assign MBI / influence to `[1-9]…` |

Status after this package: **CI gate landed** (suite enforceable on every PR).
Operational “never rises in live env” remains a standing control on the
scoreboard rails row.

## Rails

No notify-on. No Telegram producer. No broker write. Lessons do not size.

## Exit gate

**PASS** when `tests/test_cio_diligence_p8_mbi_partition.py` is green alongside
`tests/test_cio_instrument_record.py` MBI section.
