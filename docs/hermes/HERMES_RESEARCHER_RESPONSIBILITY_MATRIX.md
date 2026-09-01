> **Canonical:** the Hermes matrix is now generated from `data/runtime/hermes_canonical_status_latest.json` and HERMES_AGENTS_WORKFLOWS_SOULS_AND_SELF_LEARNING_MATRIX.md (Phase 217); this older matrix is superseded.

# Hermes Researcher Responsibility Matrix (2026-06-07)

Status:      ACTIVE
as_of:       2026-06-07T18:49:05-04:00
Measured at: efcc51365 / not measured

## Table 1 — Identity / Model Matrix
| Identity | Model | Provider | Tools | Runtime | Auto/Manual | Purpose | Writes | Safety | Learning feedback | v3 |
|----------|-------|----------|-------|---------|-------------|---------|--------|--------|-------------------|----|
| tradeai | gemma3:4b | custom | 0 | chat | manual | Trade AI advisory | none | tool-less, no broker | reads lessons/RAG | System→Hermes |
| tradeai12b | gemma3:12b-ctx4k | custom | 0 | chat | manual | deep advisory (exp) | none | tool-less | reads lessons | System→Hermes |
| Coordinator | gemma3 | Ollama | n/a | cron */15 | auto | orchestrate fleet | hermes_memory_events | advisory | coordination logs | /v3/hermes |
| Source Discovery | gemma3 | Ollama | n/a | timer | auto | discover sources | hermes_research_intelligence | staging | research outcomes | /v3/hermes |
| Librarian | gemma3 | Ollama | n/a | timer | auto | review/route findings | research_intelligence (status) | staging | routing outcomes | /v3/hermes |
| Embedding Curator | gemma3/embed | Ollama | n/a | timer | auto | embed candidates (gated) | hermes_embedding_queue | gated | embed promotion | /v3/hermes |
| Promotion Review | gemma3 | Ollama | n/a | timer | auto | promotion advisory | hermes_promotion_audit | advisory | promotion accuracy | /v3/hermes |
| Backlog Manager | gemma3 | Ollama | n/a | timer | auto | backlog health | research_intelligence (tags) | staging | backlog outcomes | /v3/hermes |
| Autonomous Research | gemma3 | Ollama | n/a | timer | auto | staged discovery | research_intelligence | staging | research outcomes | /v3/hermes |
| Momentum Catalyst | gemma3 | Ollama | n/a | timer | auto | catalyst research | catalyst JSONL | research | catalyst accuracy | Intelligence |
| Advisory Cache Worker | n/a | n/a | n/a | timer | auto | cache advisory | advisory cache | read-cache | n/a | Intelligence |
| High-LLM Worker | gemma3/queue | Ollama | n/a | queue | auto | escalated LLM jobs | llm cache | gated | job outcomes | Queue |
| Internal Deep Research Local | gemma3:27b/overnight | Ollama | none | BATCH_OVERNIGHT | auto (window) | deep synthesis | hermes_* staging | advisory | recommendation vs outcome | /v3/hermes (design) |
| Claude External | claude | Anthropic | none | manual/escalation | manual | high-stakes reasoning | hermes_external_research (proposed) | advisory, no creds | usefulness vs outcome | External queue (design) |
| ChatGPT External | gpt | OpenAI | none | manual/escalation | manual | second opinion/synthesis | via approved queue | advisory | usefulness vs outcome | External queue (design) |
| Grok External | grok | xAI | none | manual/escalation | manual | market/social narrative | hermes_external_research (proposed) | advisory, source-scored | usefulness vs outcome | External queue (design) |
| Operator (John/CIO) | human | — | — | human | manual | decide/approve | approvals/audit | full authority | choices feed learning | all v3 |

## Table 2 — Workflow Matrix
(see PHASE209G + PHASE210F; rows: source discovery, librarian backlog, embedding curation, promotion review,
ticker thesis challenge, momentum catalyst, advisory cache, self-learning overview, dual opinion, proposal
sandbox, journal/backtest learning, profit protection, high-LLM escalation, external consensus, SIEM
normalization, RAG source credibility/scar updates — each: owner/trigger/cadence/model/reads/writes/learns-from/
feeds-into/operator-action/state/gap.)

## Table 3 — Chat Usage Matrix
| Chat | When to use | When NOT | Model | Tools | Output | Escalates to | Safety |
|------|-------------|----------|-------|-------|--------|--------------|--------|
| default | general help | trading decisions needing fleet data | gemma3:4b | 0 | text | tradeai | no broker |
| tradeai | Trade AI advisory/review | needs live self-fetch | gemma3:4b | 0 | advisory | tradeai12b / deep / external | no trades |
| tradeai12b | deep/complex analysis | routine quick Q | gemma3:12b-ctx4k | 0 | advisory | internal deep / external | no trades |
| dev | code/docs/Codex | trading advice | future Codex | 14 (high-risk off) | code | — | no secrets to cloud |
| serverops | server-ops (future) | anything until hardened | unset | broad (HOLD) | advisory | operator | no trading |
