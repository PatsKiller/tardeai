# M5_OBSERVED adjudication — live ceiling 2026-09-09

**Adjudicated_at_utc:** 2026-09-09T04:02:00Z  
**CURRENT pin:** `340aaf831-main-exact-phase2-20260908-185931`  
**Verdict:** **NOT_OBSERVED** — remains `M5_CANDIDATE` / `AWAITING_OPERATOR`

## Evidence examined

| Source | Result |
|---|---|
| `evidence/20260909T034650Z/watchers/m5_log_*.json` | `hit_count=0` for `cadence_not_due` / pin / load-by-subject patterns |
| `/home/johnclaw/logs/persistent_wake.log` (watcher grep) | No quoteable days-earlier `cadence_not_due` on served pin in captured tails |
| Dry P1 hermetic | `P1_M5_HERMETIC_PASS` — does **not** grant OBSERVED |

## Required for OBSERVED (all must be in one artifact)

1. Disposition age ≥ days (days-earlier honor)
2. Served pin matches CURRENT
3. Unattended (not hand-run)

**Missing tonight:** (1) and quoteable log hits. Hermetic PASS alone is insufficient.

## Claim

`M5_OBSERVED` = **AWAITING_OPERATOR** (unchanged)
