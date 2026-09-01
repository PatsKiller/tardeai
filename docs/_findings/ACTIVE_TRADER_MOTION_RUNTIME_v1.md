# Active Trader Motion Runtime v1

Status:      HISTORICAL
as_of:       2026-07-29T09:39:38-04:00
Measured at: efcc51365 / not measured

## Status

Repository implementation only. The service unit is **default-disabled**, is not enabled by this change, and carries no execution authority. Host installation, activation, restart, and HTTP proof require an operator with production-host access.

## Runtime boundary

The runtime repeatedly gathers account-unbound candidate and monitored-position evidence, reuses one `T2LeaseManager` plus per-symbol `MomentumExitPolicy` instances, appends the resulting read-only snapshot, checkpoints deterministic policy state, and records a heartbeat.

It does **not** select an account, environment, broker, venue, adapter, route, quantity, or execution authority. `EXIT_SIGNAL` remains evidence only.

Write scope is limited to:

- `motion_journal.jsonl`;
- `motion_runtime_state.json`;
- `motion_runtime_heartbeat.json`;
- `motion_runtime.lock`.

## Guarantees

- Single-instance advisory lock using `flock`.
- T2 lease and momentum-exit hysteresis state restored across process restarts.
- Expired T2 leases and cooldowns are discarded on restore.
- Adaptive cadence: 5 seconds active, 10 seconds near-fire, 30 seconds idle.
- Bounded error backoff: 5, 10, 20, then 30 seconds maximum by default.
- Producer exceptions append no fabricated snapshot; the GET naturally becomes stale.
- Atomic state and heartbeat replacement.
- SIGTERM/SIGINT graceful stop.
- Heartbeat includes PID, process start, last success, restore evidence, counts, bounded write scope, and zero authority.

## Default-disabled systemd installation

The unit contains:

```text
ConditionPathExists=/etc/tardeai/enable-active-trader-motion
```

Therefore copying or enabling the unit does not start the producer until an operator deliberately creates the marker.

Installation commands for an authorized host operator:

```bash
sudo install -m 0644 config/systemd/tradeai-active-trader-motion.service \
  /etc/systemd/system/tradeai-active-trader-motion.service
sudo install -m 0640 config/systemd/active-trader-motion.env.example \
  /etc/tardeai/active-trader-motion.env
sudo systemctl daemon-reload
```

Do not create the enable marker or start the service until configuration paths and data sources are reviewed.

## Activation and data-only proof

After review:

```bash
sudo install -d -m 0750 /etc/tardeai
sudo touch /etc/tardeai/enable-active-trader-motion
sudo systemctl enable --now tradeai-active-trader-motion.service
sudo systemctl status --no-pager tradeai-active-trader-motion.service
```

Initial proof:

```bash
PYTHONPATH=scripts python3 -m active_trader.motion_host_proof \
  --endpoint http://127.0.0.1:8000/api/v3/active-trader/motion
```

The proof requires:

- a journal exists;
- runtime heartbeat and checkpoint contracts are valid;
- heartbeat and snapshot are fresh;
- direct and HTTP responses are read-only and zero-authority;
- the journal's size, modification time, and SHA-256 are unchanged by GET.

Restart recovery proof:

```bash
OLD_PID="$(jq -r .pid data/active_trader/motion_runtime_heartbeat.json)"
sudo systemctl restart tradeai-active-trader-motion.service
sleep 6
PYTHONPATH=scripts python3 -m active_trader.motion_host_proof \
  --endpoint http://127.0.0.1:8000/api/v3/active-trader/motion \
  --require-restored-state \
  --previous-pid "$OLD_PID"
```

A PASS proves the new process loaded a valid checkpoint, has a different PID, produced a fresh snapshot, and GET did not write the journal.

## Rollback

```bash
sudo systemctl disable --now tradeai-active-trader-motion.service
sudo rm -f /etc/tardeai/enable-active-trader-motion
```

Removing the unit does not alter the policy modules or endpoint contract. Runtime JSON/JSONL files may be retained for forensic review or removed separately after the service is stopped.
