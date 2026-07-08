# LLM Consumption Monitoring (Command Center v3)

Tracks and controls **free OAuth** usage for Grok (xAI proxy `:8645`) and ChatGPT (codex proxy `:8646`). No metered API keys.

## UI

**Ops → Consumption** (`/v3/consumption`)

- OAuth lane health (Grok / ChatGPT ready vs offline)
- Usage overview (today / 7d relative units)
- Per-process **Automated** vs **Manual** toggles
- Recent activity feed

## Per-process modes

| Mode | Behavior |
|------|----------|
| **Manual** (default) | Automatic cron/agents skip Grok/ChatGPT; UI shows run controls |
| **Automated** | Process calls OAuth lanes normally; every call is logged |

Bootstrap defaults (explicit in `config/llm_process_registry.json`):

| Process | Mode |
|---------|------|
| `cloud_review` | Automated — broker oversight second opinions |
| `oauth_lane_keepalive` | Automated — daily OAuth token roll |
| `holding_protection_advisor` | Manual — many holdings per run |
| `watchlist_cio_synthesis` | Manual — per-symbol CIO runs |

Configure in Consumption UI or:

```bash
curl -X POST http://127.0.0.1:7777/api/v2/consumption/process-mode \
  -H 'Content-Type: application/json' \
  -d '{"process_id":"holding_protection_advisor","mode":"automated"}'
```

## Register a new process

1. Add to `config/llm_process_registry.json`:

```json
{"id": "my_feature", "name": "My Feature", "category": "Intel", "description": "What it does"}
```

2. Call `llm_lane.generate` with `process_id`:

```python
import llm_lane
text = llm_lane.generate(prompt, lane="grok", process_id="my_feature",
                          task_summary="short label for logs")
```

3. On first API hit, `llm_process_config` is seeded (default **manual**).

## Manual on-demand run (API)

```bash
curl -X POST http://127.0.0.1:7777/api/v2/consumption/run-manual \
  -H 'Content-Type: application/json' \
  -d '{"process_id":"rotation_grok_review","lane":"grok","prompt":"...","task_summary":"operator run"}'
```

## OAuth availability (canonical)

All pages should use `lib.oauth_lane_status` (via `llm_lane.available` or `GET /api/v2/llm/oauth-lanes`).

- **Do not** use `XAI_API_KEY` for lane health — that is a separate metered path.
- Services: `grok-oauth-proxy.service`, `chatgpt-oauth-proxy.service`
- Re-auth: `hermes auth add xai-oauth --type oauth`

## Database

Tables: `llm_consumption_log`, `llm_process_config`  
Migration: `migrations/2026_07_08_llm_consumption_monitoring.sql`  
Schema also auto-created by `lib.llm_consumption.ensure_schema()`.

## Fail-open

If logging or config DB fails, model calls still proceed. Manual mode is enforced only when config reads succeed.