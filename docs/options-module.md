# Options Module — Architecture & Operations

**Location:** Trading hub → **Options** tab (`/v3/trading?tab=Options`)  
**Status:** Maturity Level 10 desk — proposals + monitor + health metrics. Execution path operator-approved (`options_pilot_arm`).

## Reuse Audit (what existed before)

| Asset | Path | Reused for |
|-------|------|------------|
| Schwab option chain (read) | `scripts/schwab_transport.py` → `get_option_chain()`, `normalize_option_chain()` | Live premium, IV, delta, OI |
| Covered-call scan (estimated) | `scripts/portfolio_options.py` → `scan_covered_calls()` | Fallback premium when chain unavailable |
| Aegis CC scoring | `scripts/aegis_synthesis.py`, `GET /api/v2/aegis/covered-calls` | Catalyst / verdict context |
| Holdings | `data/portfolios/state/holdings.json`, `GET /api/v2/portfolio/holdings` | Covered-call eligibility (≥100 shares) |
| Technical snapshot | `technical_snapshot.json` | RSI, SMA200, IV proxy, IV rank |
| Layer 4 inferences | `inference_results` via DB | High-conviction puts/calls |
| Fused signals | `fused_signals` table | Catalyst strength |
| Portfolio intent | `assets/portfolio_intent.yaml` | CC candidates, DTE/OTM/IV gates |
| UI cards | `SynthesizedReportCard`, `EnsembleValidationInline` | Proposal + position cards |
| Protective-stop pattern | `stop-management-architecture.md` | Future execution template (2FA + policy) |

**Gaps filled by this module:** unified `options_engine.py`, v3 UI, monitoring cadence, quality gates, OCC position parsing from Schwab.

## Components

### Backend — `scripts/options_engine.py`

- **`generate_proposals()`** — Covered calls on owned stock + defined-risk puts/calls on Layer-4 names
- **`monitor_positions()`** — ITM/OTM, POP, hold/close/roll recommendations
- **`get_overview()`** — Desk-level KPIs
- **Quality gates (default):** edge ≥62, POP ≥52%, IV rank ≥20 (stricter for non-intent symbols)

Caches:
- `data/portfolios/state/options_proposals.json` (10 min TTL)
- `data/portfolios/state/options_monitor.json` (5 min TTL)

### API (`scripts/api_v2.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/options/proposals` | Filtered proposals (`symbol`, `strategy`, `min_pop`, `min_edge`, `force=1`) |
| `GET /api/v2/options/positions` | Open legs + monitoring |
| `GET /api/v2/options/monitor` | Alias for positions |
| `GET /api/v2/options/overview` | Strategy summary |
| `GET /api/v2/schwab/option-chain` | Chain drill-down (existing) |

### Frontend — `apps/command-center-v3/src/pages/OptionsHub.tsx`

Tabs: **Proposals**, **Open Positions**, **Strategy Overview**

Wired into `TradingHub.tsx` as the **Options** tab.

### Monitor cadence — `scripts/run_options_monitor.py`

```bash
.venv/bin/python scripts/run_options_monitor.py
```

Installed cron (see `crontab_backup.txt` + `linux_launchers/run_options_monitor.sh`):
- `35,45,55 9`, `*/10 10-15`, `5 16` weekdays → `run_options_monitor.sh` (flock)
- `20 16` weekdays → `options_iv_snapshot.py` (52-week IV rank history)

## Proposal types

1. **Covered call** — Holdings ≥100 shares, Schwab chain strike selection, Aegis + intent overlay
2. **Cash-secured put** — High-conviction names (Layer 4 / fused), defined max loss
3. **Long call** — Bullish conviction plays (smaller set, higher edge bar)
4. **Credit spread** — Bull put vertical (`NET_CREDIT` two-leg intent)

## Monitoring logic

Positions sourced from Schwab `get_positions()` with OCC symbol parse.

Per position:
- Moneyness (ITM / ATM / OTM)
- POP OTM / ITM (Black-Scholes N(d2) approximation)
- Unrealized P/L vs mark
- Recommended action: Hold, Close for Profit, Roll, Close

## Safety

- Proposals include `execution_note` reflecting arm state (advisory vs live path)
- Respects `portfolio_intent.yaml` earnings blackout (via Aegis / FMP in CC path)
- SSDI/retirement context: CSP copy reminds operator to verify income impact
- Live submit requires: policy `ENABLED` commit + DB `options_execution_enabled` + Schwab standing unlock + per-order 2FA

## Execution (Schwab live)

| Component | Path |
|-----------|------|
| Policy | `scripts/brokers/options_execution_policy.py` (ENABLED commit + envelope) |
| Operator arm | `scripts/options_pilot_arm.py --approve --confirm "APPROVE OPTIONS EXECUTION YYYY-MM-DD"` |
| Pilot | `scripts/brokers/options_order_pilot.py` |
| Guard | `execution_guard.py` → `OPTIONS_EXECUTION_MARKER` |
| API | `POST /api/v2/options/preflight` → 2FA → `POST /api/v2/options/confirm` |
| Status | `GET /api/v2/options/execution/status` |

Requires: Schwab pilot standing unlock + `options_execution_enabled` DB flag + per-order 2FA.

## Credit spreads

`strategy: credit_spread` — bull put vertical via `NET_CREDIT` two-leg intent (`OptionLeg` + `SpreadType.CREDIT_SPREAD` in `order_intent.py`).

## Extending

1. **Inference types:** add `covered_call` / `assignment_risk` to Layer 4 `ACTION_FOR`
2. **Journal feedback:** log closed proposal outcomes → edge calibration
3. **Roll automation:** wire monitor `roll` action to preflight with new expiration

## CLI

```bash
python scripts/options_engine.py              # proposals
python scripts/options_engine.py --monitor    # positions
python scripts/options_engine.py --overview   # summary
python scripts/options_engine.py --force      # bypass cache
```