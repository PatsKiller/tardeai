"""Structured catalyst calendar domain for CIO evidence packs.

Normalize raw catalyst / corporate-action rows into a stable schema, assign
deterministic severity, and expose desk decision helpers (revisit, Hermes warm,
Telegram elevate, cache invalidation).

Authority: READ_ONLY_ADVISORY — never implies execution.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

try:
    from lib.catalyst_policy import (
        EXPECTED_MOVE_STEP_PCT,
        HORIZON_HERMES_RESEARCH_GAP,
        HORIZON_HERMES_WARM,
        HORIZON_INVALIDATE_ON_ADD,
        HORIZON_PACK_FILTER,
        HORIZON_REVISIT_TIGHTEN,
        HORIZON_TELEGRAM_ELEVATE,
        KIND_DEFAULT_SEVERITY,
        MIN_SEV_HERMES_WARM,
        MIN_SEV_INVALIDATE_CACHE,
        MIN_SEV_MATERIALITY_BUMP,
        MIN_SEV_RESEARCH_GAP,
        MIN_SEV_REVISIT_TIGHTEN,
        MIN_SEV_TELEGRAM_ELEVATE,
        SEVERITY_RANK,
        clamp_severity,
        effective_research_priority,
        hermes_priority_for_severity,
        max_severity,
        next_relevant_event,
        sev_at_least,
        step_up_severity,
    )
except ImportError:  # pragma: no cover
    from scripts.lib.catalyst_policy import (  # type: ignore
        EXPECTED_MOVE_STEP_PCT,
        HORIZON_HERMES_RESEARCH_GAP,
        HORIZON_HERMES_WARM,
        HORIZON_INVALIDATE_ON_ADD,
        HORIZON_PACK_FILTER,
        HORIZON_REVISIT_TIGHTEN,
        HORIZON_TELEGRAM_ELEVATE,
        KIND_DEFAULT_SEVERITY,
        MIN_SEV_HERMES_WARM,
        MIN_SEV_INVALIDATE_CACHE,
        MIN_SEV_MATERIALITY_BUMP,
        MIN_SEV_RESEARCH_GAP,
        MIN_SEV_REVISIT_TIGHTEN,
        MIN_SEV_TELEGRAM_ELEVATE,
        SEVERITY_RANK,
        clamp_severity,
        effective_research_priority,
        hermes_priority_for_severity,
        max_severity,
        next_relevant_event,
        sev_at_least,
        step_up_severity,
    )

DOMAIN_ID = "catalyst"
QUALITY_OK = "OK"
QUALITY_PARTIAL = "PARTIAL"
QUALITY_UNAVAILABLE = "DATA_UNAVAILABLE"

_GUIDANCE_HIGH_RE = re.compile(
    r"\b(cut|cuts|cutting|slash|slashed|lower(ed|s)?|raise[sd]?|hike[sd]?|"
    r"withdraw|withdrawn|suspend(ed|s)?)\b",
    re.I,
)
_REGULATORY_CRITICAL_RE = re.compile(
    r"\b(halt|halted|trading halt|enforcement|sec charge|doj|indictment|"
    r"delist|delisting|suspend(ed)? trading)\b",
    re.I,
)
_SPECIAL_DIV_RE = re.compile(
    r"\b(special dividend|large special|extraordinary distribution|spin[- ]?off)\b",
    re.I,
)
_ETF_INCOME_HINT_RE = re.compile(
    r"\b(etf|income fund|distribution|ex[- ]?div|ex[- ]?dividend)\b",
    re.I,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        pass
    # bare YYYY-MM-DD
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    s = str(value).strip().replace("Z", "+00:00")
    if not s:
        return None
    try:
        ts = datetime.fromisoformat(s)
    except ValueError:
        d = _parse_date(s)
        if d is None:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _session_date_str(d: date) -> str:
    return d.isoformat()


def _horizon_days(session: date, *, today: Optional[date] = None) -> int:
    today = today or _now_utc().date()
    return (session - today).days


def stable_event_id(
    symbol: str,
    session_date: str,
    kind: str,
    *,
    title: str = "",
) -> str:
    """Deterministic event_id: symbol + date + kind (+ short title hash if needed)."""
    sym = (symbol or "BOOK").upper()
    base = f"{sym}_{session_date}_{kind}".lower()
    if title:
        h = hashlib.sha256(title.encode("utf-8")).hexdigest()[:6]
        return f"cat_{base}_{h}"
    return f"cat_{base}"


def normalize_kind(raw: Any) -> str:
    """Map free-form / broker types into controlled kind set."""
    s = str(raw or "other").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ex_dividend": "ex_div",
        "exdiv": "ex_div",
        "dividend": "distribution",
        "div": "distribution",
        "earnings_release": "earnings",
        "eps": "earnings",
        "quarterly_earnings": "earnings",
        "rebalance": "index_rebalance",
        "index": "index_rebalance",
        "reg": "regulatory",
        "sec": "regulatory",
        "fomc": "macro",
        "cpi": "macro",
        "fed": "macro",
        "product_launch": "product",
        "analyst_upgrade": "analyst_upgrade",
        "analyst_downgrade": "analyst_downgrade",
        "contract_win": "contract_win",
        "m_and_a": "mna",
        "merger": "mna",
        "acquisition": "mna",
    }
    s = aliases.get(s, s)
    if s in KIND_DEFAULT_SEVERITY:
        return s
    # soft match
    if "earn" in s:
        return "earnings"
    if "div" in s or "distrib" in s:
        return "distribution"
    if "guid" in s:
        return "guidance"
    if "rebal" in s:
        return "index_rebalance"
    if "reg" in s or "halt" in s:
        return "regulatory"
    return "other"


def assign_severity(
    kind: str,
    *,
    title: str = "",
    notes: str = "",
    confirmed: bool = True,
    expected_move_pct: float | None = None,
    impact_flag: bool = False,
    is_etf_income: bool = False,
    special_distribution: bool = False,
    top_weight: bool = False,
    book_level_macro: bool = False,
    explicit_severity: str | None = None,
) -> str:
    """Deterministic severity from kind + metadata (not free-form LLM at ingest).

    Unknown / missing → low. Unconfirmed → capped at medium.
    """
    kind = normalize_kind(kind)
    text = f"{title} {notes}".strip()

    # Start from explicit only if already valid; else kind default
    if explicit_severity and str(explicit_severity).strip().lower() in SEVERITY_RANK:
        base = clamp_severity(explicit_severity)
        # Still apply safety caps below
    else:
        base = KIND_DEFAULT_SEVERITY.get(kind, "low")

    # Kind-specific raises
    if kind in ("ex_div", "distribution", "dividend"):
        if special_distribution or _SPECIAL_DIV_RE.search(text):
            base = max_severity(base, "medium")
        elif is_etf_income or _ETF_INCOME_HINT_RE.search(text):
            base = "low"  # stay low unless special
        else:
            base = KIND_DEFAULT_SEVERITY.get(kind, "low")
    elif kind == "guidance":
        if _GUIDANCE_HIGH_RE.search(text):
            base = "high"
        else:
            base = max_severity(base, "medium")
    elif kind == "index_rebalance" and (top_weight or impact_flag):
        base = max_severity(base, "high")
    elif kind == "macro" and book_level_macro:
        base = max_severity(base, "high")
    elif kind == "regulatory":
        if _REGULATORY_CRITICAL_RE.search(text):
            base = "critical"
        else:
            base = max_severity(base, "high")
    elif kind == "other" and impact_flag and confirmed:
        base = max_severity(base, "medium")
    elif kind == "earnings":
        base = max_severity(base, "high")

    # Optional +1 step for large expected move (max one step via step_up)
    if expected_move_pct is not None:
        try:
            emp = float(expected_move_pct)
        except (TypeError, ValueError):
            emp = 0.0
        if emp >= EXPECTED_MOVE_STEP_PCT:
            base = step_up_severity(base, 1)

    if impact_flag and kind not in ("ex_div", "distribution", "dividend"):
        base = max_severity(base, step_up_severity(KIND_DEFAULT_SEVERITY.get(kind, "low"), 1))

    # Unconfirmed: never critical; cap at medium
    if not confirmed:
        if SEVERITY_RANK[clamp_severity(base)] > SEVERITY_RANK["medium"]:
            base = "medium"

    return clamp_severity(base)


def normalize_event(
    raw: Mapping[str, Any],
    *,
    symbol: str | None = None,
    today: Optional[date] = None,
    is_etf_income: bool = False,
    top_weight: bool = False,
    book_level_macro: bool = False,
) -> Optional[dict[str, Any]]:
    """Normalize one raw row into catalyst event schema. Returns None if undated junk."""
    today = today or _now_utc().date()
    sym = str(
        symbol
        or raw.get("symbol")
        or ""
    ).strip().upper()
    kind = normalize_kind(
        raw.get("kind") or raw.get("catalyst_type") or raw.get("type") or "other"
    )
    title = str(
        raw.get("title") or raw.get("headline") or raw.get("name") or kind
    ).strip()[:240]
    notes = str(raw.get("notes") or raw.get("note") or "")[:400]

    # Date resolution
    session = (
        _parse_date(raw.get("session_date"))
        or _parse_date(raw.get("event_date"))
        or _parse_date(raw.get("ex_date"))
        or _parse_date(raw.get("at"))
        or _parse_date(raw.get("published_at"))
        or _parse_date(raw.get("event_ts"))
    )
    event_ts = _parse_ts(raw.get("event_ts")) or (
        datetime(session.year, session.month, session.day, tzinfo=timezone.utc)
        if session
        else None
    )
    if session is None and event_ts is not None:
        session = event_ts.date()
    if session is None:
        # News-style catalyst without calendar date: use "today" horizon 0 as soft event
        # only if we have a headline (evidence still useful); mark unconfirmed calendar
        if not title or title == kind:
            return None
        session = today
        event_ts = event_ts or datetime(session.year, session.month, session.day, tzinfo=timezone.utc)

    session_s = _session_date_str(session)
    horizon = _horizon_days(session, today=today)

    confirmed = raw.get("confirmed")
    if confirmed is None:
        verified = raw.get("verified")
        if verified is not None:
            confirmed = bool(verified)
        else:
            conf = raw.get("confidence")
            try:
                confirmed = float(conf) >= 0.3 if conf is not None else True
            except (TypeError, ValueError):
                confirmed = True
    confirmed = bool(confirmed)

    emp = raw.get("expected_move_pct")
    try:
        emp_f = float(emp) if emp is not None else None
    except (TypeError, ValueError):
        emp_f = None

    impact_flag = bool(raw.get("impact_flag") or raw.get("material_impact"))
    special_dist = bool(raw.get("special_distribution") or _SPECIAL_DIV_RE.search(title + " " + notes))

    severity = assign_severity(
        kind,
        title=title,
        notes=notes,
        confirmed=confirmed,
        expected_move_pct=emp_f,
        impact_flag=impact_flag,
        is_etf_income=is_etf_income or bool(raw.get("is_etf_income")),
        special_distribution=special_dist,
        top_weight=top_weight or bool(raw.get("top_weight")),
        book_level_macro=book_level_macro or bool(raw.get("book_level_macro")),
        explicit_severity=str(raw.get("severity")) if raw.get("severity") is not None else None,
    )

    eid = str(raw.get("event_id") or "").strip() or stable_event_id(sym, session_s, kind, title=title)

    return {
        "event_id": eid,
        "symbol": sym or None,
        "kind": kind,
        "title": title,
        "event_ts": event_ts.isoformat() if event_ts else None,
        "session_date": session_s,
        "horizon_days": horizon,
        "severity": severity,
        "expected_move_pct": emp_f,
        "confirmed": confirmed,
        "source": str(raw.get("source") or raw.get("source_url") or "catalyst_events")[:120],
        "tags": list(raw.get("tags") or [])[:8],
        "notes": notes,
    }


def filter_horizon(
    pack: dict[str, Any],
    *,
    max_days: int = HORIZON_PACK_FILTER,
    include_past_days: int = 0,
) -> dict[str, Any]:
    """Keep events with horizon in [-include_past_days, max_days]. Recompute rollups."""
    events = []
    for e in pack.get("events") or []:
        if not isinstance(e, dict):
            continue
        hd = e.get("horizon_days")
        if hd is None:
            continue
        try:
            days = float(hd)
        except (TypeError, ValueError):
            continue
        if -include_past_days <= days <= max_days:
            events.append(e)
    return build_pack_from_events(
        events,
        symbol=pack.get("symbol"),
        as_of=pack.get("as_of"),
        scope=pack.get("scope") or ("symbol" if pack.get("symbol") else "book"),
        quality=pack.get("quality"),
    )


def build_pack_from_events(
    events: Iterable[dict[str, Any]],
    *,
    symbol: str | None = None,
    as_of: str | None = None,
    scope: str = "symbol",
    quality: str | None = None,
) -> dict[str, Any]:
    """Assemble domain pack with next_event / max_severity / open_count rollups."""
    evs = [e for e in events if isinstance(e, dict)]
    # de-dupe by event_id keeping higher severity then nearer horizon
    by_id: dict[str, dict[str, Any]] = {}
    for e in evs:
        eid = str(e.get("event_id") or "")
        if not eid:
            continue
        prev = by_id.get(eid)
        if prev is None:
            by_id[eid] = e
            continue
        if SEVERITY_RANK[clamp_severity(e.get("severity"))] > SEVERITY_RANK[clamp_severity(prev.get("severity"))]:
            by_id[eid] = e
        elif float(e.get("horizon_days") or 99) < float(prev.get("horizon_days") or 99):
            by_id[eid] = e
    ordered = sorted(
        by_id.values(),
        key=lambda e: (
            float(e.get("horizon_days") if e.get("horizon_days") is not None else 999),
            -SEVERITY_RANK[clamp_severity(e.get("severity"))],
        ),
    )
    upcoming = [e for e in ordered if (e.get("horizon_days") is not None and float(e["horizon_days"]) >= 0)]
    next_ev = upcoming[0] if upcoming else (ordered[0] if ordered else None)
    max_sev = "low"
    for e in ordered:
        max_sev = max_severity(max_sev, e.get("severity"))
    open_med = sum(
        1
        for e in upcoming
        if sev_at_least(e.get("severity"), "medium") and float(e.get("horizon_days") or 99) <= HORIZON_HERMES_RESEARCH_GAP
    )
    next_elevated = next_relevant_event(
        upcoming,
        max_days=HORIZON_TELEGRAM_ELEVATE,
        min_sev=MIN_SEV_TELEGRAM_ELEVATE,
    )
    if not ordered:
        q = quality or QUALITY_UNAVAILABLE
    else:
        q = quality or QUALITY_OK
    pack: dict[str, Any] = {
        "domain": DOMAIN_ID,
        "as_of": as_of or _now_utc().isoformat(),
        "quality": q,
        "quality_state": q,  # alias for evidence_refs consumers
        "symbol": (symbol or None),
        "scope": scope,
        "events": ordered,
        "next_event": next_ev,
        "next_elevated_event": next_elevated,
        "open_count": len(upcoming),
        "open_count_medium_plus": open_med,
        "max_severity": max_sev if ordered else None,
        "fields_used": ["events", "next_event", "max_severity"] if ordered else [],
    }
    if not ordered:
        pack["gap_reason"] = pack.get("gap_reason") or "no_catalyst_events"
    return pack


def unavailable_pack(
    *,
    symbol: str | None = None,
    as_of: str | None = None,
    gap_reason: str = "DATA_UNAVAILABLE",
) -> dict[str, Any]:
    return {
        "domain": DOMAIN_ID,
        "as_of": as_of or _now_utc().isoformat(),
        "quality": QUALITY_UNAVAILABLE,
        "quality_state": QUALITY_UNAVAILABLE,
        "symbol": symbol,
        "scope": "symbol" if symbol else "book",
        "events": [],
        "next_event": None,
        "next_elevated_event": None,
        "open_count": 0,
        "open_count_medium_plus": 0,
        "max_severity": None,
        "fields_used": [],
        "gap_reason": gap_reason,
    }


def normalize_raw_rows(
    rows: Iterable[Mapping[str, Any]] | None,
    *,
    symbol: str | None = None,
    today: Optional[date] = None,
    is_etf_income: bool = False,
    top_weight: bool = False,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        ev = normalize_event(
            row,
            symbol=symbol,
            today=today,
            is_etf_income=is_etf_income,
            top_weight=top_weight,
        )
        if ev:
            out.append(ev)
    return out


def pack_from_broker_record(
    record: Mapping[str, Any] | None,
    *,
    symbol: str | None = None,
    today: Optional[date] = None,
    is_etf_income: bool = False,
) -> dict[str, Any]:
    """Bridge existing get_catalyst_record dict → structured catalyst pack."""
    sym = str(symbol or (record or {}).get("symbol") or "").upper() or None
    if not record:
        return unavailable_pack(symbol=sym, gap_reason="no_catalyst_record")
    # Single headline row → one event
    events = normalize_raw_rows(
        [record],
        symbol=sym,
        today=today,
        is_etf_income=is_etf_income,
    )
    if not events:
        return unavailable_pack(symbol=sym, gap_reason="undated_catalyst_record")
    return build_pack_from_events(
        events,
        symbol=sym,
        as_of=str(record.get("as_of") or record.get("at") or _now_utc().isoformat()),
        scope="symbol",
    )


def attach_catalyst(
    evidence: dict[str, Any],
    *,
    symbol: str | None = None,
    raw_events: Iterable[Mapping[str, Any]] | None = None,
    broker_record: Mapping[str, Any] | None = None,
    is_etf_income: bool = False,
    top_weight: bool = False,
    max_days: int = HORIZON_PACK_FILTER,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Always declare domain=catalyst on evidence (even if empty / unavailable)."""
    sym = (symbol or "").upper() or None
    if raw_events is not None:
        events = normalize_raw_rows(
            raw_events, symbol=sym, today=today, is_etf_income=is_etf_income, top_weight=top_weight,
        )
        pack = build_pack_from_events(events, symbol=sym) if events else unavailable_pack(
            symbol=sym, gap_reason="empty_events",
        )
    elif broker_record is not None:
        pack = pack_from_broker_record(
            broker_record, symbol=sym, today=today, is_etf_income=is_etf_income,
        )
    else:
        pack = unavailable_pack(symbol=sym, gap_reason="no_catalyst_source")

    pack = filter_horizon(pack, max_days=max_days)
    evidence["catalyst"] = pack
    return evidence


# ── desk decision helpers ────────────────────────────────────────────────────


def session_open_utc(session_date: str, *, hour: int = 13, minute: int = 30) -> datetime:
    """Approx US equity open in UTC (13:30 UTC = 9:30 ET during standard; good enough for revisit)."""
    d = _parse_date(session_date) or _now_utc().date()
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


def adjust_revisit_at(
    default_revisit: datetime | str | None,
    catalyst_pack: Mapping[str, Any] | None,
    *,
    now: Optional[datetime] = None,
) -> datetime:
    """Tighten revisit to next medium+ event within horizon when sooner than default."""
    now = now or _now_utc()
    if isinstance(default_revisit, str):
        try:
            default_dt = datetime.fromisoformat(default_revisit.replace("Z", "+00:00"))
        except ValueError:
            default_dt = now + timedelta(hours=24)
        if default_dt.tzinfo is None:
            default_dt = default_dt.replace(tzinfo=timezone.utc)
    elif isinstance(default_revisit, datetime):
        default_dt = default_revisit
        if default_dt.tzinfo is None:
            default_dt = default_dt.replace(tzinfo=timezone.utc)
    else:
        default_dt = now + timedelta(hours=24)

    pack = catalyst_pack or {}
    if pack.get("quality") == QUALITY_UNAVAILABLE or pack.get("quality_state") == QUALITY_UNAVAILABLE:
        return default_dt

    ev = next_relevant_event(
        pack.get("events") or [],
        max_days=HORIZON_REVISIT_TIGHTEN,
        min_sev=MIN_SEV_REVISIT_TIGHTEN,
    )
    if not ev:
        return default_dt
    event_revisit = session_open_utc(str(ev.get("session_date") or "")) + timedelta(hours=2)
    if event_revisit < now:
        return default_dt
    return min(default_dt, event_revisit)


def catalyst_warm_decision(
    symbol: str | None,
    catalyst_pack: Mapping[str, Any] | None,
    *,
    plan_open: bool = True,
    weight_pct: float | None = None,
    fire_pct: float | None = None,
    dd_pct: float | None = None,
    deep_dd_pct: float | None = None,
) -> Optional[dict[str, Any]]:
    """Return warm payload or None. Low-severity ex-divs do not warm."""
    pack = catalyst_pack or {}
    if pack.get("quality") == QUALITY_UNAVAILABLE:
        return None
    if not plan_open and not pack.get("events"):
        return None
    ev = next_relevant_event(
        pack.get("events") or [],
        max_days=HORIZON_HERMES_WARM,
        min_sev=MIN_SEV_HERMES_WARM,
    )
    if not ev:
        return None
    sev = clamp_severity(ev.get("severity", "low"))
    pri = effective_research_priority(
        sev,
        weight_pct=weight_pct,
        fire_pct=fire_pct,
        dd_pct=dd_pct,
        deep_dd_pct=deep_dd_pct,
    )
    return {
        "warm": True,
        "priority": pri,
        "severity": sev,
        "reason": f"catalyst_{sev}_{ev.get('kind')}",
        "event_id": ev.get("event_id"),
        "kind": ev.get("kind"),
        "session_date": ev.get("session_date"),
        "horizon_days": ev.get("horizon_days"),
        "symbol": symbol or pack.get("symbol"),
        "intent": "catalyst_map",
    }


def catalyst_research_gap_eligible(catalyst_pack: Mapping[str, Any] | None) -> bool:
    pack = catalyst_pack or {}
    if pack.get("quality") == QUALITY_UNAVAILABLE:
        return False
    ev = next_relevant_event(
        pack.get("events") or [],
        max_days=HORIZON_HERMES_RESEARCH_GAP,
        min_sev=MIN_SEV_RESEARCH_GAP,
    )
    return ev is not None


def materiality_bump(catalyst_pack: Mapping[str, Any] | None) -> bool:
    pack = catalyst_pack or {}
    ev = next_relevant_event(
        pack.get("events") or [],
        max_days=HORIZON_REVISIT_TIGHTEN,
        min_sev=MIN_SEV_MATERIALITY_BUMP,
    )
    return ev is not None


def catalyst_invalidation_signals(
    prior_as_of: str | None,
    new_pack: Mapping[str, Any] | None,
    *,
    known_event_ids: Iterable[str] | None = None,
) -> list[str]:
    """Signals for Hermes cache invalidation on medium+ add/change within horizon."""
    pack = new_pack or {}
    signals: list[str] = []
    known = set(known_event_ids or [])
    prior_ts = _parse_ts(prior_as_of)
    for e in pack.get("events") or []:
        if not isinstance(e, dict):
            continue
        if not sev_at_least(e.get("severity", "low"), MIN_SEV_INVALIDATE_CACHE):
            continue
        try:
            hd = float(e.get("horizon_days", 99))
        except (TypeError, ValueError):
            hd = 99
        if hd > HORIZON_INVALIDATE_ON_ADD:
            continue
        eid = str(e.get("event_id") or "")
        event_ts = _parse_ts(e.get("event_ts"))
        is_new = eid and eid not in known
        moved = False
        if prior_ts and event_ts and event_ts > prior_ts and (not known or is_new):
            moved = True
        if is_new or moved or (not known and eid):
            signals.append("catalyst_added_or_changed")
            break
    return signals


def catalyst_telegram_line(pack: Mapping[str, Any] | None) -> Optional[str]:
    """Elevated summary line when medium+ within elevate horizon; else None."""
    pack = pack or {}
    if pack.get("quality") == QUALITY_UNAVAILABLE:
        return None
    ev = next_relevant_event(
        pack.get("events") or [],
        max_days=HORIZON_TELEGRAM_ELEVATE,
        min_sev=MIN_SEV_TELEGRAM_ELEVATE,
    )
    if not ev:
        return None
    return (
        f"Next catalyst: {ev.get('kind')} {ev.get('session_date')} "
        f"({ev.get('severity')})"
    )


def catalyst_evidence_line(pack: Mapping[str, Any] | None) -> Optional[str]:
    """Quiet evidence line for any next event (including low severity)."""
    pack = pack or {}
    if pack.get("quality") == QUALITY_UNAVAILABLE:
        return None
    ev = pack.get("next_event")
    if not isinstance(ev, dict):
        return None
    return (
        f"Next catalyst: {ev.get('kind')} {ev.get('session_date')} "
        f"({ev.get('severity')})"
    )


def catalyst_map_questions(symbol: str) -> list[dict[str, str]]:
    """Fingerprint-stable catalyst_map questions for Hermes warm."""
    sym = (symbol or "BOOK").upper()
    return [
        {
            "intent": "catalyst_map",
            "question_id": "q_cat_1",
            "text": f"What catalysts fall in the next 10 sessions for {sym}?",
        },
        {
            "intent": "catalyst_map",
            "question_id": "q_cat_2",
            "text": (
                f"Which catalysts for {sym} are high-impact enough to change "
                f"hold vs size-review language under the live desk thesis?"
            ),
        },
        {
            "intent": "catalyst_map",
            "question_id": "q_cat_3",
            "text": (
                f"What revisit trigger should bind to the next confirmed event for {sym}?"
            ),
        },
    ]


# Re-export policy helpers commonly needed by callers
__all__ = [
    "DOMAIN_ID",
    "QUALITY_OK",
    "QUALITY_UNAVAILABLE",
    "adjust_revisit_at",
    "assign_severity",
    "attach_catalyst",
    "build_pack_from_events",
    "catalyst_evidence_line",
    "catalyst_invalidation_signals",
    "catalyst_map_questions",
    "catalyst_research_gap_eligible",
    "catalyst_telegram_line",
    "catalyst_warm_decision",
    "effective_research_priority",
    "filter_horizon",
    "materiality_bump",
    "normalize_event",
    "normalize_kind",
    "normalize_raw_rows",
    "pack_from_broker_record",
    "session_open_utc",
    "stable_event_id",
    "unavailable_pack",
]
