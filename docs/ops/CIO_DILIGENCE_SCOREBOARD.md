# CIO Platform Diligence — living scoreboard

GitHub is source of truth. Drive mirror optional via gog.

Authority: **READ_ONLY_ADVISORY**. MBI_BEHAVIOR: **0**. INTERDICT: left as found.

Resume cursor: first phase/package with status != DONE.

---

## NOW

| Field | Value |
|-------|--------|
| CURRENT pin | `852ecd47` (#681) |
| origin/main | `852ecd47` |
| `/api/v2/health` | 200 |
| `/v3/cio` | 200 |
| lineage complete_to_checkpoint | **406 / 752 (54.0%)** |
| arcs | research_checkpoint 436 · cio_notification 29 |
| first open stage | research 640 · cio 112 |
| rails | MBI=0 · READ_ONLY_ADVISORY · no broker write · no notify-on |
| DRIVE | FAIL until gog upsert (optional) |
| phase cursor | **P3 DONE** → next first PENDING (P1-WS1) |

---

## Phase packages

| ID | Title | Status | PR | sha | Proof |
|----|-------|--------|----|-----|-------|
| P0 | Master plan + scoreboard + gap register | DONE | #681 | `852ecd47` | plan in docs/audits; lineage re-measure 54% |
| P1-WS1 | Architecture as-built pack | PENDING | | | |
| P1-WS2 | Event lifecycle census baseline | PENDING | | | |
| P1-WS3 | Operator S0 workflow + failure battery | PENDING | | | |
| P2-WS4 | Identity confidence score | PENDING | | | |
| P2-WS5 | HELD/EXIT/WATCH/CASH/DUST matrix | PENDING | | | |
| P3 | InstrumentRecord persistence drills | DONE | #682 | `72bc42c9` | tmp cold-start/partial-write/rollback PASS; see diligence audit |
| P4 | Research free / residual / model gov | PENDING | | | |
| P5 | Specialist N=100 sample | PENDING | | | |
| P6 | Council determinism | PENDING | | | |
| P7 | Notification matrix (CC-first) | PENDING | | | |
| P8 | Outcome/lesson MBI partition | PENDING | | | |
| P9 | Registry / orphan / 99.99% path | PENDING | | | |

---

## Seeded gap themes (update with evidence)

See `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md`.

Leftovers still forbidden unless a package explicitly allows: ROTATE-as-action, notify-on, gate loosen, AGENT_COMMITMENT as policy, book merge, cio_run LLM default, stop-management files, historical ticker_prices DELETE.
