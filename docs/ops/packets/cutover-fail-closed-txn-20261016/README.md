# Cutover fail-closed + controller transactions (2026-10-16)

An independent architect review found four defects that must be fixed before the nightly cutover controller or the cron
effect-claim wrapper runs unattended. This packet records the fix, the design of the durable handover manifest, and the
order in which an operator must deploy it. Nothing in this PR edits the crontab, systemd, the ledger or any credential.

## The defects and the fixes

| # | Defect | Fix | Tests (`tests/test_cutover_fail_closed_txn_20261016.py`) |
|---|---|---|---|
| D1 | `scripts/effect_claim_cron.sh` **failed open** when the ledger was unreadable, including for lanes already handed over to n8n. The flock stops an overlap, but it does not stop a second run after the first one has finished. | **Handed-over lane:** if ownership cannot be established, the wrapper runs nothing, exits 75, logs `skipped_ownership_unknown` and raises a **P1**. **Never-handed-over lane:** the old fail-open behaviour is kept. | `test_D1_*` |
| D2 | "5 per night" was enforced per evaluation, so repeated invocations could exceed it. | Durable per-ET-night quota ledger, written under the controller lock and counted across invocations. | `test_D2_*` |
| D3 | Apply evaluated one snapshot and reused it for every lane. | Before each lane's edit, inside the fenced handover, the controller runs fresh checks: grant, ledger owner, release / allowlist / contracts / workflow graph, in-flight runs, ambiguous claims. A lane-level change holds that lane. A shared change stops the cohort. | `test_D3_*` |
| D4 | A crash between the crontab, registry and contract writes left no record. | A write-ahead transaction record is written before the first mutation. Steps are marked as they complete. Recovery is deterministic and idempotent, and runs before any new work. | `test_D4_*` |

## The durable handover manifest (D1)

The wrapper must be able to tell whether a process was handed over **without** reading the ledger.

- **Path.** `$TRADEAI_N8N_HANDOVER_MANIFEST`, else `n8n_handover_manifest.json` beside the coordination ledger. The
  default is `<state>/data/governance/n8n_handover_manifest.json`. It is plain JSON, not sqlite, so a locked or corrupt
  ledger does not make it unreadable.
- **Schema `N8nHandoverManifest@v1`.**
  `{"schema", "updated_at", "processes": {"<process>": {"owner", "epoch", "switched_at", "by"}}}`. Here `owner` is the
  last owner recorded by `set-owner`.
- **Writers.** `effect_claim.py set-owner` and the one-time bootstrap `effect_claim.py handover-seed` are the only
  writers. Every write holds an exclusive flock on `<manifest>.lock` and goes temp file, fsync, rename, then directory
  fsync, so a reader sees the old file or the new one, never a torn one. The wrapper, the controller and the reports
  only read it.
- **Write order.** Any crash leaves the two stores disagreeing only in the safe direction:
  - A switch **to n8n** writes the manifest first, then the ledger. If the compare-and-swap is refused, the prior
    manifest entry is restored under the same lock.
  - A switch **away from n8n** writes the ledger first, then the manifest.
  - Either crash leaves "manifest n8n, ledger not", which the wrapper treats as ownership unknown: fail closed, P1.
- **Fence.** The controller holds the same lock across each lane's re-check and edit, so no `set-owner` can land
  between the two.
- **Never reconciled automatically (AGENTS.md §0 rule 5).** On disagreement the wrapper puts both values in the event
  detail and the incident row, and skips. `handover-seed` refuses if a manifest already exists.

### What the wrapper decides (`effect_claim.py ownership --process P`, read-only)

| Ledger owner | Manifest owner | Decision |
|---|---|---|
| n8n | n8n | `skip_owner_n8n`: exit 0, `skipped_effect` |
| cron / none | same as ledger, or not listed, or no manifest file | `run` (unchanged behaviour) |
| unreachable | n8n or none | **`skip_ownership_unknown`**: exit 75, P1 |
| unreachable | cron, not listed, or no manifest file | `run`: **fail open**, never handed over or handed back |
| any | unreadable manifest | **`skip_ownership_unknown`**: P1 |
| one value | a different listed value | **`skip_ownership_unknown`** (`manifest_ledger_disagree`): P1 |
| n8n | not listed, or no manifest file | **`skip_ownership_unknown`** (`manifest_ledger_disagree`): P1 |

If the interpreter or helper fails, so that no decision is made, the wrapper fails closed when a manifest file exists
and fails open otherwise.

### The P1 path

The wrapper appends one `EffectOwnershipIncident@v1` row to `<state>/data/runtime/effect_ownership_incidents.jsonl`. It
writes that row from bash, so a broken interpreter still records it. `scripts/lib/effect_ownership_watch.py` turns the
rows from the last 6 h into one P1 per lane, with source `effect_ownership` and item `<lane>:OWNERSHIP_UNKNOWN`. Two
places read them under the same keys:

- **`scripts/incident_notifier.py`**, on host cron. It does not depend on the ledger or on n8n, either of which may be
  the thing that is down.
- **`scripts/n8n_incident_fanin.py`**, for the SIEM row.

## Controller transactions (D2–D4)

All of the following lives under `<receipt_dir>` (default `<state>/data/runtime/nightly_cutover/`).

- **`controller.lock`.** Apply and rollback take it non-blocking. A concurrent invocation is refused with
  `controller_busy` and changes nothing.
- **`quota/night-<date>.json`** (`NightlyCutoverQuota@v1`). An ET night runs from noon to noon America/New_York and is
  named by the date of its evening. One reservation is written per lane before that lane's first mutation. Its status
  is `reserved`, then `applied` or `released`.
- **`txn/<txn_id>.json`** (`NightlyCutoverTxn@v1`), plus backup copies beside it. The record holds the planned crontab
  edits, the before and after images of the registry row and the health contract, the hashes of each file before the
  change, and the step marks.
- **Recovery** runs at the start of every armed apply. It inspects the **actual** state of each target:
  - every mutation landed: complete the transaction (write the rollback receipt, then commit);
  - some mutations landed: roll back in reverse order;
  - a target matches neither its before image nor its after image: mark it `conflict`, touch nothing, report both
    values, and stop on every start until an operator restores a consistent state.

  After any recovery the invocation stops for the night. A plan or dry-run reports `incomplete_txn_pending_recovery`.

## Deploy order (operator)

These steps must happen in this order. If the PR is served before the manifest exists, every wrapped lane that n8n owns
fails closed with a P1. That is safe, but it is noisy.

1. Merge, then prepare the release as usual.
2. **Before promote.** Seed the manifest from the live ledger, then check it. Each command is run twice: first as a dry
   run, then for real.

   ```bash
   $PY scripts/lib/effect_claim.py handover-seed --by operator
   $PY scripts/lib/effect_claim.py handover-seed --by operator --apply
   ```

   Spot-check `$PY scripts/lib/effect_claim.py ownership --process <p>` for a few n8n-owned processes. Each should print
   `skip_owner_n8n	n8n	n8n	0	owner_n8n`.
3. Promote. From then on, `set-owner` keeps the manifest current.
4. Verify by reading `logs/effect_claim_events.jsonl`. It should show `skipped_effect` for n8n-owned lanes and no
   `skipped_ownership_unknown`.

The nightly controller also requires the served wrapper to carry `skipped_ownership_unknown`, and the manifest to name
the process as n8n's, before it retires a keyed lane. It stays DISARMED until the operator issues a `cron` grant naming
`nightly-cutover-controller`.
