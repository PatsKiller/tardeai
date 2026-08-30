# P1-WS1 — As-built architecture pack

**Package:** P1-WS1 Architecture as-built  
**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY · `MBI_BEHAVIOR=0`  
**Measured against:** live CURRENT pin `852ecd47` (= `origin/main` at authorship)  
**Persistent root:** `/home/johnclaw/trade-ai-releases/persistent-state`  
**Method:** code paths + live store/API/timer greps. Not aspirational. No 99.99% claim.

Companions:
- Failure inventory → `docs/audits/diligence/P1_WS1_FAILURE_POINT_INVENTORY_2026-08-30.md`
- Type mapping refresh → `docs/architecture/cio/EXTERNAL_DIAGRAM_TYPE_MAPPING.md`
- Gap register → `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md`
- Prior flow measure → `docs/audits/CIO_PIPELINE_DIAGRAM_VERIFICATION_2026-08-27.md`

---

## 0. Headline

The operator diagram (event → … → cognition → persistence) is **partially as-built**.

| Band | Reality on `852ecd47` |
|------|------------------------|
| Upper CIO lane (wake → materiality → research/Hermes → product → CC home) | **Live** — timers fire; product + lineage stores fresh; `/api/v3/cio/home` 200 |
| Wave 3 typed contracts (`InstrumentRecord@v1`, `SpecialistArtifact@v1-lite`, `CIOCouncilSynthesis@v1`) | **Library live**; stores present but **not universal** on every wake |
| Daily portfolio rebalance recommendation path | **Parallel authority** — still not CIO-gated (G-AUTH-01) |
| Closed loop to OutcomeCheckpoint → lesson → next wake | **Partial** — lineage `complete_to_checkpoint` **406/752 (54.0%)**; not 99.99% |

Rails observed (left as found; this package does not change them):
- `MEMORY_BEHAVIOR_INFLUENCE=0` on CIO user units + stamped on sampled lineage envelopes
- Portfolio `/api/v2/health` **200**, `/v3/cio` **200**, `/api/v3/cio/home` **200** (port 7777)
- Dual reentry books on home: `merged=false`, Surface A/B labeled

---

## 1. Stage map (diagram order)

Status legend: **LIVE** = scheduled/served and writing; **PARTIAL** = code+some store but not universal; **LIBRARY** = real module, thin/zero production bind; **PARALLEL** = live path outside CIO authority; **MISSING STORE** = registry id without on-disk file.

### 1.1 Event intake

| Item | Path / evidence | Status |
|------|-----------------|--------|
| Event detector (lab schedules → wake jobs) | `scripts/lib/cio_event_detector.py` | PARTIAL (lab + inventory-derived schedules) |
| Event bus / outbox helpers | `scripts/lib/cio_event_bus.py`, `cio_event_outbox.py` | LIBRARY |
| Material publisher | `scripts/lib/cio_material_publisher.py` | LIVE (fed by material scan) |
| Situation detector | `scripts/lib/cio_situation_detector.py` | PARTIAL |
| Live cursors / events | `data/cio/cio_event_cursors.jsonl`, `cio_events.jsonl` (persist root; events mtime 2026-08-29) | LIVE stores |
| Reactive wake cycle | user timer `tradeai-cio-reactive.timer` → `scripts/cio_reactive_cycle.py --once` | **LIVE** (~2 min) |
| Legacy portfolio morning pipe | crontab `15 7 * * 1-5` → `portfolio_orchestrator.py` | **PARALLEL** (non-CIO) |

### 1.2 Operator interface

| Item | Path / evidence | Status |
|------|-----------------|--------|
| Command Center / home API | `scripts/lib/cio_command_center.py`; `GET /api/v3/cio/home` | **LIVE** |
| Operator product contract | `scripts/lib/cio_operator_product.py` (`CIOOperatorProduct@v1`) | **LIVE** (`cio_operator_product.json` fresh 2026-08-30) |
| S0 converse loop | `scripts/lib/cio_s0_operator_loop.py`, `cio_converse_core.py`, `cio_telegram_converse.py` | LIVE code; Telegram bot unit active |
| Operator turns store | `data/cio/cio_operator_turns.jsonl` (via S0 module) | PARTIAL |
| Dedicated CIO Telegram bot | user unit `tradeai-cio-telegram.service` → `scripts/cio_telegram_bot.py --loop` | **LIVE** (left as found; this PR adds no producer) |

### 1.3 Identity

| Item | Path / evidence | Status |
|------|-----------------|--------|
| Canonical event identity (join key) | `scripts/lib/cio_canonical_identity.py` (`CanonicalEventIdentity@v1`) | **LIVE library**; used to join research/CIO arcs |
| Subject GUID attach (lookup only) | `scripts/lib/cio_subject_guid.py` | LIVE library |
| Identity registry store | registry id `identity.registry` → `data/runtime/identity_registry.json` | **LIVE** (~10k entities; schema present; MBI=0) |
| Instrument subject keys | `scripts/lib/cio_instrument_record.py` `subject_key()` HELD/EXIT/WATCH/SECTOR/SLEEVE | LIVE on IR rows |
| Envelope identity | `scripts/lib/cio_workflow_envelope.py` `identity_from_payload` | LIVE |

**Measured:** identity node exists (unlike 2026-08-27 “0 files” baseline). Completions improved from 0% → **54%**, but identity alone does not close all loops (goal wakes ≠ security events; evidence gates). See prior verification doc.

### 1.4 Materiality

| Item | Path / evidence | Status |
|------|-----------------|--------|
| Material scan (office) | `scripts/lib/cio_material_scan.py` + `scripts/cio_material_scan.py --live` | **LIVE** (timer ~10 min) |
| Freshness / materiality gate | `scripts/lib/cio_freshness_materiality_gate.py` | LIVE library (acceptance policy; no broker) |
| Financial truth gate | `scripts/lib/cio_financial_truth_gate.py` | LIVE library |
| Holdings delta | `scripts/lib/cio_holdings_delta.py` | LIVE (material scan) |
| Receipt | `data/audit/cio_material_scan_last.json` | LIVE pattern |

### 1.5 Graph impact

| Item | Path / evidence | Status |
|------|-----------------|--------|
| 1-hop held neighbours | `scripts/lib/cio_graph_impact.py` (`CIOGraphImpact@v1`) | PARTIAL (Wave 2 slices 15/16) |
| Held graph impact | `scripts/lib/cio_graph_impact_held.py` | PARTIAL |
| Catalyst graph artifact | `data/cio/catalyst_graph_latest.json` (mtime 2026-08-27) | STALE-ish / not a pipeline stage |

**Not** a universal stage on every event; still a side computation.

### 1.6 Research

| Item | Path / evidence | Status |
|------|-----------------|--------|
| Research need gate | `scripts/lib/cio_research_gate.py` (`ResearchNeedDecision@v2`) | **LIVE library** |
| Free-first layer | `scripts/lib/free_first_refresh.py`, `free_first_circulation.py`, `scripts/free_first_refresh.py` | LIVE code paths |
| Residual web lane | `scripts/lib/cio_residual_web.py` (`ResidualWebLane@v1`; stub default) | LIBRARY / gated |
| Research budget | `scripts/lib/cio_research_budget.py` | LIBRARY |
| Hermes CIO worker | user timer `tradeai-hermes-cio-worker.timer` → `scripts/hermes_cio_worker.py --drain --max 2` | **LIVE** |
| Persistent cognition consumer | `scripts/lib/cio_persistent_cognition.py` | LIVE library |
| Lineage arc A | research → specialist → checkpoint ids on `wf_<digest>` | PARTIAL (436 with checkpoint_id) |

### 1.7 Specialists

| Item | Path / evidence | Status |
|------|-----------------|--------|
| Run worker specialist routing | `scripts/lib/cio_run_worker.py` `_route_specialists` / handoff queue | **LIVE code** on reactive runs |
| SpecialistArtifact@v1-lite | `scripts/lib/cio_specialist_artifact.py` | **LIBRARY + thin store** (2 jsonl rows; `workflow_id=None`) |
| Informal / handoff advisories | `scripts/lib/cio_specialist_artifacts.py` (plural) | LIVE reconstruct path |
| Legacy SpecialistArtifact@v2 jsonl | `data/cio/specialist_artifacts.jsonl` (36 rows) | PARALLEL naming (not v1-lite) |
| Registry | `cio.specialist_artifacts` → `cio_specialist_artifacts.jsonl` | exists |

### 1.8 Council / synthesis

| Item | Path / evidence | Status |
|------|-----------------|--------|
| CIOCouncilSynthesis@v1 (Wave 3B deterministic join) | `scripts/lib/cio_council_synthesis.py` — no model; AGREED/DISPUTED/… | **LIBRARY** |
| InvestmentDecision@v1 (committee envelope) | `scripts/lib/cio_investment_decision.py` + `cio_committee_synthesis.py` | LIBRARY / CIO-lane |
| On-disk `cio_council_synthesis.json` | schema literal `CIOCouncilSynthesis@v1` but **older committee-shaped keys** (no Wave3B `state`); mtime **2026-08-26** | STALE / shape drift |
| Registry `cio.decisions` | path `cio_decisions.jsonl` | **MISSING STORE** |

### 1.9 Product

| Item | Path / evidence | Status |
|------|-----------------|--------|
| CIOOperatorProduct@v1 | `scripts/lib/cio_operator_product.py` | **LIVE** |
| Investment brief / product.current | `cio_investment_brief.json` / registry `cio.product.current` | **LIVE** |
| Desk depth / books | `scripts/lib/cio_desk_depth.py`, `cio_investment_product.py` | **LIVE** |
| Dual reentry labels | `scripts/lib/cio_reentry_surface_labels.py` + `cio_command_center.build_reentry_book_labels` | **LIVE**; home `merged=false` |
| Preconditions board | `scripts/lib/cio_preconditions_board.py` | LIVE library |

### 1.10 Notify

| Item | Path / evidence | Status |
|------|-----------------|--------|
| Notification policy | `scripts/lib/cio_notification_policy.py` (`IMMEDIATE`/`DIGEST`/`COMMAND_CENTER_ONLY`/`SUPPRESSED`) | LIVE library |
| Delivery worker | user timer `tradeai-cio-delivery.timer` → `scripts/cio_delivery_worker.py --once --mode live` | **LIVE** |
| Transport / modes | `scripts/lib/cio_telegram_transport.py`, `cio_delivery_mode.py` | LIVE |
| Audit / metrics | `cio_notification_audit.jsonl`, `cio_notification_metrics.jsonl` | LIVE |
| Registry `notifications.outbox` | | **MISSING STORE** |
| Situation notify bridge | `scripts/lib/cio_situation_notify_bridge.py` | PARTIAL |

**This package:** no notify-on change; no Telegram producer added. INTERDICT left as found on the host.

### 1.11 Outcome

| Item | Path / evidence | Status |
|------|-----------------|--------|
| OutcomeCheckpoint@v1 | `scripts/lib/cio_lineage.py` (`CHECKPOINT_SCHEMA`); `cio.checkpoints` → `outcome_checkpoints.jsonl` | **LIVE** |
| Outcome observer / store | `scripts/lib/cio_outcome_observer.py`, `cio_outcome_store.py` | PARTIAL |
| Lineage completion report | `scripts/cio_lineage_completion_report.py` | **LIVE measure:** 406/752 (54.0%) |
| Lesson bind | `scripts/lib/cio_lesson_bind.py` | LIBRARY; `cio.lesson_binds` **MISSING STORE** |

### 1.12 Cognition

| Item | Path / evidence | Status |
|------|-----------------|--------|
| InstrumentRecord cognition apply | `cio_instrument_record.apply_cognition` — only `next_research_question` / `next_eligible_at` / `notify_priority` / `cc_narrative`; refuses sizing fields | **LIVE library + store** |
| Persistent cognition pack | `scripts/lib/cio_persistent_cognition.py` | LIVE library |
| Nightly reflection | user timer `tradeai-cio-nightly-reflection.timer` | LIVE schedule |
| Learning weekly registry | `learning.weekly` | **MISSING STORE** |
| Feedback dispositions | `cio.feedback` → `decision_dispositions.jsonl` | exists |

**Invariant:** `MBI_BEHAVIOR=0` enforced in IR module; sampled lineage n=200 all `memory_behavior_influence=0`.

### 1.13 Persistence

| Item | Path / evidence | Status |
|------|-----------------|--------|
| CanonicalStoreRegistry@v1 | `scripts/lib/canonical_store_registry.py` — **34** registered stores | **LIVE** |
| Production state root | `production_state_root()` → persistent-state | **LIVE** |
| Instrument records | `cio_instrument_records.jsonl` — **129** rows (HELD 54 / EXIT 72 / SLEEVE 3) | **LIVE** |
| Workflow lineage | `cio_workflow_lineage.jsonl` | **LIVE** |
| Atomic JSON helpers | `scripts/lib/atomic_json_store.py` | LIVE |

---

## 2. Dependency sketch (as-built, not target)

```
[crontab portfolio_orchestrator] ----PARALLEL----> rebalancer/alerts (G-AUTH-01)
        \ (read-only AVOID flag only)

events/cursors ─┐
goals/wakes ────┼─> cio_reactive_cycle / wake_dispatcher ─> cio_run_worker
material_scan ──┘         │
                          ├─ snapshot / evidence gates
                          ├─ research_gate + hermes_cio_worker (free-first / residual)
                          ├─ specialist handoffs ─┬─ SpecialistArtifact@v1-lite (thin)
                          │                      └─ informal specialist_artifacts
                          ├─ committee / InvestmentDecision  OR  council_synthesis join
                          ├─ CIOOperatorProduct + CC home (/api/v3/cio/home)
                          ├─ notification_policy → delivery_worker
                          └─ lineage / OutcomeCheckpoint → (lesson_bind sparse)

InstrumentRecord@v1 ◀── apply_cognition / rehydrate / residual_web / budget
identity.registry   ◀── subject_guid / canonical_identity (event_id join)
```

---

## 3. Wave 3 type live bind (summary)

| Type | Module | On-disk | Universal wake? |
|------|--------|---------|-----------------|
| `InstrumentRecord@v1` | `cio_instrument_record.py` | 129 rows | **No** (G-IR-01) |
| `SpecialistArtifact@v1-lite` | `cio_specialist_artifact.py` | 2 rows | **No** (G-SPEC-01) |
| `CIOCouncilSynthesis@v1` | `cio_council_synthesis.py` | file present but **shape/age drift** vs Wave3B | **No** |

Full naming table: `docs/architecture/cio/EXTERNAL_DIAGRAM_TYPE_MAPPING.md`.

---

## 4. Authority split (re-confirmed G-AUTH-01)

On pin `852ecd47`:

1. `scripts/portfolio_rebalancer.py` still **owns** daily drift order generation via `portfolio_orchestrator.py` (cron `15 7 * * 1-5`).
2. Slice 14 added **read-only** CIO product consult (`scripts/lib/cio_rebalancer_readonly.py`): flags `cio_avoid_contradiction`; **job continues**; **does not execute**; does not require CIO synthesis.
3. `cio_decision_engine.py` cron remains **DISABLED** (2026-08-08) in effective crontab backup.
4. `autonomous_rebalance_planner.py` still not a live CIO-gated replacement.

**Severity lock:** Sev **2 High** (advisory path; MBI=0; no broker write from this job) — platform “CIO is authoritative” claim remains false for the daily rebalance recommendation surface. See gap register.

---

## 5. Dual reentry pipes (G-DUAL-01 reconfirm)

Live `GET /api/v3/cio/home` → `reentry_books`:
- `merged: false`
- `a.surface=A` `former_holdings_reentry` (producer: `cio_investment_product.build_reentry_book`)
- `b.surface=B` `desk_cash_stage_reentry` (producer: `cio_desk_depth.build_reentry_book`)

Labels: `scripts/lib/cio_reentry_surface_labels.py`. Risk is **merge regression**, not current merge. Keep monitored.

---

## 6. What this pack deliberately does not claim

- End-to-end 99.99% lifecycle success (needs P1-WS2 instrumentation + P9).
- That every wake loads InstrumentRecord.
- That SpecialistArtifact@v1-lite is the sole specialist record (v2 informal jsonl still present).
- That CIOCouncilSynthesis Wave3B join is the file written 2026-08-26.
- Remediation or promote (orchestrator-owned).
