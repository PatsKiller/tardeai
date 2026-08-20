# Flash activation + thesis canary — 2026-08-20

Authority: **READ_ONLY_ADVISORY**. No broker / order / stop / 2FA mutation.
Scope: governed Flash-first research engine activation + first living-thesis canary.

## Verdict

The Flash-first research engine was **productionized but not fully activated**.
This receipt records the activation steps that removed the operating gates and the
honest boundary reached on the living-thesis program.

## 1. CAP path fix (corrected root cause)

Original finding (`RESEARCH_ENGINE_FLASH_FIRST_FAILURE_2026-08-20.md`) blamed a
missing `LLM_GLOBAL_DAILY_USD_CAP`. Re-investigation found that was **stale**:

- The 8-19 cron→wrapper migration already sourced `~/.config/tradeai/agent-operator.env`
  on the live drain path (`run_watchlist_agent_jobs_offpeak.sh` logs
  `LLM_GLOBAL_DAILY_USD_CAP_ok=yes` every run; `deepseek_tradeai=present`).
- The two **real** gates were:

| Gate | Symptom | Fix |
|------|---------|-----|
| Canonical containment flag absent (`~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED`) | market governed canary `exit=78` every 15m | armed via `agent_jobs_containment.activate()` |
| `watchlist_maria_flash_narrative` `daily_soft_cap=120` exhausted overnight | `COST_CAP_EXCEEDED: daily request cap` → 8 errors → `agent_flash` circuit open | raised `daily_soft_cap` 120→240 |

Also added the process-scoped containment override to `run_watchlist_agent_jobs_offpeak.sh`
so the offpeak drain stays functional with the host flag armed (mirrors the market wrapper).

## 2. Flash proof (governed, exact model)

Triggered the sanctioned market wrapper (`run_governed_agent_flash_market.sh`),
which sources the operator env internally (no secret printed to the agent).

```
returned_model=deepseek-v4-flash  success=True  cost=1.61e-05  fallback=False   (×5)
LLM_GLOBAL_DAILY_USD_CAP_ok=yes
host_flag_still_present=yes
provider_calls=1  maria_two_pass_entered=false  process_jobs_entered=false
```

- `first_provider_attempted` / `actual_provider` = **DeepSeek Flash** (not `gemma3:4b`).
- Cost recorded (`$0.0000161`/call), `fallback_used=false`, 5/5 completed.
- Failure churn (CAP_MISSING / CIRCUIT_OPEN) **stopped** once containment was armed
  (direct worker invocations now fail-closed at entry, exit 78).

## 3. Thesis canary (SCHG / CSCO / ANET) — honest boundary

Coverage enumeration (read-only, `symbol_thesis_coverage_cli.py`):

```
RESEARCH_REQUIRED: 125   (HELD 25 · FORMER_HOLDING 49 · REENTRY 103 · WATCHLIST 5173)
symbol_thesis published: 0
```

SCHG / CSCO / ANET are all **former holdings** (`RESEARCH_REQUIRED`, `ACTIVE_MATERIAL`).
Gap-driven RI pipeline (`run_ri_pipeline_for_gap`, retrieve-only) reports:

```
gate = BLOCKED_PENDING_ACQUISITION_AND_CURATION
supporting=0  contradictory=0  structured=1
remaining_evidence_gaps = [insufficient_supporting_rag, ...]
acquisition_plan = searxng_metasearch, sec_filings, rss_news, financial_senses, deterministic_structured
```

**No thesis was invented.** The pipeline correctly holds synthesis at
`BLOCKED_PENDING_ACQUISITION_AND_CURATION` because these names have empty RAG. The
acquisition + embed + Flash-synthesis → `reconcile_symbol_thesis` → `CANARY_THESIS_APPLY`
path is the deliberate next operating step (gated behind acquisition/embed opt-in),
**not** a seed-summary shortcut.

## 4. Telegram acceptance — pending

Interactive CIO thesis proof and the gated proactive transport canary are deferred
until at least one `symbol_*@v1` pin exists (nothing to cite yet).

## 5. Status of related work

- PR #405 (P0–P3 truth/presentation + living-thesis program) is **MERGED** and
  **DEPLOYED** (release snapshot `5209c820`).
- This session's changes (containment arm is runtime state; `daily_soft_cap` bump +
  offpeak override are code/config) are committed and pushed separately.

## Non-goals

- No bulk re-queue of the ~300 prior CAP-miss failures.
- No inventing thesis text or Flash receipts.
- No permanent daily-budget decision from one day's measured spend.
