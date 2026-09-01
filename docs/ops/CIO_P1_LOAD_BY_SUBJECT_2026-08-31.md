# CIO P1 — scheduled wake loads InstrumentRecord before decide (M5)

Status:      ACTIVE  
as_of:       2026-08-31T22:30:00Z  
Measured at: worktree `feat/cio-p1-load-by-subject` · local commit (not pushed)  
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR=0  

---

## Timer inventory (read-only)

### Cron (CIO / hermes / situation / wake)

| schedule | command (abbrev) | notes |
|---|---|---|
| `*/5 * * * *` | `…/CURRENT && …/python scripts/cio_wake_dispatch_entrypoint.py` | **wired job** — sole wake claimant |
| (disabled) | `cio_decision_engine.py --run` | DISABLED 2026-08-08 |
| many | hermes_* / hermes_subject_enhance / coordinator | research fleet; not IR wake |

### systemd user timers

| unit | cadence | ExecStart |
|---|---|---|
| `tradeai-cio-reactive.timer` | ~2 min | `scripts/cio_reactive_cycle.py --once` (CURRENT) |
| `tradeai-cio-material-scan.timer` | ~10 min | `scripts/cio_material_scan.py --live` |
| `tradeai-cio-delivery.timer` | ~5 min | delivery worker |
| `tradeai-cio-defer-revisit.timer` | hourly | defer revisit |
| `tradeai-hermes-cio-worker.timer` | ~15 min | hermes CIO worker |
| hermes-* | various | observation / librarian / deep-research / … |

### OpenClaw gateway timers

Migrated jobs only (aegis evening, steph weekly/monthly, plan reminders, Gemma research). **No CIO InstrumentRecord wake** in OpenClaw cron.

**No new crontab installed this PR.** Existing `cio_wake_dispatch_entrypoint.py` cron is the consumer.

---

## What was wired

| step | function:line | role |
|---|---|---|
| Wake-queue consult (existing #723) | `scripts/lib/cio_wake_dispatcher.py:192` | load record **before claim** — no twin plan |
| Subject resolve + cadence | `scripts/lib/cio_wake_subject.py` `decide` | `skip/cadence_not_due` on future `next_eligible_at` |
| **Research preflight (this PR)** | `scripts/lib/cio_research_preflight.py:80` `decide_after_load` | after materiality → load → days-old defer + hashes → **skip without calling** `ResearchNeedDecision.decide` |
| Dry-run entry | `scripts/cio_wake_dispatch_entrypoint.py:36` `dry_run_record_consult` | `--dry-run`: print subject_key + decision; no claim |
| Gate report path | `scripts/cio_research_gate_report.py` | uses `decide_after_load` instead of bare `decide` |

Cadence skip for research decide requires **all three**:
1. `next_eligible_at` in the future  
2. hashes unchanged (UNSET ≠ change)  
3. operator `defer` turn ≥ 48h old  

---

## Acceptance quotes

### A — unit

```
pytest tests/test_cio_p1_load_by_subject.py tests/test_wake_loads_record.py -q
# 19 passed
```

- old defer (72h) + unchanged hashes → `decide_called=False`, `reason=cadence_not_due`
- mutation: `next_eligible_at` past → `decide_called=True`

### B — dry-run (cron form)

```
cd /tmp   # neutral cwd
PYTHONPATH=<worktree>:<worktree>/scripts \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python \
  <worktree>/scripts/cio_wake_dispatch_entrypoint.py --dry-run
# exit 0
# P1_DRY no PENDING wakes   ← live queue empty at as_of
```

Synthetic mutation (same preflight):

```
MUTATION_A subject_key='HELD:SCHD' decision=skip reason=cadence_not_due decide_called=False record_loaded=True
MUTATION_B subject_key='HELD:SCHD' decision=flash … decide_called=True record_loaded=True
MUTATION_OK
```

### C — soak

**M5 unattended soak: NOT OBSERVED.**

This PR did not wait for the next natural `*/5` cron fire against a subject with a days-old defer. Hand-run / unit / dry-run = M5 **candidate** only. Claim OBSERVED only after a natural timer fire loads the record with nobody at the keyboard.

---

## Pins honoured

BehaviorWriteRefused untouched · no Telegram send · no residual_web live drain · no AgentView · dust/TEST/CASH-as-ticker still refused at mint (`is_mintable`) · no new cron.
