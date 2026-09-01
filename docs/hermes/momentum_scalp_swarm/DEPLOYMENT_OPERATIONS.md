# Deployment & Operations — MS-01

Status:      ACTIVE
as_of:       2026-07-02T18:56:18-04:00
Measured at: efcc51365 / not measured

---

## Hermes Tools Profile

Enable for `tradeai12b` profile (System → Hermes):
- File read/write (state/momentum_scalp/)
- Telegram (OpenClaw approvals)
- No broker write tools

---

## Tmux Session Layout

```bash
./linux_launchers/hermes_scalp_swarm_tmux.sh start
```

| Window | Process | Interval |
|--------|---------|----------|
| orchestrator | `hermes_scalp_orchestrator.py` | 60s |
| live_monitor | `hermes_scalp_live_monitor.py` | 30s |
| signal_scout | `hermes_scalp_signal_scout.py` | 45s |
| entry_validation | `hermes_scalp_entry_validation.py` | 60s |
| exit_intelligence | `hermes_scalp_exit_intelligence.py` | 60s |
| post_trade_review | `hermes_scalp_post_trade_review.py` | 300s |
| health | API status watch | 15s |

```bash
tmux attach -t hermes-scalp-swarm
./linux_launchers/hermes_scalp_swarm_tmux.sh stop   # halt
```

---

## Logs

| Log | Path |
|-----|------|
| Orchestrator | `logs/hermes_scalp_orchestrator.log` |
| Live Monitor | `logs/hermes_scalp_live_monitor.log` |
| Audit | `state/momentum_scalp/orchestrator_audit.json` |

---

## Auto-Restart Pattern (systemd optional)

```ini
# /etc/systemd/user/hermes-scalp-live-monitor.service
[Unit]
Description=Hermes Scalp Live Monitor
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
ExecStart=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python3 scripts/hermes_scalp_live_monitor.py --interval 30
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

Mirror for orchestrator at 60s interval.

---

## Health Monitoring

1. **API:** `curl -s http://127.0.0.1:7777/api/v2/hermes/scalp-swarm/status | jq .agents`
2. **State freshness:** `state.files.*.age_hours` < 0.5 for live agents
3. **health_agent.py:** Add `hermes_scalp_swarm_stale` finding if state > 2h old

---

## Server Restart

After code changes:
```bash
linux_launchers/restart_server.sh
```

Rebuild CC v3 if HermesHub.tsx changed:
```bash
cd apps/command-center-v3 && npm run build
```

---

## Rollback

1. `./linux_launchers/hermes_scalp_swarm_tmux.sh stop`
2. State files are non-destructive — archive `state/momentum_scalp/` if needed
3. Paper trades unaffected (monitor is read-only unless `--apply` on tighten)