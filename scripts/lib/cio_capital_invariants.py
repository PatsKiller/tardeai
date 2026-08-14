"""cio_capital_invariants.py — G7 full ledger identities.

evaluate_capital_invariants(plan) emits one record per REQUIRED name:
  {name, lhs, rhs, residual, tolerance, pass}

Missing required operands => pass=False (never default True).

Does not size or mutate a plan. Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
CAPITAL_INVARIANTS_VERSION = "capital_invariants_1.0.0"
DEFAULT_TOLERANCE_USD = 0.02

REQUIRED_CAPITAL_INVARIANTS = [
    "sum_account_cash_eq_portfolio_cash",
    "sum_account_values_eq_portfolio_value",
    "earmark_le_settled_cash",
    "reserve_le_settled_cash",
    "free_investable_nonnegative",
    "prospective_raise_excludes_current_cash",
    "prospective_raise_excludes_earmarked_existing_cash",
    "prospective_raise_excludes_realized_historical_proceeds",
    "deploy_le_free_plus_prospective",
    "post_plan_cash_identity",
    "account_post_plan_rollup_eq_portfolio",
    "no_capital_source_double_count",
    "no_negative_account_cash",
    "authority_read_only_advisory",
]


def _opt_num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tol(rhs: Optional[float], floor: float = DEFAULT_TOLERANCE_USD) -> float:
    if rhs is None:
        return floor
    return max(floor, abs(rhs) * 0.0001)


def _rec(
    name: str,
    *,
    lhs: Any,
    rhs: Any,
    tolerance: float,
    passed: bool,
    residual: Optional[float] = None,
) -> dict[str, Any]:
    if residual is None:
        try:
            residual = float(lhs) - float(rhs)
        except (TypeError, ValueError):
            residual = None
    return {
        "name": name,
        "lhs": lhs,
        "rhs": rhs,
        "residual": None if residual is None else round(float(residual), 6),
        "tolerance": tolerance,
        "pass": bool(passed),
    }


def _fail_missing(name: str, *, lhs: Any = None, rhs: Any = None) -> dict[str, Any]:
    return _rec(name, lhs=lhs, rhs=rhs, residual=None, tolerance=DEFAULT_TOLERANCE_USD, passed=False)


def extract_capital_operands(plan: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Read-only operand map. Missing keys stay None (never invented)."""
    p = plan if isinstance(plan, dict) else {}
    src = p.get("capital_sources") if isinstance(p.get("capital_sources"), dict) else {}
    ledger = p.get("account_capital_ledger") if isinstance(p.get("account_capital_ledger"), dict) else {}
    cash_ledger = p.get("cash_ledger") if isinstance(p.get("cash_ledger"), dict) else {}
    agg = ledger.get("portfolio_aggregate") if isinstance(ledger.get("portfolio_aggregate"), dict) else {}
    accounts = ledger.get("accounts") if isinstance(ledger.get("accounts"), list) else None

    cash = _opt_num(p.get("cash_total_usd"))
    if cash is None:
        cash = _opt_num(agg.get("settled_cash_usd"))
    if cash is None:
        cash = _opt_num(cash_ledger.get("settled_cash_usd"))

    value = _opt_num(p.get("portfolio_value_usd"))
    if value is None:
        value = _opt_num(agg.get("portfolio_value_usd"))
    if value is None:
        value = _opt_num(cash_ledger.get("portfolio_value_usd"))

    reserve = _opt_num(p.get("cash_reserved_usd"))
    if reserve is None:
        reserve = _opt_num(agg.get("reserve_usd"))
    if reserve is None:
        reserve = _opt_num(cash_ledger.get("policy_reserve_usd"))

    investable = _opt_num(p.get("cash_investable_usd"))
    if investable is None:
        investable = _opt_num(cash_ledger.get("investable_usd"))

    earmark = _opt_num(p.get("cash_earmarked_redeploy_usd"))
    if earmark is None:
        earmark = _opt_num(src.get("earmarked_redeploy_usd"))
    if earmark is None:
        earmark = _opt_num(agg.get("earmarked_usd"))

    prospective = _opt_num(src.get("total_prospective_raise_usd"))
    if prospective is None:
        prospective = _opt_num(p.get("net_recommended_raise_usd"))
    if prospective is None:
        prospective = _opt_num(agg.get("prospective_raise_usd"))

    total_raise = _opt_num(src.get("total_raise_usd"))
    if total_raise is None:
        total_raise = _opt_num(p.get("net_recommended_raise_usd"))

    trims = _opt_num(src.get("trims_usd"))
    exits = _opt_num(src.get("exits_usd"))
    maturities = _opt_num(src.get("maturities_usd"))

    deploy = _opt_num(p.get("net_recommended_deploy_usd"))
    if deploy is None:
        deploy = _opt_num(agg.get("recommended_deploy_usd"))
    if deploy is None:
        deploy = _opt_num(cash_ledger.get("net_deploy_usd"))

    deployable = _opt_num(p.get("deployable_usd"))
    post = _opt_num(p.get("post_plan_cash_usd"))
    if post is None:
        post = _opt_num(agg.get("post_plan_cash_usd"))
    if post is None:
        post = _opt_num(cash_ledger.get("post_plan_cash_usd"))

    authority = p.get("authority")
    guard = src.get("double_count_guard")

    sum_acct_cash: Optional[float] = None
    sum_acct_value: Optional[float] = None
    sum_acct_post: Optional[float] = None
    min_acct_cash: Optional[float] = None
    if isinstance(accounts, list):
        sum_acct_cash = 0.0
        sum_acct_value = 0.0
        sum_acct_post = 0.0
        saw_cash = False
        for row in accounts:
            if not isinstance(row, dict):
                continue
            sc = _opt_num(row.get("settled_cash_usd"))
            mv = _opt_num(row.get("positions_mv_usd"))
            pc = _opt_num(row.get("post_plan_cash_usd"))
            if sc is not None:
                sum_acct_cash += sc
                saw_cash = True
                min_acct_cash = sc if min_acct_cash is None else min(min_acct_cash, sc)
            if sc is not None or mv is not None:
                sum_acct_value += (sc or 0.0) + (mv or 0.0)
            if pc is not None:
                sum_acct_post += pc
                min_acct_cash = pc if min_acct_cash is None else min(min_acct_cash, pc)
        if not saw_cash and not accounts:
            sum_acct_cash = 0.0
            sum_acct_value = 0.0
            sum_acct_post = 0.0

    return {
        "cash": cash,
        "portfolio_value": value,
        "reserve": reserve,
        "investable": investable,
        "earmark": earmark,
        "prospective": prospective,
        "total_raise": total_raise,
        "trims": trims,
        "exits": exits,
        "maturities": maturities,
        "deploy": deploy,
        "deployable": deployable,
        "post": post,
        "authority": authority,
        "double_count_guard": guard,
        "accounts": accounts,
        "sum_account_cash": sum_acct_cash,
        "sum_account_value": sum_acct_value,
        "sum_account_post": sum_acct_post,
        "min_account_cash": min_acct_cash,
        "has_sources": bool(src),
        "has_ledger": isinstance(ledger, dict) and bool(ledger),
    }


def _eval_one(name: str, op: dict[str, Any]) -> dict[str, Any]:
    cash = op["cash"]
    value = op["portfolio_value"]
    reserve = op["reserve"]
    investable = op["investable"]
    earmark = op["earmark"]
    prospective = op["prospective"]
    total_raise = op["total_raise"]
    trims = op["trims"]
    exits = op["exits"]
    maturities = op["maturities"]
    deploy = op["deploy"]
    deployable = op["deployable"]
    post = op["post"]

    if name == "sum_account_cash_eq_portfolio_cash":
        lhs, rhs = op["sum_account_cash"], cash
        if lhs is None or rhs is None:
            return _fail_missing(name, lhs=lhs, rhs=rhs)
        tol = _tol(rhs)
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=abs(lhs - rhs) <= tol)

    if name == "sum_account_values_eq_portfolio_value":
        lhs, rhs = op["sum_account_value"], value
        if lhs is None or rhs is None:
            return _fail_missing(name, lhs=lhs, rhs=rhs)
        tol = _tol(rhs, floor=1.0)
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=abs(lhs - rhs) <= tol)

    if name == "earmark_le_settled_cash":
        lhs, rhs = earmark, cash
        if lhs is None or rhs is None:
            return _fail_missing(name, lhs=lhs, rhs=rhs)
        tol = _tol(rhs)
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=lhs <= rhs + tol)

    if name == "reserve_le_settled_cash":
        lhs, rhs = reserve, cash
        if lhs is None or rhs is None:
            return _fail_missing(name, lhs=lhs, rhs=rhs)
        tol = _tol(rhs)
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=lhs <= rhs + tol)

    if name == "free_investable_nonnegative":
        lhs, rhs = investable, 0.0
        if lhs is None:
            return _fail_missing(name, lhs=lhs, rhs=rhs)
        tol = DEFAULT_TOLERANCE_USD
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=lhs >= -tol)

    if name == "prospective_raise_excludes_current_cash":
        if prospective is None or cash is None or trims is None or exits is None:
            return _fail_missing(name, lhs=prospective, rhs=None)
        expected = trims + exits
        raise_amt = total_raise if total_raise is not None else prospective
        includes_cash = False
        if cash > DEFAULT_TOLERANCE_USD:
            if abs(raise_amt - (expected + cash)) <= DEFAULT_TOLERANCE_USD:
                includes_cash = True
            if abs(prospective - cash) <= DEFAULT_TOLERANCE_USD and abs(expected - cash) > DEFAULT_TOLERANCE_USD:
                includes_cash = True
        lhs, rhs = raise_amt, expected
        tol = _tol(rhs)
        passed = (not includes_cash) and abs(lhs - rhs) <= tol
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=passed)

    if name == "prospective_raise_excludes_earmarked_existing_cash":
        if prospective is None or earmark is None or trims is None or exits is None:
            return _fail_missing(name, lhs=prospective, rhs=None)
        expected = trims + exits
        raise_amt = total_raise if total_raise is not None else prospective
        includes_earmark = False
        if earmark > DEFAULT_TOLERANCE_USD:
            if abs(raise_amt - (expected + earmark)) <= DEFAULT_TOLERANCE_USD:
                includes_earmark = True
            if abs(prospective - (expected + earmark)) <= DEFAULT_TOLERANCE_USD:
                includes_earmark = True
        lhs, rhs = raise_amt, expected
        tol = _tol(rhs)
        passed = (not includes_earmark) and abs(prospective - expected) <= tol
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=passed)

    if name == "prospective_raise_excludes_realized_historical_proceeds":
        if prospective is None or maturities is None or trims is None or exits is None:
            return _fail_missing(name, lhs=prospective, rhs=None)
        expected = trims + exits
        includes_realized = False
        if maturities > DEFAULT_TOLERANCE_USD:
            if abs(prospective - (expected + maturities)) <= DEFAULT_TOLERANCE_USD:
                includes_realized = True
        lhs, rhs = prospective, expected
        tol = _tol(rhs)
        passed = (not includes_realized) and abs(lhs - rhs) <= tol
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=passed)

    if name == "deploy_le_free_plus_prospective":
        if deploy is None or investable is None or prospective is None:
            return _fail_missing(name, lhs=deploy, rhs=None)
        lhs = deploy
        rhs = investable + prospective
        tol = _tol(rhs)
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=lhs <= rhs + tol)

    if name == "post_plan_cash_identity":
        if post is None or cash is None or prospective is None or deploy is None:
            return _fail_missing(name, lhs=post, rhs=None)
        lhs = post
        rhs = cash + prospective - deploy
        tol = _tol(rhs)
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=abs(lhs - rhs) <= tol)

    if name == "account_post_plan_rollup_eq_portfolio":
        lhs, rhs = op["sum_account_post"], post
        if lhs is None or rhs is None:
            return _fail_missing(name, lhs=lhs, rhs=rhs)
        tol = _tol(rhs)
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=abs(lhs - rhs) <= tol)

    if name == "no_capital_source_double_count":
        if deployable is None or investable is None or prospective is None:
            return _fail_missing(name, lhs=deployable, rhs=None)
        lhs = deployable
        rhs = investable + prospective
        tol = _tol(rhs)
        formula_ok = abs(lhs - rhs) <= tol
        if earmark is not None and earmark > DEFAULT_TOLERANCE_USD:
            wrong = investable + earmark + prospective
            if abs(deployable - wrong) <= tol and abs(wrong - rhs) > tol:
                formula_ok = False
            if total_raise is not None and abs(total_raise - (prospective + earmark)) <= tol:
                if abs(total_raise - prospective) > tol:
                    formula_ok = False
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=formula_ok)

    if name == "no_negative_account_cash":
        if op["accounts"] is None:
            return _fail_missing(name, lhs=op["min_account_cash"], rhs=0.0)
        lhs = op["min_account_cash"]
        if lhs is None:
            lhs = 0.0
        rhs = 0.0
        tol = DEFAULT_TOLERANCE_USD
        return _rec(name, lhs=lhs, rhs=rhs, residual=lhs - rhs, tolerance=tol, passed=lhs >= -tol)

    if name == "authority_read_only_advisory":
        auth = op.get("authority")
        lhs = 1.0 if str(auth or "") == AUTHORITY else 0.0
        rhs = 1.0
        return _rec(
            name,
            lhs=lhs,
            rhs=rhs,
            residual=lhs - rhs,
            tolerance=0.0,
            passed=lhs == rhs,
        )

    return _fail_missing(name)


def evaluate_capital_invariants(plan: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluate every required identity. Unknown/missing names are failures."""
    op = extract_capital_operands(plan)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in REQUIRED_CAPITAL_INVARIANTS:
        seen.add(name)
        out.append(_eval_one(name, op))
    # Extra declared names on the plan cannot silently pass.
    declared = None
    if isinstance(plan, dict):
        declared = plan.get("required_capital_invariants") or plan.get("REQUIRED_CAPITAL_INVARIANTS")
    if isinstance(declared, (list, tuple)):
        for name in declared:
            n = str(name)
            if n not in seen:
                out.append(_fail_missing(n))
    return out


def capital_invariants_ok(plan: Optional[dict[str, Any]]) -> bool:
    recs = evaluate_capital_invariants(plan)
    if len(recs) < len(REQUIRED_CAPITAL_INVARIANTS):
        return False
    names = {r.get("name") for r in recs}
    if any(n not in names for n in REQUIRED_CAPITAL_INVARIANTS):
        return False
    return all(bool(r.get("pass")) for r in recs)
