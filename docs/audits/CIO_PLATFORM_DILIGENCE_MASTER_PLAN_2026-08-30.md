# Trade AI Platform — Enterprise Due Diligence, Validation, Remediation & Execution Master Plan

**Document type:** Phase 1–9 master plan (planning only; no remediation code in this turn)  
**Authority rails (immutable for all phases):** `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR = 0` · no broker/order/stop/2FA/risk mutations without explicit operator-approved 2FA path · INTERDICT left as found unless a phase explicitly re-scopes notify  
**As-of:** 2026-08-30  
**Live pin at plan authorship:** `be09945b` (`CURRENT` exact-main release); Wave 2 scoreboard also tracks later pins through `#623` / `53794d82` — re-measure NOW at Phase 0 kickoff  
**Primary diagram:** operator-supplied end-to-end event → InstrumentRecord → research → specialists → CIO synthesis → product → notification → outcome → cognition loop  
**Prior art (must reuse, not redo):**  
- `docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md` + remediation closeout  
- `docs/audits/CIO_PIPELINE_DIAGRAM_VERIFICATION_2026-08-27.md`  
- `docs/architecture/cio/EXTERNAL_DIAGRAM_TYPE_MAPPING.md`  
- Wave 2 living scoreboard + Wave 3A–3E ops notes  

---

## 0. Executive framing

### 0.1 Objective

Produce a governed, evidence-based program that:

1. Validates every workflow stage against specification **and** against live behavior.  
2. Verifies data integrity, identity, and persistence.  
3. Confirms determinism where required (council, product, MBI=0).  
4. Identifies broken processes, gaps, risks, and enhancements with severity.  
5. Documents remediation actions with owners, gates, and rollback.  
6. Yields an **approved** execution roadmap (30 / 60 / 90 + beyond).  
7. Establishes ongoing governance and control standards.

### 0.2 What is already true (do not rediscover as “missing”)

| Area | As-built status (grounded) |
|------|----------------------------|
| Operator product / books / home coverage | Live: `CIOOperatorProduct@v1`, Wave 2 slices 00–41+ on scoreboard, coverage card, Surface A status (SCHG dust = EXITED) |
| InstrumentRecord@v1 | Real module + migration + Wave 3A library; not yet the sole authoritative wake path for every surface |
| SpecialistArtifact@v1-lite / CIOCouncilSynthesis@v1 | Real library modules (Wave 3B); diagram’s older “v2 / renamed InvestmentDecision” mapping is partially superseded |
| Notification classes | IMMEDIATE / DIGEST / COMMAND_CENTER_ONLY / SUPPRESSED exist; Wave 3E CC-only rendering with INTERDICT on |
| OutcomeCheckpoint@v1 | Real; lineage completion **improved** from 0% (2026-08-27) to **~54%** (752 workflows, 406 complete_to_checkpoint) — still not 99.99% |
| MBI_BEHAVIOR=0 | Enforced in env + stamped on products / instrument records |
| Identity / dust | `subject_guid`, Surface A dust rule (`<1` share → EXITED), holdings truth slice 12 reduced held_n dust |
| CanonicalStoreRegistry@v1 | Exact match; wired |
| C1-class finding (rebalancer bypasses CIO) | Documented Critical in Aug 27 audit — still a platform authority gap unless closed later |

### 0.3 What the diagram claims that is still weak or open

| Diagram claim | Measured reality |
|---------------|------------------|
| Closed loop Event → … → REVIEW_READY → next wake | Partial: research/CIO arcs improved but **not** universal completion; goal wakes ≠ security events |
| Every wake loads InstrumentRecord | Partially wired (Wave 3); many producers still write side stores without bind |
| Specialists always same `workflow_id` / same record | Contract exists; not proven across all agent lanes |
| Free-first then residual web then LLM | Budget/library code exists (Wave 3D); residual web gated; not yet proven for every research_id |
| 99.99% event lifecycle success | **Not measured** end-to-end today; need Workstream 2 instrumentation before claiming |
| Lessons never affect sizing/orders | Policy + MBI=0; need continuous regression gates |

### 0.4 Success definition for the **program** (not a single PR)

- Living **As-Built vs Diagram** matrix maintained on GitHub (SoT).  
- Severity-ranked **Gap Register** with evidence links (script output, PR, pin).  
- Phase exit gates: green local acceptance, health/cio 200, exact-main promote, no MBI/notify/broker regressions.  
- Approved roadmap signed off phase-by-phase (operator “continue” / phase exit).  
- No phase may raise `MBI_BEHAVIOR`, enable notify-on, or scrub history without an explicit operator decision recorded on the scoreboard.

---

## 1. Governance & operating rules (all phases)

### 1.1 Authority

- Default: **READ_ONLY_ADVISORY**.  
- `MBI_BEHAVIOR = 0` immutable unless operator amends this charter.  
- `MBI_COGNITION = 1` allowed only for next question / narrative / priority (as InstrumentRecord docs state).  
- Telegram: INTERDICT left as found; Wave 3E pattern = CC render without producer.  
- Exact-main deploy: HEAD == origin/main merge commit; `cio_phase2_exact_main_deploy.sh` prepare/promote.  
- One PR per remediation slice unless operator allows a batched closeout PR.

### 1.2 Evidence standard

Every finding must cite at least two of: **doc claim · code path · live store/API measure**.  
No “file exists ⇒ working.” Prefer `cio_lineage_completion_report.py`, census scripts, `/api/v3/cio/home`, registry integrity tools.

### 1.3 Severity rubric (operator framework)

| Sev | Name | Examples |
|-----|------|----------|
| 1 | Critical | Persistence loss, identity collision, corrupt prices driving decisions, silent MBI breach, unrecoverable event |
| 2 | High | Wrong recommendation path, research contamination, notify miss/dup of material events, CIO bypass by live cron |
| 3 | Medium | Performance, duplicate processing, incomplete audit trail, dual pipes unlabeled |
| 4 | Low | UX, reporting polish, operational efficiency |

### 1.4 Deliverable home

| Artifact | Location |
|----------|----------|
| Master plan (this) | Session plan + promote to `docs/audits/CIO_PLATFORM_DILIGENCE_MASTER_PLAN_2026-08-30.md` on kickoff PR |
| Living scoreboard | Extend or sibling `docs/ops/CIO_DILIGENCE_SCOREBOARD.md` (+ json) |
| Gap register | `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md` |
| Phase packs | `docs/audits/diligence/phase_N_*.md` |
| Drive mirror | gog `--replace` blobs when folder exists; else DRIVE=FAIL, GitHub SoT |

---

## 2. Phase map (1–9) with workstreams

### PHASE 1 — Full system due diligence

**Exit gate:** As-built architecture pack + failure-point inventory + risk register approved; diagram verification re-run on current pin.

#### WS1 — Architecture review

**Scope:** Event intake → operator interface → identity → materiality → graph impact → research → specialist dispatcher → CIO synthesis → product → notification → outcome → cognition → persistence.

**Tasks:**

1. Refresh `EXTERNAL_DIAGRAM_TYPE_MAPPING.md` for Wave 3 types (`InstrumentRecord@v1`, `SpecialistArtifact@v1-lite`, `CIOCouncilSynthesis@v1`).  
2. Produce **as-built** architecture doc + data-flow + dependency diagram (code-derived, not aspirational redraw).  
3. Failure-point inventory (per stage: crash, silent skip, dual-write, id fork).  
4. Risk register seeded from Aug 27 Critical/High leftovers + Wave 2 leftovers (ROTATE-as-action, notify-on, history DELETE, etc.).

**Deliverables:** as-built doc · diagrams · failure inventory · risk register.

#### WS2 — Event lifecycle validation

**Event families:** security/ticker/holdings/exit/reentry · sector/industry/concentration · catalyst (earnings/guidance/reg/macro).

**Per event:** accepted → normalized → persisted → processed → archived → recoverable.

**Method:**

- Inventory producers (cron/systemd/API) vs consumers.  
- Sample N events per family from live stores; measure drop rate.  
- Build/extend a **lifecycle census** script (read-only) with stage timestamps.  
- Target **99.99%** is a **program KPI after instrumentation** — Phase 1 measures baseline; Phase 9 hardens to target.

**Failure tests:** duplicate / late / missing / out-of-order / restart mid-pipeline.

#### WS3 — Operator workflow validation

**Flows:** question · ack · defer · reject · CIO escalation (`S0_OPERATOR_CONVERSE`).

**Confirm:** Telegram mapping (when not interdicted), operator turns on InstrumentRecord, conversation state, replay, audit trail.

**Failure tests:** duplicate/late/missing/out-of-order messages · restart mid-conversation.

**Constraint:** INTERDICT-on environments validate **would_send / CC-only** paths without enabling notify.

---

### PHASE 2 — Data integrity & identity

**Exit gate:** Identity confidence report for production HELD/EXIT/WATCH/CASH; dust/cash never misclassified as active security.

#### WS4 — Canonical identity engine

**Must distinguish:** ticker · CUSIP · ISIN · CIK · ETF · ADR · mutual fund.

**Validate:** no collisions · no duplicate entities · correct mapping · historical continuity.

**Controls:** Identity Confidence Score; target **100% for production records** that are promotion-grade (define “production record” = HELD material + ACTIVE watch + EXIT with former table row).

**Reuse:** `cio_subject_guid`, `identity_registry`, Wave 2 subject_guid % measure (slice 13), never ticker-as-security-GUID regression.

#### WS5 — Position state validation

**States:** HELD · EXIT · WATCH · CASH · DUST.

**Verify:** dust never active position · cash never security · exit→watch transition · reentry Surface A/B not merged · SCHG-class residual = EXITED/DUST_RESIDUAL.

**Reuse:** `collect_surface_a_status`, holdings truth slice 12, two-writer holdings detect (Wave 2).

---

### PHASE 3 — InstrumentRecord@v1 audit

**Exit gate:** Cold-start / restart / partial-write recovery demos with zero loss; version/rollback path documented and tested.

**Validate fields:** `subject_key`, thesis, narrative, research, artifacts, lessons, analyst, earnings date, `next_eligible_at`, priority, operator_turns.

**Persistence tests:** cold-start · restart · replication (overlay inode) · partial write.

**Versioning:** history available · rollback possible · prior thesis recoverable · research lineage preserved.

**Reuse:** `cio_instrument_record.py`, `cio_migrate_instrument_records.py`, Wave 3A–C.

---

### PHASE 4 — Research engine review

**Exit gate:** Free-first path proven; residual web hop/day/budget enforced; one model class per research_id/day regression green.

#### WS6 — Free research layer

FRED · Fed · gov datasets · internal RAG · historical DBs — accessibility, freshness, quality score.

#### WS7 — Residual web

≤1 hop / subject_key / day · budget N · official-first · duplicate suppression · reuse · grade C/D ≠ corpus_hit.

**Reuse:** `cio_residual_web.py`, Wave 3D hop/critique notes.

#### WS8 — Model governance

Flash · Pro · Grok critique · corpus reuse — one class per cycle · no redundant inference · cost min.

**Reuse:** research budget report, Wave 3D flash/critique docs, cost_usd=0.0 / absent checks from Wave 2B.

---

### PHASE 5 — Specialist agent validation

**Exit gate:** Sample of **100** SpecialistArtifact outputs scored; zero orphan artifacts in sample; same `workflow_id` / same InstrumentRecord in all sampled dispatches.

**Agents:** research · seasonality · sector · earnings · macro · cash-regime.

**Controls:** same workflow context · update same record · no parallel record creation.

**Measure:** accuracy · relevance · consistency · traceability.

**Reuse:** `cio_specialist_artifact.py`, Wave 3B.

---

### PHASE 6 — CIO decision system audit

**Exit gate:** Deterministic property tests: same inputs → same `CIOCouncilSynthesis` / product fields; DISPUTED preserved; no silent specialist drop.

**Cases:** bullish-only · bearish-only · mixed · conflicting specialists · missing specialists · incomplete research.

**Reuse:** `cio_council_synthesis.py`, Wave 3B council policy tests.

**Open risk (carry from C1):** platform rebalancer path still may bypass CIO — track as Sev 2/1 policy decision (gate cron vs flag AVOID-only).

---

### PHASE 7 — Notification governance

**Exit gate:** Routing matrix proven for IMMEDIATE / DIGEST / CC_ONLY / SUPPRESSED under INTERDICT-on and (optional) INTERDICT-off canary.

**Tests:** priority up/down · reentry NEAR · duplicates · dust · cash · test events.

**Verify:** correct routing · suppression · escalation · no duplicate deliveries · Wave 3E CC block pattern.

**Hard rule:** no new Telegram producer without operator phase exit.

---

### PHASE 8 — Outcome & learning

**Exit gate:** Lessons shown to affect research question / priority / narrative only; property tests prove **no** influence on size / orders / broker; MBI_BEHAVIOR=0 regression suite in CI.

**Review:** OutcomeCheckpoint · lessons · hypotheses · REVIEW_READY.

**Reuse:** checkpoints, provisional lessons Wave 2, memory receipts.

---

### PHASE 9 — Registry & persistence validation

**Exit gate:** Every sampled object has registry id; duplicate-id / concurrency / failover / recovery tests documented; orphan scan = 0 for production window.

**IDs:** workflow · event · research · artifact · notification · checkpoint · lesson · instrument_record (+ generation / outcome / operator_turn).

**Reuse:** `canonical_store_registry.py`, integrity audits, `GOOD_PERSISTENT_ROOT` / overlay.

**KPI:** move lifecycle success from measured baseline toward **99.99%** with dead-letter + replay.

---

## 3. Gap analysis method (apply every phase)

For each component:

1. Diagram claim  
2. Code contract  
3. Live measure  
4. Gap (if any)  
5. Severity 1–4  
6. Remediation option(s)  
7. Test / rollback  
8. Scoreboard row  

**Seeded Sev 1/2 themes (update with fresh evidence at Phase 0):**

| ID | Theme | Sev | Notes |
|----|-------|-----|-------|
| G-AUTH-01 | Daily rebalancer / alerts may bypass CIO authority | 1–2 | Aug 27 C1; confirm still true on current pin |
| G-LOOP-01 | Lineage completion ≪ 99.99% | 2 | Now ~54%; identity/causal unwiring remains |
| G-ID-01 | Not all rows stamp subject_guid; CUSIP/dust edge cases | 2 | Wave 2 progress; finish confidence score |
| G-IR-01 | InstrumentRecord not yet universal wake load | 2 | Wave 3 partial |
| G-SPEC-01 | Specialist→same record not proven at N=100 | 2 | Need sample audit |
| G-NOTIFY-01 | Alert fatigue vs miss under INTERDICT | 2–3 | 3E suppresses heavily; canary policy TBD |
| G-PRICE-01 | Historical outlier bars / no history DELETE policy | 2 | C3 family; quarantine without scrub |
| G-MBI-01 | Continuous CI gate that MBI never rises | 1 | Must be automated |

---

## 4. Enhancement & execution roadmap

### Immediate (0–30 days) — Diligence Phase 0 + Phase 1–2 start

| Work | Owner lane | Gate |
|------|------------|------|
| Kickoff PR: publish this master plan under `docs/audits/` | Conductor | merged + exact-main |
| Diligence scoreboard + gap register bootstrap | Conductor | tests parse JSON |
| Re-run diagram verification + lineage report on pin | Conductor | artifact dated |
| WS1 as-built pack | Arch | review OK |
| WS4/WS5 identity + position-state baseline | Data | census JSON |
| Security: audit logging checklist, immutable event trail inventory | Ops | checklist |
| Dead-letter + replay **design** (no silent auto-remediate) | Ops | design approved |

### Near term (30–60 days) — Phases 3–5

| Work | Gate |
|------|------|
| InstrumentRecord cold-start / recovery drills | zero loss |
| Research free-first + residual hop/budget proof | budget report green |
| SpecialistArtifact sample N=100 | scorecard published |
| Research quality / specialist confidence scoring v0 | Class D product fields |

### Mid term (60–90 days) — Phases 6–9

| Work | Gate |
|------|------|
| Deterministic council property suite in CI | suite green |
| Notification routing matrix + optional canary | no Telegram burst |
| Outcome→lesson cognition-only proofs | MBI=0 CI |
| Registry orphan scan + concurrency tests | 0 orphans in window |
| Lifecycle KPI plan to 99.99% | measured path |

### Beyond 90 days

Horizontal processing · search optimization · artifact compression · CIO scorecards · explainability / decision lineage reporting — only after Sev 1/2 closed.

---

## 5. Work package sequence (executable after approval)

```text
P0  Publish master plan + diligence scoreboard + gap register
P1  WS1 architecture pack (as-built vs diagram)
P1  WS2 event lifecycle census (baseline %, not fake 99.99%)
P1  WS3 operator S0 workflow + failure battery (INTERDICT-aware)
P2  WS4 identity confidence score
P2  WS5 HELD/EXIT/WATCH/CASH/DUST matrix
P3  InstrumentRecord persistence & versioning drills
P4  WS6–8 research free / residual / model governance
P5  Specialist N=100 sample audit
P6  Council determinism + DISPUTED cases
P7  Notification matrix (CC-first)
P8  Outcome/lesson MBI partition tests
P9  Registry / orphan / recovery / 99.99% path
```

Each package: **dry → tests → ops note → scoreboard → one PR → exact-main promote → LIVE 5 → DRIVE ok/fail**.

---

## 6. Ongoing controls (standing)

| Control | Cadence |
|---------|---------|
| `cio_lineage_completion_report.py --fail-on-finding` | daily / CI |
| Diligence scoreboard NOW block | every package |
| MBI=0 / no new Telegram producer grep | every PR |
| Identity + dust classification unit tests | every PR |
| Store integrity / registry drift audit | weekly |
| Operator readout after every 10 diligence packages | stop for continue |

---

## 7. Out of scope unless operator amends charter

- Enabling notify-on / lowering INTERDICT without canary plan  
- ROTATE-as-action · book merge · AGENT_COMMITMENT as policy  
- `cio_run` LLM as default product path  
- Historical `ticker_prices` DELETE  
- Broker/stop/cash/2FA mutations  
- Claiming 99.99% before instrumentation baseline exists  

---

## 8. Immediate next action after plan approval

1. Open kickoff PR that copies this plan to `docs/audits/CIO_PLATFORM_DILIGENCE_MASTER_PLAN_2026-08-30.md`.  
2. Create `CIO_DILIGENCE_SCOREBOARD.md` + `.json` (NOW pin, rails, phase cursor).  
3. Re-measure lineage + diagram verification on **then-current** pin; seed gap register.  
4. Stop for operator approval of Phase 1 WS1 start.

**Approval question for exit:** Approve this Phase 1–9 master plan as the diligence charter?
