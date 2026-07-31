# Deploy — Agent Runtime Operator UX

Sync from the guardrails worktree into the **live portfolio-server release checkout** (not only v12-rebuild), then wire dispatch env and verify on ms01-openclaw.

## Discover the live backend root

portfolio-server is SHA-pinned via user systemd drop-in:

```bash
systemctl --user cat portfolio-server.service
ls ~/.config/systemd/user/portfolio-server.service.d/
# WorkingDirectory → trade-ai-releases/portfolio-server/<sha>-<label>/
```

Copy all backend files below into that release tree’s `scripts/` directory.

## Backend files to sync

| File | Purpose |
|---|---|
| `scripts/agent_runtime/readiness.py` | **NEW** — `GET /api/v3/agent-runtime/readiness` |
| `scripts/agent_runtime/operations.py` | **NEW** — `GET /api/v3/agent-runtime/operations` |
| `scripts/agent_runtime/operator_dispatch_http.py` | **NEW** — `POST /api/v3/agent-runtime/dispatch` |
| `scripts/agent_runtime/maturity_promotion_gates.py` | **NEW** — promotion gates route (imported by read_http) |
| `scripts/agent_runtime/read_http.py` | readiness + operations routes |
| `scripts/agent_runtime/maturity_observability.py` | Sentinel MVL hint fix |
| `scripts/portfolio_server.py` | dispatch POST handler (before read-only 405) |

Verify (already present in most releases; sync if mismatched):

- `scripts/agent_runtime_dispatch_boot.py`
- `scripts/agent_runtime/providers/lab_watch_provider.py`
- `scripts/agent_runtime/sentinel_pipeline.py` (`persistence` param required)

```bash
.venv/bin/python -m py_compile scripts/portfolio_server.py scripts/agent_runtime/*.py
.venv/bin/python -m pytest tests/test_agent_runtime_readiness.py \
  tests/test_agent_runtime_operations.py tests/test_agent_runtime_operator_dispatch.py -q
```

## Frontend

```bash
cd apps/command-center-v3 && npm run build
```

Static is served from `apps/command-center-v3/dist` on this host (may differ from the release backend root).

## Operator env (Bitwarden tmpfs — no DSNs in repo or drop-in literals)

**Preferred:** run the coordinated script (dry-run first):

```bash
./scripts/agent_runtime/deploy_operator_wiring.sh          # dry-run
./scripts/agent_runtime/deploy_operator_wiring.sh --execute
```

It writes mode-0600 `~/.config/tradeai/agent-operator.env` from Bitwarden tmpfs, updates the user-systemd drop-in, restarts `portfolio-server.service`, and asserts `dispatch.state=WIRED`.

Manual equivalent:

```bash
set -a && source /run/user/$(id -u)/tradeai/env && set +a
# ensure secrets: .venv/bin/python scripts/secrets/render_env.py --now

umask 077
cat > ~/.config/tradeai/agent-operator.env <<EOF
AGENT_RUNTIME_READ_API=1
AGENT_RUNTIME_READ_DSN=${SHADOW_READER_DSN}
AGENT_RUNTIME_OPERATOR_AUTH=1
AGENT_RUNTIME_DISPATCH_DSN=${SHADOW_DSN}
AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot
AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime.providers.lab_watch_provider
EOF
chmod 600 ~/.config/tradeai/agent-operator.env

mkdir -p ~/.config/systemd/user/portfolio-server.service.d
printf '[Service]\nEnvironmentFile=%s\n' "$HOME/.config/tradeai/agent-operator.env" \
  > ~/.config/systemd/user/portfolio-server.service.d/10-agent-read-api.conf

sudo install -m0644 /dev/null /etc/tradeai/agent_runtime_enabled   # kill switch
systemctl --user daemon-reload
systemctl --user restart portfolio-server.service
```

Optional: `AGENT_RUNTIME_TIMER_PROBE=1` for systemd timer state in operations API.

## Verify

```bash
curl -s 'http://127.0.0.1:7777/api/v3/agent-runtime/readiness' | jq .wiring
curl -s 'http://127.0.0.1:7777/api/v3/agent-runtime/operations?agent_id=sentinel' | jq '.agents[0] | {last_dispatch_at,timer_state,designed_schedule}'
curl -s 'http://127.0.0.1:7777/api/v3/agent-runtime/runs?agent_id=sentinel&limit=1' | jq '.data[0] | {started_at,status,agent_id}'
```

Expected readiness:

- `wiring.read_api.state` → `CONNECTED`
- `wiring.dispatch.state` → `WIRED`
- `wiring.dispatch.kill_switch_present` → `true`

Open `http://127.0.0.1:7777/v3/agents` — **Run now** enabled on SHADOW rows when dispatch is WIRED.

## Dispatch smoke (operator-only)

```bash
curl -s -X POST 'http://127.0.0.1:7777/api/v3/agent-runtime/dispatch' \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"sentinel","max_batch":1}' | jq .
```

Audit log: `state/agent_runtime/dispatch_audit.jsonl`
