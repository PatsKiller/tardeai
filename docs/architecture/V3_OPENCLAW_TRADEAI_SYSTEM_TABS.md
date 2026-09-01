# Command Center v3 — OpenClaw + TradeAI System Tabs — 2026-06-07

Status:      ACTIVE
as_of:       2026-06-07T21:24:18-04:00
Measured at: efcc51365 / not measured

Added two System-hub tabs alongside Hermes, same format.

## OpenClaw tab (System → OpenClaw)
Read-only inventory of the OpenClaw ecosystem + editable agent SOULs.
- Endpoint: `GET /api/v2/openclaw/status` (`_openclaw_status`) — agents (id/name/identity/emoji/model/
  workspace/soul_exists), skills catalog, channels, gateway status, model defaults. Read-only, no secrets.
- Agent SOUL: `GET/POST /api/v2/openclaw/agent-soul?agent=NAME` — reads/writes
  `~/.openclaw/agents/<id>/agent/SOUL.md`. POST is **backup-first** (`~/.openclaw/agent_soul_backups/<id>/`),
  **fail-closed validation** (`_agent_soul_validate` rejects unsafe enabling language — execute/place orders,
  bypass approval, read secrets, enable live trading), path-traversal guarded under `~/.openclaw`.
- UI: `OpenClawPanel.tsx` — status card (gateway active/enabled, model ollama/qwen3:14b, fallbacks), agents
  table (5 agents: main + steph/aegis/alex/iris with emoji/identity/SOUL → **Edit Identity**), skills
  catalog (8), channels (telegram + whatsapp). Gateway shown but **not** controlled here.

## TradeAI tab (System → TradeAI)
Read-only TradeAI agent fleet; advisory personas have editable SOULs, algorithmic agents are config-locked.
- Endpoint: `GET /api/v2/tradeai/fleet` (`_tradeai_fleet`) — 11 agents with role (config/agents.yaml +
  ROLES), runtime model gemma3:12b, type (advisory/algorithmic), calibration, soul_editable.
- **Advisory personas** (alex/aegis/steph/iris) share the OpenClaw SOUL → **Edit Identity** (same editor).
  maria/maria_research show as advisory but have no SOUL → config-locked.
- **Algorithmic agents** (cio_engine/risk_agent/tax_agent/social_scalp/scalp_critic) are **config-locked** —
  their operational config (config/agents.yaml thresholds/routing) is safety-locked and NOT editable here
  (honors the no-scoring/no-threshold-change rules).
- UI: `TradeAIPanel.tsx` + shared `AgentSoulEditor.tsx`.

## Safety
Read-only inventories; the only writes are agent SOUL persona text (backup-first, validated, path-guarded).
No broker/order/proposal/protection/threshold/strategy mutation. OpenClaw gateway displayed, never toggled.
Screenshots: `v3_openclaw_tab.png`, `v3_tradeai_tab.png`. v3 build OK; 0 console errors; v2 untouched.
