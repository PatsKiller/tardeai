# Current-Main Host Convergence Packet — dry-run-first, exact-ref (2026-07-27)

**Status:** DRAFT PR, dry-run only. Nothing applied. No agents/schedules/models/providers/proposals/
orders/execution. M3 source + config unchanged. **Base:** `03bbf00d2646a08f63bc9e94f2f35dc406311262`.

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
