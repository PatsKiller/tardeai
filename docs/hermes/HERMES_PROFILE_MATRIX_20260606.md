# Hermes Profile Matrix — 2026-06-06

Status:      ACTIVE
as_of:       2026-06-06T23:14:31-04:00
Measured at: efcc51365 / not measured

Verified live via `hermes profile list` / `<profile> config show` / `<profile> tools list` on ms01.
All profiles use provider=custom → local Ollama (`http://127.0.0.1:11434/v1`, api_mode openai).

| Profile | Path | Model | Tools | Purpose | Runtime Status | Safety Boundary |
|---------|------|-------|-------|---------|----------------|-----------------|
| **default** | `~/.hermes` | gemma3:4b | disabled | Global/general assistant | Active (gateway stopped) | No live/current claims without tools; no secrets; no trading/admin actions |
| **tradeai** | `~/.hermes/profiles/tradeai` | gemma3:4b | disabled (all ✗) | Stable restricted Trade AI advisory/review | Active (gateway stopped) | No trades, orders, stops, proposals, broker/holdings mutation, or raw secrets |
| **tradeai12b** | `~/.hermes/profiles/tradeai12b` | gemma3:12b-ctx4k | disabled (all ✗) | Experimental 12B context-gated advisory | Active, experimental | Same as tradeai; advisory only; do NOT trust current-version/system answers from model memory |
| **dev** | `~/.hermes/profiles/dev` | — (unset) | — (unconfigured) | FUTURE ChatGPT/Codex development route | Not configured | Code/config/docs/tests only; no broker secrets; no autonomous runtime; human-invoked |
| **serverops** | `~/.hermes/profiles/serverops` | — (unset) | — (unconfigured) | FUTURE controlled server operations | Not configured | Advisory only until explicitly configured + operator-approved |
| **old sidecar** | `hermes_sidecar/.hermes` (+`install`, v0.15.2) | gemma3:4b | disabled | Legacy gated install | Retained, NOT canonical | Rollback / migration source / audit evidence only |

## Rules
- **default** — global/general; with tools disabled it must not claim it checked live files/commands/versions.
- **tradeai** — stable restricted advisory; no trades/orders/stops/proposals/secrets (enforced by SOUL + tools off).
- **tradeai12b** — experimental 12B advisory; same restrictions; explicitly distrusts its own current-version answers.
- **dev** — future direct Codex/dev route; code/config/docs/tests only; no broker secrets; no autonomous runtime.
- **serverops** — future controlled server ops; advisory until configured.

## Verified (2026-06-06)
tradeai + tradeai12b tools: web/browser/terminal/file/code_execution/vision/video all **disabled (✗)**.
SOULs present for all; no `execute actions via your tools` phrase in tradeai/tradeai12b (only safe negated boundaries).

### x_search pinned off (2026-06-06)
`x_search` (read-only X/Twitter search) auto-enabled in the **Command Center server runtime** for
`tradeai`/`tradeai12b` because ambient xAI/X credentials exist there (a bare shell showed it disabled).
It is now **explicitly pinned off** via `disabled_toolsets: [x_search]` in each profile config, so the
profile policy wins over the ambient credentials. Both stable Trade AI profiles now show **zero enabled
tools** in BOTH bare shell and Command Center runtime (`/api/v2/hermes/profiles-status`:
`tradeai: disabled`, `tradeai12b: disabled`). **`default` was subsequently pinned the same way**
(`~/.hermes/config.yaml` → `disabled_toolsets: [x_search]`), so **all three** profiles (default, tradeai,
tradeai12b) now show `disabled` in the runtime. No credentials read/removed; no `.env` edited.
