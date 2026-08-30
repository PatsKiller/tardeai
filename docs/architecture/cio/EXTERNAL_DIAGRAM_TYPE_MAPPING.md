# External Diagram Type Mapping

**Status:** REFERENCE  
**Date:** 2026-08-27 (Wave 3 appendix 2026-08-30, P1-WS1)  
**Context:** docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md (audit finding L7); diligence P1-WS1 as-built

## Why this exists

The 2026-08-27 platform audit was scoped against a diagram supplied by the
operator describing an end-to-end pipeline (event → canonical entity →
materiality → graph impact → research gap → specialist dispatcher →
`SpecialistArtifact@v2` → `CIOCouncilSynthesis@v1` → `CIOOperatorProduct@v1`
→ notification policy → delivery receipt → `OutcomeCheckpoint@v1` → outcome
→ lesson/hypothesis, indexed by a `CanonicalStoreRegistry@v1`).

No file in this repo formally scoped that diagram end-to-end before the
audit — it reads as an external/aspirational reference, not a superseded
internal spec. But its vocabulary converges with real, merged, wired
implementation work more than a first-pass grep suggested (a repo-wide
search for the literal type names returned mostly zero hits at first look,
which undersold how much already exists under different code paths). This
doc is the permanent record of that mapping, so a future reader doesn't
have to re-derive it from the audit.

## Mapping (2026-08-27 baseline)

| Diagram type | Code equivalent | Status |
|---|---|---|
| `CanonicalStoreRegistry@v1` | `scripts/lib/canonical_store_registry.py` (`SCHEMA = "CanonicalStoreRegistry@v1"`) | **Exact literal match.** Registry live on pin `852ecd47` (34 stores). Hub M10 closed 2026-08-27. |
| `CIOOperatorProduct@v1` | `scripts/lib/cio_operator_product.py` (`SCHEMA = "CIOOperatorProduct@v1"`) | **Exact literal match.** Registry-backed (`cio.operator_product.current` / `.history`), consumed by command center / delivery paths. |
| `OutcomeCheckpoint@v1` | `scripts/lib/cio_lineage.py` (`CHECKPOINT_SCHEMA = "OutcomeCheckpoint@v1"`), also registered as `cio.checkpoints` (`scripts/lib/r17_checkpoint_binding.py` writer) | **Exact literal match.** Store `outcome_checkpoints.jsonl` live. |
| `CIOCouncilSynthesis@v1` | See **Wave 3 appendix** below. Historically mapped only to `InvestmentDecision@v1` (`cio_investment_decision.py` / `cio_committee_synthesis.py`). | **Superseded in part** by literal Wave 3B module; InvestmentDecision remains the committee envelope. |
| `SpecialistArtifact@v2` | Informal handoff advisories via `scripts/lib/cio_specialist_artifacts.py` (plural); live jsonl rows still stamped `SpecialistArtifact@v2` under `data/cio/specialist_artifacts.jsonl` | **Still present** as parallel informal store. Prefer Wave 3 `SpecialistArtifact@v1-lite` for new joins (appendix). |

## Wave 3 appendix (P1-WS1, 2026-08-30)

Measured on CURRENT pin `852ecd47` / persistent-state. Code-derived; not a claim that every wake uses these types.

| Diagram / program type | Code equivalent | Live bind (as-built) |
|---|---|---|
| `InstrumentRecord@v1` | `scripts/lib/cio_instrument_record.py` (`SCHEMA = "InstrumentRecord@v1"`); registry `cio.instrument_records` → `data/cio/cio_instrument_records.jsonl` | **Exact literal.** **129** rows (HELD 54 / EXIT 72 / SLEEVE 3). Consumers include residual web, research budget, rehydrate, command center, preconditions board. **Not** yet the sole authoritative wake load for every surface (gap G-IR-01). MBI_BEHAVIOR=0 / MBI_COGNITION=1 enforced in `apply_cognition`. |
| `SpecialistArtifact@v1-lite` | `scripts/lib/cio_specialist_artifact.py` (`SPECIALIST_ARTIFACT_SCHEMA = "SpecialistArtifact@v1-lite"`); registry `cio.specialist_artifacts` | **Exact literal.** Schema+validator+jsonl append; **no vendor HTTP** in-module. Live store **2** rows (both `grok_critique`, `workflow_id=None`) — thin. Distinct from plural `cio_specialist_artifacts.py` (handoff reconstruction) and from legacy `SpecialistArtifact@v2` jsonl (**36** rows). |
| `CIOCouncilSynthesis@v1` | `scripts/lib/cio_council_synthesis.py` (`COUNCIL_SCHEMA = "CIOCouncilSynthesis@v1"`) — deterministic join, **no model**, states AGREED / DISPUTED / SINGLE_SOURCE / NO_VALID_ARTIFACTS | **Exact literal (Wave 3B).** Library ready for product T/D/A lines. On-disk `data/cio/cio_council_synthesis.json` also carries schema literal `CIOCouncilSynthesis@v1` but an **older committee-shaped** payload (no Wave3B `state`; mtime 2026-08-26) — treat as shape drift, not proof the Wave3B join is the live writer. `InvestmentDecision@v1` remains the separate committee decision envelope; registry `cio.decisions` **missing** on disk. |

### Related Wave 3 / diagram neighbours (short)

| Type | Module | Note |
|---|---|---|
| `ResearchNeedDecision@v2` | `cio_research_gate.py` | Free-first → residual → critique ladder |
| `ResidualWebLane@v1` | `cio_residual_web.py` | Executes residual rung; stub default |
| `NotificationPolicy@v1` | `cio_notification_policy.py` | IMMEDIATE / DIGEST / COMMAND_CENTER_ONLY / SUPPRESSED |
| `CanonicalEventIdentity@v1` | `cio_canonical_identity.py` | Diagram IDENTITY node; event_id join |
| `CIOGraphImpact@v1` | `cio_graph_impact.py` | 1-hop neighbours; not universal stage |

As-built stage narrative: `docs/audits/diligence/P1_WS1_AS_BUILT_ARCHITECTURE_2026-08-30.md`.

## What this doc is not

This is a naming cross-reference, not an architecture decision. It does not
obligate deleting `SpecialistArtifact@v2` rows, renaming `InvestmentDecision@v1`,
or asserting universal InstrumentRecord wake loads. See
`docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md` and the diligence gap
register for open work.

## Related

- [ADR_DURABLE_STATE_EVENT_SOURCING.md](./ADR_DURABLE_STATE_EVENT_SOURCING.md) — the event-sourcing decision `CanonicalStoreRegistry@v1` sits alongside
- `docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md` — full audit, findings C4/L7
- `docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md` — remediation plan, M10
- `docs/audits/CIO_PIPELINE_DIAGRAM_VERIFICATION_2026-08-27.md` — flow completion measure
- `docs/audits/diligence/P1_WS1_AS_BUILT_ARCHITECTURE_2026-08-30.md` — stage-by-stage as-built
