"""Honest per-strategy economics for option proposals (operator 2026-09-27).

Why: the desk's "expected value" was `credit x POP` for every income trade -- it
counted the chance of keeping the credit and ignored the losses (DELL $490 put:
"EV $1,473" = 68.3% x $2,157). Protective puts used a placeholder `-cost x 0.5`.

What: expected P/L at expiration, integrated over a lognormal price distribution
with the SAME volatility the desk used for POP and zero drift. For a fairly priced
option that is close to zero by construction -- which is the point: POP alone makes
selling premium look like free money. Plus the figures an operator asks for:
net cost of stock if assigned (strike - premium), cash committed, insured and
uninsured shares, and the stock-plus-put floor. Deterministic arithmetic only;
READ_ONLY_ADVISORY; MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

GRID = 400  # integration points over +/- 6 standard deviations


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _iso(v: Any) -> Optional[str]:
    """Epoch ms/s or ISO string -> ISO 8601 UTC; None when absent."""
    if v in (None, "", 0):
        return None
    try:
        from datetime import datetime, timezone
        if isinstance(v, (int, float)):
            ts = float(v) / (1000.0 if float(v) > 1e11 else 1.0)
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        return str(v)
    except (TypeError, ValueError, OSError):
        return None


def leg_quote(contract: Optional[dict[str, Any]], *, role: str) -> dict[str, Any]:
    """One leg's quote with its timestamp, as the desk saw it. Never a guess."""
    c = contract or {}
    bid, ask, last = _f(c.get("bid")), _f(c.get("ask")), _f(c.get("last"))
    mid = _f(c.get("mid"))
    if mid is None and bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2
    return {"role": role, "strike": _f(c.get("strike")), "expiration": c.get("exp") or c.get("expiration"),
            "bid": bid, "ask": ask, "mid": round(mid, 2) if mid is not None else None, "last": last,
            "mark": _f(c.get("mark")), "open_interest": c.get("oi", c.get("open_interest")),
            "volume": c.get("volume", c.get("vol")), "quote_time": _iso(c.get("quote_time")),
            "two_sided": bool(bid and ask and bid > 0 and ask > bid)}


def spread_quote(short_c: dict[str, Any], long_c: dict[str, Any], *, session: Optional[str] = None,
                 quotes_as_of: Optional[str] = None) -> dict[str, Any]:
    """Credit of a two-leg credit spread under an EXPLICIT fill assumption (operator 2026-09-27).

    The desk advertised the leg-midpoint difference as the credit: DELL $8.10 while selling the
    short put at its bid and buying the long put at its ask gave $6.35; ETON $0.89 while crossing
    the displayed quotes was a $2.00 DEBIT. A midpoint is not a fill. ``executable_credit`` is
    short bid minus long ask -- the credit a marketable limit at the displayed quotes would
    receive -- and is what the payoff is priced from. The midpoint is kept, labelled, for
    comparison. Deterministic arithmetic only; READ_ONLY_ADVISORY."""
    sq, lq = leg_quote(short_c, role="short put"), leg_quote(long_c, role="long put")
    mid_credit = (round(sq["mid"] - lq["mid"], 2) if sq["mid"] is not None and lq["mid"] is not None else None)
    exec_credit = None
    if sq["bid"] is not None and lq["ask"] is not None and sq["two_sided"] and lq["two_sided"]:
        exec_credit = round(sq["bid"] - lq["ask"], 2)
    basis = "executable" if exec_credit is not None else ("midpoint" if mid_credit is not None else None)
    return {
        "schema": "OptionsSpreadQuote@v1",
        "mid_credit": mid_credit,
        "executable_credit": exec_credit,
        "credit_basis": basis,
        "credit_haircut": (round(mid_credit - exec_credit, 2)
                           if mid_credit is not None and exec_credit is not None else None),
        "fill_assumption": ("sell the short leg at its bid, buy the long leg at its ask (marketable limit "
                            "at the displayed quotes)" if exec_credit is not None else
                            "leg midpoints only: one leg has no two-sided quote"),
        "legs": [sq, lq],
        "quotes_as_of": quotes_as_of or sq["quote_time"] or lq["quote_time"],
        "market_session": session,
        "is_credit": (exec_credit is not None and exec_credit > 0),
    }


def expected_payoff(payoff: Callable[[float], float], spot: float, iv: float, dte: int) -> Optional[float]:
    """E[payoff(S_T)] with ln S_T ~ N(ln S - sigma^2 T / 2, sigma^2 T) (zero drift)."""
    if not spot or spot <= 0 or not iv or iv <= 0 or dte is None:
        return None
    t = max(int(dte), 1) / 365.0
    s = iv * math.sqrt(t)
    mu = math.log(spot) - 0.5 * s * s
    lo, hi = mu - 6 * s, mu + 6 * s
    step = (hi - lo) / GRID
    total = 0.0
    for i in range(GRID):
        x = lo + (i + 0.5) * step
        w = math.exp(-0.5 * ((x - mu) / s) ** 2) / (s * math.sqrt(2 * math.pi)) * step
        total += w * payoff(math.exp(x))
    return total


def _payoff(p: dict[str, Any]) -> Optional[Callable[[float], float]]:
    """Per-share expiration P/L of the OPTION position (not the stock) as a function of S_T."""
    strat = str(p.get("strategy") or "")
    k = _f(p.get("strike"))
    prem = _f(p.get("premium"))
    if strat == "credit_spread":
        short_k = _f(p.get("short_strike")) or k
        long_k = _f(p.get("long_strike"))
        credit = _f(p.get("executable_credit"))
        if credit is None:
            credit = _f(p.get("net_credit")) or prem
        if short_k is None or long_k is None or credit is None:
            return None
        return lambda s: credit - max(short_k - s, 0.0) + max(long_k - s, 0.0)
    if k is None or prem is None:
        return None
    if strat == "cash_secured_put":
        return lambda s: prem - max(k - s, 0.0)
    if strat == "covered_call":
        return lambda s: prem - max(s - k, 0.0)
    if strat in ("protective_put", "long_put"):
        return lambda s: max(k - s, 0.0) - prem
    if strat == "long_call":
        return lambda s: max(s - k, 0.0) - prem
    return None


def economics(p: dict[str, Any], *, shares_held: Optional[float] = None,
              quote_issues: Optional[list[str]] = None, session: Optional[str] = None) -> dict[str, Any]:
    """Economics block for one proposal. Missing inputs give None, never a guess.

    ``quote_issues`` (the liquidity gate's failures) withholds expected P/L: on a 185%-wide
    weekend quote the desk's IV is not the market's, and XLB's hedge showed +$827 on a
    $345 put (Wave B, 2026-09-27). Strike/premium arithmetic is still shown, at the mid."""
    strat = str(p.get("strategy") or "")
    n = int(_f(p.get("contracts")) or 1)
    multiplier = _f(p.get("multiplier")) or 100
    mult = multiplier * n
    spot = _f(p.get("underlying_price"))
    iv = _f(p.get("iv_used"))
    dte = p.get("dte")
    k = _f(p.get("strike"))
    prem = _f(p.get("premium"))
    out: dict[str, Any] = {"schema": "OptionsEconomics@v1", "contracts": n, "multiplier": multiplier,
                           "ev_method": "expected P/L at expiration, lognormal at the desk's IV, zero drift"}
    pay = _payoff(p)
    ev = expected_payoff(pay, spot, iv, dte) if pay else None
    out["expected_pl_at_expiry"] = round(ev * mult, 2) if ev is not None else None
    if ev is not None:
        # A bare figure is not a fact (operator 2026-09-27): say what it was computed from.
        basis = p.get("credit_basis") or ("executable" if p.get("executable_credit") is not None else "midpoint")
        credit_in = (_f(p.get("executable_credit")) if strat == "credit_spread" and p.get("executable_credit") is not None
                     else (_f(p.get("net_credit")) if strat == "credit_spread" else prem))
        out["ev_inputs"] = {"credit_or_premium": credit_in, "credit_basis": basis if strat == "credit_spread" else "quote mid",
                            "iv": iv, "spot": spot, "dte": dte, "quotes_as_of": p.get("quotes_as_of"),
                            "market_session": session}
        caveats = []
        if session and session != "REGULAR":
            caveats.append(f"closed-market quote ({str(session).lower().replace('_', ' ')})")
        if strat == "credit_spread" and basis == "midpoint":
            caveats.append("credit is a leg midpoint, not a fill")
        out["ev_caveat"] = ("model estimate at the desk's IV" + (" on a " + "; ".join(caveats) if caveats else "")
                            + "; recheck on live validated quotes before acting")
    if quote_issues:
        out["expected_pl_at_expiry"] = None
        out["expected_pl_status"] = "withheld: quotes not tradeable (" + "; ".join(map(str, quote_issues[:3])) + ")"
        out["prices_basis"] = "mid of a non-tradeable quote; recheck on live quotes"
    if strat == "cash_secured_put" and k is not None and prem is not None:
        out.update({
            "net_cost_if_assigned_per_share": round(k - prem, 2),
            "net_cost_if_assigned_total": round((k - prem) * mult, 2),
            "cash_committed": round(k * mult, 2),
            "discount_to_spot_pct": round(100.0 * (1 - (k - prem) / spot), 1) if spot else None,
            "credit_total": round(prem * mult, 2),
        })
    if strat == "covered_call" and k is not None and prem is not None:
        out.update({
            "credit_total": round(prem * mult, 2),
            "called_away_price_per_share": round(k + prem, 2),
            "shares_committed": mult,
        })
    if strat == "credit_spread":
        sk, lk = _f(p.get("short_strike")) or k, _f(p.get("long_strike"))
        exec_credit = _f(p.get("executable_credit"))
        credit = exec_credit if exec_credit is not None else (_f(p.get("net_credit")) or prem)
        if sk is not None and lk is not None and credit is not None:
            out.update({"credit_total": round(credit * mult, 2),
                        "collateral": round((sk - lk) * mult, 2),
                        "max_loss_total": round((sk - lk - credit) * mult, 2),
                        "breakeven": round(sk - credit, 2),
                        "credit_basis": "executable" if exec_credit is not None else "midpoint"})
            mid_credit = _f(p.get("mid_credit"))
            if exec_credit is not None and mid_credit is not None:
                out.update({"credit_total_at_mid": round(mid_credit * mult, 2),
                            "max_loss_total_at_mid": round((sk - lk - mid_credit) * mult, 2),
                            "breakeven_at_mid": round(sk - mid_credit, 2),
                            "credit_haircut_total": round((mid_credit - exec_credit) * mult, 2),
                            "prices_basis": "sell short leg at bid, buy long leg at ask; midpoint shown for comparison"})
    if strat == "protective_put" and k is not None and prem is not None and spot:
        insured = mult
        out.update({
            "option_cost_total": round(prem * mult, 2),
            "insured_shares": insured,
            "uninsured_shares": (round(max(0.0, shares_held - insured), 3) if shares_held is not None else None),
            "floor_value_after_premium": round((k - prem) * insured, 2),
            "position_value_at_mark": round(spot * insured, 2),
            "downside_to_floor_from_mark": round((spot - (k - prem)) * insured, 2),
            "stock_plus_put_breakeven_from_mark": round(spot + prem, 2),
            # Operator 2026-09-27: the card is insurance for held stock, so the headline max loss
            # is the hedged shares' loss to the floor from the mark (premium included), and the
            # put-alone figures are labelled as such rather than shown as "max loss"/"breakeven".
            "hedged_max_loss_from_mark": round(max(0.0, spot - (k - prem)) * insured, 2),
            "option_max_loss": round(prem * mult, 2),
            "put_breakeven": round(k - prem, 2),
            "uninsured_downside_note": (None if shares_held is None or shares_held - insured <= 0 else
                                        f"{round(shares_held - insured, 3):g} shares beyond the {insured} insured "
                                        f"are unhedged and fall with the stock"),
            "note": "Max loss of the hedged shares is to the floor, not the premium; P/L vs your "
                    "actual cost basis differs from the mark.",
        })
    return out


def _package_payoff(p: dict[str, Any]):
    """Per-unit terminal payoff from current stock mark, including entry cash flow."""
    strategy = p.get("strategy")
    spot, k, premium = (_f(p.get(key)) for key in ("underlying_price", "strike", "premium"))
    if premium is None or spot is None or not math.isfinite(premium) or not math.isfinite(spot) or spot <= 0:
        raise ValueError("spot and executable premium required")
    if strategy in {"credit_spread", "debit_spread"}:
        sk, lk = _f(p.get("short_strike")), _f(p.get("long_strike"))
        side = p.get("option_type", "put")
        if sk is None or lk is None or side not in {"call", "put"}:
            raise ValueError("vertical strikes and option type required")
        credit = strategy == "credit_spread"
        valid = (sk < lk if side == "call" else sk > lk)
        if valid != credit or not 0 < premium < abs(sk - lk):
            raise ValueError("invalid vertical ordering or entry price")
        expirations = {str(x.get("expiration") or x.get("exp")) for x in p.get("legs", [])
                       if x.get("expiration") or x.get("exp")}
        if len(expirations) > 1:
            raise ValueError("vertical legs must share expiry")
        intrinsic = (lambda s, strike: max(s - strike, 0.0)) if side == "call" else (
            lambda s, strike: max(strike - s, 0.0))
        return lambda s: intrinsic(s, lk) - intrinsic(s, sk) + (premium if credit else -premium), [lk, sk]
    if strategy == "collar":
        pk, ck = _f(p.get("put_strike")), _f(p.get("call_strike"))
        debit = _f(p.get("net_debit"))
        if pk is None or ck is None or debit is None or not 0 < pk < ck:
            raise ValueError("collar strikes and signed net debit required")
        return lambda s: s - spot + max(pk - s, 0.0) - max(s - ck, 0.0) - debit, [pk, ck]
    if k is None or k <= 0 or premium < 0:
        raise ValueError("positive strike and nonnegative premium required")
    if strategy == "covered_call":
        return lambda s: s - spot + premium - max(s - k, 0.0), [k]
    if strategy == "protective_put":
        return lambda s: s - spot + max(k - s, 0.0) - premium, [k]
    if strategy == "cash_secured_put":
        return lambda s: premium - max(k - s, 0.0), [k]
    if strategy == "long_call":
        return lambda s: max(s - k, 0.0) - premium, [k]
    if strategy == "long_put":
        return lambda s: max(k - s, 0.0) - premium, [k]
    raise ValueError("unsupported strategy")


def payoff_metrics(p: dict[str, Any]) -> dict[str, Any]:
    """Piecewise-linear package risk and model probability of positive net P/L.

    Finite tail slopes are checked explicitly; None plus ``unlimited`` means an
    unbounded gain, never a fabricated target. Fees/slippage are explicit inputs.
    The zero-drift lognormal distribution is a model assumption, not calibrated alpha.
    """
    out: dict[str, Any] = {"schema": "OptionsPayoff@v1", "status": "UNAVAILABLE",
        "max_loss": None, "max_profit": None, "breakeven": None,
        "probability_of_profit_pct": None, "expected_pl": None,
        "probability_basis": "lognormal terminal price at stated IV, zero drift; not empirically calibrated",
        "price_basis": p.get("price_basis") or p.get("credit_basis") or "legacy midpoint",
        "fee_basis": "provided" if p.get("fees_total") is not None else "not supplied; excluded",
        "slippage_basis": "provided" if p.get("slippage_total") is not None else "not supplied; excluded"}
    if p.get("non_standard") or p.get("nonstandard") or p.get("deliverable_status") == "nonstandard":
        return {**out, "status": "UNSUPPORTED_DELIVERABLE"}
    try:
        contracts = _f(p.get("contracts", 1))
        multiplier = _f(p.get("multiplier", 100))
        fees = _f(p.get("fees_total", 0))
        slippage = _f(p.get("slippage_total", 0))
        vals = [contracts, multiplier, fees, slippage]
        if any(v is None or not math.isfinite(v) for v in vals):
            raise ValueError("non-finite economics input")
        if contracts <= 0 or contracts != int(contracts) or multiplier <= 0 or fees < 0 or slippage < 0:
            raise ValueError("invalid multiplier, contracts or costs")
        payoff, strikes = _package_payoff(p)
        if any(not math.isfinite(k) or k <= 0 for k in strikes):
            raise ValueError("invalid strike")
        unit_cost = (fees + slippage) / (contracts * multiplier)
        net = lambda s: payoff(s) - unit_cost
        points = sorted({0.0, *strikes})
        last = points[-1]
        slope = net(last + 1) - net(last)
        values = [net(s) for s in points]
        scale = contracts * multiplier
        maximum = None if slope > 1e-8 else max(values) * scale
        minimum = None if slope < -1e-8 else min(values) * scale
        roots = []
        segments = [*points, math.inf]
        profitable = []
        for left, right in zip(segments, segments[1:]):
            m = net(left + 1) - net(left) if math.isinf(right) else (net(right) - net(left)) / (right - left)
            root = left - net(left) / m if abs(m) > 1e-9 else None
            cuts = [left]
            if root is not None and left <= root <= right and math.isfinite(root):
                roots.append(round(root, 6))
                if left < root < right:
                    cuts.append(root)
            cuts.append(right)
            for a, b in zip(cuts, cuts[1:]):
                if net(a + 1 if math.isinf(b) else (a + b) / 2) > 0:
                    profitable.append((a, b))
        roots = sorted(set(roots))
        out.update(status="MODELED", multiplier=multiplier, contracts=int(contracts),
                   max_loss=round(max(0, -minimum), 2) if minimum is not None else None,
                   max_profit=round(maximum, 2) if maximum is not None else None,
                   profit_unlimited=maximum is None, loss_unlimited=minimum is None,
                   breakeven=roots[0] if len(roots) == 1 else None, breakevens=roots,
                   package_basis="stock plus options from current mark" if p.get("strategy") in {
                       "covered_call", "protective_put", "collar"} else "options only")
        spot, iv, dte = _f(p.get("underlying_price")), _f(p.get("iv_used")), _f(p.get("dte"))
        if spot and iv and dte and all(math.isfinite(v) and v > 0 for v in (spot, iv, dte)):
            sigma = iv * math.sqrt(dte / 365)
            def cdf(s):
                if s <= 0:
                    return 0.0
                if math.isinf(s):
                    return 1.0
                z = (math.log(s / spot) + sigma * sigma / 2) / sigma
                return (1 + math.erf(z / math.sqrt(2))) / 2
            out["probability_of_profit_pct"] = round(100 * sum(cdf(b) - cdf(a) for a, b in profitable), 2)
            ev = expected_payoff(net, spot, iv, int(dte))
            out["expected_pl"] = round(ev * scale, 2) if ev is not None else None
    except (ValueError, TypeError, OverflowError) as exc:
        out.update(status="INVALID_INPUT", reason=str(exc))
    return out


def stamp_payoff(proposal: dict[str, Any], *, quote_issues: list | None = None,
                 session: str | None = None) -> None:
    """Price every displayed field from one captured quote and the same contract lot.

    This is advisory arithmetic after policy gates, not a fill or quote validation.
    Preserve the old heuristic input once; repeated cache reads must be idempotent.
    """
    proposal.setdefault('gate_probability_pct', proposal.get('pop_pct'))
    proposal.setdefault('gate_probability_basis', 'legacy strike probability used by existing heuristic gate')
    proposal.setdefault('premium_midpoint', proposal.get('premium'))
    strategy = proposal.get('strategy')
    session = session or proposal.get('market_session') or 'UNKNOWN'
    bid, ask = _f(proposal.get('bid')), _f(proposal.get('ask'))
    selected = _f(proposal.get('premium_midpoint'))
    side, quoted = 'midpoint', False
    if strategy == 'credit_spread' and _f(proposal.get('executable_credit')) is not None:
        selected, side, quoted = _f(proposal['executable_credit']), 'short bid minus long ask', True
    elif strategy in {'debit_spread', 'collar'}:
        # These generators already supply the signed multi-leg entry cash flow.
        selected, side = _f(proposal.get('premium')), 'multi-leg quoted price'
    elif (bid is not None and ask is not None and math.isfinite(bid) and math.isfinite(ask)
          and 0 <= bid <= ask and ask > 0):
        side = 'ask' if strategy in {'long_call', 'long_put', 'protective_put'} else 'bid'
        selected, quoted = (ask if side == 'ask' else bid), True
    basis = f'{side} estimate; not a fill; session {session}; fees and slippage excluded from premium'
    proposal['price_basis'] = basis
    proposal['premium_basis'] = side
    priced = dict(proposal, premium=selected)
    metrics = payoff_metrics(priced)
    issues = list(quote_issues or [])
    if session != 'REGULAR':
        issues.append(f'quote session {session}; live validation required')
    if issues or not quoted or proposal.get('data_source') == 'bs_estimate':
        metrics['probability_of_profit_pct'] = None
        metrics['expected_pl'] = None
        metrics['model_status'] = 'WITHHELD_UNVALIDATED_QUOTES'
    proposal['payoff'] = metrics
    proposal['edge_basis'] = 'heuristic score; not calibrated expected return'
    proposal['pop_pct'] = metrics.get('probability_of_profit_pct')
    proposal['pop_basis'] = metrics['probability_basis']
    proposal['expected_value'] = metrics.get('expected_pl')
    proposal['expected_value_method'] = metrics['probability_basis']
    proposal['economics_revision'] = 'coherent_quote_v1'
    if metrics['status'] != 'MODELED':
        proposal['pop_pct'] = None
        proposal['expected_value'] = None
        # Never retain a legacy finite risk figure when the payoff is unavailable.
        for key in ('max_loss', 'max_profit', 'breakeven', 'risk_reward', 'floor_value', 'option_max_loss'):
            proposal[key] = None
        ent = proposal.setdefault('enterprise', {})
        ent['live_eligible'] = False
        ent['blocks'] = list(ent.get('blocks') or [])
        if metrics['status'] not in ent['blocks']:
            ent['blocks'].append(metrics['status'])
        proposal['enterprise_blocked'] = True
        proposal['economics'] = {'schema': 'OptionsEconomics@v1', 'status': metrics['status'], 'prices_basis': basis}
        return
    proposal['premium'] = selected
    mult = float(proposal.get('multiplier') or 100) * int(proposal.get('contracts') or 1)
    proposal['premium_total'] = round(selected * mult, 2)
    proposal['max_loss'] = metrics['max_loss']
    proposal['max_profit'] = 'unlimited' if metrics['profit_unlimited'] else metrics['max_profit']
    proposal['breakeven'] = metrics['breakeven']
    proposal['risk_reward'] = (round(metrics['max_profit'] / metrics['max_loss'], 4)
                              if metrics['max_profit'] is not None and metrics['max_loss'] else None)
    e = economics(priced, shares_held=_f(proposal.get('shares_held')), quote_issues=issues, session=session)
    e.update(prices_basis=basis, premium=selected, premium_total=proposal['premium_total'],
             expected_pl_at_expiry=metrics.get('expected_pl'), ev_method=metrics['probability_basis'],
             quote_time=proposal.get('quotes_as_of') or proposal.get('quote_time'),
             market_session=session, scope='contract lot; stock marked from captured underlying price')
    if e.get('credit_basis'):
        e['credit_basis'] = side
    if e.get('ev_inputs'):
        e['ev_inputs']['credit_basis'] = side
    if metrics.get('model_status'):
        e['expected_pl_status'] = 'withheld: quotes require live validation'
    costs = (_f(proposal.get('fees_total')) or 0) + (_f(proposal.get('slippage_total')) or 0)
    held = _f(proposal.get('shares_held'))
    e['fees_and_slippage_total'] = costs
    if strategy == 'credit_spread':
        e.update(max_loss_total=metrics['max_loss'], breakeven=metrics['breakeven'])
    if strategy == 'cash_secured_put':
        assigned = float(proposal['strike']) - selected + costs / mult
        e.update(net_cost_if_assigned_per_share=round(assigned, 2),
                 net_cost_if_assigned_total=round(assigned * mult, 2),
                 discount_to_spot_pct=round(100 * (1 - assigned / float(proposal['underlying_price'])), 1))
    if strategy == 'protective_put':
        e.update(hedged_max_loss_from_mark=metrics['max_loss'],
                 downside_to_floor_from_mark=metrics['max_loss'],
                 stock_plus_put_breakeven_from_mark=metrics['breakeven'],
                 floor_value_after_premium=round((float(proposal['strike']) - selected) * mult - costs, 2),
                 option_max_loss=round(selected * mult + costs, 2),
                 put_breakeven=round(float(proposal['strike']) - selected - costs / mult, 2))
        proposal.update(option_max_loss=e['option_max_loss'], put_breakeven=e.get('put_breakeven'),
                        max_loss_label='Max loss (hedged shares, to the floor)',
                        breakeven_label='Stock+put breakeven from mark',
                        floor_value=e['floor_value_after_premium'], uninsured_shares=e.get('uninsured_shares'))
        spot = float(proposal['underlying_price'])
        e['protection_scenarios'] = []
        for move in (-30, -20, -10):
            terminal = spot * (1 + move / 100)
            stock_pl = (terminal - spot) * mult
            hedge_pl = max(float(proposal['strike']) - terminal, 0) * mult - selected * mult - costs
            e['protection_scenarios'].append({'move_pct': move, 'stock_pl': round(stock_pl, 2),
                'hedged_pl': round(stock_pl + hedge_pl, 2), 'loss_reduction': round(hedge_pl, 2)})
        e['assessment_basis'] = ('Insurance: compare premium budget, protection window and loss reduction on insured '
                                 'shares. Profit probability is not an insurance suitability score.')
    if strategy == 'covered_call':
        e['called_away_price_per_share'] = round(float(proposal['strike']) + selected - costs / mult, 2)
        proposal['stock_downside_risk'] = metrics['max_loss']
        e['residual_shares'] = round(max(0, held - mult), 3) if held is not None else None
        e['stock_downside_risk'] = metrics['max_loss']
    proposal['economics'] = e
    # Rebuild deterministic prose too; a repaired number must not coexist with an old mid-price sentence.
    from scripts.lib.options_plain_english import explain, _plain_summary
    proposal['plain_english'] = explain(proposal)
    if proposal.get('committee_memo') and not proposal['committee_memo'].get('error'):
        memo = proposal['committee_memo']
        memo['plain_summary'] = _plain_summary(proposal, memo.get('classification', ''), memo.get('purpose', ''))
