# Hermes External Researcher Lanes — Status & Routes (2026-06-07)

`scripts/hermes_external_researcher.py --lane {claude|chatgpt|grok}`. All advisory-only, redaction-first,
DRY-RUN by default, manual/escalation, governed by EXTERNAL_LLM_USAGE_POLICY_20260607.md. Audit:
`hermes_external_research` + `GET /api/v2/hermes/external-research`.

| Lane | Route | Cost model | Status | Activate |
|------|-------|-----------|--------|----------|
| **claude** | Anthropic API (`api.anthropic.com`, key from env) | metered API | wired; **blocked by credits** | add Anthropic billing credits |
| **chatgpt** | **openai-codex OAuth** via Hermes CLI one-shot (`hermes -z … --provider openai-codex`) — **NOT the OpenAI API** | **FREE (ChatGPT subscription)** | wired; **auth_pending** | operator: `hermes login --provider openai-codex` |
| **grok** | **xai-oauth proxy** (`hermes proxy start --provider xai`, local :8645) — **NOT the xAI API** | **FREE (xAI OAuth)** | wired; **auth_pending** | operator: `hermes login --provider xai-oauth` + `hermes proxy start --provider xai` |

## Why ChatGPT uses Codex OAuth, not the OpenAI API
Per operator directive: ChatGPT must run on the **free ChatGPT-subscription OAuth (openai-codex)**, not the
metered OpenAI API. The Hermes proxy only bridges `nous`/`xai` (no openai-codex upstream), so the ChatGPT
lane uses the Hermes one-shot CLI with `--provider openai-codex`, which uses the stored login OAuth — no
OpenAI API key, no per-call billing. It is `auth_pending` until the operator completes the device-code login.
(The earlier OpenAI-API wiring was removed.)

## Grok — repointed to the FREE xAI OAuth proxy (2026-06-07)
Grok now routes through the local xai-oauth proxy (`hermes proxy start --provider xai`, 127.0.0.1:8645) — the
metered xAI API key route was removed. auth_pending until the operator runs `hermes login --provider
xai-oauth` and starts the proxy. Override the proxy URL with HERMES_XAI_PROXY_URL if needed.

## Safety (all lanes)
Redaction verified (amounts/account#/keys stripped); API keys/OAuth read at call-time only, never stored/
logged/returned; dry-run default; advisory-only (no broker/order/stop/proposal/trading); not auto-scheduled;
per-call operator approval (`--apply`).
