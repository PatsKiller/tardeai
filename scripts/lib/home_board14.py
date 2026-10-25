"""Board 14 Home display fields. Read-only. No broker, order, stop, or credential calls.

Shapes text the Home page already has a source for. A missing source stays null
with a reason. This module does not edit stop counts, protection links, or
``cio_truth`` classification.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.lib.cron_outage_watchdog import SCHEMA as WATCHDOG_SCHEMA
from scripts.lib.cron_outage_watchdog import instant
from scripts.lib.cron_schedule import fires_between, last_fire_at_or_before

_ET = ZoneInfo("America/New_York")
# Registry row schwab-position-sync (ACTIVE cron). Tests pin this string to the row.
HOLDINGS_SYNC_EXPR = "7,22,37,52 9-16 * * 1-5"
HOLDINGS_SYNC_TZ = "America/New_York"
HOLDINGS_SYNC_GRACE = timedelta(minutes=25)
NO_STOP_REASON = "No active broker stop observed"
VIX_GAP_REASON = "VIX input unavailable for classifier snapshot"
REGIME_SINCE_GAP = "Regime start is not in the fetched history"
JOBS_RECEIPT = "data/runtime/cron_outage_watchdog_latest.json"
HYGIENE_RECEIPT = "data/runtime/pr-hygiene-audit_last.json"
ASKS_LEDGER = "data/cio/cio_ask_events.jsonl"
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_ASK_BYTES = 20 * 1024 * 1024


def _aware(value: Any) -> datetime | None:
    at = instant(value)
    if at is not None:
        return at
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return None


def _short_et(at: datetime) -> str:
    return at.astimezone(_ET).strftime("%a %H:%M ET")


def _date_label(at: datetime) -> str:
    return at.astimezone(_ET).strftime("%b %-d, %Y")


def _market_closed(now: datetime) -> bool:
    from scripts.lib.cio_truth import _market_open

    return not _market_open(now)


def _next_fire(now: datetime):
    upcoming = fires_between(HOLDINGS_SYNC_EXPR, now, now + timedelta(days=8), HOLDINGS_SYNC_TZ)
    return upcoming[0] if upcoming else None


def holdings_market_note(positions_as_of: Any, now: datetime) -> dict[str, Any]:
    """Weekend and after-hours holdings clock. Stale only when a scheduled slot was missed.

    The phrase names the last sync and the next fire of the holdings cron. It is
    not a substitute for a missing clock, and it is omitted while the market is open.
    """
    if now.tzinfo is None:
        raise ValueError("holdings clock requires an aware time")
    closed = _market_closed(now)
    synced = _aware(positions_as_of)
    last = last_fire_at_or_before(HOLDINGS_SYNC_EXPR, now, HOLDINGS_SYNC_TZ)
    nxt = _next_fire(now)
    missed = False
    if last is not None and now >= last.at + HOLDINGS_SYNC_GRACE:
        missed = synced is None or synced < last.at
    elif last is None:
        missed = synced is None
    phrase = None
    if closed:
        last_text = _short_et(synced) if synced else "unavailable"
        next_text = _short_et(nxt.at) if nxt is not None else "not on the holdings schedule"
        phrase = f"Market closed · last broker sync {last_text} · next {next_text}"
    reason = None
    if missed:
        reason = "A scheduled holdings sync was missed."
    return {
        "market_open": not closed,
        "market_closed_phrase": phrase,
        "sync_missed": missed,
        "sync_missed_reason": reason,
        "next_sync_at": nxt.at.isoformat() if nxt is not None else None,
    }


def _gap(reason: str) -> dict[str, Any]:
    return {"as_of": None, "phrase": None, "on_schedule": None, "gap": {"reason": reason}}


def jobs_clock(path: Path, now: datetime) -> dict[str, Any]:
    """Home Jobs chip from the missed-run monitor receipt only.

    Never calls ``get_jobs_health`` and never says "all ran on schedule" unless
    that receipt's status is OK with no missed lanes and no coverage gaps.
    """
    path = Path(path)
    if not path.is_file():
        return _gap("Jobs monitor receipt not published")
    try:
        if path.stat().st_size > _MAX_RECEIPT_BYTES:
            return _gap("Jobs monitor receipt is too large to read")
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _gap("Jobs monitor receipt could not be read")
    if not isinstance(doc, dict) or doc.get("schema") != WATCHDOG_SCHEMA or doc.get("mode") != "monitor":
        return _gap("Jobs monitor receipt is not a monitor snapshot")
    observed = instant(doc.get("observed_at"))
    if observed is None or observed > now:
        return _gap("Jobs monitor receipt has no usable observation time")
    status = doc.get("status")
    missed = doc.get("missed_lane_ids") if isinstance(doc.get("missed_lane_ids"), list) else None
    gaps = doc.get("coverage_gap_lane_ids") if isinstance(doc.get("coverage_gap_lane_ids"), list) else None
    if missed is None or gaps is None or not isinstance(status, str):
        return _gap("Jobs monitor receipt has no schedule verdict")
    base = {"as_of": observed.isoformat(), "phrase": None, "on_schedule": False, "gap": None}
    if status == "OK" and not missed and not gaps:
        return {**base, "phrase": "all ran on schedule", "on_schedule": True}
    if missed:
        return {**base, "gap": {"reason": f"{len(missed)} scheduled runs missed"}}
    if gaps or status == "UNKNOWN":
        return {**base, "gap": {"reason": "Jobs monitor has not measured every lane"}}
    return {**base, "gap": {"reason": "Jobs monitor is not clear"}}


def questions_approved() -> bool:
    """True only when cio_asks is an approved domain. Failure is not approval."""
    try:
        from scripts.lib.data_source_authority import domain

        approval = domain("cio_asks").get("approval") or {}
        return bool(isinstance(approval, dict) and approval.get("approved_by") and approval.get("reference"))
    except Exception:
        return False


def questions_new_count(path: Path, now: datetime, *, approved: bool) -> dict[str, Any]:
    """Count of answer versions since yesterday 00:00 ET. No question text is returned.

    A missing or unapproved store is a gap, not zero.
    """
    window = now.astimezone(_ET).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    empty = {"count": None, "as_of": None, "window_start": window.isoformat(), "label": "new", "gap": None}
    if not approved:
        return {**empty, "gap": {"reason": "My questions store is not an approved source"}}
    path = Path(path)
    if not path.is_file():
        return {**empty, "gap": {"reason": "My questions store is not available"}}
    try:
        if path.stat().st_size > _MAX_ASK_BYTES:
            return {**empty, "gap": {"reason": "My questions store is too large to count"}}
    except OSError:
        return {**empty, "gap": {"reason": "My questions store could not be read"}}
    count = 0
    newest: datetime | None = None
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if "ask.answer_version" not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("kind") != "ask.answer_version":
                    continue
                at = _aware(event.get("at"))
                if at is None:
                    continue
                if newest is None or at > newest:
                    newest = at
                if at >= window:
                    count += 1
    except OSError:
        return {**empty, "gap": {"reason": "My questions store could not be read"}}
    return {**empty, "count": count, "as_of": newest.isoformat() if newest else None}


def releases_to_merge(path: Path) -> dict[str, Any]:
    """Open-PR count from the local hygiene receipt. No ``gh`` call. Missing is a gap, not zero."""
    path = Path(path)
    if not path.is_file():
        return {"count": None, "as_of": None, "gap": {"reason": "Releases census receipt not published"}}
    try:
        if path.stat().st_size > _MAX_RECEIPT_BYTES:
            return {"count": None, "as_of": None, "gap": {"reason": "Releases census receipt is too large to read"}}
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"count": None, "as_of": None, "gap": {"reason": "Releases census receipt could not be read"}}
    summary = doc.get("summary") if isinstance(doc, dict) else None
    count = summary.get("open_prs") if isinstance(summary, dict) else None
    if not isinstance(count, int):
        return {"count": None, "as_of": None, "gap": {"reason": "Releases census has no open-PR count"}}
    as_of = summary.get("as_of") or doc.get("finished_at")
    return {"count": count, "as_of": as_of if isinstance(as_of, str) else None, "gap": None}


def _evidence(item: dict) -> dict:
    evidence = item.get("evidence")
    return evidence if isinstance(evidence, dict) else {}


def _is_no_stop(item: dict) -> bool:
    state = _evidence(item).get("stop_state")
    if state in ("pending_activation", "filled"):
        return False
    why = item.get("why") or item.get("reason")
    return why == NO_STOP_REASON and state in (None, "none")


def _with_kind(item: dict) -> dict:
    state = _evidence(item).get("stop_state")
    kind = None
    if state in ("pending_activation", "filled"):
        kind = "STOP"
    elif str(item.get("id") or "").startswith("approvals"):
        kind = "REVIEW"
    elif item.get("category") == "protect":
        kind = "STOP"
    if kind is None or item.get("kind") == kind:
        return item
    return {**item, "kind": kind}


def _symbol_of(item: dict) -> str:
    symbol = _evidence(item).get("symbol")
    if isinstance(symbol, str) and symbol.strip():
        return symbol.strip()
    title = str(item.get("title") or "")
    return title.split("·", 1)[0].strip()


def _rollup(rows: list[dict]) -> dict:
    counts = Counter(symbol for symbol in (_symbol_of(row) for row in rows) if symbol)
    listed = ", ".join(f"{symbol} ×{n}" if n > 1 else symbol for symbol, n in counts.items())
    name_count = len(counts)
    return {
        "id": "protection:no-broker-stop",
        "kind": "REVIEW",
        "category": "protect",
        "severity": "P1",
        "symbol": "1 name" if name_count == 1 else f"{name_count} names",
        "title": "no broker stop",
        "why": listed,
        "reason": listed,
        "cta": "See list",
        "action": {"label": "See list", "where": "/v3/risk"},
        "evidence": {"stop_state": "none", "name_count": len(counts)},
    }


def shape_do_now(section: dict) -> dict:
    """Tag STOP/REVIEW on items the CIO already ranked, and roll unprotected names into one row.

    Awaiting-fill and pending-activation stay their own STOP rows. ENTRY and INFO
    are not invented when no source published them.
    """
    items = section.get("items") if isinstance(section, dict) else None
    if not isinstance(items, list):
        return section
    output: list[Any] = []
    rolled: list[dict] = []
    marked = False
    for item in items:
        if isinstance(item, dict) and _is_no_stop(item):
            rolled.append(item)
            if not marked:
                output.append(None)
                marked = True
            continue
        output.append(_with_kind(item) if isinstance(item, dict) else item)
    if marked:
        rollup = _rollup(rolled)
        output = [rollup if item is None else item for item in output]
    return {**section, "items": output}


def regime_since(history: list[dict] | None) -> tuple[str | None, str | None]:
    """ISO start of the current label when history shows a prior different label.

    The latest snapshot's generated_at is not a start date. One label across the
    whole window is a gap.
    """
    if not history:
        return None, REGIME_SINCE_GAP
    current = history[0].get("regime_label") if isinstance(history[0], dict) else None
    if not current:
        return None, REGIME_SINCE_GAP
    started = None
    changed = False
    for row in history:
        if not isinstance(row, dict):
            continue
        if row.get("regime_label") != current:
            changed = True
            break
        started = _aware(row.get("generated_at") or row.get("created_at"))
    if not changed or started is None:
        return None, REGIME_SINCE_GAP
    return started.isoformat(), None


def shape_regime(regime: dict, history: list[dict] | None) -> dict:
    """Keep a published regime label when only VIX is missing, and attach an honest since."""
    out = dict(regime or {})
    gap = out.get("gap")
    reason = gap.get("reason") if isinstance(gap, dict) else gap if isinstance(gap, str) else None
    if out.get("label") and reason == VIX_GAP_REASON:
        out["vix_gap"] = {"reason": VIX_GAP_REASON}
        out["gap"] = None
    since, since_gap = regime_since(history)
    out["since"] = since
    out["since_label"] = _date_label(_aware(since)) if since and _aware(since) else None
    out["since_gap"] = since_gap
    return out


def _regime_history(db_query: Callable, now: datetime) -> list[dict] | None:
    try:
        from scripts.lib.data_broker.market_regime import get_market_regime

        history = get_market_regime(db_query, history=10, now=now).get("history")
    except Exception:
        return None
    return history if isinstance(history, list) else None


def apply_home_board(payload: dict, *, root: Path | str, now: datetime, db_query: Callable | None = None) -> dict:
    """Add Board 14 display fields onto an already validated page payload."""
    root = Path(root)
    portfolio = payload.get("portfolio") if isinstance(payload.get("portfolio"), dict) else {}
    payload["portfolio"] = {**portfolio, **holdings_market_note(portfolio.get("positions_as_of"), now)}
    payload["jobs"] = jobs_clock(root / JOBS_RECEIPT, now)
    payload["questions"] = questions_new_count(root / ASKS_LEDGER, now, approved=questions_approved())
    payload["releases"] = releases_to_merge(root / HYGIENE_RECEIPT)
    regime = payload.get("regime") if isinstance(payload.get("regime"), dict) else {}
    history = _regime_history(db_query, now) if db_query is not None else None
    payload["regime"] = shape_regime(regime, history)
    return payload
