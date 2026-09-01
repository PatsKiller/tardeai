# Hermes Identity Profiles — Due Diligence + Seeded Identities (2026-06-07)

Status:      ACTIVE
as_of:       2026-06-07T12:05:16-04:00
Measured at: efcc51365 / not measured

Each of the 5 Hermes profiles now has a researched identity (label + purpose + description metadata +
role-specific SOUL), applied via the validated API (`POST /api/v2/hermes/identity` + `/soul`, backup-first,
SOUL safety-validated). Reproducible: `scripts/seed_hermes_identities.py --apply`.
Identity metadata persists to `~/.hermes/profiles/<p>/identity_meta.json`; SOULs to `<p>/SOUL.md`.

## What each profile does (due diligence — grounded in Phase 208 audit)

### default — Global Hermes (general assistant)
Model gemma3:4b, tools off. General local reasoning/planning/writing/docs/troubleshooting. Not Trade AI
advisory, not dev. Reasons over what you give it; asks you to run live checks rather than claiming it did.

### tradeai — Trade AI Advisory  ← the Trade AI identity
Model gemma3:4b, **0 tools** (the safety boundary). Read-only advisory analyst for Trade AI v12. It supports
the operator by consuming:
- operator-provided evidence, and
- the **Hermes research fleet's** staged output: `hermes_research_intelligence`, `hermes_validation_findings`,
  promotion recommendations, and **Trade AI safe views** (the read-only WALL).
It summarizes, challenges assumptions, flags risks, reviews docs/logs, interprets the research fleet's
findings, and prepares operator recommendations. Never trades/orders/stops/proposals/broker/secrets.

### tradeai12b — Trade AI Advisory (experimental 12B)
Model gemma3:12b-ctx4k (context-gated), 0 tools. Same role/restrictions as tradeai, higher-capacity model
for deeper analysis. Unpromoted (not the default Trade AI model).

### dev — Development / Codex
Model unset (future Codex via operator OAuth, provider openai-codex). Human-invoked engineering assistant
(code/docs/config/tests/Claude Code prompts). Not Trade AI runtime, not autonomous. terminal/code_execution/
computer_use disabled; SOUL forbids sending raw secrets/holdings/.env to cloud models.

### serverops — ServerOps (future, advisory)
Model unset, advisory-only/unconfigured. Reserved for controlled server-ops (host/services/timers/logs/
backups). Still carries broad default tools — HOLD: harden before use (risk-register R2). Proposes; operator executes.

## The research fleet tradeai supports (separate subsystem, not profiles)
Coordinator · Source Discovery · Librarian · Embedding Curator · Promotion Review · Research Backlog
Manager · Autonomous Research Manager — run via systemd timers + `scripts/hermes_*.py`, feeding the
hermes_* staging tables that tradeai reads. (Phase 208E: 476 writes/24h, all timers success.)

## Safety (post-seed, verified)
SOUL audit: all 5 active SOULs safe (no live-trading, no broker-mutation, no retired refs). tradeai/
tradeai12b retain the required boundary lines + 0 tools. Identity guards unchanged (no gemma3:12b on
default/tradeai, no qwen3:14b, Trade AI local-only). Backups written before every SOUL/config change.
