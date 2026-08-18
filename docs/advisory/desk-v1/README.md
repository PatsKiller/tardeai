# Advisory Desk v1 — Documentation Index

**CURRENT OPERATOR TRUTH (living sheet, R6):**  
[`docs/investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md`](../../investment-office/CIO_AND_ADVISORY_LIVING_STATUS.md)  
This sheet overrides older Advisory phase write-ups when they disagree. Drive: same filename, replaced in place.

**Branch:** `feature/advisory-desk-v1`  
**Flag:** `ADVISORY_DESK_V1` (enabled 2026-08-12 in `config/advisory_desk.yaml`; systemd timer live via drop-in)  
**Authority:** READ_ONLY_ADVISORY throughout  
**Phases 0–7:** code complete 2026-08-11 · promotion gate **NOT_PROMOTED** (wait for 30 green shadow sessions)

## Autonomy in one sentence

**Scheduled advisory factory with LLM brains (Flash/Pro on timer-fired jobs) — not free-running agents, not autonomous traders.**  
See [AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md](./AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md).

## Canonical documents

| Doc | Purpose |
|---|---|
| [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md) | Approved end-to-end plan: CIO + wealth advisors, Flash→Pro, phases, PR DAG, pass criteria |
| [AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md](./AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md) | **Honest answer:** brains vs timers; goal wakes; desk not self-waking |
| [RUNTIME_TRUTH_2026-08-11.md](./RUNTIME_TRUTH_2026-08-11.md) | Host unit pass/fail (WS0) |
| [AUTONOMY_GOAL_THESIS_COMPLETE.md](./AUTONOMY_GOAL_THESIS_COMPLETE.md) | Goal store + dispatcher acceptance (per-goal thesis snippets) |
| [../../cio/THESIS_STORE_P3.md](../../cio/THESIS_STORE_P3.md) | **P3** versioned desk thesis (`desk@vN` pins) |
| [../../cio/WAKE_TRACES_P5.md](../../cio/WAKE_TRACES_P5.md) | **P5** lightweight wake traces (`cio_wake_traces.jsonl`) |
| [../../cio/P2B_PLAN_ENRICHMENT.md](../../cio/P2B_PLAN_ENRICHMENT.md) | **P2b** plan enrichment under governed LLM cap |
| [../../cio/CIO_TELEGRAM_CONVERSE_RUNBOOK.md](../../cio/CIO_TELEGRAM_CONVERSE_RUNBOOK.md) | **P1** dedicated CIO Telegram converse |
| [../../cio/CIO_WHATSAPP_CONVERSE_RUNBOOK.md](../../cio/CIO_WHATSAPP_CONVERSE_RUNBOOK.md) | **P4** WhatsApp mirror channel (Cloud API; flag default off) |
| [SITUATION_CATALOG_V1_FREEZE.md](./SITUATION_CATALOG_V1_FREEZE.md) | **FROZEN** S1–S8 situations + plan schema + SpaceX fixture |
| [../../cio/SITUATION_CATALOG_V1.md](../../cio/SITUATION_CATALOG_V1.md) | Phase 2a code catalog + operator commands |
| [P0_BRIDGE_OUTCOME_2026-08-11.md](./P0_BRIDGE_OUTCOME_2026-08-11.md) | P0 outcome: governed bridge path, registry, systemd unit, tests |
| [PHASE1_DATA_TRUTH_OUTCOME_2026-08-11.md](./PHASE1_DATA_TRUTH_OUTCOME_2026-08-11.md) | Phase 1: lots rebuild, catalyst path, validation, Risk/Tax holdings enqueue, flag |
| [PHASE2_QUALITY_CACHE_OUTCOME_2026-08-11.md](./PHASE2_QUALITY_CACHE_OUTCOME_2026-08-11.md) | Phase 2: evidence quality, stable-prefix cache, dollars-first Pro synthesis |
| [PHASE3_MEMORY_OUTCOME_2026-08-11.md](./PHASE3_MEMORY_OUTCOME_2026-08-11.md) | Phase 3: verdict history, feedback codes, thrash, outcome scoring |
| [PHASE4_SURFACE_DELIVERY_OUTCOME_2026-08-11.md](./PHASE4_SURFACE_DELIVERY_OUTCOME_2026-08-11.md) | Phase 4: /api/v3/advisory, CC page, Telegram brief + /advisory |
| [PHASE5_SHADOW_OUTCOME_2026-08-11.md](./PHASE5_SHADOW_OUTCOME_2026-08-11.md) | Phase 5: 20-session shadow track, Guardian/Ledger/Steph |
| [PHASE6_LESSONS_BROKER_OUTCOME_2026-08-11.md](./PHASE6_LESSONS_BROKER_OUTCOME_2026-08-11.md) | Phase 6: kb_lessons, Iris, auto-retire, notification broker |
| [PHASE7_PROMOTION_OUTCOME_2026-08-11.md](./PHASE7_PROMOTION_OUTCOME_2026-08-11.md) | Phase 7: 30-session promotion gate, morning default path |
| [MATURITY_BASELINE_2026-08-12.md](./MATURITY_BASELINE_2026-08-12.md) | Field-gap map vs Morgan Stanley report + 4/10 maturity rubric |
| [DEEPSEEK_USAGE_2026-08-12.md](./DEEPSEEK_USAGE_2026-08-12.md) | DeepSeek routing, key path, cost controls, prompt curation (read-only) |
| [SURFACE_REPORT_AND_ACTORS_2026-08-12.md](./SURFACE_REPORT_AND_ACTORS_2026-08-12.md) | **Who consumes the desk** (CIO/wealth/advisor), Telegram map, MS-style report + CIO event brief + timers |
| [CC_V3_MATURITY_CRITIQUE_2026-08-12.md](./CC_V3_MATURITY_CRITIQUE_2026-08-12.md) | **Command Center v3 critique** (1–10 per item) + polish: snapshot fix, LLM-on, de-coded labels, tooltips |
| [LLM_SURFACE_FIX_2026-08-12.md](./LLM_SURFACE_FIX_2026-08-12.md) | **LLM flag root-cause fix**: bridge `thinking` field, relaxed validator, enrichment persistence → Flash/Pro now reach `/v3/advisory` |
| [HEALTH_AGENT_FIXES_2026-08-12.md](./HEALTH_AGENT_FIXES_2026-08-12.md) | Health fixes: stale release-manifest FAIL + Finnhub 401 `data_source_auth_failed` |
| [DATA_INTEGRITY_AUDIT_2026-08-12.md](./DATA_INTEGRITY_AUDIT_2026-08-12.md) | **Integrity audit**: fabricated watchlist verdicts/confidence, aggregate-evidence inflation, allocation confidence inversion, CIO watchlist stale path — all fixed |

## Related diagnostics (repo root / prior sessions)

| Doc | Notes |
|---|---|
| `S1_DIAGNOSIS_2026-08-10.md` | EXIT avalanche / underweight rule (historical) |
| `S6_REPORT.md` | Data truth + Flash run quality snapshot |

## Runtime artifacts

| Path | Role |
|---|---|
| `data/runtime/advisory_desk_latest.json` | Latest deterministic desk snapshot |
| `data/runtime/advisory_opinions_latest.json` | Live Flash opinions + Pro synthesis (enrichment → read path) |
| `data/runtime/advisory_opinion_cache.json` | Local per-row opinion cache |
| `data/cio/cio_theses.jsonl` | P3 versioned desk thesis events |
| `data/cio/cio_wake_traces.jsonl` | P5 wake traces (why wake / llm path) |
| `data/cio/cio_plans.jsonl` | Situation / converse action plans |
| `data/cio/cio_goals.jsonl` | Goal store events |
| `/run/user/<uid>/tradeai/env` | SM-rendered secrets (Bitwarden) |
| `logs/cio_governed_bridge.log` | Bridge stdout/stderr when unit installed |

## Model policy (summary)

| Workload | Model | Process |
|---|---|---|
| Per-row opinion | DeepSeek V4 **Flash** | `advisory_desk_opinion` |
| Desk synthesis | DeepSeek V4 **Pro** | `advisory_desk_synthesis` |

Both must egress only via `cio_governed_model_bridge` on `127.0.0.1:8766`.
