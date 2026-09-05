# Communications Gateway — Test Plan (Phase 11)

**Status:** Communications Gateway program documentation (Phases 0–11).
**Date:** 2026-09-05

**Scope:** Unit / integration / e2e / chaos / security / retention / agent matrix  
**Gateway modes:** `OFF` (default) · `SHADOW` · `CANARY` · `ACTIVE` via `COMMS_GATEWAY_MODE`  
**Constraint:** Production remains **OFF**. This plan maps coverage; it does not authorize ACTIVE.

---

## Matrix overview

| Layer | Goal | Primary suites | Mode under test |
|---|---|---|---|
| Unit | Contract + fail-closed gates | `tests/test_comms_*.py` | OFF (default) + mode helpers |
| Integration | Memory ledger + portal API | `tests/test_communications_portal.py`, delivery/subject suites | OFF / SHADOW stubs |
| E2E (planned) | Producer → ledger → delivery stub → portal | Portal + publish path; live DB optional | SHADOW only until canary |
| Chaos | Idempotency / duplicate / transition abuse | Delivery ledger + communication_event tests | OFF memory |
| Security | No provider import / no self-certify / protected facts | Portal, agent_contracts, curation | OFF |
| Retention | Classify / hold / dry-run expiry / no auto-promote | `tests/test_comms_librarian.py` | OFF |
| Agent | Subscriptions / receipts / influence | `tests/test_comms_agent_contracts.py` | OFF |
| SHADOW compare | Legacy vs gateway decision parity | `tests/test_comms_shadow_compare.py` | SHADOW evidence helper |

---

## Unit — mapped to existing tests

| Capability | Tests | Notes |
|---|---|---|
| Identity / idempotency / fail-closed publish | `tests/test_comms_communication_event.py` | `delivery_owned` always False in Phase 1 client |
| Mode default OFF | `test_gateway_mode_defaults_off` | Unset env → OFF |
| Enforcement gate | `tests/test_comms_enforcement_gate.py` | `require_event_id`; OFF/SHADOW may not own delivery |
| ChannelDelivery@v1 | `tests/test_comms_delivery_ledger.py` | RESERVED stubs; settle transitions; no provider I/O |
| Subject memory | `tests/test_comms_subject_memory.py` | `subject_key_for`, attach, retrieve |
| Curation + protected facts | `tests/test_comms_curation.py` | Deterministic fallback on fact mutation |
| Librarian retention | `tests/test_comms_librarian.py` | Dry-run expiry; no auto knowledge accept |
| Agent consumption | `tests/test_comms_agent_contracts.py` | Rejects self-certifying truth |
| SHADOW compare helper | `tests/test_comms_shadow_compare.py` | subject_key / severity / route_intent |

**Command (unit packet):** see `docs/testing/unit-results.md`.

---

## Integration

| Scenario | Coverage today | Gap / next |
|---|---|---|
| Publish → memory event listable via portal | `test_communications_portal.py` | DB-backed integration when migration applied on lab |
| Publish outbound → auto RESERVED delivery stubs | `test_comms_delivery_ledger.py` | Provider settlement ownership deferred (CANARY+) |
| Subject filter on portal | `test_list_events_subject_filter` | CC deploy attestation still open |
| Health reports delivery_not_owned | `test_health_empty_ledger_delivery_not_owned` | Keep invariant until ACTIVE evidence |

---

## E2E (concrete plan; results await runs)

1. Lab DSN with communication_* migrations applied.  
2. Set `COMMS_GATEWAY_MODE=SHADOW` (never ACTIVE in e2e until activation checklist).  
3. Drive one Telegram-class producer through adapter → `publish_communication`.  
4. Assert ledger row + RESERVED delivery stub; assert legacy path still sends (SHADOW does not own egress).  
5. Run `compare_legacy_vs_gateway` / `record_shadow_observation` and archive `shadow_report()`.  
6. Paste evidence into `docs/deployment/canary-results.md` only after CANARY starts (not before).

---

## Chaos

| Fault | Expected | Suite |
|---|---|---|
| Duplicate publish same idempotency_key | Duplicate acknowledged; no second logical event | `test_publish_idempotent_duplicate` |
| Illegal delivery status jump | Fail closed | `test_status_transitions` |
| Missing event_id on reserve | `DeliveryGateError` | `test_fail_closed_without_event_id` |
| Empty / invalid `COMMS_GATEWAY_MODE` | Resolve OFF | mode unit coverage |

Planned additions (not blocking Phase 11 docs): concurrent reserve races; clock skew on expiry pass.

---

## Security

| Control | Test / check |
|---|---|
| Portal must not import provider SDKs | `test_portal_never_imports_providers` |
| Approval / protection require protected_facts | `test_fail_closed_approval_requires_protected_facts` |
| LLM curation cannot mutate protected facts | curation fallback tests |
| Agents cannot self-certify truth | `test_self_certification_rejected_on_emit` |
| Chokepoint ratchets (Telegram / providers) | `tests/test_telegram_chokepoint_ratchet.py`, `tests/test_provider_chokepoint_ratchet.py` |

Telegram zero-bypass remains Phase 9 debt — security gate for ACTIVE, not for SHADOW docs.

---

## Retention

| Case | Suite |
|---|---|
| Class TTLs (ops_7d, operational_30d, research_365d, approval) | `test_comms_librarian.py` |
| Legal hold blocks delete | `test_legal_hold_forces_hold_and_blocks_delete` |
| Expiry pass dry_run default | `test_expiry_pass_dry_run_default_no_tombstone` |
| Knowledge candidate never auto-accepted | `test_knowledge_candidate_no_auto_accept` |

---

## Agent matrix

| Agent / role | Contract surface | Test |
|---|---|---|
| Known agents set | `KNOWN_AGENTS` | `test_known_agents_set` |
| Subscription filter | `register_subscription` / `eligible_events_for_agent` | subscribe + filter tests |
| Consumption receipt + ack | `emit_consumption_receipt` / `acknowledge_consumption` | receipt tests |
| Influence declaration | `declare_influence` | `test_influence_declaration` |
| Unknown agent | rejected by default | `test_unknown_agent_rejected_by_default` |

Producer wiring of subscriptions is still adoption work (BUILT_DARK).

---

## Exit criteria for later ACTIVE (tests only)

- All rows above green in CI.  
- SHADOW compare match rate acceptable for canary message classes (record in canary-results).  
- Telegram chokepoint baseline empty (Phase 9).  
- Production activation checklist (`docs/deployment/production-activation.md`) still all unchecked until operator sign-off.