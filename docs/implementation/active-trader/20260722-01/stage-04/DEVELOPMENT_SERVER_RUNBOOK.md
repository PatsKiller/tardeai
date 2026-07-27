# Development Server Runbook — Stage 4

The read API dev server is **manual-only**: no systemd unit exists, nothing is enabled
at boot, no proxy/firewall/Docker change was made. Default state is DISABLED.

## Start (manual, loopback only)
```bash
cd /home/johnclaw/worktrees/active-trader-next
export BWS_ACCESS_TOKEN="$(cat ~/.openclaw/credentials/bws_lab_token)"
export ACTIVE_TRADER_READ_API_DSN="$(bws secret list 1b0a478d-87a3-4e2d-85f6-b4900015afa0 \
  | python3 -c "import sys,json;[print(s['value']) for s in json.load(sys.stdin) if s['key']=='ACTIVE_TRADER_READ_API_DSN']")"
unset BWS_ACCESS_TOKEN
export ACTIVE_TRADER_READ_API_ENABLED=true
export ACTIVE_TRADER_ENV=SHADOW                # or SIMULATION; LIVE refused
export ACTIVE_TRADER_TEST_IDENTITY=dev-operator
# lab cluster must be running: bash scripts/active_trader/provision_test_db.sh
.venv-or-prod-venv/python scripts/active_trader/read_api.py --port 8134
```
Requests need the header `x-at-test-identity: dev-operator`.

## Startup gates (all enforced in code, all tested)
1. `ACTIVE_TRADER_READ_API_ENABLED=true` — otherwise exits WITHOUT a listener (rc 0)
2. `ACTIVE_TRADER_ENV` ∈ {SHADOW, SIMULATION} — LIVE → rc 2
3. bind host ∈ {127.0.0.1, localhost, ::1} — anything else (0.0.0.0, ::, hostnames) → rc 2
4. `ACTIVE_TRADER_READ_API_DSN` present — missing → rc 2 (no fallback)
5. ReadStore guard — production DB name/port refused at connect

## Port
Ruled preference 8134 was free and is in use. If ever occupied, pass `--port <n>`
(loopback rule still applies) and record the value in the stage evidence.

## Stop
Ctrl-C (or TERM). Verify cleanup: `ss -tlnp | grep 8134` → empty;
`pgrep -f read_api.py` → nothing.

## Smoke evidence (2026-07-22)
Bind 127.0.0.1:8134 · health/version/accounts/brokers/brokers/capabilities/rejections/
features/parity all 200 env=SHADOW · POST → 405 · after TERM: 0 listeners, 0 processes,
0 units installed.
