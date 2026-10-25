# WP-30: moomoo retirement state readers and writers

Status: DRAFT — read-only audit and operator packet complete; decision/correction/archive pending
as_of: 2026-10-24T03:02:12Z
Measured at: main `8ed8a246486317950df01f2a1846825627f369eb`; session `codex-wp30-20261023`

The drift is verified: the served holdings record retains `retired: true` from September 1 while its stored account classification says LIVE. The authoritative account registry already says active. The worker changed no account record, financial data, broker code, scheduler, archive or production state.

## Current evidence

| Store or observation | Verified value | Interpretation |
|---|---|---|
| `CURRENT/assets/portfolio_accounts.yaml`, moomoo row | `active: true`, `sync_kind: api`; no retired field | Account registry already active; no redundant toggle needed |
| Main's same registry | Same active configuration | No source/deployment disagreement for this flag |
| Served holdings resolves to persistent state | `persistent-state/data/portfolios/state/holdings.json` | One file was inspected; divergent copies were not merged |
| Target `account_summaries` retirement | true; historical date 2026-09-01 | Obsolete retirement metadata remains |
| Stored classification | LIVE; observation `2026-10-23T19:45:02.450337+00:00` | Producer's stored label, not a fresh broker check |
| Target holdings rows | 2 | Presence only; no balances/account identifiers/position sizes disclosed |
| Original retirement archive | Present; schema `RetiredAccountRow@v1` | Existing bytes retained; tripwire is written instruction |
| Live preview | `archive_ready: false` | Archive application correctly remains blocked |

Safe preview receipt: `/home/johnclaw/.cache/rtc/wp30-preview-xn_4mi2u/preview.json`. Its original tripwire digest is `7e250a876958eace71bb933eda24e32616f5d845d145259684427f6ec6b9b50a`. Holdings hashes are observation-specific and will change normally as writers run; a new preview is required before any later operation.

## Direct retirement handling

| Source | Role | Effect |
|---|---|---|
| `scripts/lib/data_broker/broker_access.py:452` (`_acct_state`) | Reads summary `retired` and `retired_reason`, projects both | Exposes the contradictory flag beside sync classification |
| Same module `moomoo_row`, lines 605–611 | Reads projected retired metadata | Adds a retirement note; it does not stop the broker read sync |
| `scripts/lib/account_state.py:377` | Writes state labels from receipts/row clocks while retaining other summary fields | Can update LIVE while leaving retired metadata intact |
| `scripts/portfolio_loader.py:313`, `:372` | Copies existing summaries, updates totals/classification and republishes them | Preserves unrelated historical metadata |
| `scripts/portfolio_repricer.py:880` | Refreshes classifications from receipts without shell probes | Does not resolve retirement intent |
| `scripts/moomoo_live_read_sync.py:125`, `:151` | Replaces account holdings under the shared lock through the protected writer | Does not read the retirement flag; no sync source was changed |
| Historical retirement archive | Prior record plus prose tripwire | No tracked executable reference to the exact archive filename was found |

There is no tracked direct writer of this account's `retired` field in the audited base. Its original operator mutation is historical evidence, not a newly discovered active writer. The source's retirement note is not a runtime enforcement mechanism.

## Complete static reference inventory and limits

The [packet](packets/moomoo-retirement-reconcile-20261023/README.md) contains reproducible inventories:

- `static-references.csv`: **145 references / 65 files**; 111 summary-container reads, 17 constructions, 2 assignments, 10 references requiring presentation/type context, 5 direct retirement-metadata reads. Scope: 92 source references, 51 test references, 2 legacy-v2 references.
- `guard-writer-sites.csv`: **15 guarded write call sites / 15 files**. Paths include Alpaca/moomoo/Schwab syncs, API, db adapter, loader, repricer, holdings reconciliation, share reconciliation, basis transfer/repair, sector/lookthrough resolution and portfolio server. The CSV gives exact source lines.
- `assets/portfolio_accounts.yaml` readers/maintenance references include `portfolio_loader`, `portfolio_repricer`, `portfolio_performance_history`, `portfolio_ai_analyst`, `portfolio_yaml_advisor`, `portfolio_technical`, `rebalance_deep_analyzer`, `fidelity_constraint_helper`, `lib/account_state`, `portfolio_yaml_writer` and `import_file_configs_to_db`; source-authority/agent configuration also references it. These read configuration or maintain/import it; no retirement-clearing operation exists there.

The data-source registry declares `portfolio_loader` and records a historical seven-writer note. That note is not the same denominator as fifteen static guarded call sites. Call sites can be manual, legacy, wrappers or non-running; the audit did not run them, inspect broker endpoints, or claim a production writer count. Dynamic aliases, external/untracked scripts and execution reachability remain NOT_MEASURED. The inventory reports every matching tracked reference in its explicit AST/text scope; it cannot prove absence of all possible indirect reads.

## Operator package and boundary

The packet provides a sanitized read-only preview, explicit-decision private candidate preparation and an archive-only command that refuses until an authorized metadata correction has been read back. Its candidate changes only `retired` plus a resolution proposal, preserving historical retirement fields, account classification, observation clocks and all financial data.

A new holdings writer requires an operator grant (§7A), and every holdings write must use `protected_holdings_write` (§9.4) while holding the shared lock. That guard currently imports the Schwab implementation. The packet therefore contains no holdings apply/new writer and never substitutes a direct JSON write. Its `apply-holdings` action refuses explicitly. The README supplies exact conditional state-write and archive grant requests, preparation commands and archive commands; no grant was issued by this worker.

The operator chooses whether to unretire the record or instead require the broker sync to honor retirement under a separate execution-engineering task. The worker made neither decision. The YAML registry already being active means a source toggle alone would leave the real defect intact.

## Verification and remaining acceptance

**29 fixture tests passed**, covering private/sanitized previews, no production writes, explicit decisions, metadata-only candidates, source/path/schema drift, unresolved-retirement refusal, unchanged archive bytes, fresh private receipts and drift/expiry rejection. Tests use temporary files and never import/call a broker or protected writer. The new test has a canonical CI gate; its suite plus the CI-gate registry checks passed 54 tests.

Remaining: direct operator decision; actual named writer authorization; protected metadata application/readback; fresh archive preview and operator archive grant/action; consumer readback proving the obsolete retirement note is gone. Fresh broker status, credentials and sync success were not tested. The account is not declared unretired by this report.

Packet `SHA256SUMS` SHA-256: `4d2258f73ead74c0033b1dd6dec380bd001d4f60b54003ad5545705582b6d0f1`. Compare this before checking the manifest contents.
