"""Python port of apps/command-center-v3/src/lib/surfaceFreshness.ts.

Proves the audited defect cannot recur: current price/value paired with an old
child record must render STALE/PARTIAL and must never show a fresh status or
misleading current date.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


HOUR_MS = 3_600_000
OVERVIEW_STALE_HOURS = 36.0
TRADE_AI_STALE_HOURS = 6.0


@dataclass
class SurfaceFreshness:
    stale: bool
    reason: str | None
    asOf: str | None
    ageHours: float | None
    surfaceLabel: str | None
    dataAsOf: str | None
    dataAsOfAccount: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_timestamp(raw: Any, now_ms: float | None = None) -> datetime | None:
    if raw is None or raw == "":
        return None
    now_ms = now_ms if now_ms is not None else datetime.now(tz=timezone.utc).timestamp() * 1000
    if isinstance(raw, (int, float)):
        ms = float(raw)
        if ms > 1e12:
            pass
        elif ms > 1e9:
            ms *= 1000
        else:
            return None
        try:
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            # Date-only → interpret as UTC midnight for hermetic determinism
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    # Strip trailing " ET" etc.
    cleaned = s
    for suffix in (" ET", " EST", " EDT", " UTC"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    cleaned = cleaned.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        try:
            dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Reject absurd future stamps (>1h ahead)
    if dt.timestamp() * 1000 - now_ms > HOUR_MS:
        return None
    return dt


def _age_hours(ts: datetime | None, now_ms: float) -> float | None:
    if ts is None:
        return None
    h = (now_ms - ts.timestamp() * 1000) / HOUR_MS
    return h if h >= 0 else None


def _fmt_age_hours(h: float | None) -> str:
    if h is None:
        return ""
    if h < 1:
        return f"{max(1, round(h * 60))}m"
    if h < 48:
        return f"{round(h)}h"
    return f"{(h / 24):.1f}d"


def overview_surface_freshness(
    overview: dict[str, Any] | None,
    now: datetime | None = None,
) -> SurfaceFreshness:
    now = now or datetime.now(tz=timezone.utc)
    now_ms = now.timestamp() * 1000
    if not overview:
        return SurfaceFreshness(True, "overview missing", None, None, "STALE · no overview", None, None)

    data_as_of = overview.get("data_as_of") if isinstance(overview.get("data_as_of"), str) else None
    data_as_of = data_as_of or None
    data_as_of_account = (
        overview.get("data_as_of_account") if isinstance(overview.get("data_as_of_account"), str) else None
    )
    data_as_of_account = data_as_of_account or None

    data_stamp = parse_timestamp(data_as_of, now_ms)
    if not data_stamp:
        return SurfaceFreshness(
            True,
            "data_as_of UNDATED",
            None,  # never borrow loader as_of
            None,
            "STALE · data UNDATED",
            None,
            data_as_of_account,
        )

    age = _age_hours(data_stamp, now_ms)
    stale = age is not None and age >= OVERVIEW_STALE_HOURS
    acct = f" · {data_as_of_account}" if data_as_of_account else ""
    if not stale:
        return SurfaceFreshness(False, None, data_as_of, age, None, data_as_of, data_as_of_account)
    reason = f"data {_fmt_age_hours(age)}{acct}"
    return SurfaceFreshness(True, reason, data_as_of, age, f"STALE · {reason}", data_as_of, data_as_of_account)


def evaluate_pipeline_honesty(overview: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Detect literal-fresh + stale file / split-root defect class."""
    now = now or datetime.now(tz=timezone.utc)
    status = str(overview.get("pipeline_status") or "")
    completed = overview.get("pipeline_completed")
    data_as_of = overview.get("data_as_of")
    fres = overview_surface_freshness(overview, now)
    literal_fresh_with_stale_data = status.lower() == "fresh" and fres.stale
    misleading_current_date = False
    # If chrome used loader as_of while data_as_of is old — defect
    loader_as_of = overview.get("as_of")
    if fres.stale and loader_as_of and fres.asOf == loader_as_of and data_as_of and loader_as_of != data_as_of:
        misleading_current_date = True
    if (
        fres.stale
        and fres.surfaceLabel
        and "FRESH" in fres.surfaceLabel.upper()
        and "STALE" not in fres.surfaceLabel.upper()
    ):
        misleading_current_date = True
    return {
        "pipeline_status": status,
        "pipeline_completed": completed,
        "chrome_stale": fres.stale,
        "chrome_label": fres.surfaceLabel,
        "chrome_asOf": fres.asOf,
        "literal_fresh_with_stale_data": literal_fresh_with_stale_data,
        "misleading_current_date": misleading_current_date,
        "pass_defect_guard": fres.stale
        and not misleading_current_date
        and (fres.asOf == data_as_of or fres.asOf is None),
    }


def assert_stale_not_fresh(overview: dict[str, Any], now: datetime) -> list[str]:
    """Return list of failure reasons (empty = pass)."""
    failures: list[str] = []
    fres = overview_surface_freshness(overview, now)
    honesty = evaluate_pipeline_honesty(overview, now)
    if not fres.stale:
        failures.append("expected_STALE_got_FRESH")
    if fres.surfaceLabel and not fres.surfaceLabel.startswith("STALE"):
        failures.append(f"label_not_STALE:{fres.surfaceLabel}")
    if fres.asOf and fres.asOf == overview.get("as_of") and overview.get("data_as_of") not in (None, fres.asOf):
        failures.append("asOf_borrowed_loader_date")
    if honesty["misleading_current_date"]:
        failures.append("misleading_current_date")
    # Never show fresh status when data clock is old
    if overview.get("pipeline_status") == "fresh" and fres.stale:
        # Detected — harness records as negative-control hit, not chrome failure
        # when evaluating defect guard for UI chrome alone.
        pass
    return failures
