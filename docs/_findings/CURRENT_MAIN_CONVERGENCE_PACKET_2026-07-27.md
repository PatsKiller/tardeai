# Current-Main Host Convergence Packet — dry-run-first, exact-ref (2026-07-27)

**Status:** MERGED (#238 as `21366635`); packet applied to host and verified. No agents/schedules/
models/providers/proposals/orders/execution. M3 source + config unchanged. **Original base:**
`03bbf00d2646a08f63bc9e94f2f35dc406311262`. **Current build pin (Front 0 re-pin):**
`21366635ce6e2a8610e0ea1ea716036016df299b` — the exact-ref build source now equals current `origin/main`
so served Command Center provenance matches HEAD. Command-center source is byte-unchanged between the two
SHAs (0 files differ), so the bundle content is identical; only the stamped `source_commit` advances.

Fixes the two deployment-architecture defects the integrator flagged, scoped to the reality the
read-only inventory proved (agent-runtime read plane is already `CONNECTED_READ_ONLY`, not 404):

1. **Frontend built from the live checkout.** `deploy_watch_production_reconciliation_from_ref.sh:101`
   builds from `$LIVE_APP` (the working tree) — a dirty/divergent host can produce an unrelated
   bundle. Also the deployed `dist/build-meta.json` has **no `source_commit`** (vite plugin only
   stamps `ui_version`), so the deployed UI's provenance is unprovable — the inventory showed
   `deployed_ui_sha=UNKNOWN` and the built bundle is **missing** `agent-runtime-command-center-read-api-v1`.
   → **Fix:** `build_exact_ref.sh` exports the candidate via `git archive <commit>`, builds only inside
   the staged tree, and stamps build-meta with the full 40-char `source_commit` + contract versions
   (the pattern `deploy_watch_quality_ui_from_ref.sh` already uses correctly).
2. **Agent read-mount can't bootstrap from 404.** `deploy_read_mount.sh:104` requires the endpoint to
   *already* return 503 before installing → a fresh host (404) can't bootstrap.
   → **Fix:** `agent_runtime_mount.sh` is state-aware: `404/000`→install exact-ref mount then require
   503; `503`→already mounted-disconnected; `200`→already connected (this host) → verify only.

## Packet (all under `scripts/convergence/`, DRY-RUN by default)

| script | phase | behavior |
|---|---|---|
| `convergence_lib.py` | core | pure safety decisions (build-source enforcement, phase gating, contract classification, 40-char build-meta, secret redaction, rollback manifest) — pinned by tests |
| `build_exact_ref.sh` | STAGE | `git archive` the exact commit → verify Watch/Defense/agent-runtime markers in the **staged source** → hash staged backend; `--apply` builds in the staged tree + stamps build-meta |
| `agent_runtime_mount.sh` | MOUNT | state-aware (fixes the 404 flaw); dry-run prints the plan; `--apply` requires `--ack=MOUNT_AGENT_RUNTIME_EXACT_REF` |
| `agent_runtime_connect.sh` | CONNECT | gated: needs MOUNT-passed **and** a separate `--ack=CONNECT_AGENT_RUNTIME_EXACT_REF`; DSN never printed; requires post `200/read_only/connected:true/agentic_runtime_reader/zero-authority` |
| `rollback.sh` | rollback | captures a redacted manifest (backend hashes, reader env/drop-in presence+mode, service state, Watch packet dir, Defense snapshot) for exact restore |
| `run_dry_run.sh` | orchestrator | read-only: inventory + stage + classify + manifest + final markers. The only command safe to run now. |

## Dry-run result (2026-07-27, read-only)

- **Exact-ref staging proves the fix**: staged source from `03bbf00d` contains **all** markers incl.
  `agent-runtime-command-center-read-api-v1` (absent from the deployed bundle) →
  `frontend_build_source=STAGED_EXACT_REF`, `live_checkout_build_input=NONE`.
- **Agent-runtime posture**: `CONNECTED_READ_ONLY` (200/read_only/connected:true/`agentic_runtime_reader`/
  zero-authority) when the server is settled. **Observation:** the read plane briefly returns 503
  (mounted-disconnected) during a portfolio-server restart before the reader reconnects — CONNECT
  verification must tolerate/retry across a restart, not treat a startup-window 503 as failure.
- All dry-run final markers = safe (see below).

## Validation tests

`tests/test_convergence_packet.py` — 15 tests: build-source staged-only (live-checkout forbidden);
40-char build-meta required; CONNECT blocked before MOUNT and without a separate ack; contract
classification (404/503/200 + malformed); mount/connect contract gates; marker verification; secret
redaction (DSN/password/token/APCA all redacted, nothing leaks); rollback manifest shape. Run:
`TRADE_AI_CI=1 .venv/bin/python -m pytest tests/test_convergence_packet.py -q`.

---

## CLOSEOUT

- **Branch:** `codex/current-main-host-convergence-v2`
- **Start SHA:** `03bbf00d2646a08f63bc9e94f2f35dc406311262`  ·  **End SHA:** _(this commit — additive packet only)_
- **Changed files:** `scripts/convergence/{convergence_lib.py,build_exact_ref.sh,agent_runtime_mount.sh,
  agent_runtime_connect.sh,rollback.sh,run_dry_run.sh}`, `tests/test_convergence_packet.py`, this doc.
  **No M3 / scalp-engine / Watch / Defense source touched.**
- **Test commands/counts:** `pytest tests/test_convergence_packet.py -q` → **15 passed**. Packet
  dry-run: `bash scripts/convergence/run_dry_run.sh` → `final_status|PASS_CURRENT_MAIN_CONVERGENCE_PACKET_DRY_RUN`.
- **Host assumptions:** portfolio-server is a `--user` service on :7777; reader env
  `~/.config/tradeai/agent-read-api.env` (0600) + drop-in `…/portfolio-server.service.d/10-agent-read-api.conf`
  already present; agent-runtime schema + `agentic_runtime_reader` role already provisioned (read plane 200).
- **Unresolved blockers:** (a) deployed static bundle provenance is `UNKNOWN` + missing the agent-runtime
  marker → a real STAGE `--apply` (exact-ref build) is the fix, but installing it is a separate operator
  step; (b) read-plane 503 flaps during server restart — CONNECT verify should retry across restarts.

### Exact commands (dry-run authorized; apply NOT AUTHORIZED)

```bash
# DRY-RUN (read-only, safe now):
bash scripts/convergence/run_dry_run.sh
bash scripts/convergence/build_exact_ref.sh                 # stage + verify only

# STAGE build the candidate into a scratch dir (no host install):
bash scripts/convergence/build_exact_ref.sh --apply         # builds in /tmp stage; does NOT install

# MOUNT  — NOT AUTHORIZED (host mutation; only needed if the plane were 404):
#   bash scripts/convergence/agent_runtime_mount.sh --apply --ack=MOUNT_AGENT_RUNTIME_EXACT_REF

# CONNECT — NOT AUTHORIZED (writes reader env/drop-in + restarts the user service):
#   SHADOW_READER_DSN=… bash scripts/convergence/agent_runtime_connect.sh \
#       --apply --mount-passed --ack=CONNECT_AGENT_RUNTIME_EXACT_REF

# ROLLBACK — capture (read-only) now; restore is NOT AUTHORIZED:
bash scripts/convergence/rollback.sh /tmp/convergence-rollback-manifest.json
#   bash scripts/convergence/rollback.sh --restore /tmp/convergence-rollback-manifest.json   # NOT AUTHORIZED
```

**The PR remains DRAFT and UNMERGED.** No repository-write beyond this branch, no host mutation, no
service restart, no schema write, no schedule change, no provider/agent/broker/order action.

---

## Update 2026-07-27 — hardened, tested static INSTALL + real ROLLBACK RESTORE

The original packet stopped the STAGE build in `/tmp` and `rollback.sh` only *captured* a manifest —
so the static install + revert procedure was neither versioned nor tested. That gap is now closed.

**New `scripts/convergence/static_install.sh <candidate_dist> [--apply]`** — atomically swaps a staged
candidate onto the live host through four gates, in order, each of which can only refuse:
1. **provenance** (`install_precheck`) — candidate `build-meta.json` must carry the full 40-char
   `source_commit`, `frontend_build_source=STAGED_EXACT_REF`, and declare the agent-runtime contract;
2. **markers** — the candidate *bundle* must actually contain the reconciled Watch/Defense/agent-runtime
   surfaces (`REQUIRED_BUNDLE_MARKERS`);
3. **parity** (`swap_parity`) — the candidate must serve every non-hashed file the live dist serves;
   content-hashed `assets/index-<hash>.js|css` are *superseded*, never *dropped*;
4. after a full **backup**, an **atomic rename-pair** swap, then an **HTTP smoke** — and **any** non-200
   route triggers an automatic rollback to the pre-swap dist.
   DRY-RUN by default. Sandbox-testable off-host via `CC_DIST` / `BACKUP_ROOT` / `SKIP_SMOKE` /
   `SMOKE_BASE` / `SMOKE_ROUTES`.

**`rollback.sh --restore <backup_dir> [--apply]`** — validates the backup is a real dist
(`dist_shape_ok`) then atomically swaps it back into the live dist. DRY-RUN validates + prints the plan.

**Tested** — `tests/test_convergence_packet.py` grew from 15 → 27. The new tests drive the *actual*
shell scripts against throwaway dirs: a full apply→restore cycle, auto-rollback when smoke fails
(unreachable `SMOKE_BASE`), a blocked swap that would drop a served file, a rejected bad-provenance
candidate, and a rejected invalid backup — plus unit tests for every new `convergence_lib` decision.
Both scripts were also dry-run against the **real** live dist: all gates `OK`, host untouched.

### Exact commands (build → install → restore)

```bash
# 1) STAGE build the exact-ref candidate (no host install):
bash scripts/convergence/build_exact_ref.sh --apply         # prints candidate_dist|/tmp/...stage.../dist

# 2) INSTALL — dry-run gates first, then apply (backup + atomic swap + smoke + AUTO-ROLLBACK):
bash scripts/convergence/static_install.sh <candidate_dist>            # dry-run: all gates, no change
bash scripts/convergence/static_install.sh <candidate_dist> --apply    # backup → swap → smoke

# 3) RESTORE — revert to any captured backup:
bash scripts/convergence/rollback.sh --restore ~/deploy/backups/cc-dist-<stamp>           # dry-run
bash scripts/convergence/rollback.sh --restore ~/deploy/backups/cc-dist-<stamp> --apply   # apply
```

The install/restore paths are now reproducible and tested, but **applying them to the host remains a
separate, explicitly-authorized operator step.**

---

## Update 2026-07-27 — review-blocker hardening (PR now READY FOR REVIEW, unmerged)

Addressed the six review findings on head `22bd6e6e`:

1. **Doc/description parity** — this doc and the PR description now state *ready for review* (not DRAFT)
   and the correct proof count (**35 tests**, up from 27).
2. **True atomic swap** — new `scripts/convergence/_dirswap.py` performs `renameat2(RENAME_EXCHANGE)`
   (zero interval where the live path is absent). If the filesystem doesn't support it, the scripts
   fall back to two renames and **label the swap `two-rename-nonatomic-window`** rather than claiming
   atomicity. The swap mode is printed every run.
3. **Verified rollback** — on a failed post-install verify, the auto-rollback now confirms the live
   dist is actually the pre-swap bundle (`meta_sc == pre_swap_source_commit`) before printing
   `rolled_back`; if the restore didn't take, it emits `CRITICAL_ROLLBACK_FAILED_MANUAL_INTERVENTION`
   instead of a false success.
4. **Bound restore** — install writes a `cc-dist-<stamp>.manifest.json` recording the backup's
   `source_commit` and a canonical `dir_content_hash`. `rollback.sh --restore` accepts `--manifest`
   / `--expect-commit` and refuses (`BLOCKED_BACKUP_INVALID`) if the backup's commit or content hash
   doesn't match what was captured. One `dir_content_hash` implementation is shared by both sides.
5. **Real post-install proof** — verification no longer trusts HTTP 200 alone: it also confirms the
   **served** `build-meta.json` carries the installed `source_commit` (catches a stale/cached bundle)
   and that the agent-runtime read plane is still `200 / read_only / connected / zero-authority` with
   the exact reader role. Same checks run after a restore.
6. **Stale preview processes** — four orphaned `vite preview` trees from `/tmp/command-center-review-
   validation.*` (~3 days old, `ppid=1`) were identified for a separate, confirmed process-cleanup.

New tests drive the real scripts through: atomic `_dirswap` exchange, stale-served-build-meta
auto-rollback, served-meta + read-plane success, and a restore refused on `--expect-commit` mismatch.
Both scripts were dry-run against the **real** live dist: all gates `OK`, host untouched.

**PR #238 is READY FOR REVIEW and still UNMERGED. Applying to the host remains a separate authorized step.**
