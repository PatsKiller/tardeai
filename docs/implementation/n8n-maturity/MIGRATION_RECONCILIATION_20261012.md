# TradeAI migration reconciliation

Status: SUPERSEDED BY docs/implementation/n8n-maturity/MIGRATION_STATE_20261014.md for current state and the cutover
proof standard (2026-10-14); otherwise HISTORICAL — the 2026-10-12 local source and evidence package. Was: "DRAFT —
additional cutover BLOCKED".
Owner: platform integrator; per-process owners remain declared, unconfirmed
as_of: 2026-10-12T04:10:00+00:00
Measured at: source base 40208881dd34495b840bcbd4e373f593d06a659f; observed CURRENT 37752b193-main-exact-phase2-20261011-201624

> **Correction, 2026-10-14 (operator ruling ~11:05 ET; AGENTS.md 8.0.0 §23.21, PROPOSED).** Three statements below
> no longer describe the standard and must not be acted on: (1) "additional cutover remains blocked until the
> applicable … natural schedule … requirements pass" — cutover is no longer blocked on natural-schedule evidence;
> (2) "two distinct natural shadow slots must follow the fixes" and "manual canaries … cannot substitute for natural
> fires" — a forced `dry_run` fire passes criterion 2 and a forced in-window `live` relay fire with the cron line
> present under the shared lock passes criterion 4; (3) "market-day proofs cannot be replaced by synthetic bursts or
> manual executions" — no multi-day or market-day soak is a cutover condition (window-bound lanes still fire
> in-window). The standard is: defect fixed, n8n dry run passes, lane regression tests pass, at least one successful
> live n8n run with cron present under the shared lock. 6 lanes were cut over by 2026-10-14 (`n8n-pilot-dispatch`,
> `n8n-incident-fanin`, `n8n-research-intake-consumer`, `crontab-snapshot-for-health-agent` on 10-09;
> `research-insight-extractor` on 10-13; `heartbeat-watch` n8n-only). Current state:
> [`MIGRATION_STATE_20261014.md`](MIGRATION_STATE_20261014.md); procedure:
> [`RUNBOOK_CUTOVER_ROLLBACK.md`](RUNBOOK_CUTOVER_ROLLBACK.md). `scripts/n8n_cutover_checklist.py` still encodes the
> natural-slot rule described below; its forced-fire verdicts are stale until a code PR changes it. The text below is
> kept unchanged as the 2026-10-12 record.

The authoritative workbook retains 679 inventory rows, including 262 rows classified for refactoring or custom development. Historical migration labels, implementation annotations and planning records remain evidence with their original scope. They do not establish production acceptance. Additional cutover remains blocked until the applicable source, deployment, natural schedule, output, monitoring and recovery requirements pass.

## Workbook reconciliation

`scripts/reconcile_migration_inventory.py` adds a closure dashboard, one closure record for every original inventory row, the 262 modification targets, a requirement matrix, an exact-ID process crosswalk and drift findings. It appends structured fields to Inventory and acceptance fields to Cutover_Tracker. Original values, styles, links, comments, lifecycle labels and operator decisions remain intact. Tracker retains its original snapshot and appends the new status partition.

Primary status follows the reviewed evidence: Completed requires all applicable closure proofs; explicit accepted decisions scoped to the entire inventory closure become Deferred; current named authority, ownership or mapping boundaries become Blocked; historical implementation or lifecycle work becomes In Progress; other required work remains Not Started. This review accepts no process as Completed on free-text assertions. Contract REVIEWED is a declaration whose provenance and runtime application still need acceptance.

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

Publication adds `--apply --expected-sha INSPECTED_WORKBOOK_SHA256`. It holds the shared advisory workbook writer lock across inspection, validation and publication, creates an exclusive exact-byte backup, verifies the candidate retains protected cells after round-trip serialization, and refuses publication if the original workbook changed during preparation. The existing build and source-annotation generators use the same lock. Raw filesystem writers that ignore the advisory lock must be serialized by the operator. Preview/candidate files remain available for review. Regenerating only the older `build_workbook.py` omits the closure review; run this adapter afterwards using the freshly inspected workbook hash. Per-review evidence contains the source-input hashes and publication receipt.

Pre-build search found `n8n_migration_board.py` for lane lifecycle, `n8n_cutover_checklist.py` for cutover evidence, and the existing external `source_tracking.py` workbook annotation mechanism. None owns the inventory-level acceptance partition or full requirement crosswalk. This adapter extends the existing workbook rather than introducing another runtime tracker, scheduled job or production store.

## Source fixes

The runner integration preserves the current main safety, environment and dry-run behavior. It retains all parallel worker PIDs for individual exit accounting and records expected step count, receipt completeness and worker failure. Missing, duplicate or foreign receipts cannot become a healthy live summary. Durable receipt-write failures return a failing stage exit while allowing remaining business steps to finish. Ordinary child failure and timeout keep existing main semantics pending owner decisions.

Runner regression fixtures copy the required Bash/Python source into scratch projects with minimal environments, isolated homes, state, locks and interpreters. Synthetic assignment-position fixtures replace the host-only C1 snapshot dependency and skipped test. Production access barriers remain enabled.

Scheduler tests use an explicitly contained scratch command rather than a host-command alias. Health tests inject a deterministic clock and an empty scratch dotenv file. Relay probes transfer parent-owned ephemeral loopback descriptors to child servers; the isolation harness validates scratch scope, descriptor identity, ownership and peer roles before launch. Invalid or unrelated descriptors are refused. These fixture capabilities do not authorize production listeners, databases, credentials or host commands.

The cutover checklist requires an exact integrated SHA and a correlated acceptance packet before it ticks natural shadow/canary/output proof. Two distinct natural shadow slots must follow the fixes and match the host receipt, ledger request, n8n schedule trigger, legacy authority, disjoint shadow lock, zero business effects and independently inspected outputs. Manual canaries remain labelled MANUAL_CANARY and cannot substitute for natural fires. Locks alone cannot establish absence of duplicate business effects. Wrong SHA, stale observations, incomplete receipt accounting and conflicting evidence fail acceptance.

The packet interface is documented in `scripts/n8n_cutover_checklist.py`; it is a read-only observation input, never a producer of natural evidence or an operational grant. Per-run effect observations live below `data/runtime` and name the lane/run/SHA. Their contents must come from output and consumer inspection. Synthetic test packets establish gate behavior only.

YouTube cookie classification recognizes Netscape `#HttpOnly_` domain prefixes through a pure name parser. Its regression uses synthetic text and does not inspect cookie files, credentials or model routes.

## Operational boundaries and remaining work

The runtime/contract packet under `reconciliation-20261012/runtime-contracts/` records sanitized observations, external DRAFT contract proposals, owner decisions, nine incomplete source pairs, monitoring requirements and OpenClaw mappings. It prepares exact operator change packets for n8n privilege hardening and Ollama retirement. Four UNKNOWN contract fields have source-backed proposed replacements; no reviewer is invented or advanced.

`inventory_coverage_resolution.json` gives all 61 registry gaps a source mapping proposal or an explicit collection action, with three classification proposals and the shared CIO timer parent relationship. The workbook keeps proposals separate from accepted business mappings and owner confirmation. Current source corrections do not silently alter historical classifications or retirement decisions.

Hermes is currently inactive with a successful exit; its earlier failed snapshot remains historical. An empty current queue does not prove recovery of historical failed work, and a restart has no current justification. Ollama still running is retirement drift; an instantaneous socket census cannot close periodic caller dependencies. The n8n database role remains overprivileged; historical backup/restore receipts do not replace a fresh prechange backup or an application-role migration test.

No source commit in this package is pushed, merged or deployed. Local regression and the native PR profile are source evidence only. A final report and workbook receipt under `~/n8n-maturity-verification/reconciliation-20261012/` record exact local SHA, validation, CURRENT identity, status counts, remaining item actions, backup and Drive synchronization separately.

The October12 daytime integration adds expected-fire momentum lifecycle monitoring, authenticated fixed-root gateway/relay reads, independent host incident notification, bounded derivative-cache reconciliation and15 external DRAFT health contracts. Staged dispatch remains mechanically off. Unaccepted input declarations cannot become business proof; runtime receipt writes require real host collection, the operative candidate policy and real clock. Owner acceptance and contract review are explicit gates.

Active Trader and TradeAI now share a read-only symbol-union component with retained source verdicts and conflicts. It shows five momentum facts (price, float, relative volume, gap and verified catalyst) plus catalyst headline/source/verification/timestamps. Missing or stale evidence stays UNKNOWN; Social Scout's five awareness pillars remain separate. Five source facts do not grant trade authority. Protected engine eligibility is not changed by this display reconciliation.

The morning06:00/06:15/06:30 Finviz shadow requests failed before scanner execution because flock could not create its dry-run lock on the inode-exhausted `/tmp` filesystem. Archiving only this session's stopped synthetic scratch work freed65,325inodes. This is a storage repair observation, not natural schedule/output acceptance. A peer later deployed main40208881; the new local tranche is not that served release.

Owner decisions are proposed for October 12, 2026; these are not accepted appointments. Natural observation dates depend on authorized deployment and each reviewed cadence. Weekly/monthly and market-day proofs cannot be replaced by synthetic bursts or manual executions. Rollback must stop candidate scheduling first, restore only the approved lane trigger, verify one scheduling authority and prove output recovery.
