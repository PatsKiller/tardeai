# CIO Platform Diligence — living scoreboard

GitHub is source of truth. Drive mirror optional via gog.

Authority: **READ_ONLY_ADVISORY**. MBI_BEHAVIOR: **0**. INTERDICT: left as found.

Resume cursor: first phase/package with status != DONE — **P4**
(`NEEDS_REVERIFICATION`, restamped 2026-08-30 by Wave A-RECONCILE R2; see
`docs/ops/CIO_R2_NO_PRODUCER_2026-08-30.md`).

---

## NOW

| Field | Value |
|-------|--------|
| CURRENT pin | **pre-promote (orchestrator)** — do not promote from this gap-register closeout alone |
| origin/main | `015a7891` (Merge #702 · full `015a7891a60a013119eff7554278c98696c6db9f`) — **hand-stamped, no producer**; records the tip these NOW figures were cut at, not today's tip. See *NOW provenance* below |
| This PR pin | **pre-promote** (orchestrator promotes) |
| Gap restamp | **PR-G** — closed mitigations + PARTIAL residuals (2026-08-30) |
| `/api/v2/health` | 200 |
| `/v3/cio` | 200 |
| `/api/v3/cio/home` | 200 |
| lineage complete_to_checkpoint | **406 / 752 (54.0%)** — **no 99.99% claim** |
| event lifecycle (weighted full) | **2.17%** recoverable / accepted (P1-WS2) |
| event lifecycle (unweighted mean) | **67.16%** · catalyst family **1.49%** |
| arcs | research_checkpoint 436 · cio_notification 29 |
| first open stage | research 640 · cio 112 |
| identity production resolvable | **98.9%** (P2-WS4) |
| SCHG Surface A | **EXITED** (P2-WS5) |
| rails | MBI=0 · READ_ONLY_ADVISORY · INTERDICT as found · no broker write · **no notify-on** · no Telegram producer |
| DRIVE | FAIL until gog upsert (optional) |
| phase cursor | **P4 PENDING REVERIFICATION** — P0–P3 and P5–P9 DONE |

### NOW provenance — hand-stamped, no producer

`[VERIFIED]` `grep -rn 'DILIGENCE_SCOREBOARD' scripts/ .github/` exits **1**: no
script and no workflow reads or writes `CIO_DILIGENCE_SCOREBOARD.json` or this
file. Every value in the NOW block is typed by hand, the `origin/main` pin
included.

A real producer for that quantity does exist —
`scripts/cio_release_manifest.py::git_origin_main()`, which is
`git rev-parse origin/main` — but it writes the release manifest, and wiring it
to this block would be the wrong fix. The pin's job is to say **which tip these
numbers were measured at**. Refreshing it on its own would hand stale figures a
current pin: a green obtained by the wrong artifact. So the pin is *labelled*
rather than automated, and it must be restamped only together with the numbers
beneath it.

`[DOC-CLAIM]` Those numbers have not been regenerated since they were stamped.
`docs/ops/CIO_V_SWEEP_2026-08-30.md` §2 re-measured several and recorded
`STALE`. Treat every NOW figure as `[DOC-CLAIM]` until the producer named beside
it is re-run.

---

## Phase packages

| ID | Title | Status | PR | sha | Proof |
|----|-------|--------|----|-----|-------|
| P0 | Master plan + scoreboard + gap register | DONE | #681 | `f54bf9f5` | plan + gap register; lineage re-measure 54% |
| P1-WS1 | Architecture as-built pack | DONE | #686 | `003806bc` | `docs/audits/diligence/P1_WS1_*` + type mapping Wave3 appendix + gap reconfirm G-AUTH-01/G-DUAL-01 |
| P1-WS2 | Event lifecycle census baseline | DONE | #685 | `aa21559c` | weighted full **2.17%**; catalyst **1.49%**; claim_99.99=false; `P1_WS2_*` + census script |
| P1-WS3 | Operator S0 workflow + failure battery | DONE | #689 | `b30aef08` | S0 flow matrix + dedup/OOO/restart battery; INTERDICT would_send=false |
| P2-WS4 | Identity confidence score | DONE | #688 | `b9f60227` | `docs/audits/diligence/P2_WS4_*`; production resolvable **98.9%**; ICS def shipped |
| P2-WS5 | HELD/EXIT/WATCH/CASH/DUST matrix | DONE | #688 | `b9f60227` | `docs/audits/diligence/P2_WS5_*`; SCHG Surface A EXITED; dust table |
| P3 | InstrumentRecord persistence drills | DONE | #682 | `72bc42c9` | `docs/audits/diligence/P3_*` + drill CLI + `test_cio_diligence_p3_*` |
| P4 | Research free / residual / model gov | **NEEDS_REVERIFICATION** | #687 | `d959111c` | Evidence JSON regenerated from `scripts/cio_research_governance_census.py` on 2026-08-30 after four hand-added keys were struck and an all-`exists:false` `stores` block (wrong root) was replaced. Code invariants (cap 5 · hop 1 · C/D∉`corpus_hit`) reproduce. Awaiting coordinator re-adjudication — `docs/ops/CIO_R2_NO_PRODUCER_2026-08-30.md` |
| P5 | Specialist N=100 sample | DONE | #687 | `d959111c` | `docs/audits/diligence/P5_*`; G-SPEC-01 evidence; exit gate FAIL honest |
| P6 | Council determinism | DONE | #683 | `eba4699a` | `docs/audits/diligence/P6_*` + `test_cio_diligence_p6_*` |
| P7 | Notification matrix (CC-first) | DONE | #683 | `eba4699a` | `docs/audits/diligence/P7_*` + `test_cio_diligence_p7_*`; G-NOTIFY-01 matrix evidence |
| P8 | Outcome/lesson MBI partition | DONE | #683 | `eba4699a` | `docs/audits/diligence/P8_*` + `test_cio_diligence_p8_*`; G-MBI-01 CI gate |
| P9 | Registry / orphan / 99.99% path | DONE | #684 | `714a665f` | `docs/audits/diligence/P9_*` + orphan census CLI; 30d miss=144 orphans=3; design path to 99.99% (**not claimed**) |

---

## Gap themes (PR-G restamp 2026-08-30)

See `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md`.

**CLOSED (mitigated):** G-AUTH-01 (#695) · G-SPEC-01 (#696) · G-PRICE-01 (#698) · G-ID-01 (#699) · G-IR-01 (#702) · G-MBI-01 (P8 CI on main) · G-DUAL-01 (labeled dual pipes `merged=false` by design).

**PARTIAL / residual OPEN:** G-LOOP-01 (#697 DLQ dry-run ledger; measured completion still 54.0% — **no 99.99%**) · G-NOTIFY-01 (matrix/S0 `would_send=false` closed; canary **DEFERRED_OPS**, no notify-on).

Leftovers still forbidden unless a package explicitly allows: ROTATE-as-action, notify-on, gate loosen, AGENT_COMMITMENT as policy, book merge, cio_run LLM default, stop-management files, historical ticker_prices DELETE.
