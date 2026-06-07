# Hermes LLM Auth / OAuth — Status & Guided Login (2026-06-07)

Read-only auth status per LLM lane + the exact login commands. **No credentials are entered or stored in
the app.** External OAuth logins authenticate in your **browser via Google SSO** at the provider's prompt.
Endpoint: `GET /api/v2/hermes/llm-auth-status`. UI: System → Hermes → "LLM Auth / OAuth" card.

## Current status (2026-06-07)
| Lane | Type | Status | Login (operator, in terminal) |
|------|------|--------|-------------------------------|
| ChatGPT (Codex) | OAuth — free (ChatGPT subscription) | **auth pending** | `hermes auth add openai-codex --type oauth` |
| Grok (xAI) | OAuth proxy — free | **auth pending** | `hermes auth add xai-oauth --type oauth` ; `hermes proxy start --provider xai` |
| Nous Portal | OAuth | **auth pending** | `hermes auth add nous --type oauth` |
| Claude (Anthropic) | API key (+credits) | key present; **credits needed** | set ANTHROPIC_API_KEY + add credits |
| Local (Ollama) | local — always free | **✓ ready** | (none) |

**Is all OAuth working? NO** — no external OAuth lane is logged in yet. Local Ollama is the only fully-ready
LLM. Run the login commands above (Google SSO in browser) to activate the free external lanes.

## Safety
The app never sees/stores credentials. `hermes login` runs device-code/browser OAuth under the operator's
session; tokens live in the Hermes auth store, not in this app or its DB. No auto-login.

---
## Correction (2026-06-07): `hermes login` removed in v0.16.0
The `hermes login` subcommand was removed. Current OAuth login command:
`hermes auth add <provider> --type oauth` (add `--manual-paste` on a headless/remote box — it prints an auth
URL; you authenticate in your browser via Google SSO, then paste the redirected callback URL back).
Examples: `hermes auth add openai-codex --type oauth --manual-paste` ·
`hermes auth add xai-oauth --type oauth --manual-paste` then `hermes proxy start --provider xai`.
This is interactive (paste-back) — run it in YOUR terminal; it cannot be brokered headlessly. Alternatively
`hermes model` (interactive picker) or `hermes setup model`.

---
## OAuth + proxy monitoring in Command Center (2026-06-07)
`/api/v2/hermes/llm-auth-status` + the System → Hermes "LLM Auth / OAuth" card now monitor BOTH auth and the
proxy:
- per-lane: `authed` (OAuth/credential present) + `usable` (authed AND, for xai/nous, proxy running).
- `proxy`: {running (socket check :8645), url, needed_by, start_command, warning} — warns if xAI is authed
  but the proxy is DOWN.
- Status labels: "✓ ready" (usable) / "authed · needs proxy" / "auth pending".
- Detection fix: xAI reports "ready" (not "logged in") — now matched correctly.

### Live (2026-06-07): Grok WIRED + WORKING
xAI OAuth saved (loopback_pkce); `hermes proxy start --provider xai` running on :8645; grok lane verified
end-to-end (real response stored in hermes_external_research). ChatGPT/Codex + Nous still auth-pending.

### Proxy persistence (operator decision)
The proxy currently runs as a foreground process. For durable uptime + auto-restart it should be a systemd
**user** service (operator-approved) — otherwise it stops if its shell exits. The card shows DOWN if it stops.

## Grok usage command
1. (once, persistent) `hermes proxy start --provider xai`
2. `python3 scripts/hermes_external_researcher.py --lane grok --question "..." --apply`
