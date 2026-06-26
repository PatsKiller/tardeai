# Options Module — Architecture & Operations

**Location:** Trading hub → **Options** tab (`/v3/trading?tab=Options`)  
**Status:** **Enterprise trade desk** — systematic proposals, enterprise risk gates, operator approval queue, position monitor, Hermes/TradeAI research bridge. Live execution is operator-approved (`options_pilot_arm` + desk queue + per-order 2FA).

**Latest commits:** `5645e068` (audit fixes + Hermes/TradeAI bridge), `4d7b9c38` (enterprise desk layer).

---

## Architecture

```
Cron (10m) ──► run_options_monitor.py
                    ├─► options_engine.generate_proposals()
                    │       ├─ portfolio sleeve (CC, protective puts)
                    │       ├─ conviction sleeve (CSP, long calls, spreads)
                    │       ├─ quality gates + per-strategy slots
                    │       └─ options_desk_enterprise (blackout, liquidity, vol, tiers)
                    ├─► options_engine.monitor_positions() + book greeks
                    └─► options_research_bridge.run() → Hermes + TradeAI runtime

Daily 16:20 ──► options_iv_snapshot.py ──► options_iv_history (52-week IV rank)

Operator ──► approval queue approve/reject ──► preflight ──► 2FA ──► Schwab submit
```

---

## Reuse Audit (what existed before)

| Asset | Path | Reused for |
|-------|------|------------|
| Schwab option chain (read) | `scripts/schwab_transport.py` → `get_option_chain()`, `normalize_option_chain()` | Live premium, IV, delta, OI |
| Covered-call scan (estimated) | `scripts/portfolio_options.py` → `scan_covered_calls()`, `_get_earnings_dates()` | BS fallback; **FMP earnings calendar** |
| Aegis CC scoring | `scripts/aegis_synthesis.py`, `GET /api/v2/aegis/covered-calls` | Catalyst / verdict context |
| Holdings | `data/portfolios/state/holdings.json` | CC eligibility (≥100 shares); protective puts (≥$15k MV) |
| Technical snapshot | `technical_snapshot.json` | RSI, SMA200, IV proxy, IV rank |
| Layer 4 inferences | `inference_results` via DB | High-conviction universe |
| Fused signals | `fused_signals` table | Primary conviction source (confidence, severity, direction) |
| Portfolio intent | `assets/portfolio_intent.yaml` | CC candidates, DTE/OTM/IV gates, **options_desk_settings** |
| UI cards | `OptionProposalCard`, `OptionReviewBar`, `GreeksOverview` | Proposal + position + ensemble review |
| Execution pilot | `options_pilot_arm`, `options_order_pilot`, `options_execution_policy` | Live Schwab submit path |

**Gaps filled:** unified `options_engine.py`, enterprise layer (`options_desk_enterprise.py`), balanced desk slots, Hermes/TradeAI bridge, approval queue, book greeks, vol analytics.

---

## Components

### Backend — `scripts/options_engine.py`

| Function | Purpose |
|----------|---------|
| `generate_proposals()` | Full desk pass: CC + protective puts + defined-risk + spreads |
| `monitor_positions()` | Open-leg lifecycle (hold/close/roll) + **book greeks** |
| `get_overview()` | Desk KPIs + enterprise risk summary |
| `build_options_desk_summary()` | Compact summary for TradeAI / Hermes |
| `enqueue_ensemble_for_proposals()` | Multi-LLM quality review (advisory) |

**Two sleeves:**

| Sleeve | Strategies | Routing |
|--------|-----------|---------|
| **Portfolio / income** | Covered calls, protective puts | Holdings-driven; CC from `covered_call_candidate` in intent YAML |
| **Conviction / defined-risk** | CSP, long calls, credit spreads | `fused_signals` + Layer 4; **CSP on non-owned names only** |

**Per-strategy desk slots** (prevents CC crowding):

| Strategy | Default cap | Env override |
|----------|-------------|--------------|
| Covered call | 5 | `OPTIONS_SLOT_COVERED_CALL` |
| Cash-secured put | 3 | `OPTIONS_SLOT_CSP` |
| Protective put | 2 | `OPTIONS_SLOT_PROTECTIVE_PUT` |
| Long call | 2 | `OPTIONS_SLOT_LONG_CALL` |
| Credit spread | 2 | `OPTIONS_SLOT_CREDIT_SPREAD` |

**Edge models:**

- **Credit** (`_edge_score`) — covered calls
- **Debit** (`_edge_score_debit`) — protective puts, long calls
- **Wheel** (`_edge_score_wheel`) — CSP, credit spreads (POP + annualized ROC)

**Quality gates (default):**

- Edge ≥ 62 (52 for income sleeve / conviction wheel plays)
- POP ≥ 52%
- IV rank ≥ 20 (12 for high-conviction names via `OPTIONS_CONVICTION_MIN_IV`)
- DTE 7–60

**Price resolution** for conviction symbols missing from `technical_snapshot.json`:
holdings → `trade_ai_scans` → `market_quote_provider.check_fresh_quote()`.

Caches:
- `data/portfolios/state/options_proposals.json` (10 min TTL; bypassed when `force=True`)
- `data/portfolios/state/options_monitor.json` (5 min TTL)
- `data/runtime/options_desk_latest.json` (TradeAI enrichment)
- `data/runtime/options_desk_enterprise.json` (risk + tier summary)

---

### Enterprise layer — `scripts/options_desk_enterprise.py`

Institutional controls applied after quality gates, before desk allocation.

| Control | Description |
|---------|-------------|
| **Earnings blackout** | FMP calendar; blocks short premium / directional entries through earnings window |
| **Liquidity gates** | Min OI, min volume, max bid-ask spread % |
| **Vol analytics** | Term structure + put/call skew from live Schwab chain (persisted to `options_chain_snapshots`) |
| **Book greeks** | Net Δ, Γ, Θ, ν aggregated across open legs |
| **Portfolio risk** | Concentration + net-delta exposure warnings |
| **Desk tiers** | A (edge ≥72), B (≥62), C (below B) |
| **Approval queue** | DB-backed operator review before live submit |

Config: `assets/portfolio_intent.yaml` → `options_desk_settings`, overridable via env (`OPTIONS_MIN_OI`, `OPTIONS_APPROVAL_REQUIRED`, etc.).

**Live eligibility:** proposals with enterprise blocks or BS-only estimates (when `require_chain_for_live: true`) are advisory-only until chain confirms and operator approves.

---

### Hermes + TradeAI bridge — `scripts/options_research_bridge.py`

After each monitor pass:
- Publishes `data/runtime/options_desk_latest.json`
- Stages `hermes_research_intelligence` rows (`research_type=options_desk`, 6h dedup per symbol)

Wired into:
- `run_options_monitor.py` (every cron pass)
- `hermes_coordinator.py` (each tick)
- `trade_ai_orchestrator.py` (step 10c — per-ticker `options_desk` context)
- `api_v2.py` `_compute_trade_ai()` (top-level + per-ticker block)
- `hermes_subject_enhance.py` (`options_proposal` gatherer for external LLM review)

```bash
.venv/bin/python scripts/options_research_bridge.py --apply
.venv/bin/python scripts/options_research_bridge.py --apply --symbol RTX --force
```

---

### API (`scripts/api_v2.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v2/options/proposals` | Filtered proposals (`symbol`, `strategy`, `min_pop`, `min_edge`, `force=1`) |
| `GET /api/v2/options/positions` | Open legs + monitoring + book greeks |
| `GET /api/v2/options/monitor` | Alias for positions |
| `GET /api/v2/options/overview` | Strategy summary + enterprise risk |
| `GET /api/v2/options/desk/risk` | Book greeks, concentration, live-eligible count |
| `GET /api/v2/options/desk/vol-analytics?symbol=RTX` | Term structure + skew |
| `GET /api/v2/options/approval-queue` | Pending/blocked desk items (`?status=pending`) |
| `POST /api/v2/options/approval-queue/resolve` | `{proposal_id, action: approve\|reject, note?}` |
| `GET /api/v2/options/execution/status` | Pilot arm + policy state |
| `POST /api/v2/options/preflight` | Build intent + 2FA (requires desk approval when enabled) |
| `POST /api/v2/options/confirm` | Confirm + Schwab submit |
| `POST /api/v2/options/ensemble/enqueue` | Batch LLM review |
| `GET /api/v2/schwab/option-chain` | Chain drill-down |

TradeAI: `GET /api/v2/trade-ai` includes `options_desk` block (top-level + per-ticker).

---

### Frontend — `apps/command-center-v3/src/pages/OptionsHub.tsx`

Tabs: **Proposals**, **Open Positions**, **Strategy Overview**

Components: `OptionProposalCard`, `OptionPositionCard`, `OptionChainPanel`, `OptionReviewBar` (ensemble), `GreeksOverview`, `OptionsPnLProfile`.

Wired into `TradingHub.tsx` as the **Options** tab.

---

### Monitor cadence — `scripts/run_options_monitor.py`

```bash
.venv/bin/python scripts/run_options_monitor.py
```

Cron (`crontab_backup.txt` + `linux_launchers/run_options_monitor.sh`):
- `35,45,55 9`, `*/10 10-15`, `5 16` weekdays → proposals + monitor + Hermes bridge (`force=True`)
- `20 16` weekdays → `options_iv_snapshot.py` (52-week IV rank history)

Each symbol gets a live `schwab_transport.get_option_chain()` per proposal (no shared chain cache).

---

## Proposal types

| Type | Source | Notes |
|------|--------|-------|
| **Covered call** | Holdings ≥100 shares | ~6% OTM, ~30 DTE; Aegis + intent overlay; Fidelity manual path |
| **Protective put** | Holdings ≥$15k MV | ~5% OTM long put; debit edge model |
| **Cash-secured put** | High-conviction, **not owned** | Wheel entry; ~8% OTM; conviction bias routing |
| **Long call** | Explicitly bullish + conf ≥60% | Defined risk; debit edge model |
| **Credit spread** | Bull put vertical | `NET_CREDIT` two-leg; wheel edge model |

**Conviction bias routing** (`_conviction_bias`): uses `direction`, `severity`, `inference_type` from fused signals — empty severity no longer defaults to bullish.

**Chain resolution:** Schwab live chain → Black-Scholes fallback (`_bs_option_premium`) when chain thin or after hours.

---

## Enterprise workflow (operator)

```
1. Desk scan generates proposals (cron, ~10m market hours)
2. Enterprise layer enriches: blackout, liquidity, vol, tier, live_eligible
3. Approval queue upserted (options_approval_queue table)
4. Operator reviews queue → approve or reject
5. Optional: ensemble LLM review (advisory, non-blocking)
6. Preflight checks: desk approval + enterprise blocks + policy + pilot arm
7. Per-order 2FA → Schwab submit
```

Reject or blocked proposals remain visible on the desk with `enterprise.blocks` — advisory review only.

---

## Monitoring logic

Positions sourced from Schwab `get_positions()` with OCC symbol parse.

Per position:
- Moneyness (ITM / ATM / OTM)
- POP OTM / ITM (Black-Scholes N(d2))
- Unrealized P/L vs mark
- Recommended action: Hold, Close for Profit, Roll, Close

Book-level (`monitor_positions` → `book_greeks`):
- Net delta (share-equivalent), gamma, theta/day, vega
- Per-underlying breakdown

---

## Safety & execution

**Advisory default.** Proposals include `execution_note` reflecting arm state.

**Enterprise gates (when `approval_required: true`):**
- Earnings blackout (FMP, configurable days)
- Liquidity: min OI 50, min vol 5, max spread 12%
- BS estimates blocked from live path when `require_chain_for_live: true`
- Desk approval required before preflight

**Live submit requires (all):**
1. Policy `ENABLED` (`options_execution_policy.py`)
2. DB `options_execution_enabled` (`options_pilot_arm.py --approve`)
3. Desk approval (`options_approval_queue.status = approved`)
4. `live_eligible = true` (no enterprise blocks)
5. Per-order 2FA (`preflight` → `confirm`)

| Component | Path |
|-----------|------|
| Policy | `scripts/brokers/options_execution_policy.py` |
| Operator arm | `scripts/options_pilot_arm.py --approve --confirm "APPROVE OPTIONS EXECUTION YYYY-MM-DD"` |
| Enterprise desk | `scripts/options_desk_enterprise.py` |
| Pilot | `scripts/brokers/options_order_pilot.py` |
| Guard | `execution_guard.py` → `OPTIONS_EXECUTION_MARKER` |
| API | `POST /api/v2/options/preflight` → 2FA → `POST /api/v2/options/confirm` |

CSP copy reminds operator to verify SSDI / income impact before entry.

---

## Database tables

| Table | Purpose |
|-------|---------|
| `options_iv_history` | Daily ATM IV snapshots for true 52-week IV rank |
| `options_approval_queue` | Desk operator approval queue (migration `2026_06_25_options_desk_enterprise.sql`) |
| `options_chain_snapshots` | Vol term structure + skew persistence |
| `hermes_research_intelligence` | `research_type=options_desk` rows from bridge |
| `inference_ensemble_jobs` | `target_type=options_proposal` ensemble review |

---

## Environment knobs

```
OPTIONS_SLOT_COVERED_CALL=5
OPTIONS_SLOT_CSP=3
OPTIONS_SLOT_PROTECTIVE_PUT=2
OPTIONS_SLOT_LONG_CALL=2
OPTIONS_SLOT_CREDIT_SPREAD=2
OPTIONS_CONVICTION_MIN_IV=12
OPTIONS_CONVICTION_MIN_EDGE=52
OPTIONS_EARNINGS_BLACKOUT_DAYS=14
OPTIONS_MIN_OI=50
OPTIONS_MIN_VOLUME=5
OPTIONS_MAX_SPREAD_PCT=12.0
OPTIONS_REQUIRE_CHAIN_LIVE=1
OPTIONS_APPROVAL_REQUIRED=1
OPTIONS_MAX_NET_DELTA_PCT=35.0
```

---

## CLI

```bash
# Proposals + monitor + overview
python scripts/options_engine.py --proposals
python scripts/options_engine.py --monitor
python scripts/options_engine.py --overview
python scripts/options_engine.py --force          # bypass 10m cache

# Full monitor pass (cron equivalent)
python scripts/run_options_monitor.py

# Hermes + TradeAI bridge
python scripts/options_research_bridge.py --apply --force

# IV history snapshot (daily)
python scripts/options_iv_snapshot.py

# Operator arm (live submit unlock)
python scripts/options_pilot_arm.py --approve --confirm "APPROVE OPTIONS EXECUTION $(date +%F)"
```

---

## Extending

1. **Approval queue UI tab** in OptionsHub (API ready; wire `GET /api/v2/options/approval-queue`)
2. **Vol surface UI** — `options_chain_snapshots` + Plotly term-structure chart
3. **Fidelity option legs** — extend `monitor_positions()` beyond Schwab-only
4. **Hard portfolio risk block** — promote `portfolio_risk_preflight` warnings to preflight rejects
5. **Roll automation** — wire monitor `roll` action to preflight with new expiration
6. **Edge calibration** — log closed proposal outcomes → edge model tuning

---

## Maturity comparison

| Capability | Retail advisory | Current (enterprise desk) | Prop-shop target |
|------------|----------------|---------------------------|------------------|
| Systematic screening | ✓ | ✓ | ✓ |
| Live chain pricing | partial | ✓ | ✓ |
| Earnings blackout | ✗ | ✓ (FMP) | ✓ |
| Liquidity gates | ✗ | ✓ | ✓ |
| Operator approval queue | ✗ | ✓ | ✓ |
| Book greeks | ✗ | ✓ (Δ, Θ, ν) | ✓ (streaming) |
| Vol surface | ✗ | term structure + skew | full 3D surface |
| Multi-broker book | ✗ | Schwab only | all brokers |
| Auto-execution | ✗ | gated (arm + queue + 2FA) | policy-driven |