# CIO Diligence P4 + P5 — ops note

Date: 2026-08-30  
Authority: READ_ONLY_ADVISORY  
MBI_BEHAVIOR: 0  
Branch: `feat/cio-diligence-p4-p5-research-specialists`  
Promote: **DO NOT** (operator gate)

## Delivered

| Artifact | Path |
|----------|------|
| P4 research engine review | `docs/audits/diligence/P4_RESEARCH_ENGINE_REVIEW_2026-08-30.md` |
| P4 census JSON | `docs/audits/diligence/P4_RESEARCH_GOVERNANCE_CENSUS_2026-08-30.json` |
| P5 specialist sample | `docs/audits/diligence/P5_SPECIALIST_SAMPLE_2026-08-30.md` |
| P5 evidence | `docs/audits/diligence/P5_SPECIALIST_SAMPLE_EVIDENCE_2026-08-30.json` (+ `_full`) |
| Governance census script | `scripts/cio_research_governance_census.py` |
| Specialist sample audit | `scripts/cio_specialist_sample_audit.py` |
| Invariant tests | `tests/test_cio_diligence_p4_p5_research_specialists.py` |
| Gap G-SPEC-01 | evidence upgraded (still OPEN) |
| Scoreboard | P4 + P5 → DONE |

## Commands (read-only)

```bash
python3 scripts/cio_research_governance_census.py --root . --json
python3 scripts/cio_research_budget_report.py \
  --root /home/johnclaw/trade-ai-releases/persistent-state --json
python3 scripts/cio_specialist_sample_audit.py \
  --root /home/johnclaw/trade-ai-releases/persistent-state --limit 100 --json
python3 -m pytest tests/test_cio_diligence_p4_p5_research_specialists.py -q
```

## Headlines

1. **P4 PASS on code gates:** free-first ladder, `DAILY_CAP=5`, residual hop=1 / subject / day, C/D∉`corpus_hit`, same-day collapse — pinned by tests + census.  
2. **P5 sample N=100 run:** 2 live SpecialistArtifacts + 98 hermes fixture projections; **exit gate FAIL** on zero-orphan / universal same-workflow / same-IR.  
3. **G-SPEC-01 remains OPEN** with measured rates (same-wf 50%, same-IR 64%, wf orphans 50%). Accuracy/relevance = **DATA_UNAVAILABLE** (no LLM rubric).  
4. Live budget dry-select (2026-08-30): PFLT, NOC, RTX, SLEEVE:CASH, EXIT:CAST — cap held at 5.  
5. No budget raise, no vendor call, no notify-on, no promote in this package.

## Wave 3D reuse

Cited as prior art: `CIO_WAVE3D_2026-08-29.md`, `CIO_WAVE3D_HOP_2026-08-29.md`, `CIO_WAVE3D_FLASH_2026-08-29.md`, critique notes — residual/flash/critique posture already evidenced; this package adds diligence census + N=100 bind audit only.
