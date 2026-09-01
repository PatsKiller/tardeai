# Pre-Deploy State Guard (canonical)

Status:      ACTIVE
as_of:       2026-06-10T11:19:14-04:00
Measured at: efcc51365 / not measured

**Prepared:** 2026-06-10 · **Closes:** the deploy/zip-extraction wipe vector that `holdings_guard.py`
(Python-write protection) cannot reach. `scripts/pre_deploy_state_guard.py`.

## The gap it closes
`protected_holdings_write()` / `holdings_guard.py` protect every **Python** write to
`data/portfolios/state/holdings.json`. But a **deploy zip/tar extraction, rsync, restore, or cleanup** that
overwrites `data/portfolios/state/**` bypasses Python entirely — a stale or empty `holdings.json` baked into
a deploy payload would clobber the live $1.2M snapshot with no guard in the path. This guard inspects the
**payload before extraction** and refuses to let a deploy touch portfolio state.

## Inventory — paths that can touch state files
| Path | Vector | Now gated by |
|---|---|---|
| `scripts/deploy_session*.py`, `deploy_yaml_patches.py` | code deploy | run `guard` on any archive first (deploy mode → BLOCK if it carries state) |
| `backups/*pre_deploy*.tar.gz`, `full_system_backup.py` | backup/restore tarballs | restore mode ceremony |
| `backup_secrets_state.sh`, Drive restore | offsite restore | restore mode ceremony |
| rsync / cleanup / manual `tar x` | ad-hoc | operator runs `guard` before extracting |

## Behaviour
- **Deploy mode (default, inspection only — never writes):**
  - payload contains **no** state files → **ALLOW** (safe to extract).
  - payload contains **any** `data/portfolios/state/**` or `holdings.json` → **BLOCK**.
- **Restore mode (`--restore`, privileged):** allowed only when **all** gates pass —
  1. **named backup** provided and exists on disk;
  2. **current-snapshot backup** taken automatically before any change (`data/backups/state_snapshots/`);
  3. **pre-restore assert** — `holdings.json` total ≥ $1M AND position_count > 0 (refuse to restore over a bad current state);
  4. **operator confirmation token** — must equal the archive's `confirm_token` (sha256 of the payload bytes), proving the operator saw *this* payload;
  5. **post-restore assert** (with `--do-extract`) — re-checks total ≥ $1M & count > 0; **auto-rollback** to the snapshot if it fails;
  6. **append-only audit** — every decision written to `data/state_guard_audit.jsonl`.

## Usage
```bash
python3 scripts/pre_deploy_state_guard.py inspect <archive>          # list state hits + confirm_token
python3 scripts/pre_deploy_state_guard.py guard   <archive>          # deploy gate (BLOCK if state present)
python3 scripts/pre_deploy_state_guard.py restore <archive> --named-backup <f> --confirm <token>
```

## Proof (2026-06-10)
| Test | Result |
|---|---|
| BAD archive (contains `holdings.json`), deploy mode | **BLOCK** — "payload contains 1 portfolio-state file(s)" |
| NORMAL deploy (code only) | **ALLOW** — "no state files in payload" |
| RESTORE mode without ceremony | **BLOCK** — lists: named backup missing, confirm token incorrect |
| `holdings.json` before vs after all tests | **byte-unchanged** (sha256 identical) |
| audit log | 3 entries written |

## Rollback
The guard is **inspection-only in deploy mode** — it never writes, so there is nothing to roll back from a
deploy-mode block. In restore mode the snapshot backup is the rollback: a failed post-assert auto-restores
`holdings.json` from `data/backups/state_snapshots/holdings_<ts>.json`; the operator can also re-apply any
listed snapshot manually. To disable the guard, simply don't invoke it (no writer routes through it).

## Scope / A1A
Read-only of the archive in deploy mode; the only writes are in restore mode (the snapshot backup + the
guarded state extraction, both asserted + rolled back). **No Schwab writes, no trading, no screeners, no
classifier, no GO/WAIT, no ATM.** Cross-ref: [`SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`](SCHWAB_API_PHASE1_READONLY_FOUNDATION.md)
"Mandatory holdings wipe-guard" (the Python-write half).
