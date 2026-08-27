# PHASE 13 CLOSEOUT — Controlled Production Canary + Rollback Proof

**UTC:** 2026-08-14  
**Branch:** `wt/cio-phase1-notify`  
**RC content / pin tip:** see `RELEASE_MANIFEST`  
**Authority:** `READ_ONLY_ADVISORY` unchanged  

## Goal

Deploy the CIO hardening RC to portfolio-server as a controlled canary, prove
rollback to the prior release, re-promote the canary, and leave Telegram
**interdicted** (no live send without operator env approval).

## Method

Worktree lacks `apps/command-center-v3/dist/` (gitignored). Canary therefore:

1. **Clone** live CURRENT release tree (runtime + frontend dist)
2. **Overlay** RC hardening files from the worktree
3. **Symlink** pipeline data dirs to canonical source (same rule as normal deploy)
4. **Stamp** `BUILD_SHA` = RC git HEAD
5. **Promote** → health + `/v3/cio`
6. **Rollback** to previous CURRENT → health
7. **Re-promote** canary → leave RC live

Tooling: `scripts/cio_phase13_canary_deploy.sh`  
Telegram: `scripts/cio_phase13_telegram_prepare_only.py` (package only)

## Executed canary (this host)

| Step | Result |
| --- | --- |
| PREV release | `/home/johnclaw/trade-ai-releases/portfolio-server/20260813-210818` (`8f11a642…`) |
| CANARY release | `…/41a6e40c-cio-rc-phase13-20260814-083220` |
| Promote health | **PASS** (`/api/v2/health` ok, `/v3/cio` 200) |
| Rollback health | **PASS** (restored PREV) |
| Re-promote health | **PASS** (RC left live) |
| Final CURRENT | canary release above |
| `CIO_TELEGRAM_INTERDICT` | **1** in systemd drop-in |
| Live Telegram sends | **0** |
| Broker / order / stop | **0** |

## Telegram prepare-only

```bash
python3 scripts/cio_phase13_telegram_prepare_only.py
```

| Check | Result |
| --- | --- |
| Package status | `AWAITING_EXPLICIT_OPERATOR_APPROVAL` |
| `execute_canary_send(force=…)` | `delivered=false`, reason env gate |
| `REAL_TELEGRAM_SENDS` | **0** |
| General bot used | **false** |

Live send still requires:

```bash
export AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
export CIO_TELEGRAM_CANARY_ENABLE=1
export CIO_TELEGRAM_CANARY_APPROVAL=I_APPROVE_CIO_CANARY_SEND
# and remove CIO_TELEGRAM_INTERDICT from drop-in / env
```

## Rollback

```bash
bash scripts/cio_phase13_canary_deploy.sh rollback
# or explicit:
bash scripts/cio_phase13_canary_deploy.sh rollback \
  /home/johnclaw/trade-ai-releases/portfolio-server/20260813-210818
```

State file: `~/.local/state/cio-phase13-canary/state.env`

## Exit gate

| Gate | Status |
| --- | --- |
| PHASE12_GO | **YES** |
| CANARY_PROMOTED | **PASS** |
| ROLLBACK_PROVEN | **PASS** |
| RE_PROMOTE_RC | **PASS** |
| HEALTH_OK | **PASS** |
| V3_CIO_200 | **PASS** |
| BUILD_SHA_MATCHES_RC | **PASS** |
| LIVE_TELEGRAM | **NOT SENT** (interdict) |
| MAIN_MERGED | **NO** — open PR under branch protection |
| FINANCIAL_AUTHORITY_CHANGED | **NO** |

## Residual (operator)

1. Open PR `wt/cio-phase1-notify` → `main` (branch protection requires PR path).
2. After CI green on main, optionally require `cio-hardening` status context.
3. Live Telegram canary only with explicit triple env approval + clear interdict.
4. Health agent still reports pre-existing stale `cio_decisions` (~166h) — not
   introduced by this RC; remediate via decision engine refresh separately.
5. Full main-line deploy via `deploy_portfolio_server.sh` after merge (canonical
   tree), which now stamps `BUILD_SHA` automatically.

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  
## ROLLBACK PROVEN: YES  

## Program status

Phases **0–13 complete** on this branch for CIO production hardening:

| Phase | Outcome |
| --- | --- |
| 0 | Forensic baseline |
| 1 | Notification containment |
| 2 | Cash / capital ledger |
| 3 | Decision semantics |
| 4 | Report architecture |
| 5 | Institutional visuals |
| 6 | Analytic completeness |
| 7 | Output pipeline |
| 8 | Office / report consistency |
| 9 | Alex Telegram product |
| 10 | Git / release / CI / Drive |
| 11 | Adversarial suite |
| 12 | Architecture review **GO** |
| 13 | Controlled canary + rollback **PASS** |
