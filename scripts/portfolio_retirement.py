"""portfolio_retirement.py — Retirement Roadmap & Wealth Timeline
Wealth projection ages 58-80, Roth ladder, income floor, Golden Window,
401k loan tracker, quarterly tax reminders.
"""
from __future__ import annotations
import json
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List

DOB = date(1967, 8, 21)
SSDI_MONTHLY   = 3_800
DISABILITY_END_AGE = 68.5
FRA_AGE        = 67.0
RMD_AGE        = 73
LOAN_BALANCE   = 21_735
LOAN_ROLLOVER_DEADLINE = date(2027, 12, 31)
MORTGAGE_BALANCE = 408_347
MORTGAGE_RATE    = 0.04
MORTGAGE_MATURITY = date(2042, 1, 1)

def _age(on_date=None):
    d = on_date or date.today()
    return (d - DOB).days / 365.25

def _date_at_age(target_age):
    days = int(target_age * 365.25)
    return date(DOB.year, DOB.month, DOB.day) + __import__("datetime").timedelta(days=days)

def _project_wealth(
    current_value: float,
    annual_contribution: float,
    annual_return: float,
    years: int,
) -> List[float]:
    vals = [current_value]
    for _ in range(years):
        vals.append(vals[-1] * (1 + annual_return) + annual_contribution)
    return [round(v, 0) for v in vals]

def build_retirement_roadmap(portfolio: Dict, state_dir: Path) -> Dict:
    today = date.today()
    current_age = _age()

    # Portfolio totals — use account_summaries dict + portfolio_totals
    totals = portfolio.get("portfolio_totals", {})
    total  = totals.get("total_value", 0) or portfolio.get("total_value", 0) or 0
    summaries = portfolio.get("account_summaries", {})

    roth = sum(
        v.get("total_value", 0) for k, v in summaries.items()
        if "roth" in k.lower() or "roth" in v.get("account_type","").lower()
    )
    traditional = sum(
        v.get("total_value", 0) for k, v in summaries.items()
        if any(x in k.lower() or x in v.get("account_type","").lower()
               for x in ["rollover","401k","ira","traditional"])
        and "roth" not in k.lower() and "roth" not in v.get("account_type","").lower()
    )
    taxable = sum(
        v.get("total_value", 0) for k, v in summaries.items()
        if any(x in k.lower() or x in v.get("account_type","").lower()
               for x in ["individual","taxable","brokerage"])
    )

    # Key dates
    date_fra        = _date_at_age(FRA_AGE)
    date_disability_end = _date_at_age(DISABILITY_END_AGE)
    date_golden_start   = _date_at_age(DISABILITY_END_AGE)
    date_golden_end     = _date_at_age(RMD_AGE)
    date_rmd        = _date_at_age(RMD_AGE)

    days_to_golden = (date_golden_start - today).days
    years_to_golden = round(days_to_golden / 365.25, 1)

    # 401k loan payoff
    days_to_loan_deadline = (LOAN_ROLLOVER_DEADLINE - today).days
    monthly_to_payoff = round(LOAN_BALANCE / max(1, days_to_loan_deadline/30), 0)

    # Wealth timeline (3 scenarios)
    years_to_model = 80 - int(current_age)
    annual_contrib = 7_000   # Roth IRA max 2026

    conservative = _project_wealth(total, annual_contrib, 0.05, years_to_model)
    base         = _project_wealth(total, annual_contrib, 0.07, years_to_model)
    aggressive   = _project_wealth(total, annual_contrib, 0.09, years_to_model)

    # Build timeline with age labels
    timeline = []
    for i, yr in enumerate(range(int(current_age), 81)):
        d = _date_at_age(yr)
        milestone = ""
        if abs(yr - FRA_AGE) < 1:        milestone = "SS Retirement @ FRA"
        if abs(yr - DISABILITY_END_AGE) < 1: milestone = "🟡 Golden Window Opens — Disability Ends"
        if abs(yr - RMD_AGE) < 1:        milestone = "RMD Age — Complete Roth Conversion"
        if yr == 59:                      milestone = "Age 59 — No Early Withdrawal Penalty"
        timeline.append({
            "age": yr, "year": d.year,
            "conservative": conservative[i] if i < len(conservative) else 0,
            "base":         base[i]         if i < len(base)         else 0,
            "aggressive":   aggressive[i]   if i < len(aggressive)   else 0,
            "milestone":    milestone,
        })

    # Roth conversion ladder
    current_roth_bal = roth
    annual_conversion = 25_000
    roth_projections = []
    bal = current_roth_bal
    for yr_offset in range(int(years_to_golden) + 6):
        yr = today.year + yr_offset
        age_then = current_age + yr_offset
        is_golden = DISABILITY_END_AGE <= age_then < RMD_AGE
        conv_this_year = annual_conversion if not is_golden else 50_000  # larger in golden window
        growth = bal * 0.07
        bal += growth + conv_this_year
        roth_projections.append({
            "year":       yr,
            "age":        round(age_then, 1),
            "conversion": conv_this_year,
            "balance":    round(bal, 0),
            "golden":     is_golden,
        })

    # Income floor analysis
    monthly_portfolio_income = round(total * 0.04 / 12, 0)  # 4% SWR
    schd_income_monthly = round(total * 0.026 / 12, 0)       # SCHD yield
    ss_monthly_at_fra   = SSDI_MONTHLY  # converts 1:1

    # At disability end (68.5): SS only + portfolio
    income_at_disability_end = {
        "ss_monthly":         ss_monthly_at_fra,
        "portfolio_4pct":     monthly_portfolio_income,
        "schd_dividends":     schd_income_monthly,
        "total_monthly":      round(ss_monthly_at_fra + monthly_portfolio_income, 0),
        "vs_current_disability": round(ss_monthly_at_fra + monthly_portfolio_income - SSDI_MONTHLY, 0),
    }

    result = {
        "as_of":              today.isoformat(),
        "current_age":        round(current_age, 1),
        "key_dates": {
            "fra":               str(date_fra),
            "disability_end":    str(date_disability_end),
            "golden_window_start": str(date_golden_start),
            "golden_window_end": str(date_golden_end),
            "rmd_age":           str(date_rmd),
            "days_to_golden":    days_to_golden,
            "years_to_golden":   years_to_golden,
            "loan_deadline":     str(LOAN_ROLLOVER_DEADLINE),
            "days_to_loan_deadline": days_to_loan_deadline,
        },
        "accounts": {
            "total":      round(total, 0),
            "roth":       round(roth, 0),
            "traditional":round(traditional, 0),
            "taxable":    round(taxable, 0),
            "roth_pct":   round(roth/total*100, 1) if total else 0,
        },
        "loan": {
            "balance":              LOAN_BALANCE,
            "deadline":             str(LOAN_ROLLOVER_DEADLINE),
            "days_remaining":       days_to_loan_deadline,
            "monthly_to_payoff":    monthly_to_payoff,
            "urgent":               days_to_loan_deadline < 365,
        },
        "mortgage": {
            "balance":  MORTGAGE_BALANCE,
            "rate":     MORTGAGE_RATE,
            "maturity": str(MORTGAGE_MATURITY),
        },
        "timeline":           timeline,
        "roth_ladder":        roth_projections,
        "income_floor":       income_at_disability_end,
        "golden_window": {
            "start_age":          DISABILITY_END_AGE,
            "end_age":            RMD_AGE,
            "years_available":    RMD_AGE - DISABILITY_END_AGE,
            "optimal_annual_conversion": 50_000,
            "projected_roth_at_start": roth_projections[int(years_to_golden)]["balance"] if int(years_to_golden) < len(roth_projections) else 0,
        },
    }

    (state_dir/"retirement_roadmap.json").write_text(json.dumps(result, indent=2, default=str))
    return result
