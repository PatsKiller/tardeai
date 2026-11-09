"""vix_headline.py — the ONE VIX the Command Center shows, with its observation clock (LQ-20261107-1610).

Before this module the header tile and the CIO market-risk card answered "what is VIX?" from different places:

* the header (``api_v2._vix_observation``) took the trade-AI scanner's ``run_summary.vix`` first — a value the
  orchestrator's market snapshot fetched from its own Yahoo-first chain — and stamped it with the RUN's time, so a
  print carried from a previous session read as observed this morning; its fallback took the newest
  ``market_regime_indicators.vix_close`` row with no source filter (FINDING-LQ-1392: a ``yahoo_finance`` row served
  the header for a weekend);
* the card (``cio_truth.regime_for``) took the classifier snapshot's ``vix_close`` input, dated by the row's
  insert time, not by the quote's observation time.

Both now read :func:`vix_complex.complex_record` — the single Yahoo-free VIX read the market-risk engine already
uses (Schwab ``$VIX`` from ``market_quotes_extended``, FRED ``VIXCLS`` as the labelled fallback; banned feeds are
refused by name) — through :func:`vix_headline`. One source, one clock, one staleness line
(``fresh_after_hours`` in ``config/market_regime_vix_complex.yaml``).

Read-only. Never writes, never fetches from a provider, never invents a value: no admissible leg is ``value=None``
with the complex's own refusal reasons, never a zero and never a fallback to another source.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

try:
    from lib.market_regime import vix_complex as vc
except ImportError:  # imported as scripts.lib.*
    from scripts.lib.market_regime import vix_complex as vc  # type: ignore[no-redef]

SCHEMA = "VixHeadline@v1"
ET = ZoneInfo("America/New_York")
# FRED VIXCLS is the official close; CBOE settles VIX at 16:15 ET. A date-only FRED observation is dated there so
# its age is real and its timestamp carries a zone (a date with no zone is not an instant).
FRED_CLOSE_ET = time(16, 15)


class _QueryConn:
    """Adapt a ``db_query(sql, params) -> rows`` callable to the cursor protocol ``vix_complex`` reads through.

    ``cio_truth`` and ``api_v2`` hold a query function, not a connection. A ``None`` answer (the api_v2 helper
    swallows errors) is an empty read, which ``vix_complex`` names as ``no_row`` — never a value.
    """

    def __init__(self, db_query: Callable[..., Any]):
        self._q = db_query
        self._rows: list = []

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        try:
            rows = self._q(sql, params)
        except TypeError:  # a db_query that takes (sql, params, fetch=...) positionally only
            rows = self._q(sql, params, "all")
        self._rows = list(rows or [])

    def fetchall(self):
        return self._rows

    def rollback(self):
        pass


def _zoned(as_of: Any) -> datetime | None:
    if isinstance(as_of, datetime):
        return as_of if as_of.tzinfo else None
    s = str(as_of or "").strip()
    if not s:
        return None
    if len(s) == 10:  # a FRED close date: dated at the settlement time, in ET
        try:
            return datetime.combine(date.fromisoformat(s), FRED_CLOSE_ET, tzinfo=ET)
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None  # an unzoned stamp is not an instant; its age stays unknown


def from_record(record: dict[str, Any] | None, *, now: datetime, stale_after_hours: float) -> dict[str, Any]:
    """Shape one ``complex_record`` into the headline fields every surface publishes."""
    record = record or {}
    leg = record.get("vix") or None
    missing = [m for m in (record.get("missing") or []) if str(m).startswith("vix_close")]
    base = {"schema": SCHEMA, "vix_stale_after_hours": stale_after_hours}
    if not leg or leg.get("value") is None:
        return {**base, "vix": None, "vix_source": None, "vix_observation_time": None, "vix_age_hours": None,
                "vix_state": "UNAVAILABLE", "vix_stale": True,
                "vix_reason": ", ".join(missing) or "vix_close not in the complex record"}
    src = str(leg.get("source") or "")
    if leg.get("value_source") == "fred" or src.startswith("fred_economic_series"):
        src = "fred_economic_series:VIXCLS"
    obs = _zoned(leg.get("as_of"))
    age = None if obs is None else round((now - obs).total_seconds() / 3600.0, 2)
    if age is not None and age < -5 / 60:  # a stamp ahead of now is a clock we cannot read, not a fresh print
        obs, age = None, None
    state = "UNDATED" if age is None else ("STALE" if age > stale_after_hours else "FRESH")
    reason = None
    if state == "UNDATED":
        reason = f"observation time unreadable: {leg.get('as_of')!r}"
    elif state == "STALE":
        reason = f"observed {age:.1f} h ago, past the {stale_after_hours:g} h line"
    if leg.get("carried_from"):
        reason = f"{reason + '; ' if reason else ''}carried print from {leg['carried_from']}"
    return {**base, "vix": float(leg["value"]), "vix_source": src,
            "vix_observation_time": obs.isoformat() if obs else None, "vix_age_hours": age,
            "vix_state": state, "vix_stale": state != "FRESH", "vix_reason": reason,
            "vix_session": leg.get("session")}


def vix_headline(*, conn=None, db_query: Callable[..., Any] | None = None, now: datetime | None = None,
                 cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """The headline VIX: value, source, zoned observation time, age, FRESH/STALE/UNDATED/UNAVAILABLE.

    Give it a connection or a ``db_query`` callable. A read failure is ``UNAVAILABLE`` with its type named.
    """
    now = now or datetime.now(timezone.utc)
    try:
        cfg = cfg or vc.load_config()
        stale_after = float(cfg.get("fresh_after_hours") or 26)
    except Exception as exc:  # noqa: BLE001 — a broken config is named, never served as a value
        return {"schema": SCHEMA, "vix": None, "vix_source": None, "vix_observation_time": None,
                "vix_age_hours": None, "vix_state": "UNAVAILABLE", "vix_stale": True,
                "vix_stale_after_hours": None, "vix_reason": f"vix_complex config: {type(exc).__name__}"}
    if conn is None and db_query is None:
        return from_record(None, now=now, stale_after_hours=stale_after) | {"vix_reason": "no database handle"}
    try:
        record = vc.complex_record(conn if conn is not None else _QueryConn(db_query), now=now, cfg=cfg)
    except Exception as exc:  # noqa: BLE001 — UNAVAILABLE by name; a surface must not fall back to another source
        return from_record(None, now=now, stale_after_hours=stale_after) | {
            "vix_reason": f"vix_complex read failed: {type(exc).__name__}"}
    return from_record(record, now=now, stale_after_hours=stale_after)
