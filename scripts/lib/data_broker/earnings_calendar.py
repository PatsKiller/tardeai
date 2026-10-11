"""Data Broker projection — market-wide earnings calendar from the Alpha Vantage owner.

Proposed registry domain ``earnings_calendar`` (config/policy_proposals/
data_source_authority_alpha_vantage_scope_20261010.json; operator grant pending). The single
writer is scripts/alpha_vantage_owner.py (one EARNINGS_CALENDAR call per day, horizon 3 months),
which publishes data/runtime/alpha_vantage/earnings_calendar_latest.json. This module only reads
that file: zero provider calls. Every answer carries the BrokerReadEnvelope@v1 fields (as_of,
age_hours, source, stale); a missing file is ``gap.kind == no_coverage`` with the declared
behaviour ``say_so`` — never a guessed date.

What it adds over the ``earnings_date`` domain (symbol_profiles, yfinance): the report's time of
day (pre-market / post-market) and the consensus estimate, for every US listing, in one call.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from lib.data_broker.envelope import envelope

DOMAIN = "earnings_calendar"
STALE_AFTER_HOURS = 26.0
NO_COVERAGE = "say_so"
WRITER = "scripts/alpha_vantage_owner.py"


def _path(base: Path | None) -> Path:
    if base is not None:
        return Path(base) / "earnings_calendar_latest.json"
    from lib.alpha_vantage_owner import state_dir
    return state_dir() / "earnings_calendar_latest.json"


def _load(base: Path | None) -> dict[str, Any] | None:
    try:
        return json.loads(_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _env(doc: dict[str, Any] | None, now: datetime | None) -> dict[str, Any]:
    env = envelope(DOMAIN, (doc or {}).get("as_of"), now=now, registry={},
                   stale_after_hours=STALE_AFTER_HOURS,
                   source={"file": "runtime/alpha_vantage/earnings_calendar_latest.json", "writer": WRITER,
                           "projection": DOMAIN, "provider": "alpha_vantage",
                           "registry": "PROPOSED (operator grant pending)"})
    if env.get("gap"):
        env["gap"]["declared_behaviour"] = NO_COVERAGE
    return env


def get_earnings(symbols: Iterable[str], *, base: Path | None = None,
                 now: datetime | None = None) -> dict[str, Any]:
    """{symbols: {SYM: row | None}, as_of, age_hours, stale, source[, gap]}.

    A symbol absent from a fresh calendar is ``None``: AV lists no report for it in the next
    3 months (or does not cover it). That is not "no earnings" — callers say so.
    """
    doc = _load(base)
    rows = (doc or {}).get("by_symbol") or {}
    out = {"symbols": {str(s).upper(): rows.get(str(s).upper()) for s in symbols},
           "horizon": (doc or {}).get("horizon")}
    out.update(_env(doc, now))
    return out


def upcoming(days: int = 7, *, base: Path | None = None, now: datetime | None = None,
             symbols: Iterable[str] | None = None) -> dict[str, Any]:
    """Reports within ``days`` (optionally only for ``symbols``), soonest first."""
    doc = _load(base)
    ref = (now or datetime.now(timezone.utc)).date()
    want = {str(s).upper() for s in symbols} if symbols is not None else None
    rows = []
    for sym, r in ((doc or {}).get("by_symbol") or {}).items():
        if want is not None and sym not in want:
            continue
        try:
            d = date.fromisoformat(r.get("report_date") or "")
        except ValueError:
            continue
        if 0 <= (d - ref).days <= days:
            rows.append({"symbol": sym, **r})
    rows.sort(key=lambda r: (r["report_date"], r["symbol"]))
    out: dict[str, Any] = {"days": days, "reports": rows}
    out.update(_env(doc, now))
    return out
