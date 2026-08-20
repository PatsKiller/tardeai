# CIO Phase A — INTERDICT truth + ACT_NOW notify — 2026-08-20

Authority: **READ_ONLY_ADVISORY**. No broker / order / stop / 2FA.

## Context

PRs **#414** (reentry → S3 wire) and **#415** (watch intelligence → S7 wire)
already closed the detector evidence plumbing. This receipt closes the remaining
Phase A ops/policy gaps from the autonomous CIO gap diligence plan.

## 1. INTERDICT split-brain (fixed)

**Problem:** Every `cio_phase2_exact_main_deploy.sh promote` rewrote
`20-exact-sha-release.conf` with `CIO_TELEGRAM_INTERDICT=1`, while
`25-cio-only-live.conf` set `=0` (+ AUTHORIZE + ENABLE). Lexicographic merge
made **25 win** (effective live), but ops looked INTERDICTED and the next
promote would re-arm the conflict.

**Fix:** `write_systemd` in [`scripts/cio_phase2_exact_main_deploy.sh`](../../scripts/cio_phase2_exact_main_deploy.sh)
no longer stamps `CIO_TELEGRAM_INTERDICT`. Live/interdict mode is owned solely by:

```
~/.config/systemd/user/portfolio-server.service.d/25-cio-only-live.conf
```

(or `scripts/cio_telegram_mode.sh {live|interdict}`).

**Host follow-up (one-shot):** remove the stale `CIO_TELEGRAM_INTERDICT=1` line
from the current `20-exact-sha-release.conf`, then `daemon-reload` (no restart
required if 25 already sets `=0`).

## 2. S3 notify — ACT_NOW only (fixed)

Bare READY/NEAR (~23 S3 candidates) must stay quiet.

- `s3_capital_act_now(plan)` in [`scripts/lib/cio_plan_enrichment.py`](../../scripts/lib/cio_plan_enrichment.py)
- `maybe_notify_plan` allows `S3_REENTRY_CANDIDATE` only when that helper is true
  (or `force=True`)
- `is_material_plan` treats S3 as material only under the same gate
- Static `notify_situation_types` still omits S3 (fail-closed if helper regresses)

## 3. S6 concentration sticky ACT_NOW (fixed)

Material-scan signal gate: when `material_generation_id` is unchanged but the
lineage is `position:*:CONCENTRATION` and `act_now` and not blocked/REJECT,
delivery class is **DIGEST** instead of silent **SUPPRESSED**.

- First ACT_NOW flip → still **IMMEDIATE** (generation change)
- Sticky over-fire → DIGEST (operator-aware, not spam-IMMEDIATE every scan)
- Non-ACT_NOW unchanged replay → still SUPPRESSED

## 4. Already live (not this PR)

| Item | Status |
|------|--------|
| Reentry in CIO snapshot `_COLLECTORS` | #414 |
| Watch `primary_state` → S7 READY/GO/NEAR | #415 |
| Material situation notify canary doc | `CIO_MATERIAL_NOTIFY_CANARY_2026-08-20.md` |

## 5. Operator canary (closed 2026-08-20 ~16:40 ET)

- Host INTERDICT effective `=0` after drop-in `20` cleanup + `daemon-reload`.
- SCHD concentration canary delivered: `dec_phase_a_schd_concentration_canary`,
  message id **202**, CIO-only, `REAL_TELEGRAM_SENDS: 1`.
- Signal gate proved in-process: first ACT_NOW → **IMMEDIATE**; sticky → **DIGEST**.
- Script: `scripts/cio_phase_a_schd_concentration_canary.py` (merged via #416).

## 6. Why Telegram looks “SCHD-only” (operator FAQ)

You are **not** missing a broken feed for former holdings / watch names. Those
paths are live for **detection** and intentionally quiet for **notify**.

Live check 2026-08-20 (~16:45 ET), reentry desk + S3/S7:

| Symbol | Desk / path | Detector | Why no Telegram |
|--------|-------------|----------|-----------------|
| **SCHD** | Held, weight over fire | S6 concentration | Notify path allowed; canary + sticky DIGEST policy |
| **AXTI** | reentry **NEAR** | S3 fires | Bare NEAR ≠ capital `RE_ENTER`+`ACT_NOW` → `s3_capital_act_now=false` |
| **FATN** (not FTAN) | reentry **NEAR** | S3 fires | Same — surface only, no page |
| **ANET** | reentry **NEAR** | S3 fires | Same |
| **SCHG** | reentry **BLOCK** | No S3 | Desk blocked — not a candidate |
| **CSCO** | reentry **BLOCK** | No S3 | Desk blocked |
| Watch desk (~80) | `promotion_grade=0` | **0 S7** | No READY/GO/NEAR promotion status projected |

Also:
- ~23 S3 READY/NEAR names fire plans; **none** page unless capital-plan says
  governed **RE_ENTER** + **ACT_NOW** (Phase A gate — avoids 23-name spam).
- Living theses for SCHG/CSCO/ANET etc. are still mostly
  `BLOCKED_PENDING_ACQUISITION_AND_CURATION` / missing pin — research exists as
  debt queue, not as Telegram advisories.
- Watchlist fall-on/off does not yet auto-create/retire theses or promote S7
  (Phase C in the gap diligence plan).

**What would make those names advise on Telegram:**
1. Reentry desk → capital **RE_ENTER** with freshness **ACT_NOW** (S3 notify gate), or
2. Watch desk marks `proposal_allowed` / near-trigger so S7 lights (then decide
   whether S7 joins notify allowlist — currently forward-loop / not paged), or
3. Explicit operator `/cio` converse on the symbol (interactive path already live).

## Tests

```bash
.venv/bin/python -m pytest \
  tests/test_cio_notification_signal.py \
  tests/test_cio_phase_a_s3_notify_gate.py \
  -q
```
