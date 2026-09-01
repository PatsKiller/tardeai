# Phase 210D — External Researcher Escalation Design (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T13:31:30-04:00
Measured at: efcc51365 / not measured

All external lanes are **advisory-only, no credentials in-app, no broker/trading mutation, full context block
in, structured evidence + uncertainty out, cost-controlled, source-scored, stored for learning feedback.**
None are enabled in this phase (design only; operator-driven auth required).

## 1. Anthropic / Claude Researcher
Purpose: high-stakes reasoning — retirement/tax/SSDI/IRMAA, complex portfolio & risk synthesis, policy/legal/
compliance interpretation, final external challenge on critical decisions.
Boundary: no execution, no credentials, advisory-only; returns structured evidence + uncertainty.

## 2. OpenAI / ChatGPT Researcher (via dev profile openai-codex / API, operator-driven)
Purpose: broad second opinion, code/design review, structured synthesis, matrix/doc generation, alternative
reasoning/checklists, operator-facing explanation.
Boundary: advisory-only; no TradeAI writes except through the approved LLM queue; no broker mutation.

## 3. xAI / Grok Researcher
Purpose: fast market/social/news narrative challenge, sentiment/catalyst interpretation, alternative market
thesis, social zeitgeist, momentum/catalyst escalation.
Boundary: advisory-only, no execution; **source quality MUST be scored** (social/web is noisy).

## 4. Optional External Consensus Panel
Run when: internal Hermes vs TradeAI disagree sharply; weak evidence + high decision importance; repeated
operator/Hermes disagreement. Compares the 3 external views into one escalation packet.

## Per-lane spec (schema)
- trigger conditions (see 210G), input packet schema (context block: positions-redacted, evidence, question,
  constraints), output schema (recommendation, evidence[], dissent, confidence, risk_flags, learning_candidate,
  operator_action), cost controls (per-call + daily cap), provider/model verification (CLI/login proof),
  rate limits, privacy controls (redact secrets/holdings/.env), storage table (hermes_external_research —
  proposed), v3 visibility (External Escalation Queue), learning feedback (was the external advice useful vs
  outcome → source/lane usefulness score).

---
## Claude lane WIRED (2026-06-07)
`scripts/hermes_external_researcher.py --lane claude` built+verified (redaction proven, request reaches Anthropic). Blocked only by Anthropic credit balance (operator billing). Manual/escalation; not auto-scheduled. See HERMES_CLAUDE_EXTERNAL_LANE_20260607.md.

---
## ChatGPT + Grok lanes wired (2026-06-07)
chatgpt = openai-codex OAuth (free; auth_pending), grok = xAI API (working). Same redaction/dry-run/advisory pattern. See HERMES_EXTERNAL_LANES_STATUS_20260607.md.
