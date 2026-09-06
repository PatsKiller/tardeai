# Mentions: scheduling, retention, and who decides relevance

**Status:** design + shipped 2026-09-06 · **Authority:** READ_ONLY_ADVISORY · **Financial action:** none

Companion to `DOCUMENT_MENTIONS_AND_LLM_ESCALATION.md`, which defines the table and the
subject/mentioned split. This one covers what happens to those rows over time.

---

## 1. Three gaps, measured

`document_mentions` shipped with 40,594 rows and **none of the following**:

| gap | state before this document |
|---|---|
| new documents get tagged | **nothing scheduled** — the extractor ran once, by hand |
| mentions expire | **no retention policy at all** |
| existing retention runs | `db_retention.py` scheduled **nowhere** (0 cron, 0 timers) |

The second is a defect I introduced on the same day I wrote *"every suppression needs a shelf
life"* into AGENTS.md. A table that only grows is the same failure in a different direction: it
does not mislead, it just becomes unusable and expensive, and nobody notices until it is large.

The third was already reported by the integrity sweep as
`producer_unscheduled: db_retention.py` — the policies for `news_articles`, `catalyst_events`,
`research_insights` and `sec_form4` all exist and none of them has ever run.

## 2. Is there a librarian for this? No — and it is the wrong tool

`hermes_autonomous_librarian_backlog_loop` reviews four things:
`backtest_weak_strategy`, `catalyst_quality_gap`, `screener_underfilled`,
`stale_source_discovery`. Research backlog findings. **It does not look at mentions and should
not.**

## 3. Does an LLM decide how long to keep a mention? No.

**A mention has no independent lifetime.** It is a derived fact about a document:

> this document mentions this issuer, in this role

Its relevance is entirely the document's relevance. So:

- **if the source document is purged, its mentions MUST go** — that is referential integrity, not
  judgment. An orphaned mention points at a `source_id` that no longer exists and will silently
  return nothing, or worse, match a recycled id.
- **while the document is retained, its mentions are exactly as relevant as it is.**

Asking a model *"is this 90-day-old mention still relevant?"* forty thousand times is expensive,
non-deterministic, and answers a question a foreign key already answers. **The date rule is not an
approximation of the judgment — it IS the judgment**, because the mention has no life of its own.

### Where judgment does belong — and it already exists

Deciding whether a **document** is worth keeping past its normal window is genuine curation, and
this system already does it at the document level: `hermes_external_research.usefulness_score`
and `learning_candidate`, `news_articles.deep_curation_verdict` and `retirement_relevance`.

That is the right layer. Curate the document; the mentions follow. Adding a second, model-driven
opinion at the mention layer would let a mention outlive the document it describes, which is
incoherent.

## 4. The design

```
   hourly   backfill_document_mentions --all --apply --limit N
              │  incremental by construction: the query already excludes
              │  source_ids already present, so a re-run is cheap and a
              │  missed hour self-heals on the next one
              ▼
   daily    prune_document_mentions --apply
              ├─ ORPHANS: source_id no longer in the source table   -> delete
              └─ AGED:    older than the SOURCE table's own retention -> delete
```

**Retention is inherited, never invented.** `MENTION_RETENTION` reads the same 90-day windows
`db_retention.py` already declares for each source table, so the two can never disagree. A source
whose retention changes changes its mentions' retention automatically.

**Deleting an orphan is not the "never delete" rule.** AGENTS.md forbids deleting authoritative
state without a tripwire. A mention row is a **derived projection**: it can be rebuilt from the
source document by re-running the extractor, and once the document is gone the row is not
evidence of anything — it is a dangling pointer. The archive-with-tripwire rule protects
irreplaceable state, and this is the opposite of irreplaceable.

**Dry run is the default.** `--apply` is required, and the pruner reports what it *would* remove.

## 5. What could go wrong, and what stops it

| risk | guard |
|---|---|
| pruner deletes rows whose source still exists | orphan check is an explicit `NOT EXISTS` against the source table, tested |
| retention drifts from the source tables' | windows are READ from `db_retention.DEFAULT_POLICIES`, not copied |
| extractor re-tags the same document forever | the query excludes `source_id`s already in `document_mentions`; `ON CONFLICT DO NOTHING` on the unique index |
| a scheduled run silently produces nothing | it reports `rows_produced` through `PipelineRun`, so `pipeline_zero_rows` can see it — the metric fixed earlier today |
| the pruner runs before the extractor and races | different schedules (hourly vs daily) and both are idempotent |

## 6. Guardrails for anyone extending this

- **Never give a mention a lifetime longer than its document.** If you find yourself wanting to,
  the document's retention is what should change.
- **Never add a model to the pruner.** If the question is "is this document still worth keeping",
  that belongs at the document layer where curation already lives.
- **A new source goes in `SOURCES` and gets a retention window in the same change.** A source
  added without one inherits the default and grows unbounded.
