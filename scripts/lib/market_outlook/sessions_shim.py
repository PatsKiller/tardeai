"""One import point for the NYSE session clock the outlook needs (``scripts/lib/market_risk/sessions.py``).

The outlook must not keep a second session calendar: freshness decay (§2.5) and category staleness (§2.9) are both
measured on the *market* clock — weekend and holiday hours do not age a Friday close — and that clock, including the
18:00 Sunday futures reopen, already lives in the Market Risk Engine.
"""

from __future__ import annotations

from datetime import date, datetime

try:  # the package runs both as scripts.lib.market_outlook and as lib.market_outlook
    from scripts.lib.market_risk.sessions import (  # type: ignore[import-not-found]
        is_trading_day,
        last_closed_session,
        market_hours_between,
    )
except ImportError:  # pragma: no cover - scripts/ on sys.path
    from lib.market_risk.sessions import (  # type: ignore[no-redef]
        is_trading_day,
        last_closed_session,
        market_hours_between,
    )

__all__ = ["is_trading_day", "last_closed_session", "market_hours_between", "session_label_et"]


def session_label_et(now: datetime) -> str:
    """The record's ``session_clock``: premarket / regular / afterhours / overnight / closed (§4.6)."""
    try:
        from scripts.lib.market_risk.sessions import session_label  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        from lib.market_risk.sessions import session_label  # type: ignore[no-redef]

    return session_label(now)


def coerce_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
