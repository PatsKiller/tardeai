# Post-Sale Redeploy Sync — 2026-07-14

## Scope

Advisory-only pipeline that detects broker sells, scores redeploy targets, and surfaces plans in Portfolio → **Redeploy** (UI live). No broker execution path.

**v2 design (institutional workbench):** `docs/design/REDEPLOY_DESK_INSTITUTIONAL_DESIGN.md` — Phases **A–E implemented** on `main` (plans A–G, entry export, UI v2, monitoring, PR-4 lock/oversight, PR-5 cron installer).

**Branch:** `main`  
**Migration:** `migrations/2026_07_14_deploy_redeploy_events.sql`

## Guardrails

- Advisory only — operator confirms sizing and placement.
- No autonomous broker writes from redeploy plans.
- AI narrative: deterministic scoring + optional OAuth oversight (`POST /api/v2/deploy/oversight`, PR-4 pending).
- Backfill sells older than 90 days → `status=dismissed` (`historical_backfill_over_90d`).
- Home banner: open events **<14 days** only (PR-3).
- Sold-fund proxy penalty: e.g. FCNTX sale → do not recommend more SCHG.

## Data Model

| Table | Purpose |
|-------|---------|
| `deploy_events` | One row per detected sell (`event_key` idempotent on `trade_transactions` dedupe) |
| `deploy_plans` | Versioned plan snapshots + OAuth oversight (PR-4) |
| `deploy_oversight_runs` | Grok / ChatGPT oversight lane runs (PR-4) |

Key columns on `deploy_events`: `symbol`, `account`, `sold_at`, `proceeds_usd`, `proxy_symbol`, `proxy_sleeve`, `lookthrough_delta`, `redeploy_plan`, `status` (`open` \| `settled` \| `dismissed` \| `approved`).

## Sync Pipeline

```
trade_transactions (SELL rows)
        ↓
sale_event_detector.py  →  deploy_events (upsert by event_key)
        ↓
deploy_intelligence_engine.py  →  redeploy_plan + metadata.market_context
```

### 1. Live detect (cron after Schwab / SnapTrade sync)

```bash
python3 scripts/deploy_detect.py              # dry-run, last 14 days
python3 scripts/deploy_detect.py --apply      # persist + enrich plans
python3 scripts/deploy_detect.py --apply --days 30
python3 scripts/deploy_detect.py --apply --trading-days-only   # skip weekends/holidays
```

**Source:** `scripts/lib/sale_event_detector.py`  
**Accounts:** `schwab_rollover_ira`, `schwab_taxable`, `schwab_roth`, `fidelity_rollover_ira`  
**Min proceeds:** $500  
**Proxy mapping:** `holding_proxies.HOLDING_PROXY_MAP` + mutual-fund fallback → SCHG

### 2. Historical backfill (one-time / refresh)

```bash
python3 scripts/deploy_backfill.py                    # dry-run, 24 months
python3 scripts/deploy_backfill.py --apply            # persist
python3 scripts/deploy_backfill.py --apply --months 24 --dismiss-after-days 90
```

**Jul 2026 backfill result:** 144 events — 113 dismissed (>90d), 31 open.

### 3. Recompute plans (after Hermes / think-tank / look-through refresh)

```bash
python3 scripts/deploy_recompute.py --apply              # all open events
python3 scripts/deploy_recompute.py --apply --symbol FCNTX
python3 scripts/deploy_recompute.py --apply --id 144
```

Dry-run (no DB write):

```bash
python3 scripts/deploy_recompute.py --symbol FCNTX
```

### 4. Monitoring re-eval (Phase E)

```bash
python3 scripts/deploy_monitor.py --apply
python3 scripts/deploy_monitor.py --apply --id 144
```

### 5. Cron install (PR-5)

```bash
bash scripts/install_deploy_redeploy_cron.sh
```

Runs **10:10** detect → **10:15** recompute → **10:20** monitor (Mon–Fri).

### API (v2 institutional)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v2/deploy/events` | Queue + institutional summary |
| GET | `/api/v2/deploy/plans?event_id=` | Plans A–G |
| GET | `/api/v2/deploy/plan?plan_id=` | Full plan |
| GET | `/api/v2/deploy/analysis?event_id=` | Before/after |
| GET | `/api/v2/deploy/export?event_id=&archetype=` | Trade plan JSON/CSV |
| GET | `/api/v2/deploy/monitoring?event_id=` | Fills + restoration |
| POST | `/api/v2/deploy/lock` | Lock plan version |
| POST | `/api/v2/deploy/oversight` | Grok/ChatGPT review (PR-4) |
| POST | `/api/v2/deploy/record-fill` | Manual stage fill |

## Intelligence Engine

**File:** `scripts/lib/deploy_intelligence_engine.py`

Deterministic score (advisory). Factors:

| Factor | Source |
|--------|--------|
| Sleeve gap | `lookthrough_themes.json` + `config/rotation_sector_targets.json` floors |
| Hermes composite / rank / research / external lanes | `hermes_data_access.py` |
| CIO view | `watchlist_final_synthesis` — AVOID blocks unless sleeve-gap ETF override |
| News sentiment | `symbol_cards_latest.json` |
| Analyst upside | symbol cards + yahoo analyst targets |
| Market regime | `market_regime_snapshots` |
| **Geopolitical posture** | `think_tank_latest.json` — catalyst count, defense research, news themes |
| Concentration | direct holding weight vs portfolio total |
| Duplicate-proxy penalty | sold fund proxy (e.g. FCNTX→SCHG) |

### Geopolitical posture (2026-07-14)

Parsed from think-tank signals:

- **Catalyst API** — `geopolitical` theme count + share of top catalyst
- **Hermes research** — `Defense spending` theme + symbol list (e.g. ITA)
- **News RSS** — `Geopolitical trade policy`, `Defense spending`
- **Contract wins** — defense-adjacent catalyst volume

Postures: `neutral` → `moderate` → `elevated`

Sleeve tilts when elevated:

| Sleeve | Bonus |
|--------|-------|
| Defense / Aerospace | +14 |
| Energy | +10 |
| Fixed Income | +8 |
| Cybersecurity | +8 |

Symbols flagged in defense/geopolitical Hermes research: +10.

## FCNTX Example (Jul 14, 2026)

| Field | Value |
|-------|-------|
| Event id | 144 |
| Proceeds | $107,023 |
| Account | `schwab_rollover_ira` |
| Proxy | SCHG (US large-cap growth) |
| Geopolitical | elevated (124 catalysts, Defense spending + trade-policy news) |

Top targets after recompute:

| Symbol | Score | Notes |
|--------|-------|-------|
| ITA | 134 | Defense sleeve gap + geopolitical elevated + research symbol |
| XAR | 123 | Defense sleeve gap + geopolitical elevated |
| JEPQ | 60 | Hermes rank, CIO ADD |
| BND | 59 | Fixed income + geopolitical safe-haven tilt |
| OSS | 52 | — |
| LHX | 46 | — |

SCHG excluded (duplicate-proxy penalty).

## Fidelity Stop Sync (related)

Rollover IRA GTC stops config: `config/fidelity_rollover_stops.json`

```bash
python3 scripts/fidelity_stop_sync.py --apply
```

**Jul 13, 2026 active stops:** QCOM 4%/$176.62, ANET 5%/$172.09, DIVI $42, CSCO $115, SCHG 6%/$32.60, DXCM 6%/$71.83, ARKX $31.06. XAR removed.

Retire logic: omission from config = canceled at Fidelity even if shares still held; clears `stop_confirmations`.

## Tests

```bash
python3 tests/test_sale_event_detector.py
python3 tests/test_deploy_intelligence.py
python3 tests/test_fidelity_stop_sync.py
```

## Cron Hooks (PR-5 — pending)

Run after broker sync completes (~10:10 ET trading days):

1. `deploy_detect.py --apply --trading-days-only`
2. Optional: `deploy_recompute.py --apply` if think-tank / Hermes refreshed same cycle

## UI / API

| PR | Deliverable | Status |
|----|-------------|--------|
| PR-3 | Portfolio → **Redeploy** tab (`/v3/portfolio?tab=Redeploy`) + Home banner (<14d events) | **Live** (2026-07-14) |
| PR-4 | OAuth oversight (`POST /api/v2/deploy/oversight`) | Pending |
| PR-5 | Cron hooks after Schwab/SnapTrade sync | Pending |

**API (live):** `GET /api/v2/deploy/events`, `POST /api/v2/deploy/detect`, `POST /api/v2/deploy/recompute`, `POST /api/v2/deploy/dismiss`

After deploy: `npm run build` in `apps/command-center-v3` — hard-refresh `/v3/portfolio` to pick up the new bundle.

## Approved Product Decisions (v1)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Tab name | Redeploy |
| 2 | Backfill >90d | Auto-dismiss |
| 3 | Home banner | Events <14 days only |
| 4 | AI narrative | Deterministic + OAuth oversight only |
| 5 | Nav item | Defer — Portfolio tab only |