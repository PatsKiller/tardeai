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
| G-LOOP-01 | 2 | Lineage complete_to_checkpoint ≪ 99.99% | Baseline still **406/752 (54.0%)** via `cio_lineage_completion_report.py`. P9 added `cio_registry_orphan_census.py`: 30d **missing_cross_id=144** (event_id 142 + specialist workflow_id 2), **orphan_hits=3** (2 null-workflow specialist artifacts, 1 receipt notification). Design path (dead-letter + operator-gated replay, no silent auto-fix) in `docs/audits/diligence/P9_REGISTRY_ORPHAN_LIFECYCLE_2026-08-30.md`. **Still OPEN** — P9 measures + designs; does not claim 99.99%. | P1-WS2 (instrument), post-P9 identity/DLQ/replay packages |
| G-AUTH-01 | **2** | Daily rebalancer / alerts may bypass CIO | Aug 27 audit C1 (`portfolio_rebalancer.py`); **P1-WS1 locked Sev 2 on pin `852ecd47`**: `cio_rebalancer_readonly` adds AVOID flags only; job continues outside CIO gate (no broker write; MBI=0) | P1-WS1 done · authority claim still false for daily rebalance surface |
| G-ID-01 | 2 | subject_guid / instrument identity incomplete | Wave 2 slice 13: resolvable high, stamped low historically; dust/CUSIP edges | P2-WS4 |
| G-IR-01 | 2 | InstrumentRecord not universal wake load | Wave 3A–C library present; **P3 2026-08-30:** tmp cold-start / partial-write / version+rollback PASS; live RO census 129 rows / 40 subjects (all multi-version, MBI=0). Universality of wake load still unproven — producers may side-store | P5, P9 (persistence proven; wake-path still open) |
| G-SPEC-01 | 2 | Specialist→same record not proven at N=100 | SpecialistArtifact@v1-lite exists; sample audit not run | P5 |
| G-NOTIFY-01 | 2–3 | Alert fatigue vs miss under INTERDICT | Wave 3E: 462/466 suppressed CC-only; **P7 matrix proven** (CC-first / would_send=false); **P1-WS3 2026-08-30:** S0 always `SUPPRESSED`/`would_send=False`; CC surfaces `s0_operator_turns` with `would_send_any=False`; INTERDICT left as found (no notify-on). Canary enablement still TBD — **not closed** | P7 done · P1-WS3 S0 evidence · canary TBD |
| G-PRICE-01 | 2 | Outlier/corrupt price history; no DELETE policy | Aug 27 C3; quarantine path preferred | P1-WS2 / ops |
| G-MBI-01 | 1 | Continuous gate that MBI never rises | **P8 CI suite landed** (`test_cio_diligence_p8_mbi_partition.py`); stamps + BehaviorWriteRefused + AST/grep | P8 CI done · live env standing |
| G-DUAL-01 | 3 | Dual reentry pipes (queue vs Surface A) | Wave 2 slice 10 overlay; **P1-WS1 reconfirmed on live home `merged=false`** (labeled dual pipes; not merged) | P1-WS1 done · keep labeled |

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
