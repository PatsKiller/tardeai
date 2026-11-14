# Wealth implementation runbook (operator directive 2026-11-14, ~18:20 ET)

Supersedes "build everything" sequencing for apps/wealth. A published preview is not backend proof.
No new grant flow, no GitHub dependency, no release window. Engineering acceptance gate inside sprint authority.

## Frozen reference (step 1)
| item | value |
|---|---|
| Spec | v02 mockup, 118,604 B, sha256 23f96d84199c5a7cabb3837a7bd94fab87d68eed15d3d5bbfb5d07e6f8dde7aa (`docs/wealth/design-reference/`) |
| Preview (FICTIONAL, not the app) | `/wealth/design-reference/index.html`, 119,742 B, sha256 93fc462d…2c763; deploy dir `~/deploy/wealth/releases/preview-20261114T2320Z`, rollback `preview-20261114T2312Z` |
| Shell index (preview link + folder redirect) | sha256 6be05af9…0832 |
| Real app | `apps/wealth` on `wt/wealth-app-20261114` (worktree `/data/worktrees/tradeai-wt-wealth-app`) — scaffold only, no real-data slice wired |
| Server | R13 `3ac0b4058`, `/wealth/*` via `_wealth_resolve` (`scripts/portfolio_server.py`), dist `~/deploy/wealth/current`; rollback R11 `663678405` |
| Register | `docs/wealth/functionality-register.json` — 56 views, 6 drawers, shell (70 rows) |

Status vocabulary for execution: NOT_STARTED · WAITING(holder) · RUNNING(PID,start,progress) · FAILED(reason,rc) · INCOMPLETE(timeout) · PASSED(rc).
Status vocabulary for capability rows: VERIFIED_WORKING · EXISTS_UNVERIFIED · PARTIAL · MISSING · NOT_APPLICABLE (UNMAPPED until the map pass reaches the row).

## Steps per bounded slice
1. Freeze reference, record truth (above).
2. Read-only map: component → endpoint → canonical broker/read-model/library → table/view/product/cache key → actual writer → n8n workflow. Trace what runs. Redact credentials/private ids.
3. Slice contract in `contracts/<slice>@N.md` BEFORE any backend change: fields/types/nullability/units/ids; metric version, session, horizon, TZ; source vs build clocks, lineage, freshness, expiry, failure; read-only vs mutation + auth. P&L kept distinct: session move / unrealized / realized / reconciled period profit (sold holdings, cash flows, income, fees, account scope). S/R needs method+window+source clock; P/E needs governed context. No invented risk scores, sizing or thresholds.
4. Backend evidence, independently reviewed, in `evidence/<slice>/`: valid/missing/partial/stale/unavailable/contradictory/session+account boundaries; fail-before/pass-after; exact commands, identities, rc, skips, baseline failures; GETs proven non-mutating and non-rebuilding; cost/payload/fan-out, cold vs warm; source-clock truth; DB/cache consistency. No live financial actions, no provider probes.
5. One approval packet per slice → operator review. Author ≠ reviewer. Ledger separates AUTHOR CLAIM / INDEPENDENT EVIDENCE / OPERATOR DECISION. Operator decisions: APPROVED_FOR_WIRING(scope, identity) · REWORK(criterion) · UNPROVEN(missing evidence). The lead never records an operator approval it did not receive.
6. REWORK → minimum backend fix: canonical source first, versioned contract, independent review; no rewrite, no test weakening, no invented data, no silent fallback, nothing added to a frozen candidate.
7. Wire faithfully once approved: port v02 HTML/CSS/JS into components + adapters with truthful states. Missing ≠ zero. A "NEEDS BACKEND" placeholder is never acceptance. Semantics annotated at code boundaries.
8. Qualify a small exact candidate: provenance, focused/type/build/contract checks, independent review, immutable evidence; deploy promptly with rollback ready; never mutate an immutable bundle without provenance + receipt.
9. Verify deployed: live URL, identity, observed outputs; account/session changes; row/drawer/export consistency; actions; desktop + phone; CIO history. Each check PASS/FAIL/NOT_TESTED; +15/+30/+60; roll back on material regression.
10. Document as you go: this file, `FUNCTIONALITY-MAP.md`, `contracts/`, `evidence/`, `DECISIONS.md`, owner/route/migration/exception registers. Append-only timestamped receipts; every finding carries owner, reviewer, next action, dependency, evidence link.

## Scheduler + CIO rules
n8n alone owns business scheduling (24/7, session-aware, bounded, idempotent). Producer failure is reported separately from missing/stale data. Automatic receipts, tested recovery. No page-triggered rebuilds. Duplicates retire only after replacement + rollback proven. Exceptions decided by the lead with the reason recorded. Auth, 2FA, orders, broker locks and CIO memory preserved. Reposition follows `BACKLOG-REPOSITION-ADVISORY.md`.

## Order
A. Preserve/link preview; finish R13 postchecks.
B. Holdings/account/session/P&L source contract + retained CIO memory → Portfolio holdings + drawer, Home summary/actions (first real-data slices).
C. Reposition daily/weekly; Watch membership/alerts/levels; Risk, Defense, Re-entry, Income, Performance.
D. Remaining Trade, Intel, Ops, detail, mobile rows.
The app frame may be built against isolated typed fixtures (synthetic, public-repo safe) before backend approval.

## Slice ledger
| slice | owner | reviewer | contract | evidence | independent review | operator decision | exec state |
|---|---|---|---|---|---|---|---|
| A preview publication | lead | operator (live Chrome) | n/a | `$H/PREVIEW-PUBLICATION-RECEIPT-20261114T2320Z.md` | operator receipt | closes preview only | PASSED |
| A shell link + folder redirect (client) | lead | — | n/a | same receipt, update section | none yet | none | deployed, unreviewed |
| A dir-index server fix | cc-opus-3 | cc-deepseek-3 | — | `PATCH-WEALTH-ROUTE-cc-opus-3.patch` | WAITING(-3) | none | next release, not R13 |
| A R13 postchecks | lead | — | — | `r13-postchecks.log` | — | — | RUNNING(task b7nnh3u2o) |
| B Portfolio holdings + drawer | cc-deepseek-6 | cc-deepseek-8 | portfolio-holdings@1 PROPOSED | BEFORE-wealth-api-…2309Z | WAITING(-8) | none | contract open |
| B Home summary/advisory | cc-deepseek-4 | cc-deepseek-3 | home-advisory@1 PROPOSED (patch 80af0c42…) | TRACE-HOME-H1, WEALTH-HOME-ADVISORY-r1 | WAITING(-3) | none | endpoint timing WAITING(lead read auth → granted, see DECISIONS) |
| B CIO memory/history | cc-deepseek-2 | cc-deepseek-9 | cio@1 READY 7409bec4e (unwired) | BEFORE-CIO-INTEL | WAITING(-9) | none | inventory incomplete |
| B valuation (P/E context) | cc-deepseek-8 | cc-deepseek-6 | valuation-assessment@1 PLAN | PLAN/DELTA/REPLY-valuation | -6 REVIEW: emit point CHANGED, 4 edits | none | rework |
| C Watch | cc-deepseek-5 | cc-deepseek-7 | watch@1 PROPOSED | WATCH-BEFORE-MEASUREMENTS | WAITING(-7) | none | contract open |
| C Defense/Reposition | cc-deepseek-7 | cc-deepseek-5 | RepositionDaily@1/Weekly@1 (backlog) | MEASURE-DEFENSE-REDEPLOY | -5 accepts F1–F9 with changes | none | R1 audit next |
| D Ops/perf | cc-deepseek-9 | cc-deepseek-2 | ops@1 §8.4 HOLD | TRACE-WEALTH-BOTTLENECKS | — | none | re-measure on R13 |
| shell frame (fixtures) | cc-opus-3 | cc-deepseek-3 | — | ADDENDUM-WEALTH-SHELL-SCOPE | — | none | RUNNING |
| ADMIN modal (LEAN: Connections · Essential settings) — REQUIRED PARITY | cc-deepseek-9 | cc-deepseek-2 | admin@1 SCOPED | lead pass 1 in contracts/admin@1.md | WAITING(-9 audit) | none | NOT_STARTED (queued) |
| ADMIN visual reference | cc-opus-3 | cc-deepseek-3 | v02 tokens | — | — | none | NOT_STARTED (after shell) |
