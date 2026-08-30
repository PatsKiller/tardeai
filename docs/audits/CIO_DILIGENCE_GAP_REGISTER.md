# CIO Diligence Gap Register

**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0  
**Seeded:** 2026-08-30 Phase 0 kickoff  
**Pin at seed:** `be09945b`  
**Update rule:** every package adds evidence (doc · code · live measure). Never close a Sev 1 without pin + test.

Severity: **1** Critical · **2** High · **3** Medium · **4** Low

---

## Open (seeded)

| ID | Sev | Theme | Evidence at seed | Next package |
|----|-----|-------|------------------|--------------|
| G-LOOP-01 | 2 | Lineage complete_to_checkpoint ≪ 99.99% | `cio_lineage_completion_report.py`: **406/752 (54.0%)**; arcs research_checkpoint 436 vs cio_notification 29 | P1-WS2, P9 |
| G-AUTH-01 | 1–2 | Daily rebalancer / alerts may bypass CIO | Aug 27 audit C1 (`portfolio_rebalancer.py`); **re-confirm on be09945b** before severity lock | P1-WS1 |
| G-ID-01 | 2 | subject_guid / instrument identity incomplete | Wave 2 slice 13: resolvable high, stamped low historically; dust/CUSIP edges | P2-WS4 |
| G-IR-01 | 2 | InstrumentRecord not universal wake load | Wave 3A–C library present; **P3 2026-08-30:** tmp cold-start / partial-write / version+rollback PASS; live RO census 129 rows / 40 subjects (all multi-version, MBI=0). Universality of wake load still unproven — producers may side-store | P5, P9 (persistence proven; wake-path still open) |
| G-SPEC-01 | 2 | Specialist→same record not proven at N=100 | SpecialistArtifact@v1-lite exists; sample audit not run | P5 |
| G-NOTIFY-01 | 2–3 | Alert fatigue vs miss under INTERDICT | Wave 3E: 462/466 suppressed CC-only; no Telegram producer | P7 |
| G-PRICE-01 | 2 | Outlier/corrupt price history; no DELETE policy | Aug 27 C3; quarantine path preferred | P1-WS2 / ops |
| G-MBI-01 | 1 | Continuous gate that MBI never rises | Stamped on products; needs CI grep/property suite | P8 |
| G-DUAL-01 | 3 | Dual reentry pipes (queue vs Surface A) | Wave 2 slice 10 overlay; must stay labeled not merged | P1-WS1 |

---

## Closed / superseded (reference only)

| ID | Note |
|----|------|
| Diagram type mapping L7 | `EXTERNAL_DIAGRAM_TYPE_MAPPING.md` — names mapped; Wave 3 added InstrumentRecord / SpecialistArtifact@v1-lite / CIOCouncilSynthesis@v1 |
| Aug 27 Critical C2–C5 | Remediation closeout claimed shipped or phased — **re-verify** under P1 before treating as closed |

---

## Measurement snapshot (Phase 0)

```
workflows                752
complete_to_checkpoint   406  (54.0%)
with checkpoint_id       436
arcs                     research_checkpoint=436  cio_notification=29
first open stage         research=640  cio=112
health/cio               200/200
```

Do **not** claim 99.99% until P1-WS2 instrumentation + P9 hardening path exist.
