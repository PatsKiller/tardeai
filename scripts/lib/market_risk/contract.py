"""Market Risk Engine contract — the shapes every module of DSN-20261031-market-risk-engine exchanges.

One file, so parallel builders agree on the seams:

* A **category module** lives at ``scripts/lib/market_risk/categories/<category>.py`` and exposes
  ``evaluate(ctx: EvalContext) -> CategoryObservation``. It reads only through ``ctx.reader`` (a ``DataReader``),
  never opens its own connection or provider (AGENTS.md §24.1 single source; tests inject a fixture reader).
* ``scoring.compose(observations, policy, *, prior=None, now=...) -> RiskAssessment`` turns observations into a
  composite score, tier, confirming count, decay and hysteresis.
* ``exposure`` / ``risk_budget`` produce ``PortfolioContext``; ``scoring.apply_uplift`` lifts at most one tier.
* ``explain.attribute(assessment) -> list[Contributor]`` gives the top five with point attribution.

Advisory only (``MBI_BEHAVIOR = 0``): no type here carries a size, order, stop price or weight, and
``assert_no_behavior_fields`` refuses any payload that does. Unknown is not zero: a category without data is
``UNKNOWN`` with ``score=None`` and is shown as such.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal, Protocol

SCHEMA_OBSERVATION = "MarketRiskCategoryObservation@v1"
SCHEMA_ASSESSMENT = "MarketRiskAssessment@v1"

CATEGORIES: tuple[str, ...] = (
    "technical",
    "breadth",
    "volatility",
    "options_flow",
    "macro_credit",
    "cross_asset",
    "event",
    "seasonal",
    "extended_hours",
)
# Supplementary modules feed the nine categories above rather than scoring on their own:
#   institutional -> options_flow / sentiment divergence; correlations -> cross_asset;
#   ai_concentration -> technical (participation) and event (earnings sensitivity); opening_shock -> extended_hours.

State = Literal["CALM", "IMPROVING", "WARN", "STRESS", "UNKNOWN"]
STATES: tuple[str, ...] = ("CALM", "IMPROVING", "WARN", "STRESS", "UNKNOWN")
Tier = Literal["GREEN", "NONE", "BLUE", "YELLOW", "ORANGE", "RED"]
TIERS: tuple[str, ...] = ("GREEN", "NONE", "BLUE", "YELLOW", "ORANGE", "RED")  # ascending severity after GREEN

BEHAVIOR_FIELDS: frozenset[str] = frozenset(
    {
        "size",
        "qty",
        "quantity",
        "shares",
        "order",
        "order_type",
        "limit_price",
        "stop_price",
        "stop_level",
        "new_stop",
        "weight",
        "target_weight",
        "position_size",
        "notional",
        "allocation",
        "buy",
        "sell",
    }
)


@dataclass(frozen=True)
class Evidence:
    """One fact behind an observation: what, value, when, where it came from."""

    label: str  # "QQQ put/call volume vs 20-session median"
    value: Any  # 3.31 or "WEAKENING"
    as_of: str | None  # ISO-8601 UTC of the source row
    source: str  # "option_chain_snapshots", "fred_economic_series:BAMLH0A0HYM2", ...
    detail: str = ""  # phone-length phrase: "2.9x median"


@dataclass(frozen=True)
class CategoryObservation:
    category: str  # one of CATEGORIES
    state: State
    score: float | None  # 0-100 within the category; None when UNKNOWN
    observed_at: str  # ISO-8601 UTC of the newest input used
    headline: str  # phone-length: "QQQ P/C vol 3.31 (2.9x median) 10:00 ET"
    evidence: tuple[Evidence, ...] = ()
    stale_after_hours: float | None = None
    reason_unknown: str | None = None  # required when state == UNKNOWN
    schema: str = SCHEMA_OBSERVATION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Contributor:
    category: str
    points: float  # signed contribution to the composite
    headline: str
    as_of: str | None


@dataclass(frozen=True)
class PortfolioContext:
    """Exposure-aware severity inputs. Symbols and distances only — never sizes (MBI_BEHAVIOR = 0)."""

    vulnerability: float | None  # 0-100; None when positions are unreadable
    budget_breaches: tuple[dict[str, Any], ...] = ()  # {budget, limit, actual, ratio, drivers:[symbol]}
    drivers: tuple[dict[str, Any], ...] = ()  # {symbol, reason, stop_distance_pct?}
    as_of: str | None = None
    note: str = ""


@dataclass
class RiskAssessment:
    as_of: str
    score: float | None
    market_score: float | None
    tier: Tier
    market_tier: Tier
    confirming: int
    observations: list[CategoryObservation]
    contributors: list[Contributor] = field(default_factory=list)
    uplift: dict[str, Any] | None = None
    portfolio: PortfolioContext | None = None
    probabilities: dict[str, Any] = field(default_factory=dict)
    analogs: list[dict[str, Any]] = field(default_factory=list)  # explanation only, never scored
    deescalates_if: str = ""
    hysteresis: dict[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA_ASSESSMENT

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        assert_no_behavior_fields(d)
        return d


class DataReader(Protocol):
    """Read-only access the engine is given. Production: scripts/lib/market_risk/reader.py over Postgres/projections.
    Tests and replay: a fixture reader. Every method returns rows with an ``as_of``/``observed_at`` field."""

    def quotes(self, symbols: Iterable[str], *, start: datetime, end: datetime) -> list[dict[str, Any]]: ...
    def daily_bars(self, symbols: Iterable[str], *, sessions: int, end: datetime) -> list[dict[str, Any]]: ...
    def session_opens(self, symbols: Iterable[str], *, sessions: int, end: datetime) -> list[dict[str, Any]]:
        """Regular-session opening prints, each knowable from that session's 09:30 ET open (``as_of``), never earlier.
        Optional: a reader without it makes the overnight-gap proxy UNKNOWN."""
        ...

    def regime_indicators(self, *, end: datetime) -> list[dict[str, Any]]: ...
    def fred(self, series: Iterable[str], *, observations: int, end: datetime) -> list[dict[str, Any]]: ...
    def option_snapshots(self, symbols: Iterable[str], *, sessions: int, end: datetime) -> list[dict[str, Any]]: ...
    def sector_states(self, *, end: datetime) -> list[dict[str, Any]]: ...
    def earnings_calendar(
        self, *, start: datetime, end: datetime, now: datetime | None = None
    ) -> list[dict[str, Any]]: ...
    def macro_calendar(self, *, start: datetime, end: datetime) -> list[dict[str, Any]]: ...


@dataclass
class EvalContext:
    now: datetime  # tz-aware; replay passes the historical instant
    reader: DataReader
    policy: dict[str, Any]  # config/market_risk_policy.yaml (load via policy.load_policy)
    session: str = "unknown"  # premarket | regular | afterhours | closed
    extras: dict[str, Any] = field(default_factory=dict)


def unknown(category: str, now: datetime, reason: str) -> CategoryObservation:
    """The honest empty observation: shown as UNKNOWN, never as zero."""
    return CategoryObservation(
        category=category,
        state="UNKNOWN",
        score=None,
        observed_at=now.isoformat(),
        headline=f"{category}: not measured ({reason})",
        reason_unknown=reason,
    )


def assert_no_behavior_fields(obj: Any, path: str = "") -> None:
    """Raise if any key anywhere in ``obj`` is a behaviour field (size, order, stop value, weight)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in BEHAVIOR_FIELDS:
                raise ValueError(f"behaviour field {path + '.' + str(k) if path else k!r} in market-risk payload")
            assert_no_behavior_fields(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_no_behavior_fields(v, f"{path}[{i}]")
