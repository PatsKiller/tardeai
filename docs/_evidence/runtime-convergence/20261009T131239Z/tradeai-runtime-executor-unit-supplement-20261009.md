# Executor unit and policy supplement — proposed only

**SOURCE_ONLY proposal; OBSERVED_HOST facts below. No grant requested, installed unit edited, service restarted, workflow changed, model called or policy ratified by this review.** This supplement does not authorize a runtime action.

The proposed [repository packet](/home/johnclaw/tradeai-wt-runtime-n8n-host-recovery-20261008/docs/_evidence/runtime-convergence/20261009T131239Z/22-updated-proposed-grant-packet.md) remains conditional on final local acceptance, exact PR/main CI and native approvals. Its earlier source13527203/a9 release bindings are historical; its integration supplement names b1c1a9157. Read-only HEAD was `76e83b03c02971710dbaaac7bda7772c0fcba825` during this review, not a final publication/deployment identity. Rebind all PENDING fields after source freeze. The older `/tmp/tradeai-runtime-updated-grant-packet-20261009.md` still proposes cron4; use the repository's corrected **cron13** budget (nine selected workflow retirements and four exact cron restorations).

## Measured executor installation

At **2026-10-09T15:02:49.067429Z**, read-only `systemctl --user show tradeai-n8n-run-executor.service` and `/proc/<MainPID>` inspection proved the following; [redacted metadata](/tmp/tradeai-runtime-executor-unit-readonly-20261009.json) preserves the observation. The repeated EnvironmentFiles property was read back separately and retained as two paths, never file contents.

| Item | OBSERVED_HOST result |
|---|---|
| CURRENT / process cwd | `/home/johnclaw/trade-ai-releases/portfolio-server/3b5c24856-main-exact-phase2-20261009-095833` |
| CURRENT SHA | `3b5c248569908adfad9a60ca895e0fa9b2aa2c49` |
| Unit | `tradeai-n8n-run-executor.service`, loaded, active/running; PID391816; started10:34:31EDT |
| Installed fragment | `/home/johnclaw/.config/systemd/user/tradeai-n8n-run-executor.service`, regular file |
| Drop-ins / reload / PassEnvironment | None / `NeedDaemonReload=no` / empty |
| Unit SHA-256 | `f5b93014f031db140954af0129c3c41d8d1113a46ca606452d284060a9b6718f` |
| Source equality | Installed fragment = CURRENT source unit = main3b source unit = reviewed candidate source unit, byte for byte |
| Unit environment names | `TRADEAI_STATE_ROOT`, `TRADEAI_VENV_PYTHON`, `PROJ`, `PY`, `LLM_DEFER_OFFPEAK`, `TRADEAI_ENV`, `BLIND_REVIEW_LANES`; all seven present in the running process |
| Non-secret parity | All five explicit cron-parity assignments match the running process; no values from environment files or secret variables were emitted |

Source file: `config/systemd/user/tradeai-n8n-run-executor.service`. Commands: `git diff 3b5c248569908adfad9a60ca895e0fa9b2aa2c49 HEAD -- config/systemd/user/tradeai-n8n-run-executor.service` returned no difference; SHA-256 computed independently for installed/CURRENT/candidate bytes. The “nine new env passthroughs” premise is **not established for these unit versions**: there are five explicit parity additions and two pre-existing assignments, with no `PassEnvironment=` names. The executor code's lane-specific child-secret filtering is separate from installing a systemd unit.

**Required additional executor-unit installation scope on this observation: none; minimum additional native uses: config-write0, service0.** Preserve the matching unit and existing environment files. The canonical deploy already reloads and rebinds the executor in its explicit CURRENT-bound allowlist. Copying a matching unit or adding a duplicate drop-in would add an unnecessary host change.

## Conditional installation packet if the final exact source differs

This fallback is not executable until a fresh comparison proves a difference and the operator reviews its exact diff. If source remains equal, omit it entirely.

1. Bind `DEPLOY_MERGE_SHA`, exact prepared release, prior CURRENT3b or its fresh replacement, installed fragment SHA, actual drop-in paths/hashes, loaded metadata, prior unit bytes, final source-unit SHA and an explicit approved environment-name delta. Refuse an unspecified nine-variable set, symlink fragment, unrelated drift, changed ExecStart/root/resource/restart/send semantics, new environment file or credential reach. Values are source constants or existing host-managed files; no secret rendering, value dump or provider call.
2. Exact possible source: `<PREPARED_EXACT_RELEASE>/config/systemd/user/tradeai-n8n-run-executor.service`. Exact possible destination: `/home/johnclaw/.config/systemd/user/tradeai-n8n-run-executor.service`. Prefer a regular-file replacement consistent with the repository unit convention; **no new drop-in is proposed**. Preserve enablement and all other units. The committed unit explicitly describes installation as operator-owned; the operator performs it under the approved installation packet.
3. Minimum conditional config-write budget: **30m / two uses**, one named forward unit replacement and one conditional restoration of the captured prior fragment. Bind both file hashes, destination, merge SHA and packet hash in the native reason. Existing packet config-write15 would require an explicit revised maximum17 only if this conditional installation becomes necessary. Confirm actual command-level guard consumption before requesting; do not wrap commands to evade classification.
4. Install after the nine selected workflows are inactive and their accepted host work is drained, but before canonical promotion. The already-approved canonical promotion executes daemon-reload and executor rebind; canonical rollback repeats them. **No extra service use is needed if those exact existing transactions cover the reload/restart.** Any standalone reload/restart, service enablement, new drop-in or additional consumed use needs a separately reviewed native reason/budget before execution; none is authorized here.
5. After promotion, prove loaded unit hash/metadata, exact process cwd/interpreter and required environment-name/parity checks without exposing values. On failure restore only the captured executor fragment, then canonical rollback to the freshly captured prior release and verify pins. Preserve the separate safe scheduler recovery: do not reactivate nine unsafe workflows or re-retire restored cron to match an older release registry. Record any resulting registry drift honestly.

## Governing policy and boundaries

Current main's AGENTS3.0.0 is **PROPOSED / Effective-DatePENDING**; its header makes **2.0.1 governing** until exact policy ratification. Read §9.3, §10, §17 and the unreplaced §23.2: scheduler edits require operator grants; units/registry-bearing config require config-write; a deploy does not install user units. The proposal's Agent-node, bridge-token, egress and routing language confers no activation, secret, model or provider authority. This packet ratifies nothing and adds no writer or scheduler.

Preserve the repository packet's exact nine IDs, unpublish/restart/drain before four receipt-based single-line restorations, mutable recovery registry outside immutable CURRENT, and exact-source promotion only after those restorations. No blanket shadow disable, DB workflow replacement, queue replay, broker/order/stop/risk/send-authority change or automatic policy approval. MFA OFF remains the explicit operator exception. No model selection/provider calls until the operator names a model. Ollama retirement is a separate privileged keyboard-only operator action; no remote sudo.

This review performed only reads and wrote this temporary proposal. It found no executor-unit source/installed/loaded drift in its bounded observation. **Historical grant provenance for the existing installation, and absence of unrelated host changes outside this observation, are NOT_MEASURED**; matching bytes do not prove either. The full corrective tranche's grants, CI, merge, deployment and natural acceptance remain parent-owned pending receipts.

PLATFORM_RUNTIME_SOURCE_ACCEPTANCE_BLOCKED
