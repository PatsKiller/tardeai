# Phase 204A — secrets_state_backup Failure Snapshot

Status:      HISTORICAL
as_of:       2026-06-05T12:08:22-04:00
Measured at: efcc51365 / not measured

- **Failing command:** `bash scripts/backup_secrets_state.sh` (NO argument), invoked by the OLD
  bundled controller (Phase 202C). **rc=2.**
- **stderr:** `usage: scripts/backup_secrets_state.sh {env|data}` (script line 29: `*) ... exit 2`).
- **Script:** `TARGET="${1:-}"`; requires `env` or `data`; exits 2 otherwise.
- **New or legacy?** NEW — introduced by the bundled controller's wrong call. The **legacy cron works**:
  it invokes the script TWICE with args — `backup_secrets_state.sh env` and `... data`.
- **Failed under legacy path too?** NO (legacy passes args). **Only under controller (no-arg)?** YES.
- **gog present?** YES — `/home/johnclaw/.local/bin/gog` v0.12.0. Script checks `[ -x "$GOG" ]`.
- **Auth/keyring/Drive/network?** NOT the cause — the script never reached the gog calls (it exited at
  arg-parse before any upload). Legacy uses the same gog/auth daily successfully.
- Timestamp: 2026-06-05T15:43:27Z (bundled apply). Log: portfolio_20260605_151306.log.
