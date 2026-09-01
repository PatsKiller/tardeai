# PHASE 212A — Hermes Current Runtime Snapshot (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T15:33:32-04:00
Measured at: efcc51365 / not measured

- hermes: /home/johnclaw/.local/bin/hermes → **v0.16.0 (2026.6.5)**; venv ~/.local/share/hermes-agent-venv (pip).
- profiles: default, tradeai, tradeai12b, dev, serverops (5).
- auth: 6 provider credentials present (incl openai-codex OAuth, xai-oauth, openai-api, anthropic).
- dev: provider=openai-codex, default=gpt-5-codex.
- tradeai tools=0, tradeai12b tools=0 (tool-less ✓).
- hermes-xai-proxy.service: **active**. hermes-gateway.service: disabled (failed/inactive — retired, correct).
