# Ops note: `momentum_scalp` bottleneck `proposals_expired_before_approval`

**Date:** 2026-07-27  
**Scope:** Diagnose + document only. **No** live broker writes. **No** `production_deployment_action`. **No** gate weakening (TTL / quote freshness / liquidity / window stay as configured).  
**Strategy:** `strategy_id = momentum_scalp`  
**Primary diagnostic:** `python3 scripts/diagnose_momentum_scalp_paper_path.py --days 30 --json`

---

## Executive summary

The paper-path diagnostic labels the first bottleneck **`proposals_expired_before_approval`** when proposals exist, **zero** reach `APPROVED_FOR_PAPER_TEST` / `BROKER_SUBMITTED`, and at least one ends **`EXPIRED`**.

For momentum_scalp this is a **timing + readiness** race:

| Clock | Value | Role |
|-------|-------|------|
| **Paper proposal TTL** | **30 minutes** | Authoritative; setup dies if not approved/expired in-window |
| **Legacy ATM auto-approver** | **every 15 min** (04–19 ET, market-day gate) | Often too coarse vs 30m TTL |
| **`momentum_scalp_fast_atm_runner`** | **Not on live crontab** | Built to close the timing gap; not scheduled |
| **Validation fast-path** | **every 2 min** (06–11 ET) | Preferred conversion path (sandbox), when eligible |
| **stale_proposal_sweeper** | **once morning + EOD report** | Cleanup / report — **not** a mid-session 30m approver |

**Do not “fix” this by lengthening TTL first.** Prefer shortening queue latency and ensuring the fast path runs while the quote and window are still valid.

---

## 1. Measured proposal TTL

### Config (source of truth)

| Field | Value | File |
|-------|-------|------|
| `intraday_execution.proposal_ttl_minutes` | **30** | `config/strategies/momentum_scalp.yaml` |
| `lifecycle.proposal_expiry_minutes` | **30** | same (`source_of_truth: intraday_execution.proposal_ttl_minutes`) |
| Trading window | **06:00–12:00 ET** | `intraday_execution.trading_window_et` |

Runtime resolve (this host, 2026-07-27):

```text
proposal_lifecycle._intraday_ttl_minutes("momentum_scalp") → 30
get_expiry_datetime("momentum_scalp", created) → created + 30 minutes
  (INTRADAY: no market-close extension to 16:00 ET)
```

Code path:

- `scripts/proposal_lifecycle.py` — `_intraday_ttl_minutes` / `get_expiry_datetime` for `INTRADAY_STRATEGIES`
- `scripts/atm_auto_approver.py` — `resolve_atm_expiry()` **before** approval; age ≥ TTL → `EXPIRED` / `EXPIRED_INTRADAY` (cannot approve after TTL)

### When expiry fires (three layers)

1. **ATM cycle (primary for PENDING during market hours)**  
   Each `atm_auto_approver` pass: if `now >= effective_expiry` → atomic `PENDING → EXPIRED`, reason `intraday_ttl_expired`.  
   Effective expiry = `created_at + 30m` (authoritative); a **stored** `expires_at` is used only if **earlier**.

2. **proposal_lifecycle job** (`*/30 9-16` ET)  
   Marks lifecycle `EXPIRED_INTRADAY` / max-window for rows past `expires_at`.

3. **stale_proposal_sweeper** (Phase 6E, paper-only)  
   - **08:15** ET dry-run, **08:25** ET apply (`sweep_stale_paper_proposals.py`)  
   - **16:10** ET report-only  
   Staleness **policy** threshold for `momentum_scalp` is **60 minutes** (`phase6_proposal_staleness_policy.STALE_THRESHOLDS`) — coarser than the 30m **approval** TTL. Sweeper is a **cleanup / hygiene** tool, not the primary 30m clock.

**Implication:** Mid-session, expiry is enforced mainly by **ATM’s 15-minute cadence** and the **30-minute TTL**, not by the morning sweeper. A scalp that sits PENDING through two missed ATM ticks is already near death.

---

## 2. Cadence map (live crontab, this host)

Measured from `crontab -l` (2026-07-27). Not a deploy action — inventory only.

| Job | Schedule (ET-ish cron) | Cadence vs 30m TTL |
|-----|------------------------|--------------------|
| `atm_auto_approver.py` | `*/15 4-19` Mon–Fri + market_day_gate | **≤ ~2 ticks** per proposal life if create lands poorly |
| `momentum_scalp_validation_fast_path.py --submit-sandbox` | `*/2 6-11` Mon–Fri | **Fits** 30m TTL (preferred conversion) |
| Finviz momentum_scalp scan + generate + validation | `*/5 6-11` (plus a lighter `*/15`) | Generation + path can stay inside window |
| `momentum_scalp_fast_atm_runner.py` | **Not scheduled** | Gap vs design docs (P0-7 runner exists, dry-run-first / paper-only) |
| `proposal_lifecycle.py` | `*/30 9-16` | Lifecycle maintenance, not primary approve |
| `stale_proposal_sweeper` | 08:15 dry / 08:25 apply / 16:10 report | **Outside** continuous 30m approval race |
| `cleanup_stale_proposals.py` | 10:00 and 15:00 | Broad stale reject (e.g. 24h PENDING) — **not** scalp-minute TTL |

### `momentum_scalp_fast_atm_runner` vs ATM window

- Runner purpose (code docstring): find **fresh**, **in-window**, paper-account momentum_scalp proposals and route them through the **existing** ATM path **before 30m TTL** — without weakening gates.
- Eligibility includes: age ≤ TTL, quote age ≤ 15m, lifecycle `ENTRY_ZONE_VALID`/`ACTIVE`, account in paper set (`tradeai_automated`), route not social/scout-only.
- **Not on crontab** → production still depends on **15m ATM** + **2m validation fast-path**, not the dedicated fast ATM runner.

### stale_proposal_sweeper vs ATM approval window

| | ATM approval window | Sweeper |
|--|---------------------|---------|
| Intent | Approve or expire **intraday scalps** while quote/window valid | Mark **stale** PENDING paper rows (policy thresholds) |
| momentum_scalp clock | **30m** TTL (config + resolve_atm_expiry) | **60m** “stale” age threshold (+ quote checks) |
| Schedule density | Every **15m** | **Once** morning apply + EOD report |
| Can approve? | Yes (subject to gates) | **No** (paper-only expire/classify; no approve/submit) |

Sweeper **does not** replace a tight ATM / fast-path cadence. If proposals expire before approval, morning sweep is usually **after the fact**.

---

## 3. Live diagnosis snapshot (read-only, 30d window)

Command: `diagnose_momentum_scalp_paper_path.py --days 30 --json` (2026-07-27T02:31Z):

| Stage | Value |
|-------|-------|
| strategy_signals | 52 |
| proposals_created | **1** |
| proposals_by_status | EXPIRED=1 |
| proposals_approved_for_paper | **0** |
| atm_decisions | deferred=**118** |
| atm_rejection_gates | `account_resolution_missing`=118 |
| confirmed_paper_trades (attribution) | 2 (all-time path; sample still << gate) |
| **first_bottleneck** | **`proposals_expired_before_approval`** |

### Sole 30d proposal sample (TBPH #889)

| Field | Measured |
|-------|----------|
| created_at | 2026-06-30 ~09:05 ET |
| status | EXPIRED |
| lifecycle_status | ENTRY_ZONE_VALID |
| stored `expires_at − created_at` | **480 minutes (8h)** — **legacy stamp** on the row, not the 30m config write |
| ATM decisions | 118× **deferred** (`account_resolution_missing` — no `target_account`) through ~11:50 ET same day |
| updated_at → EXPIRED | 2026-07-10 (sweeper/cleanup days later) |

**Interpretation:**

1. Config/runtime TTL is **30 minutes**; this historical row still carries an **8h stored expires_at** (old writer / pre-alignment). ATM **should** still enforce `created_at + 30m` via `resolve_atm_expiry` once that code is live — do not rely on stored 8h.
2. Dominant hard gate in this sample was **`account_resolution_missing`**, not quote staleness alone. **Cadence cannot convert** a proposal with no target account; fixing account resolution is prerequisite, not gate weakening.
3. Even with accounts fixed, **15m ATM vs 30m TTL** remains a structural thin margin; **2m validation fast-path** is the path that matches the TTL by design.

---

## 4. Recommended order of remedies

**Constraint:** No gate weakening. Prefer operational latency and correctness over “more minutes of dead scalp.”

### 1) Shorten queue latency (first)

- Ensure **account resolution** (`target_account` / paper account) is set at proposal create for momentum_scalp paper path — ATM cannot approve without it.
- Prefer **validation fast-path** (`momentum_scalp_validation_fast_path` / paper fast-path) **immediately** after create or `ENTRY_ZONE_VALID`, still sandbox-only, still full deterministic gates.
- Keep generation inside **06:00–12:00 ET** with fresh quotes (15m freshness already required).

### 2) Run fast ATM more often (second)

- Schedule or event-trigger **`momentum_scalp_fast_atm_runner`** (paper-only / dry-run-first as designed) at **1–2 minute** cadence during the window **or** on proposal-create hook — **without** bypassing ATM gates.
- Optionally tighten **generic ATM** from 15m → 5m **only for** momentum_scalp eligibility (if ever coded) — still no TTL extension.

### 3) Lengthen paper TTL (last resort only)

- Raising `proposal_ttl_minutes` above 30 fights the product rule (“scalp is minutes, not hours”) and re-opens the original 9h-TTL failure mode documented in strategy YAML.
- Consider only after (1) and (2) are proven and if data still show **true** age-out **with** account resolved, quote fresh, and fast-path running — and treat any increase as a **measured experiment** with a hard cap (e.g. still ≤ 45–60m), never multi-hour.

---

## 5. What not to do

- Do **not** weaken quote freshness, liquidity unknown fail-closed, or trading window to “get more approvals.”
- Do **not** treat `stale_proposal_sweeper` as the fix for mid-session expiry.
- Do **not** issue production deployment / live broker actions from this note.
- Do **not** conflate paper `PENDING` TTL with Path B broker-queue latency (different pipeline).

---

## 6. Re-measure commands (read-only)

```bash
# Bottleneck label + stage counts
.venv/bin/python scripts/diagnose_momentum_scalp_paper_path.py --days 30 --json

# Config TTL resolve
.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); \
  from proposal_lifecycle import _intraday_ttl_minutes; \
  print(_intraday_ttl_minutes('momentum_scalp'))"

# Optional: dry-run fast ATM eligibility (no broker write)
.venv/bin/python scripts/momentum_scalp_fast_atm_runner.py --dry-run
```

---

## 7. References

| Artifact | Path |
|----------|------|
| Strategy config | `config/strategies/momentum_scalp.yaml` |
| TTL + window lifecycle | `docs/diligence/current/MOMENTUM_SCALP_LIFECYCLE.md` |
| Diagnose script | `scripts/diagnose_momentum_scalp_paper_path.py` |
| ATM expiry | `scripts/atm_auto_approver.py` (`resolve_atm_expiry`) |
| Fast ATM runner | `scripts/momentum_scalp_fast_atm_runner.py` |
| Sweeper wrapper | `scripts/run_scheduled_stale_proposal_sweeper.sh` |
| Staleness thresholds | `scripts/phase6_proposal_staleness_policy.py` |
| Cron inventory | `docs/operations/SCHEDULED_JOBS_REFERENCE.md` |

---

_Generated from config, live crontab, diagnosis JSON, and read-only DB inspection on 2026-07-27. Diagnosis-only; no production_deployment_action._
