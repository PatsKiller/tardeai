# PHASE 212H — v3 Codex Interactive vs Headless Status (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T15:33:32-04:00
Measured at: efcc51365 / not measured

The System → Hermes "LLM Auth / OAuth" card + `/api/v2/hermes/llm-auth-status` already surface the distinction:
- ChatGPT (Codex): authed=True; note = "authed; interactive `hermes -p dev chat` works. Headless researcher
  one-shot (hermes -z) returns no final response in Hermes v0.16.0 — automated lane pending a Hermes fix."
- Reason code (for the chatgpt researcher lane): **hermes_headless_limit** (not auth_pending /
  workspace_device_code_blocked / command_timeout / unsupported_version — auth + version are fine; the
  headless path is the blocker).
- Grok (xai-oauth): ✓ ready (proxy active). Local (Ollama): ✓ ready. Claude: key present, needs credits.
No credential forms; no token display. No UI rebuild required (existing card already shows it).
