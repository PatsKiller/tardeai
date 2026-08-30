# P9 — Registry / orphan scan / lifecycle path toward 99.99%

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0  
**INTERDICT:** left as found  
**Rails:** never_auto_remediate `store_consistency` · Do NOT promote from this package alone  

---

## 1. Purpose

Phase 9 of the CIO Platform Diligence master plan:

> Exit gate: every sampled object has registry id; duplicate-id / concurrency / failover / recovery tests documented; orphan scan = 0 for production window.  
> KPI: move lifecycle success from measured baseline toward **99.99%** with dead-letter + replay.

This package delivers the **measurement tool**, a **bounded-window orphan census**, and a **design-only** path from today’s lineage completion to 99.99%. It does **not** silently repair stores.

---

## 2. Tooling

| Artifact | Path |
|----------|------|
| Orphan census CLI | `scripts/cio_registry_orphan_census.py` (`--json`, `--days`, `--root`) |
| Lineage baseline (integrated) | `scripts/cio_lineage_completion_report.py` via `scripts.lib.cio_lineage_health.completion_report` |
| Registry contract | `scripts/lib/canonical_store_registry.py` (`CanonicalStoreRegistry@v1`) |
| Tests (tmp fixtures) | `tests/test_cio_registry_orphan_census.py` |

Fail-soft: missing stores, bad JSON lines, and unsupported formats are reported per-store; the census never aborts the run and never writes.

---

## 3. Live orphan census (pin context `852ecd47` / persistent-state)

Command:

```bash
python scripts/cio_registry_orphan_census.py --json --days 30
```

### Headline (30-day window)

| Metric | Value |
|--------|-------|
| stores_present / scanned | **9 / 12** |
| missing_cross_id_hits | **144** |
| orphan_hits | **3** |
| lineage complete_to_checkpoint | **406 / 752 (54.0%)** |
| lineage arcs | research_checkpoint **436** · cio_notification **29** |

### Missing cross-ids (folded latest-per-primary)

| Store.field | Hits |
|-------------|------|
| `cio.workflow_lineage.event_id` | 142 |
| `cio.specialist_artifacts.workflow_id` | 2 |

### Orphan edges

| Edge | Hits | Notes |
|------|------|-------|
| `cio.specialist_artifacts.null_workflow_id` | 2 | Wave 3B critique artifacts stamped `research_id`/`plan_id` but not `workflow_id` |
| `cio.delivery_receipts.notification_id→notification_id` | 1 | Receipt `ntf_*` not present on lineage / notification audit hub in window |

### Absent producers (not orphans — PRODUCER_NOT_RUN)

`cio.notification_policy`, `cio.lesson_binds`, and (depending on root) other registered stores with no file yet. Counted as absent, not as orphans.

### Index sizes (hub)

workflow_id 752 · event_id 299 · checkpoint_id 741 · notification_id 4990

---

## 4. Lineage baseline (G-LOOP-01)

`cio_lineage_completion_report.py` remains the authoritative completion gauge:

```
workflows                752
complete_to_checkpoint   406  (54.0%)
with checkpoint_id       436
arcs                     research_checkpoint=436  cio_notification=29
first open stage         research=640  cio=112
```

P9 does **not** claim identity-fork merge or completion repair. The census **embeds** this baseline so orphan work and lifecycle KPI share one evidence surface.

Do **not** claim 99.99% until instrumentation (P1-WS2) + hardening path (this doc §6) are both live **and** measured.

---

## 5. Concurrency / failover — design notes (no code change)

These are design contracts for a later implementation package. P9 records them only.

### 5.1 Writers

| Concern | Design |
|---------|--------|
| Append-only jsonl | Single-writer flock per path; readers tolerate torn last lines (fail-soft skip) |
| Current projections | Atomic replace (`*.tmp` + `os.replace`); readers treat missing/partial as `PRODUCER_NOT_RUN` / `INVALID_SCHEMA` |
| Duplicate ids | Mint with content-addressed or ULID ids; census flags duplicate primary keys as a **finding class** (future); never auto-delete |
| Cross-store commit | No distributed transaction. Emit satellite rows only after hub id is durable; otherwise dead-letter the satellite intent |

### 5.2 Failover / recovery

| Concern | Design |
|---------|--------|
| Process crash mid-pipeline | Stage status stays `NOT_YET_CREATED` / prior stage; replay from last durable hub id |
| Host failover | Persistent-state root is the authority; overlay/CURRENT must resolve via `CanonicalStoreRegistry.resolve_store` |
| Split brain (two writers) | Ownership_class + writer field in registry; second writer is a Sev-1 gap, not a merge |
| Read replica lag | Census and completion report always read the persistent-state root, never a cache |

### 5.3 never_auto_remediate

Store consistency repairs (delete orphan, mint missing event_id, join identity arcs) require an **operator-authorized** remediation package with dry-run + pin. This census is advisory only.

---

## 6. Path from 54% → 99.99% (dead-letter + replay; no silent auto-fix)

### 6.1 KPI definition

**Lifecycle success** = fraction of workflows (or events, once identity is unified) for which `is_complete_to_checkpoint` is true — checkpoint COMPLETED **and** notification stage settled on one envelope.

Today: **54.0%** (406/752). Target program KPI: **99.99%** over a defined production window (recommend: rolling 30d after identity unification).

### 6.2 Gap decomposition (why not 99.99% today)

1. **Identity fragmentation (dominant structural risk):** research/checkpoint arc (`wf_` digest) vs CIO/notification arc (run UUID). Completion needs both halves on one id — see `cio_lineage_health` docstring.  
2. **Missing `event_id`:** 142 / 752 latest envelopes lack `event_id`, so event-level coverage metrics under-count.  
3. **Satellite orphans:** specialist artifacts without `workflow_id`; receipt whose notification id is not on the hub.  
4. **Stage stalls:** first-open stage still research-heavy (640) / cio (112).

### 6.3 Phased path (design)

| Phase | Action | Success signal | Auto-fix? |
|-------|--------|----------------|------------|
| A | **Instrument** P1-WS2 lifecycle census + keep P9 orphan census in CI/cron (`--json`) | Daily orphan_hits + missing_cross_id trend | No |
| B | **Identity decision** (architecture): single workflow_id authority; stamp `event_id` at mint | `identity_fork_suspected=false` sustained; event_id fill → ~100% new rows | No silent merge of historical arcs |
| C | **Dead-letter queue** (new store, APPEND_ONLY_EVIDENCE): rows that fail cross-id validation land here with reason codes (`NULL_WORKFLOW_ID`, `UNKNOWN_NOTIFICATION_ID`, `MISSING_EVENT_ID`, …) | DLQ depth visible on control plane | Enqueue only — never mutate source |
| D | **Replay workers** (operator-gated): re-stamp / re-emit from DLQ with explicit allowlist; dry-run default | DLQ drain rate; orphan_hits → 0 on new window | Replay is explicit; no silent rewrite |
| E | **Hard gate:** `--fail-on-orphan` (future flag) + lineage `--fail-on-finding` in CI for production window | orphan_hits=0 ∧ completion_rate ≥ threshold ramp (90% → 99% → 99.99%) | Gate fails closed |

### 6.4 Ramp (suggested, not claimed)

| Milestone | Completion rate | Orphan hits (30d) | Gate |
|-----------|-----------------|-------------------|------|
| Now (P9 measure) | 54.0% | 3 | advisory |
| Post identity unify (new traffic) | ≥ 90% | 0 on new rows | warn |
| Hardened window | ≥ 99% | 0 | CI warn |
| Program target | ≥ 99.99% | 0 | CI fail |

Historical backfill of forked arcs is a **separate, operator-authorized** project — not implied by this PR.

---

## 7. Evidence standard

Two of: doc claim · code path · live measure — satisfied here by:

1. Doc: this file + master plan Phase 9  
2. Code: `cio_registry_orphan_census.py` + registry + lineage health  
3. Live: §3 census numbers + embedded lineage baseline 54.0%

---

## 8. Out of scope / forbidden in this package

- Promoting exact-main / notify-on / broker writes  
- Silent delete or rewrite of store rows  
- Claiming 99.99% achieved  
- Merging identity arcs without an architecture decision package  
- Raising MBI_BEHAVIOR above 0  

---

## 9. Scoreboard / gap updates

- Scoreboard package **P9 → DONE** (this PR; sha/PR filled on merge)  
- Gap **G-LOOP-01** updated with orphan census evidence; remains **OPEN** until 99.99% path phases A–E land  
- Ops note: `docs/ops/CIO_DILIGENCE_P9_REGISTRY_LIFECYCLE_2026-08-30.md`  
