# Docker Rollback Runbook

Status:      ACTIVE
as_of:       2026-05-31T17:44:35-04:00
Measured at: efcc51365 / not measured

## If a container fails or causes issues:

```bash
# Stop container
docker compose down

# Verify bare-metal services are running
systemctl status tradeai-portfolio-server
systemctl status ollama
systemctl --user status openclaw-gateway
systemctl --user status hermes-gateway

# If services stopped, restart them
sudo systemctl restart tradeai-portfolio-server
sudo systemctl restart ollama
systemctl --user restart openclaw-gateway
systemctl --user restart hermes-gateway

# Verify ports
ss -tlnp | grep -E "7777|11434|18789|18790"

# Verify DB
psql -h localhost -U trade_ai -d trade_ai -c "SELECT 1;"
```

## If Docker was not installed yet:
No rollback needed — bare-metal remains operational.
