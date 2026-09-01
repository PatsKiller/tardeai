# Hermes External Researcher — Claude Lane (2026-06-07)

Status:      ACTIVE
as_of:       2026-06-07T13:23:09-04:00
Measured at: efcc51365 / not measured

Implements the Phase 210D/G Anthropic/Claude external research lane. `scripts/hermes_external_researcher.py --lane claude`.

## Status
- **WIRED + verified reachable.** Redaction, packet build, API call, and DB storage all work.
- **Blocked only by Anthropic billing:** live call returns `HTTP 400 — "Your credit balance is too low to
  access the Anthropic API."` Add credits at Anthropic Plans & Billing to activate. No code change needed.

## What it does
Manual / escalation-triggered (NOT auto-scheduled). Builds a **redacted** escalation packet (question +
whitelisted high-level context), sends it to Claude, and stores the structured response in
`hermes_external_research`. Advisory-only — never touches broker/order/stop/proposal/holdings/trading.

## Run
```
python3 scripts/hermes_external_researcher.py --lane claude --question "..." [--symbol AAPL]   # DRY-RUN (default; sends nothing)
python3 scripts/hermes_external_researcher.py --lane claude --question "..." --apply           # send (needs Anthropic credits)
python3 scripts/hermes_external_researcher.py --lane claude --question "..." --model claude-opus-4-8 --apply
```

## Safety (verified)
- **Redaction (hard):** strips $ amounts, account numbers, API keys/tokens, .env content, emails, long digit
  runs; drops any line containing secret/credential markers; only whitelisted context is assembled; a second
  redaction pass runs over the whole packet. Verified: account#→[REDACTED_NUM], $250,000→$[REDACTED_AMOUNT],
  sk-…→[REDACTED_KEY].
- **API key:** read from environment at call-time only — never stored in DB, logged, or returned by the API.
- **DRY-RUN by default** — shows exactly what would be sent; `--apply` required to call out.
- Output schema: recommendation, evidence, dissent, confidence, risk_flags, learning_candidate, operator_action.
- Storage: `hermes_external_research` (redacted inputs + structured response + later usefulness_score for learning feedback).
- **NOT auto-scheduled.** Escalation triggers/priority in PHASE210G; lane is operator-invoked.

## v3 visibility
`GET /api/v2/hermes/external-research` (read-only, redacted) — lanes_wired=[claude], recent packets + status.

## Other lanes
chatgpt / grok / consensus remain designed (210D); same runner pattern; wire when operator approves + provides access.

> Governance/approval: EXTERNAL_LLM_USAGE_POLICY_20260607.md.
