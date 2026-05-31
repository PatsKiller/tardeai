# MASTER Rewrite and Architecture Consolidation Report

**Date:** 2026-05-31
**Status:** COMPLETE

## Files Rewritten
- `docs/MASTER_SYSTEM_DOCUMENTATION.md` — 50+ corrections applied

## Files Archived
- `docs/ARCHITECTURE_OVERVIEW.md` — marked ARCHIVED, copy in `docs/_archive/2026-05-31_master_rewrite/`
- `docs/project/SYSTEM_ARCHITECTURE_COMPLETE.md` — marked ARCHIVED, copy in `docs/_archive/2026-05-31_master_rewrite/`

## Major Corrections
| Category | Before | After | Count |
|----------|--------|-------|-------|
| Model routing | qwen3:14b throughout | gemma3:12b (with context) | 39 refs fixed |
| Strategy count | 20/23 mixed | 24 | 6 refs fixed |
| Portfolio value | $1.19M hardcoded | "see dashboard" pointer | 1 fix |
| Page count | 43-page | 70+ page | 1 fix |
| LLM fallback | 3-provider chain | local-first routing | 1 fix |
| Document version | 2026-05-11 | 2026-05-31 | 1 fix |
| STALE WARNING | Present | Removed (rewrite done) | 1 block |
| Hermes section | Missing | Added (Section 18b) | New |
| Beelink | Not found | N/A | 0 |

## Hermes Pointer Added
Section 18b: "Hermes Sidecar — Advisory Challenger and Memory Layer"
Covers: sidecar status, gateway, staging tables, promoted cache, autonomous timer, kill switch, dashboard pages.

## Unresolved Items
- Multi-tier trade review still references gemma3:27b → gpt-4o → Claude (correct for review tiers, not changed)
- Overnight model references to gemma3-overnight remain correct
- Some detailed pipeline stage descriptions may need refresh in future pass
- Table/cron/page counts should use live pointers where possible (partially done)

## Safety
| Item | Status |
|------|--------|
| Code changes | ZERO |
| DB writes | ZERO |
| .env changes | ZERO |
| Model routing changes | ZERO |
| Timer/service changes | ZERO |
