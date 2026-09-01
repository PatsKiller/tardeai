# Phase 209E — Hermes Chat Profile Usage Matrix (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:29:04-04:00
Measured at: efcc51365 / not measured

| Profile | Model | Provider | Tools | Status | Use in chat | Used by automation | Safety boundary | Promotion criteria |
|---------|-------|----------|-------|--------|-------------|--------------------|-----------------|--------------------|
| default | gemma3:4b | custom (Ollama) | 0 | active | general non-trading help | no | no broker/trading/secrets | n/a |
| tradeai | gemma3:4b | custom | 0 | active/stable | **Trade AI advisory/review** (portfolio, strategy, backtest, journal, research findings) | **no** | no trades/orders/stops/proposals/secrets; tool-less | is the stable default for Trade AI chat |
| tradeai12b | gemma3:12b-ctx4k | custom | 0 | experimental | deeper/complex Trade AI analysis when 4b is too shallow | **no** | same as tradeai; tool-less | promote only after: stable canaries, no hallucinated facts, operator A/B vs 4b |
| dev | unset (future Codex) | custom→openai-codex | 14 (terminal/code_exec/computer_use OFF) | future | code/docs/config/tests; Codex engineering | no | not Trade AI runtime; no secrets to cloud | operator OAuth + model selection |
| serverops | unset | custom | broad (HOLD) | future/unconfigured | (not yet) server-ops | no | advisory until hardened | harden tools + assign model first |

## Answers
- **default** = the default profile; general use.
- **tradeai** = trading advisory (stable). **tradeai12b** = same role, experimental 12B for deeper analysis.
- Safe for trading advisory: tradeai (primary), tradeai12b (experimental). Experimental: tradeai12b.
- Tool-less: default/tradeai/tradeai12b. Has tools: dev (high-risk off), serverops (HOLD).
- Local-only: default/tradeai/tradeai12b. Codex/OAuth future: dev (and serverops later).
- Never touch broker/trading: ALL (only the operator + gated executors touch trading; Hermes never does).
- **Any automated job calls tradeai12b? NO** (no job uses any chat profile; fleet scripts call Ollama directly).
- **tradeai12b should remain experimental** until the promotion criteria are met (operator A/B).
