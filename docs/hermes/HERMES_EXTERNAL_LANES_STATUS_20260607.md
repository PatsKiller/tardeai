# Hermes External Researcher Lanes — Status & Routes (2026-06-07, updated 2026-07-02)

`scripts/hermes_external_researcher.py --lane {claude|chatgpt|grok}`. All advisory-only, redaction-first,
DRY-RUN by default, manual/escalation, governed by EXTERNAL_LLM_USAGE_POLICY_20260607.md. Audit:
`hermes_external_research` + `GET /api/v2/hermes/external-research`.

## Live status (2026-07-02)
| Lane | Route | Cost model | Status | Service / activate |
|------|-------|-----------|--------|-------------------|
| **grok** | `grok_oauth_proxy.py` on :8645 (Hermes `xai-oauth`) | **FREE (xAI OAuth)** | **✓ ready** | `grok-oauth-proxy.service` |
| **chatgpt** | `chatgpt_oauth_proxy.py` on :8646 (Hermes `openai-codex`) | **FREE (ChatGPT subscription)** | **✓ ready** | `chatgpt-oauth-proxy.service` |
| **claude** | Anthropic API (`api.anthropic.com`, key from env) | metered API | wired; **blocked by credits** | add Anthropic billing credits |

Nous Portal OAuth is logged in for Hermes CLI/portal (`hermes portal status`); external researcher lanes above are Grok + ChatGPT + Claude.

---
## Historical status (2026-06-07)
| Lane | Route | Cost model | Status | Activate |
|------|-------|-----------|--------|----------|
| **claude** | Anthropic API (`api.anthropic.com`, key from env) | metered API | wired; **blocked by credits** | add Anthropic billing credits |
| **chatgpt** | **openai-codex OAuth** via Hermes CLI one-shot (`hermes -z … --provider openai-codex`) — **NOT the OpenAI API** | **FREE (ChatGPT subscription)** | wired; **auth_pending** | operator: `hermes auth add openai-codex --type oauth` |
| **grok** | **xai-oauth proxy** (`hermes proxy start --provider xai`, local :8645) — **NOT the xAI API** | **FREE (xAI OAuth)** | wired; **auth_pending** | operator: `hermes auth add xai-oauth --type oauth` + `hermes proxy start --provider xai` |

## Why ChatGPT uses Codex OAuth, not the OpenAI API
Per operator directive: ChatGPT must run on the **free ChatGPT-subscription OAuth (openai-codex)**, not the
metered OpenAI API. The Hermes proxy only bridges `nous`/`xai` (no openai-codex upstream), so the ChatGPT
lane uses the Hermes one-shot CLI with `--provider openai-codex`, which uses the stored login OAuth — no
OpenAI API key, no per-call billing. It is `auth_pending` until the operator completes the device-code login.
(The earlier OpenAI-API wiring was removed.)

## Grok — FREE xAI OAuth proxy (2026-07-02)
Grok routes through `scripts/grok_oauth_proxy.py` on 127.0.0.1:8645, managed by `grok-oauth-proxy.service`.
Requires `hermes auth add xai-oauth --type oauth`. Override URL with `HERMES_XAI_PROXY_URL` if needed.

## Safety (all lanes)
Redaction verified (amounts/account#/keys stripped); API keys/OAuth read at call-time only, never stored/
logged/returned; dry-run default; advisory-only (no broker/order/stop/proposal/trading); not auto-scheduled;
per-call operator approval (`--apply`).

---
## Phase 212 (2026-06-07): ChatGPT/Codex headless — no Hermes fix available
0.16.0 is the latest Hermes build (no newer/pre-release). All headless command shapes fail for Codex →
chatgpt automated lane stays `unavailable` (reason: hermes_headless_limit). Codex interactive works.
Grok (xai-oauth proxy) is the working free automated external lane. See PHASE212* docs.

---
## Phase 213 (2026-06-07): lane hardening
ChatGPT/Codex: free + interactive-only (`hermes -p dev chat`); automated lane cache-gated to `unavailable`
(hermes_headless_limit) — NOT retried until Hermes>0.16.0. Grok (xai-oauth proxy) = current free automated
external lane. Local Ollama = primary automated lane. Claude = high-stakes once credits added. Capability
cache: data/runtime/hermes_llm_capabilities.json. Override: --force-retest.
