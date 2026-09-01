# Trade AI Command Center v2 -- UI/UX Design Handoff Package

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25 (Memorial Day)
Baseline commit: `8e938dca` on `main`
Server: `http://127.0.0.1:7777/v2/`

---

## Package Contents

### Core Documentation
| File | Purpose |
|------|---------|
| ALL_V2_ROUTE_MAP.md | Complete route inventory: 55 active routes, 25+ legacy redirects |
| API_CONTRACTS_AND_PAYLOADS.md | API endpoint mapping per page, envelope format, POST endpoints |
| COMPONENT_INVENTORY.md | All shared components, sub-components, hooks, libs |
| DESIGN_TOKENS_CURRENT.md | Full CSS token documentation: colors, typography, spacing, shadows |
| NAVIGATION_REDESIGN_REVIEW.md | Current nav structure + proposed restructuring |

### Audit & Analysis
| File | Purpose |
|------|---------|
| DUPLICATE_AND_OVERLAP_AUDIT.md | Route conflicts, shared APIs, nav overlaps, dead code |
| PAGE_FAMILY_CONSOLIDATION_REVIEW.md | Consolidation candidates and impact matrix |
| OPS_PIPELINE_HEALTH_REVIEW.md | Deep review of the 4 ops/pipeline/health pages |
| GOVERNANCE_TRADEAI_PROSPECTS_REVIEW.md | Review of governance + misplaced trading pages |
| SELF_IMPROVEMENT_PAGE_ENHANCEMENT_NOTES.md | Enhancement-only notes (operator says page is good) |

### Implementation Guidance
| File | Purpose |
|------|---------|
| UX_ISSUES_OBSERVED.md | 17 issues ranked by severity |
| IMPLEMENTATION_CONSTRAINTS.md | Architecture constraints, non-negotiable rules |
| REDESIGN_TARGETS.md | Prioritized redesign targets with risk ratings |

### Backups & References
| File | Purpose |
|------|---------|
| SCREENSHOT_INDEX.md | Screenshot checklist (Playwright unavailable) |
| backups/git_info.txt | Git state at backup time |
| backups/pre_redesign_source_backup_20260525.tgz | Full source backup |
| samples/ | 17 API response samples (JSON) |
| source_snapshot/ | Key source files preserved |

---

## Key Findings Summary

1. **55 active routes, 25+ legacy redirects** -- considerable route surface
2. **Admin nav group has 17 items** -- highest priority UX fix
3. **`/alerts` route defined twice** -- dead code / potential bug
4. **Trade AI and Prospects are misplaced** in Admin instead of Trading group
5. **4 overlapping system monitoring pages** -- consolidation opportunity
6. **Overview page makes 18 API calls** -- performance concern
7. **api_v2.py is 18,000+ lines** -- monolith backend
8. **8 hub pages already use TabPage pattern** -- proven consolidation approach
9. **Design tokens exist but are inconsistently used** -- hardcoded hex in pages
10. **No search/command palette** -- 55+ routes require dropdown navigation

## Quick Start for Redesigners

1. Read `ALL_V2_ROUTE_MAP.md` for the full picture
2. Read `NAVIGATION_REDESIGN_REVIEW.md` for the nav proposal
3. Read `REDESIGN_TARGETS.md` for prioritized work
4. Check `DESIGN_TOKENS_CURRENT.md` for the color/type system
5. Review `samples/` for API payload shapes
6. Use `source_snapshot/` as reference code
