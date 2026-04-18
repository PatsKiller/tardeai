"""portfolio_tax_projection.py — Tax Projection Engine
Tracks YTD conversions, projects annual tax bill, calculates remaining
Roth capacity, wash sale scanner, IRMAA projection, quarterly payment calc.
Specific to John's situation: SSDI + Schedule C + MFS lived-apart.
"""
from __future__ import annotations
import json
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 2026 Tax Constants (MFS lived-apart) ──────────────────────────────────────
BRACKETS_2026_MFS = [
    (0,       11_925,  0.10),
    (11_925,  47_150,  0.12),
    (47_150,  100_525, 0.22),
    (100_525, 191_950, 0.24),
    (191_950, 243_725, 0.32),
    (243_725, 365_600, 0.35),
    (365_600, float('inf'), 0.37),
]
# IRMAA thresholds 2026 MFS (estimated — MFS threshold is ~$103K)
IRMAA_TIERS_MFS = [
    (103_000, 0),       # Under threshold: standard Part B
    (129_000, 69.90),   # Tier 1 surcharge/month
    (161_000, 174.70),
    (193_000, 279.50),
    (750_000, 384.30),
    (float('inf'), 419.30),
]
STANDARD_DEDUCTION_MFS_2026 = 15_000
SSDI_MONTHLY = 3_800
SCHEDULE_C_ANNUAL_GROSS = 20_000

def _tax_on_income(taxable: float, brackets=BRACKETS_2026_MFS) -> float:
    tax = 0.0
    for low, high, rate in brackets:
        if taxable <= low: break
        tax += (min(taxable, high) - low) * rate
    return round(tax, 2)

def _irmaa_surcharge(magi: float) -> Tuple[float, str]:
    monthly = 0.0
    tier = "Standard"
    for threshold, surcharge in IRMAA_TIERS_MFS:
        if magi < threshold:
            break
        monthly = surcharge
        if surcharge > 0:
            tier = f"Tier {IRMAA_TIERS_MFS.index((threshold, surcharge))}"
    annual = round(monthly * 12, 2)
    return annual, tier

def _ssdi_taxable(other_income: float) -> float:
    """85% of SSDI is taxable when combined income > $25K (MFS threshold lower)."""
    annual_ssdi = SSDI_MONTHLY * 12
    # MFS: if any SS received, up to 85% taxable regardless (harsh rule for MFS)
    return round(annual_ssdi * 0.85, 2)

def calculate_tax_projection(
    ytd_conversions: float = 35_000,
    planned_additional_conversion: float = 0,
    ytd_schedule_c_net: float = 0,
    ytd_investment_gains: float = 0,
    state_dir: Optional[Path] = None,
) -> Dict:
    """
    Full 2026 tax projection for John's MFS lived-apart situation.
    Returns bracket analysis, IRMAA exposure, quarterly payments, what-if scenarios.
    """
    today = datetime.now()
    months_elapsed = today.month
    months_remaining = 12 - today.month

    # ── Income Sources ────────────────────────────────────────────────────────
    ssdi_annual     = SSDI_MONTHLY * 12          # $45,600
    ssdi_taxable    = _ssdi_taxable(0)            # $38,760 (85%)
    schedule_c_net  = ytd_schedule_c_net or round(SCHEDULE_C_ANNUAL_GROSS * 0.70, 0)  # ~$14K net
    total_conversions = ytd_conversions + planned_additional_conversion
    investment_gains  = ytd_investment_gains

    # ── Itemized Deductions ───────────────────────────────────────────────────
    mortgage_interest = 16_011
    property_tax      = 7_670
    itemized          = mortgage_interest + property_tax  # $23,681
    # Use itemized if > standard deduction
    deduction         = max(itemized, STANDARD_DEDUCTION_MFS_2026)

    # ── AGI and Taxable Income ────────────────────────────────────────────────
    agi = ssdi_taxable + schedule_c_net + total_conversions + investment_gains
    taxable_income = max(0, agi - deduction)

    # ── Federal Tax ───────────────────────────────────────────────────────────
    federal_tax = _tax_on_income(taxable_income)

    # ── Effective Bracket ─────────────────────────────────────────────────────
    current_bracket = 0.10
    for low, high, rate in BRACKETS_2026_MFS:
        if taxable_income > low:
            current_bracket = rate
    next_bracket = None
    for i, (low, high, rate) in enumerate(BRACKETS_2026_MFS):
        if taxable_income <= high and taxable_income > low:
            if i + 1 < len(BRACKETS_2026_MFS):
                next_bracket = BRACKETS_2026_MFS[i+1][2]
                capacity_in_bracket = round(high - taxable_income, 2)
            break

    # ── IRMAA ─────────────────────────────────────────────────────────────────
    magi = agi  # simplified
    irmaa_annual, irmaa_tier = _irmaa_surcharge(magi)

    # ── Roth Conversion Analysis ──────────────────────────────────────────────
    # How much MORE can be converted while staying in current bracket
    remaining_capacity = max(0, capacity_in_bracket) if 'capacity_in_bracket' in dir() else 0

    # Optimal annual conversion (stay in 22% bracket)
    bracket_22_limit = 100_525  # MFS 22% tops out here
    income_before_conversion = ssdi_taxable + schedule_c_net
    max_in_22_pct = max(0, bracket_22_limit + deduction - income_before_conversion)
    optimal_conversion = round(min(max_in_22_pct, 35_000), 0)  # cap at $35K practical

    # Tax cost scenarios
    scenarios = []
    for conv in [0, 10_000, 25_000, 35_000, 50_000, 75_000]:
        ti = max(0, ssdi_taxable + schedule_c_net + conv - deduction)
        tax = _tax_on_income(ti)
        magi_s = ssdi_taxable + schedule_c_net + conv
        irmaa_s, _ = _irmaa_surcharge(magi_s)
        scenarios.append({
            "conversion":       conv,
            "taxable_income":   ti,
            "federal_tax":      tax,
            "effective_rate":   round(tax/ti*100, 1) if ti > 0 else 0,
            "irmaa_annual":     irmaa_s,
            "total_cost":       round(tax + irmaa_s, 0),
        })

    # ── Quarterly Estimated Tax Payments ─────────────────────────────────────
    total_annual_tax = federal_tax + irmaa_annual
    prior_year_safe_harbor = total_annual_tax * 1.10  # safe harbor: 110% of prior
    quarterly_payment = round(prior_year_safe_harbor / 4, 0)

    year = today.year
    quarterly_dates = [
        {"period": "Q1", "due": f"{year}-04-15", "amount": quarterly_payment,
         "days_until": (_d(f"{year}-04-15") - today.date()).days},
        {"period": "Q2", "due": f"{year}-06-15", "amount": quarterly_payment,
         "days_until": (_d(f"{year}-06-15") - today.date()).days},
        {"period": "Q3", "due": f"{year}-09-15", "amount": quarterly_payment,
         "days_until": (_d(f"{year}-09-15") - today.date()).days},
        {"period": "Q4", "due": f"{year+1}-01-15","amount": quarterly_payment,
         "days_until": (_d(f"{year+1}-01-15") - today.date()).days},
    ]
    next_payment = next((q for q in quarterly_dates if q["days_until"] > 0), None)

    # ── NY State Tax (estimated) ──────────────────────────────────────────────
    # NY has 6.85% rate for MFS at ~$65K-$215K bracket
    ny_rate = 0.0685
    ny_tax = round(taxable_income * ny_rate * 0.85, 2)  # approximate with partial SSDI exclusion
    nyc_tax = round(taxable_income * 0.03078, 2)  # NYC resident tax

    # ── Save projection ───────────────────────────────────────────────────────
    result = {
        "as_of":                today.strftime("%Y-%m-%d"),
        "tax_year":             today.year,
        "income": {
            "ssdi_annual":      ssdi_annual,
            "ssdi_taxable":     ssdi_taxable,
            "schedule_c_net":   schedule_c_net,
            "ytd_conversions":  ytd_conversions,
            "planned_additional": planned_additional_conversion,
            "total_conversions":total_conversions,
            "investment_gains": investment_gains,
        },
        "deductions": {
            "mortgage_interest":mortgage_interest,
            "property_tax":     property_tax,
            "total_itemized":   itemized,
            "standard":         STANDARD_DEDUCTION_MFS_2026,
            "deduction_used":   deduction,
        },
        "tax": {
            "agi":              round(agi, 0),
            "taxable_income":   round(taxable_income, 0),
            "federal_tax":      federal_tax,
            "current_bracket":  f"{current_bracket*100:.0f}%",
            "next_bracket":     f"{next_bracket*100:.0f}%" if next_bracket else "N/A",
            "remaining_in_bracket": remaining_capacity if 'capacity_in_bracket' in dir() else 0,
            "effective_rate":   round(federal_tax/taxable_income*100, 1) if taxable_income else 0,
            "ny_state_est":     ny_tax,
            "nyc_est":          nyc_tax,
            "total_est":        round(federal_tax + ny_tax + nyc_tax, 0),
        },
        "irmaa": {
            "magi":             round(magi, 0),
            "annual_surcharge": irmaa_annual,
            "tier":             irmaa_tier,
            "threshold":        103_000,
            "exposure":         magi > 103_000,
        },
        "roth": {
            "ytd_conversions":  ytd_conversions,
            "remaining_capacity": remaining_capacity if 'capacity_in_bracket' in dir() else 0,
            "optimal_annual":   optimal_conversion,
            "golden_window_age":68.5,
            "recommendation":   f"Convert ${optimal_conversion:,.0f} more to stay in {current_bracket*100:.0f}% bracket",
        },
        "quarterly_payments":   quarterly_dates,
        "next_payment":         next_payment,
        "scenarios":            scenarios,
    }

    if state_dir:
        (state_dir/"tax_projection.json").write_text(json.dumps(result, indent=2, default=str))

    return result

def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

def load_tax_projection(state_dir: Path) -> Dict:
    p = state_dir/"tax_projection.json"
    if p.exists():
        try: return json.loads(p.read_text())
        except: pass
    return calculate_tax_projection(state_dir=state_dir)
