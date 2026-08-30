# P3 — InstrumentRecord@v1 persistence & versioning drills

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0 (enforced)  
**Pin / base:** `852ecd47` (origin/main at branch cut)  
**Branch:** `feat/cio-diligence-p3-instrument-record`  
**Reuse:** `scripts/lib/cio_instrument_record.py`, `scripts/lib/instrument_record.py`, `scripts/cio_migrate_instrument_records.py`, Wave 3A–C docs  

Do **not** promote from this package. Diligence only.

---

## 1. Field checklist vs diagram / master plan

Master plan Phase 3 validate list vs cognition store (`new_record` / JSONL) and CC adapter (`instrument_record.py`):

| Diagram / plan field | Cognition store (`cio_instrument_record`) | CC adapter (`instrument_record.py`) | Status |
|----------------------|-------------------------------------------|-------------------------------------|--------|
| `subject_key` | `subject_key` / `kind`+symbols | derived `HELD:`+`symbol` on persist bridge | **Present** |
| thesis | `thesis_ref` + `cc_narrative.thesis_fit` / `.what` | `thesis` | **Present** (ref + narrative slice) |
| narrative | `cc_narrative` | `cc_narrative` | **Present** |
| research | *(not a first-class list on cognition row)* | `research` / `research_ids` | **Adapter only** — cognition store points via questions / artifact id |
| artifacts | `last_artifact_id` (singular) | `artifact_ids` (list) | **Partial** — tip pointer vs multi-id list |
| lessons | `lessons[]` (support_only, applied_to=cognition) | `lessons` / `lesson_ids` | **Present** |
| analyst | `hashes.analyst` | `analyst` | **Hash on store; value on adapter** |
| earnings date | `hashes.earnings` | `earnings_next` | **Hash on store; date on adapter** |
| `next_eligible_at` | `next_eligible_at` | `next_eligible_at` | **Present** |
| priority | `notify_priority` ∈ {none,cc,digest,immediate_candidate} | `notify_priority` | **Present** |
| operator_turns | `last_operator_turn` (singular) | `operator_turns` / `operator_turn_ids` | **Partial** — tip pointer vs history list |

**Envelope (always stamped on upsert):** `schema=InstrumentRecord@v1`, `authority=READ_ONLY_ADVISORY`, `memory_behavior_influence=0`, `memory_cognition_influence=1`.

**Diagram mapping note:** `docs/architecture/cio/EXTERNAL_DIAGRAM_TYPE_MAPPING.md` (Aug 27) predates Wave 3 and does not yet list `InstrumentRecord@v1`. Gap register already marks L7 mapping closed for Wave 3 types in spirit; P1-WS1 should add the literal row. Code + registry entry `cio.instrument_records` are the as-built truth for this package.

---

## 2. Persistence model

- **Store:** append-only JSONL at `data/cio/cio_instrument_records.jsonl` (registry id `cio.instrument_records`).
- **Projection:** last complete JSON object per `subject_key`.
- **History:** every upsert is a new line; `InstrumentRecordStore.history(key)` returns file-order versions.
- **Rollback:** re-append a prior version as the new tip via `InstrumentRecordStore.rollback(key, to_index=…)` — never rewrite or delete lines.
- **Partial write:** incomplete final lines fail `json.loads` and are skipped; prior tip remains.
- **Cold-start / restart:** a new `InstrumentRecordStore(path)` with empty cache reloads from disk.

MBI split: `apply_cognition` raises `BehaviorWriteRefused` on any behavior field (`recommended_delta_usd`, `size_usd`, `shares`, `qty`, `order`, `stop`, `limit`, `target_weight_pct`, `trade`, `execution`).

---

## 3. tmp_path drill results (2026-08-30)

Executed via in-process drill and `scripts/cio_instrument_record_drill.py --tmp` (no live mutation).

| Drill | Result | Evidence |
|-------|--------|----------|
| Cold-start reload | **PASS** | New store instance loads tip `thesis_ref` / narrative unchanged |
| Restart projection | **PASS** | N appends → `all()` length 1; history length N |
| Append version | **PASS** | Two complete lines; tip = latest cognition |
| Recover prior thesis summary | **PASS** | `thesis_summary(history[0])` returns prior `thesis_ref` + `what` |
| Rollback path | **PASS** | `rollback(to_index=0)` re-appends prior; tip restored; history length +1 |
| Partial-write recovery | **PASS** | Truncated JSON line ignored; tip stays prior complete row |
| Refuse MBI behavior fields | **PASS** | All `BEHAVIOR_FIELDS` raise `BehaviorWriteRefused` |

Zero loss of complete prior versions under tmp crash simulation.

---

## 4. Live overlay (read-only inspection)

Path: `/home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_instrument_records.jsonl`  
*(CURRENT release `852ecd47` symlinks host `data/` → persistent-state.)*

| Metric | Value |
|--------|------:|
| JSONL rows | 129 |
| Distinct `subject_key` | 40 |
| Subjects with >1 version | 40 |
| Kinds (row counts) | HELD 54 · EXIT 72 · SLEEVE 3 |
| `memory_behavior_influence` | {0} only |
| Schema | `InstrumentRecord@v1` only |

Example: `HELD:SCHD` has 6 append versions; prior defer narrative / `thesis_ref=desk@v5` remains recoverable from earlier lines while tip carries the latest research question.

**Not mutated** by this package.

---

## 5. Version / rollback path (operator)

```text
1. Inspect:  store.history("HELD:SCHD")          # oldest → newest
2. Summarize: thesis_summary(version_row)        # thesis_ref / what / thesis_fit
3. Roll tip:  store.rollback("HELD:SCHD", to_index=k)
              # appends a copy of history[k] as new tip; history preserved
4. Verify:    InstrumentRecordStore(path).load(...)  # cold reader
```

CLI dry: `python3 scripts/cio_instrument_record_drill.py --tmp [--live-ro]`.

Migration seed (existing, dry default): `python3 scripts/cio_migrate_instrument_records.py`.

---

## 6. Gap impact — G-IR-01

| Before | After P3 |
|--------|----------|
| Library present; persistence unproven under diligence drills | **Persistence, cold-start, partial-write, version/rollback proven on tmp**; live census shows multi-version subjects already in overlay |
| Universal wake load still incomplete | **Still open** — many producers may side-store; P5/P9 own universality / orphan path |

G-IR-01 severity stays **2**; evidence updated. Do not close until wake-path universality is measured.

---

## 7. Tests / artifacts

| Artifact | Path |
|----------|------|
| Diligence tests | `tests/test_cio_diligence_p3_instrument_record.py` |
| Drill CLI | `scripts/cio_instrument_record_drill.py` |
| History/rollback helpers | `InstrumentRecordStore.history` / `.rollback`, `thesis_summary` in `cio_instrument_record.py` |
| Ops note | `docs/ops/CIO_DILIGENCE_P3_2026-08-30.md` |

Existing unit suite `tests/test_cio_instrument_record.py` remains the MBI/cognition contract; P3 adds persistence/version drills only.
