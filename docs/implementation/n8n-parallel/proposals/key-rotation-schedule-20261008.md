# Weekly key rotation schedule — PROPOSAL (operator cron grant), 2026-10-08

Status: PROPOSAL. Nothing in this PR schedules anything, edits the crontab, or touches
`config/lane_registry.json`. Every action below is an operator step under a grant.

## Why

`docs/architecture/n8n/ADR_COORDINATION_SECRETS.md` (ACCEPTED) requires `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N`
and `TRADEAI_N8N_RELAY_BEARER` to be rotated weekly by `scripts/secrets/rotation_daemon.py`.
`config/secret_registry.yaml` lists both (`class: self_minted`, `max_age_days: 7`, restart targets
`tradeai-n8n-run-relay` / `tradeai-n8n-coordination-gateway`). The daemon is unscheduled
(`10-eligibility-and-secrets-20261007.md` §6 and item 17; `09-live-audit-20261007.md`), so the ADR's
weekly cadence is a promise with no clock behind it.

This PR gives the daemon a hermetic `--dry-run` (`--registry`, `--state`, `--now`) and a pure
`select_due()` so the selection can be proven without a Telegram send or a state write
(`tests/test_secret_rotation_schedule_20261008.py`).

## Dry-run evidence (tmp copy of the registry; both keys stamped rotated 2026-10-08, evaluated at day 8)

```
$ $PY scripts/secrets/rotation_daemon.py --dry-run --registry <tmp>/registry.yaml --state <tmp>/state.json --now 2026-10-16T09:30:00Z
{"mode": "dry-run", "now": "2026-10-16T09:30:00+00:00", "considered": 21, "would_send_telegram": true, "state_written": false}
due total 21
[
 {
  "name": "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N",
  "class": "self_minted",
  "max_age_days": 7,
  "age_days": 8,
  "restart_targets": ["tradeai-n8n-run-relay", "tradeai-n8n-coordination-gateway"],
  "action": "nag_self_minted_run_rotate_py_generate",
  "command": "scripts/secrets/rotate.py TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N --generate"
 },
 {
  "name": "TRADEAI_N8N_RELAY_BEARER",
  "class": "self_minted",
  "max_age_days": 7,
  "age_days": 8,
  "restart_targets": ["tradeai-n8n-run-relay"],
  "action": "nag_self_minted_run_rotate_py_generate",
  "command": "scripts/secrets/rotate.py TRADEAI_N8N_RELAY_BEARER --generate"
 }
]
nag_lines for n8n: ['• `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N` self_minted overdue — run rotate.py --generate when window allows',
                    '• `TRADEAI_N8N_RELAY_BEARER` self_minted overdue — run rotate.py --generate when window allows']

$ ... --now 2026-10-14T09:30:00Z      (day 6)
n8n due at day 6: []
```

Read it exactly: at day 8 the daemon **selects** both keys and **would do** one thing — send one Telegram
line per key saying "run rotate.py --generate". It does not rotate. See the next section.

Also measured: `due total 21`. The state file `data/runtime/rotation_daemon_state.json` does not exist on
the host and nothing writes `last_rotated_at` (`rotate.py` does not stamp it), so every non-`BWS_*` registry
key reads as never rotated (age 999 d). The first live run will nag for all 21 keys, not two. That is the
truth of the registry today, not a bug in the selection.

## What the daemon cannot do (exact missing capabilities — not faked here)

1. **The daemon never mints or writes a secret.** For `self_minted` it only nags ("run rotate.py
   --generate when window allows"); the docstring's safety rule is "do NOT auto-rotate without explicit
   flag", and no such flag exists. The rotation itself is `scripts/secrets/rotate.py <NAME> --generate`
   → `scripts/secrets_admin.set_secret` → the Bitwarden Secrets Manager CLI `$HOME/.local/bin/bws` with
   the write token at `$HOME/.openclaw/credentials/bws_write_token`. A cron-run daemon holding the SM
   write token is an AGENTS.md §17 decision the ADR did not make. **Until it is made, weekly rotation of
   these two keys is an operator runbook step triggered by the nag, not an automated rotation.**
2. **No `*_PREVIOUS` overlap exists for either key.** The ADR's two-step rotation needs: (a) the gateway to
   accept `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N_PREVIOUS` — `scripts/n8n_coordination_gateway.py` honours
   `TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS` for the dispatch key only; (b) the relay to accept
   `TRADEAI_N8N_RELAY_BEARER_PREVIOUS` — `scripts/n8n_run_relay.py` `_auth` compares one bearer;
   (c) `scripts/secrets/render_env.py` to move the old value onto `_PREVIOUS` at render — it does not.
   Today a rotation is a hard cutover: between the relay restart and the operator updating the n8n
   Header-Auth credential every n8n `POST /run` is refused `relay_bad_bearer` (which the new fan-in
   `relay:auth_failures` finding will report as a P2 — expected during the window, not a fault).
   Those three are relay / gateway / render_env changes owned by other streams; this PR does not touch them.
3. **`rotate.py` does not stamp `data/runtime/rotation_daemon_state.json`** (`<NAME>.last_rotated_at`), so
   the daemon cannot tell a rotated key from a never-rotated one. Follow-up (small, not in this PR):
   `rotate.py` writes `last_rotated_at` on a successful `set_secret`.

## Proposed cron line (operator installs; the crontab header already defines `PROJ`, `PY`, `TRADEAI_ENV`)

```
# Secret rotation nag — ADR_COORDINATION_SECRETS weekly keys (daemon docstring: 05:30 ET daily). PROPOSAL key-rotation-schedule-20261008.md
30 5 * * * cd $PROJ && flock -n /tmp/rotation_daemon.lock $PY scripts/secrets/rotation_daemon.py >> logs/rotation_daemon.log 2>&1
```

Daily, not weekly, on purpose: the daemon is the clock that notices a 7-day key at day 7; a weekly cron
would let a key reach day 13 before the first nag. The Telegram nag repeats daily for `self_minted`
(no 3-day suppression for that class) until the operator rotates.

## Proposed `config/lane_registry.json` row (PROPOSAL — a registry edit goes through the registry lock, Agent 2's W1/W2 queue)

```json
{
  "lane_id": "secret-rotation-daemon",
  "owner": "platform",
  "scheduler": {
    "kind": "cron",
    "expression": "30 5 * * * scripts/secrets/rotation_daemon.py",
    "match": "scripts/secrets/rotation_daemon.py"
  },
  "expected_cadence_hours": 24.0,
  "state": "NEVER_SCHEDULED",
  "state_since": "2026-10-08",
  "state_reason": "ADR_COORDINATION_SECRETS weekly keys need this daemon as their clock; cron line is an operator grant (proposals/key-rotation-schedule-20261008.md). Flip to ACTIVE in the same change that installs the line.",
  "reason_confidence": "ESTABLISHED",
  "reason_evidence": "crontab -l 2026-10-08 has no rotation_daemon line; 10-eligibility-and-secrets-20261007.md item 17",
  "output_signal": {"kind": "file_mtime", "path": "data/runtime/rotation_daemon_state.json"},
  "note": "Nag-only: never mints, never writes SM, never restarts. Live run writes rotation_daemon_state.json every day (the output signal) and sends one Telegram nag per due key."
}
```

The output signal is the state file the live run writes on every pass (`nothing_due` included), so SILENT
means the cron stopped firing, not that nothing was due.

## Grant text (the operator approves this wording; fill the PR number and head SHA from the PR header)

> **cron grant** — install the one line above into the user crontab, reason `PR #<N> sha <head sha>`
> (`guard` matches that form only; `pr:N` never matches). Scope: one line, `scripts/secrets/rotation_daemon.py`,
> `30 5 * * *`, `flock -n /tmp/rotation_daemon.lock`, log `logs/rotation_daemon.log`. No unit, no secret value,
> no SM write. Follow-on in the same grant: Agent 2 adds the `secret-rotation-daemon` row above as `ACTIVE`
> with `state_since` = install date (W2, registry lock).

Separately decided (§17, not this grant): whether the daemon may hold the SM write token and rotate
`self_minted` keys unattended; and the `_PREVIOUS` overlap support in relay / gateway / render_env.

## Weekly operator runbook for the two keys (until capabilities 1–2 exist)

1. Off-market window. `$PY scripts/secrets/rotate.py TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N --generate` then the
   same for `TRADEAI_N8N_RELAY_BEARER` (values never shown; `verify_probe` is `null` for both, so the probe prints `{"ok": true, "probe": null, "skipped": true}` — nothing verifies the new value except step 4).
2. `$PY scripts/secrets/render_env.py --now` (the `sm-render` lane does this every 4 h anyway), then
   `scripts/secrets/staged_restart.sh` for `tradeai-n8n-coordination-gateway` and `tradeai-n8n-run-relay`.
3. Update the n8n Header-Auth credential with the new bearer (the ONE n8n credential; ADR invariant 5).
4. Verify: relay `GET /status` returns 200 with the new bearer; the next fan-in receipt's `relay_counts`
   stops rising; `relay:auth_failures` (if it opened during the window) clears on the next receipt.
5. Until follow-up 3 lands, write `last_rotated_at` for both keys into `data/runtime/rotation_daemon_state.json`
   by hand or the nag keeps firing.
