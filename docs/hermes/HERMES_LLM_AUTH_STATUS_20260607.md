# Hermes LLM Auth / OAuth — Status & Guided Login (2026-06-07)

Read-only auth status per LLM lane + the exact login commands. **No credentials are entered or stored in
the app.** External OAuth logins authenticate in your **browser via Google SSO** at the provider's prompt.
Endpoint: `GET /api/v2/hermes/llm-auth-status`. UI: System → Hermes → "LLM Auth / OAuth" card.

## Current status (2026-06-07)
| Lane | Type | Status | Login (operator, in terminal) |
|------|------|--------|-------------------------------|
| ChatGPT (Codex) | OAuth — free (ChatGPT subscription) | **auth pending** | `hermes login --provider openai-codex` |
| Grok (xAI) | OAuth proxy — free | **auth pending** | `hermes login --provider xai-oauth` ; `hermes proxy start --provider xai` |
| Nous Portal | OAuth | **auth pending** | `hermes login --provider nous` |
| Claude (Anthropic) | API key (+credits) | key present; **credits needed** | set ANTHROPIC_API_KEY + add credits |
| Local (Ollama) | local — always free | **✓ ready** | (none) |

**Is all OAuth working? NO** — no external OAuth lane is logged in yet. Local Ollama is the only fully-ready
LLM. Run the login commands above (Google SSO in browser) to activate the free external lanes.

## Safety
The app never sees/stores credentials. `hermes login` runs device-code/browser OAuth under the operator's
session; tokens live in the Hermes auth store, not in this app or its DB. No auto-login.
