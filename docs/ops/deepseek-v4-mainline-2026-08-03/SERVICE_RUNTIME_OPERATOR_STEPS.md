# Operator: wire DeepSeek key into portfolio-server (no auto restart)

1. Confirm rendered env has key **name** only:
   `awk -F= '{print $1}' /run/user/$(id -u)/tradeai/env | grep -i deepseek`
2. Add EnvironmentFile for that rendered env (or export `DEEPSEEK_API_KEY`) to
   `~/.config/systemd/user/portfolio-server.service.d/` drop-in.
3. Prefer canonical name `DEEPSEEK_API_KEY`; `deepseek_tradeai` remains temporary legacy.
4. Operator-approved: `systemctl --user daemon-reload && systemctl --user restart portfolio-server`
5. Smoke: `curl -s localhost:7777/api/v2/...` health/LLM endpoints after restart.
