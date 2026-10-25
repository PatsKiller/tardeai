# JSONL archive rotation — the oversized append-only stores

```
Status:      PROPOSED (branch ops/jsonl-retention-20261023; lane jsonl-archive-rotate at SHADOW, contract DRAFT)
as_of:       2026-10-23T12:15:00-04:00
Measured at: base 53aa1b619 (origin/main); read-only dry run over the real stores 2026-10-23 11:12 ET (§4)
Owner:       platform
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Runbook-Id:  jsonl-archive-rotate
Tests:       tests/test_jsonl_archive_rotate_20261023.py (gate jsonl_archive_rotate_20261023, ANCHOR JSONL_ARCHIVE_ROTATE_20261023)
```

**Why.** Three append-only stores under `persistent-state/data/cio/` had grown without bound:
`aif_memory_retrievals.jsonl` 574 MB, `research_call_accounting.jsonl` 1.73 GB and `cio_workflow_lineage.jsonl`
165 MB. Several readers loaded them whole, and that was part of the 2026-10-23 portfolio-server memory kills (PR
#2012). The operator approved at about 11:05 ET on 2026-10-23 ("approved"): rotate them by archiving, never deleting.
At about 11:10 ET the operator added, verbatim: "You have my authority to delete them. And the N8N agent needs to
delete these on a regular. We cannot have this junk piling up on the". §6 covers how much of that this branch
delivers.

## 1. Pieces

| Piece | What it does |
|---|---|
| `scripts/ops/jsonl_archive_rotate.py` | `--dry-run` prints the plan and writes nothing. `--plan` writes the plan and a receipt. `--apply --confirm APPLY` rotates. `--recover --confirm APPLY` merges back a crashed rotation. `--retention-preview` lists the segments the retention rules would select and removes nothing. |
| `config/disk_hygiene_rules.json` `jsonl_retention` | Holds the stores, `hot_days`, `min_tail_rows`, `retention_days`, `max_archive_bytes`, the ET refusal window, `enabled: false`, and the `not_candidates` with a reason for each. |
| `<state>/archive/file_prune/<store>/` | Holds `<store>.<UTC>.jsonl.gz`, its `.manifest.json` sidecar (`RetentionArchiveManifest@v1`) and `TRIPWIRE.jsonl`. |
| lane `jsonl-archive-rotate` | An n8n dispatcher lane at SHADOW, running weekdays at 16:45 ET. The stage clamp runs `--dry-run`, and `live_arg` is null. Promotion is the operator's word. |
| `config/data_retention_policy.json` `purge_paths` `jsonl_archive_rotate` | The retention registry row. |

## 2. Stores, readers and hot tail

| Store | Size and growth | Timestamp field | Hot tail | Readers, and why the hot tail is enough |
|---|---|---|---|---|
| `data/cio/aif_memory_retrievals.jsonl` | 574 MB, about 21 MB/day | `at` | 3 days, at least 2,000 rows | `autonomy_watchdog` (today), `cross_agent_memory_agreement` (24 h), tails of 20 rows, 512 KB or 1 MB. The all-time count `get_memory_summary_v1.retrieval_receipts` (PR #2012 `count_jsonl_lines`) falls to the hot tail. It was already understated after the 2026-09-27 rotation. |
| `data/cio/research_call_accounting.jsonl` | 1.73 GB, about 63 MB/day | `timestamp` | 3 days, at least 2,000 rows | `read_events` (24 h default, `--hours`), n8n pilot observations (4 MB tail, 24 h). `cio_model_learning.mine_historical_performance` samples the head of the file, so its sample changes but nothing breaks. |
| `data/runtime/health_inspector_fixes.jsonl` | 115 MB, about 1.5 MB/day | `timestamp` | 14 days | `/api/v2/health/remediation` (8 MB tail, 24 h counts), the ops digest (24 h) |
| `data/runtime/advisory_notif_broker/decisions.jsonl` | 156 MB, about 2.1 MB/day | `ts` | 7 days | No reader in the repo. This is the notification-routing SHADOW log, not broker or order data. |
| `data/cio/daily_intelligence_heartbeats.jsonl` | 124 MB, about 1.9 MB/day | `generated_at`, `date` | 35 days | `heartbeat.load_history` reads the last 30 distinct days. |
| `data/cio/cio_workflow_lineage.jsonl` | 165 MB, about 2.7 MB/day | `recorded_at` | **not rotated** | `cio_lineage.LineageStore._existing_keys` dedups over every `semantic_key`, and `latest_envelope`/`upsert_envelope` merge a workflow's envelope from its full history. Moving old rows out would re-append duplicates and fork a late-updated workflow's envelope. It also drops the totals in `cio_lineage_health`, control-plane and `data_store_inventory`. Rotate it only after `cio_lineage` keeps a key index and a latest-envelope projection. |

These are not candidates, with the measured reasons:
- `research_contradiction_candidates.jsonl` (301 MB): its writer dedups over every `candidate_id`, and three readers read from the head.
- `memory_contexts.jsonl` (153 MB): it needs whole-file decision lookups.
- `cio_production_cases.jsonl` and `cio_plans.jsonl`: these are ledgers of record.
- `advisory_kb_lessons.jsonl`: already rotated by `rotate_advisory_kb_lessons.py`.

## 3. Writer safety — rename, not copy-truncate

Every writer opens the store per write with `O_APPEND` and takes no lock that the rotation could share. The writers are:
- `agent_durable_memory._append_receipt`
- `research_call_accounting.append_event`
- `cio_lineage.append`
- `notification_broker._append_jsonl`
- `autonomy_watchdog` `append_jsonl`
- the health-inspect remediation runner

A copy-then-truncate without the writer's lock loses every row appended between the copy and the truncate. The rotation therefore runs these steps:

1. Refuse if any process holds the store open across two samples. A long-lived fd holder would keep writing into the renamed inode.
2. Rename the store aside. A new open creates a fresh file.
3. Wait until no `/proc/*/fd` points at the renamed inode.
4. Stream the head to `.gz.part` and the tail to a temp file. Re-read the archive: its line count and the sha256 of its decompressed bytes must match.
5. `renameat2(RENAME_NOREPLACE)` the tail into place. If writers created a new live file meanwhile, `RENAME_EXCHANGE` swaps the two, and the swapped-out rows are appended with `O_APPEND`. No file is ever overwritten.
6. After a short grace, sweep late bytes.
7. Write the manifest and the tripwire record.
8. Unlink the two renamed-aside intermediates. Every byte in them has been verified to be in the archive or the live file, the same archive-then-unlink pattern `retention_archive.py` uses.

A failure at any step merges the source back. `--recover` handles a crash.

The tripwire is a `RetentionArchiveTripwire@v1` line per archive. `scripts/lib/retention_tripwire.py` reads it nightly through `report_db_hygiene.py`, and any live reference to `archive/file_prune` becomes an ARCHIVE_TRIPWIRE P1.

## 4. Dry run, 2026-10-23 11:46 ET (packet `--preview`: read-only, real stores, writes nothing to the state root)

| Store | Lines | Archive lines / bytes | Keep lines / bytes |
|---|---|---|---|
| aif_memory_retrievals | 1,066,938 | 901,279 / 481,860,688 | 165,659 / 92,235,222 |
| research_call_accounting | 2,827,720 | 2,507,653 / 1,535,724,769 | 320,067 / 195,980,346 |
| health_inspector_fixes | 245,143 | 126,611 / 65,543,423 | 118,532 / 55,550,906 |
| advisory_notif_decisions | 834,501 | 779,554 / 153,442,353 | 54,947 / 10,778,106 |
| daily_intelligence_heartbeats | 18,534 | 8,648 / 62,508,158 | 9,886 / 68,410,484 |
| cio_workflow_lineage | — | skip (`rotate_false`) | — |
| **total** | | **4,323,745 / 2,299,079,391** | **422,955,064 bytes** |

The retention selection (read-only) picks the two raw segments from the 2026-09-27 rotation, which were never compressed and carry no tripwire record:
- `data/cio/archive/aif_memory_retrievals-20260927T144843Z.jsonl`: 171,809,500 bytes, 26 days old, over the 7-day window.
- `data/cio/archive/research_call_accounting-20260927T144848Z.jsonl`: 1,648,777,181 bytes, over the 14-day window.

Together they come to 1.82 GB. Nothing removes them (§6).

The first dry run (11:12 ET) used the wrong timestamp field for daily_intelligence_heartbeats. It read `observed_at`, but the rows carry `generated_at` and `date`, so it found no parseable timestamp and would have cut the store to its 200-row minimum. The field is fixed. The code now refuses any store that has no parseable timestamp (`no_parseable_timestamp`) instead of rotating it by row count.

## 5. Running it

The packet is `docs/ops/packets/jsonl-rotation-20261023/run.sh`. The operator runs it after 16:15 ET:
- `--preview` reads only.
- `--apply` requires typed `APPLY`.

The lane promotion is the operator's: `live_arg` `["--apply","--confirm","APPLY"]` and `TRADEAI_N8N_RELAY_LIVE_LANES`.

## 6. Deletion — not automated, stated gap

The operator's second instruction asks for regular deletion of archive segments by n8n. This branch delivers the selection, not the removal:
- `retention_days` and `max_archive_bytes` are in the rules.
- `--retention-preview` lists exactly which segments they select.
- Nothing removes a segment.

The reasons:
1. AGENTS.md §24.12 (15.0.0) admits only git clones, worktrees and release directories to automated deletion. Its "Not in scope" bullet keeps stores and archives out, and `persistent-state` is on the hard never-touch list in `scripts/disk_hygiene.py`.
2. §23.14 and the allowlist never-list keep destructive retention off n8n.
3. In this session, extending `disk_hygiene.py` with a removal path for these segments was refused by the session's permission classifier, and the refusal was not routed around (§0 rule 3).

Widening §24.12 removes a restriction, so it is a MAJOR amendment of its own (it cannot ride the MINOR 20.1.0). Until it exists, removing a segment is the operator's own act (§17).
