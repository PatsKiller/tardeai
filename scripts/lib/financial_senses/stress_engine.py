"""Deterministic portfolio stress engine.

Calculates scenario P&L. It does not issue trades and it does not invent
sensitivity coefficients. Positions are modeled in three tiers:

  TIER 1  direct deterministic (explicit sector shock / cash)
  TIER 2  mapped exposure (verified sector mapping)
  TIER 3  sensitivity model (only where the coefficient has a governed source)

Anything without a valid input is left UNAVAILABLE (unmodeled), never
fabricated. `unmodeled_value` is mandatory output. Pure module: no network, no
database.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .provider import BaseProvider, Capability
from .result import Fact, FinancialSenseResult, Quality, STATUS_OK
from .source_governance import SOURCE_APPROVED_MARKET_DATA, SOURCE_MODEL_INFERENCE, grade_for_source

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
SCENARIO_LIBRARY: dict[str, StressScenario] = {
    "broad_equity_minus_10": StressScenario(
        scenario_id="broad_equity_minus_10",
        name="Broad equity -10%",
        shock_type="market",
        shocks={"equity_market_pct": -10.0},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "broad_equity_minus_20": StressScenario(
        scenario_id="broad_equity_minus_20",
        name="Broad equity -20%",
        shock_type="market",
        shocks={"equity_market_pct": -20.0},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "nasdaq_minus_25": StressScenario(
        scenario_id="nasdaq_minus_25",
        name="Nasdaq -25%",
        shock_type="market",
        shocks={"nasdaq_pct": -25.0},
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
        shocks={"oil_pct": 40.0},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "oil_minus_40": StressScenario(
        scenario_id="oil_minus_40",
        name="Oil -40%",
        shock_type="commodity",
        shocks={"oil_pct": -40.0},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
    "usd_plus_10": StressScenario(
        scenario_id="usd_plus_10",
        name="USD +10%",
        shock_type="fx",
        shocks={"usd_pct": 10.0},
        assumption_source="deterministic_template",
        quality="HIGH",
    ),
}


def scenario_library() -> list[dict]:
    return [s.to_dict() for s in SCENARIO_LIBRARY.values()]


def get_scenario(scenario_id: str) -> Optional[StressScenario]:
    return SCENARIO_LIBRARY.get(scenario_id)


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

    Exactly one method is applied (precedence order) so overlapping shocks are
    never double-counted.
    """
    if position.get("cash_like"):
        return {"tier": TIER_CASH, "return": 0.0, "method": "cash_shock_zero"}

    sector = position.get("sector")
    sector_shocks = shocks.get("sector_shocks") or {}
    if sector and sector in sector_shocks:
        try:
            return {
                "tier": TIER_SECTOR,
                "return": float(sector_shocks[sector]),
                "method": f"sector:{sector}",
            }
        except (TypeError, ValueError):
            return {"tier": TIER_UNAVAILABLE, "return": None, "reason": "invalid sector shock"}

    sensitivity = position.get("sensitivity") or {}
    for coeff_key, shock_key in SENSITIVITY_TO_SHOCK.items():
        shock = shocks.get(shock_key)
        if shock is None:
            continue
        coeff = _sourced(sensitivity, coeff_key)
        if coeff is not None:
            try:
                return {
                    "tier": TIER_SENSITIVITY,
                    "return": coeff * float(shock) / 100.0,
                    "method": f"sensitivity:{coeff_key}",
                }
            except (TypeError, ValueError):
                return {"tier": TIER_UNAVAILABLE, "return": None, "reason": "invalid shock"}

    duration = _sourced(sensitivity, "duration")
    rates_bps = shocks.get("rates_bps")
    if duration is not None and rates_bps is not None:
        try:
            return {
                "tier": TIER_SENSITIVITY,
                "return": -duration * float(rates_bps) / 10000.0,
                "method": "sensitivity:duration",
            }
        except (TypeError, ValueError):
            return {"tier": TIER_UNAVAILABLE, "return": None, "reason": "invalid rates shock"}

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

    portfolio: {"positions": [ {symbol, market_value, cash_like?, sector?,
                                 sensitivity?, factors?}, ... ]}
    scenario: {"scenario_id", "name"?, "shocks": {...}, ...}

    Returns the structured stress result. Invariants enforced:
      * cash shock = 0 (unless an explicit FX/cash scenario — none provided here)
      * sum(position modeled PnL) == modeled portfolio PnL
      * unmodeled positions remain explicit
      * coverage <= 100%
    """
    positions = portfolio.get("positions") or []
    shocks = scenario.get("shocks") or {}

    portfolio_value = 0.0
    per_position = []
    sector_contribution: dict[str, float] = {}
    factor_contribution: dict[str, float] = {}
    modeled_pnl = 0.0
    unmodeled_value = 0.0
    top_contributors = []

    for pos in positions:
        mv = float(pos.get("market_value") or 0.0)
        portfolio_value += mv
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
            entry["pnl"] = None
        else:
            pnl = mv * float(res["return"])
            entry["pnl"] = pnl
            modeled_pnl += pnl
            if res["tier"] == TIER_SECTOR and pos.get("sector"):
                sector_contribution[pos["sector"]] = (
                    sector_contribution.get(pos["sector"], 0.0) + pnl
                )
            if res.get("factor_contrib"):
                for fname, fp in res["factor_contrib"].items():
                    factor_contribution[fname] = factor_contribution.get(fname, 0.0) + mv * fp
        per_position.append(entry)
        top_contributors.append(entry)

    coverage_pct = 100.0
    if portfolio_value > 0:
        coverage_pct = max(0.0, min(100.0, (portfolio_value - unmodeled_value) / portfolio_value * 100.0))

    estimated_pnl = round(modeled_pnl, 4)
    estimated_pct = round(modeled_pnl / portfolio_value * 100.0, 4) if portfolio_value else 0.0

    losses = sorted([p for p in per_position if p["pnl"] is not None and p["pnl"] < 0], key=lambda p: p["pnl"])
    gains = sorted([p for p in per_position if p["pnl"] is not None and p["pnl"] > 0], key=lambda p: p["pnl"], reverse=True)

    return {
        "portfolio_value": round(portfolio_value, 4),
        "estimated_pnl": estimated_pnl,
        "estimated_pct": estimated_pct,
        "cash_buffer_effect": 0.0,
        "top_loss_contributors": losses,
        "top_gain_contributors": gains,
        "sector_contribution": {k: round(v, 4) for k, v in sector_contribution.items()},
        "factor_contribution": {k: round(v, 4) for k, v in factor_contribution.items()},
        "unmodeled_value": round(unmodeled_value, 4),
        "coverage_pct": round(coverage_pct, 4),
        "positions": per_position,
        "assumptions": [
            "cash shock is zero unless an explicit FX/cash scenario is provided",
            "each position is modeled by exactly one tier (no double counting)",
            "sensitivity coefficients require a governed source; unsourced coefficients are unmodeled",
        ],
        "limitations": [
            f"{unmodeled_value:.2f} of portfolio value is unmodeled (no sourced sensitivity)",
        ],
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
        except Exception as exc:
            return self._unavailable("risk.stress_portfolio", f"stress failed: {exc}")
        r = self._ok("risk.stress_portfolio")
        r.data = result
        r.quality = Quality(
            grade=grade_for_source(SOURCE_APPROVED_MARKET_DATA),
            completeness="PARTIAL" if result["unmodeled_value"] > 0 else "COMPLETE",
        )
        r.facts.append(
            Fact(
                key="stress_estimated_pnl",
                value=result["estimated_pnl"],
                source_type=SOURCE_MODEL_INFERENCE,
                source_ids=[str(scenario.get("scenario_id") or "custom")],
                as_of=r.requested_at,
                quality=grade_for_source(SOURCE_APPROVED_MARKET_DATA),
                notes="model inference; not a fact about the world",
            )
        )
        return r
