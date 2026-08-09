# Operator Investment Policy Statement (IPS) Template

**Date:** 2026-08-08
**Phase:** P2.1 Operator Profile + Financial Context
**Status:** TEMPLATE — awaiting operator values

---

## Purpose

This template defines the required fields for an operator's Investment Policy Statement (IPS) and associated financial context. All values must be provided by the operator, stored in the authoritative `cio_operator_profile.py` event store, and explicitly confirmed by the operator before they can support material financial advice.

**No values in this template are filled in.** The operator must provide actual values through the profile service.

---

## 1. Investment Policy Statement Core

### Objectives

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| primary_objective | string | "Long-term growth with income generation" | [TO BE PROVIDED] |
| secondary_objectives | list[string] | ["Capital preservation", "Tax efficiency"] | [TO BE PROVIDED] |
| benchmark_index | string | "S&P 500 Total Return" | [TO BE PROVIDED] |
| target_return_annual | float | 7.0 | [TO BE PROVIDED] |
| target_return_timeframe_years | int | 10 | [TO BE PROVIDED] |

### Risk Tolerance

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| risk_tolerance_level | enum | "MODERATE" / "MODERATE_AGGRESSIVE" / "AGGRESSIVE" / "CONSERVATIVE" | [TO BE PROVIDED] |
| max_acceptable_drawdown_pct | float | 25.0 | [TO BE PROVIDED] |
| max_acceptable_annual_loss_pct | float | 15.0 | [TO BE PROVIDED] |
| risk_capacity_assessment | string | "Moderate capacity — stable income, 20+ year horizon" | [TO BE PROVIDED] |
| willingness_vs_capacity_gap | string | "None — aligned" | [TO BE PROVIDED] |

### Liquidity Requirements

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| emergency_fund_months | int | 6 | [TO BE PROVIDED] |
| emergency_fund_target_usd | float | 50000.00 | [TO BE PROVIDED] |
| near_term_expenses_next_12mo_usd | float | 20000.00 | [TO BE PROVIDED] |
| near_term_expenses_next_36mo_usd | float | 60000.00 | [TO BE PROVIDED] |
| cash_buffer_min_pct | float | 2.0 | [TO BE PROVIDED] |

### Time Horizon

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| target_retirement_age | int | 65 | [TO BE PROVIDED] |
| current_age | int | 45 | [TO BE PROVIDED] |
| accumulation_phase_years | int | 20 | [TO BE PROVIDED] |
| distribution_phase_years | int | 30 | [TO BE PROVIDED] |
| risk_glide_path | string | "Aggressive until 55, moderate 55-65, conservative 65+" | [TO BE PROVIDED] |

### Tax Considerations

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| filing_status | enum | "SINGLE" / "MARRIED_JOINT" / "HEAD_OF_HOUSEHOLD" | [TO BE PROVIDED] |
| federal_marginal_rate_pct | float | 24.0 | [TO BE PROVIDED] |
| state_marginal_rate_pct | float | 6.0 | [TO BE PROVIDED] |
| state_of_residence | string | "NY" | [TO BE PROVIDED] |
| irmaa_threshold_concern | bool | false | [TO BE PROVIDED] |
| tax_loss_harvesting_enabled | bool | true | [TO BE PROVIDED] |
| municipal_bond_preference | bool | false | [TO BE PROVIDED] |

### Account Constraints

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| taxable_accounts | list[object] | [{"type":"brokerage","name":"Individual"}] | [TO BE PROVIDED] |
| ira_accounts | list[object] | [{"type":"traditional_ira","name":"Rollover IRA"}] | [TO BE PROVIDED] |
| roth_accounts | list[object] | [{"type":"roth_ira","name":"Roth IRA"}] | [TO BE PROVIDED] |
| hsa_accounts | list[object] | [] | [TO BE PROVIDED] |
| employer_plan_accounts | list[object] | [{"type":"401k","name":"Employer 401k"}] | [TO BE PROVIDED] |
| ira_contribution_limit_current_year | float | 7000.00 | [TO BE PROVIDED] |
| 401k_contribution_limit_current_year | float | 23000.00 | [TO BE PROVIDED] |
| catch_up_eligible | bool | false | [TO BE PROVIDED] |

### Concentration Constraints

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| max_single_position_pct | float | 10.0 | [TO BE PROVIDED] |
| max_sector_pct | float | 30.0 | [TO BE PROVIDED] |
| max_single_asset_class_pct | float | 60.0 | [TO BE PROVIDED] |
| max_employer_stock_pct | float | 5.0 | [TO BE PROVIDED] |
| restricted_securities | list[string] | ["Employer stock above 5%"] | [TO BE PROVIDED] |

### Income Requirements

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| annual_income_needed_retirement_usd | float | 80000.00 | [TO BE PROVIDED] |
| social_security_expected_monthly | float | 2500.00 | [TO BE PROVIDED] |
| social_security_claim_age | int | 67 | [TO BE PROVIDED] |
| pension_monthly | float | 0.00 | [TO BE PROVIDED] |
| other_income_sources | list[object] | [] | [TO BE PROVIDED] |
| rmd_start_age | int | 73 | [TO BE PROVIDED] |

### Rebalancing Policy

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| rebalancing_frequency | enum | "QUARTERLY" / "SEMI_ANNUAL" / "ANNUAL" / "THRESHOLD" | [TO BE PROVIDED] |
| rebalancing_threshold_pct | float | 5.0 | [TO BE PROVIDED] |
| tax_aware_rebalancing | bool | true | [TO BE PROVIDED] |
| cash_flow_rebalancing | bool | true | [TO BE PROVIDED] |

---

## 2. Goals

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| short_term_goals | list[object] | [{"name":"Home down payment","amount":100000,"target_date":"2027-06-01"}] | [TO BE PROVIDED] |
| medium_term_goals | list[object] | [{"name":"College fund","amount":200000,"target_date":"2030-09-01"}] | [TO BE PROVIDED] |
| long_term_goals | list[object] | [{"name":"Retirement","amount":2000000,"target_date":"2040-01-01"}] | [TO BE PROVIDED] |

---

## 3. Prohibited and Restricted Actions

| Category | Items | Operator Value |
|----------|-------|---------------|
| prohibited_actions | Securities, strategies, or actions that are NEVER allowed | [TO BE PROVIDED] |
| restricted_actions | Actions requiring explicit operator pre-approval | [TO BE PROVIDED] |

---

## 4. Review and Maintenance

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| review_cadence | enum | "QUARTERLY" / "SEMI_ANNUAL" / "ANNUAL" | [TO BE PROVIDED] |
| next_review_date | date | "2026-10-01" | [TO BE PROVIDED] |
| trigger_review_events | list[string] | ["5% portfolio drop", "Job change", "Tax law change"] | [TO BE PROVIDED] |

---

## 5. Communication Preferences

| Field | Type | Example | Operator Value |
|-------|------|---------|---------------|
| primary_channel | enum | "TELEGRAM" | [TO BE PROVIDED] |
| notification_frequency | enum | "DAILY_MARKET" / "WEEKLY" / "ACTION_ONLY" | [TO BE PROVIDED] |
| preferred_format | enum | "MARKDOWN" / "PLAIN_TEXT" | [TO BE PROVIDED] |
| timezone | string | "America/New_York" | [TO BE PROVIDED] |

---

## 6. Document Metadata

| Field | Value |
|-------|-------|
| template_version | 1.0 |
| effective_date | [TO BE PROVIDED by operator] |
| operator_confirmation | PENDING |
| stored_in | data/cio/operator_profile.jsonl |
| service | scripts/lib/cio_operator_profile.py |

---

## How to Fill This Template

1. The operator provides values for each field
2. Values are written to `data/cio/operator_profile.jsonl` via `cio_operator_profile.py`
3. Each field starts with status UNVERIFIED
4. The operator explicitly confirms each field (or batch confirms)
5. Confirmed fields move to OPERATOR_CONFIRMED status
6. Only OPERATOR_CONFIRMED facts can support material financial advice

**Alex must reconstruct operator goals/constraints from `cio_operator_profile.py` on every material CIO run — never from OpenClaw MEMORY.md.**
