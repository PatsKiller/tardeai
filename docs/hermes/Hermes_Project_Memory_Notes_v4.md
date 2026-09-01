# Project Memory Notes - Hermes Sidecar Strategy v4

Status:      ACTIVE
as_of:       2026-05-29T22:39:06-04:00
Measured at: efcc51365 / not measured

## Durable Decision
Hermes should be integrated into Trade AI as a near-24/7 research, memory, and challenge sidecar. It should not be installed as a standalone Railway trading worker or second execution system.

## Ownership
- Trade AI remains the system of record and execution authority.
- Hermes researches, remembers, challenges, and recommends.
- Claude Code implements only operator-approved changes.
- John approves anything affecting execution, DB state, proposal state, cron, broker behavior, model routing, or strategy configuration.

## Hermes Target Design
Hermes v4 is organized into six pods and 24 logical agents:
1. Research Intelligence Pod
2. Trade Lifecycle Pod
3. Portfolio Planning Pod
4. Strategy and Experiment Pod
5. Operations and Governance Pod
6. Coordinator and Memory Pod

## First Launch Scope
Start with five agents only:
1. Chief Hermes Coordinator
2. Ticker Research Agent
3. News Research Agent
4. Incubator Research Agent
5. All-Trade Reflection Agent

## First Pilot Outputs
- Daily Hermes Research Brief
- Ticker Dossiers
- Incubator Watch Report
- All-Trade Lessons Report
- Missed Opportunity Report
- Research Debt Report
- One one-variable strategy hypothesis

## Safety Guardrails
Hermes must not place orders, call broker submit endpoints, approve/reject/expire proposals, mutate paper_trades, mutate journal rows, mutate proposal lifecycle state, edit `.env`, change cron, or create a duplicate trading worker.

## Model Policy
- Local first.
- gemma3:12b for normal research and analysis.
- gemma3:4b for quick summaries/fallback.
- Gemma4 31B via llama.cpp only for off-hours deep review.
- qwen3:14b, Gemma4 e2b/e4b, and gemma3:27b GPU are not production.
- Grok/xAI is optional later as an external challenger only.

## Next Build Step
Do not install Hermes immediately. First run a Hermes Compatibility Audit and Sidecar Install Plan:
- check install behavior
- check memory storage
- check local model support
- check external API behavior
- check sandboxing
- check read-only connectors
- check rollback
- propose final install/no-install decision
