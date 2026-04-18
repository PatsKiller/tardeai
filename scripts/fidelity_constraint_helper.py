"""
fidelity_constraint_helper.py
==============================
Helper module for portfolio_ai_analyst.py and portfolio_rebalancer.py.
Reads fidelity_available_funds and fidelity_401k_constraints from
portfolio_accounts.yaml and returns formatted constraint text for injection
into AI analyst prompts.

Usage:
    from fidelity_constraint_helper import get_fidelity_constraint_block
    constraint_text = get_fidelity_constraint_block(root)
    # Inject into AI prompt before asking for 401k recommendations
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import yaml


def _load_yaml(root: Path) -> Dict:
    p = root / "assets" / "portfolio_accounts.yaml"
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def get_fidelity_constraint_block(root: Path) -> str:
    """
    Returns a formatted constraint block for injection into AI analyst prompts.
    Includes: constraint status, available fund universe, performance, preferences.

    Returns empty string if constraint_active is False (post-rollover).

    Example output injected into AI prompt:
        ⚠️ FIDELITY 401K CONSTRAINT — ACTIVE UNTIL 2027 ROLLOVER
        The Fidelity 401k (Omnicom) is a CLOSED-UNIVERSE PLAN.
        ALL recommendations for this account MUST use ONLY these funds:
        ...
    """
    data = _load_yaml(root)
    constraints = data.get("fidelity_401k_constraints", {})

    if not constraints.get("constraint_active", False):
        return ""

    funds: List[Dict] = data.get("fidelity_available_funds", [])
    if not funds:
        return ""

    rollover_date = constraints.get("rollover_target_date", "2027")
    preferred     = constraints.get("preferred_for_rebalance", [])
    avoid         = constraints.get("avoid_for_rebalance", [])
    pre_strategy  = constraints.get("pre_rollover_strategy", "")

    # Build fund table
    fund_lines = []
    for f in funds:
        if f.get("current_value", 0) == 0 and f["internal_code"] not in preferred:
            continue  # Only show currently held + preferred for brevity
        line = (
            f"  {f['internal_code']:15} | {f['name']:25} | "
            f"Cat: {f['category']:20} | "
            f"1yr:{f.get('perf_1yr',0):+.1f}% | "
            f"ER:{f.get('expense_ratio','?')}% | "
            f"{'⭐ PREFERRED' if f['internal_code'] in preferred else ''}"
            f"{'⚠️ AVOID' if f['internal_code'] in avoid else ''}"
        )
        fund_lines.append(line)

    # Add bond options (not currently held but available)
    for f in funds:
        if f["asset_class"] == "Bond/Managed Income" and f["internal_code"] not in [x["internal_code"] for x in funds if x.get("current_value",0) > 0]:
            line = (
                f"  {f['internal_code']:15} | {f['name']:25} | "
                f"Cat: {f['category']:20} | "
                f"1yr:{f.get('perf_1yr',0):+.1f}% | "
                f"ER:{f.get('expense_ratio','?')}% | "
                f"{'⭐ PREFERRED' if f['internal_code'] in preferred else ''}(not held, available)"
            )
            if line not in fund_lines:
                fund_lines.append(line)

    block = f"""
⚠️ FIDELITY 401K CONSTRAINT — ACTIVE UNTIL {rollover_date} ROLLOVER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The Fidelity 401k (Omnicom, ~$503K) is a CLOSED-UNIVERSE PLAN.
ALL recommendations for this account MUST use ONLY these funds via
Fidelity NetBenefits 'Exchange' function. DO NOT suggest ETFs (BND,
VXUS, JEPI, etc.) or individual stocks for this account.

AVAILABLE FUNDS:
{chr(10).join(fund_lines)}

AVOID: {', '.join(avoid)} (poor performance or concentration risk)
PRE-ROLLOVER STRATEGY: {pre_strategy.strip()}

After {rollover_date} rollover to Schwab Rollover IRA → full universe opens.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return block


def get_fidelity_rebalance_options(root: Path, category: str) -> List[Dict]:
    """
    Returns available fund options for a given allocation category.
    Used by portfolio_rebalancer.py to generate constrained buy/sell suggestions.

    Args:
        category: 'us_large_blend', 'us_large_growth', 'international', 'bonds', etc.

    Returns list of matching funds with name, ticker, perf, cost.
    """
    data = _load_yaml(root)
    funds = data.get("fidelity_available_funds", [])
    constraints = data.get("fidelity_401k_constraints", {})

    if not constraints.get("constraint_active", False):
        return []

    # Category mapping from target_allocation keys to fund categories
    CAT_MAP = {
        "us_large_blend":  ["Large Blend"],
        "us_large_growth": ["Large Growth"],
        "us_large_value":  ["Large Value"],
        "us_small":        ["Small Blend", "Small Growth", "Small Value"],
        "international":   ["Foreign"],
        "bonds":           ["Intermediate-Term Bond", "Stable Value"],
    }

    target_cats = CAT_MAP.get(category, [category])
    avoid = constraints.get("avoid_for_rebalance", [])
    preferred = constraints.get("preferred_for_rebalance", [])

    results = []
    for f in funds:
        if f["category"] in target_cats and f["internal_code"] not in avoid:
            results.append({
                "internal_code": f["internal_code"],
                "name":          f["name"],
                "real_ticker":   f.get("real_ticker"),
                "category":      f["category"],
                "expense_ratio": f.get("expense_ratio"),
                "perf_1yr":      f.get("perf_1yr", 0),
                "perf_3yr":      f.get("perf_3yr", 0),
                "is_preferred":  f["internal_code"] in preferred,
                "notes":         f.get("notes", ""),
            })

    # Sort: preferred first, then by 1yr performance
    results.sort(key=lambda x: (not x["is_preferred"], -x.get("perf_1yr", 0)))
    return results


if __name__ == "__main__":
    # Test
    from pathlib import Path
    root = Path(".")
    print(get_fidelity_constraint_block(root))
    print("\nOptions for 'international':")
    for f in get_fidelity_rebalance_options(root, "international"):
        print(f"  {f['internal_code']} — {f['name']} — {f['perf_1yr']:+.1f}%/1yr — preferred:{f['is_preferred']}")
