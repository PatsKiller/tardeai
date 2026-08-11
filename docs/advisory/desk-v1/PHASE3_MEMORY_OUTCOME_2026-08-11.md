# Phase 3 Outcome — Memory (History, Feedback, Outcomes)

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Plan:** [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md)  
**Depends on:** Phase 0–2  
**Authority:** READ_ONLY_ADVISORY  

---

## Delivered

| Track | Work | Status |
|---|---|---|
| **3A** | Append-only `advisory_rows.jsonl` on every enrich | **DONE** |
| **3A** | Prior verdict / conviction / key_risk / flips_90d injection | **DONE** |
| **3A** | Thrash penalty on conviction (≥3 flips / 90d) | **DONE** |
| **3B** | Feedback with fixed reason codes | **DONE** |
| **3B** | CLI `/advisory rate|ack|snooze|history|calibration` | **DONE** |
| **3B** | `DISAGREE_THESIS` surfaces in next-run rationale + memory block | **DONE** |
| **3C** | Deterministic 30/60/90d outcome scorer | **DONE** |
| **3C** | Calibration table by verdict | **DONE** |
| **3C** | Daily systemd timer for scoring | **DONE** |

Memory is **evidence only** — prompt block states it must not override current evidence.

---

## Storage layout

| File | Role |
|---|---|
| `data/runtime/advisory_rows.jsonl` | Per-run per-row verdict history |
| `data/runtime/advisory_feedback.jsonl` | Operator useful/notuseful/ack/snooze |
| `data/runtime/advisory_outcomes.jsonl` | Scored horizons |
| `data/runtime/advisory_calibration.json` | Hit rates by verdict |

---

## Reason codes (notuseful)

`WRONG_FACT` · `STALE` · `MISSING_CONTEXT` · `TOO_SMALL` · `DISAGREE_THESIS` · `ALREADY_KNEW` · `WRONG_TIMING`

Routing intent (design):
- WRONG_FACT / STALE → data defect, not prompt tweak  
- MISSING_CONTEXT → evidence gap  
- TOO_SMALL → materiality floor  
- **DISAGREE_THESIS** → store stance; surface next run  
- ALREADY_KNEW → novelty / suppress  

---

## Thrash rule

| Flips in 90d | Penalty (conviction 0–100) |
|---|---|
| 0–2 | 0 |
| 3+ | 5 × (flips − 2), capped at 25 |

Applied after model (or dry-run) conviction; `conviction_pre_thrash` retained.

---

## Outcome scoring (no model)

| Verdict | “Correct” if return over horizon… |
|---|---|
| TRIM / EXIT | ≤ −1% (and not a large rally against) |
| ADD / RE_ENTER | ≥ +1% |
| HOLD | > −15% drawdown |
| AVOID / WAIT / INSUFFICIENT_DATA | unscored |

Prices from `price_ohlc_cache.json`. Missing series → skip (no invent).

---

## CLI

```bash
.venv/bin/python scripts/advisory_commands.py help
.venv/bin/python scripts/advisory_commands.py rate SCHD useful
.venv/bin/python scripts/advisory_commands.py rate SPCX:schwab_taxable notuseful DISAGREE_THESIS held through
.venv/bin/python scripts/advisory_commands.py history SPCX schwab_taxable
.venv/bin/python scripts/advisory_commands.py calibration
.venv/bin/python scripts/advisory_outcome_scorer.py --once
```

Timer: `tradeai-advisory-outcome-scorer.timer` @ 18:30 daily.

---

## Pass criteria

| # | Criterion | Status |
|---|---|---|
| 3.1 | Prior verdict on ≥90% of repeat rows | **PASS path** — after first enrich, second run hits priors; grows with daily use |
| 3.2 | Rationale references prior when changed | **PASS** — memory block + thrash/risk lines; DISAGREE appendix |
| 3.3 | Feedback round-trip with reason code | **PASS** (unit + CLI) |
| 3.4 | DISAGREE_THESIS surfaces next run | **PASS** (unit + live dry-run) |
| 3.5 | Thrash penalty reduces conviction | **PASS** (unit) |
| 3.6 | Outcome scoring ≥20 at horizon | **PARTIAL** — scorer live; needs aged history + OHLCV to accumulate 20 |

### Live dry-run (2026-08-11)

```
run1 history_rows_appended=15 memory_prior_hit_pct=100% actionable=5/5
run3 disagree_thesis_surfaced_n=1 (after DISAGREE_THESIS on SCHD)
advisory_rows.jsonl ≈ 65 lines after multi-run
outcomes written=0 (horizons not yet mature — expected day-0)
```

---

## Tests

```
tests/test_advisory_desk_phase3.py → 9 passed
(+ phase2 suite still green)
```

---

## Files

- `scripts/lib/advisory/advisory_memory.py`
- `scripts/advisory_commands.py`
- `scripts/advisory_outcome_scorer.py`
- `scripts/lib/data_broker/advisory_desk.py` (enrich wire)
- `scripts/lib/advisory/__init__.py`
- `config/systemd/user/tradeai-advisory-outcome-scorer.{service,timer}`
- `tests/test_advisory_desk_phase3.py`
- `docs/advisory/desk-v1/PHASE3_MEMORY_OUTCOME_2026-08-11.md`

---

## Next (Phase 4)

`/api/v3/advisory` + CC v3 page (memory column) · Telegram brief + `/advisory` bot wiring · alert regression proof.

---

*Advisory only. No broker credentials or order authority.*
