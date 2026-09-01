# Hermes dev Profile — Codex/ChatGPT Setup — 2026-06-06

Status:      ACTIVE
as_of:       2026-06-07T14:32:18-04:00
Measured at: efcc51365 / not measured

## Purpose
Prepare the Hermes `dev` profile for **future human-invoked** ChatGPT/Codex development assistance.
Not Trade AI runtime; not an autonomous gateway. tradeai/tradeai12b are unchanged and remain local/restricted.

## Discovery results (from installed Hermes CLI help — no guessing)
- `hermes login --help` → providers: `{nous, openai-codex, xai-oauth}`; "Run OAuth device authorization flow".
- **Outcome A**: Hermes natively supports a ChatGPT/Codex **OAuth device-code** provider (`openai-codex`) —
  the subscription OAuth route, not an API-key route.
- `hermes model` selects provider + default model interactively (also does OAuth).
- `hermes config set <key> <value>` exists (non-interactive), but the proper provider/model wiring is done
  by the login/model flow after auth.

## Verified local command
```
hermes auth add openai-codex --type oauth   # OAuth device-code (browser) — OPERATOR runs this manually
dev model                              # pick the Codex model for the dev profile (interactive)
dev config show                        # verify provider/model on dev
```
Auth is **operator-interactive** (device-code + browser). Claude Code did NOT run it and never handles
ChatGPT credentials/tokens. No web-UI OAuth button.

## Auth method / status
- Route: provider `openai-codex`, OAuth device-code.
- Current: `codex_auth_configured = not configured`, `dev_model_configured = false`, `codex_runtime_enabled = false`.
- Completing auth + model selection is left to the operator (subscription/quota + browser login).

## dev profile config before/after
- Before: model unset; SOUL generic.
- After: model still unset (no cloud wired without operator OAuth); **SOUL hardened** (backup at
  `~/.hermes/profile_backups/dev/SOUL.md.bak_codex_<ts>`) with dev-mode boundaries + Codex policy
  (no trades/orders/broker creds/.env; redact before sending to cloud; human-invoked only; not autonomous).

## Tool policy
- dev currently has full development toolsets enabled (web, browser, terminal, file, code_execution,
  vision, image_gen, tts, skills, todo, memory, session_search, clarify, delegation, cronjob, messaging,
  computer_use = 17 enabled).
- **Operator decision (2026-06-06): leave dev tools as-is (all enabled)** — dev is a development profile
  that needs terminal/file/code_execution for engineering work. Cloud-data risk is mitigated by the SOUL
  policy (no raw secrets/holdings/.env to cloud; redact first). Not changed in this pass.

## Safety boundaries
No Codex in tradeai/tradeai12b/default. No gateway/Telegram/Discord/cron/systemd enabled. No `.env` read,
no secrets printed, no credentials migrated, no third-party Codex packages installed. gateway remains
failed/disabled. No broker/trading changes. Live chat sessions untouched.

## Verification
- tradeai = gemma3:4b, 0 tools enabled (unchanged). tradeai12b = gemma3:12b-ctx4k, 0 tools (unchanged).
- gateway: active=failed, enabled=disabled.
- dev SOUL hardened + readable via Command Center; tradeai/tradeai12b SOUL boundaries intact.

## Command Center status update
`/api/v2/hermes/codex-dev-status` now surfaces: `supported_provider=openai-codex`,
`verified_login_command=hermes auth add openai-codex --type oauth`, live `codex_auth_configured`
(from `hermes auth list`), `codex_runtime_enabled=false`, dev tools note, and operator terminal instructions.
The System→Hermes panel renders these (auth-pending until the operator completes device-code login).

---
## High-risk dev tools disabled before Codex login (2026-06-06)
Before operator OAuth, the dev profile had its high-risk LOCAL execution toolsets explicitly disabled via `hermes -p dev tools disable code_execution terminal computer_use`:
- `terminal` — disabled
- `code_execution` — disabled
- `computer_use` — disabled

This is a hard boundary so the future cloud-backed dev profile cannot directly run terminal commands, execute code, or control the computer unless the operator explicitly re-enables them later. dev went 17 -> 14 enabled (web/browser/file/vision/skills/todo/memory/etc. remain per operator). Codex remains future/human-invoked; the operator completes OAuth manually. The status collector now reports dev's real tool state (profile-level disabled wins over model-unset "future" label).
