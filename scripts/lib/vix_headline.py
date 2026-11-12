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
refused by name) — through :func:`vix_headline`. One source, one clock, one staleness rule, and it follows the
session: inside the configured ``printing_window`` (config/market_regime_vix_complex.yaml) the minute line applies;
outside it the print is judged against the last settlement the source could have produced (LQ-20261107-2600).

Read-only. Never writes, never fetches from a provider, never invents a value: no admissible leg is ``value=None``
with the complex's own refusal reasons, never a zero and never a fallback to another source.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

try:
    from lib import cio_market_session as ms
    from lib.market_regime import vix_complex as vc
except ImportError:  # imported as scripts.lib.*
    from scripts.lib import cio_market_session as ms  # type: ignore[no-redef]
    from scripts.lib.market_regime import vix_complex as vc  # type: ignore[no-redef]

SCHEMA = "VixHeadline@v1"
ET = ZoneInfo("America/New_York")
# FRED VIXCLS is the official close; CBOE settles VIX at 16:15 ET. A date-only FRED observation is dated there so
# its age is real and its timestamp carries a zone (a date with no zone is not an instant).
FRED_CLOSE_ET = time(16, 15)
# LQ-20261107-1669 (operator 2026-11-09 14:50 ET): VIX refreshes every 15 min through the trading day and anything
# older than 30 min is STALE, with its time, on every surface. Config key ``session_fresh_after_minutes`` in
# config/market_regime_vix_complex.yaml overrides the default.
# LQ-20261107-2600 (lead 2026-11-12T1804): the span the operator's order assumed -- prints every 15 min from 18:00
# ET the evening before to 20:00 ET -- is not what the provider does. Measured 2026-11-12: market_quotes:schwab:$VIX
# carries 15-min prints 03:15..16:15 ET and NOTHING between 16:15 and 03:15, while the writer lane fired every 15
# min all evening (105/105 RUN_DONE; its 18:00 receipt reads the 16:15 print and names ``cboe_not_calculating``).
# Cboe stops calculating at the settlement, so the wall-clock line cannot be met. The rule is now the configured
# printing window: inside [start_et, official close + settlement offset) the minute line above applies; outside it
# the newest print any source could carry is the last trading day's settlement, and the observation is judged
# against that instant -- reaching it is current-for-session, predating it is a missed settle write (STALE).
SESSION_FRESH_AFTER_MINUTES = 30.0


def parse_printing_window(raw: Any) -> dict[str, Any]:
    """Validate the configured printing window into its two parts: first print time and settlement offset.

    A malformed window raises: the caller names a config error and shows no value, rather than inventing an hour.
    """
    if not isinstance(raw, dict):
        raise ValueError("printing_window must be a mapping of start_et + settlement_after_close_minutes")
    if isinstance(raw.get("start"), time) and "settlement_offset_minutes" in raw:  # already parsed
        return {"start": raw["start"], "settlement_offset_minutes": float(raw["settlement_offset_minutes"])}
    start_raw = str(raw.get("start_et") or "").strip()
    try:
        start = datetime.strptime(start_raw, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"printing_window.start_et must be HH:MM (ET), not {start_raw!r}") from exc
    offset_raw = raw.get("settlement_after_close_minutes")
    if isinstance(offset_raw, bool) or not isinstance(offset_raw, (int, float)):
        raise ValueError(
            f"printing_window.settlement_after_close_minutes must be a number, not {offset_raw!r}")
    offset = float(offset_raw)
    if not 0 < offset <= 120:
        raise ValueError(f"printing_window.settlement_after_close_minutes must be in (0, 120], not {offset!r}")
    return {"start": start, "settlement_offset_minutes": offset}


def _latest_settlement(et_now: datetime, svc: Any, offset_minutes: float) -> datetime | None:
    """The newest settlement instant that has passed (10 calendar days back; holidays have no bounds)."""
    for back in range(0, 10):
        _open, close, _early = svc.official_bounds(et_now.date() - timedelta(days=back))
        if close is None:
            continue
        settlement = close + timedelta(minutes=offset_minutes)
        if settlement <= et_now:
            return settlement
    return None


def freshness_line(now: datetime, cfg_minutes: Any, off_hours_line: float,
                   printing_window: dict[str, Any]) -> dict[str, Any]:
    """Which freshness rule applies at ``now``, from the configured printing window (LQ-20261107-2600).

    ``line_s`` is the exact age bound in seconds (``line_h`` its display form; None when the rule is not an age).
    ``expected`` is the newest print any source could carry outside the window, so a STALE reason can name the
    settlement that was missed; ``open`` is today's official open once it has passed. A session read failure keeps
    the off-hours line and says so; it never makes a print fresher.
    """
    et = now.astimezone(ET)
    window = parse_printing_window(printing_window)
    try:
        svc = ms.get_session_service()
        opened, close, _early = svc.official_bounds(et.date())
        first = datetime.combine(et.date(), window["start"], tzinfo=ET) if close is not None else None
        settlement = (close + timedelta(minutes=window["settlement_offset_minutes"])
                      if close is not None else None)
    except Exception as exc:  # noqa: BLE001 -- named in the rule, never a fresher answer
        return {"rule": f"off_hours:session_unreadable:{type(exc).__name__}",
                "line_s": off_hours_line * 3600.0, "line_h": off_hours_line, "open": None, "expected": None}
    if first is not None and settlement is not None and first <= et < settlement:
        try:
            minutes = float(cfg_minutes) if cfg_minutes is not None else SESSION_FRESH_AFTER_MINUTES
        except (TypeError, ValueError):
            minutes = SESSION_FRESH_AFTER_MINUTES
        return {"rule": "continuous_30m" if minutes == SESSION_FRESH_AFTER_MINUTES else f"continuous_{minutes:g}m",
                "line_s": minutes * 60.0, "line_h": round(minutes / 60.0, 4),
                "open": opened if (opened is not None and now >= opened) else None, "expected": None}
    expected = _latest_settlement(et, svc, window["settlement_offset_minutes"])
    if expected is None:
        return {"rule": "off_hours:no_settlement_in_calendar", "line_s": off_hours_line * 3600.0,
                "line_h": off_hours_line, "open": None, "expected": None}
    return {"rule": "settled", "line_s": max(0.0, (et - expected).total_seconds()), "line_h": None,
            "open": None, "expected": expected}


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


def from_record(
    record: dict[str, Any] | None, *, now: datetime, stale_after_hours: float,
    printing_window: dict[str, Any], session_fresh_after_minutes: Any = None
) -> dict[str, Any]:
    """Shape one ``complex_record`` into the headline fields every surface publishes."""
    record = record or {}
    leg = record.get("vix") or None
    missing = [m for m in (record.get("missing") or []) if str(m).startswith("vix_close")]
    line = freshness_line(now, session_fresh_after_minutes, stale_after_hours, printing_window)
    base = {"schema": SCHEMA, "vix_stale_after_hours": line["line_h"], "vix_fresh_rule": line["rule"],
            "vix_expected_print": line["expected"].isoformat() if line["expected"] else None}
    if not leg or leg.get("value") is None:
        return {**base, "vix": None, "vix_source": None, "vix_observation_time": None, "vix_age_hours": None,
                "vix_state": "UNAVAILABLE", "vix_stale": True,
                "vix_reason": ", ".join(missing) or "vix_close not in the complex record"}
    src = str(leg.get("source") or "")
    if leg.get("value_source") == "fred" or src.startswith("fred_economic_series"):
        src = "fred_economic_series:VIXCLS"
    obs = _zoned(leg.get("as_of"))
    age_s = None if obs is None else (now - obs).total_seconds()
    age = None if age_s is None else round(age_s / 3600.0, 2)
    if age_s is not None and age_s < -300:  # a stamp ahead of now is a clock we cannot read, not a fresh print
        obs, age, age_s = None, None, None
    state = "UNDATED" if age_s is None else ("STALE" if age_s > line["line_s"] else "FRESH")
    predates_open = state == "STALE" and line["open"] is not None and obs < line["open"]
    reason = None
    if state == "UNDATED":
        reason = f"observation time unreadable: {leg.get('as_of')!r}"
    elif predates_open:
        reason = (
            f"last print {obs.astimezone(ET):%H:%M} ET {obs.astimezone(ET):%m-%d} predates today's "
            f"{line['open'].astimezone(ET):%H:%M} ET open; no intraday VIX print since"
        )
    elif state == "STALE" and line["expected"] is not None:
        reason = (f"last print {obs.astimezone(ET):%H:%M} ET {obs.astimezone(ET):%m-%d} predates the "
                  f"{line['expected'].astimezone(ET):%m-%d %H:%M} ET settlement; no print since")
    elif state == "STALE" and float(line["line_h"]) < 1:
        reason = (f"last print {obs.astimezone(ET):%H:%M} ET {obs.astimezone(ET):%m-%d}, {age * 60:.0f} min ago, "
                  f"past the {float(line['line_h']) * 60:g} min line")
    elif state == "STALE":
        reason = f"observed {age:.1f} h ago, past the {line['line_h']:g} h line"
    if leg.get("carried_from"):
        reason = f"{reason + '; ' if reason else ''}carried print from {leg['carried_from']}"
    return {**base, "vix": float(leg["value"]), "vix_source": src,
            "vix_observation_time": obs.isoformat() if obs else None, "vix_age_hours": age,
            "vix_state": state, "vix_stale": state != "FRESH", "vix_reason": reason,
            "vix_session": leg.get("session")}


def vix_headline(*, conn=None, db_query: Callable[..., Any] | None = None, now: datetime | None = None,
                 cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """The headline VIX: value, source, zoned observation time, age, FRESH/STALE/UNDATED/UNAVAILABLE.

    Give it a connection or a ``db_query`` callable. A read failure is ``UNAVAILABLE`` with its type named; a
    config without a readable ``printing_window`` is the same (the freshness rule cannot be decided, so no
    value is judged).
    """
    now = now or datetime.now(timezone.utc)
    try:
        cfg = cfg or vc.load_config()
        stale_after = float(cfg.get("fresh_after_hours") or 26)
        session_min = cfg.get("session_fresh_after_minutes")
        printing_window = parse_printing_window(cfg.get("printing_window"))
    except Exception as exc:  # noqa: BLE001 — a broken config is named, never served as a value
        return {"schema": SCHEMA, "vix": None, "vix_source": None, "vix_observation_time": None,
                "vix_age_hours": None, "vix_state": "UNAVAILABLE", "vix_stale": True,
                "vix_stale_after_hours": None, "vix_reason": f"vix_complex config: {type(exc).__name__}"}
    if conn is None and db_query is None:
        return from_record(None, now=now, stale_after_hours=stale_after, printing_window=printing_window,
                           session_fresh_after_minutes=session_min) | {"vix_reason": "no database handle"}
    try:
        record = vc.complex_record(conn if conn is not None else _QueryConn(db_query), now=now, cfg=cfg)
    except Exception as exc:  # noqa: BLE001 — UNAVAILABLE by name; a surface must not fall back to another source
        return from_record(None, now=now, stale_after_hours=stale_after, printing_window=printing_window,
                           session_fresh_after_minutes=session_min) | {
            "vix_reason": f"vix_complex read failed: {type(exc).__name__}"}
    return from_record(record, now=now, stale_after_hours=stale_after, printing_window=printing_window,
                       session_fresh_after_minutes=session_min)
