# Hermes Phase 21A — Librarian Dry-Run Design

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Purpose

Define the checks the Hermes Librarian runs over staged sources, promoted advisory cache, and advisory communications in dry-run mode (file output only, zero DB writes).

---

## Librarian Check Catalog

### Source Quality Checks

| Check | ID | Description |
|-------|----|-------------|
| Duplicate source | DUP-1 | Same URL or topic already in hermes_research_intelligence |
| Stale source | STALE-1 | Source older than 90 days or freshness_date > 90 days ago |
| Low-quality source | QUAL-1 | confidence_score < 0.3 or evidence_json empty |
| Missing evidence | EVID-1 | evidence_json is empty array or lacks substantive content |
| Missing source URL | URL-1 | source_urls_json is empty for source_discovery type |

### Advisory Quality Checks

| Check | ID | Description |
|-------|----|-------------|
| Weak/vague recommendation | VAGUE-1 | Summary lacks specific action or named candidates |
| Missing actionability block | ACT-1 | Per HERMES_ADVISORY_ACTIONABILITY_STANDARD.md |
| Missing ticker/fund/sector examples | TICK-1 | No named candidates when recommending action |
| Missing funding source | FUND-1 | Recommends rebalance without naming what to trim |
| Missing account location | ACCT-1 | No taxable/IRA/Roth guidance |
| Missing risk/tax tradeoff | RISK-1 | Action without risk assessment |
| Missing income impact estimate | INC-1 | Income recommendation without yield projection |
| Unsupported income claim | INC-2 | Income projection without data |
| Unsupported tax claim | TAX-1 | Tax impact claim without analysis |

### Curation Decision Checks

| Check | ID | Description |
|-------|----|-------------|
| Candidate for research backlog | BKL-1 | Needs more research before action |
| Candidate for embedding | EMB-1 | High-quality, unique, would improve RAG |
| Candidate for rejection/archive | REJ-1 | Low value, duplicate, or stale |
| Candidate for promotion review | PRO-1 | High-quality staged row ready for promotion |

---

## Input Sources

| Source | Type | Count |
|--------|------|-------|
| hermes_research_intelligence (all rows) | DB read | 18 |
| llm_intelligence_cache hermes sections | DB read | 10 |
| hermes_promotion_audit | DB read | 10 |
| Telegram fixture text | File | 1 |
| Phase 20 actionability standard | File | 1 |

## Output Format

All outputs to `docs/hermes/phase21_librarian_dryrun/`:

| File | Content |
|------|---------|
| librarian_findings.json | All findings with check ID, severity, details |
| duplicate_sources.json | Duplicate detection results |
| stale_or_weak_sources.json | Stale or low-quality rows |
| research_backlog_candidates.json | Items needing more research |
| embedding_candidates_dryrun.json | Items suitable for future embedding |
| rejected_or_archive_candidates.json | Items to reject or archive |
| dry_run_summary.md | Human-readable summary |

## Constraints

- DB writes: ZERO
- Embeddings: ZERO
- Promotions: ZERO
- Max reviewed records: 20
