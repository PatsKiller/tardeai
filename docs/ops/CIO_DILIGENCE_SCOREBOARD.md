# CIO Platform Diligence — living scoreboard

GitHub is source of truth. Drive mirror optional via gog.

Authority: **READ_ONLY_ADVISORY**. MBI_BEHAVIOR: **0**. INTERDICT: left as found.

Resume cursor: first phase/package with status != DONE.

---

## NOW

| Field | Value |
|-------|--------|
| CURRENT pin | `852ecd47` (main @ P0 merge #681; live CURRENT may still trail) |
| origin/main | `852ecd47` |
| `/api/v2/health` | 200 |
| `/v3/cio` | 200 |
| lineage complete_to_checkpoint | **406 / 752 (54.0%)** |
| event lifecycle (weighted full) | **2.17%** recoverable / accepted (P1-WS2) |
| event lifecycle (unweighted mean) | **67.16%** · catalyst family **1.49%** |
| arcs | research_checkpoint 436 · cio_notification 29 |
| first open stage | research 640 · cio 112 |
| rails | MBI=0 · READ_ONLY_ADVISORY · no broker write · no notify-on · no Telegram producer |
| DRIVE | FAIL until gog upsert (optional) |
| phase cursor | **P1-WS1** (earliest PENDING) · P1-WS3 + P2-WS4/WS5 + P6/P7/P8 DONE out of order · P4/P5 DONE this PR |

---

## Phase packages

| ID | Title | Status | PR | sha | Proof |
|----|-------|--------|----|-----|-------|
| P0 | Master plan + scoreboard + gap register | DONE | #681 | `f54bf9f5` | plan in docs/audits; lineage re-measure 54% |
| P1-WS1 | Architecture as-built pack | PENDING | | | |
| P1-WS2 | Event lifecycle census baseline | DONE | *(this PR)* | | weighted full **2.17%**; catalyst **1.49%**; claim_99.99=false |
| P1-WS3 | Operator S0 workflow + failure battery | **DONE** | *(this PR)* | *(fill after promote)* | S0 flow matrix + dedup/OOO/restart battery; INTERDICT would_send=false |
| P2-WS4 | Identity confidence score | **DONE** | *(this PR)* | *(fill after merge)* | `docs/audits/diligence/P2_WS4_*`; production resolvable **98.9%**; ICS def shipped |
| P2-WS5 | HELD/EXIT/WATCH/CASH/DUST matrix | **DONE** | *(this PR)* | *(fill after merge)* | `docs/audits/diligence/P2_WS5_*`; SCHG Surface A EXITED; dust table |
| P3 | InstrumentRecord persistence drills | PENDING | | | |
| P4 | Research free / residual / model gov | DONE | *(this PR)* | | `docs/audits/diligence/P4_*` + census + `test_cio_diligence_p4_p5_*` |
| P5 | Specialist N=100 sample | DONE | *(this PR)* | | `docs/audits/diligence/P5_*`; G-SPEC-01 evidence; exit gate FAIL honest |
| P6 | Council determinism | DONE | *(#683)* | | `docs/audits/diligence/P6_*` + `test_cio_diligence_p6_*` |
| P7 | Notification matrix (CC-first) | DONE | *(#683)* | | `docs/audits/diligence/P7_*` + `test_cio_diligence_p7_*`; G-NOTIFY-01 evidence |
| P8 | Outcome/lesson MBI partition | DONE | *(#683)* | | `docs/audits/diligence/P8_*` + `test_cio_diligence_p8_*`; G-MBI-01 CI gate |
| P9 | Registry / orphan / 99.99% path | PENDING | | | |

---

## Seeded gap themes (update with evidence)

See `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md`.

Leftovers still forbidden unless a package explicitly allows: ROTATE-as-action, notify-on, gate loosen, AGENT_COMMITMENT as policy, book merge, cio_run LLM default, stop-management files, historical ticker_prices DELETE.
