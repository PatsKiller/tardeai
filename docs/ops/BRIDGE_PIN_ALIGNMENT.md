```
Status: ACTIVE
as_of: 2026-09-18T16:50:00-04:00
Measured at: audit docs/agent-controls-implementation-audit.md
  portfolio-server pin: 71535687d-main-exact-phase2-20260918-155627
  bridge pin (pre-align): 0162d0f19-main-exact-phase2-20260914-200906
Canonical repo path: docs/ops/BRIDGE_PIN_ALIGNMENT.md
Authority: AGENTS.md §10 · FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md §7 · cio_phase2_exact_main_deploy.sh
Supersedes: none (records the 2026-09-18 pin-drift finding and the fix path)
```

# Governed bridge pin alignment

## Problem

`cio-governed-bridge.service` sets `WorkingDirectory=…/portfolio-server/CURRENT`, but the
process resolves that symlink **once at start**. A later `promote` moves `CURRENT` and
restarts `portfolio-server` (and, until this change, only `tradeai-health-agent` by
default). The bridge stays active on the **previous concrete release**.

Observed 2026-09-18:

| Unit | Process cwd |
|---|---|
| `portfolio-server` | `…/71535687d-main-exact-phase2-20260918-155627` |
| `cio-governed-bridge` | `…/0162d0f19-main-exact-phase2-20260914-200906` |

Paid-lane code, caps, and logging can therefore disagree with the served release.

## Permanent fix (this PR)

1. Default `TRADEAI_CURRENT_BOUND_UNITS` includes `cio-governed-bridge.service`.
2. Repo unit file runs from `…/portfolio-server/CURRENT` (not the hub checkout).
3. Promote still **reads back** each bound unit's `/proc/<pid>/cwd` and warns on mismatch.

Live restart of an already-drifted bridge is still **operator / release-write** territory.
Merging this PR alone does not move the live pin.

## One-shot align (operator, after merge — or immediately if granted)

Dry-run first (print only; no mutation):

```bash
PS_PID=$(systemctl --user show -p MainPID --value portfolio-server.service)
BR_PID=$(systemctl --user show -p MainPID --value cio-governed-bridge.service)
echo "portfolio-server cwd: $(readlink /proc/$PS_PID/cwd)"
echo "bridge cwd:           $(readlink /proc/$BR_PID/cwd)"
echo "CURRENT:              $(readlink -f ~/trade-ai-releases/portfolio-server/CURRENT)"
```

If bridge cwd ≠ CURRENT (or ≠ portfolio-server cwd), install the unit from the served
release if needed, then restart and re-read:

```bash
# Optional: refresh the installed unit from the served release (daemon-reload after).
SRC=~/trade-ai-releases/portfolio-server/CURRENT/config/systemd/user/cio-governed-bridge.service
test -f "$SRC" && install -m 0600 "$SRC" ~/.config/systemd/user/cio-governed-bridge.service
systemctl --user daemon-reload

systemctl --user restart cio-governed-bridge.service
sleep 3
BR_PID=$(systemctl --user show -p MainPID --value cio-governed-bridge.service)
readlink /proc/$BR_PID/cwd
# must equal:
readlink -f ~/trade-ai-releases/portfolio-server/CURRENT

# Health (POST-only historically returned 501; JSON /health is live since 2026-09-14)
curl -fsS --max-time 5 http://127.0.0.1:8766/health
ss -ltn | grep 8766
```

Compatible pin rule: **bridge process cwd == portfolio-server process cwd == resolved CURRENT**.
Do not invent a second "bridge-only" release directory.

## Verification after the next promote

Promote log must show:

```
cio-governed-bridge.service re-resolved → <same dir as CURRENT>
```

Any `WARN … cwd=… != …` means the bridge is still frozen — treat as a failed promote for
the paid lane even if `portfolio-server` health passed.

## Override

Operators may still set `TRADEAI_CURRENT_BOUND_UNITS` explicitly. Omitting the bridge
re-introduces this class of drift; do that only with a documented reason.

## Soak ledger (control-3)

After live align and after every promote, record an observation:

```bash
python3 scripts/record_bridge_pin_soak.py --dry-run   # quote output
python3 scripts/record_bridge_pin_soak.py            # append ledger
python3 scripts/record_bridge_pin_soak.py --status    # streak / need=3
```

Production Ready on pin consistency requires `soak_ready=YES` (consecutive match streak ≥ 3 across promotes).
Ledger default: `~/trade-ai-releases/persistent-state/data/runtime/bridge_pin_soak.jsonl`
