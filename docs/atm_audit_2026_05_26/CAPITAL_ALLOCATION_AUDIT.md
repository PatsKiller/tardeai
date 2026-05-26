# Capital Allocation Audit
**Date:** 2026-05-26
**Auditor:** Automated code + DB analysis

---

## 1. Current State

### ATM State
- **Mode:** `active`
- **Last evaluated:** 2026-05-26 11:15 ET
- **Config hash:** `ab8369972241`
- **Pause reason:** None

### Open Positions
4 positions open, all on `ALPACA_PAPER` / target_account `alpaca_paper`:

| Symbol | Strategy | Dollar Size | Stop | Risk/share |
|--------|----------|-------------|------|------------|
| AGNC | reit_income | ~$10.22 * shares | $9.71 | $0.51 |
| CMCSA | dividend_growth_compounder | ~$24.97 * shares | $23.61 | $1.36 |
| NVDA | dividend_growth_compounder | ~$218.00 * shares | $210.58 | $7.42 |
| NWG | dividend_growth_compounder | ~$15.84 * shares | $15.05 | $0.79 |

### Registered Accounts (DB: `accounts` table)

| Account Label | Broker | Mode | Enabled |
|---------------|--------|------|---------|
| alpaca_paper | alpaca | paper | **true** |
| fidelity_401k | fidelity | live | **false** |
| schwab_rollover_ira | schwab | live | **false** |
| schwab_roth_ira | schwab | live | **false** |
| schwab_taxable | schwab | live | **false** |

**Only `alpaca_paper` is enabled.** All live brokerage accounts (Schwab, Fidelity) are disabled at the DB level.

---

## 2. Capital Allocation Chain: Signal to Execution

### Layer 1: Auto Proposal Generator
**File:** `scripts/auto_proposal_generator.py`

| Control | Value | Source |
|---------|-------|--------|
| DEFAULT_MAX_DOLLAR_SIZE | $2,000 | L31 hard-coded |
| DEFAULT_MAX_DOLLAR_RISK | $150 | L32 hard-coded |
| DEFAULT_RISK_PER_TRADE | $150 | L33 hard-coded |
| Strategy config max_position_size | Per-strategy YAML `live_trade_rules.max_position_size` | L458 |
| Strategy config max_dollar_risk | Per-strategy YAML `live_trade_rules.max_dollar_risk` | L459 |
| Shared rules default_risk_per_trade | $150 | `shared_risk_rules.yaml` L40 |

**Sizing normalization** (`normalize_size()`, L443-509):
1. Reads strategy YAML `live_trade_rules.max_position_size` (default: $2,000)
2. Reads strategy YAML `live_trade_rules.max_dollar_risk` (default: $150)
3. Reads shared rules `risk_limits.default_risk_per_trade` ($150)
4. Uses the MORE CONSERVATIVE of all risk caps
5. Calculates `max_shares_by_size = max_dollar_size / entry_price`
6. Calculates `max_shares_by_risk = max_dollar_risk / risk_per_share`
7. Takes `min(original_shares, max_shares_by_size, max_shares_by_risk)`

### Layer 2: Alpaca Paper Adapter
**File:** `scripts/alpaca_paper_adapter.py`

| Control | Value | Source |
|---------|-------|--------|
| MAX_POSITIONS | 3 | L23 hard-coded constant |
| MAX_POSITION_SIZE | $2,000 | L24 hard-coded constant |
| MIN_SCORE_ALPACA | 45 | L25 hard-coded constant |
| Max positions check | `SELECT COUNT(*) FROM paper_trades WHERE account='ALPACA_PAPER' AND status='open'` | L274-278 |
| Duplicate symbol block | Checks both DB and Alpaca for existing position in same symbol | L281-294 |
| Stop breached gate | Block if current price <= stop price | L357-359 |
| Excessive drift gate | Block if price drifted > 5% from proposed entry | L362-366 |
| Market hours gate | Blocks outside 4:00-20:00 ET weekdays | L387-398 |
| Live endpoint hard block | `RuntimeError` if non-paper URL detected | L36-37 |

**Note:** The adapter only connects to `https://paper-api.alpaca.markets` (L57). The live URL is explicitly rejected.

### Layer 3: Risk Gate
**File:** `scripts/risk_gate.py` (class `RiskGate`)

20 checks in sequence:

| # | Gate | Threshold | Source |
|---|------|-----------|--------|
| 1 | Global halt | `halt_all_trading` system_control | L125 |
| 2 | Live halt | `halt_live_only` system_control | L129 |
| 3 | Strategy halt | `halt_{strategy_id}_strategy` system_control | L133 |
| 4 | Strategy lifecycle | `strategy_registry.active = false` -> KILLED | L137-147 |
| 5 | Account eligibility | Checks `forbidden_accounts` in strategy YAML | L150-155 |
| 6 | Daily loss limit | `risk_per_trade * 4` (paper) or `* 3` (live) = $600 paper / $450 live | L158-172 |
| 7 | Weekly loss limit | `risk_per_trade * 8` (paper) or `* 6` (live) = $1,200 paper / $900 live | L175-190 |
| 8 | Max positions (taxable) | 3 (from `shared_risk_rules.yaml` L38) | L193-202 |
| 9 | Max total positions | 8 (from `shared_risk_rules.yaml` L39) | L205-214 |
| 10 | Same sector exposure | Max 1 per sector (from `shared_risk_rules.yaml` L40) | L217-233 |
| 11 | Stop defined | Required for fail-closed contexts | L236-239 |
| 12 | Stop width | Max 15% | L242-252 |
| 13 | Dollar size | Paper: $15K (env), Live: from strategy YAML | L254-261 |
| H1 | Portfolio heat | 6% of $100K = $6,000 total risk | L268-279 |
| H2 | Single position concentration | 8% of $100K = $8,000 per position | L282-288 |
| H3 | Sector concentration | 25% of $100K = $25,000 per sector | L291-306 |
| 14 | Data quality | intel_readiness < 20 -> block | L314-318 |
| 15 | Data freshness | > 60 min stale -> block | L321-323 |
| 16 | VIX regime | VIX >= 35 pauses momentum/gap/swing/earnings | L326-338 |
| 17 | Social-only catalyst | Block unverified social-only sources | L340-348 |

**Fail-closed behavior:** Risk gate errors block execution for paper/live trades (`FAIL_CLOSED_CONTEXTS`). Only discovery/dashboard contexts are fail-open (L52-53).

### Layer 4: ATM Auto Approver
**File:** `scripts/atm_auto_approver.py`

| Control | Value | Source |
|---------|-------|--------|
| Operating hours | 09:35 - 15:30 ET | `atm_config.yaml` L21-22 |
| Max concurrent (default) | 6 | `atm_config.yaml` L12 |
| Max new per day (default) | 3 | `atm_config.yaml` L13 |
| Max % per trade | 10% | `atm_config.yaml` L14 |
| Max % per strategy | 25% | `atm_config.yaml` L15 |
| Max % per sector | 35% | `atm_config.yaml` L16 |
| Kill switch per-account | 0.25% daily loss | `atm_config.yaml` L24 |
| Kill switch aggregate | 10% daily loss | `atm_config.yaml` L45 |
| Classifier health min | 0.0 (temporarily lowered from 0.5 for cold-start) | `atm_config.yaml` L19 |
| Same-day skip strategies | momentum_scalp, gap_and_go (ATM cron too slow) | `atm_config.yaml` L31-33 |
| B-1 bucket2 excluded | swing_breakout, swing_trade, earnings_post_momentum, recovery_watch, fib_retracement_bounce | `atm_config.yaml` L54-59 |
| B-1 observation end | 2026-05-25 (EXPIRED) | `atm_config.yaml` L52 |
| Proposal expiry | 4 hours age, or 5+ consecutive failures, or 3x enrichment failures | `atm_auto_approver.py` L287-296 |

**ATM account resolution:** `_resolve_proposal_account()` in `auto_proposal_generator.py` L135-144 calls `atm_config_manager.get_enabled_accounts()` which intersects config `accounts.*.enabled=true` with DB `accounts.enabled=true`. Currently only `alpaca_paper` qualifies.

**Enrichment gate:** Proposals must have `enrichment_status = 'COMPLETE'` before ATM will approve them (L332-339). Not-yet-enriched proposals are deferred, not rejected.

---

## 3. Per-Strategy Capital Allocation Matrix

| Strategy | Account | Sizing Method | Dollar Cap | Risk Cap | Cash Basis | Config Source | Guardrails | Risks |
|----------|---------|---------------|------------|----------|------------|---------------|------------|-------|
| momentum_scalp | taxable only (IRA forbidden) | min(signal_shares, $2K/entry, $150-200/risk) | $2,000 | $200 | risk_per_share = entry - stop | `config/strategies/momentum_scalp.yaml` L99, shared_risk_rules L40 | Same-day skip in ATM, VIX pause >35, intraday exit required | ATM cron at 15min may miss fast-moving setups |
| gap_and_go | taxable only | Same sizing logic | $2,000 | $150 (default) | risk_per_share | `config/strategies/gap_and_go.yaml` | Same-day skip in ATM | Same timing concern |
| dividend_growth_compounder | taxable, rollover_ira, roth_ira | Same sizing logic | $2,000 (live_trade_rules default) | $150 | risk_per_share | `config/strategies/dividend_growth_compounder.yaml` | None strategy-specific | IRMAA/SSDI checks only for income_add, not dividend strategies |
| reit_income | taxable, rollover_ira, roth_ira | Same sizing logic | $2,000 (live_trade_rules default) | $150 | risk_per_share | `config/strategies/reit_income.yaml` | Auto-DQ: REIT in taxable unapproved | Non-qualified REIT dividends in taxable could be tax-inefficient |
| swing_breakout | (general) | Same sizing logic | $2,000 | $150 | risk_per_share | `config/strategies/swing_breakout.yaml` | B-1 excluded (observation expired 05-25) | B-1 observation end date passed -- may now auto-approve |
| income_add | (general) | Same sizing logic | $2,000 | $150 | risk_per_share | `config/strategies/income_add.yaml` | SSDI + IRMAA checks required | Requires extra evidence fields |

---

## 4. Live Account Protection Verification

### Question: Are Schwab/Fidelity/Vanguard protected from automated trading?

**YES -- protected at 5 independent layers:**

| Layer | Protection | Evidence |
|-------|-----------|----------|
| **1. .env** | `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true` | `.env` lines 103, 107 |
| **2. Adapter hard block** | `alpaca_paper_adapter.py` L36-37: `RuntimeError` if live Alpaca URL detected | Only connects to `paper-api.alpaca.markets` |
| **3. DB accounts table** | All live accounts (schwab_*, fidelity_*) have `enabled=false` | DB query confirmed |
| **4. ATM config** | Only `alpaca_paper` has `enabled: true` in `atm_config.yaml` L37-40 | Config file confirmed |
| **5. ATM enabled account intersection** | `get_enabled_accounts()` intersects config AND DB enabled flags | `atm_config_manager.py` L110-123 |
| **6. Supervisor safety assertions** | `unified_stop_supervisor.py` L33-34: asserts `ALPACA_MODE=paper` and `LLM_DISABLE_LIVE_EXECUTION=true` at every run | Both assertions present |
| **7. Reconciliation safety** | `reconcile_stop_v21_broker_stops.py` L33-40: same assertions | Both assertions present |
| **8. Risk gate IRA block** | `risk_gate.py` L154-155: momentum_scalp/gap_and_go blocked in IRA accounts | Hard-coded check |

### Question: Is live trading blocked?

**YES.** No code path exists to submit orders to live brokers:
- There is no live Alpaca adapter (only `AlpacaPaperAdapter`)
- There is no Schwab/Fidelity order submission code
- The `ALPACA_MODE=paper` env var is asserted by supervisor and reconciliation
- The `LLM_DISABLE_LIVE_EXECUTION=true` env var provides a second safety lock

### Question: What are per-day/per-account caps?

| Cap | Value | Enforced By |
|-----|-------|-------------|
| Max new trades per day per account | 3 | ATM config + `_count_new_today()` in `atm_auto_approver.py` L107-112 |
| Max concurrent per account | 6 | ATM config + `_count_positions()` in `atm_auto_approver.py` L100-104 |
| Max concurrent (adapter level) | 3 | `alpaca_paper_adapter.py` L23 (MAX_POSITIONS) |
| Max position size | $2,000 | `alpaca_paper_adapter.py` L24, strategy YAMLs |
| Max total open positions | 8 | `shared_risk_rules.yaml` L39, `risk_gate.py` L205-214 |
| Daily loss limit (paper) | $600 (4x $150 risk_per_trade) | `risk_gate.py` L158-172, `shared_risk_rules.yaml` L36 |
| Weekly loss limit (paper) | $1,200 (8x $150) | `risk_gate.py` L175-190, `shared_risk_rules.yaml` L37 |
| Portfolio heat limit | 6% of $100K = $6,000 total risk | `risk_gate.py` L268-279 |
| Single position concentration | 8% of $100K = $8,000 | `risk_gate.py` L282-288 |
| Sector concentration | 25% of $100K = $25,000 | `risk_gate.py` L291-306 |
| Kill switch per-account daily | -0.25% | `atm_config.yaml` L24 |
| Kill switch aggregate daily | -10.0% | `atm_config.yaml` L45 |

**Note on MAX_POSITIONS conflict:** The adapter hard-codes MAX_POSITIONS=3 (L23), but ATM config sets `max_concurrent=6` (L12, L40). The adapter limit is hit first during `submit_entry()` and would block at 3 positions. Current state: 4 positions open, suggesting some were opened before this limit was added, or via a different path.

---

## 5. Identified Gaps and Risks

### GAP 1: MAX_POSITIONS discrepancy (MEDIUM)
- **What:** `alpaca_paper_adapter.py` L23 hard-codes `MAX_POSITIONS = 3`, but `atm_config.yaml` allows `max_concurrent = 6`. Currently 4 positions are open.
- **Risk:** The adapter will reject new entries because `open_count >= MAX_POSITIONS` (3), even though ATM config allows 6. This creates a silent cap at 3 that doesn't match the configured limit.
- **Where:** `alpaca_paper_adapter.py` L23 and L274-278 vs `atm_config.yaml` L12 and L40
- **Fix:** Make `MAX_POSITIONS` read from ATM config or shared_risk_rules, or raise the hard-coded value to match.

### GAP 2: B-1 observation expired (LOW)
- **What:** `atm_config.yaml` L52 sets `observation_end: "2026-05-25"`. Today is 2026-05-26, so B-1 observation has expired.
- **Risk:** Bucket2 strategies (swing_breakout, swing_trade, earnings_post_momentum, recovery_watch, fib_retracement_bounce) are now eligible for ATM auto-approval. This may be intentional.
- **Action needed:** Confirm this is intentional or extend the observation period.

### GAP 3: Classifier health set to 0.0 (LOW)
- **What:** `atm_config.yaml` L19 sets `min_classifier_health: 0.0` as a temporary cold-start override. Comment says "Restore to 0.50 once >= 3 paper trades close per active strategy."
- **Risk:** Quality filtering is effectively disabled at the ATM layer. Proposals with zero classifier confidence can be auto-approved.
- **Action needed:** Check if enough trades have closed to restore the 0.50 threshold.

### GAP 4: Paper account size assumed $100K (LOW)
- **What:** `risk_gate.py` L266 reads `PAPER_ACCOUNT_SIZE` env var, defaulting to $100,000. Risk percentage calculations (heat, concentration, sector) are based on this assumed value.
- **Risk:** If actual Alpaca paper account equity differs significantly, percentage-based limits may be miscalibrated.
- **Mitigation:** The adapter fetches actual account equity via `get_account()`, but risk_gate uses the env-var value.

### GAP 5: No Vanguard account registered (INFO)
- **What:** The accounts table has Schwab and Fidelity but no Vanguard account.
- **Risk:** None currently -- no Vanguard trading integration exists. Noted for completeness.

### GAP 6: Duplicate position past MAX_POSITIONS (INFO)
- **What:** 4 positions are currently open despite `MAX_POSITIONS = 3`. This suggests positions were created before the limit was enforced or via a code path that bypasses it.
- **Risk:** None immediate -- all positions have stops. But the inconsistency should be understood.

---

## 6. Capital Flow Diagram

```
Strategy Signal (strategy_signals table)
    |
    v
[auto_proposal_generator.py]
    - normalize_size(): cap to $2K / $150 risk
    - check_quality(): score >= 40, RR >= 1.2
    - check_risk_gate(): 20 checks (risk_gate.py)
    - check_duplicate(), check_recently_closed()
    - _validate_against_strategy_criteria()
    |
    v
paper_trade_proposals (status=PENDING)
    |
    v
[atm_auto_approver.py] (*/15 min cron, 09:35-15:30 ET)
    - ATM state check (active/paused/disabled)
    - Enrichment gate (must be COMPLETE)
    - B-1 / same-day skip filters
    - Position limits (max_concurrent, max_new_per_day)
    - Classifier health gate
    - Kill switch checks
    |
    v
[paper_trade_logger.py] approve_proposal()
    |
    v
[proposal_paper_submitter.py] submit_paper()
    |
    v
[alpaca_paper_adapter.py] submit_entry()
    - MAX_POSITIONS check (3)
    - Duplicate symbol block
    - Risk gate re-check
    - Price validation (data API quotes)
    - Stop breached gate
    - Drift gate (5%)
    - Market hours gate
    - Order submission (bracket or market+stop)
    - Fill verification loop
    - Stop placement verification
    |
    v
paper_trades (status=open, account=ALPACA_PAPER)
```

---

## 7. File Reference Index

| File | Role | Key Constants/Functions |
|------|------|------------------------|
| `scripts/auto_proposal_generator.py` | Proposal creation + sizing | `normalize_size()`, `check_risk_gate()`, `DEFAULT_MAX_DOLLAR_SIZE=$2K` |
| `scripts/alpaca_paper_adapter.py` | Broker submission | `MAX_POSITIONS=3`, `MAX_POSITION_SIZE=$2K`, `submit_entry()` |
| `scripts/risk_gate.py` | 20-check risk gate | `RiskGate.check()`, `RiskDecision` |
| `scripts/atm_auto_approver.py` | ATM auto-approval cron | `run_cycle()`, position/day limits, kill switches |
| `scripts/atm_config_manager.py` | ATM config loader | `load_config()`, `get_enabled_accounts()`, `get_effective_limits()` |
| `config/atm_config.yaml` | ATM configuration | max_concurrent=6, max_new_per_day=3, kill switches |
| `config/strategies/shared_risk_rules.yaml` | Shared risk rules | risk_per_trade=$150, max_total=8, daily/weekly multipliers |
| `config/strategies/momentum_scalp.yaml` | Momentum config | max_position_size=$2K, max_dollar_risk=$200, forbidden_accounts |
| `.env` | Environment safety | `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true` |
