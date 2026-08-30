# P5 — Specialist agent validation (N=100 sample)

**As-of:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY · `MBI_BEHAVIOR=0`  
**Rails:** no new LLM spend · sample from live/overlay **or fixtures** · no promote  

**Evidence:**  
- `docs/audits/diligence/P5_SPECIALIST_SAMPLE_EVIDENCE_2026-08-30.json` (summary)  
- `docs/audits/diligence/P5_SPECIALIST_SAMPLE_EVIDENCE_2026-08-30_full.json` (per-row)  
**Audit:** `python3 scripts/cio_specialist_sample_audit.py --root <overlay> --limit 100 --json`  

Schema under test: `SpecialistArtifact@v1-lite` (`scripts/lib/cio_specialist_artifact.py`).  
Gap: **G-SPEC-01** (updated in `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md`).

---

## Exit gate (master plan)

> Sample of **100** SpecialistArtifact outputs scored; zero orphan artifacts in sample; same `workflow_id` / same InstrumentRecord in all sampled dispatches.

| Gate clause | Measured | Verdict |
|-------------|----------|---------|
| N=100 sample | **100** (2 live + 98 hermes→fixture projections) | Met (with honesty on source mix) |
| Zero orphans | workflow orphans **50/100 (50%)**; instrument orphans **36/100 (36%)** | **FAIL** — exit gate not met |
| Same `workflow_id` for sampled dispatch | **50/100 (50%)** same-bind (stamped **or** single lineage recovery) | **FAIL** vs “all” |
| Same InstrumentRecord | **64/100 (64%)** exactly one subject via plan/symbol | **FAIL** vs “all” |
| Scorecard axes | consistency **100% PASS**; traceability **100% PASS**; accuracy/relevance **DATA_UNAVAILABLE** | Honest partial |

---

## Sample composition

| Source | N | Notes |
|--------|--:|-------|
| Live overlay `data/cio/cio_specialist_artifacts.jsonl` | **2** | Both `provider=grok_critique`; `workflow_id` **null** on row; `plan_id`+`research_id` present (SPCX / `res_557cfaab8c34`) |
| Fixture projection from `hermes_research_results.jsonl` | **98** | SpecialistArtifact-*shaped* rows labeled `fixture_projection_hermes_result`; **no new model calls**; used only for bind/orphan structural rates |

Live store is real but tiny — Wave 3B writer is used by tests/join; production critique path wrote the two SPCX rows (see Wave 3D HOP notes). Claiming “100 live SpecialistArtifact rows” would be false.

---

## Bind rates (structural)

Join rules used by the audit (read-only):

1. **Workflow:** `artifact.workflow_id` if stamped; else lineage `node_id == research_id` → unique `workflow_id`.  
2. **InstrumentRecord:** `plan_id` → plans projection symbols (else hermes `symbol`) → IR `subject_key` / symbols map. Exactly one subject = same-record bind.

| Metric | Count | Rate |
|--------|------:|-----:|
| Same workflow bind | 50 | **50.0%** |
| Same InstrumentRecord bind | 64 | **64.0%** |
| Orphan workflow (no stamp + no recoverable wf) | 50 | **50.0%** |
| Orphan instrument (no IR subject) | 36 | **36.0%** |

### Live-only (n=2)

| artifact_id | workflow stamped | workflow recovered | IR bind |
|-------------|------------------|--------------------|---------|
| `crit_spcx_res_557cfaab8c34` | null | `wf_e374cc02293301e1396f` | via plan/symbol when present |
| `crit_grok_spcx_res_557cfaab8c34` | null | same | same |

**Finding:** contract allows `workflow_id=None` on `build()`; live writers are not stamping it. Same-workflow is **recoverable** via lineage for these two, but the SpecialistArtifact row itself is not the SoT. InstrumentRecord tips show **`last_artifact_id` unused (0/129)** on the overlay census — cognition pointer not wired from specialist append.

---

## Scorecard

| Axis | Result | Method |
|------|--------|--------|
| **Accuracy** | **DATA_UNAVAILABLE** | Requires human or authorized LLM rubric against ground truth; package forbids new LLM spend |
| **Relevance** | **DATA_UNAVAILABLE** | Same |
| **Consistency** | **PASS 100/100** | Schema validate: provider/outcome enums, `financial_action=false`, stub cost rules |
| **Traceability** | **PASS 100/100** | `research_id` and/or `plan_id` present on every sampled row (structural) |

Agents named in the master plan (research · seasonality · sector · earnings · macro · cash-regime) are **not** distinct `provider` values on `SpecialistArtifact@v1-lite` today — providers are `stub|flash|pro|openai|grok_critique|edgar`. Multi-agent coverage is therefore **DATA_UNAVAILABLE** at the artifact schema layer (plural `cio_specialist_artifacts.py` handoff extractor is a different surface).

---

## G-SPEC-01 update

| Field | Value |
|-------|-------|
| ID | G-SPEC-01 |
| Sev | **2** (unchanged) |
| Prior | Specialist→same record not proven at N=100 |
| Now | Sample **run**; exit gate **not** met. Live n=2; stamp rate workflow_id **0%**; recovered same-wf **50%** on N=100 mix; IR same-bind **64%**; orphans non-zero |
| Next | Remediation: stamp `workflow_id` at specialist write; require IR subject on append; backfill `last_artifact_id`; grow live SpecialistArtifact coverage beyond critique-only |

Status in gap register: **OPEN — evidence upgraded** (not closed).

---

## Tests

`tests/test_cio_diligence_p4_p5_research_specialists.py` — fixture audit recovers workflow + IR bind; orphan case flagged; accuracy/relevance remain `DATA_UNAVAILABLE`.
