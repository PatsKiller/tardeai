# ADR-008 — One Global Intelligence Record with one envelope and one key discipline

Status: PROPOSED (package `cognitive_transformation_20260927`, 2026-09-27) · extends 09-27 §11 (Company Intelligence Record) and v3.3 §18; supersedes nothing.
Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.

## Context
The 09-27 design composes a company record keyed by `security_guid`. Decisions (71,847 rows), agents and their calibration, lessons, risks, operational state and market events stay outside it, under four key namespaces and their own APIs `[DOC-CLAIM: 09-27 §2–§6]`.

## Decision
1. Eight intelligence classes — Company, Research, Decision, Agent, Operational, Lessons, Risk, Market — share one `IntelligenceEnvelope@v1` with eight fields: memory, history, contradictions, confidence, lineage, ownership, freshness, dependencies. `UNKNOWN` is a legal value and is counted.
2. Registry GUIDs are the only company keys; other entities get UUIDv5 keys in explicit namespaces (`DEC:`, `AGENT:`, `LANE:`, `LESSON:`, `RISK:`, `EVENT:`, `MACRO:` …). `HELD:` and friends become views of `SEC:`.
3. Storage is one new schema `intelligence` on production Postgres (entity, envelope, edge, research index, embedding, supervisor, approvals), **projected** from the canonical stores by the M2-projector pattern with idempotency keys. Canonical stores keep their single writers; the projection has zero authority.
4. Read through the façade (`get_intelligence`, `what_changed`, `find`, `contradictions`, `lineage`); write through one door per class.

## Consequences
- The 09-27 CIR becomes the Company class of the GIR; nothing built for it is wasted.
- Bitemporal history requires M2 on production (an infra/security approval); until then the projection reads the shadow.
- Freshness and confidence policies per class are explicit and machine-checked; the 30-day thesis SLA is generalised.

## Rejected alternatives
- Per-domain records (company, decision log, lessons KB) that share a host but not an envelope.
- A graph database or document store (a new silo; Postgres suffices — ADR on the graph in package 07).
