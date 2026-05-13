# Trade AI v12 — Strategy YAML Audit
Generated: 2026-05-13 17:56

## AUDIT SUMMARY

Total strategy YAML files: 20

| Strategy | Issues | Status |
|----------|--------|--------|
| bond_income | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| cash_or_stable | MISSING: max_hold_days; MISSING: technical_indicators_required... | 6 issues |
| core_growth_compounder | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| core_index | MISSING: max_hold_days; MISSING: technical_indicators_required... | 7 issues |
| covered_call_income | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| defense_thesis | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| dividend_growth_compounder | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| earnings_catalyst | MISSING: max_hold_days; MISSING: entry_criteria... | 10 issues |
| gap_and_go | MISSING: max_hold_days; MISSING: entry_criteria... | 9 issues |
| high_yield_income_bdc | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| income_add | MISSING: max_hold_days; MISSING: entry_criteria... | 10 issues |
| international_dividend | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| momentum_scalp | MISSING: max_hold_days; MISSING: entry_criteria... | 9 issues |
| recovery_watch | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| reit_income | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| sector_rotation | MISSING: max_hold_days; MISSING: entry_criteria... | 11 issues |
| speculative_growth | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| swing_breakout | MISSING: max_hold_days; MISSING: entry_criteria... | 9 issues |
| swing_trade | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |
| tax_loss_harvest | MISSING: max_hold_days; MISSING: technical_indicators_required... | 5 issues |

---

## FULL YAML CONTENT — ALL STRATEGIES

### bond_income
**File:** bond_income.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: bond_income
display_name: Bond Income
version: "1.0.0"
status: UNVALIDATED
purpose: "Bond funds and ETFs for fixed income allocation. Portfolio ballast, income generation, and interest rate positioning."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 1.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: BOND_VEHICLE
    description: "Approved bond ETF or mutual fund (AGG, BND, TLT, VCIT, VGSH, etc.)"
    metric: asset_class
    operator: eq
    value: fixed_income
  - id: DURATION_FIT
    description: "Duration appropriate for current rate environment and portfolio needs"
    metric: duration_appropriateness
    operator: eq
    value: true
  - id: YIELD_ATTRACTIVE
    description: "SEC yield or distribution yield meets minimum threshold for duration risk"
    metric: sec_yield
    operator: gte
    value: 0.03
  - id: CREDIT_QUALITY
    description: "Average credit quality of investment grade (BBB or above)"
    metric: avg_credit_quality
    operator: in
    value: [AAA, AA, A, BBB]

auto_disqualifiers:
  - id: HIGH_YIELD_ONLY_UNAWARE
    description: "High-yield bond fund without explicit risk acknowledgment"
  - id: DURATION_MISMATCH
    description: "Long duration in rising rate environment without explicit thesis"
  - id: IRMAA_INCOME_BREACH
    description: "Interest income would push MAGI past IRMAA threshold"

exit_rules:
  stop_method: fundamental
  target_method: level_based

risk:
  risk_per_trade_pct: 0.003
  max_position_size: 25000
  max_daily_trades: null
  target_rr: 1.5

scoring:
  min_score_go: 35
  min_score_wait: 20

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify rate environment context, credit spread trends, and Fed policy outlook."
  risk: "Assess duration risk, credit quality, and portfolio-level fixed income allocation."
  steph: "Confirm account placement for tax efficiency (munis in taxable, corporates in IRA)."

co_enables:
  promotes_to: []
  strengthens: [cash_or_stable, core_index, international_dividend]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Bond income strategy for fixed income allocation via bond ETFs and funds. Balances yield, duration, and credit quality for portfolio ballast. Tax-aware placement with munis in taxable and corporates in IRA."
  key_questions:
    - "Is duration positioning appropriate for the current rate cycle?"
    - "What is the credit spread environment signaling about risk appetite?"
    - "Should munis be favored in taxable accounts for after-tax yield?"

screen_filters:
  min_price: 20.00
  max_price: 200.00
  min_div_yield_pct: 2.5
  max_beta: 0.5
  asset_type: [etf, bond_fund, preferred]
  min_score: 0
```

### cash_or_stable
**File:** cash_or_stable.yaml
**Issues:** 6
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context
  - INSUFFICIENT entry_criteria: 3 (need 4)

```yaml
strategy_id: cash_or_stable
display_name: Cash or Stable Value
version: "1.0.0"
status: UNVALIDATED
purpose: "Money market funds, T-bills, and stable value positions for capital preservation. Dry powder management and defensive positioning."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: CASH

universe:
  price:
    min: 1.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: CASH_VEHICLE
    description: "Approved money market, T-bill ETF, or stable value fund (SPAXX, SGOV, BIL, SHV)"
    metric: asset_class
    operator: in
    value: [money_market, tbill, stable_value]
  - id: YIELD_POSITIVE
    description: "Current yield is positive and competitive with alternatives"
    metric: current_yield
    operator: gte
    value: 0.01
  - id: NAV_STABLE
    description: "NAV stable at $1.00 or ETF tracks short-duration with minimal volatility"
    metric: nav_stability
    operator: eq
    value: true

auto_disqualifiers:
  - id: CREDIT_RISK
    description: "Fund holds significant non-government credit risk"
  - id: DURATION_RISK
    description: "Effective duration exceeds 0.5 years"
  - id: BREAKING_THE_BUCK
    description: "NAV has deviated below $0.995"

exit_rules:
  stop_method: fundamental
  target_method: level_based

risk:
  risk_per_trade_pct: 0.001
  max_position_size: 100000
  max_daily_trades: null
  target_rr: 1.0

scoring:
  min_score_go: 25
  min_score_wait: 15

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Monitor yield environment and flag when redeployment into risk assets is warranted."
  risk: "Verify cash allocation percentage aligns with market regime and risk posture."
  steph: "Confirm cash placement optimizes yield across accounts and maintains liquidity needs."

co_enables:
  promotes_to: [core_index, bond_income]
  strengthens: []

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Cash and stable value strategy for capital preservation and dry powder management. Targets money market funds, T-bill ETFs, and stable value for near-zero volatility. Serves as deployment source when risk assets become attractive."
  key_questions:
    - "Is the current cash allocation appropriate for the market regime?"
    - "Are yields competitive or should cash be redeployed into short-duration bonds?"
    - "Is there sufficient liquidity across accounts for upcoming needs or opportunities?"

screen_filters:
  min_price: 1.00
  max_price: 200.00
  max_beta: 0.1
  asset_type: [money_market, treasury, stable_value]
  min_score: 0
```

### core_growth_compounder
**File:** core_growth_compounder.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: core_growth_compounder
display_name: Core Growth Compounder
version: "1.0.0"
status: UNVALIDATED
purpose: "Blue-chip growth positions for long-term compounding. Core holdings like MSFT, AAPL, NVDA with dip-buying entry discipline."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 50.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: QUALITY_SCORE
    description: "ROE >15%, debt/equity <1.5, consistent earnings growth"
    metric: quality_composite
    operator: gte
    value: 80
  - id: PULLBACK_ENTRY
    description: "Price within 10% of 52-week high or at key support level"
    metric: pct_from_52w_high
    operator: gte
    value: -0.10
  - id: EARNINGS_GROWTH
    description: "Forward EPS growth estimate >10%"
    metric: fwd_eps_growth
    operator: gte
    value: 0.10
  - id: MOAT_RATING
    description: "Wide or narrow economic moat with durable competitive advantage"
    metric: moat_rating
    operator: in
    value: [wide, narrow]

auto_disqualifiers:
  - id: EARNINGS_DECLINE
    description: "Two consecutive quarters of declining earnings"
  - id: DEBT_CRISIS
    description: "Debt/equity ratio exceeds 2.0 with declining coverage"
  - id: REGULATORY_RISK_ACUTE
    description: "Active antitrust or major regulatory action pending"
  - id: VALUATION_EXTREME
    description: "Forward P/E exceeds 2x sector median without justification"

exit_rules:
  stop_method: fundamental
  target_method: trailing

risk:
  risk_per_trade_pct: 0.01
  max_position_size: 25000
  max_daily_trades: null
  target_rr: 3.0

scoring:
  min_score_go: 45
  min_score_wait: 30

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify fundamental quality, earnings trajectory, and competitive moat durability."
  risk: "Assess valuation risk, concentration limits, and correlation with existing holdings."
  steph: "Confirm account placement optimization and total portfolio allocation fit."

co_enables:
  promotes_to: []
  strengthens: [covered_call_income, dividend_growth_compounder]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Core growth compounder for blue-chip names with durable competitive advantages. Long-term hold with fundamental stop criteria. Targets MSFT, AAPL, NVDA-class companies with pullback entry discipline."
  key_questions:
    - "Is the competitive moat widening or narrowing?"
    - "Does the current valuation offer acceptable long-term return potential?"
    - "How does this position fit within overall portfolio growth allocation?"

screen_filters:
  min_price: 50.00
  max_price: 5000.00
  min_market_cap_b: 50
  min_score: 0
  quality_focus: true
```

### core_index
**File:** core_index.yaml
**Issues:** 7
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context
  - INSUFFICIENT entry_criteria: 3 (need 4)
  - INSUFFICIENT auto_disqualifiers: 2 (need 3)

```yaml
strategy_id: core_index
display_name: Core Index
version: "1.0.0"
status: UNVALIDATED
purpose: "Broad market index fund positions (SPY, QQQ, VTI) for core portfolio allocation. DCA and rebalancing driven."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 1.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: INDEX_ELIGIBLE
    description: "Symbol is an approved broad market index ETF"
    metric: symbol
    operator: in
    value: [SPY, QQQ, VTI, VOO, IVV, VXUS, VEA, VWO]
  - id: REBALANCE_TRIGGER
    description: "Allocation drift exceeds 5% from target or scheduled DCA date"
    metric: allocation_drift_pct
    operator: gte
    value: 0.05
  - id: VALUATION_CHECK
    description: "Market not at extreme overvaluation (CAPE <35 or DCA override)"
    metric: cape_ratio
    operator: lte
    value: 35

auto_disqualifiers:
  - id: NOT_INDEX_ETF
    description: "Symbol is not in approved index ETF list"
  - id: IRMAA_BREACH
    description: "Purchase would cause MAGI to breach IRMAA threshold in IRA"

exit_rules:
  stop_method: fundamental
  target_method: level_based

risk:
  risk_per_trade_pct: 0.01
  max_position_size: 50000
  max_daily_trades: null
  target_rr: 2.0

scoring:
  min_score_go: 35
  min_score_wait: 20

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify macro environment and valuation context for allocation timing."
  risk: "Check portfolio allocation drift and rebalancing thresholds."
  steph: "Confirm account placement, tax lot selection, and IRMAA impact."

co_enables:
  promotes_to: []
  strengthens: [sector_rotation, bond_income, cash_or_stable]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Core index strategy for broad market exposure via SPY, QQQ, VTI and similar ETFs. Entry driven by DCA schedule and rebalancing triggers. Long-term hold with fundamental valuation guardrails."
  key_questions:
    - "Is portfolio allocation drifting from target index weighting?"
    - "Does current market valuation support adding or should DCA be paused?"
    - "Which account is optimal for this purchase from a tax perspective?"

screen_filters:
  min_price: 50.00
  max_price: 1000.00
  min_market_cap_b: 50.0
  max_beta: 1.1
  max_div_yield_pct: 3.0
  asset_type: [etf, index_fund]
  min_score: 0
```

### covered_call_income
**File:** covered_call_income.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: covered_call_income
display_name: Covered Call Income
version: "1.0.0"
status: UNVALIDATED
purpose: "Write covered calls on existing share positions to generate premium income. Requires 100+ shares owned in the underlying."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 10.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: SHARES_OWNED
    description: "Must own at least 100 shares of the underlying in the target account"
    metric: shares_held
    operator: gte
    value: 100
  - id: IV_RANK_ELEVATED
    description: "Implied volatility rank above 30 for acceptable premium"
    metric: iv_rank
    operator: gte
    value: 30
  - id: STRIKE_ABOVE_COST_BASIS
    description: "Call strike price above average cost basis to avoid called-away loss"
    metric: strike_vs_cost_basis
    operator: gte
    value: 1.0
  - id: DTE_RANGE
    description: "Days to expiration between 21 and 45 for optimal theta decay"
    metric: dte
    operator: gte
    value: 21

auto_disqualifiers:
  - id: NO_SHARES_HELD
    description: "No existing position of 100+ shares in the underlying"
  - id: EARNINGS_BEFORE_EXPIRY
    description: "Earnings date falls before option expiration"
  - id: STRIKE_BELOW_BASIS
    description: "Call strike below cost basis would lock in a loss if assigned"
  - id: WASH_SALE_RISK
    description: "Assignment would trigger wash sale with recent loss in same security"

exit_rules:
  stop_method: fixed_pct
  target_method: level_based

risk:
  risk_per_trade_pct: 0.005
  max_position_size: 10000
  max_daily_trades: null
  target_rr: 1.5

scoring:
  min_score_go: 40
  min_score_wait: 25

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: 45

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify underlying thesis intact and no upcoming catalysts that warrant keeping upside."
  risk: "Validate strike selection, DTE, and assignment risk vs cost basis."
  steph: "Confirm account-level options approval, tax implications of assignment, and income impact."

co_enables:
  promotes_to: []
  strengthens: [core_growth_compounder, dividend_growth_compounder, reit_income]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Covered call income strategy for generating premium on existing 100+ share positions. Targets elevated IV rank with strikes above cost basis and 21-45 DTE. Requires existing share ownership as prerequisite."
  key_questions:
    - "Is the underlying thesis still intact or should shares be sold outright instead?"
    - "Does IV rank justify writing calls now vs waiting for higher premium?"
    - "Will assignment at the selected strike result in a net gain above cost basis?"

screen_filters:
  min_price: 15.00
  max_price: 500.00
  min_iv_rank: 30
  min_market_cap_b: 1.0
  max_beta: 1.5
  requires_shares_owned: true
  min_shares_owned: 100
  min_score: 0
```

### defense_thesis
**File:** defense_thesis.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: defense_thesis
display_name: Defense Thesis
version: "1.0.0"
status: UNVALIDATED
purpose: "Defense and aerospace conviction positions based on AI + WWIII geopolitical thesis. Long-term strategic allocation to defense contractors and adjacent technologies."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 20.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: DEFENSE_SECTOR
    description: "Company is a defense contractor, aerospace firm, or defense-adjacent technology provider"
    metric: sector_subsector
    operator: in
    value: [defense_prime, defense_sub, aerospace, defense_tech, cybersecurity_defense]
  - id: GOVERNMENT_REVENUE
    description: "At least 30% of revenue from US government or NATO contracts"
    metric: govt_revenue_pct
    operator: gte
    value: 0.30
  - id: BACKLOG_GROWTH
    description: "Contract backlog growing or stable YoY"
    metric: backlog_trend
    operator: in
    value: [growing, stable]
  - id: PULLBACK_ENTRY
    description: "Entry on pullback to support or consolidation, not chasing highs"
    metric: entry_quality
    operator: eq
    value: pullback_or_base

auto_disqualifiers:
  - id: CONTRACT_LOSS_MAJOR
    description: "Lost a major contract representing >10% of revenue"
  - id: SECURITY_CLEARANCE_ISSUE
    description: "Company facing security clearance revocation or CFIUS concerns"
  - id: BUDGET_CUT_DIRECT
    description: "Direct line item in proposed budget cuts exceeding 15%"
  - id: OVERCONCENTRATION
    description: "Defense thesis allocation would exceed 20% of total portfolio"

exit_rules:
  stop_method: fundamental
  target_method: trailing

risk:
  risk_per_trade_pct: 0.01
  max_position_size: 25000
  max_daily_trades: null
  target_rr: 3.0

scoring:
  min_score_go: 45
  min_score_wait: 30

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify contract pipeline, geopolitical catalyst relevance, and competitive position."
  risk: "Assess concentration risk within defense thesis and correlation with existing holdings."
  steph: "Confirm portfolio-level defense allocation limits and account placement optimization."

co_enables:
  promotes_to: []
  strengthens: [core_growth_compounder, covered_call_income]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Defense thesis strategy for conviction positions in defense/aerospace companies aligned with AI and geopolitical risk themes. Long-term hold with fundamental exit criteria. Targets prime contractors, defense tech, and cybersecurity defense names."
  key_questions:
    - "Is the geopolitical catalyst thesis strengthening or weakening?"
    - "Does the company have durable contract backlog and margin stability?"
    - "What is current defense thesis allocation as percentage of total portfolio?"

screen_filters:
  min_price: 5.00
  max_price: 1000.00
  min_market_cap_b: 0.5
  sector_include: [Industrials, Technology]
  sector_filter: [defense, aerospace, cybersecurity]
  industry_keywords: [defense, aerospace, government, military, security]
  thesis_driven: true
  min_score: 0
```

### dividend_growth_compounder
**File:** dividend_growth_compounder.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: dividend_growth_compounder
display_name: Dividend Growth Compounder
version: "1.0.0"
status: UNVALIDATED
purpose: "Dividend aristocrats and kings for reliable income growth. Focus on companies with 10+ years of consecutive dividend increases and sustainable payout ratios."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 15.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: DIVIDEND_STREAK
    description: "At least 10 consecutive years of dividend increases"
    metric: div_increase_streak_years
    operator: gte
    value: 10
  - id: PAYOUT_RATIO
    description: "Payout ratio below 75% for sustainability"
    metric: payout_ratio
    operator: lte
    value: 0.75
  - id: DIVIDEND_GROWTH_RATE
    description: "5-year dividend CAGR of at least 5%"
    metric: div_cagr_5y
    operator: gte
    value: 0.05
  - id: YIELD_MINIMUM
    description: "Current yield at least 1.5%"
    metric: dividend_yield
    operator: gte
    value: 0.015

auto_disqualifiers:
  - id: DIVIDEND_CUT
    description: "Dividend cut or freeze within the last 12 months"
  - id: PAYOUT_UNSUSTAINABLE
    description: "Payout ratio exceeds 85% with declining earnings"
  - id: DEBT_DETERIORATION
    description: "Debt/equity rising with declining interest coverage"
  - id: IRMAA_BREACH_RISK
    description: "Dividend income would push MAGI past IRMAA threshold"

exit_rules:
  stop_method: fundamental
  target_method: trailing

risk:
  risk_per_trade_pct: 0.005
  max_position_size: 15000
  max_daily_trades: null
  target_rr: 2.0

scoring:
  min_score_go: 42
  min_score_wait: 28

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify dividend safety, payout sustainability, and earnings quality."
  risk: "Assess yield trap risk, sector concentration, and rate sensitivity."
  steph: "Confirm account placement for tax efficiency and IRMAA/SSDI income impact."

co_enables:
  promotes_to: []
  strengthens: [covered_call_income, high_yield_income_bdc, reit_income]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Dividend growth compounder targeting aristocrats and kings with 10+ year increase streaks. Focuses on sustainable payout ratios and growing dividends for long-term income compounding. IRMAA-aware for retirement accounts."
  key_questions:
    - "Is the dividend growth rate accelerating or decelerating?"
    - "Can the company sustain the dividend through a recession scenario?"
    - "What is the IRMAA and SSDI income impact of adding this position?"

screen_filters:
  min_price: 10.00
  max_price: 500.00
  min_div_yield_pct: 1.0
  max_div_yield_pct: 6.0
  min_market_cap_b: 5.0
  max_beta: 1.2
  min_dividend_growth_years: 5
  min_score: 0
```

### earnings_catalyst
**File:** earnings_catalyst.yaml
**Issues:** 10
  - MISSING: max_hold_days
  - MISSING: entry_criteria
  - MISSING: exit_rules
  - MISSING: technical_indicators_required
  - MISSING: co_enables
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context
  - INSUFFICIENT entry_criteria: 0 (need 4)
  - INSUFFICIENT auto_disqualifiers: 2 (need 3)

```yaml
strategy_id: earnings_catalyst
display_name: Earnings Catalyst
version: "1.0"
status: TESTING
purpose: "Pre-earnings buildup + post-earnings momentum. Two sub-strategies tracked independently."

eligible_accounts: [taxable, rollover_ira, roth_ira]
forbidden_accounts: []
timeframe: swing_1_to_5d
timeframe_class: SHORT_SWING
universe: earnings_candidates

primary_data_sources:
  - news_articles
  - finviz_screener
  - sec_edgar

sub_strategies:
  pre_earnings_buildup:
    description: "Enter 3-5 days before earnings on institutional activity."
    entry_window_days_before: [3, 5]
    exit_before_announcement: true
    never_hold_through_earnings_in_taxable: true
    required_evidence:
      - options_activity_surge
      - analyst_revision_up_30d
  post_earnings_momentum:
    description: "Enter 1-2 days after earnings if beat >10% and price gaps."
    entry_window_days_after: [1, 2]
    min_beat_pct: 10
    gap_hold_30min_required: true
    hold_ok_in_ira_when_validated: true

screen_filters:
  min_price: 5.00
  max_price: 200.00
  min_rvol: 1.5
  max_float_m: 200

setup_qualification:
  earnings_date_required: true
  catalyst_verification: required

auto_disqualifiers:
  - id: NO_EARNINGS_DATE
    condition: "earnings_date not available"
  - id: HOLD_THROUGH_IN_TAXABLE
    condition: "pre_earnings and account == taxable and hold_through"

scoring_weights:
  earnings_quality: 25
  options_activity: 20
  technical_setup: 20
  analyst_sentiment: 15
  catalyst: 10
  float: 10

grade_thresholds:
  aplus: 50
  a: 42
  b: 35
  c: 28

minimum_evidence:
  required:
    - earnings_date
    - price_data
    - trade_plan
  preferred:
    - options_volume
    - analyst_estimates
    - revenue_data

agent_responsibilities:
  maria: "Verify earnings/catalyst data. Check beat magnitude and guidance."
  risk: "Verify gap levels, entry timing, stop placement."
  tax: "Verify account rules for hold-through-earnings scenarios."

live_trade_rules:
  max_dollar_risk: 200
  max_hold_days: 5

outcome_learning_fields:
  - sub_strategy_type
  - beat_magnitude
  - guidance_direction
  - gap_magnitude
  - entry_timing
  - sector_alignment
```

### gap_and_go
**File:** gap_and_go.yaml
**Issues:** 9
  - MISSING: max_hold_days
  - MISSING: entry_criteria
  - MISSING: exit_rules
  - MISSING: technical_indicators_required
  - MISSING: co_enables
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context
  - INSUFFICIENT entry_criteria: 0 (need 4)

```yaml
strategy_id: gap_and_go
display_name: Gap & Go
version: "1.0"
status: TESTING
purpose: "Pre-market gap >5% with volume confirmation at open. Enter on first candle close above gap high."

eligible_accounts: [taxable]
forbidden_accounts: [rollover_ira, roth_ira, fidelity_401k]
timeframe: intraday
timeframe_class: INTRADAY
universe: gap_candidates

primary_data_sources:
  - premarket_watcher
  - finviz_screener
  - news_articles
  - sec_edgar

screen_filters:
  min_price: 2.00
  max_price: 50.00
  min_gap_pct: 5.0
  elevated_vix_min_gap_pct: 10.0
  max_gap_pct: 100.0
  min_rvol: 3.0
  max_float_m: 100
  min_score: 38

setup_qualification:
  catalyst_required: true
  social_only_max_grade: WATCH
  entry_window_start: "09:30"
  entry_window_end: "09:50"
  first_candle_confirmation: required
  no_chase_entry: true
  premarket_rvol_confirmation: true

auto_disqualifiers:
  - id: NO_CATALYST
    condition: "catalyst is null or empty"
  - id: ENTRY_AFTER_950AM
    condition: "current_time > 09:50 ET"
  - id: GAP_FILL_ALREADY
    condition: "price below previous close"
  - id: CHASE_ENTRY
    condition: "price > gap_high * 1.05"

scoring_weights:
  gap: 20
  rvol: 15
  catalyst: 12
  float: 8
  price_action: 10
  price_range: 5

grade_thresholds:
  aplus: 48
  a: 40
  b: 35
  c: 28

minimum_evidence:
  required:
    - price_data
    - gap_pct_data
    - rvol_data
    - catalyst_text
    - trade_plan
  preferred:
    - premarket_volume
    - catalyst_verified

agent_responsibilities:
  maria: "Verify gap catalyst. Check if gap is news-driven vs technical."
  risk: "Verify gap levels, entry timing, stop below gap low."

paper_trade_rules:
  use_same_plan_as_live: true
  confirm_in_tos_premarket: true

live_trade_rules:
  max_position_size: 2000
  max_dollar_risk: 200
  max_entry_delay_minutes: 30
  no_overnight_hold: true

outcome_learning_fields:
  - gap_magnitude
  - catalyst_type
  - first_candle_direction
  - entry_vs_gap_high
  - fill_time
```

### high_yield_income_bdc
**File:** high_yield_income_bdc.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: high_yield_income_bdc
display_name: High Yield Income (BDC/CLO)
version: "1.0.0"
status: UNVALIDATED
purpose: "BDC, CLO, and high-yield vehicles for current income generation. Tax-inefficient income best suited for tax-advantaged accounts."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 5.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: YIELD_MINIMUM
    description: "Current distribution yield at least 7%"
    metric: distribution_yield
    operator: gte
    value: 0.07
  - id: NAV_DISCOUNT
    description: "Trading at or below NAV (price/NAV <= 1.05)"
    metric: price_to_nav
    operator: lte
    value: 1.05
  - id: DISTRIBUTION_COVERAGE
    description: "Net investment income covers at least 90% of distribution"
    metric: nii_coverage
    operator: gte
    value: 0.90
  - id: CREDIT_QUALITY
    description: "Non-accrual rate below 3% of portfolio at fair value"
    metric: non_accrual_rate
    operator: lte
    value: 0.03

auto_disqualifiers:
  - id: DISTRIBUTION_CUT
    description: "Distribution cut within the last 6 months"
  - id: NAV_EROSION
    description: "NAV declined more than 10% over trailing 12 months"
  - id: BDC_IN_TAXABLE_UNAPPROVED
    description: "BDC placement in taxable account without explicit approval"
  - id: LEVERAGE_EXCESSIVE
    description: "Debt-to-equity ratio exceeds regulatory limit or 1.5x"

exit_rules:
  stop_method: fundamental
  target_method: level_based

risk:
  risk_per_trade_pct: 0.003
  max_position_size: 10000
  max_daily_trades: null
  target_rr: 1.5

scoring:
  min_score_go: 40
  min_score_wait: 25

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify credit quality, NAV trend, distribution sustainability, and portfolio composition."
  risk: "Assess rate sensitivity, leverage levels, and correlation with existing income holdings."
  steph: "Confirm tax-advantaged account placement and income impact on SSDI/IRMAA thresholds."

co_enables:
  promotes_to: []
  strengthens: [dividend_growth_compounder, reit_income, bond_income]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "High-yield income strategy targeting BDCs, CLOs, and high-yield vehicles for current income. Emphasizes distribution coverage, NAV stability, and credit quality. Tax-inefficient income strongly prefers IRA placement."
  key_questions:
    - "Is the distribution covered by net investment income or is it return of capital?"
    - "What is the non-accrual trend and credit quality trajectory?"
    - "Is this being placed in a tax-advantaged account to avoid ordinary income taxation?"

screen_filters:
  min_price: 3.00
  max_price: 50.00
  min_div_yield_pct: 7.0
  max_div_yield_pct: 20.0
  asset_type: [bdc, high_yield, cef]
  min_score: 0
```

### income_add
**File:** income_add.yaml
**Issues:** 10
  - MISSING: max_hold_days
  - MISSING: entry_criteria
  - MISSING: exit_rules
  - MISSING: technical_indicators_required
  - MISSING: co_enables
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context
  - INSUFFICIENT entry_criteria: 0 (need 4)
  - MISSING: agent_responsibilities.maria and/or .risk

```yaml
strategy_id: income_add
display_name: Income Position Add
version: "1.0"
status: TESTING
purpose: "Adding to or initiating income positions. Triggered by pullbacks to support, ex-div opportunities, or rebalancing."

eligible_accounts: [rollover_ira, roth_ira, taxable]
forbidden_accounts: []
timeframe: position_long
timeframe_class: POSITION
universe: income_candidates

primary_data_sources:
  - portfolio_holdings
  - finviz_enrichment
  - alex_retirement_advisor
  - fred_data

screen_filters:
  min_yield: 3.0
  max_payout_ratio: 0.85
  min_dividend_growth_years: 3
  entry_rsi_max: 50
  entry_below_sma_50: true

setup_qualification:
  ssdi_check_required: true
  irmaa_check_required: true
  golden_window_impact_check: true
  alex_analysis_required: true
  steph_analysis_required: true

auto_disqualifiers:
  - id: DIVIDEND_CUT
    condition: "dividend_cut_within_12m"
  - id: PAYOUT_UNSUSTAINABLE
    condition: "payout_ratio > 0.85"
  - id: SSDI_NOT_CHECKED
    condition: "ssdi_check not completed"
  - id: IRMAA_BREACH_RISK
    condition: "projected MAGI exceeds IRMAA threshold"
  - id: BDC_IN_TAXABLE
    condition: "asset_type == BDC and account == taxable"
  - id: REIT_IN_TAXABLE_UNAPPROVED
    condition: "asset_type == REIT and account == taxable and not specifically_approved"

scoring_weights:
  dividend_safety: 30
  yield_quality: 25
  technical_entry: 20
  income_gap_impact: 15
  ssdi_impact: 10

grade_thresholds:
  aplus: 50
  a: 42
  b: 35
  c: 28

minimum_evidence:
  required:
    - dividend_data
    - ssdi_impact_assessment
    - irmaa_projection
    - portfolio_income_impact
    - alex_analysis
    - steph_analysis
  preferred:
    - golden_window_impact
    - tax_lot_optimization

recommendation_outputs:
  - ADD
  - WATCH
  - HOLD
  - DO_NOT_ADD

agent_responsibilities:
  alex: "Full retirement-aware analysis. SSDI/IRMAA/MAGI check. Golden Window impact."
  steph: "Portfolio fit, income gap impact, allocation limits."
  tax: "Tax lot optimization. Wash sale check. Account placement."

paper_trade_rules:
  track_income_yield_on_cost: true
  benchmark_comparison_12m: true

live_trade_rules:
  dollar_risk: 500
  preferred_accounts: [rollover_ira, roth_ira]

outcome_learning_fields:
  - yield_on_cost
  - income_contribution
  - ssdi_impact
  - irmaa_impact
  - hold_duration
  - benchmark_relative_performance
```

### international_dividend
**File:** international_dividend.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: international_dividend
display_name: International Dividend
version: "1.0.0"
status: UNVALIDATED
purpose: "International dividend-paying equities and ETFs for geographic diversification and currency exposure. Focus on developed market payers with stable dividends."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 5.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: INTERNATIONAL_EXPOSURE
    description: "ETF or ADR with primary revenue from non-US markets"
    metric: intl_revenue_pct
    operator: gte
    value: 0.50
  - id: YIELD_MINIMUM
    description: "Current dividend yield at least 2.5%"
    metric: dividend_yield
    operator: gte
    value: 0.025
  - id: DIVIDEND_STABILITY
    description: "No dividend cut in the last 3 years (or ETF distribution stable)"
    metric: div_cut_3y
    operator: eq
    value: false
  - id: CURRENCY_DIVERSIFICATION
    description: "Adds meaningful currency diversification to portfolio"
    metric: currency_diversification_score
    operator: gte
    value: 0.5

auto_disqualifiers:
  - id: COUNTRY_RISK_EXTREME
    description: "Domiciled in country with extreme political or capital control risk"
  - id: WITHHOLDING_TAX_PUNITIVE
    description: "Foreign withholding tax >25% without treaty relief"
  - id: LIQUIDITY_INSUFFICIENT
    description: "Average daily volume below $500K for ADRs"
  - id: DIVIDEND_CUT_RECENT
    description: "Dividend cut within last 12 months"

exit_rules:
  stop_method: fundamental
  target_method: level_based

risk:
  risk_per_trade_pct: 0.003
  max_position_size: 10000
  max_daily_trades: null
  target_rr: 2.0

scoring:
  min_score_go: 38
  min_score_wait: 25

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify dividend sustainability, country risk, and currency trend analysis."
  risk: "Assess foreign withholding tax impact, ADR liquidity, and correlation with domestic holdings."
  steph: "Confirm account placement for foreign tax credit optimization and portfolio diversification fit."

co_enables:
  promotes_to: []
  strengthens: [dividend_growth_compounder, core_index]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "International dividend strategy for geographic and currency diversification via dividend-paying ADRs and international ETFs. Prioritizes developed market stability with foreign tax credit awareness for account placement."
  key_questions:
    - "Does the foreign withholding tax make this better suited for taxable (FTC) or IRA?"
    - "What is the currency risk and does it provide meaningful diversification?"
    - "Is the dividend sustainable given the local economic and political environment?"

screen_filters:
  min_price: 5.00
  max_price: 300.00
  min_div_yield_pct: 2.0
  max_div_yield_pct: 10.0
  country_filter: [non_us, international, adr]
  min_score: 0
```

### momentum_scalp
**File:** momentum_scalp.yaml
**Issues:** 9
  - MISSING: max_hold_days
  - MISSING: entry_criteria
  - MISSING: exit_rules
  - MISSING: technical_indicators_required
  - MISSING: co_enables
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context
  - INSUFFICIENT entry_criteria: 0 (need 4)

```yaml
strategy_id: momentum_scalp
display_name: Momentum Scalp
version: "1.0"
status: TESTING
purpose: "Micro-cap momentum — RVOL surge + verified catalyst. Intraday hold, exit same day."

eligible_accounts: [taxable]
forbidden_accounts: [rollover_ira, roth_ira, fidelity_401k]
timeframe: intraday
timeframe_class: INTRADAY
universe: micro_cap_momentum

primary_data_sources:
  - finviz_screener
  - trade_ai_scans
  - social_posts
  - news_articles
  - sec_form4

screen_filters:
  min_price: 1.00
  max_price: 25.00
  preferred_max_price: 10.00
  min_rvol: 5.0
  premium_rvol: 8.0
  max_float_m: 100
  preferred_max_float_m: 20
  min_gap_pct: 5.0
  min_score: 40
  aplus_score: 48

setup_qualification:
  catalyst_present: required
  catalyst_verified_for_aplus: true
  catalyst_verified_for_live: true
  social_only_max_grade: WATCH
  price_data_max_age_minutes: 15
  rvol_data_required: true
  float_data_required: true

auto_disqualifiers:
  - id: PRICE_OVER_25
    condition: "price > 25"
  - id: FLOAT_OVER_100M
    condition: "float_m > 100"
  - id: STOP_OVER_15_PCT
    condition: "stop_pct > 0.15"
  - id: POSITION_OVER_2000
    condition: "dollar_size > 2000"
  - id: SAME_SECTOR_OPEN
    condition: "open_position_in_same_sector"
  - id: AFTER_130PM
    condition: "current_time > 13:30 ET"
  - id: REVERSE_SPLIT_RECENT
    condition: "reverse_split_within_90d"
  - id: TRADING_HALTED
    condition: "trading_halt_active"
  - id: WIDE_SPREAD
    condition: "spread_pct > 5"
  - id: DILUTION_RISK
    condition: "recent_offering_or_shelf"

scoring_weights:
  catalyst: 15
  rvol: 12
  price_action: 10
  float: 8
  price_range: 5
  sector_momentum: 5

grade_thresholds:
  aplus: 48
  a: 42
  b: 35
  c: 28

minimum_evidence:
  required:
    - price_data
    - rvol_data
    - float_data
    - trade_plan
    - stop_defined
  preferred:
    - catalyst_verified
    - intel_readiness_score
    - sector_data

recommendation_rules:
  social_only_catalyst: WATCH
  unverified_catalyst_max: WAIT
  verified_catalyst_high_rvol: GO
  all_evidence_present_aplus: APPROVAL_REQUIRED

agent_responsibilities:
  maria: "Verify catalyst source and relevance. Check for contrary news."
  risk: "Verify entry zone, stop placement, R:R ratio. Check for technical traps."
  steph: "Verify position sizing and account fit. Confirm no wash sale risk."

paper_trade_rules:
  use_same_plan_as_live: true
  log_entry_slippage: true
  log_max_adverse_excursion: true
  auto_exit_at_close: true

live_trade_rules:
  max_position_size: 2000
  max_dollar_risk: 200
  no_overnight_hold: true
  require_risk_gate_approved: true

outcome_learning_fields:
  - entry_slippage
  - stop_hit_before_target
  - target_hit_time
  - max_adverse_excursion
  - catalyst_type
  - rvol_at_entry
  - float_at_entry
  - time_of_entry
  - sector
  - vix_at_entry

sub_strategies:
  high_rvol_verified:
    description: "RVOL >8x + verified catalyst"
    expected_win_rate: 0.65
    filters:
      min_rvol: 8.0
      catalyst_verified: true
  moderate_rvol_verified:
    description: "RVOL 5-8x + verified catalyst"
    expected_win_rate: 0.55
    filters:
      min_rvol: 5.0
      max_rvol: 8.0
      catalyst_verified: true
  high_rvol_unverified:
    description: "RVOL >8x + unverified catalyst"
    expected_win_rate: 0.45
    filters:
      min_rvol: 8.0
      catalyst_verified: false
  social_confirmed:
    description: "Social surge + Finviz confirmation"
    expected_win_rate: 0.50
    filters:
      source: social_confirmed
```

### recovery_watch
**File:** recovery_watch.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: recovery_watch
display_name: Recovery Watch
version: "1.0.0"
status: UNVALIDATED
purpose: "Beaten-down names showing early recovery signs. Contrarian entries on oversold bounces with fundamental improvement catalysts."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_2_to_8w
timeframe_class: MEDIUM_SWING

universe:
  price:
    min: 3.00
    max: 200.00
  float_m:
    max: null
  rvol:
    min: 1.0

entry_criteria:
  - id: DRAWDOWN_MAGNITUDE
    description: "Stock has declined 30%+ from 52-week high"
    metric: drawdown_from_52w_high
    operator: lte
    value: -0.30
  - id: RECOVERY_SIGNAL
    description: "Price reclaiming 10-day or 20-day SMA with volume"
    metric: sma_reclaim
    operator: eq
    value: true
  - id: FUNDAMENTAL_CATALYST
    description: "Identifiable catalyst for recovery: earnings beat, insider buying, upgrade, restructuring"
    metric: recovery_catalyst
    operator: exists
    value: true
  - id: NOT_VALUE_TRAP
    description: "Revenue not declining and no secular headwinds"
    metric: revenue_trend
    operator: in
    value: [growing, stable]

auto_disqualifiers:
  - id: BANKRUPTCY_RISK
    description: "Debt maturities within 12 months exceed cash plus revolver"
  - id: SECULAR_DECLINE
    description: "Industry in permanent secular decline with no pivot"
  - id: FRAUD_OR_RESTATEMENT
    description: "Accounting restatement or fraud investigation active"
  - id: INSIDER_DUMPING
    description: "Heavy insider selling during the decline period"

exit_rules:
  stop_method: atr_based
  target_method: rr_based

risk:
  risk_per_trade_pct: 0.005
  max_position_size: 3000
  max_daily_trades: 2
  target_rr: 3.0

scoring:
  min_score_go: 42
  min_score_wait: 28

lifecycle:
  proposal_expiry_hours: 336
  overnight_allowed: true
  max_hold_days: 56

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify recovery catalyst legitimacy and distinguish from dead-cat bounce."
  risk: "Assess downside risk to new lows, bankruptcy probability, and stop placement."
  steph: "Confirm position sizing appropriate for speculative recovery allocation."

co_enables:
  promotes_to: [swing_trade, speculative_growth]
  strengthens: []

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Recovery watch strategy for contrarian entries on beaten-down names showing fundamental improvement. Targets 30%+ drawdowns with identifiable recovery catalysts. Holds 2-8 weeks with strict value-trap guardrails."
  key_questions:
    - "Is this a genuine recovery catalyst or a dead-cat bounce?"
    - "What is the bankruptcy or further downside risk from current levels?"
    - "Is insider behavior aligned with the recovery thesis?"

screen_filters:
  min_price: 1.00
  max_price: 100.00
  max_pct_from_52w_high: -30
  recovery_candidate: true
  min_score: 0
```

### reit_income
**File:** reit_income.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: reit_income
display_name: REIT Income
version: "1.0.0"
status: UNVALIDATED
purpose: "REIT positions for income generation and real estate portfolio exposure. Focus on well-managed REITs with sustainable FFO payout ratios."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: position_long
timeframe_class: POSITION

universe:
  price:
    min: 10.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: REIT_CLASSIFICATION
    description: "Company is a qualifying REIT with 90%+ income distribution requirement"
    metric: asset_type
    operator: eq
    value: REIT
  - id: FFO_PAYOUT
    description: "AFFO payout ratio below 85% for distribution sustainability"
    metric: affo_payout_ratio
    operator: lte
    value: 0.85
  - id: OCCUPANCY_RATE
    description: "Portfolio occupancy rate above 90%"
    metric: occupancy_rate
    operator: gte
    value: 0.90
  - id: YIELD_ATTRACTIVE
    description: "Current yield at least 3.5% or above sector median"
    metric: dividend_yield
    operator: gte
    value: 0.035

auto_disqualifiers:
  - id: DISTRIBUTION_CUT
    description: "Distribution cut within the last 12 months"
  - id: LEVERAGE_EXCESSIVE
    description: "Net debt to EBITDA exceeds 7x"
  - id: REIT_IN_TAXABLE_UNAPPROVED
    description: "REIT placement in taxable without explicit approval (non-qualified dividends)"
  - id: OCCUPANCY_DECLINING
    description: "Occupancy rate declining for 3+ consecutive quarters"

exit_rules:
  stop_method: fundamental
  target_method: level_based

risk:
  risk_per_trade_pct: 0.005
  max_position_size: 12000
  max_daily_trades: null
  target_rr: 2.0

scoring:
  min_score_go: 40
  min_score_wait: 25

lifecycle:
  proposal_expiry_hours: 720
  overnight_allowed: true
  max_hold_days: null

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify FFO quality, occupancy trends, lease duration, and property type outlook."
  risk: "Assess interest rate sensitivity, leverage, and correlation with existing real estate exposure."
  steph: "Confirm IRA placement preference for tax efficiency and IRMAA income impact."

co_enables:
  promotes_to: []
  strengthens: [dividend_growth_compounder, high_yield_income_bdc, covered_call_income]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "REIT income strategy for real estate exposure and income generation. Targets well-managed REITs with sustainable AFFO payout ratios and high occupancy. Strongly prefers IRA placement due to non-qualified dividend taxation."
  key_questions:
    - "Is the REIT's property type sector facing headwinds or tailwinds?"
    - "Is the distribution covered by AFFO or is there return-of-capital risk?"
    - "Should this be placed in IRA to avoid unfavorable tax treatment?"

screen_filters:
  min_price: 5.00
  max_price: 200.00
  min_div_yield_pct: 3.5
  max_div_yield_pct: 15.0
  sector_include: [Real Estate]
  sector_filter: [reit, real_estate]
  min_score: 0
```

### sector_rotation
**File:** sector_rotation.yaml
**Issues:** 11
  - MISSING: max_hold_days
  - MISSING: entry_criteria
  - MISSING: exit_rules
  - MISSING: technical_indicators_required
  - MISSING: co_enables
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context
  - INSUFFICIENT entry_criteria: 0 (need 4)
  - INSUFFICIENT auto_disqualifiers: 2 (need 3)
  - MISSING: agent_responsibilities.maria and/or .risk

```yaml
strategy_id: sector_rotation
display_name: Sector Rotation
version: "1.0"
status: TESTING
purpose: "Trade leading sector ETF surges and lagging sector weakness. Weekly rebalance."

eligible_accounts: [taxable, rollover_ira, roth_ira]
forbidden_accounts: []
timeframe: position_2_to_8w
timeframe_class: MEDIUM_SWING
universe: sector_etfs

primary_data_sources:
  - price_cache
  - fred_data
  - indicator_engine

etf_universe:
  - XLF
  - XLE
  - XLK
  - XLV
  - XLI
  - XLU
  - XLP
  - XLB
  - XLRE
  - XLC

screen_filters:
  min_relative_strength_vs_spy: 0.02
  top_n_sectors: 3
  rebalance_frequency: weekly
  max_hold_weeks: 8

setup_qualification:
  outperform_spy_5d_pct: 2.0
  must_be_top_3: true
  exit_when_drops_to_bottom_5: true
  macro_alignment_check: true

auto_disqualifiers:
  - id: NOT_IN_ETF_UNIVERSE
    condition: "symbol not in etf_universe"
  - id: BELOW_SPY_PERFORMANCE
    condition: "5d performance < SPY + 2%"

scoring_weights:
  relative_strength: 30
  momentum: 25
  breadth: 20
  macro_alignment: 15
  volume: 10

grade_thresholds:
  aplus: 50
  a: 42
  b: 35
  c: 28

minimum_evidence:
  required:
    - sector_performance_data
    - spy_comparison
    - fred_context
  preferred:
    - breadth_data
    - options_flow

agent_responsibilities:
  steph: "Verify sector allocation fit with portfolio. Check IRA eligibility."
  risk: "Verify relative strength calculation and exit rules."
  alex: "Check macro alignment with FRED context and retirement impact."

paper_trade_rules:
  weekly_rebalance: true
  log_sector_ranks_at_entry: true

live_trade_rules:
  dollar_risk: 500
  max_hold_weeks: 8

fidelity_401k_note: "Limited to available 401k funds. Map sector to closest available fund."

outcome_learning_fields:
  - sector_rank_at_entry
  - spy_relative_performance
  - fred_context_at_entry
  - hold_duration_weeks
  - rebalance_count
```

### speculative_growth
**File:** speculative_growth.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: speculative_growth
display_name: Speculative Growth
version: "1.0.0"
status: UNVALIDATED
purpose: "High-growth small/mid-cap names with strong momentum thesis. Higher risk tolerance for outsized upside potential."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: swing_3_to_21d
timeframe_class: SHORT_SWING

universe:
  price:
    min: 3.00
    max: 150.00
  float_m:
    max: 500
  rvol:
    min: 1.5

entry_criteria:
  - id: REVENUE_GROWTH
    description: "Revenue growth >20% YoY or accelerating QoQ"
    metric: revenue_growth_yoy
    operator: gte
    value: 0.20
  - id: MOMENTUM_SCORE
    description: "Relative strength rank in top 20% of universe"
    metric: rs_rank_percentile
    operator: gte
    value: 80
  - id: INSTITUTIONAL_INTEREST
    description: "Rising institutional ownership or notable fund entry"
    metric: inst_ownership_trend
    operator: eq
    value: rising
  - id: BREAKOUT_PATTERN
    description: "Price breaking above consolidation or basing pattern"
    metric: breakout_confirmed
    operator: eq
    value: true

auto_disqualifiers:
  - id: CASH_BURN_CRITICAL
    description: "Less than 6 months cash runway without profitability path"
  - id: DILUTION_RISK
    description: "Recent shelf registration or ATM offering filed"
  - id: INSIDER_SELLING_HEAVY
    description: "Insider selling >5% of holdings in last 30 days"
  - id: NO_REVENUE
    description: "Pre-revenue company with no clear monetization timeline"

exit_rules:
  stop_method: atr_based
  target_method: trailing

risk:
  risk_per_trade_pct: 0.005
  max_position_size: 3000
  max_daily_trades: 2
  target_rr: 3.0

scoring:
  min_score_go: 42
  min_score_wait: 28

lifecycle:
  proposal_expiry_hours: 168
  overnight_allowed: true
  max_hold_days: 21

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify growth metrics, competitive moat, and catalyst timeline."
  risk: "Assess downside scenario, stop placement, and dilution risk."
  steph: "Confirm position sizing appropriate for speculative allocation bucket."

co_enables:
  promotes_to: [core_growth_compounder]
  strengthens: [swing_trade, swing_breakout]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Speculative growth strategy targeting small/mid-cap names with strong revenue growth and momentum. Higher risk tolerance with strict dilution and cash burn guardrails. Holds 3-21 days."
  key_questions:
    - "Is revenue growth accelerating or decelerating?"
    - "What is the dilution risk from shelf registrations or convertible notes?"
    - "Does institutional ownership trend support the momentum thesis?"

screen_filters:
  min_price: 2.00
  max_price: 50.00
  min_rvol: 2.0
  max_float_m: 200
  min_score: 35
  high_risk: true
```

### swing_breakout
**File:** swing_breakout.yaml
**Issues:** 9
  - MISSING: max_hold_days
  - MISSING: entry_criteria
  - MISSING: exit_rules
  - MISSING: technical_indicators_required
  - MISSING: co_enables
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context
  - INSUFFICIENT entry_criteria: 0 (need 4)

```yaml
strategy_id: swing_breakout
display_name: Swing Breakout
version: "1.0"
status: TESTING
purpose: "Technical breakout from multi-week consolidation base. 20+ day base, volume dry-up, then expansion."

eligible_accounts: [taxable, rollover_ira, roth_ira]
forbidden_accounts: [fidelity_401k]
timeframe: swing_3_to_21d
timeframe_class: SHORT_SWING
universe: breakout_candidates

primary_data_sources:
  - finviz_screener
  - indicator_engine
  - news_articles

screen_filters:
  min_price: 5.00
  max_price: 150.00
  max_float_m: 500
  min_rvol: 1.5
  min_score: 35

setup_qualification:
  min_base_days: 15
  max_base_days: 90
  volume_dry_up_days: 3
  volume_dry_up_threshold: 0.7
  breakout_volume_ratio: 1.5
  sector_rank_max: 3
  entry_within_breakout_pct: 3.0
  stop_below_base_low: true
  manual_chart_review_during_testing: true
  no_entry_if_earnings_within_days: 7

auto_disqualifiers:
  - id: BASE_TOO_SHORT
    condition: "base_days < 15"
  - id: NO_VOLUME_CONFIRMATION
    condition: "breakout_volume_ratio < 1.5"
  - id: EXTENDED_FROM_BREAKOUT
    condition: "price > breakout_level * 1.03"
  - id: EARNINGS_WITHIN_7D
    condition: "earnings_date within 7 days"

scoring_weights:
  technical_setup: 25
  volume_pattern: 20
  sector_momentum: 15
  fundamental_quality: 15
  catalyst: 10
  price_range: 15

grade_thresholds:
  aplus: 50
  a: 42
  b: 35
  c: 28

minimum_evidence:
  required:
    - price_data
    - base_duration
    - volume_pattern
    - breakout_level
    - stop_below_base
    - trade_plan
  preferred:
    - sector_rank
    - institutional_activity
    - options_activity

agent_responsibilities:
  maria: "Verify fundamental quality and news flow."
  risk: "Verify base structure, breakout level, stop placement."
  steph: "Verify account fit and position sizing for multi-day hold."

paper_trade_rules:
  chart_review_required: true
  max_hold_days: 21
  auto_exit_at_max_hold: true

live_trade_rules:
  max_dollar_risk: 200
  max_hold_days: 21
  ira_max_risk: 500

outcome_learning_fields:
  - base_duration
  - base_tightness
  - breakout_volume_ratio
  - sector_rank
  - hold_duration
  - max_favorable_excursion
```

### swing_trade
**File:** swing_trade.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: swing_trade
display_name: Swing Trade
version: "1.0.0"
status: UNVALIDATED
purpose: "Breakout continuation trades in confirmed uptrends. Any market cap, multi-day hold with trend-following exits."

eligible_accounts: [taxable, rollover_ira, roth_ira]
timeframe: swing_3_to_21d
timeframe_class: SHORT_SWING

universe:
  price:
    min: 5.00
    max: 500.00
  float_m:
    max: null
  rvol:
    min: 1.2

entry_criteria:
  - id: TREND_CONFIRMED
    description: "Price above 20-day and 50-day SMA with rising slope"
    metric: trend_confirmation
    operator: eq
    value: true
  - id: BREAKOUT_LEVEL
    description: "Price breaking above prior swing high or consolidation resistance"
    metric: breakout_vs_resistance
    operator: gte
    value: 1.0
  - id: VOLUME_EXPANSION
    description: "Breakout day volume at least 1.2x 20-day average"
    metric: rvol
    operator: gte
    value: 1.2
  - id: SECTOR_SUPPORT
    description: "Sector relative strength positive vs SPY over 5 days"
    metric: sector_rs_5d
    operator: gte
    value: 0.0

auto_disqualifiers:
  - id: DOWNTREND
    description: "Price below 50-day SMA"
  - id: EARNINGS_WITHIN_5D
    description: "Earnings announcement within 5 trading days"
  - id: EXTENDED_ENTRY
    description: "Price more than 5% above breakout level"
  - id: NO_STOP_DEFINED
    description: "Trade plan lacks a defined stop loss"

exit_rules:
  stop_method: atr_based
  target_method: trailing

risk:
  risk_per_trade_pct: 0.005
  max_position_size: 5000
  max_daily_trades: 3
  target_rr: 2.5

scoring:
  min_score_go: 42
  min_score_wait: 28

lifecycle:
  proposal_expiry_hours: 168
  overnight_allowed: true
  max_hold_days: 21

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify trend strength, catalyst presence, and sector alignment."
  risk: "Validate stop placement relative to ATR and breakout structure."
  steph: "Confirm position sizing, account eligibility, and portfolio concentration."

co_enables:
  promotes_to: [swing_breakout]
  strengthens: [speculative_growth, sector_rotation]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Swing trade strategy targeting breakout continuation in confirmed uptrends. Holds 3-21 days with ATR-based stops and trailing targets. Suitable for any market cap with volume confirmation."
  key_questions:
    - "Is the trend confirmed on daily and weekly timeframes?"
    - "Does volume support the breakout or is it suspect?"
    - "Are there any earnings or macro events that could disrupt the hold period?"

screen_filters:
  min_price: 5.00
  max_price: 200.00
  min_rvol: 1.5
  max_float_m: 500
  min_score: 35
```

### tax_loss_harvest
**File:** tax_loss_harvest.yaml
**Issues:** 5
  - MISSING: max_hold_days
  - MISSING: technical_indicators_required
  - MISSING: vix_rules
  - MISSING: risk_parameters
  - MISSING: performance_context

```yaml
strategy_id: tax_loss_harvest
display_name: Tax Loss Harvest
version: "1.0.0"
status: UNVALIDATED
purpose: "Harvest realized losses in taxable accounts for tax efficiency. Sell losing positions and replace with correlated but non-substantially-identical substitutes."

eligible_accounts: [taxable]
timeframe: swing_3_to_21d
timeframe_class: SHORT_SWING

universe:
  price:
    min: 1.00
    max: null
  float_m:
    max: null
  rvol:
    min: null

entry_criteria:
  - id: UNREALIZED_LOSS
    description: "Position has unrealized loss exceeding $200 or 5% of cost basis"
    metric: unrealized_loss_pct
    operator: lte
    value: -0.05
  - id: HARVEST_BENEFIT
    description: "Estimated tax benefit exceeds transaction costs by at least 3x"
    metric: tax_benefit_ratio
    operator: gte
    value: 3.0
  - id: SUBSTITUTE_AVAILABLE
    description: "Non-substantially-identical substitute available for replacement"
    metric: substitute_available
    operator: eq
    value: true
  - id: NO_WASH_SALE_CONFLICT
    description: "No purchase of substantially identical security in 30-day window"
    metric: wash_sale_clear
    operator: eq
    value: true

auto_disqualifiers:
  - id: WASH_SALE_WINDOW
    description: "Substantially identical security purchased within 30-day window (before or after)"
  - id: IRA_ACCOUNT
    description: "Cannot harvest losses in tax-advantaged accounts"
  - id: LOSS_TOO_SMALL
    description: "Loss below $200 not worth transaction friction"
  - id: YEAR_END_WASH_RISK
    description: "Too close to year-end to complete 30-day wash sale window"

exit_rules:
  stop_method: fixed_pct
  target_method: level_based

risk:
  risk_per_trade_pct: 0.005
  max_position_size: 10000
  max_daily_trades: null
  target_rr: 1.0

scoring:
  min_score_go: 35
  min_score_wait: 20

lifecycle:
  proposal_expiry_hours: 168
  overnight_allowed: true
  max_hold_days: 31

execution:
  paper_allowed: true
  live_allowed: false

agent_responsibilities:
  maria: "Verify thesis on original position - is the loss permanent or temporary?"
  risk: "Validate wash sale compliance across all accounts and 61-day window."
  steph: "Calculate tax benefit, confirm substitute selection, and track harvest budget YTD."

co_enables:
  promotes_to: []
  strengthens: [core_index, core_growth_compounder]

validation_gate:
  min_closed_paper_trades: 30
  min_win_rate: 0.55
  min_profit_factor: 1.3
  min_calendar_months: 6
  human_approval_required: true

prompt_context:
  summary: "Tax loss harvesting strategy for taxable accounts. Sells losing positions to realize losses for tax efficiency and replaces with non-substantially-identical substitutes. Strict wash sale compliance across all accounts."
  key_questions:
    - "Is the loss likely permanent or is this a temporary drawdown worth holding?"
    - "Is there a suitable non-substantially-identical substitute to maintain market exposure?"
    - "Are there any wash sale conflicts across taxable, IRA, or Roth accounts?"

screen_filters:
  min_price: 1.00
  max_price: 5000.00
  max_pct_from_cost_basis: -5
  requires_unrealized_loss: true
  requires_existing_position: true
  account_types: [taxable]
  min_holding_days: 31
  min_score: 0
```
