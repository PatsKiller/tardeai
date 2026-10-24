# WP-27: continuous scanner root reconciliation

Status: DRAFT — operator packet locally tested; installed change and natural-run proof pending
as_of: 2026-10-24T02:43:06Z
Measured at: origin/main `fe826d2ecdb59a19bd7c510c8923c7b743f06eee`; worker `codex-wp27-20261023`

The worker prepared the CURRENT-root system-unit packet without changing the installed service, scheduler, operative registry or release code. The operator must run its privileged preview and apply. No live-server request, daemon execution, broker call or credential read was used for verification.

| Question | Observed evidence | Result |
|---|---|---|
| Which root does the base system unit declare? | Partial `systemctl cat tradeai-continuous.service`: canonical WorkingDirectory and canonical `linux_launchers/run_continuous.sh` ExecStart | Canonical-root regression remains |
| What does its protected singleton override do now? | `singleton.conf` returned Permission denied; read stopped | NOT_MEASURED; privileged exact-command preview required |
| What release is CURRENT on disk? | Symlink and BUILD_SHA: `d0c8b70d8-main-exact-phase2-20261023-182515`, `d0c8b70d8d915098094aa7180f25d6b0b0e0cffe` | Filesystem release identity only; no HTTP/served-identity claim |
| Does promote restart this system service? | `restart_root_frozen_units` uses `systemctl --user`; default list has eight other user units | No; use existing next natural start or explicit operator restart |
| Is the system scheduler represented accurately? | Existing `tradeai-continuous` row is PAUSED, citing historical user-manager state and omitting scope | Scope drift; current system timer state NOT_MEASURED |

## Delivered behavior

The [packet README](packets/continuous-from-current-20261023/README.md) contains the exact sudo preview/apply/rollback/check commands. The drop-in points WorkingDirectory and launcher at CURRENT, explicitly pins PROJECT_ROOT there and preserves the cross-process singleton lock. It does not reset unrelated unit settings or enable any timer.

An operator preview captures only safe systemd metadata, unit hashes and release/store-path identity into root-private receipts. Installation requires that exact unexpired preview, a TTY phrase and an unchanged CURRENT/configuration. It refuses every weekday 04:00–16:15 ET, conservatively including holidays, with DST and boundary rechecks. There is no clock override in the CLI.

Installation without restart is recorded as pending runtime proof. With an explicit operator restart, a pass requires an active stable MainPID, stable process start time and cwd equal to the physical verified CURRENT release. Wrong effective commands, overrides, stale roots and missing runtime proof produce failure receipts. Recovery restores only the packet's prior drop-in and archives all displaced bytes.

The preview also produces a review-only, explicitly system-scoped registry proposal based on observed timer state. No operative registry row was invented or promoted. The registry follow-up and runtime/business-output acceptance remain pending operator evidence.

## Validation

The fixture-only test suite passed **39 tests**. It covers EDT/EST boundaries, holiday conservatism, no collection/write during a blocked window, changed release/config/payload, stale/future preview, unknown command/user/root, preserved flock, effective command override, PID/cwd and PID-race failures, pending versus running statuses, rollback preview, archive preservation, managed-file drift and non-TTY refusal. Tests never instantiate a live systemd connection; process/file-adapter tests use temporary filesystem fixtures.

New test: `tests/test_continuous_current_packet_20261023.py`. Its canonical CI gate is `config/ci_gates/continuous_current_packet_20261023.json`, generated with `scripts.lib.ci_gates.render`.

## Package integrity

The packet manifest `SHA256SUMS` has SHA-256 `bc70b1a871e262a73d9ec611a93a3da92f37e9255ee334476d34f9719d565583`. It binds the README, Python adapter, drop-in and all three shell entry points. Compare this value before `sha256sum -c SHA256SUMS`.

## Remaining acceptance

1. Operator reviews a successful privileged preview. The protected override must match the packet's exact expected singleton form; otherwise stop and rebuild from reviewed operator evidence.
2. Operator applies, choosing either the next existing natural start or an explicit outside-window restart; records install and PID-cwd proof.
3. Coordinator lands a reviewed system-scope registry reconciliation from the captured proposal, preserving the historical user-timer row.
4. Correlate the next actual scheduled scan, business output and consumer readback with its run and release identity. Neither a configured unit nor a cwd receipt substitutes for these.

No PR CI, merge, deployment, operator approval or runtime success is claimed by this local delivery.
