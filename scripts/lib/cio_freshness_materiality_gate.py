"""cio_freshness_materiality_gate.py — Freshness & Materiality (acceptance).

Nothing may say ACT NOW merely because recommended_delta_usd != 0.

ACT NOW requires:
  * financial-truth gate not CONFLICTED for the symbol / book
  * current financial state (holdings freshness PASS)
  * current market price (quote / MV freshness PASS)
  * real decision generated_at / revalidated_at — never an undated clock
  * relevant current risk when concentration is cited
  * at least one independent thesis/research/risk source beyond the book
  * no unresolved contradiction affecting sizing

Holdings + quote from the same holdings.json snapshot are ONE evidence group
(financial_state), not two. Missing generated_at / revalidated_at is REVALIDATE.

Otherwise labels:
  REVIEW | WATCH | REVALIDATE | DATA_CONFLICT | STALE_REFRESH_REQUIRED

READ_ONLY_ADVISORY. Pure policy — no broker / Telegram.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

# Reuse timestamp helpers from financial truth gate
from scripts.lib.cio_financial_truth_gate import (  # noqa: E402
    PROCESS_CLOCK_FIELDS,
    STATE_CONFLICTED,
    STATE_DATA_UNAVAILABLE,
    STATE_STALE,
    STATE_VERIFIED_AS_OF,
    STATE_VERIFIED_CURRENT,
    age_seconds,
    extract_source_observation_time,
    parse_ts,
)

FRESHNESS_MATERIALITY_VERSION = "freshness_materiality_1.2.0"

# Operator-facing action labels (Phase 3)
LABEL_ACT_NOW = "ACT_NOW"
LABEL_REVIEW = "REVIEW"
LABEL_WATCH = "WATCH"
LABEL_REVALIDATE = "REVALIDATE"
LABEL_DATA_CONFLICT = "DATA_CONFLICT"
LABEL_STALE_REFRESH = "STALE_REFRESH_REQUIRED"

ACTION_LABELS = frozenset({
    LABEL_ACT_NOW,
    LABEL_REVIEW,
    LABEL_WATCH,
    LABEL_REVALIDATE,
    LABEL_DATA_CONFLICT,
    LABEL_STALE_REFRESH,
})

# Policy thresholds (seconds) — configurable via apply_policy kwargs
QUOTE_FRESH_SEC = 15 * 60          # RTH quote / MV
HOLDINGS_FRESH_SEC = 48 * 3600     # broker snapshot / holdings book
DECISION_REVALIDATE_SEC = 24 * 3600
THESIS_FRESH_SEC = 7 * 24 * 3600
ADVISORY_FRESH_SEC = 7 * 24 * 3600
ANALYST_MAX_AGE_SEC = 90 * 24 * 3600  # may be old but must be dated
SECTOR_FRESH_SEC = 48 * 3600
CASH_FRESH_SEC = 48 * 3600
RISK_FRESH_SEC = 48 * 3600
HERMES_FRESH_SEC = 14 * 24 * 3600
MIN_EVIDENCE_SOURCES_ACT_NOW = 2

# Canonical evidence groups (Phase 4). Same-snapshot book marks collapse.
GROUP_FINANCIAL_STATE = "financial_state"
GROUP_MARKET_PRICE = "market_price"
GROUP_RISK = "risk"
GROUP_FUNDAMENTAL = "fundamental"
GROUP_TECHNICAL = "technical"
GROUP_SECTOR = "sector"
GROUP_ANALYST = "analyst"
GROUP_HERMES = "hermes"
GROUP_TAX_LOT = "tax_lot"
GROUP_STRATEGY = "strategy_context"

EVIDENCE_GROUPS = (
    GROUP_FINANCIAL_STATE,
    GROUP_MARKET_PRICE,
    GROUP_RISK,
    GROUP_FUNDAMENTAL,
    GROUP_TECHNICAL,
    GROUP_SECTOR,
    GROUP_ANALYST,
    GROUP_HERMES,
    GROUP_TAX_LOT,
    GROUP_STRATEGY,
)

# Independent thesis / research / risk sources that may justify ACT NOW
# beyond the holdings book itself.
INDEPENDENT_THESIS_RESEARCH_RISK = frozenset({
    GROUP_RISK,
    GROUP_FUNDAMENTAL,
    GROUP_TECHNICAL,
    GROUP_SECTOR,
    GROUP_ANALYST,
    GROUP_HERMES,
})

_HOLDINGS_SNAPSHOT_SOURCES = frozenset({
    "holdings.json",
    "holdings_quote",
    "holdings.market_value",
    "holdings.cash",
    "holdings",
    "holdings.updated_at",
})

_NEUTRAL_WHY = "no new desk signal"


def _holdings_like_source(source: Any) -> bool:
    s = str(source or "").strip().lower()
    if not s:
        return True
    if s in _HOLDINGS_SNAPSHOT_SOURCES:
        return True
    return s.startswith("holdings")


def _clocks_equal(a: Any, b: Any) -> bool:
    """True when two stamps are the same snapshot clock."""
    if a is None or b is None:
        return False
    if str(a) == str(b):
        return True
    da, db = parse_ts(a), parse_ts(b)
    if da is None or db is None:
        return False
    return abs((da - db).total_seconds()) < 1.0


def contributing_account_rows(
    holdings_doc: Optional[dict[str, Any]],
    symbol: str,
) -> list[dict[str, Any]]:
    """Every non-cash holdings row for `symbol` (all accounts, not first only)."""
    want = str(symbol or "").upper()
    if not want:
        return []
    out: list[dict[str, Any]] = []
    for r in (holdings_doc or {}).get("holdings") or []:
        if not isinstance(r, dict) or r.get("is_cash"):
            continue
        if str(r.get("symbol") or "").upper() == want:
            out.append(r)
    return out


def _merge_position_rows(
    *,
    holdings_doc: Optional[dict[str, Any]],
    symbol: str,
    position_row: Optional[dict[str, Any]] = None,
    position_rows: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Dedupe contributing rows by account; never drop a book account."""
    by_acct: dict[str, dict[str, Any]] = {}

    def _add(row: Optional[dict[str, Any]]) -> None:
        if not isinstance(row, dict):
            return
        acct = str(row.get("account") or row.get("account_id") or "")
        key = acct or f"__anon_{len(by_acct)}"
        if key not in by_acct:
            by_acct[key] = row

    for r in position_rows or []:
        _add(r)
    _add(position_row)
    for r in contributing_account_rows(holdings_doc, symbol):
        _add(r)
    return list(by_acct.values())


def _is_process_clock_value(row: dict[str, Any], ts: Any) -> bool:
    """True when `ts` only appears on a process-clock field of the row."""
    if ts is None:
        return False
    on_source, on_process = False, False
    _n, _d, src_raw = extract_source_observation_time(row, include_aliases=True)
    if src_raw is not None and str(src_raw) == str(ts):
        on_source = True
    for key in PROCESS_CLOCK_FIELDS:
        if row.get(key) is not None and str(row.get(key)) == str(ts):
            on_process = True
    return on_process and not on_source


def _row_quote_ts(row: dict[str, Any]) -> Any:
    """Quote clock is a source observation time. Process clocks are not freshness.

    Uses the derived canonical fields so a stale persisted ``canonical_mark_as_of``
    does not make a mark freshly re-derived from ``current_price`` read as old.
    """
    from scripts.lib.cio_canonical_quote import apply_canonical_quote_fields

    named = apply_canonical_quote_fields(row)
    _name, _dt, raw = extract_source_observation_time(named, include_aliases=True)
    return raw


def inspect_account_row_quotes(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fail-closed quote clock across every contributing account row."""
    reports: list[dict[str, Any]] = []
    worst_dt: Optional[datetime] = None
    worst_ts: Any = None
    worst_src: Any = None
    any_undated = False
    any_present = False
    for r in rows:
        ts = _row_quote_ts(r)
        dt = parse_ts(ts)
        has_mark = any(
            r.get(k) is not None
            for k in ("current_price", "price", "market_value", "last", "quote")
        )
        rec = {
            "account": r.get("account") or r.get("account_id"),
            "symbol": r.get("symbol"),
            "source_as_of": str(ts) if ts else None,
            "price_source": r.get("price_source"),
        }
        if dt is None:
            rec["pass"] = False
            rec["detail"] = "undated" if (ts or has_mark) else "missing"
            if rec["detail"] != "missing":
                any_undated = True
                any_present = True
        else:
            any_present = True
            rec["pass"] = True
            rec["detail"] = "ok"
            if worst_dt is None or dt < worst_dt:
                worst_dt = dt
                worst_ts = ts
                worst_src = r.get("price_source")
        reports.append(rec)
    return {
        "rows": reports,
        "worst_ts": worst_ts,
        "worst_source": worst_src,
        "any_undated": any_undated,
        "any_present": any_present,
        "row_count": len(rows),
    }


def _market_price_from_holdings_snapshot(
    *,
    stamps: dict[str, Any],
    src: dict[str, Any],
    extra: Optional[dict[str, Any]],
    decision: dict[str, Any],
    position_row: Optional[dict[str, Any]],
) -> bool:
    """True when quote/MV rode in on the holdings.json snapshot."""
    extra = extra or {}
    pos = position_row or {}
    live_source = (
        extra.get("quote_source")
        or decision.get("quote_source")
        or pos.get("price_source")
        or src.get("quote")
    )
    live_ts = (
        extra.get("quote_as_of")
        or decision.get("quote_as_of")
        or pos.get("price_as_of")
        or pos.get("quote_time")
    )
    holdings_ts = stamps.get("holdings_snapshot") or stamps.get("holdings")
    if live_ts and not _holdings_like_source(live_source):
        if not _clocks_equal(live_ts, holdings_ts):
            return False
    if not _holdings_like_source(live_source) and not _clocks_equal(
        stamps.get("quote"), holdings_ts
    ):
        # Distinct non-holdings source with a distinct clock.
        if live_ts or extra.get("quote_as_of") or decision.get("quote_as_of"):
            return False
    return True


def _risk_from_book(
    stamps: dict[str, Any],
    extra: Optional[dict[str, Any]],
    decision: dict[str, Any],
) -> bool:
    independent = (decision or {}).get("risk_as_of") or (extra or {}).get("risk_as_of")
    if not independent:
        return True
    book = stamps.get("holdings_snapshot") or stamps.get("holdings")
    return _clocks_equal(independent, book) or _clocks_equal(independent, stamps.get("holdings"))


def _tax_from_book(
    stamps: dict[str, Any],
    extra: Optional[dict[str, Any]],
    decision: dict[str, Any],
) -> bool:
    independent = (decision or {}).get("tax_as_of") or (extra or {}).get("tax_as_of")
    if not independent:
        return True
    book = stamps.get("holdings_snapshot") or stamps.get("holdings")
    return _clocks_equal(independent, book) or _clocks_equal(independent, stamps.get("holdings"))


def _record_ok(rec: Optional[dict[str, Any]]) -> bool:
    if not rec:
        return False
    if not rec.get("present"):
        return False
    if rec.get("detail") in ("missing", "undated"):
        return False
    return bool(rec.get("pass"))


def _fnum(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _session_context(now: datetime) -> dict[str, Any]:
    """NYSE session flag via injectable deterministic calendar (no network)."""
    try:
        from scripts.lib.cio_market_session import get_market_session
        sess = get_market_session(now)
    except Exception:
        sess = {
            "exchange": "XNYS",
            "session_date": None,
            "state": "CLOSED",
            "official_open": None,
            "official_close": None,
            "early_close": False,
            "source": "cio_market_session_unavailable",
        }
    state = str(sess.get("state") or "CLOSED").upper()
    rth = state == "RTH"
    is_weekday = False
    if sess.get("session_date"):
        try:
            from datetime import date as _date
            is_weekday = _date.fromisoformat(str(sess["session_date"])[:10]).weekday() < 5
        except ValueError:
            is_weekday = False
    return {
        "is_weekday": is_weekday,
        "likely_rth": rth,
        "quote_policy": "rth_15m" if rth else "after_hours_latest_supported",
        "market_session": {
            "exchange": sess.get("exchange"),
            "session_date": sess.get("session_date"),
            "state": state if state in ("PRE", "RTH", "POST", "CLOSED") else "CLOSED",
            "official_open": sess.get("official_open"),
            "official_close": sess.get("official_close"),
            "early_close": bool(sess.get("early_close")),
            "source": sess.get("source"),
        },
        "note": (
            "Regular session quote freshness window active (15 minutes)."
            if rth else
            "Regular session: quote/MV age <= 15m where live marks exist. "
            "After-hours/weekend/holiday: use latest supported mark and label as_of."
        ),
    }


def _freshness_record(
    *,
    name: str,
    ts: Any,
    max_age_sec: float,
    now: datetime,
    required_for_act_now: bool,
    source: str = "",
    present: bool = True,
    after_hours_ok: bool = False,
    session: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One evidence-class freshness evaluation."""
    session = session or {}
    if not present:
        return {
            "name": name,
            "present": False,
            "pass": not required_for_act_now,
            "required_for_act_now": required_for_act_now,
            "quality": STATE_DATA_UNAVAILABLE,
            "age_seconds": None,
            "source_as_of": None,
            "source": source or None,
            "max_age_sec": max_age_sec,
            "detail": "missing",
        }
    dt = parse_ts(ts)
    if dt is None:
        # Present but undated — cannot prove freshness
        return {
            "name": name,
            "present": True,
            "pass": False if required_for_act_now else True,
            "required_for_act_now": required_for_act_now,
            "quality": STATE_DATA_UNAVAILABLE,
            "age_seconds": None,
            "source_as_of": str(ts) if ts else None,
            "source": source or None,
            "max_age_sec": max_age_sec,
            "detail": "undated",
        }
    age = age_seconds(dt, now=now) or 0.0
    # After-hours: quotes may be older than 15m but still "latest supported"
    effective_max = max_age_sec
    detail = "ok"
    if name in ("quote", "market_value") and not session.get("likely_rth") and after_hours_ok:
        effective_max = max(max_age_sec, 24 * 3600)  # allow prior close mark
        detail = "after_hours_latest_supported"
    passed = age <= effective_max
    if not passed:
        quality = STATE_STALE
        detail = "stale"
    else:
        quality = STATE_VERIFIED_CURRENT if age <= max_age_sec else STATE_VERIFIED_AS_OF
    return {
        "name": name,
        "present": True,
        "pass": passed,
        "required_for_act_now": required_for_act_now,
        "quality": quality,
        "age_seconds": round(age, 1),
        "source_as_of": dt.isoformat(),
        "source": source or None,
        "max_age_sec": effective_max,
        "detail": detail,
    }


def _cash_ts_from_rows(rows, doc):
    """The cash block's own clock: oldest contributing balance, or None.

    Delegates to cio_capital_plan.cash_evidence_as_of -- the one derivation. A
    second implementation here is how two surfaces start disagreeing about the age
    of the same dollars.
    """
    # Cash evidence comes from the WHOLE BOOK, not from the position under
    # evaluation. `rows` here is the merged position rows -- for a decision about
    # one symbol that is that symbol, which contains no cash, so deriving from it
    # reported every book as undated. The document's holdings are the cash source.
    book = (doc or {}).get("holdings")
    if not isinstance(book, list) or not book:
        book = rows or []
    try:
        from scripts.lib.cio_capital_plan import cash_evidence_as_of
        ev = cash_evidence_as_of(book, doc or {})
    except Exception:  # noqa: BLE001 -- a clock we cannot derive is absent, not "now"
        return None
    if not isinstance(ev, dict) or ev.get("unstamped"):
        return None
    return ev.get("as_of")


def collect_evidence_timestamps(
    *,
    decision: dict[str, Any],
    holdings_doc: Optional[dict[str, Any]] = None,
    position_row: Optional[dict[str, Any]] = None,
    position_rows: Optional[list[dict[str, Any]]] = None,
    financial_truth: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    symbol: str = "",
) -> dict[str, Any]:
    """Pull best-effort timestamps for each evidence class.

    Decision clock is *only* generated_at / revalidated_at. Plan computed_at
    is not a substitute. Quote clock is the worst contributing account row.
    """
    extra = extra or {}
    doc = holdings_doc or {}
    sym = str(symbol or decision.get("symbol") or "").upper()
    rows = _merge_position_rows(
        holdings_doc=doc,
        symbol=sym,
        position_row=position_row,
        position_rows=position_rows,
    )
    pos = rows[0] if rows else (position_row or {})
    row_quotes = inspect_account_row_quotes(rows)
    # holdings book: source as_of is freshness. updated_at is snapshot identity
    # only — it must never make an old source look fresh.
    holdings_source_ts = (
        doc.get("last_repriced")
        or doc.get("generated_at")
        or doc.get("as_of")
        or doc.get("source_as_of")
    )
    holdings_updated_at = doc.get("updated_at") or doc.get("ingested_at")
    # Identity of this holdings.json write (grouping), not a freshness clock.
    holdings_snapshot_ts = holdings_updated_at or holdings_source_ts
    holdings_ts = holdings_source_ts  # freshness clock; None if missing
    # quote / MV: worst account row, then explicit live quote, never invent now
    # and never a process clock.
    quote_ts = row_quotes.get("worst_ts")
    if quote_ts is None:
        quote_ts = extra.get("quote_as_of") or decision.get("quote_as_of")
        if quote_ts is None:
            _n, _d, quote_ts = extract_source_observation_time(pos, include_aliases=True)
        elif _is_process_clock_value(pos, quote_ts):
            quote_ts = None
    mv_ts = quote_ts
    if mv_ts is None:
        mv_ts = pos.get("broker_position_as_of") or pos.get("source_as_of")
    # PP3. `cash_ts = holdings_ts` borrowed the holdings document's REPRICING clock
    # for the cash figure. Repricing is about equity marks; it says nothing about
    # when a cash balance was last confirmed. Live, that substitution presented cash
    # last confirmed 2026-08-03 as being as fresh as this morning's marks.
    #
    # Derived from the cash rows themselves via the SAME function the capital plan
    # and the operator product use, so the surfaces cannot drift. No stamp anywhere
    # yields None -- a visible absence, never a borrowed clock.
    cash_ts = _cash_ts_from_rows(rows, doc)
    # advisory / desk
    advisory_ts = (
        decision.get("advisory_as_of")
        or decision.get("verdict_as_of")
        or (decision.get("item") or {}).get("as_of")
        or extra.get("advisory_as_of")
    )
    analyst_ts = decision.get("analyst_as_of") or extra.get("analyst_as_of")
    thesis_ts = (
        decision.get("thesis_as_of")
        or extra.get("thesis_as_of")
        or decision.get("research_as_of")
        or extra.get("research_as_of")
    )
    hermes_ts = decision.get("hermes_as_of") or extra.get("hermes_as_of")
    sector_ts = decision.get("sector_as_of") or extra.get("sector_as_of")
    technical_ts = decision.get("technical_as_of") or extra.get("technical_as_of")
    research_ts = decision.get("research_as_of") or extra.get("research_as_of")
    strategy_ts = (
        decision.get("strategy_as_of")
        or extra.get("strategy_as_of")
        or extra.get("strategy_context_as_of")
    )
    risk_ts = decision.get("risk_as_of") or extra.get("risk_as_of") or holdings_ts
    tax_ts = decision.get("tax_as_of") or pos.get("last_reconciled_at") or extra.get("tax_as_of")
    # Real decision clock only — never computed_at / plan_computed_at / now.
    decision_ts = decision.get("revalidated_at") or decision.get("generated_at")
    quote_source = (
        extra.get("quote_source")
        or decision.get("quote_source")
        or row_quotes.get("worst_source")
        or pos.get("price_source")
        or "holdings_quote"
    )
    return {
        "holdings": holdings_ts,
        "holdings_snapshot": holdings_snapshot_ts,
        "holdings_updated_at": holdings_updated_at,
        "quote": quote_ts,
        "market_value": mv_ts,
        "cash": cash_ts,
        "advisory": advisory_ts,
        "analyst": analyst_ts,
        "thesis": thesis_ts,
        "hermes": hermes_ts,
        "sector": sector_ts,
        "technical": technical_ts,
        "research": research_ts,
        "strategy": strategy_ts,
        "risk": risk_ts,
        "tax": tax_ts,
        "decision": decision_ts,
        "account_row_quotes": row_quotes,
        "sources": {
            "holdings": "holdings.json",
            "quote": quote_source,
            "market_value": "holdings.market_value",
            "cash": "holdings.cash",
            "advisory": "opportunity_queue/directive",
            "analyst": "analyst_consensus",
            "thesis": "cio_thesis",
            "hermes": "hermes_research",
            "sector": "sector_opportunity",
            "technical": "technicals",
            "research": "fundamental_research",
            "strategy": "strategy_context",
            "risk": "risk_posture/concentration",
            "tax": "tax_lots/cost_basis",
            "decision": "capital_plan/decision",
        },
    }


def evaluate_decision_actionability(
    decision: dict[str, Any],
    *,
    holdings_doc: Optional[dict[str, Any]] = None,
    position_row: Optional[dict[str, Any]] = None,
    position_rows: Optional[list[dict[str, Any]]] = None,
    financial_truth: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    min_evidence_sources: int = MIN_EVIDENCE_SOURCES_ACT_NOW,
) -> dict[str, Any]:
    """Return action_label + freshness board for one decision."""
    now = now or datetime.now(timezone.utc)
    session = _session_context(now)
    d = decision or {}
    extra = extra or {}
    symbol = str(d.get("symbol") or "").upper()
    rows = _merge_position_rows(
        holdings_doc=holdings_doc,
        symbol=symbol,
        position_row=position_row,
        position_rows=position_rows,
    )
    primary_row = rows[0] if rows else position_row
    stance = str(d.get("stance_code") or d.get("cio_stance") or d.get("stance") or "HOLD").upper()
    if stance in ("TRIM", "EXIT", "ADD", "RE_ENTER", "HOLD", "REVIEW"):
        pass
    else:
        # professional labels
        su = stance.upper()
        if "TRIM" in su:
            stance = "TRIM"
        elif "EXIT" in su:
            stance = "EXIT"
        elif "ENTER" in su or "ADD" in su:
            stance = "ADD"
        else:
            stance = "HOLD"

    delta = _fnum(d.get("recommended_delta_usd") if d.get("recommended_delta_usd") is not None else d.get("delta_usd"))
    why = str(d.get("why_now") or "")
    risk = str(d.get("risk") or "")

    ft = financial_truth or {}
    suppress = set(ft.get("suppress_act_now_symbols") or ft.get("conflicted_symbols") or [])
    ft_quality = str(
        d.get("financial_truth_quality")
        or ft.get("overall_quality")
        or STATE_VERIFIED_AS_OF
    )
    ft_ok_for_act = (
        symbol not in suppress
        and ft_quality not in (STATE_CONFLICTED, STATE_DATA_UNAVAILABLE)
        and not d.get("act_now_suppressed")
    )

    stamps = collect_evidence_timestamps(
        decision=d,
        holdings_doc=holdings_doc,
        position_row=primary_row,
        position_rows=rows,
        financial_truth=ft,
        extra=extra,
        symbol=symbol,
    )
    src = stamps.get("sources") or {}
    row_quotes = stamps.get("account_row_quotes") or inspect_account_row_quotes(rows)
    # Any undated contributing mark fails the quote/MV clock (never invent now).
    quote_ts = stamps["quote"]
    mv_ts = stamps["market_value"]
    quote_present = bool(quote_ts or primary_row or row_quotes.get("any_present"))
    mv_present = bool(mv_ts or d.get("current_value_usd") is not None or row_quotes.get("any_present"))
    if row_quotes.get("any_undated"):
        quote_ts = None
        mv_ts = None

    # Evidence classes
    board = [
        _freshness_record(
            name="holdings", ts=stamps["holdings"], max_age_sec=HOLDINGS_FRESH_SEC,
            now=now, required_for_act_now=True, source=src.get("holdings", ""),
            present=bool(holdings_doc or stamps["holdings"]),
            session=session,
        ),
        _freshness_record(
            name="quote", ts=quote_ts, max_age_sec=QUOTE_FRESH_SEC,
            now=now, required_for_act_now=True, source=str(src.get("quote") or ""),
            present=quote_present,
            after_hours_ok=True, session=session,
        ),
        _freshness_record(
            name="market_value", ts=mv_ts, max_age_sec=QUOTE_FRESH_SEC,
            now=now, required_for_act_now=True, source=str(src.get("market_value") or ""),
            present=mv_present,
            after_hours_ok=True, session=session,
        ),
        _freshness_record(
            name="cash", ts=stamps["cash"], max_age_sec=CASH_FRESH_SEC,
            now=now, required_for_act_now=True, source=str(src.get("cash") or ""),
            present=bool(stamps["cash"] or holdings_doc),
            session=session,
        ),
        _freshness_record(
            name="risk", ts=stamps["risk"], max_age_sec=RISK_FRESH_SEC,
            now=now, required_for_act_now=("concentration" in risk.lower()),
            source=str(src.get("risk") or ""),
            present=bool(risk) or bool(stamps["risk"]),
            session=session,
        ),
        _freshness_record(
            name="advisory", ts=stamps["advisory"], max_age_sec=ADVISORY_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("advisory") or ""),
            present=bool(stamps["advisory"]) or (
                bool(why) and _NEUTRAL_WHY not in why.lower()
            ),
            session=session,
        ),
        _freshness_record(
            name="analyst", ts=stamps["analyst"], max_age_sec=ANALYST_MAX_AGE_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("analyst") or ""),
            present=bool(stamps["analyst"]),
            session=session,
        ),
        _freshness_record(
            name="thesis", ts=stamps["thesis"], max_age_sec=THESIS_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("thesis") or ""),
            present=bool(stamps["thesis"]),
            session=session,
        ),
        _freshness_record(
            name="hermes", ts=stamps["hermes"], max_age_sec=HERMES_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("hermes") or ""),
            present=bool(stamps["hermes"]),
            session=session,
        ),
        _freshness_record(
            name="sector", ts=stamps["sector"], max_age_sec=SECTOR_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("sector") or ""),
            present=bool(stamps["sector"]),
            session=session,
        ),
        _freshness_record(
            name="technical", ts=stamps.get("technical"), max_age_sec=SECTOR_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("technical") or ""),
            present=bool(stamps.get("technical")),
            session=session,
        ),
        _freshness_record(
            name="research", ts=stamps.get("research"), max_age_sec=THESIS_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("research") or ""),
            present=bool(stamps.get("research")),
            session=session,
        ),
        _freshness_record(
            name="tax", ts=stamps["tax"], max_age_sec=HOLDINGS_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("tax") or ""),
            present=bool(stamps["tax"]),
            session=session,
        ),
        _freshness_record(
            name="decision", ts=stamps["decision"], max_age_sec=DECISION_REVALIDATE_SEC,
            now=now, required_for_act_now=True,
            source=str(src.get("decision") or ""),
            present=bool(stamps["decision"]),
            session=session,
        ),
    ]
    # Undated decision clocks stay undated. Never mint a fresh-now pass.

    by_name = {r["name"]: r for r in board}

    same_snapshot_quote = _market_price_from_holdings_snapshot(
        stamps=stamps, src=src, extra=extra, decision=d, position_row=primary_row,
    )
    risk_book_derived = _risk_from_book(stamps, extra, d)
    tax_book_derived = _tax_from_book(stamps, extra, d)

    # Collapse same-snapshot holdings + quote + cash into financial_state.
    groups: dict[str, dict[str, Any]] = {}

    def _add_group(name: str, member: str, *, independent: bool) -> None:
        rec = by_name.get(member)
        if rec is None:
            return
        g = groups.setdefault(name, {
            "name": name,
            "members": [],
            "independent": independent,
            "ok": False,
        })
        if member not in g["members"]:
            g["members"].append(member)
        if not independent:
            g["independent"] = False
        if _record_ok(rec):
            g["ok"] = True

    _add_group(GROUP_FINANCIAL_STATE, "holdings", independent=False)
    _add_group(GROUP_FINANCIAL_STATE, "cash", independent=False)
    if same_snapshot_quote:
        _add_group(GROUP_FINANCIAL_STATE, "quote", independent=False)
        _add_group(GROUP_FINANCIAL_STATE, "market_value", independent=False)
    else:
        _add_group(GROUP_MARKET_PRICE, "quote", independent=True)
        _add_group(GROUP_MARKET_PRICE, "market_value", independent=True)
    _add_group(GROUP_RISK, "risk", independent=not risk_book_derived)
    _add_group(GROUP_FUNDAMENTAL, "thesis", independent=True)
    _add_group(GROUP_FUNDAMENTAL, "research", independent=True)
    _add_group(GROUP_HERMES, "hermes", independent=True)
    _add_group(GROUP_SECTOR, "sector", independent=True)
    _add_group(GROUP_ANALYST, "analyst", independent=True)
    _add_group(GROUP_TECHNICAL, "technical", independent=True)
    _add_group(GROUP_TAX_LOT, "tax", independent=not tax_book_derived)
    if by_name.get("advisory") and _record_ok(by_name["advisory"]) and _NEUTRAL_WHY not in why.lower():
        _add_group(GROUP_STRATEGY, "advisory", independent=True)

    evidence_groups = [groups[k] for k in EVIDENCE_GROUPS if k in groups and groups[k]["members"]]
    ok_groups = [g for g in evidence_groups if g["ok"]]
    source_count = len(ok_groups)
    independent_groups = [
        g["name"] for g in ok_groups
        if g["independent"] and g["name"] in INDEPENDENT_THESIS_RESEARCH_RISK
    ]
    independent_count = len(independent_groups)

    required = [r for r in board if r["required_for_act_now"]]
    required_pass = all(r["pass"] for r in required)

    # Material stance?
    is_action_stance = stance in ("TRIM", "EXIT", "ADD", "RE_ENTER")
    has_delta = abs(delta) >= 0.01
    thin_hold = (not is_action_stance) or (
        abs(delta) < 0.01 and _NEUTRAL_WHY in why.lower()
    )

    reasons: list[str] = []
    label = LABEL_WATCH

    # 1) Financial truth conflict
    if not ft_ok_for_act or ft_quality == STATE_CONFLICTED or symbol in suppress:
        label = LABEL_DATA_CONFLICT
        reasons.append("financial_truth_conflict_or_suppressed")
    # 2) Required freshness failures
    elif not required_pass:
        failed = [r["name"] for r in required if not r["pass"]]
        if any(by_name[n]["quality"] == STATE_STALE or by_name[n]["detail"] == "stale" for n in failed if n in by_name):
            label = LABEL_STALE_REFRESH
            reasons.append("required_evidence_stale:" + ",".join(failed))
        elif any(by_name[n]["detail"] in ("undated", "missing") for n in failed if n in by_name):
            label = LABEL_REVALIDATE
            reasons.append("required_evidence_undated_or_missing:" + ",".join(failed))
        else:
            label = LABEL_STALE_REFRESH
            reasons.append("required_freshness_fail:" + ",".join(failed))
    # 3) Thin / non-material
    elif thin_hold or not is_action_stance:
        label = LABEL_WATCH
        reasons.append("non_actionable_stance_or_thin_signal")
    # 4) Insufficient distinct evidence groups (after same-snapshot collapse)
    elif source_count < min_evidence_sources:
        label = LABEL_REVIEW
        reasons.append(f"insufficient_evidence_sources:{source_count}<{min_evidence_sources}")
    # 5) Book-only evidence (holdings+quote same snapshot, no independent thesis/research/risk)
    elif independent_count < 1:
        label = LABEL_REVIEW
        reasons.append("insufficient_independent_evidence_beyond_book")
        if same_snapshot_quote:
            reasons.append("holdings_quote_same_snapshot_collapsed")
    # 6) Action stance + delta + independent evidence
    elif is_action_stance and has_delta and source_count >= min_evidence_sources and required_pass and ft_ok_for_act:
        # ACT NOW only if financial truth ok AND not overall STALE book
        if ft_quality == STATE_STALE:
            label = LABEL_STALE_REFRESH
            reasons.append("financial_truth_book_stale")
        else:
            label = LABEL_ACT_NOW
            reasons.append("fresh_material_actionable")
    else:
        label = LABEL_REVIEW
        reasons.append("default_review")

    act_now = label == LABEL_ACT_NOW
    return {
        "version": FRESHNESS_MATERIALITY_VERSION,
        "symbol": symbol,
        "stance": stance,
        "recommended_delta_usd": delta,
        "action_label": label,
        "act_now": act_now,
        "actionable": act_now,  # strict: only ACT_NOW is fully actionable
        "operator_priority": {
            LABEL_ACT_NOW: 0,
            LABEL_DATA_CONFLICT: 1,
            LABEL_STALE_REFRESH: 2,
            LABEL_REVALIDATE: 3,
            LABEL_REVIEW: 4,
            LABEL_WATCH: 5,
        }.get(label, 9),
        "reasons": reasons,
        "evidence_source_count": source_count,
        "min_evidence_sources": min_evidence_sources,
        "evidence_groups": evidence_groups,
        "independent_evidence_groups": independent_groups,
        "independent_evidence_count": independent_count,
        "same_snapshot_quote": same_snapshot_quote,
        "account_rows_checked": row_quotes.get("rows") or [],
        "financial_truth_quality": ft_quality,
        "financial_truth_ok_for_act_now": ft_ok_for_act,
        "session": session,
        "freshness_board": board,
        "authority": "READ_ONLY_ADVISORY",
    }


def apply_to_decisions(
    decisions: list[dict[str, Any]],
    *,
    holdings_doc: Optional[dict[str, Any]] = None,
    financial_truth: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Annotate each decision; return (decisions, summary)."""
    now = now or datetime.now(timezone.utc)
    # Index every contributing holdings row by symbol (not first-row only)
    by_sym_rows: dict[str, list[dict[str, Any]]] = {}
    for r in (holdings_doc or {}).get("holdings") or []:
        if not isinstance(r, dict) or r.get("is_cash"):
            continue
        sym = str(r.get("symbol") or "").upper()
        if sym:
            by_sym_rows.setdefault(sym, []).append(r)

    out: list[dict[str, Any]] = []
    counts: dict[str, int] = {k: 0 for k in ACTION_LABELS}
    act_now_ids: list[str] = []

    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        dd = dict(d)
        sym = str(dd.get("symbol") or "").upper()
        rows = by_sym_rows.get(sym) or []
        ev = evaluate_decision_actionability(
            dd,
            holdings_doc=holdings_doc,
            position_row=rows[0] if rows else None,
            position_rows=rows,
            financial_truth=financial_truth,
            extra=extra,
            now=now,
        )
        dd["action_label"] = ev["action_label"]
        dd["act_now"] = ev["act_now"]
        dd["actionable"] = ev["actionable"]
        dd["freshness"] = {
            "version": ev["version"],
            "reasons": ev["reasons"],
            "evidence_source_count": ev["evidence_source_count"],
            "evidence_groups": ev.get("evidence_groups"),
            "independent_evidence_groups": ev.get("independent_evidence_groups"),
            "independent_evidence_count": ev.get("independent_evidence_count"),
            "same_snapshot_quote": ev.get("same_snapshot_quote"),
            "account_rows_checked": ev.get("account_rows_checked"),
            "session": ev["session"],
            "board": ev["freshness_board"],
            "financial_truth_quality": ev["financial_truth_quality"],
        }
        # Human prose for operator surfaces
        dd["action_label_display"] = {
            LABEL_ACT_NOW: "ACT NOW",
            LABEL_REVIEW: "REVIEW",
            LABEL_WATCH: "WATCH",
            LABEL_REVALIDATE: "REVALIDATE",
            LABEL_DATA_CONFLICT: "DATA CONFLICT",
            LABEL_STALE_REFRESH: "STALE — REFRESH REQUIRED",
        }.get(ev["action_label"], ev["action_label"])
        counts[ev["action_label"]] = counts.get(ev["action_label"], 0) + 1
        if ev["act_now"]:
            did = dd.get("decision_id") or sym
            act_now_ids.append(str(did))
        out.append(dd)

    summary = {
        "version": FRESHNESS_MATERIALITY_VERSION,
        "evaluated_at": now.isoformat(),
        "counts": counts,
        "act_now_count": counts.get(LABEL_ACT_NOW, 0),
        "act_now_decision_ids": act_now_ids,
        "authority": "READ_ONLY_ADVISORY",
    }
    raw = json.dumps({"counts": counts, "act_now": act_now_ids}, sort_keys=True)
    summary["gate_hash"] = hashlib.sha256(raw.encode()).hexdigest()
    return out, summary


def attach_to_capital_plan(
    plan: dict[str, Any],
    *,
    holdings_doc: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Apply freshness/materiality after financial truth attachment."""
    out = dict(plan)
    ft = out.get("financial_truth_gate") or {}
    extra = {"plan_computed_at": out.get("computed_at") or out.get("as_of")}
    decisions, summary = apply_to_decisions(
        out.get("position_decisions") or [],
        holdings_doc=holdings_doc,
        financial_truth=ft,
        extra=extra,
        now=now,
    )
    out["position_decisions"] = decisions
    out["freshness_materiality_gate"] = summary
    return out
