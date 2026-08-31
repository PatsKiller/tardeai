# PHASE 216A — Live v3 Portal Truth Capture (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T17:50:18-04:00
Measured at: efcc51365 / not measured

Source: live `/api/v2/hermes/*` endpoints (source of truth over stale docs).

## Header / infra
- Hermes version: v0.16.0 (2026.6.5) · CLI ~/.local/bin/hermes · venv ~/.local/share/hermes-agent-venv · home ~/.hermes
- Portal header (System): 38 timers · 209 crons · 2 services · 6 LLM jobs (live spot-check: 32 user timers, 212 crontab lines — header scope differs; API is canonical for the rest)
- Workflows: **19** · graph nodes: **9** · DB tables: **6** · safe views: **13** · CLI profile used by automation: **false**
- DB writes/24h: research_intelligence=**436** · memory_events=**95**
- Kill-switch: INACTIVE · canonical `data/runtime/HERMES_DISABLED` · retired `.hermes/DISABLED` ignored
- Retired/legacy agents: **24** items · gateway failed/disabled

## Profiles (live)
| Profile | Model | Tools | SOUL hash |
|---|---|---|---|
| default | gemma3:4b | disabled (0) | 7a3aa0e6b3d18ac1 |
| tradeai | gemma3:4b | disabled (0) | fc060ad139e96d48 |
| tradeai12b | gemma3:12b-ctx4k | disabled (0) | 9ed7b8a993469452 |
| dev | gpt-5-codex | 14 enabled (no terminal/code_exec/computer_use) | 8df596720c9103a3 |
| serverops | unset | **18 enabled incl terminal, code_execution, computer_use, x_search** (P1 hardening) | aebf7b52c57e8bba |

## LLM / Auth lanes (live)
| Lane | Authed | Usable | Headless | Reason |
|---|---|---|---|---|
| ChatGPT (Codex) | YES | YES (interactive) | unavailable | hermes_headless_limit (runtime enabled=false, human-invoked) |
| Grok (xAI) | YES | YES | ready | ok (xai-oauth proxy UP :8645) |
| Claude (Anthropic) | YES (key) | YES | credits_required | anthropic_credits_required |
| Nous Portal | NO | NO | auth_pending | auth_pending |
| Local (Ollama) | YES | YES | ready | ok |

## Self-learning + lanes (live)
- Closed-loop: **PARTIAL** (by design) · **11 loops** · 11 advisory-only · **9** feed prompts · **0** mutate scoring (operator-gated)
- Internal deep research lane: **designed (not enabled)** · gemma3:27b/overnight · gemma4 deferred
- External lanes: Claude/ChatGPT/Grok/Consensus (Grok live; Codex interactive; Claude credits; Nous pending)
- Loop sample (external_researcher_feedback): steps stored, 2 completed
- Gaps: dedicated research_backlog table; shadow-efficacy < graft sample
