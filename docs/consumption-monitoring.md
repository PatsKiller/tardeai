# LLM Consumption Monitoring (Command Center v3)

Tracks and controls **free OAuth** usage for Grok (xAI proxy `:8645`) and ChatGPT (codex proxy `:8646`). No metered API keys.

## UI

**Ops → Consumption** (`/v3/consumption`)

- OAuth lane health (Grok / ChatGPT ready vs offline)
- Usage overview (today / 7d relative units)
- Per-process **Automated** vs **Manual** toggles
- Recent activity feed

## Lane policies (Grok vs ChatGPT)

Each process has a `lane_policy` in `config/llm_process_registry.json`:

| Policy | Meaning | Examples |
|--------|---------|----------|
| **grok_only** | Grok only | `holding_protection_advisor`, `rotation_grok_review`, `grok_execution_review` |
| **chatgpt_only** | ChatGPT only | (reserved) |
| **either** | Operator picks **one** lane — either is enough | `portfolio_ask`, `journal_ask`, `hermes_external_research`, `strategy_planner` |
| **both_preferred** | Best with both; **either alone still useful** | `broker_cloud_oversight`, `cloud_review`, `paper_trade_advisory` |
| **ensemble** | Designed to **run both** and reconcile | `rotation_oversight`, `watchlist_cio_synthesis`, `options_ensemble`, `cloud_consensus_verdict` |

UI: broker proposal cards and Rotation oversight show **▶ Grok** / **▶ ChatGPT** per policy. Broker cards use `POST /api/v2/broker-proposals/run-cloud-oversight` with `lanes: ["grok"]` or `["chatgpt"]`.

`cloud_consensus_verdict` needs **both** lanes for `CLOUD_APPROVE`. Most escalation paths try Grok → ChatGPT → local.

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

## Stop advisory batch (Manual, periodic Grok)

Without flipping `holding_protection_advisor` to Automated, run top-N priority holdings:

```bash
curl -X POST http://127.0.0.1:7777/api/v2/consumption/stop-advisory-batch \
  -H 'Content-Type: application/json' \
  -d '{"limit":6,"lane":"grok"}'
```

CLI (same `manual_trigger` / `holding_protection_advisor_batch` process_id):

```bash
python3 scripts/holding_protection_advisor.py --batch --limit 6 --lane grok
```

UI: **Portfolio → Stop Management** or **Ops → Consumption** (batch row) — **▶ Grok (top 6)**.

Watchlist CIO synthesis (per card, Manual):

```bash
curl -X POST http://127.0.0.1:7777/api/v2/watchlist/AAPL/cio-synthesis \
  -H 'Content-Type: application/json' \
  -d '{"lanes":["grok"]}'
```

UI: **Watch** cards — **▶ Grok / ▶ ChatGPT** on Conviction (v3) or CIO context (v4). Requires completed agent reviews on the symbol.

Optional cron (weekdays, stays Manual in DB):

```cron
# 10:30 ET — top-6 stop advisories via Grok OAuth (manual_trigger batch)
30 10 * * 1-5 cd /path/to/trade-ai && python3 scripts/holding_protection_advisor.py --batch --limit 6 --lane grok >> logs/stop_advisory_batch.log 2>&1
```

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