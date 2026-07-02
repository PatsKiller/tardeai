# Hermes LLM Auth / OAuth — Status & Guided Login (2026-06-07, updated 2026-07-02)

Read-only auth status per LLM lane + the exact login commands. **No credentials are entered or stored in
the app.** External OAuth logins authenticate in your **browser via Google SSO** at the provider's prompt.
Endpoint: `GET /api/v2/hermes/llm-auth-status` · `GET /api/v2/llm/oauth-lanes`. UI: System → Hermes → "LLM Auth / OAuth" card.

## Current status (2026-07-02 — live on ms01-openclaw)
| Lane | Type | Status | Login / service |
|------|------|--------|-----------------|
| Grok (xAI) | OAuth proxy — free | **✓ ready** | `hermes auth add xai-oauth --type oauth` · `grok-oauth-proxy.service` (:8645) |
| ChatGPT (Codex) | OAuth — free (ChatGPT subscription) | **✓ ready** | `hermes auth add openai-codex --type oauth` · `chatgpt-oauth-proxy.service` (:8646) |
| Nous Portal (Hermes lane) | OAuth | **✓ ready** | `hermes auth add nous --type oauth` · or `scripts/nous_portal_login_detach.sh` |
| Claude (Anthropic) | API key (+credits) | key present; **credits needed** | set ANTHROPIC_API_KEY + add credits |
| Local (Ollama) | local — always free | **✓ ready** | (none) |

**Command Center free OAuth lanes: 4/4 ready** (Grok, ChatGPT, Hermes/Nous, local). Verify:
`curl -s http://127.0.0.1:7777/api/v2/llm/oauth-lanes | python3 -m json.tool`

### Proxy systemd (user units, 2026-07-02)
| Unit | Port | Script |
|------|------|--------|
| `grok-oauth-proxy.service` | 8645 | `scripts/grok_oauth_proxy.py` |
| `chatgpt-oauth-proxy.service` | 8646 | `scripts/chatgpt_oauth_proxy.py` |

Install: `cp config/systemd/*.service ~/.config/systemd/user/` → `systemctl --user daemon-reload` →
`systemctl --user enable --now grok-oauth-proxy.service chatgpt-oauth-proxy.service`.

Legacy `hermes-xai-proxy.service` (same :8645) — **disable** after migrating to `grok-oauth-proxy` to avoid double-bind on reboot.

### Nous re-login (headless / agent timeout)
Interactive OAuth can be killed by short agent timeouts. Use detached helper:
`bash scripts/nous_portal_login_detach.sh` → approve URL from `/tmp/nous_oauth_login.log`.

---
## Historical status (2026-06-07)
| Lane | Type | Status | Login (operator, in terminal) |
|------|------|--------|-------------------------------|
| ChatGPT (Codex) | OAuth — free (ChatGPT subscription) | **auth pending** | `hermes auth add openai-codex --type oauth` |
| Grok (xAI) | OAuth proxy — free | **auth pending** | `hermes auth add xai-oauth --type oauth` ; `hermes proxy start --provider xai` |
| Nous Portal | OAuth | **auth pending** | `hermes auth add nous --type oauth` |
| Claude (Anthropic) | API key (+credits) | key present; **credits needed** | set ANTHROPIC_API_KEY + add credits |
| Local (Ollama) | local — always free | **✓ ready** | (none) |

**Was all OAuth working? NO** — at that date no external OAuth lane was logged in yet.

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

---
## xAI/Grok proxy systemd (2026-07-02, canonical)
- `grok-oauth-proxy.service` (user): ExecStart=`scripts/grok_oauth_proxy.py`, Type=simple,
  **Restart=always** (RestartSec=5), `GROK_PROXY_PORT=8645`. enabled + active on ms01-openclaw.
- Legacy `hermes-xai-proxy.service` — same port; **disable** when using `grok-oauth-proxy`.
- Operate: `systemctl --user status|restart|stop grok-oauth-proxy.service`.
- ChatGPT mirror: `chatgpt-oauth-proxy.service` on :8646.

## ChatGPT/Codex login — BLOCKED by ChatGPT workspace policy (2026-06-07)
The Codex device-code login (`hermes auth add openai-codex --type oauth`) returns:
"Please contact your workspace admin to enable device code authentication."
This is a **ChatGPT workspace (Business/Enterprise/Edu) admin policy** — device-code auth is disabled for
the org on account john@jwwhiting.com. Resolution is EXTERNAL to this system: the **ChatGPT workspace admin**
must enable device-code authentication in ChatGPT admin settings. If john@jwwhiting.com is the workspace
owner/admin, enable it there; if it's a managed workspace, the org admin must. Until then the ChatGPT/Codex
lane stays auth_pending. (Grok via xai-oauth is unaffected and working; Claude needs Anthropic credits.)

---
## ChatGPT/Codex — authed, but headless researcher lane unavailable in v0.16.0 (2026-06-07)
After the workspace admin enabled device-code auth, the operator completed the Codex OAuth (creds saved:
`openai-codex-oauth-1`). **Auth works + is detected.** HOWEVER: the automated researcher lane uses the Hermes
**headless one-shot** `hermes -z --provider openai-codex -m <model>`, which returns **"no final response was
produced; treating the run as failed"** for EVERY codex model (gpt-5-codex/gpt-5/o4-mini/etc.) and every
profile — a **Hermes v0.16.0 limitation** (the codex/ChatGPT agent backend doesn't finalize a response
through the non-interactive `-z` harness). Not a credential issue.

- ✅ ChatGPT/Codex is usable INTERACTIVELY: `hermes -p dev chat` (subscription-backed, free). dev profile now
  configured to provider openai-codex / gpt-5-codex.
- ⛔ The automated `--lane chatgpt` researcher returns status=`unavailable` (CODEX_HEADLESS_UNAVAILABLE) until
  a Hermes fix enables headless codex output. The lane is wired correctly and will work once `-z` finalizes codex.
- Grok (xai-oauth proxy) and Claude (API+credits) are the headless-capable external lanes.

---
## Phase 212 (2026-06-07): headless reason = hermes_headless_limit
Confirmed 0.16.0 is the latest Hermes; no upgrade fixes headless Codex. chatgpt researcher lane reason code:
`hermes_headless_limit` (auth + version are fine; the headless path is the blocker). Re-evaluate on Hermes >0.16.0.

---
## Phase 213 (2026-06-07): capability cache + lane hardening
chatgpt lane now reads `data/runtime/hermes_llm_capabilities.json` and **fails closed without retrying** the
Codex headless path (reason hermes_headless_limit) until Hermes > 0.16.0 (or `--force-retest`). v3
llm-auth-status surfaces interactive vs headless status per lane. Read-only `check_hermes_update_available.py`
watches for a newer build (no auto-upgrade). Codex = interactive-only; Grok = free automated lane.
