# Service-runtime DeepSeek credential wiring (operator-approved only)

Status:      ACTIVE
as_of:       2026-08-03T11:40:56-04:00
Measured at: efcc51365 / not measured

## Canonical secret

| Item | Value |
|------|--------|
| **Canonical Trade AI DeepSeek secret identifier** | `deepseek_tradeai` |
| Bitwarden/rendered env var | `deepseek_tradeai` |
| Compatibility alias (optional, not required) | `DEEPSEEK_API_KEY` |
| Secret value | **never print or inspect** |

Do **not** rename the Bitwarden item. Do **not** require `DEEPSEEK_API_KEY`.
Do **not** create a second unmanaged secret file or put the value in systemd `Environment=`.

## Verified current state (read-only)

| Check | Result |
|-------|--------|
| EnvironmentFile on portfolio-server | `/home/johnclaw/.config/tradeai/agent-operator.env` only |
| `deepseek_tradeai` name in agent-operator.env | **ABSENT** |
| `DEEPSEEK_API_KEY` name in agent-operator.env | **ABSENT** |
| Rendered Bitwarden tmpfs `/run/user/$UID/tradeai/env` name `deepseek_tradeai` | **PRESENT** |
| Running portfolio_server process has `deepseek_tradeai` name | **ABSENT** |
| Live WorkingDirectory | release tree `af45096e-platform-audit-20260802` (not this worktree) |

**Status: BLOCKED** for service-context DeepSeek until the service loads the rendered env that already defines `deepseek_tradeai`, then an **operator-approved** restart.

---

## Name-only verification (safe)

```bash
# Rendered Trade AI env — name only
awk -F= '{print $1}' /run/user/$(id -u)/tradeai/env | grep -Fx 'deepseek_tradeai'

# Optional: confirm alias is NOT required
awk -F= '{print $1}' /run/user/$(id -u)/tradeai/env | grep -Fx 'DEEPSEEK_API_KEY' || true
```

Never `cat`, `echo $deepseek_tradeai`, or print values.

---

## Exact remediation (mutation — operator approval required)

### 1) Ensure portfolio-server loads the Bitwarden-rendered EnvironmentFile

```bash
mkdir -p ~/.config/systemd/user/portfolio-server.service.d
cat > ~/.config/systemd/user/portfolio-server.service.d/30-deepseek-env.conf <<'UNIT'
[Service]
# Load the existing Bitwarden-rendered tmpfs env (defines deepseek_tradeai).
# Do not put the secret value in this file.
EnvironmentFile=-/run/user/1000/tradeai/env
UNIT
```

Use the same UID path the host already uses for Trade AI render (`/run/user/1000/tradeai/env` on this host).

### 2) Confirm the file defines the **name** only

```bash
awk -F= '{print $1}' /run/user/1000/tradeai/env | grep -Fx 'deepseek_tradeai'
```

### 3) Later — operator-approved reload + restart

```bash
systemctl --user daemon-reload
systemctl --user restart portfolio-server.service
systemctl --user is-active portfolio-server.service
```

### 4) After restart — process has the **name**

```bash
PID=$(pgrep -f portfolio_server.py | head -1)
tr '\0' '\n' < /proc/$PID/environ | cut -d= -f1 | grep -Fx 'deepseek_tradeai'
```

### 5) Service-context health (existing API routes — no invented endpoints)

```bash
curl -sS -o /tmp/llm_health.json -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/llm/health
curl -sS -o /tmp/llm_health2.json -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/llm-health
curl -sS -o /tmp/oauth_lanes.json -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/llm/oauth-lanes
python3 -c "import json;d=json.load(open('/tmp/llm_health.json'));print(type(d).__name__, list(d)[:20] if isinstance(d,dict) else '')"
```

Interactive worktree probes using `deepseek_tradeai` are **not** service-context proof.

### 6) Rollback

```bash
rm -f ~/.config/systemd/user/portfolio-server.service.d/30-deepseek-env.conf
systemctl --user daemon-reload
# restart only if you previously restarted
```
