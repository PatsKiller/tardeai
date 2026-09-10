# NarrativeSubjectLink@v1 — Architecture

**Status:** Phases 1–5 implemented. Outbound comms (Phase 7) not yet routed.
**Schema version:** `NarrativeSubjectLink@v1`
**Code:** `scripts/lib/cio_narrative_subjects.py` (resolve), `scripts/lib/cio_narrative_write.py` (persist)
**Store:** `narrative_subjects`
**Migration:** `migrations/2026_09_10_narrative_subject_links.sql`
**Standard:** AGENTS.md §13.4 · identifier model §7 · "topics are subjects" §17A

---

## Purpose

Say what a narrative is **about**, for every narrative the system produces, across
every kind of subject — so that "what has the desk concluded about Energy", "what
has this strategy produced", and "what did we already tell the operator about
this name" are answerable questions.

## The cause

Measured 2026-09-10. Fifteen surfaces hold a narrative, thesis, rationale or
summary. One carried identity.

| Surface | Rows | Identity before |
|---|---|---|
| `subject_state_narratives` | 153 | full |
| `agent_recommendation_registry` | 462,902 | none |
| `watchlist_final_synthesis` | 1,184 | none |
| `defense_directive_hits_staging` | 515 | none |
| `rotation_directive_hits_staging` | 109 | none |
| `inference_sizing_recommendations` | 269 | none |
| …nine more | — | none |

The sharpest instance, and the one this contract was proven against:
`material_change_detector.sector_moves()` emits a sector event under a
representative *member* symbol, burying the sector in `evidence`. `persist()`
then resolved identity from that symbol, so **13 of 14 `sector_move` rows carried
a SECURITY guid for a SECTOR event**. "Energy is moving" was stored as a
statement about XOM. §17A already said *"Topics are subjects, not securities…
never give a theme a SECURITY guid"*; nothing enforced it.

## Why a link table

Two reasons, both load-bearing.

**Cardinality.** A defense thesis is about a theme *and* a sector *and* several
securities. `two_way_curation.rotation_signal_to_feedback` returns `None` without
a sector and sets `symbol` only when an ETF proxy exists — rotation is
sector-first *by design*. One `subject_guid` column cannot express that, and
forcing one recreates the `sector_move` defect one table over.

**Safety.** `sql/research_identity_tags.sql` records that `ALTER TABLE … ADD
COLUMN` takes `ACCESS EXCLUSIVE`, and a `taxonomy_tagger` run took a table down
on 2026-07-02. `agent_recommendation_registry` is 462,902 rows behind a live
reader; `watchlist_final_synthesis` has writers every 5–15 minutes. The link
table exists so tagging never takes that lock — **no existing table was
altered**.

This mirrors `document_mentions`, the only many-to-many subject linkage that
already existed, including its role/relationship distinction.

## Shape

```
narrative_subjects
  link_guid        uuid5 "tradeai:narrative_link:{row_guid}|{subject_guid}|{relationship}"
  row_guid         the narrative row's own guid (uuid5 over table+pk if it has none)
  source_table     which of the fifteen
  source_id        that row's native PK
  entity_type      SECURITY | SECTOR | INDUSTRY | THEME | PORTFOLIO | STRATEGY
  subject_guid     registry lookup (SECURITY) or entity_guid (all others)
  semantic_subject human label — 'Energy', 'momentum_scalp'
  relationship     subject | mentioned | from | to | peer
  confidence       CONFIRMED | CANDIDATE | UNKNOWN_LEGACY
  author_agent_id  KNOWN_AGENTS — 'cio'
```

`link_guid` is a pure function of its triple, so replay and re-ingestion are
idempotent by construction; the unique index states the same fact in the database.

## Rules

1. A security guid is **never minted from a name** — registry lookup only.
2. **Canonicalise before minting.** `entity_guid` casefolds but does not
   canonicalise; without `normalize_sector`, "Consumer Cyclical" and "Consumer
   Discretionary" become two sectors and every rollup silently splits.
3. A sector has **no issuer** — `issuer_guid` is NULL on non-security subjects.
4. `author_agent_id` ≠ `issuer_guid`. The latter is the *company*.
5. **Fail-safe, not fail-closed.** A tagging failure leaves the narrative
   persisted and untagged, and reports the miss. An untagged row is degraded; a
   lost one is a blank operator surface. Deliberately opposite to the rest of the
   standard.
6. **Tags, not records.** A link says what text is *about*. It never mints an
   `InstrumentRecord@v1` and never gives a sector a cadence — `INDUSTRY:` /
   `THEME:` remain "SPECIFIED, no producer yet" as records (§13.4).

## Ownership

The CIO owns narrative writes through `cio_narrative_write.write_narrative`.
There is deliberately **no dual-write mode**: for a lane where the CIO takes over
persistence the text is unchanged, so a comparison proves nothing a unit test
does not; for a lane where the CIO *composes*, the text is supposed to differ, so
a comparison gate would fail by design. `composed` is recorded on every write so
an audit can distinguish "tagged" from "actually upgraded".

## Status by lane

| Lane | Tagged | Composed by CIO |
|---|---|---|
| `material_changes` | yes | n/a (detector) |
| `inference_sizing_recommendations` | yes | not yet |
| `defense_directive_hits_staging` | yes | not yet |
| `rotation_directive_hits_staging` | yes | not yet |
| `watchlist_final_synthesis` | yes | not yet |
| `agent_recommendation_registry` | yes | not yet |
| outbound `communication_events` | **no — Phase 7** | no |
| `strategy_lesson_rollup`, `risk_synthesis_results`, `run_summary`, `system_rollup_daily`, `learning_recommendations`, `rec_rotation_links`, `aegis_rotation_candidates`, `advisor_recommendations` | not yet | not yet |
| `watchlist_synthesis_safety_history`, `profit_protection_shadow_recommendations`, `closed_trade_digest_log` | deliberately last — **no reader exists** | no |

## Verification

`tests/test_narrative_subject_identity.py` (15) · `test_sector_move_subject.py` (5)
· `test_narrative_lane_wiring.py` (8) · `test_wake_memory_carryforward.py` (7).
Registered in `run_cio_hardening_ci.py` GATES.
