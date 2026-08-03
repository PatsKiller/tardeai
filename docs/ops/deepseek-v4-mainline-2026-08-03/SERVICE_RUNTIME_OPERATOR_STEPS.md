# Service-runtime DeepSeek credential wiring (operator-approved only)

## Verified current state (read-only, 2026-08-03)

| Check | Result |
|-------|--------|
| Unit | `portfolio-server.service` (user) |
| FragmentPath | `~/.config/systemd/user/portfolio-server.service` |
| Drop-ins | `10-agent-read-api.conf`, `12-agent-runtime-probe.conf`, `20-exact-sha-release.conf` |
| EnvironmentFile | `/home/johnclaw/.config/tradeai/agent-operator.env` only |
| `DEEPSEEK_API_KEY` name in agent-operator.env | **ABSENT** |
| `deepseek_tradeai` name in agent-operator.env | **ABSENT** |
| Rendered Bitwarden tmpfs `/run/user/$UID/tradeai/env` has `deepseek_tradeai` name | **PRESENT** |
| Running `portfolio_server.py` process env has DeepSeek names | **ABSENT** |
| WorkingDirectory (live) | `…/af45096e-platform-audit-20260802` (release tree, not this worktree) |

**Status: BLOCKED for service-context DeepSeek until operator wires env + restarts.**

This worktree must not execute daemon-reload or restart.

---

## Exact operator procedure (do not run unless you approve mutation)

### 1) Confirm key **names** only (no values)

```bash
awk -F= '{print $1}' /run/user/$(id -u)/tradeai/env | grep -iE 'deepseek|DEEPSEEK'
# expect: deepseek_tradeai and/or DEEPSEEK_API_KEY
```

### 2) Create drop-in loading the rendered env

```bash
mkdir -p ~/.config/systemd/user/portfolio-server.service.d
cat > ~/.config/systemd/user/portfolio-server.service.d/30-deepseek-env.conf <<'EOF'
[Service]
# Prefer Bitwarden-rendered env (contains deepseek_tradeai and/or DEEPSEEK_API_KEY)
EnvironmentFile=-/run/user/1000/tradeai/env
# Optional explicit canonical name if you set it in agent-operator.env later:
# EnvironmentFile=-/home/johnclaw/.config/tradeai/agent-operator.env
EOF
```

Prefer canonical `DEEPSEEK_API_KEY` in Bitwarden when practical; `deepseek_tradeai` remains temporary legacy (client accepts both).

### 3) daemon-reload (approved)

```bash
systemctl --user daemon-reload
```

### 4) restart (approved)

```bash
systemctl --user restart portfolio-server.service
systemctl --user is-active portfolio-server.service
```

### 5) Post-restart **name** check on service PID

```bash
PID=$(pgrep -f portfolio_server.py | head -1)
tr '\0' '\n' < /proc/$PID/environ | cut -d= -f1 | grep -iE 'deepseek|DEEPSEEK'
# expect DEEPSEEK_API_KEY and/or deepseek_tradeai
```

### 6) Service-context smoke (exact existing endpoints)

```bash
# LLM router health (exists in api_v2 routes)
curl -sS -o /tmp/llm_health.json -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/llm/health
curl -sS -o /tmp/llm_health2.json -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/llm-health
curl -sS -o /tmp/oauth_lanes.json -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/llm/oauth-lanes
curl -sS -o /tmp/system_health.json -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/system-health
# Inspect JSON for DeepSeek lane readiness fields without printing secrets
python3 -c "import json;d=json.load(open('/tmp/llm_health.json'));print(sorted(d.keys())[:30] if isinstance(d,dict) else type(d))"
```

Interactive worktree live Flash/Pro smoke is **not** a substitute for this service-context check.

### 7) Rollback

```bash
rm -f ~/.config/systemd/user/portfolio-server.service.d/30-deepseek-env.conf
systemctl --user daemon-reload
systemctl --user restart portfolio-server.service   # only if you previously restarted
```
