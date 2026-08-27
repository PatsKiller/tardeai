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

## 5. Operator canary (after merge + host INTERDICT cleanup)

1. Confirm effective env: `CIO_TELEGRAM_INTERDICT=0` on portfolio-server
2. Optional situation canary: `CIO_SITUATION_NOTIFY=1` for one S6 pass (policy master may stay false)
3. Confirm phone: concentration DIGEST/IMMEDIATE path; no flood of ~23 S3 READY pages
4. S3 Telegram only if a capital-plan row is `RE_ENTER` + `act_now`

## Tests

```bash
.venv/bin/python -m pytest \
  tests/test_cio_notification_signal.py \
  tests/test_cio_phase_a_s3_notify_gate.py \
  -q
```
