# Registry reconciliation: frozen-input audit and unresolved live-input diff

Status: DRAFT — evidence package; source action BLOCKED by an existing claim
as_of: 2026-10-24T04:18:00Z
Design-Task: DSN-20261024-registry-reconcile-P1-T31

The reported approximately 70 added / 96 removed recommendation and `stay_on_cron` lines cannot be reproduced from the committed October 9 snapshot on frozen main `8b24e113740cda70c25e4823c16c46ea3b63cf7f`. Reconciliation against that historical snapshot changes **zero bytes and zero semantic fields**. The same replay is byte-identical on the canonical checkout and the reviewed batch-14 candidate. This does **not** resolve the reported default-command drift: the default command reads current host schedules, and the original live inputs/proposed diff were not retained in the inspected coordinator cache.

No registry, scheduler, dispatch mode, live flag, contract, policy or installed workflow was changed. No new host census was performed. This is a separately claimed documentation/evidence package, not a substitute for the blocked source task.

## Exact source boundary

Attempting to take `DSN-20261024-registry-reconcile-P1-T3`, scoped to `config/lane_registry.json`, was refused:

```text
CONFLICT: config/lane_registry.json — held by codex/codex-worker session codex-wp21-20261023
on branch work/T-20261023-84a7f0 since 2026-10-24T02:14:37Z
(last heartbeat 2026-10-24T03:56:50Z; claim 20261024T021437Z-codex-8df6cf34;
task: [T-20261023-84a7f0] Rebase #1953 ...)
refused: the task's areas overlap a live claim of another session.
```

The refusal was recorded in `PROGRESS_LOG.md` at `2026-10-24T04:09:22Z`. No source retry or alternate write followed. Documentation claim `20261024T040923Z-codex-10342010`, session `codex-registry-audit-20261024`, owns only this report, its evidence directory and the generated docs index. The coordinator retains release/merge authority and will announce when the original source claim can be retried after batch 14.

## What `--write` actually reads

`main()` in `scripts/reconcile_lane_registry.py:1371` selects its inputs as follows. `--write` changes the final write mode, not input selection.

| Input | Default | Explicit historical replay |
|---|---|---|
| Cron | `read_live_crontab()` → `crontab -l` | `--snapshot-in` → `snapshot_cron_text()` |
| Units | `capture_units_live()` → user systemctl discovery/show/cat and systemd-analyze calendar | `snapshot["units"]` |
| Registry | worktree-relative `config/lane_registry.json` | Same, unless `--registry` provided |
| Rationalization | worktree-relative `docs/implementation/n8n-maturity/data/F_rationalization.json` | Same, unless `--rationalization` provided |
| Output evidence | worktree-relative `docs/implementation/n8n-maturity/data/lane_output_evidence.json`, including source-token checks | Same, unless `--evidence` provided |
| Stay markers | gateway/pipeline constants and `config/lane_stay_on_cron_tokens.json` | Same |
| Serialization | `json.dumps(indent=2, ensure_ascii=False)` plus LF | Same |

There is **no default snapshot path**. `--dry-run` alone also reads the host; use `--snapshot-in` for a source-only replay. Supplying only `--crontab-file` still reads live units; supplying only `--units-json` still reads live cron. `--snapshot-out` and `--report-md` explicitly write artifacts even in dry-run mode.

`make_snapshot()` currently stamps `captured_on` from fixed `RECONCILED_ON="2026-10-09"`. A newly collected host snapshot therefore needs a separate actual UTC observation receipt; that fixed date is not proof of when the host was observed. `make_snapshot()` preserves source line numbers because the rationalization join uses them. Do not reconstruct a capture by stripping comments or compacting lines.

## Measured replay and every semantic change

The three JSON receipts in [the evidence packet](packets/registry-reconcile-audit-20261024/README.md) contain full input SHA-256 identities, before/candidate digests, row/order/field diffs, problem lists and explicit capture provenance. Replays used only committed inputs, with live census functions, subprocess execution and `socket.create_connection` replaced with refusing barriers. No `--write` ran.

| Frozen tree | Head | Rows before/after | Changed lanes / fields / bytes | Added / removed IDs | Problems |
|---|---|---:|---:|---:|---:|
| Fresh main | `8b24e113740cda70c25e4823c16c46ea3b63cf7f` | 676 / 676 | 0 / 0 / 0 | 0 / 0 | 0 |
| Batch 14 | `3693b3d2cdfdb3289ed7c38321f8313c8b517c23` | 677 / 677 | 0 / 0 / 0 | 0 / 0 | 0 |
| Canonical checkout | `d0c8b70d8d915098094aa7180f25d6b0b0e0cffe` | 676 / 676 | 0 / 0 / 0 | 0 / 0 | 0 |

For these exact replays, the exhaustive semantic-change sets are empty: no lane additions/removals, lane-order changes, lane-field changes or top-level changes. The candidate digests equal their respective input registry digests. Every scheduler, `state`, `dispatch`, recommendation, rationalization and stay marker is therefore preserved exactly.

Between main and batch 14, `git diff --numstat` reports **48 added / zero removed lines**, all belonging to the separately reviewed `cio-prospect-shadow` row from WP-21. That is the already-reviewed shadow/dry-run admission, not reconciliation drift. This package neither introduces nor re-approves it. The reconciler, historical snapshot, rationalization, evidence and stay-token files are byte-identical between the three trees. The canonical registry is byte-identical to fresh main. The coordinator batch-14 cache inspected at this observation contains the PR body, but no captured live cron/unit input or retained proposed registry patch. The old cache files `lane_registry.main.json` / `lane_registry.mine.json` have 661 / 662 rows and no binding to the reported command; they are not treated as current evidence.

The approximately 70/96 diff's lane IDs, individual old/new values, actual capture time and command provenance remain **NOT_MEASURED**. It would be inaccurate to invent explanations for those changes or say the drift is fixed.

## Why recommendation/stay changes need review

These fields influence admission. They are not harmless presentation annotations.

| Generator behavior | Consumer / practical implication | Review disposition |
|---|---|---|
| `annotate_existing()` overwrites existing rows' `value_class`, top-level `recommendation` and entire `rationalization` block after a captured scheduler/F join | `lane_dispatch._keep_on_cron()` reads both top-level and rationalization `KEEP_ON_CRON` | Explain the specific F row, match and normalization for each change; preserve current reviewed verdict until reconciled |
| A matching forbidden token adds/replaces `stay_on_cron`; it forces top-level `KEEP_ON_CRON`, even if F says eliminate | `dispatch_eligible()` rejects a nonempty stay marker unless the applicable explicit policy exemption/directive lifts it | Adding can block a lane; removing can remove a blocker. Require reviewed provenance, not a mechanical replay |
| Existing hand-written stay markers are **not removed** when no new stay match is found | A stale marker can survive a new capture and continue blocking | Missing new match is not proof the old marker was intentionally cleared |
| Generated rows are removed from the working copy and regenerated from capture/evidence | Their markers, output evidence and even population can differ when the captured host changes | Review added/removed IDs and all fields, not just line counts; do not infer authority from the generator header's “never deletes a row” |
| Declarations match cron by substring; F joining first uses captured line number, with fallbacks | New/missing/ambiguous host matches may change the joined recommendation | Record exact declaration, captured line reference, F ID and token cause per changed lane |
| `state` and `dispatch.mode` may remain unchanged despite metadata changes | Eligibility also consults operator holds, directives, exceptions, watch blocks and forbidden tokens | Unchanged live flags alone do not prove unchanged eligibility; do not run or enable a lane as part of this audit |

Relevant source: `annotate_existing()` around line 1021; `_final_recommendation()` around line 761; `reconcile()` around line 1091; `scripts/lib/lane_dispatch.py:_keep_on_cron` around line 835 and `dispatch_eligible` around line 953. This package inspected those admission rules statically; it did not execute host admission or any broker capability path.

## Verification and next action

`PYTHONPATH=/home/johnclaw/.cache/rtc/nopg` with the canonical virtualenv Python ran the existing `tests/test_n8n_maturity_registry_reconcile_20261009.py`: **33 passed in 11.26 seconds**. No tests or application source were changed. The fixture replay, source identities and byte equality were independently recorded for all three trees. JSON/checksum/index/diff checks are recorded in the packet. These checks establish historical-input reproducibility, not current host correctness or runtime acceptance.

The coordinator/operator should supply the original retained capture plus command/head and candidate patch, or perform the exact read-only capture in [OPERATOR_CAPTURE.md](packets/registry-reconcile-audit-20261024/OPERATOR_CAPTURE.md). Only after that evidence exists and the WP-21 source claim is released should the source task be taken again. A new source review must explain every changed lane/leaf, retain reviewed authority and rejection rules, and pass fixture tests with psycopg2 hidden. Do not commit raw `--write` output or treat a recommendation change as scheduler authorization.

Actual live-input drift explanation and source correction remain blocked/unmeasured. No cutover, policy, deployment, natural-fire or production-readiness status is promoted by this report.
