# Hermes External Researcher Lanes — Status & Routes (2026-06-07)

`scripts/hermes_external_researcher.py --lane {claude|chatgpt|grok}`. All advisory-only, redaction-first,
DRY-RUN by default, manual/escalation, governed by EXTERNAL_LLM_USAGE_POLICY_20260607.md. Audit:
`hermes_external_research` + `GET /api/v2/hermes/external-research`.

| Lane | Route | Cost model | Status | Activate |
|------|-------|-----------|--------|----------|
| **claude** | Anthropic API (`api.anthropic.com`, key from env) | metered API | wired; **blocked by credits** | add Anthropic billing credits |
| **chatgpt** | **openai-codex OAuth** via Hermes CLI one-shot (`hermes -z … --provider openai-codex`) — **NOT the OpenAI API** | **FREE (ChatGPT subscription)** | wired; **auth_pending** | operator: `hermes login --provider openai-codex` |
| **grok** | xAI API (`api.x.ai`, XAI_API_KEY) | metered API | **wired + working** | live now (free alt below) |

## Why ChatGPT uses Codex OAuth, not the OpenAI API
Per operator directive: ChatGPT must run on the **free ChatGPT-subscription OAuth (openai-codex)**, not the
metered OpenAI API. The Hermes proxy only bridges `nous`/`xai` (no openai-codex upstream), so the ChatGPT
lane uses the Hermes one-shot CLI with `--provider openai-codex`, which uses the stored login OAuth — no
OpenAI API key, no per-call billing. It is `auth_pending` until the operator completes the device-code login.
(The earlier OpenAI-API wiring was removed.)

## Grok — free OAuth alternative (optional)
Grok currently uses the xAI API key (working). To switch Grok to the FREE xAI OAuth proxy instead:
`hermes login --provider xai-oauth` then `hermes proxy start --provider xai` (local OpenAI-compatible proxy
on 127.0.0.1:8645). Say the word and I'll repoint the grok lane at the proxy.

## Safety (all lanes)
Redaction verified (amounts/account#/keys stripped); API keys/OAuth read at call-time only, never stored/
logged/returned; dry-run default; advisory-only (no broker/order/stop/proposal/trading); not auto-scheduled;
per-call operator approval (`--apply`).
