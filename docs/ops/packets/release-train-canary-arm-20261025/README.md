# Release train: arm the 18:00 canary with no per-release grant (2026-10-25)

```
Status:    PR (shared-infra). Protected surfaces: ships by the manual release path (arming packet L.1), never by a train.
Operator:  "It needs to work without grant. It's a perpetual grant." (2026-10-25)
Packet:    docs/ops/packets/release-train-arming-20261021/README.md I.3 step 3, I.4 PR 3, §K
Authority: MBI_BEHAVIOR = 0. No broker, order or credential path. Broker / Active Trader code stays held.
```

## What the PR changes

| Gate | Before | After |
|---|---|---|
| `release_grant_binding.CAPABILITY_BINDING_STATUS` (§K) | `PROPOSED`: the deploy's `release_grant_preflight` accepts a train `prepare`/`promote` only with a guard `release-write` grant naming the batch PR | `ACTIVE`: with no binding grant, a `release-train-<id>` campaign is accepted on the signed, RESERVED host capability (the guard ledger is not consumed) |
| Controller `_cap_effect` | never wrote the reservation token, so even an ACTIVE binding refused `TOKEN_MISSING` | writes `<state>/trains/<id>/capability/{prepare,promote}_release.rcap` (mode 600) right after `reserve()`, live runs only; a write failure refunds the reservation before the effect |
| `config/release_train_policy.json` | `PROPOSED`, `armed: false`, every window disabled | `ACTIVE`, `armed: true`, 18:00 enabled; 00:00 / 06:00 / 08:00 disabled |
| `release_train_classify.validate_policy` | refused `armed: true` or any enabled window (the classifier would then hold every PR) | accepts armed + ACTIVE with windows enabled strictly in `enable_order` (18:00 first) |
| Allowlist `release-train-request-1800` `live_arg` | `["--append", "--shadow-only"]` | `["--append"]` (the other three slots unchanged) |

## The host step this PR cannot take (operator or the delegated release agent)

The request that actually fires today is the host timer `tradeai-release-train-request@1800.timer`. Its template
service hard-codes `--shadow-only`, so after the PR is released the 18:00 request is still shadow until this drop-in
is installed for the **1800 instance only**:

```bash
CUR=~/trade-ai-releases/portfolio-server/CURRENT
D=~/.config/systemd/user/tradeai-release-train-request@1800.service.d
mkdir -p "$D"
install -m 644 "$CUR/docs/ops/packets/release-train-canary-arm-20261025/tradeai-release-train-request@1800.service.d--canary-live.conf.proposed" \
  "$D/canary-live.conf"
systemctl --user daemon-reload
systemctl --user cat tradeai-release-train-request@1800.service | grep ExecStart   # last ExecStart has no --shadow-only
```

- Dry run first: `cd $CUR && .venv/bin/python scripts/release_train_window_request.py --window 1800 --dry-run`
  (off-window it reports `shadow_reason: off_window`; at 18:00 it reports `shadow: false` when every gate is green).
- Rollback: `mv "$D/canary-live.conf" "$D/canary-live.conf.archived-$(date -u +%Y%m%dT%H%M%SZ)"` and
  `systemctl --user daemon-reload`. STOP (`release_control_cli.py stop`) and `revoke` keep working at any time.

## What still needs the operator

- Changes classified `needs_operator`, `held` or `blocked` never ride (policy, AGENTS, guard/CI, scheduler, migrations,
  auth, broker / Active Trader, the train's own files, deletions, oversized changes). They release by the manual path.
- The other windows (packet J), each by its own reviewed PR and host `change-scope`.
