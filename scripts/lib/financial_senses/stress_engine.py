"""Deterministic portfolio stress engine.

Calculates scenario P&L. It does not issue trades and it does not invent
sensitivity coefficients. Positions are modeled in tiers:

  TIER 1  direct deterministic (explicit sector shock / cash)
  TIER 2  mapped exposure (verified sector mapping)
  TIER 3  sensitivity model (only where the coefficient has a governed source)

Anything without a valid input is left UNAVAILABLE (unmodeled), never
fabricated. `unmodeled_value` is mandatory output.

Shock unit contract
-------------------
All equity/sector/factor/oil/USD shocks are DECIMAL RETURNS by default
(-0.20 == -20%). Callers may be explicit with a ShockValue dict:
    {"value": -20.0, "unit": "PERCENT"}    -> -0.20
    {"value": -0.20, "unit": "DECIMAL_RETURN"} -> -0.20
Rates / credit shocks are BASIS_POINTS by default and accept PERCENT or
DECIMAL_RETURN via an explicit unit. Invalid units or out-of-range values
raise ValueError (mapped to INVALID_REQUEST by the provider), never a silent
wrong-size shock.

Pure module: no network, no database.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .provider import BaseProvider, Capability
from .result import FinancialSenseResult, ModelEstimate, Quality, STATUS_OK
from .source_governance import SOURCE_APPROVED_MARKET_DATA, grade_for_source

# Stress tiers.
TIER_CASH = "CASH"
TIER_SECTOR = "MAPPED_SECTOR"
TIER_SENSITIVITY = "SENSITIVITY_MODEL"
TIER_FACTOR = "FACTOR_MODEL"
TIER_UNAVAILABLE = "UNAVAILABLE"

# Which sensitivity coefficient responds to which scenario shock.
SENSITIVITY_TO_SHOCK: dict[str, str] = {
    "equity_market_beta": "equity_market_pct",
    "nasdaq_beta": "nasdaq_pct",
    "oil_beta": "oil_pct",
    "usd_beta": "usd_pct",
}

# A sensitivity coefficient must carry a governed source to be used.
VALID_SENSITIVITY_SOURCES = frozenset(
    {
        "approved_vendor",
        "verified_regression",
        "explicit_etf_lookthrough",
        "sector_industry_mapping",
        "duration_credit_characteristics",
    }
)

# Shock units.
SHOCK_PERCENT = "PERCENT"
SHOCK_DECIMAL_RETURN = "DECIMAL_RETURN"
SHOCK_BASIS_POINTS = "BASIS_POINTS"
VALID_SHOCK_UNITS = frozenset({SHOCK_PERCENT, SHOCK_DECIMAL_RETURN, SHOCK_BASIS_POINTS})

# Return shocks (equity/sector/factor/oil/usd) — decimal returns by default.
RETURN_SHOCK_KEYS = frozenset({"equity_market_pct", "nasdaq_pct", "oil_pct", "usd_pct"})
# Rates / credit shocks — basis points by default.
BPS_SHOCK_KEYS = frozenset({"rates_bps", "credit_spread_bps"})

# Sanity range (fail-closed on mis-united inputs).
RETURN_MIN = -1.0   # -100%
RETURN_MAX = 10.0   # +1000%
BPS_MIN = -10000.0  # -100%
BPS_MAX = 10000.0   # +100%


class InvalidShock(ValueError):
    """A shock value/unit is malformed or out of range."""


@dataclass
class StressScenario:
    """StressScenario@v1."""

    scenario_id: str
    name: str = ""
    description: str = ""
    shock_type: str = "custom"
    created_at: Optional[str] = None
    shocks: dict = field(default_factory=dict)
    assumption_source: Optional[str] = None
    quality: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return asdict(self)


# ── Scenario library (safe deterministic templates) ─────────────────────────
# Return shocks use decimal returns (-0.10 == -10%). Rates/credit use bps.
SCENARIO_LIBRARY: dict[str, StressScenario] = {
    "broad_equity_minus_10": StressScenario(
        scenario_id="broad_equity_minus_10",
        name="Broad equity -10%",
        shock_type="market",
        shocks={"equity_market_pct": -0.10},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "broad_equity_minus_20": StressScenario(
        scenario_id="broad_equity_minus_20",
        name="Broad equity -20%",
        shock_type="market",
        shocks={"equity_market_pct": -0.20},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "nasdaq_minus_25": StressScenario(
        scenario_id="nasdaq_minus_25",
        name="Nasdaq -25%",
        shock_type="market",
        shocks={"nasdaq_pct": -0.25},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "rates_plus_100bp": StressScenario(
        scenario_id="rates_plus_100bp",
        name="Rates +100bp",
        shock_type="rates",
        shocks={"rates_bps": 100.0},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "rates_minus_150bp": StressScenario(
        scenario_id="rates_minus_150bp",
        name="Rates -150bp",
        shock_type="rates",
        shocks={"rates_bps": -150.0},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "credit_plus_200bp": StressScenario(
        scenario_id="credit_plus_200bp",
        name="Credit spreads +200bp",
        shock_type="credit",
        shocks={"credit_spread_bps": 200.0},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "oil_plus_40": StressScenario(
        scenario_id="oil_plus_40",
        name="Oil +40%",
        shock_type="commodity",
        shocks={"oil_pct": 0.40},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "oil_minus_40": StressScenario(
        scenario_id="oil_minus_40",
        name="Oil -40%",
        shock_type="commodity",
        shocks={"oil_pct": -0.40},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "usd_plus_10": StressScenario(
        scenario_id="usd_plus_10",
        name="USD +10%",
        shock_type="fx",
        shocks={"usd_pct": 0.10},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
}


def scenario_library() -> list[dict]:
    return [s.to_dict() for s in SCENARIO_LIBRARY.values()]


def get_scenario(scenario_id: str) -> Optional[StressScenario]:
    return SCENARIO_LIBRARY.get(scenario_id)


def _shock_parts(value: Any):
    """Return (raw, unit) from a shock value (number or {value, unit})."""
    if isinstance(value, dict):
        return value.get("value"), str(value.get("unit") or "").strip().upper()
    return value, ""


def normalize_return(value: Any, default_unit: str = SHOCK_DECIMAL_RETURN) -> float:
    """Normalize a return shock to a decimal return (e.g. -0.20 == -20%)."""
    raw, unit = _shock_parts(value)
    unit = unit or default_unit
    if unit not in VALID_SHOCK_UNITS:
        raise InvalidShock(f"invalid shock unit {unit!r}")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise InvalidShock(f"invalid shock value {raw!r}")
    if unit == SHOCK_PERCENT:
        v = v / 100.0
    elif unit == SHOCK_BASIS_POINTS:
        v = v / 10000.0
    if v < RETURN_MIN or v > RETURN_MAX:
        raise InvalidShock(f"return shock {v} out of range [{RETURN_MIN}, {RETURN_MAX}]")
    return v


def normalize_bps(value: Any, default_unit: str = SHOCK_BASIS_POINTS) -> float:
    """Normalize a rates/credit shock to basis points."""
    raw, unit = _shock_parts(value)
    unit = unit or default_unit
    if unit not in VALID_SHOCK_UNITS:
        raise InvalidShock(f"invalid shock unit {unit!r}")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise InvalidShock(f"invalid shock value {raw!r}")
    if unit == SHOCK_PERCENT:
        v = v * 100.0
    elif unit == SHOCK_DECIMAL_RETURN:
        v = v * 10000.0
    if v < BPS_MIN or v > BPS_MAX:
        raise InvalidShock(f"bps shock {v} out of range [{BPS_MIN}, {BPS_MAX}]")
    return v


def _normalize_shocks(shocks: dict) -> dict:
    """Validate + normalize all shocks up front. Raises InvalidShock."""
    out: dict = {}
    for k in RETURN_SHOCK_KEYS:
        if shocks.get(k) is not None:
            out[k] = normalize_return(shocks[k])
    for k in BPS_SHOCK_KEYS:
        if shocks.get(k) is not None:
            out[k] = normalize_bps(shocks[k])
    sector = shocks.get("sector_shocks") or {}
    if sector:
        out["sector_shocks"] = {str(s): normalize_return(v) for s, v in sector.items()}
    factor = shocks.get("factor_shocks") or {}
    if factor:
        out["factor_shocks"] = {str(f): normalize_return(v) for f, v in factor.items()}
    return out


def _sourced(sensitivity: Optional[dict], key: str) -> Optional[float]:
    """Return a sensitivity coefficient only if it has a governed source."""
    if not isinstance(sensitivity, dict):
        return None
    coeff = sensitivity.get(key)
    if not isinstance(coeff, dict):
        return None
    src = str(coeff.get("source") or "").strip().lower()
    if src not in VALID_SENSITIVITY_SOURCES:
        return None
    try:
        return float(coeff["value"])
    except (KeyError, TypeError, ValueError):
        return None


def _position_return(position: dict, shocks: dict) -> dict:
    """Determine a single position's modeled return and the tier that produced it.

    `shocks` are already normalized (decimal returns / bps). Exactly one method
    is applied (precedence order) so overlapping shocks are never double-counted.
    """
    if position.get("cash_like"):
        return {"tier": TIER_CASH, "return": 0.0, "method": "cash_shock_zero"}

    sector = position.get("sector")
    sector_shocks = shocks.get("sector_shocks") or {}
    if sector and sector in sector_shocks:
        return {
            "tier": TIER_SECTOR,
            "return": float(sector_shocks[sector]),
            "method": f"sector:{sector}",
        }

    sensitivity = position.get("sensitivity") or {}
    for coeff_key, shock_key in SENSITIVITY_TO_SHOCK.items():
        shock = shocks.get(shock_key)
        if shock is None:
            continue
        coeff = _sourced(sensitivity, coeff_key)
        if coeff is not None:
            return {
                "tier": TIER_SENSITIVITY,
                "return": coeff * float(shock),
                "method": f"sensitivity:{coeff_key}",
            }

    duration = _sourced(sensitivity, "duration")
    rates_bps = shocks.get("rates_bps")
    if duration is not None and rates_bps is not None:
        return {
            "tier": TIER_SENSITIVITY,
            "return": -duration * float(rates_bps) / 10000.0,
            "method": "sensitivity:duration",
        }

    factor_shocks = shocks.get("factor_shocks") or {}
    factors = position.get("factors") or {}
    modeled_factors = {}
    for fname, fshock in factor_shocks.items():
        fl = factors.get(fname)
        if not isinstance(fl, dict):
            continue
        src = str(fl.get("source") or "").strip().lower()
        if src not in VALID_SENSITIVITY_SOURCES:
            continue
        try:
            modeled_factors[fname] = float(fl["loading"]) * float(fshock)
        except (KeyError, TypeError, ValueError):
            continue
    if modeled_factors:
        return {
            "tier": TIER_FACTOR,
            "return": sum(modeled_factors.values()),
            "method": "factors",
            "factor_contrib": modeled_factors,
        }

    return {"tier": TIER_UNAVAILABLE, "return": None, "reason": "no sourced sensitivity"}


def stress_portfolio(
    portfolio: dict,
    scenario: dict,
) -> dict:
    """Run a deterministic stress scenario over a portfolio.

    portfolio: {"positions": [...], "portfolio_nav"?}
    scenario: {"scenario_id", "name"?, "shocks": {...}, ...}

    Returns the structured stress result. Invariants enforced:
      * cash shock = 0
      * sum(position modeled PnL) == modeled portfolio PnL
      * unmodeled positions remain explicit
      * coverage <= 100%
      * gross/net exposure, modeled/unmodeled value, and portfolio_nav are kept
        separate; estimated_pct is unavailable when NAV cannot be established
        (shorts present and no explicit portfolio_nav)
    """
    positions = portfolio.get("positions") or []
    shocks = _normalize_shocks(scenario.get("shocks") or {})

    per_position = []
    sector_contribution: dict[str, float] = {}
    factor_contribution: dict[str, float] = {}
    modeled_pnl = 0.0
    unmodeled_value = 0.0
    modeled_value = 0.0
    gross_exposure = 0.0
    net_exposure = 0.0
    unmodeled_gross = 0.0
    modeled_gross = 0.0
    has_shorts = False

    for pos in positions:
        mv = float(pos.get("market_value") or 0.0)
        if mv < 0:
            has_shorts = True
        gross_exposure += abs(mv)
        net_exposure += mv
        res = _position_return(pos, shocks)
        entry = {
            "symbol": pos.get("symbol"),
            "market_value": mv,
            "tier": res["tier"],
            "method": res.get("method"),
            "return": res.get("return"),
            "pnl": None,
            "reason": res.get("reason"),
        }
        if res["tier"] == TIER_UNAVAILABLE:
            unmodeled_value += mv
            unmodeled_gross += abs(mv)
            entry["pnl"] = None
        else:
            pnl = mv * float(res["return"])
            entry["pnl"] = pnl
            modeled_pnl += pnl
            modeled_value += mv
            modeled_gross += abs(mv)
            if res["tier"] == TIER_SECTOR and pos.get("sector"):
                sector_contribution[pos["sector"]] = (
                    sector_contribution.get(pos["sector"], 0.0) + pnl
                )
            if res.get("factor_contrib"):
                for fname, fp in res["factor_contrib"].items():
                    factor_contribution[fname] = factor_contribution.get(fname, 0.0) + mv * fp
        per_position.append(entry)

    coverage_pct = 100.0
    if gross_exposure > 0:
        coverage_pct = max(0.0, min(100.0, (gross_exposure - unmodeled_gross) / gross_exposure * 100.0))

    estimated_pnl = round(modeled_pnl, 4)

    # NAV: explicit portfolio_nav wins; otherwise net exposure only when there
    # are no shorts (signed market values are exposures, not necessarily equity).
    nav_input = portfolio.get("portfolio_nav")
    portfolio_nav = None
    if nav_input is not None:
        try:
            portfolio_nav = float(nav_input)
        except (TypeError, ValueError):
            portfolio_nav = None
    if portfolio_nav is None and not has_shorts:
        portfolio_nav = round(net_exposure, 4)

    estimated_pct = None
    if portfolio_nav is not None and portfolio_nav != 0:
        estimated_pct = round(estimated_pnl / portfolio_nav * 100.0, 4)

    losses = sorted([p for p in per_position if p["pnl"] is not None and p["pnl"] < 0], key=lambda p: p["pnl"])
    gains = sorted([p for p in per_position if p["pnl"] is not None and p["pnl"] > 0], key=lambda p: p["pnl"], reverse=True)

    limitations = [
        f"{round(unmodeled_value, 2)} of net exposure is unmodeled (no sourced sensitivity)",
    ]
    if portfolio_nav is None and has_shorts:
        limitations.append(
            "estimated_pct unavailable: shorts present and no explicit portfolio_nav provided"
        )
    limitations.append(
        "cash_buffer_effect not computed: no FX/cash shock scenario is modeled; "
        "a 0 would imply analysis that was not performed"
    )

    return {
        "portfolio_value": round(net_exposure, 4),
        "portfolio_nav": portfolio_nav,
        "gross_exposure": round(gross_exposure, 4),
        "net_exposure": round(net_exposure, 4),
        "modeled_value": round(modeled_value, 4),
        "unmodeled_value": round(unmodeled_value, 4),
        "modeled_net_exposure": round(modeled_value, 4),
        "modeled_gross_exposure": round(modeled_gross, 4),
        "unmodeled_net_exposure": round(unmodeled_value, 4),
        "unmodeled_gross_exposure": round(unmodeled_gross, 4),
        "estimated_pnl": estimated_pnl,
        "estimated_pct": estimated_pct,
        "cash_buffer_effect": None,
        "top_loss_contributors": losses,
        "top_gain_contributors": gains,
        "sector_contribution": {k: round(v, 4) for k, v in sector_contribution.items()},
        "factor_contribution": {k: round(v, 4) for k, v in factor_contribution.items()},
        "coverage_pct": round(coverage_pct, 4),
        "positions": per_position,
        "assumptions": [
            "equity/sector/factor/oil/USD shocks are decimal returns (-0.20 == -20%)",
            "rates/credit shocks are basis points",
            "each position is modeled by exactly one tier (no double counting)",
            "sensitivity coefficients require a governed source; unsourced coefficients are unmodeled",
        ],
        "limitations": limitations,
    }


class PortfolioStressProvider(BaseProvider):
    name = "stress"
    version = "1.0.0"
    source_type = SOURCE_APPROVED_MARKET_DATA

    def _capabilities(self) -> list[Capability]:
        return [
            Capability(
                "risk.stress_portfolio",
                "READ_ONLY",
                input_schema={
                    "portfolio": "object",
                    "scenario": "object|string (scenario_id)",
                },
            )
        ]

    def _query(self, capability: str, request: dict) -> FinancialSenseResult:
        if capability != "risk.stress_portfolio":
            return self._unavailable(capability, "unknown capability")
        portfolio = request.get("portfolio")
        scenario = request.get("scenario")
        if not isinstance(portfolio, dict) or not portfolio.get("positions"):
            return self._invalid("risk.stress_portfolio", "portfolio.positions required")
        if isinstance(scenario, str):
            sc = get_scenario(scenario)
            if sc is None:
                return self._invalid("risk.stress_portfolio", f"unknown scenario {scenario!r}")
            scenario = sc.to_dict()
        if not isinstance(scenario, dict):
            return self._invalid("risk.stress_portfolio", "scenario required")
        try:
            result = stress_portfolio(portfolio, scenario)
        except InvalidShock as exc:
            return self._invalid("risk.stress_portfolio", str(exc))
        except Exception as exc:
            return self._unavailable("risk.stress_portfolio", f"stress failed: {exc}")
        r = self._ok("risk.stress_portfolio")
        r.data = result
        # Completeness derives from GROSS unmodeled exposure, never signed net
        # exposure: an unmodeled short (or an offsetting unmodeled long/short)
        # must still be reported as PARTIAL, not COMPLETE.
        completeness = (
            "PARTIAL" if result["unmodeled_gross_exposure"] > 0 else "COMPLETE"
        )
        r.quality = Quality(
            grade=grade_for_source(SOURCE_APPROVED_MARKET_DATA),
            completeness=completeness,
        )
        # Stress estimated P&L is a MODEL ESTIMATE, never a world fact.
        r.add_estimate(
            ModelEstimate(
                key="stress_estimated_pnl",
                value=result["estimated_pnl"],
                method=f"deterministic_scenario:{str(scenario.get('scenario_id') or 'custom')}",
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_APPROVED_MARKET_DATA),
                notes="model inference; not a fact about the world",
            )
        )
        return r
