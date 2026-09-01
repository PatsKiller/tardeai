# Phase 199I — State-of-Repo Snapshot Generator

Status:      HISTORICAL
as_of:       2026-06-04T22:51:02-04:00
Measured at: efcc51365 / not measured

`scripts/generate_state_of_repo_snapshot.py` → `docs/project/STATE_OF_REPO_LATEST.md`. Read-only;
DB facts degrade gracefully to "unknown" if the DB is unavailable. Mutates no runtime state.

## Output sections
- **Git** — branch, dirty count, latest 5 commits
- **Phase** — latest architecture phase doc + current phase
- **Safety state** — paper mode (ALPACA_MODE), live trading (PROHIBITED/OFF), live Alpaca endpoint
  (BLOCKED), Level 7 (PROHIBITED), ATM mode, protection workstream (PAUSED/observe-only), threshold
  tuning (OBSERVE-ONLY)
- **Runtime control plane** — cron/service/timer/unique-script/multi-scheduled counts (from the 199B
  inventory) + the 7 target pipelines + dry-run controller note
- **LLM queue** — deep_overnight_llm_queue pending
- **Hermes research** — last write age (24/7 expected)
- **Blockers / gate** — closed-trades vs 100 (gate BLOCKED by design)
- **Next triggers** — cadences unchanged; freshness monitor `*/20`, watchdog `*/30`
- **Governance reminders** — v3 canonical; `/api/v2` = backend namespace not v2 UI; Drive sync; no
  cron disabled without approval

## Graceful degradation
DB query failures (or missing inventory) yield "unknown" rather than erroring — safe to run anywhere.

## Verified
`python3 scripts/generate_state_of_repo_snapshot.py` → wrote the snapshot:
branch=main, dirty=18, live_allowed=False; runtime 211 cron / 30 svc / 32 timers / 143 unique / 31 dup.

---
*Read-only generator. Run after phase changes; pairs with the Drive sync reminder.*
