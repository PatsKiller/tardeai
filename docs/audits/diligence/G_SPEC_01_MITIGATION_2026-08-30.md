# G-SPEC-01 mitigation — SpecialistArtifact `workflow_id` bind

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0  
**Rails:** no silent DELETE/rewrite of historical jsonl · no gap-register edit in this PR · no promote  

**Schema:** still `SpecialistArtifact@v1-lite` (no new `@v1` bump → dark-contract `NO_CONSUMER_REASON` N/A).  

**Code:**  
- `scripts/lib/cio_specialist_artifact.py`  
- `scripts/lib/cio_grok_critique.py` / `scripts/lib/cio_edgar_proof.py` (`to_artifact` pass-through)  
- `scripts/cio_specialist_sample_audit.py` (policy expectations)  
- `tests/test_cio_gap_spec_01.py`  

---

## 1. Gap (as measured in P5)

Live `SpecialistArtifact@v1-lite` store was thin (n=2 critique rows) with **`workflow_id=null`** on row. Same-workflow bind was only recoverable via lineage `research_id→node_id`. Contract previously allowed `build(workflow_id=None)`.

See: `docs/audits/diligence/P5_SPECIALIST_SAMPLE_2026-08-30.md`.

---

## 2. Mitigation (this package)

| Surface | Behavior |
|---------|----------|
| `build(...)` | **Requires** non-empty `workflow_id` (keyword-only). Null / blank / non-str → `ValueError` (builders/tests fail loud). |
| `append(root, row)` | Validates with `new_write=True`. Missing bind → **structured refusal** `{wrote:false, refused:true, reason:missing_workflow_id, problems:[...]}` — jobs do not crash. |
| `validate(row)` | Default **historical-tolerant** (null wf still structurally OK). `validate(..., new_write=True)` adds `missing_workflow_id`. |
| Writers | `cio_grok_critique.to_artifact` / `cio_edgar_proof.to_artifact` require `workflow_id` and pass it through from plan/research context. |
| Historical rows | **Retained.** No backfill rewrite in this package. Orphans remain until operator-gated DLQ/replay (P9 path). |
| Sample audit | Documents new-write policy vs live historical null-wf; does not DELETE. |

`cio_specialist_artifacts.py` (plural) is the handoff-advisory extractor — out of scope for this bind (different surface).

---

## 3. What this does *not* claim

- Exit gate “zero orphans / 100% same-wf stamped on live N=100” is **not** closed: historical null-wf + fixture projections remain measurable orphans until DLQ growth of live stamped coverage.  
- InstrumentRecord `last_artifact_id` wiring is **not** in this package.  
- Gap register row G-SPEC-01 is **not** edited here (operator/follow-on scoreboard update).  

---

## 4. Tests

```bash
.venv/bin/python -m pytest \
  tests/test_cio_gap_spec_01.py \
  tests/test_cio_wave3b_council_policy.py \
  tests/test_cio_diligence_p4_p5_research_specialists.py \
  tests/test_cio_grok_critique_lane.py \
  -q
```

---

## 5. Follow-on

1. Operator-gated DLQ/replay for the 2 (or more) live null-wf specialist rows (align with P9 never_auto_remediate).  
2. Ensure every production write path that materializes SpecialistArtifact rows has plan/research `workflow_id` in scope before `to_artifact` / `append`.  
3. Re-run `cio_specialist_sample_audit.py` after live stamped coverage grows; update gap register when evidence warrants.
