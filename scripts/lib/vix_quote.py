"""One accessor for the newest VIX observation. Every VIX consumer reads here (LQ-20261107-1690).

Before this module the fleet had four disagreeing VIX clocks, each with its own staleness rule:

* the Market Risk Volatility category read a DAILY close and called it fresh for 32 h, so a VIX that had
  moved overnight still graded ``CALM``;
* the base-rate conditions bucketed "today's" VIX from yesterday's close;
* the Home card printed the regime collector's ``vix_close`` snapshot (the operator saw "VIX 24.1 ... 12 h old");
* the CIO brain printed the FRED ``VIXCLS`` official close, published with a lag (the operator saw 28.18).

They now all read this module and get ONE answer: the newest admissible observation --- the 15-minute Schwab
``$VIX`` continuous feed when it is landing, otherwise the newest stored observation --- with its ``as_of``,
its ``source``, its age, and whether it may be read as the CURRENT VIX. Nothing here invents a value, and
nothing returns a bare float.

There is exactly one freshness rule in the fleet, and it is not re-implemented here: :func:`read` delegates to
:func:`lib.vix_headline.vix_headline`, which reads :func:`lib.market_regime.vix_complex.complex_record` under
``session_fresh_after_minutes`` / ``fresh_after_hours`` from ``config/market_regime_vix_complex.yaml``
(LQ-20261107-1610 / LQ-20261107-1669, operator 2026-11-09 14:50 ET: VIX refreshes every 15 min through the
weekday, and anything older than 30 min is STALE with its time, on every surface). ``measured`` is true only
for the ``FRESH`` state, so a consumer can never grade "calm" on a stale print. A read failure or an absent
store is ``UNAVAILABLE`` with its type named --- never a value, never another source, never a zero.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

SCHEMA = "VixQuote@v1"
#: The one state in which a value may be read as the CURRENT VIX.
MEASURED_STATE = "FRESH"

try:
    from lib import vix_headline as _headline
except ImportError:  # imported as scripts.lib.vix_quote
    from scripts.lib import vix_headline as _headline  # type: ignore[no-redef]


@dataclass(frozen=True)
class VixQuote:
    """The newest VIX observation and whether it may be read as the current index."""

    value: float | None
    as_of: str | None  # ISO-8601 with an explicit offset
    source: str | None  # "schwab", "fred_economic_series:VIXCLS", ...
    state: str  # FRESH | STALE | UNDATED | UNAVAILABLE (the shipped vix_headline vocabulary)
    age_hours: float | None
    measured: bool  # True only when state is FRESH and a value exists
    reason: str  # never empty; carries the headline's reason (with the print time and the age)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def evidence(self) -> dict[str, Any]:
        """The flat shape a CategoryObservation's Evidence / a contract row can carry."""
        return self.to_dict()


def _float(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def from_headline(headline: dict[str, Any] | None, *, now: datetime | None = None) -> VixQuote:
    """Convert one ``vix_headline.vix_headline`` result into a :class:`VixQuote`. Pure; never raises.

    ``now`` is accepted so a caller that already resolved its clock passes the same instant; the headline
    carries its own age, so nothing here re-derives it.
    """
    h = headline if isinstance(headline, dict) else {}
    value = _float(h.get("vix"))
    state = str(h.get("vix_state") or "UNAVAILABLE").strip().upper() or "UNAVAILABLE"
    if value is None and state == MEASURED_STATE:  # a FRESH state with no value is not a measurement
        state = "UNAVAILABLE"
    source = h.get("vix_source")
    as_of = h.get("vix_observation_time")
    reason = str(h.get("vix_reason") or "").strip()
    measured = state == MEASURED_STATE and value is not None
    if measured and not reason:
        reason = f"measured: VIX {value:.2f} from {source or 'unknown source'} at {as_of}"
    elif not measured and not reason:
        seen = f" (last {value:.2f} from {source} at {as_of})" if value is not None else ""
        reason = f"not measured: VIX is {state.lower()}{seen}"
    return VixQuote(
        value=value,
        as_of=str(as_of) if as_of else None,
        source=str(source) if source else None,
        state=state,
        age_hours=_float(h.get("vix_age_hours")),
        measured=measured,
        reason=reason,
    )


def read(
    *,
    query: Callable[..., Any] | None = None,
    conn: Any = None,
    now: datetime | None = None,
    cfg: dict[str, Any] | None = None,
) -> VixQuote:
    """Read the newest VIX observation through ``query(sql, params)`` or a DB-API ``conn``. Never raises.

    A failed read is reported as not measured --- never as a value, never as an exception that takes a
    consumer down.
    """
    at = now or datetime.now(timezone.utc)
    if query is None and conn is None:
        return VixQuote(
            value=None,
            as_of=None,
            source=None,
            state="UNAVAILABLE",
            age_hours=None,
            measured=False,
            reason="not measured: VIX accessor has no database handle",
        )
    try:
        headline = _headline.vix_headline(conn=conn, db_query=query, now=at, cfg=cfg)
    except Exception as exc:  # noqa: BLE001 --- an unreadable store is "not measured", not a crash of the caller
        return VixQuote(
            value=None,
            as_of=None,
            source=None,
            state="UNAVAILABLE",
            age_hours=None,
            measured=False,
            reason=f"not measured: VIX accessor read failed ({type(exc).__name__}: {exc})",
        )
    return from_headline(headline, now=at)
