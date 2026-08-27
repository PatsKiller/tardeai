# External Diagram Type Mapping

**Status:** REFERENCE
**Date:** 2026-08-27
**Context:** docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md (audit finding L7)

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

## Mapping

| Diagram type | Code equivalent | Status |
|---|---|---|
| `CanonicalStoreRegistry@v1` | `scripts/lib/canonical_store_registry.py` (`SCHEMA = "CanonicalStoreRegistry@v1"`) | **Exact literal match.** Wired into 11 consumers incl. `api_v3_cio.py`. Exists on `origin/main`; confirm it's present on whatever checkout you're reading before trusting it — it was missing from the live hub as of this writing (see `docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md`, M10/M1). |
| `CIOOperatorProduct@v1` | `scripts/lib/cio_operator_product.py` (`SCHEMA = "CIOOperatorProduct@v1"`) | **Exact literal match.** Registry-backed (`cio.operator_product.current` / `.history` stores), consumed by `aegis`, `telegram`, `command_center`. |
| `OutcomeCheckpoint@v1` | `scripts/lib/cio_lineage.py` (`CHECKPOINT_SCHEMA = "OutcomeCheckpoint@v1"`), also registered as `cio.checkpoints` (`scripts/lib/r17_checkpoint_binding.py` writer) | **Exact literal match.** Added 2026-08-26. |
| `CIOCouncilSynthesis@v1` | `InvestmentDecision@v1` (`scripts/lib/cio_investment_decision.py`), produced via `scripts/lib/cio_committee_synthesis.py` | **Renamed-equivalent.** Same role (specialist advisories → committee vote → canonical decision envelope), different name. Not registry-backed as of this writing. |
| `SpecialistArtifact@v2` | Informal `SpecialistAdvisory`-shaped dict convention (`scripts/lib/cio_specialist_artifacts.py` reconstructs these from completed handoffs) | **Partially implemented.** No formal versioned dataclass/schema exists under this name; `cio_lineage.py`'s lineage projection does track a `specialist_artifact_ids` list and a `SPECIALIST_ARTIFACT` node type, but only within the Hermes lineage sub-flow. |

## What this doc is not

This is a naming cross-reference, not an architecture decision. It doesn't
obligate anyone to rename `InvestmentDecision@v1` to `CIOCouncilSynthesis@v1`
or to formalize `SpecialistArtifact@v2` as a real type — those remain open
questions for whoever owns this area next, not settled by this doc. See
`docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md` for the audit's
remediation framing.

## Related

- [ADR_DURABLE_STATE_EVENT_SOURCING.md](./ADR_DURABLE_STATE_EVENT_SOURCING.md) — the event-sourcing decision `CanonicalStoreRegistry@v1` sits alongside
- `docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md` — full audit, findings C4/L7
- `docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md` — remediation plan, M10
