# TradeAI migration reconciliation

Status: DRAFT — local source and evidence package; additional cutover BLOCKED
Owner: platform integrator; per-process owners remain declared, unconfirmed
as_of: 2026-10-12T03:07:00+00:00
Measured at: source base 40208881dd34495b840bcbd4e373f593d06a659f; observed CURRENT 37752b193-main-exact-phase2-20261011-201624

The authoritative workbook retains 679 inventory rows, including 262 rows classified for refactoring or custom development. Historical migration labels, implementation annotations and planning records remain evidence with their original scope. They do not establish production acceptance. Additional cutover remains blocked until the applicable source, deployment, natural schedule, output, monitoring and recovery requirements pass.

## Workbook reconciliation

`scripts/reconcile_migration_inventory.py` adds a closure dashboard, one closure record for every original inventory row, the 262 modification targets, a requirement matrix, an exact-ID process crosswalk and drift findings. It appends structured fields to Inventory and acceptance fields to Cutover_Tracker. Original values, styles, links, comments, lifecycle labels and operator decisions remain intact. Tracker retains its original snapshot and appends the new status partition.

Primary status follows the reviewed evidence: Completed requires all applicable closure proofs; explicit dated decisions become Deferred; current named authority, ownership or mapping boundaries become Blocked; historical implementation or lifecycle work becomes In Progress; other required work remains Not Started. This review accepts no process as Completed on free-text assertions. Contract REVIEWED is a declaration whose provenance and runtime application still need acceptance.

Unclassified rows retain uncertain applicability. A retained scheduler can make n8n contract and cutover requirements inapplicable with an explicit reason; it still needs production output, schedule, notification and recovery proof. Requirement coverage measures checklist evidence only. Inventory closure, accepted refactors and production readiness stay separate and retain NOT_MEASURED where acceptance is absent. Zero verified completions under the new contract is a lower bound, not an assertion that no process works.

Only exact `registry_row` IDs map automatically. Several scheduler rows may represent one lane, and one stage may cover several business processes. Missing IDs, inherited owners and parent relationships stay unresolved; they never increase the denominator automatically. The canonical business-process denominator remains NOT_MEASURED until aliases, OpenClaw exclusions and stage coverage are reviewed.

The source-work crosswalk reproduces 116 wave target rows, 60 Completion119 target rows, and 153 combined targets after overlap. Another 48 targets appear only in the code-only planning list. That leaves 109 without wave/Completion119 metadata and 61 without those records or planning metadata. Every modification target has a collection or owner action; none is automatically accepted as refactored.

The adapter reads explicitly named workbook and source files, performs no host probes, loads no environment file and changes no runtime scheduling or contract review authority. Preview is the default:

```bash
python scripts/reconcile_migration_inventory.py \
  --workbook /path/to/CRON_INVENTORY_LATEST.xlsx \
  --inventory-dir /path/to/cron-inventory \
  --source-root /path/to/integrated-worktree \
  --source-sha FULL_INTEGRATED_SHA \
  --deployed-sha FULL_OBSERVED_CURRENT_SHA \
  --output /path/to/reconciliation-evidence
```

Publication adds `--apply --expected-sha INSPECTED_WORKBOOK_SHA256`. It creates an exclusive exact-byte backup, verifies the candidate retains protected cells after round-trip serialization, and refuses publication if the original workbook changed during preparation. Preview/candidate files remain available for review. Regenerating only the older `build_workbook.py` omits the closure review; run this adapter afterwards using the freshly inspected workbook hash. Per-review evidence contains the source-input hashes and publication receipt.

Pre-build search found `n8n_migration_board.py` for lane lifecycle, `n8n_cutover_checklist.py` for cutover evidence, and the existing external `source_tracking.py` workbook annotation mechanism. None owns the inventory-level acceptance partition or full requirement crosswalk. This adapter extends the existing workbook rather than introducing another runtime tracker, scheduled job or production store.

## Source fixes

The runner integration preserves the current main safety, environment and dry-run behavior. It retains all parallel worker PIDs for individual exit accounting and records expected step count, receipt completeness and worker failure. Missing, duplicate or foreign receipts cannot become a healthy live summary. Durable receipt-write failures return a failing stage exit while allowing remaining business steps to finish. Ordinary child failure and timeout keep existing main semantics pending owner decisions.

Runner regression fixtures copy the required Bash/Python source into scratch projects with minimal environments, isolated homes, state, locks and interpreters. Synthetic assignment-position fixtures replace the host-only C1 snapshot dependency and skipped test. Production access barriers remain enabled.

The cutover checklist requires an exact integrated SHA and a correlated acceptance packet before it ticks natural shadow/canary/output proof. Two distinct natural shadow slots must follow the fixes and match the host receipt, ledger request, n8n schedule trigger, legacy authority, disjoint shadow lock, zero business effects and independently inspected outputs. Manual canaries remain labelled MANUAL_CANARY and cannot substitute for natural fires. Locks alone cannot establish absence of duplicate business effects. Wrong SHA, stale observations, incomplete receipt accounting and conflicting evidence fail acceptance.

The packet interface is documented in `scripts/n8n_cutover_checklist.py`; it is a read-only observation input, never a producer of natural evidence or an operational grant. Per-run effect observations live below `data/runtime` and name the lane/run/SHA. Their contents must come from output and consumer inspection. Synthetic test packets establish gate behavior only.

YouTube cookie classification recognizes Netscape `#HttpOnly_` domain prefixes through a pure name parser. Its regression uses synthetic text and does not inspect cookie files, credentials or model routes.

## Operational boundaries and remaining work

The runtime/contract packet under `reconciliation-20261012/runtime-contracts/` records sanitized observations, external DRAFT contract proposals, owner decisions, nine incomplete source pairs, monitoring requirements and OpenClaw mappings. It prepares exact operator change packets for n8n privilege hardening and Ollama retirement. Four UNKNOWN contract fields have source-backed proposed replacements; no reviewer is invented or advanced.

Hermes is currently inactive with a successful exit; its earlier failed snapshot remains historical. An empty current queue does not prove recovery of historical failed work, and a restart has no current justification. Ollama still running is retirement drift; an instantaneous socket census cannot close periodic caller dependencies. The n8n database role remains overprivileged; historical backup/restore receipts do not replace a fresh prechange backup or an application-role migration test.

No source commit in this package is pushed, merged or deployed. Local regression and the native PR profile are source evidence only. A final report and workbook receipt under `~/n8n-maturity-verification/reconciliation-20261012/` record exact local SHA, validation, CURRENT identity, status counts, remaining item actions, backup and Drive synchronization separately.

Owner decisions are proposed for October 12, 2026; these are not accepted appointments. Natural observation dates depend on authorized deployment and each reviewed cadence. Weekly/monthly and market-day proofs cannot be replaced by synthetic bursts or manual executions. Rollback must stop candidate scheduling first, restore only the approved lane trigger, verify one scheduling authority and prove output recovery.
