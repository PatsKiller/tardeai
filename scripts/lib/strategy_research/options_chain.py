"""Read-only option-chain research adapter + deep-ITM call analysis (spec Part D).

Chain data source — REUSED, never re-implemented: the options desk's Schwab
read path, ``schwab_transport.get_option_chain`` (the exact function
``options_engine._schwab_chain`` calls). Its ``normalize_option_chain`` shape:

    {"status": "ok", "symbol": ..., "underlying_price": ...,
     "expirations": [{"exp": "YYYY-MM-DD", "dte": int, "contracts": int,
                      "total_call_oi": int, "total_put_oi": int,
                      "strikes": [{"exp", "strike", "side", "bid", "ask",
                                   "last", "iv", "delta", "oi", "volume",
                                   "dte"}, ...]}, ...]}

The ONLY attributes this module ever touches on schwab_transport are
``get_option_chain`` (and nothing else) — READ-ONLY market data. No order,
submit, cancel, or approval surface is imported or called anywhere in this
package (grep + AST enforced by tests/test_options_strategy_research.py).

Honest degradation (HARD RULE): weekend / no linked account / transport
error / thin chain → {"available": False, "reason": ...}. Numbers are never
fabricated; every figure in an "available" result comes from actual chain
rows. All outputs are EDUCATIONAL_ONLY research JSON.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

EDUCATIONAL_BANNER = ("EDUCATIONAL_ONLY — options strategy research analysis. "
                      "Not investment advice, not a recommendation, and NOT an "
                      "order: this tool has no order, submit, or execution "
                      "surface. Operator review required before any use.")

CHAIN_SOURCE = "schwab_transport.get_option_chain (options desk read-only chain path)"

# Flag thresholds (research heuristics, not gates).
WIDE_SPREAD_PCT = 10.0      # bid/ask spread > 10% of mid → wide_spread flag
LOW_OI = 100                # open interest below this → low_oi flag
LOW_VOLUME = 1              # day volume below this → no_volume flag

# ITM%-depth proxy for the 0.80-0.95 delta band when the chain carries no
# usable greeks: intrinsic depth (S - K) / S between 10% and 35%.
ITM_PCT_PROXY_RANGE = (0.10, 0.35)


# ── small numeric helpers ────────────────────────────────────────────────────

def _f(v: Any, default: float | None = None) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN (Schwab pads greeks with NaN / -999 sentinels)
        return default
    return x


def _mid(bid: Any, ask: Any, last: Any) -> float | None:
    b, a = _f(bid) or 0.0, _f(ask) or 0.0
    if b > 0 and a > 0 and a >= b:
        return round((a + b) / 2.0, 4)
    l = _f(last) or 0.0
    return round(l, 4) if l > 0 else None


def _spread_pct(bid: Any, ask: Any, mid: float | None) -> float | None:
    b, a = _f(bid) or 0.0, _f(ask) or 0.0
    if not mid or mid <= 0 or b <= 0 or a <= 0 or a < b:
        return None
    return round((a - b) / mid * 100.0, 2)


def _usable_delta(v: Any) -> float | None:
    """Delta if plausible; Schwab pads dead contracts with -999/NaN."""
    d = _f(v)
    if d is None:
        return None
    d = abs(d)
    return d if 0.0 < d <= 1.0 else None


def contract_liquidity_score(c: dict[str, Any]) -> int:
    """0-100 tradability-of-data score: OI (40) + volume (30) + spread (30)."""
    oi = _f(c.get("oi")) or 0.0
    vol = _f(c.get("volume")) or 0.0
    spread = c.get("spread_pct")
    score = 0.0
    score += min(oi / 1000.0, 1.0) * 40.0
    score += min(vol / 200.0, 1.0) * 30.0
    if spread is not None:
        score += max(0.0, 1.0 - (float(spread) / 25.0)) * 30.0
    return int(round(min(score, 100.0)))


# ── chain snapshot (parse + fetch) ───────────────────────────────────────────

def _unavailable(symbol: str, reason: str) -> dict[str, Any]:
    return {"available": False, "symbol": (symbol or "").upper(),
            "reason": reason, "source": CHAIN_SOURCE,
            "educational_only": True, "banner": EDUCATIONAL_BANNER,
            "generated_at": datetime.now(timezone.utc).isoformat()}


def parse_chain(raw: Any, symbol: str) -> dict[str, Any]:
    """normalize_option_chain payload → research snapshot (or honest degrade).

    Pure function (unit-testable on a synthetic fixture): adds mid, spread%,
    per-contract liquidity scores, per-expiration + overall liquidity, and a
    per-strategy feasibility map. Anything that is not a status=ok chain with
    expirations degrades to {"available": False, "reason": ...}.
    """
    sym = (symbol or "").upper()
    if not isinstance(raw, dict):
        return _unavailable(sym, "chain read returned no payload")
    status = raw.get("status")
    if status not in (None, "ok"):
        detail = raw.get("error") or raw.get("reason") or ""
        return _unavailable(sym, f"chain unavailable (status={status}"
                                 f"{': ' + str(detail)[:120] if detail else ''})")
    expirations = raw.get("expirations") or []
    if not expirations:
        return _unavailable(sym, "chain returned no expirations "
                                 "(market closed, unlisted, or no options)")

    out_exps: list[dict[str, Any]] = []
    for exp in expirations:
        contracts: list[dict[str, Any]] = []
        for r in (exp.get("strikes") or []):
            strike = _f(r.get("strike"))
            if strike is None:
                continue
            mid = _mid(r.get("bid"), r.get("ask"), r.get("last"))
            c = {"side": r.get("side"), "strike": strike,
                 "bid": _f(r.get("bid")), "ask": _f(r.get("ask")),
                 "mid": mid,
                 "spread_pct": _spread_pct(r.get("bid"), r.get("ask"), mid),
                 "volume": int(_f(r.get("volume")) or 0),
                 "oi": int(_f(r.get("oi")) or 0),
                 "delta": _usable_delta(r.get("delta")),
                 "iv": _f(r.get("iv")),
                 "dte": int(_f(r.get("dte")) or _f(exp.get("dte")) or 0)}
            c["liquidity_score"] = contract_liquidity_score(c)
            contracts.append(c)
        if not contracts:
            continue
        out_exps.append({
            "exp": str(exp.get("exp") or "")[:10],
            "dte": int(_f(exp.get("dte")) or contracts[0]["dte"]),
            "contracts": contracts,
            "total_call_oi": int(_f(exp.get("total_call_oi")) or 0),
            "total_put_oi": int(_f(exp.get("total_put_oi")) or 0),
            "liquidity_score": int(round(
                sum(c["liquidity_score"] for c in contracts) / len(contracts))),
        })
    if not out_exps:
        return _unavailable(sym, "chain carried no parseable contracts")

    snapshot = {
        "available": True,
        "symbol": raw.get("symbol") or sym,
        "source": CHAIN_SOURCE,
        "underlying_price": _f(raw.get("underlying_price")),
        "expirations": out_exps,
        "liquidity_score": int(round(
            sum(e["liquidity_score"] for e in out_exps) / len(out_exps))),
        "educational_only": True,
        "banner": EDUCATIONAL_BANNER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    snapshot["strategy_feasibility"] = strategy_feasibility(snapshot)
    return snapshot


def fetch_chain_snapshot(symbol: str, *, strike_count: int = 40,
                         account_key: str | None = None) -> dict[str, Any]:
    """Read-only chain snapshot via the options desk's Schwab read path.

    Lazy-imports schwab_transport and calls ONLY get_option_chain (the same
    call options_engine._schwab_chain makes). Every failure mode — import,
    auth (needs_account_link), transport error, empty weekend chain —
    degrades to {"available": False, "reason": ...}.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return _unavailable(sym, "no symbol given")
    try:
        import schwab_transport  # read path only; see module docstring
    except Exception as e:
        return _unavailable(sym, f"schwab_transport import failed: {e}")
    try:
        raw = schwab_transport.get_option_chain(
            sym, strike_count=int(strike_count),
            **({"account_key": account_key} if account_key else {}))
    except Exception as e:
        return _unavailable(sym, f"chain read failed: {str(e)[:160]}")
    return parse_chain(raw, sym)


# ── strategy feasibility over a snapshot ─────────────────────────────────────

def _contracts(snapshot: dict[str, Any], *, side: str,
               min_dte: int = 0, max_dte: int = 10 ** 6) -> Iterable[dict[str, Any]]:
    for exp in snapshot.get("expirations") or []:
        if min_dte <= int(exp.get("dte") or 0) <= max_dte:
            for c in exp.get("contracts") or []:
                if c.get("side") == side:
                    yield c


def _band_score(cs: list[dict[str, Any]]) -> tuple[bool, int, str]:
    if not cs:
        return False, 0, "no contracts in the required DTE band"
    score = int(round(sum(c["liquidity_score"] for c in cs) / len(cs)))
    return score >= 20, score, f"{len(cs)} contracts, avg liquidity {score}"


def strategy_feasibility(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Per-strategy {feasible, score 0-100, reason} from actual chain depth.

    Research heuristic ONLY (feeds the strategy-discovery evidence trail) —
    never a gate, never an instruction to trade.
    """
    if not snapshot.get("available"):
        return {}
    spot = snapshot.get("underlying_price")
    checks: dict[str, tuple[list, str]] = {
        "deep_itm_call": (
            [c for c in _contracts(snapshot, side="call", min_dte=25)
             if spot and c["strike"] < spot],
            "ITM calls with >=25 DTE"),
        "covered_call": (
            [c for c in _contracts(snapshot, side="call", min_dte=15, max_dte=60)
             if spot and c["strike"] >= spot],
            "near-dated OTM calls (15-60 DTE)"),
        "cash_secured_put": (
            [c for c in _contracts(snapshot, side="put", min_dte=15, max_dte=60)
             if spot and c["strike"] <= spot],
            "near-dated OTM puts (15-60 DTE)"),
        "protective_put": (
            [c for c in _contracts(snapshot, side="put", min_dte=25)
             if spot and c["strike"] <= spot],
            "downside puts with >=25 DTE"),
        "collar": (
            [c for c in _contracts(snapshot, side="put", min_dte=25)]
            + [c for c in _contracts(snapshot, side="call", min_dte=25)],
            "both wings with >=25 DTE"),
        "leaps_long_call": (
            [c for c in _contracts(snapshot, side="call", min_dte=270)],
            "calls with >=270 DTE (LEAPS)"),
        "call_spread": (
            [c for c in _contracts(snapshot, side="call", min_dte=15)],
            "call ladder depth (15+ DTE)"),
        "diagonal_spread": (
            [c for c in _contracts(snapshot, side="call", min_dte=60)]
            if any(int(e.get("dte") or 0) <= 45
                   for e in snapshot.get("expirations") or []) else [],
            "short near-dated + long 60+ DTE calls"),
        "synthetic_long": (
            [c for c in _contracts(snapshot, side="call", min_dte=25)]
            + [c for c in _contracts(snapshot, side="put", min_dte=25)],
            "matched call+put >=25 DTE"),
    }
    out: dict[str, Any] = {}
    for name, (cs, band) in checks.items():
        feasible, score, detail = _band_score(cs)
        out[name] = {"feasible": feasible, "score": score,
                     "reason": f"{band}: {detail}"}
    return out


# ── earnings lookup (read-only symbol_profiles) ──────────────────────────────

def next_earnings_date(symbol: str) -> str | None:
    """symbol_profiles.next_earnings_date as 'YYYY-MM-DD', or None.

    Read-only DB lookup; any failure (no DB, no table, no row) returns None —
    the earnings flag then reports honestly as unknown.
    """
    try:
        from db_adapter import _execute
        row = _execute(
            "SELECT next_earnings_date FROM symbol_profiles WHERE symbol = %s",
            ((symbol or "").upper(),), fetch="one")
        if row:
            val = dict(row).get("next_earnings_date")
            if val:
                return str(val)[:10]
    except Exception:
        pass
    return None


def _earnings_before(exp: str, earnings: str | None) -> bool | None:
    """True/False when both ISO dates are known; None (unknown) otherwise."""
    if not earnings or not exp:
        return None
    try:
        return str(earnings)[:10] <= str(exp)[:10]
    except Exception:
        return None


# ── deep ITM call analysis (spec Part D) ─────────────────────────────────────

def _bucket_expiration(snapshot: dict[str, Any], target_dte: int) -> dict[str, Any] | None:
    """Closest expiration to the bucket target, within a sane tolerance."""
    best, best_gap = None, None
    for exp in snapshot.get("expirations") or []:
        gap = abs(int(exp.get("dte") or 0) - int(target_dte))
        if best_gap is None or gap < best_gap:
            best, best_gap = exp, gap
    if best is None:
        return None
    # a bucket only counts when a listed expiration is reasonably near it —
    # matching a 33-DTE expiry to the 90-day bucket would misrepresent the data
    tolerance = max(15, round(target_dte * 0.4))
    return best if best_gap is not None and best_gap <= tolerance else None


def _candidate_row(c: dict[str, Any], spot: float, exp: str,
                   earnings: str | None) -> dict[str, Any]:
    mid = c.get("mid")
    intrinsic = round(max(spot - c["strike"], 0.0), 4)
    extrinsic = round(mid - intrinsic, 4) if mid is not None else None
    breakeven = round(c["strike"] + mid, 4) if mid is not None else None
    spread = c.get("spread_pct")
    row = {
        "strike": c["strike"], "exp": exp, "dte": c.get("dte"),
        "bid": c.get("bid"), "ask": c.get("ask"), "mid": mid,
        "delta": c.get("delta"), "iv": c.get("iv"),
        "volume": c.get("volume"), "oi": c.get("oi"),
        "spread_pct": spread,
        "liquidity_score": c.get("liquidity_score"),
        "flags": {
            "wide_spread": (spread is None) or (spread > WIDE_SPREAD_PCT),
            "low_oi": int(c.get("oi") or 0) < LOW_OI,
            "no_volume": int(c.get("volume") or 0) < LOW_VOLUME,
            "no_quote": mid is None,
            "earnings_before_expiry": _earnings_before(exp, earnings),
        },
        "intrinsic_value": intrinsic,
        "extrinsic_value": extrinsic,
        "breakeven": breakeven,
        "breakeven_move_pct": (round((breakeven / spot - 1.0) * 100.0, 2)
                               if breakeven is not None and spot else None),
    }
    if mid is not None:
        contract_capital = round(mid * 100.0, 2)
        shares_capital = round(spot * 100.0, 2)
        row["max_loss"] = contract_capital        # long premium: max loss = debit
        row["capital_required"] = contract_capital
        row["capital_vs_100_shares"] = {
            "contract_debit": contract_capital,
            "100_shares": shares_capital,
            "capital_ratio_pct": (round(contract_capital / shares_capital * 100.0, 2)
                                  if shares_capital else None),
        }
    else:
        row["max_loss"] = None
        row["capital_required"] = None
        row["capital_vs_100_shares"] = None
    return row


def _iv_context_for(symbol: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """IV-rank context (ADVISORY ONLY — informs, never rejects) for a symbol.

    Current ATM IV comes from the snapshot already in hand (no second chain
    read); the rank comes from the options_iv_history daily series. Every
    failure mode degrades honestly to {"available": False, "reason": ...} —
    including <20 stored days ("insufficient history"), which is never
    fabricated into a rank.
    """
    try:
        from . import iv_history
        atm = iv_history.extract_atm_iv(snapshot)
        return iv_history.iv_rank(symbol, current_iv=(atm or {}).get("atm_iv"))
    except Exception as e:
        return {"available": False,
                "reason": f"iv context error: {str(e)[:120]}"}


def deep_itm_call_analysis(symbol: str,
                           delta_range: tuple[float, float] = (0.80, 0.95),
                           dte_buckets: list[int] | tuple[int, ...] = (30, 60, 90, 180, 365),
                           *, snapshot: dict[str, Any] | None = None,
                           strike_count: int = 40,
                           earnings_date: str | None = None,
                           iv_context: dict[str, Any] | None = None,
                           max_candidates_per_bucket: int = 3) -> dict[str, Any]:
    """Deep-ITM (stock-replacement) call research per DTE bucket. EDUCATIONAL_ONLY.

    Per bucket: nearest expiration, candidate strikes with delta inside
    ``delta_range`` (greeks path) or, when the chain carries no usable
    greeks, ITM-depth (S-K)/S inside ITM_PCT_PROXY_RANGE (proxy path —
    reported via selection_mode). Per candidate: spread / OI / volume /
    earnings-before-expiry flags, extrinsic value, breakeven, max loss, and
    capital vs 100 shares. Unavailable chain data degrades honestly.

    ``iv_context`` (injectable for tests; computed from iv_history when None)
    is ADVISORY context — {atm_iv, iv_rank, percentile, verdict} or an honest
    {"available": False, ...}. It informs downstream scoring/disclosure and
    never gates anything here.
    """
    sym = (symbol or "").strip().upper()
    snap = snapshot if snapshot is not None else fetch_chain_snapshot(
        sym, strike_count=strike_count)
    base = {"strategy": "deep_itm_call", "symbol": sym,
            "educational_only": True, "banner": EDUCATIONAL_BANNER,
            "source": snap.get("source", CHAIN_SOURCE),
            "generated_at": datetime.now(timezone.utc).isoformat()}
    if not snap.get("available"):
        return {**base, "available": False,
                "reason": snap.get("reason") or "chain data unavailable"}
    spot = _f(snap.get("underlying_price"))
    if not spot or spot <= 0:
        return {**base, "available": False,
                "reason": "chain carried no underlying price — refusing to "
                          "compute moneyness from fabricated data"}

    lo, hi = float(min(delta_range)), float(max(delta_range))
    earnings = earnings_date if earnings_date is not None else next_earnings_date(sym)

    buckets: list[dict[str, Any]] = []
    modes_used: set[str] = set()
    for target in dte_buckets:
        exp = _bucket_expiration(snap, int(target))
        if exp is None:
            buckets.append({"target_dte": int(target), "available": False,
                            "reason": "no expiration near this DTE bucket"})
            continue
        itm_calls = [c for c in exp["contracts"]
                     if c.get("side") == "call" and c["strike"] < spot]
        with_delta = [c for c in itm_calls if c.get("delta") is not None]
        if with_delta:
            mode = "delta"
            in_band = [c for c in with_delta if lo <= c["delta"] <= hi]
        else:
            mode = "itm_pct_proxy"
            plo, phi = ITM_PCT_PROXY_RANGE
            in_band = [c for c in itm_calls
                       if plo <= (spot - c["strike"]) / spot <= phi]
        modes_used.add(mode)
        if not in_band:
            buckets.append({
                "target_dte": int(target), "exp": exp["exp"], "dte": exp["dte"],
                "selection_mode": mode, "available": False,
                "reason": (f"no ITM calls with delta in [{lo}, {hi}]" if mode == "delta"
                           else "no ITM calls inside the ITM%-depth proxy band")})
            continue
        ranked = sorted(in_band, key=lambda c: (-int(c.get("liquidity_score") or 0),
                                                -c["strike"]))
        rows = [_candidate_row(c, spot, exp["exp"], earnings)
                for c in ranked[:max(1, int(max_candidates_per_bucket))]]
        buckets.append({"target_dte": int(target), "exp": exp["exp"],
                        "dte": exp["dte"], "selection_mode": mode,
                        "available": True, "selected": rows[0],
                        "candidates": rows})

    return {**base, "available": True, "underlying_price": spot,
            "delta_range": [lo, hi],
            "selection_modes_used": sorted(modes_used),
            "next_earnings_date": earnings,
            "iv_context": iv_context if iv_context is not None
                          else _iv_context_for(sym, snap),
            "dte_buckets": buckets,
            "chain_liquidity_score": snap.get("liquidity_score"),
            "feasibility": (snap.get("strategy_feasibility") or {}).get("deep_itm_call")}
