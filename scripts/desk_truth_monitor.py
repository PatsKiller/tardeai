#!/usr/bin/env python3
"""desk_truth_monitor.py — three read-only desk truth checks, one per n8n lane.

Operator 2026-10-22: "fix all of these n8n first for scheduling and monitoring". The holdings writer had been off for a
week (the holdings store missing NAVN, SCHD/SCHG 2,000 short each, cash +$153,920 vs positions_current), the options desk
carried 09:30 quotes until noon, and nothing said so. Each check is its own dispatcher lane:

  --check holdings-drift          lane holdings-drift-monitor
      the holdings store (lib.portfolio_positions.load_store) vs positions_current (SELECT, read-only session): per account
      a symbol missing on either side, a share count off by more than qty_tolerance, account cash off by more than
      cash_tolerance_usd; plus holdings freshness (newest broker_position_as_of_at, else positions_built_at) older than
      holdings_stale_after_h inside the trading session, and positions_current itself stale (its numbers then do not
      count as truth: POSITIONS_CURRENT_STALE, the comparison still printed).
  --check options-desk-staleness  lane options-desk-staleness-monitor
      options_proposals.json freshness = newer of generated_at and quote_refresh.at; older than max_age_min during a
      configured session is DESK_STALE.
  --check held-exit-coverage      lane held-exit-coverage-monitor
      every live held position (positions_current, non-cash, qty > 0) needs a stop_lifecycle row for the same account
      and symbol in a WORKING lifecycle; one without is UNCOVERED. Paper-account stop rows are counted and tagged PAPER.
      A stale stop_lifecycle snapshot is SNAPSHOT_STALE and the coverage verdict is NOT_MEASURED, never "uncovered".
      (The lane id avoids the dispatcher's forbidden word for stop WRITERS; this check reads the snapshot that
      scripts/stop_lifecycle_monitor.py writes and never reaches a broker, an order route or a stop write.)

Every check: --dry-run (default) prints the findings and writes nothing; --apply writes the lane's LaneRunReceipt@v2
(data/runtime/<lane>_last.json, read by GET /api/v2/needs-action source desk_truth) and its alert state, and queues
ONE host comms intent (desk/<check>_finding, DIGEST -> P2 through the comms-intent consumer and the incident notifier)
only when the alertable finding set GAINED a finding since the last apply. Never a sender, never a broker, never a
store write other than its own receipt and alert state (AGENTS.md §0 rule 5: report both sides; it never repairs).

Database: a direct psycopg2 read-only session (set_session(readonly=True)) from DB_HOST/DB_PORT/DB_NAME/DB_USER/
DB_PASSWORD, not db_adapter: db_adapter's closure reaches the broker transport (tests/test_lane_transitive_capabilities
_20261015.py), and positions_current / stop_lifecycle have no data-broker projection (config/data_source_authority.json
positions_store "projection": null) — two direct store reads, stated in the PR (AGENTS.md §24.3).

Exit 0 = the check completed (findings are output, not failures); 1 = a required source is unreadable
(dependency_unavailable); 2 = usage. MBI_BEHAVIOR = 0. Authority: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = "scripts/desk_truth_monitor.py"
SCHEMA = "DeskTruthCheck@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
PRODUCER = "desk_truth_monitor"
CONFIG = ROOT / "config" / "desk_truth_monitors.json"
ET = ZoneInfo("America/New_York")

#: check -> lane and its host intent route (config/host_comms_intent_routes.json, producer desk_truth_monitor, DIGEST).
CHECKS = {
    "holdings-drift": {"lane": "holdings-drift-monitor", "domain": "positions", "kind": "holdings_drift_finding"},
    "options-desk-staleness": {"lane": "options-desk-staleness-monitor", "domain": "data", "kind": "options_desk_stale"},
    "held-exit-coverage": {"lane": "held-exit-coverage-monitor", "domain": "stops", "kind": "held_exit_coverage_gap"},
    "display-truth": {"lane": "display-truth-monitor", "domain": "data", "kind": "display_truth_finding"},
}
DEP = "dependency_unavailable"


# ── shared helpers ──────────────────────────────────────────────────────────────────────────────────────────────


def proposals_path() -> Path:
    try:
        from scripts.lib.desk_session import proposals_path as pp
    except ImportError:  # pragma: no cover
        from lib.desk_session import proposals_path as pp  # type: ignore[no-redef]
    return pp()


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    return json.loads((path or CONFIG).read_text(encoding="utf-8"))


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hhmm(text: str) -> time:
    h, m = str(text).split(":")
    return time(int(h), int(m))


def is_trading_day(now: datetime) -> bool:
    try:
        from scripts.lib.cio_market_session import is_trading_day as itd
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from lib.cio_market_session import is_trading_day as itd  # type: ignore[no-redef]
    return bool(itd(now))


def in_session(now: datetime, start: str, end: str, *, trading_day: Callable[[datetime], bool] = is_trading_day) -> bool:
    local = now.astimezone(ET)
    return trading_day(now) and _hhmm(start) <= local.time() <= _hhmm(end)


def _f(code: str, key: str, detail: str, *, alert: bool = True, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "key": key, "detail": detail, "alert": alert, "evidence": evidence}


def fingerprint(keys: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(keys))).encode("utf-8")).hexdigest()[:16]


# ── holdings drift ──────────────────────────────────────────────────────────────────────────────────────────────


def _is_cash_row(h: Mapping[str, Any]) -> bool:
    return bool(h.get("is_cash")) or str(h.get("symbol") or "").upper() in {"CASH", "SPAXX", "FDRXX"}


def holdings_drift(store: Mapping[str, Any], current: list[Mapping[str, Any]], cfg: Mapping[str, Any], *,
                   now: datetime, pc_as_of: Optional[datetime], session: bool) -> dict[str, Any]:
    """Pure. store = the holdings-store document; current = positions_current rows {account_key, symbol, qty, is_cash}."""
    aliases = dict(cfg.get("holdings_account_aliases") or {})
    accounts = list(cfg.get("accounts") or [])
    qtol = float(cfg.get("qty_tolerance", 0.001))
    ctol = float(cfg.get("cash_tolerance_usd", 50.0))
    held: dict[tuple[str, str], float] = {}
    h_cash: dict[str, float] = {}
    newest: Optional[datetime] = None
    for h in store.get("holdings") or []:
        acct = aliases.get(h.get("account"), h.get("account"))
        if acct not in accounts:
            continue
        if _is_cash_row(h):
            h_cash[acct] = h_cash.get(acct, 0.0) + (_num(h.get("market_value")) or _num(h.get("shares")) or 0.0)
            continue
        sym = str(h.get("symbol") or "").upper()
        qty = _num(h.get("shares") if h.get("shares") is not None else h.get("quantity")) or 0.0
        if sym and abs(qty) > qtol:
            held[(acct, sym)] = held.get((acct, sym), 0.0) + qty
        t = _ts(h.get("broker_position_as_of_at"))
        if t and (newest is None or t > newest):
            newest = t
    pc: dict[tuple[str, str], float] = {}
    pc_cash: dict[str, float] = {}
    for c in current:
        acct = str(c.get("account_key") or "")
        if acct not in accounts:
            continue
        if c.get("is_cash"):
            pc_cash[acct] = pc_cash.get(acct, 0.0) + (_num(c.get("qty")) or 0.0)
            continue
        q = _num(c.get("qty")) or 0.0
        if abs(q) > qtol:
            pc[(acct, str(c.get("symbol") or "").upper())] = q
    findings: list[dict[str, Any]] = []
    for k in sorted(set(held) | set(pc)):
        a, s = k
        hq, cq = held.get(k), pc.get(k)
        if hq is None:
            findings.append(_f("MISSING_IN_HOLDINGS", f"missing:{a}:{s}", f"{a} {s}: positions_current {cq:g}, "
                               "the holdings store none", account=a, symbol=s, positions_current_qty=cq))
        elif cq is None:
            findings.append(_f("PHANTOM_IN_HOLDINGS", f"phantom:{a}:{s}", f"{a} {s}: the holdings store {hq:g}, "
                               "positions_current none", account=a, symbol=s, holdings_qty=hq))
        elif abs(hq - cq) > qtol:
            findings.append(_f("QTY_DRIFT", f"qty:{a}:{s}", f"{a} {s}: the holdings store {hq:g} vs positions_current {cq:g} "
                               f"({hq - cq:+g})", account=a, symbol=s, holdings_qty=hq, positions_current_qty=cq))
    for a in accounts:
        hc, cc = h_cash.get(a), pc_cash.get(a)
        if hc is None and cc is None:
            continue
        if hc is None or cc is None or abs(hc - cc) > ctol:
            findings.append(_f("CASH_DRIFT", f"cash:{a}", f"{a} cash: the holdings store {hc if hc is not None else 'none'} "
                               f"vs positions_current {cc if cc is not None else 'none'}", account=a,
                               holdings_cash=hc, positions_current_cash=cc,
                               delta=(round(hc - cc, 2) if hc is not None and cc is not None else None)))
    basis = "broker_position_as_of_at"
    fresh = newest
    if fresh is None:
        fresh, basis = _ts(store.get("positions_built_at")), "positions_built_at"
    age_h = round((now - fresh).total_seconds() / 3600.0, 2) if fresh else None
    stale_h = float(cfg.get("holdings_stale_after_h", 2.0))
    if session and (age_h is None or age_h > stale_h):
        findings.append(_f("HOLDINGS_STALE", "holdings_stale", f"the holdings store positions last confirmed "
                           f"{'never' if age_h is None else f'{age_h:g} h ago'} ({basis}); bound {stale_h:g} h in session",
                           basis=basis, as_of=fresh.isoformat() if fresh else None, age_h=age_h))
    pc_age = round((now - pc_as_of).total_seconds() / 3600.0, 2) if pc_as_of else None
    pc_stale = session and (pc_age is None or pc_age > float(cfg.get("positions_current_stale_after_h", 1.0)))
    if pc_stale:
        findings.append(_f("POSITIONS_CURRENT_STALE", "positions_current_stale",
                           f"positions_current newest as_of {'none' if pc_age is None else f'{pc_age:g} h ago'}: the "
                           "comparison is printed but its side is not current truth", as_of=pc_as_of and
                           pc_as_of.isoformat(), age_h=pc_age))
    return {"findings": findings, "holdings_as_of": fresh.isoformat() if fresh else None, "holdings_basis": basis,
            "holdings_age_h": age_h, "positions_current_age_h": pc_age, "in_session": session,
            "compared": {"holdings_positions": len(held), "positions_current_positions": len(pc),
                         "accounts": accounts}}


# ── portfolio total (PortfolioTotal@v1) ───────────────────────────────────────────────────────────────────────


def portfolio_total_agreement(store: Mapping[str, Any], cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Pure. The one total the pages publish, checked where it is decided.

    LQ-20261107-1611: Home header, Book and the All-accounts row read one contract
    (``scripts/lib/portfolio_total_contract.py``). Its alerting findings are this lane's findings, so a
    store whose ``portfolio_totals.total_value`` stops equalling its rows pages without anyone opening
    the page — the header would otherwise show a number its own rows do not sum to. The broker total is
    reported for the receipt only: the repricer's re-mark between passes is expected, not drift.
    """
    try:
        from scripts.lib import portfolio_total_contract as ptc
    except ImportError:  # pragma: no cover
        from lib import portfolio_total_contract as ptc  # type: ignore[no-redef] -- the host lane runs with scripts/ on sys.path, tests with the repo root; one of the two names is always missing

    contract = ptc.build_portfolio_total(
        store,
        tolerance_usd=float(cfg.get("tolerance_usd", ptc.DEFAULT_TOLERANCE_USD)),
        min_position_usd=float(cfg.get("min_position_usd", ptc.MIN_POSITION_USD)),
    )
    findings = [_f(f["code"], f"portfolio_total:{f['code']}", f["detail"], alert=bool(f["alert"]),
                   **f.get("evidence", {}))
                for f in contract.get("findings") or [] if f.get("alert")]
    report = {k: contract.get(k) for k in ("contract_version", "value", "basis", "as_of", "cash",
                                           "position_count", "position_scope", "position_summary", "agree")}
    report["alternatives"] = [{"name": a["name"], "value": a["value"], "delta": a["delta"],
                               "basis": a["basis"]} for a in contract.get("alternatives") or []]
    return {"portfolio_total": report, "findings": findings}


# ── options desk staleness ──────────────────────────────────────────────────────────────────────────────────────


def options_desk_staleness(doc: Mapping[str, Any], cfg: Mapping[str, Any], *, now: datetime,
                           session_label: str) -> dict[str, Any]:
    gen = _ts(doc.get("generated_at"))
    qr = _ts((doc.get("quote_refresh") or {}).get("at")) if isinstance(doc.get("quote_refresh"), Mapping) else None
    fresh = max([t for t in (gen, qr) if t], default=None)
    basis = "quote_refresh.at" if (qr and fresh == qr and qr != gen) else "generated_at"
    age_min = round((now - fresh).total_seconds() / 60.0, 1) if fresh else None
    bound = float(cfg.get("max_age_min", 45))
    findings: list[dict[str, Any]] = []
    if session_label in set(cfg.get("sessions") or ["REGULAR"]) and (age_min is None or age_min > bound):
        findings.append(_f("DESK_STALE", "desk_stale", f"options desk last refreshed "
                           f"{'never' if age_min is None else f'{age_min:g} min ago'} ({basis}); bound {bound:g} min "
                           f"in {session_label}", basis=basis, generated_at=doc.get("generated_at"),
                           quote_refresh_at=(doc.get("quote_refresh") or {}).get("at")
                           if isinstance(doc.get("quote_refresh"), Mapping) else None, age_min=age_min))
    return {"findings": findings, "generated_at": doc.get("generated_at"), "freshness_basis": basis,
            "age_min": age_min, "market_session": session_label, "cards": len(doc.get("proposals") or [])}


# ── held exit coverage ──────────────────────────────────────────────────────────────────────────────────────────


def held_exit_coverage(current: list[Mapping[str, Any]], snapshot: list[Mapping[str, Any]], cfg: Mapping[str, Any],
                       *, now: datetime, session: bool) -> dict[str, Any]:
    aliases = dict(cfg.get("account_aliases") or {})
    working = {str(x) for x in cfg.get("working_lifecycles") or ["working", "near_trigger"]}
    paper = {str(x) for x in cfg.get("paper_accounts") or []}
    exclude = {str(x).lower() for x in cfg.get("exclude_asset_types") or []}
    exempt = {(str(e.get("account")), str(e.get("symbol")).upper()) for e in cfg.get("exempt") or []
              if isinstance(e, Mapping)}
    floor = float(cfg.get("min_position_value_usd", 0) or 0)
    held = {}
    below_floor = 0
    for c in current:
        if c.get("is_cash") or str(c.get("asset_type") or "").lower() in exclude:
            continue
        q = _num(c.get("qty")) or 0.0
        if q <= 0:
            continue
        mv = _num(c.get("broker_market_value"))
        if floor and mv is not None and abs(mv) < floor:
            below_floor += 1  # dust / fractional DRIP remainders; a missing value is never treated as small
            continue
        held[(str(c.get("account_key")), str(c.get("symbol") or "").upper())] = q
    covered: set[tuple[str, str]] = set()
    paper_rows = 0
    newest: Optional[datetime] = None
    for s in snapshot:
        acct = aliases.get(s.get("account"), s.get("account"))
        t = _ts(s.get("snapshot_at"))
        if t and (newest is None or t > newest):
            newest = t
        if acct in paper:
            paper_rows += 1
            continue
        if str(s.get("lifecycle") or "") in working:
            covered.add((str(acct), str(s.get("symbol") or "").upper()))
    age_h = round((now - newest).total_seconds() / 3600.0, 2) if newest else None
    stale = age_h is None or age_h > float(cfg.get("snapshot_stale_after_h", 2.0))
    findings: list[dict[str, Any]] = []
    if stale and session:
        findings.append(_f("SNAPSHOT_STALE", "snapshot_stale", f"stop_lifecycle snapshot "
                           f"{'empty' if age_h is None else f'{age_h:g} h old'}: coverage NOT_MEASURED",
                           age_h=age_h))
    uncovered = sorted(k for k in held if k not in covered and k not in exempt)
    for a, s in uncovered:
        findings.append(_f("UNCOVERED", f"uncovered:{a}:{s}", f"{a} {s}: held {held[(a, s)]:g}, no WORKING stop",
                           alert=not stale, account=a, symbol=s, held_qty=held[(a, s)], tag="LIVE"))
    return {"findings": findings, "held": len(held), "covered": len(held) - len(uncovered),
            "uncovered": len(uncovered), "exempt": len([k for k in held if k in exempt]),
            "below_value_floor": below_floor, "value_floor_usd": floor,
            "coverage_verdict": "NOT_MEASURED" if stale else ("GAPS" if uncovered else "COVERED"),
            "snapshot_age_h": age_h, "paper_stop_rows": paper_rows, "paper_tag": "PAPER",
            "paper_positions": "NOT_MEASURED (no paper position source is read; no broker call)",
            "in_session": session}


# ── display truth (LQ-20261107-1646) ───────────────────────────────────────────────────────────────────────────
#
# The operator's question is not "did a lane succeed" but "is what the page shows the thing itself". Every check above
# compares one store with another; this one recomputes the book from independent inputs and compares it to what the
# card serves, so a displayed number that stopped moving, a day P&L that was never re-marked, a stop advice the broker
# already satisfied and an as-of that is really a check time all become findings instead of a human noticing.
# It reads the snapshots the broker-read lanes write and NEVER calls a broker (AGENTS.md §0 rule 2).

DISPLAY_VERDICTS = ("OK", "DEGRADED", "BROKEN", "UNVERIFIABLE")


def _first(doc: Any, *names: str) -> Any:
    """The first of ``names`` present on a mapping; None when the document is not a mapping or carries none of them."""
    if not isinstance(doc, Mapping):
        return None
    for n in names:
        v = doc.get(n)
        if v is not None:
            return v
    return None


def _dt(v: Any) -> Optional[datetime]:
    """``_ts`` for display documents: also accepts epoch seconds, which a cache may serialise instead of an ISO string."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return _ts(v)


def _age_min(now: datetime, t: Optional[datetime]) -> Optional[float]:
    return round((now - t).total_seconds() / 60.0, 1) if t else None


def _age_h(now: datetime, t: Optional[datetime]) -> Optional[float]:
    return round((now - t).total_seconds() / 3600.0, 2) if t else None


def _quotes_by_symbol(quotes: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Newest row per symbol. The caller passes the Finviz feed only; this keeps the newest even so."""
    out: dict[str, dict[str, Any]] = {}
    for q in quotes or ():
        sym = str(q.get("symbol") or "").upper()
        if not sym:
            continue
        t = _dt(q.get("fetched_at"))
        prev = out.get(sym)
        if prev is None or (t is not None and (prev["fetched_at"] is None or t > prev["fetched_at"])):
            out[sym] = {"price": _num(q.get("price")), "prev_close": _num(q.get("prev_close")), "fetched_at": t,
                        "source": q.get("source")}
    return out


def _acc(d: dict[str, float], key: str, amount: float) -> None:
    """Add to a per-account sum. A missing key is "no contribution yet", never an assumed zero mark."""
    d[key] = d[key] + amount if key in d else amount


def recompute_book(current: Iterable[Mapping[str, Any]], quotes: Iterable[Mapping[str, Any]],
                   stops: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], *, now: datetime, session: bool
                   ) -> dict[str, Any]:
    """Pure. The book the card SHOULD show: value = qty x independent price + cash, day P&L = qty x (price - prev_close).

    ``cash`` is included because the card's total is a portfolio total, not a securities sum: a cash row contributes its
    dollar balance (``broker_market_value``, else ``qty``), never a quote. A symbol with no quote, no price, or (in
    session) a quote older than ``quote_stale_after_min`` is NOT priced: the total, the account values and the day P&L
    are then NOT_MEASURED rather than summed over a partial book, because a partial sum differs from the displayed one
    for the wrong reason. Stop coverage is still measured from ``stop_last_known`` — that is a different question, and
    a stale stop snapshot only makes it NOT_MEASURED too.
    """
    aliases = dict(cfg.get("account_aliases") or {})
    accounts = list(cfg.get("accounts") or [])
    exclude = {str(x).lower() for x in cfg.get("exclude_asset_types") or []}
    include_cash = bool(cfg.get("include_cash", True))
    quote_age_bound = float(cfg.get("quote_stale_after_min", 20))
    qmap = _quotes_by_symbol(quotes)
    newest_pc: Optional[datetime] = None
    by_account: dict[str, float] = {}
    day_by_account: dict[str, float] = {}
    unpriced: list[str] = []
    stale: list[str] = []
    no_prev: list[str] = []
    held: dict[tuple[str, str], float] = {}
    held_value: dict[tuple[str, str], Optional[float]] = {}
    cash_total = 0.0
    for c in current or ():
        acct = aliases.get(c.get("account_key"), c.get("account_key"))
        if acct not in accounts:
            continue
        t = _dt(c.get("as_of"))
        if t and (newest_pc is None or t > newest_pc):
            newest_pc = t
        if c.get("is_cash") or str(c.get("asset_type") or "").lower() == "cash":
            # cash is part of the book the card shows: the projected total is a portfolio total, not a securities sum.
            # A cash row's value is its dollar balance — broker_market_value when the writer stamps it, else qty.
            if not include_cash:
                continue
            v = _num(c.get("broker_market_value"))
            if v is None:
                v = _num(c.get("qty"))
            if v is not None:
                cash_total += v
                _acc(by_account, str(acct), v)
            continue
        if str(c.get("asset_type") or "").lower() in exclude:
            continue
        qty = _num(c.get("qty"))
        if qty is None or qty <= 0:
            continue
        sym = str(c.get("symbol") or "").upper()
        held[(str(acct), sym)] = qty
        held_value[(str(acct), sym)] = _num(c.get("broker_market_value"))
        q = qmap.get(sym)
        price = q["price"] if q else None
        age = _age_min(now, q["fetched_at"]) if q else None
        if price is None or price <= 0:
            unpriced.append(sym)
            continue
        if session and (age is None or age > quote_age_bound):
            stale.append(sym)  # an undated quote cannot be shown to be fresh either
            continue
        _acc(by_account, str(acct), qty * price)
        if q["prev_close"] is None:
            no_prev.append(sym)
        else:
            _acc(day_by_account, str(acct), qty * (price - q["prev_close"]))
    pc_age = _age_h(now, newest_pc)
    pc_stale = session and (newest_pc is None or pc_age > float(cfg.get("positions_stale_after_h", 1.0)))
    working = {str(x).strip().lower() for x in cfg.get("working_stop_statuses") or ["working"]}
    covered: set[tuple[str, str]] = set()
    stops_newest: Optional[datetime] = None
    for s in stops or ():
        t = _dt(s.get("captured_at"))
        if t and (stops_newest is None or t > stops_newest):
            stops_newest = t
        stop_qty = _num(s.get("qty"))
        if str(s.get("status") or "").strip().lower() not in working or stop_qty is None or stop_qty <= 0:
            continue  # a row with no readable qty covers nothing; it is not a zero-qty stop
        covered.add((str(aliases.get(s.get("account"), s.get("account"))), str(s.get("symbol") or "").upper()))
    stops_age = _age_h(now, stops_newest)
    stops_stale = session and (stops_newest is None or stops_age > float(cfg.get("stops_stale_after_h", 2.0)))
    reason = None
    if pc_stale:
        reason = "positions_snapshot_stale"
    elif stale:
        reason = "quotes_stale"
    elif unpriced:
        reason = "quotes_missing"
    measured = reason is None
    total = round(sum(by_account.values()), 2) if measured else None
    day_pnl = round(sum(day_by_account.values()), 2) if measured and not no_prev else None
    # the same value floor as held_exit_coverage: a fractional DRIP remainder is not an unprotected position, and a
    # missing value is checked rather than excused (a position whose size is unknown is not known to be small)
    floor = float(cfg.get("min_position_value_usd", 1000.0))
    uncovered: list[tuple[str, str]] = []
    below_floor = 0
    for k in sorted(held):
        if k in covered:
            continue
        v = held_value.get(k)
        if v is not None and v < floor:
            below_floor += 1
            continue
        uncovered.append(k)
    return {
        "status": "MEASURED" if measured else "NOT_MEASURED",
        "reason": reason,
        "total": total,
        "cash": round(cash_total, 2) if include_cash else None,
        "by_account": {a: round(v, 2) for a, v in sorted(by_account.items())} if measured else None,
        "day_pnl": day_pnl,
        "day_pnl_unpriced_prev_close": sorted(set(no_prev)),
        "unpriced_symbols": sorted(set(unpriced)),
        "stale_quote_symbols": sorted(set(stale)),
        "positions": len(held), "positions_as_of": newest_pc.isoformat() if newest_pc else None,
        "positions_age_h": pc_age, "in_session": session,
        "quote_age_bound_min": quote_age_bound,
        "quotes_read": len(qmap),
        "coverage": {
            "held": len(held), "covered": len(held) - len(uncovered),
            "uncovered": [{"account": a, "symbol": s, "held_qty": held[(a, s)], "value_usd": held_value.get((a, s))}
                          for a, s in uncovered],
            "below_value_floor": below_floor,
            "verdict": "NOT_MEASURED" if stops_stale else ("GAPS" if uncovered else "COVERED"),
            "stops_as_of": stops_newest.isoformat() if stops_newest else None,
            "stops_age_h": stops_age,
        },
    }


def displayed_overview(doc: Any) -> dict[str, Any]:
    """Normalise what the overview route serves (or its projection file). Unknown field names are NOT guessed: a
    document this cannot read is ``readable: False`` and the comparison is NOT_MEASURED."""
    if not isinstance(doc, Mapping):
        return {"readable": False}
    total = _num(_first(doc, "total_value", "book_value", "portfolio_value", "total"))
    raw_accounts = _first(doc, "accounts", "by_account", "account_values")
    by_account: dict[str, float] = {}
    if isinstance(raw_accounts, Mapping):
        for k, v in raw_accounts.items():
            n = _num(_first(v, "market_value", "value", "total_value") if isinstance(v, Mapping) else v)
            if n is not None:
                by_account[str(k)] = n
    elif isinstance(raw_accounts, (list, tuple)):
        for a in raw_accounts:
            if not isinstance(a, Mapping):
                continue
            key = _first(a, "account_key", "account", "key", "name")
            n = _num(_first(a, "market_value", "value", "total_value", "broker_market_value"))
            if key is not None and n is not None:
                by_account[str(key)] = n
    raw_day = _first(doc, "day_pnl", "today_pnl", "day_change")
    day = _num(_first(raw_day, "change", "value", "amount") if isinstance(raw_day, Mapping) else raw_day)
    as_of = _dt(_first(doc, "as_of", "generated_at", "updated_at", "projected_at"))
    source_as_of = _dt(_first(doc, "source_as_of", "marks_as_of", "quotes_as_of", "data_as_of"))
    readable = total is not None or bool(by_account)
    return {"readable": readable, "total": total, "by_account": by_account, "day_pnl": day,
            "as_of": as_of.isoformat() if as_of else None, "source_as_of": source_as_of.isoformat() if source_as_of
            else None}


def displayed_since_close(doc: Any) -> dict[str, Any]:
    """The stop advice the card serves, the stop read it names, and the clocks it was built on."""
    if not isinstance(doc, Mapping):
        return {"readable": False}
    brief = doc.get("cio_brief") if isinstance(doc.get("cio_brief"), Mapping) else {}
    rows = [r for r in (brief.get("stop_advice") or []) if isinstance(r, Mapping)]
    read = brief.get("stop_read") if isinstance(brief.get("stop_read"), Mapping) else None
    return {
        "readable": bool(rows) or read is not None,
        "advice_rows": rows,
        "stop_read": read,
        "generated_at": _dt(_first(doc, "generated_at", "updated_at")),
        "stop_advice_as_of": _dt(_first(brief, "as_of")),
    }


def _tolerance(value: Optional[float], usd: float, pct: float) -> float:
    base = 0.0 if value is None else abs(float(value))
    return max(float(usd), float(pct) * base)


def display_truth(current: Iterable[Mapping[str, Any]], quotes: Iterable[Mapping[str, Any]],
                  stops: Iterable[Mapping[str, Any]], displayed: Mapping[str, Any], cfg: Mapping[str, Any], *,
                  now: datetime, session: bool, previous: Optional[Mapping[str, Any]] = None,
                  reconcile: Optional[Callable[..., dict[str, Any]]] = None) -> dict[str, Any]:
    """Pure. Compares what is shown with what an independent recomputation says it should be.

    ``displayed`` = {"overview": doc|None, "since_close": doc|None, "header": doc|None, "card": doc|None,
    "dom": doc|None}. ``previous`` is the carry block of the last run (same shape as this report's ``carry``).
    ``reconcile`` is ``since_close_card.reconcile_stop_advice`` injected so this module holds no second copy of the
    stop-advice rule.
    """
    findings: list[dict[str, Any]] = []
    book = recompute_book(current, quotes, stops, cfg, now=now, session=session)
    ov = displayed_overview(displayed.get("overview"))
    sc = displayed_since_close(displayed.get("since_close"))
    dom = displayed.get("dom") if isinstance(displayed.get("dom"), Mapping) else None
    measured = book["status"] == "MEASURED"
    displayed_readable = bool(ov.get("readable") or sc.get("readable") or dom)

    # ---- the book, per total and per account ----------------------------------------------------------------
    if measured and ov.get("readable") and ov.get("total") is not None:
        tol = _tolerance(book["total"], cfg.get("total_tolerance_usd", 250.0), cfg.get("total_tolerance_pct", 0.0005))
        delta = round(ov["total"] - book["total"], 2)
        if abs(delta) > tol:
            findings.append(_f("DT_TOTAL_MISMATCH", "total",
                               f"the card shows ${ov['total']:,.2f}; the independent recomputation ${book['total']:,.2f} "
                               f"({delta:+,.2f}, bound ${tol:,.2f})", shown=ov["total"], recomputed=book["total"],
                               delta=delta, tolerance=round(tol, 2)))
        rec_accts = book.get("by_account") or {}
        accounts = list(cfg.get("accounts") or []) or sorted(set(rec_accts) | set(ov["by_account"]))
        for a in accounts:
            shown, rec = ov["by_account"].get(a), rec_accts.get(a)
            if shown is None and rec is None:
                continue
            atol = _tolerance(rec, cfg.get("account_tolerance_usd", 100.0), cfg.get("account_tolerance_pct", 0.001))
            if shown is None or rec is None or abs(shown - rec) > atol:
                findings.append(_f("DT_ACCOUNT_MISMATCH", f"account:{a}",
                                   f"{a}: the card shows {'nothing' if shown is None else f'${shown:,.2f}'}; the "
                                   f"recomputation {'nothing' if rec is None else f'${rec:,.2f}'} (bound ${atol:,.2f})",
                                   account=a, shown=shown, recomputed=rec, tolerance=round(atol, 2)))
        if ov.get("day_pnl") is not None and book.get("day_pnl") is not None:
            dtol = _tolerance(book["day_pnl"], cfg.get("day_pnl_tolerance_usd", 100.0),
                              cfg.get("day_pnl_tolerance_pct", 0.10))
            ddelta = round(ov["day_pnl"] - book["day_pnl"], 2)
            if abs(ddelta) > dtol:
                findings.append(_f("DT_DAY_PNL_MISMATCH", "day_pnl",
                                   f"the card shows day P&L ${ov['day_pnl']:,.2f}; qty x (price - prev_close) says "
                                   f"${book['day_pnl']:,.2f} ({ddelta:+,.2f}, bound ${dtol:,.2f})",
                                   shown=ov["day_pnl"], recomputed=book["day_pnl"], delta=ddelta,
                                   tolerance=round(dtol, 2)))
    carry = {"at": now.isoformat(), "displayed_total": ov.get("total"), "recomputed_total": book.get("total"),
             "alertable": []}
    # ---- frozen: the card did not move while the marks did ------------------------------------------------------
    if measured and ov.get("total") is not None and isinstance(previous, Mapping):
        prev_at = _dt(previous.get("at"))
        prev_shown, prev_rec = _num(previous.get("displayed_total")), _num(previous.get("recomputed_total"))
        gap = _age_min(now, prev_at)
        if prev_at and prev_shown is not None and prev_rec is not None:
            k = int(cfg.get("frozen_k", 2))
            moved = abs(book["total"] - prev_rec) > _tolerance(prev_rec, cfg.get("total_tolerance_usd", 250.0),
                                                               cfg.get("total_tolerance_pct", 0.0005))
            frozen_shown = abs(ov["total"] - prev_shown) < 0.005
            if k <= 2 and gap is not None and gap >= float(cfg.get("frozen_min_gap_min", 5)) and frozen_shown and moved:
                findings.append(_f("DT_FROZEN", "frozen_total",
                                   f"the card shows ${ov['total']:,.2f} at both runs {gap:g} min apart while the "
                                   f"recomputation moved ${prev_rec:,.2f} -> ${book['total']:,.2f}",
                                   shown=ov["total"], prior_shown=prev_shown, prior_recomputed=prev_rec,
                                   recomputed=book["total"], gap_min=gap))
    # ---- stop advice: the rule is the brief's own, never a second copy -----------------------------------------
    newest_stop = None
    for s in stops or ():
        t = _dt(s.get("captured_at"))
        if t and (newest_stop is None or t > newest_stop):
            newest_stop = t
    if sc.get("readable") and reconcile is not None and sc.get("advice_rows"):
        read_block = _stop_read(stops, cfg, now=now)
        rec = reconcile({"stop_advice": sc["advice_rows"]}, read_block, now=now)
        for row, out in zip(sc["advice_rows"], rec.get("rows") or []):
            if out.get("state") == "done" and row.get("state") in (None, "open", "unread"):
                ev = out.get("stop_evidence") or {}
                findings.append(_f("DT_STOP_ADVICE_SATISFIED", f"advice:{row.get('account')}:{row.get('symbol')}",
                                   f"{row.get('account')} {row.get('symbol')}: the card still asks {row.get('answer')} "
                                   f"at {row.get('suggested_stop')}, but the broker holds a WORKING stop at "
                                   f"{ev.get('best_stop')} covering {ev.get('covered_qty')}",
                                   account=row.get("account"), symbol=row.get("symbol"), answer=row.get("answer"),
                                   suggested_stop=row.get("suggested_stop"), best_stop=ev.get("best_stop")))
        sr = sc.get("stop_read")
        if isinstance(sr, Mapping) and sr.get("status") == "read" and sr.get("as_of"):
            shown_as_of = _dt(sr.get("as_of"))
            slack = timedelta(seconds=float(cfg.get("asof_slack_s", 60)))
            checked = _dt(sr.get("checked_at"))
            newer_than_book = shown_as_of and (newest_stop is None or shown_as_of > newest_stop + slack)
            check_time = shown_as_of and checked and abs((shown_as_of - checked).total_seconds()) <= slack.total_seconds()
            if newer_than_book or check_time:
                findings.append(_f("DT_ASOF_MISLABEL", "asof:stops",
                                   f"the card labels its stops {sr.get('as_of_text') or sr.get('as_of')}; the newest "
                                   f"broker stop capture is {newest_stop.isoformat() if newest_stop else 'none'}"
                                   + (" (the check time, not a stop time)" if check_time else ""),
                                   shown_as_of=sr.get("as_of"),
                                   newest_capture=newest_stop.isoformat() if newest_stop else None,
                                   checked_at=sr.get("checked_at")))
    # ---- stop coverage: a warn, the same question held_exit_coverage asks of the snapshot ----------------------
    if book["coverage"]["verdict"] != "NOT_MEASURED":
        for gap in book["coverage"]["uncovered"]:
            findings.append(_f("DT_STOP_UNCOVERED", f"uncovered:{gap['account']}:{gap['symbol']}",
                               f"{gap['account']} {gap['symbol']}: held {gap['held_qty']:g}, no WORKING stop",
                               alert=False, account=gap["account"], symbol=gap["symbol"], held_qty=gap["held_qty"]))
    # ---- the other two families reuse their own monitors' verdicts ----------------------------------------------
    # The header/card VIX split is judged by header_market_freshness_health (LQ-1610), which reads the served header,
    # the card and the one headline together. This check reads that lane's receipt rather than recomputing the split:
    # a second implementation of the same rule would disagree with the first one day, and the receipt already names the
    # reason. Its BROKEN vix contract is "the header or the card serves another source, or they disagree on value or
    # observation time" - exactly the operator-reported split. DEGRADED (stale/undated) stays that lane's finding.
    hh = displayed.get("header_health") if isinstance(displayed.get("header_health"), Mapping) else None
    hh_state = "missing"
    if hh is not None:
        contracts = hh.get("contracts") if isinstance(hh.get("contracts"), Mapping) else {}
        reasons = hh.get("reasons") if isinstance(hh.get("reasons"), Mapping) else {}
        vix_state = str((contracts or {}).get("vix") or "").upper()
        hh_state = vix_state or "unknown"
        if vix_state == "BROKEN":
            findings.append(_f("DT_HEADER_CARD_SPLIT", "header:vix",
                               "header-market-freshness-health grades the header/card VIX contract BROKEN: "
                               f"{reasons.get('vix') or 'no reason recorded'}",
                               contract="vix", verdict=vix_state, reason=reasons.get("vix")))
    if dom:
        allowed = {str(k).lower(): {str(x).lower() for x in v or ()}
                   for k, v in (cfg.get("tier_segment_states") or {}).items()}
        for item in dom.get("drivers") or ():
            if not isinstance(item, Mapping):
                continue
            tier = str(item.get("tier") or "").strip().lower()
            state = str(item.get("segment_state") or item.get("state") or "").strip().lower()
            if not tier or not state or tier not in allowed:
                continue
            if state not in allowed[tier]:
                findings.append(_f("DT_TIER_COLOR_CONTRADICTION", f"tier:{item.get('driver') or tier}",
                                   f"{item.get('driver') or tier}: the badge says '{tier}' while its meter segment "
                                   f"reads '{state}'", driver=item.get("driver"), tier=tier, segment_state=state))
    # ---- the verdict -----------------------------------------------------------------------------------------
    alertable = sorted(f["key"] for f in findings if f.get("alert"))
    alert_codes = sorted({f["code"] for f in findings if f.get("alert")})
    prev_keys = set(previous.get("alertable") or []) if isinstance(previous, Mapping) else set()
    survived = sorted(set(alertable) & prev_keys)
    warns = [f for f in findings if not f.get("alert")]
    render = displayed.get("render") if isinstance(displayed.get("render"), Mapping) else None
    render_state = str((render or {}).get("state") or ("SKIPPED" if not cfg.get("render", {}).get("enabled") else
                                                       "MISSING"))
    if not measured or not displayed_readable:
        verdict = "UNVERIFIABLE"
        why = (book.get("reason") or "nothing displayed was readable")
    elif survived:
        verdict = "BROKEN"
        why = f"{len(survived)} alert finding(s) survived a cadence after a heal"
    elif alertable:
        verdict = "DEGRADED"
        why = f"{len(alertable)} new alert finding(s)"
    elif warns:
        verdict = "DEGRADED"
        why = f"{len(warns)} warn finding(s)"
    elif render_state != "OK":
        verdict = "DEGRADED"
        why = f"data checks passed; the render leg is {render_state}"
    else:
        verdict = "OK"
        why = "the card agrees with the independent recomputation"
    carry["alertable"] = alertable
    return {"findings": findings, "verdict": verdict, "verdict_reason": why,
            "recomputed": book, "displayed": {"overview": ov, "since_close": sc,
                                             "render_state": render_state, "header_health_state": hh_state},
            "survived_after_heal": survived, "carry": carry,
            "heal": plan_display_heal(alert_codes, cfg)}


def _stop_read(stops: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """The stop rows as ``since_close_card.reconcile_stop_advice`` wants them: the same working-status set, the same
    newest-capture clock. A set that drifts from the brief's would grade a cancelled stop as coverage."""
    working = {str(x).strip().lower() for x in cfg.get("working_stop_statuses") or ["working"]}
    per: dict[str, list[dict[str, Any]]] = {}
    newest: Optional[datetime] = None
    n = 0
    for r in stops or ():
        n += 1
        t = _dt(r.get("captured_at"))
        if t and (newest is None or t > newest):
            newest = t
        status = str(r.get("status") or "").strip().lower()
        price, qty = _num(r.get("stop_price")), _num(r.get("qty"))
        if status not in working or price is None or qty is None or qty <= 0:
            continue
        per.setdefault(str(r.get("symbol") or "").upper(), []).append(
            {"account": str(r.get("account") or ""), "order_id": r.get("order_id"), "stop": price, "qty": qty,
             "status": status, "captured_at": t})
    return {"status": "read", "stops": per, "as_of": newest, "rows": n, "error": None}


#: which owning lane a display finding asks to re-run. The heal NEVER writes a displayed value, a store, a stop or a
#: broker: it re-dispatches the lane that produces the shown number and then re-checks (design SELF-HEALING).
DISPLAY_HEAL_LANES = {
    "DT_TOTAL_MISMATCH": "overview-projection",
    "DT_ACCOUNT_MISMATCH": "overview-projection",
    "DT_DAY_PNL_MISMATCH": "day-change-writer",
    "DT_FROZEN": "overview-projection",
    "DT_STOP_ADVICE_SATISFIED": "since-close-snapshot",
    "DT_ASOF_MISLABEL": "since-close-snapshot",
    "DT_HEADER_CARD_SPLIT": "header-warm",
}


def plan_display_heal(alertable_codes: Iterable[str], cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Pure. Which owning lane each alert CODE asks to re-run, and which codes have no automatic remedy.

    Takes the catalog codes themselves (``DT_TOTAL_MISMATCH``), never a finding key: a key is subject-specific
    (``account:schwab_taxable``) and its prefix is not the code, so keying the map on it would silently heal nothing.
    """
    codes = {}
    for code in alertable_codes:
        lane = DISPLAY_HEAL_LANES.get(code)
        if lane:
            codes.setdefault(code, lane)
    return {"lanes": dict(sorted(codes.items())), "dispatch_lanes": sorted(set(codes.values())),
            "unhealable": sorted(c for c in set(alertable_codes) if c not in DISPLAY_HEAL_LANES)}


# ── sources (read-only) ─────────────────────────────────────────────────────────────────────────────────────────


def pg_connect():  # pragma: no cover - exercised on the host only
    import psycopg2

    conn = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD", ""), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _select(conn, sql: str) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


POSITIONS_SQL = ("SELECT account_key, symbol, qty, is_cash, asset_type, broker_market_value, as_of "
                 "FROM positions_current")
LIFECYCLE_SQL = "SELECT account, symbol, broker, lifecycle, coverage, snapshot_at FROM stop_lifecycle"
#: the broker-read lane's stop snapshot (never a broker call: this SELECT reads the table that lane writes)
STOP_LAST_KNOWN_SQL = "SELECT symbol, account, order_id, stop_price, qty, status, captured_at FROM stop_last_known"


def quotes_sql(sources: Iterable[str]) -> str:
    """Newest row per symbol from the named feeds only (never yfinance, design LQ-1646 step 2)."""
    return ("SELECT DISTINCT ON (symbol) symbol, source, price, prev_close, fetched_at FROM market_quotes "
            f"WHERE source = ANY(ARRAY[{', '.join(repr(str(s)) for s in sources)}]) "
            "ORDER BY symbol, fetched_at DESC")


def load_store() -> dict[str, Any]:
    try:
        from scripts.lib import portfolio_positions as pp
    except ImportError:  # pragma: no cover
        from lib import portfolio_positions as pp  # type: ignore[no-redef]
    return pp.load_store()


def run_check(check: str, *, now: datetime, cfg: Mapping[str, Any], sources: Mapping[str, Callable[[], Any]],
              trading_day: Callable[[datetime], bool] = is_trading_day) -> dict[str, Any]:
    """One check against injected sources (tests) or the host's. Returns the report (never raises on a source)."""
    rep: dict[str, Any] = {"schema": SCHEMA, "authority": AUTHORITY, "check": check, "lane_id": CHECKS[check]["lane"],
                           "as_of": now.isoformat()}

    def get(name: str):
        try:
            return sources[name]()
        except Exception as exc:  # noqa: BLE001 — an unreadable source is dependency_unavailable, never clean
            rep["error"] = f"{name}_unreadable: {type(exc).__name__}"
            return None

    if check == "holdings-drift":
        c = cfg["holdings_drift"]
        store = get("holdings")
        rows = get("positions_current") if store is not None else None
        if rep.get("error"):
            return rep
        if not isinstance(store, Mapping) or not store.get("holdings"):
            rep["error"] = "holdings_unreadable: empty store"
            return rep
        pc_as_of = max([t for t in (_ts(r.get("as_of")) for r in rows or []) if t], default=None)
        drift = holdings_drift(store, list(rows or []), c, now=now, pc_as_of=pc_as_of,
                               session=in_session(now, c["session_start_et"], c["session_end_et"],
                                                  trading_day=trading_day))
        # The store's own total is checked on the same read: the pages publish it, so a field that
        # has stopped equalling its rows is a page defect even when no one is looking at the page.
        total = portfolio_total_agreement(store, c.get("portfolio_total") or {})
        rep.update(drift)
        rep["portfolio_total"] = total["portfolio_total"]
        rep["findings"] = list(drift.get("findings") or []) + total["findings"]
    elif check == "options-desk-staleness":
        doc = get("options_desk")
        if rep.get("error"):
            return rep
        from scripts.lib.desk_session import market_session  # NYSE-calendar RTH gate, desk vocabulary

        label = market_session(now) if trading_day(now) else "CLOSED"
        rep.update(options_desk_staleness(doc or {}, cfg["options_desk_staleness"], now=now, session_label=label))
    elif check == "held-exit-coverage":
        c = cfg["held_exit_coverage"]
        rows = get("positions_current")
        snap = get("stop_lifecycle") if rows is not None else None
        if rep.get("error"):
            return rep
        hd = cfg["holdings_drift"]
        rep.update(held_exit_coverage(list(rows or []), list(snap or []), c, now=now,
                                      session=in_session(now, hd["session_start_et"], hd["session_end_et"],
                                                         trading_day=trading_day)))
    else:  # display-truth
        c = cfg["display_truth"]
        rows = get("positions_current")
        stops_rows = get("stop_last_known") if rows is not None else None
        quotes = get("market_quotes") if rows is not None else None
        shown = get("displayed") if rows is not None else None
        if rep.get("error"):
            return rep
        if rows is None:
            rep["error"] = "positions_current_unreadable: no rows"
            return rep
        try:  # the stop-advice rule lives in one place: the brief's module, never a second copy here
            from scripts.lib.since_close_card import reconcile_stop_advice as _reconcile
        except ImportError:  # pragma: no cover - scripts/ on sys.path
            from lib.since_close_card import reconcile_stop_advice as _reconcile  # type: ignore[no-redef] -- one module, two sys.path roots
        prev = get("previous_display")
        rep.update(display_truth(list(rows), list(quotes or []), list(stops_rows or []), shown or {}, c, now=now,
                                 session=in_session(now, c["session_start_et"], c["session_end_et"],
                                                    trading_day=trading_day),
                                 previous=prev if isinstance(prev, Mapping) else None, reconcile=_reconcile))
    alertable = sorted(f["key"] for f in rep.get("findings") or [] if f.get("alert"))
    rep.update(finding_count=len(rep.get("findings") or []), alertable=alertable,
               by_code=_count(f["code"] for f in rep.get("findings") or []), fingerprint=fingerprint(alertable))
    return rep


def _count(codes: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in codes:
        out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items()))


def _read_json(path: Optional[Path]) -> Any:  # pragma: no cover - host only
    if path is None or not Path(path).is_file():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def state_dir() -> Path:  # pragma: no cover - host only
    return Path(os.environ.get("TRADEAI_STATE_DIR") or ROOT / "data" / "portfolios" / "state")


def host_sources(check: str, proposals: Path, *, cfg: Optional[Mapping[str, Any]] = None
                 ) -> dict[str, Callable[[], Any]]:  # pragma: no cover - host only
    holder: dict[str, Any] = {}

    def conn():
        if "c" not in holder:
            holder["c"] = pg_connect()
        return holder["c"]

    sources: dict[str, Callable[[], Any]] = {
        "holdings": load_store,
        "positions_current": lambda: _select(conn(), POSITIONS_SQL),
        "stop_lifecycle": lambda: _select(conn(), LIFECYCLE_SQL),
        "options_desk": lambda: json.loads(proposals.read_text(encoding="utf-8")),
    }
    if check == "display-truth":
        c = (cfg or {}).get("display_truth") or {}
        feeds = list(c.get("quote_sources") or ["finviz"])
        runtime = ROOT / "data" / "runtime"
        since_close = state_dir() / "since_close_latest.json"
        overview = Path(os.environ.get("TRADEAI_OVERVIEW_PROJECTION") or runtime / "overview_projection.json")
        from scripts.lib import lane_last_receipt as R

        lane = CHECKS["display-truth"]["lane"]
        state_path = alert_state_path(lane, os.environ.get("TRADEAI_STATE_ROOT"))

        def _displayed() -> dict[str, Any]:
            # disk first: when a projection file is fresh it is byte-for-byte what its route serves, so reading it
            # cannot drift from the page and costs the server nothing. The live GET is the operator's leg, not this.
            return {"since_close": _read_json(since_close), "overview": _read_json(overview), "dom": None,
                    "header_health": _header_health_receipt(),
                    "render": {"state": "SKIPPED" if not c.get("render", {}).get("enabled") else "MISSING"}}

        def _header_health_receipt() -> Optional[dict[str, Any]]:
            # the header lane's own verdict, read from its LaneRunReceipt summary; never a second VIX comparison here
            doc = _read_json(R.receipt_path("header-market-freshness-health",
                                            os.environ.get("TRADEAI_STATE_ROOT")))
            return doc.get("summary") if isinstance(doc, Mapping) and isinstance(doc.get("summary"), Mapping) else None

        def _previous() -> Optional[dict[str, Any]]:
            doc = _read_json(state_path)
            carry = doc.get("carry") if isinstance(doc, Mapping) else None
            return carry if isinstance(carry, Mapping) else None

        sources.update({
            "stop_last_known": lambda: _select(conn(), STOP_LAST_KNOWN_SQL),
            "market_quotes": lambda: _select(conn(), quotes_sql(feeds)),
            "displayed": _displayed,
            "previous_display": _previous,
        })
    return sources


# ── alerting (host comms intent, never a send) ──────────────────────────────────────────────────────────────────


def alert_state_path(lane: str, state_root: Optional[str]) -> Path:
    from scripts.lib import lane_last_receipt as R

    return R.receipt_path(lane, state_root).with_name(f"{lane.replace('-', '_')}_alert_state.json")


def plan_alert(report: Mapping[str, Any], previous: Iterable[str]) -> dict[str, Any]:
    """Pure: queue when the alertable set gained a key. Returns {queue, gained, keys}."""
    keys = list(report.get("alertable") or [])
    gained = sorted(set(keys) - set(previous))
    return {"queue": bool(gained), "gained": gained, "keys": keys}


def intent_text(report: Mapping[str, Any], gained: list[str]) -> tuple[str, str]:
    check = report["check"]
    n = len(report.get("alertable") or [])
    subject = f"{check}: {n} finding(s) ({len(gained)} new)"
    details = [f["detail"] for f in report.get("findings") or [] if f.get("key") in set(gained)][:6]
    summary = ("; ".join(details) + (" ..." if len(gained) > 6 else "")
               + f". Read-only check; run python3 {SCRIPT} --check {check} for the evidence; nothing was changed.")
    return subject, summary


def emit_alert(report: Mapping[str, Any], *, state_root: Optional[str], ledger_path: Path, execution_id: str,
               queue: Optional[Callable[..., dict]] = None) -> dict[str, Any]:
    lane = report["lane_id"]
    path = alert_state_path(lane, state_root)
    try:
        prev = json.loads(path.read_text(encoding="utf-8")).get("keys") or []
    except (OSError, ValueError):
        prev = []
    plan = plan_alert(report, prev)
    result: dict[str, Any] = {"queued": False, "gained": plan["gained"]}
    if plan["queue"]:
        subject, summary = intent_text(report, plan["gained"])
        from scripts.check_registry_runtime_truth import IntentRefused, queue_host_intent

        try:
            route = CHECKS[report["check"]]
            rec = (queue or queue_host_intent)(producer=PRODUCER, domain=route["domain"], kind=route["kind"],
                                               subject=subject, summary=summary, execution_id=execution_id,
                                               node=str(report.get("fingerprint") or ""), ledger_path=ledger_path)
            result.update(queued=True, intent_id=(rec or {}).get("intent_id"),
                          duplicate=bool((rec or {}).get("duplicate")))
        except IntentRefused as exc:
            result["reason"] = f"intent_{exc.reason}"
            return result  # keep the old state so the next run retries the gained finding
    path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {"keys": plan["keys"], "fingerprint": report.get("fingerprint"),
                             "at": report.get("as_of")}
    if report.get("carry"):  # display-truth carries its two totals forward so a frozen card is visible next run
        state["carry"] = report["carry"]
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return result


def _ledger(state_root: Optional[str]) -> Path:
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    sr = state_root or os.environ.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(sr) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


def render(rep: Mapping[str, Any]) -> str:
    lines = [f"desk truth {rep.get('check')}  {rep.get('as_of')}  ({AUTHORITY})"]
    if rep.get("error"):
        return "\n".join(lines + [f"CANNOT RUN: {rep['error']}"])
    for k in ("holdings_as_of", "holdings_basis", "holdings_age_h", "positions_current_age_h", "generated_at",
              "freshness_basis", "age_min", "market_session", "held", "covered", "uncovered", "coverage_verdict",
              "snapshot_age_h", "paper_stop_rows", "in_session", "verdict", "verdict_reason",
              "survived_after_heal", "heal"):
        if k in rep:
            lines.append(f"  {k}: {rep[k]}")
    lines.append(f"findings: {rep.get('finding_count')}  alertable {len(rep.get('alertable') or [])}  "
                 f"fingerprint {rep.get('fingerprint')}")
    for f in rep.get("findings") or []:
        lines.append(f"  x {f['code']}: {f['detail']}" + ("" if f.get("alert") else "  (not alerted)"))
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", required=True, choices=sorted(CHECKS))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: print, write nothing")
    g.add_argument("--apply", action="store_true", help="write the receipt + alert state; queue one DIGEST intent")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT)")
    ap.add_argument("--proposals", help="options desk snapshot (options-desk-staleness)")
    ap.add_argument("--now", help=argparse.SUPPRESS)
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    now = _ts(a.now) if a.now else datetime.now(timezone.utc)
    if now is None:
        return 2
    cfg = load_config()
    lane = CHECKS[a.check]["lane"]
    rep = run_check(a.check, now=now, cfg=cfg,
                    sources=host_sources(a.check, Path(a.proposals) if a.proposals else proposals_path(), cfg=cfg))
    ok = not rep.get("error")
    from scripts.lib import lane_last_receipt as R

    receipt = R.receipt_path(lane, a.state_root)
    if not a.apply:
        print(json.dumps(rep, indent=1, default=str, sort_keys=True) if a.json else render(rep))
        if not a.json:
            route = CHECKS[a.check]
            would = [str(receipt), str(alert_state_path(lane, a.state_root))]
            if rep.get("alertable"):
                would.append(f"host comms intent {route['domain']}/{route['kind']} (DIGEST) if a finding is new")
            R.dry_run_report(lane, {k: rep.get(k) for k in ("finding_count", "by_code", "fingerprint", "error")},
                             would_write=would, receipt=receipt)
        return 0 if ok else 1
    alert: dict[str, Any] = {"queued": False, "reason": "not_run"}
    if ok:
        run_id = os.environ.get("TRADEAI_RUN_ID") or f"{lane}:{now.strftime('%Y%m%dT%H%M%SZ')}"
        alert = emit_alert(rep, state_root=a.state_root, ledger_path=_ledger(a.state_root), execution_id=run_id)
    output = ({"produced_count": 1, "attempted_count": 1, "skipped_reasons": {}, "empty_reason": None} if ok else
              {"produced_count": 0, "attempted_count": 1, "skipped_reasons": {DEP: 1}, "empty_reason": None})
    if str(alert.get("reason", "")).startswith("intent_"):
        output["skipped_reasons"] = {alert["reason"]: 1}
    summary = {k: rep.get(k) for k in rep if k not in ("findings", "schema", "authority")}
    summary["findings"] = [{"code": f["code"], "key": f["key"], "detail": f["detail"], "alert": f["alert"]}
                           for f in rep.get("findings") or []][:60]
    summary["alert"] = alert
    written = R.write_lane_receipt(lane, ok=ok, exit_code=0 if ok else 1, started_at=now, script=SCRIPT,
                                   summary=summary, error=rep.get("error"), path=receipt, output=output)
    print(json.dumps({"mode": "apply", "check": a.check, "ok": ok, "receipt": str(written) if written else None,
                      "finding_count": rep.get("finding_count"), "by_code": rep.get("by_code"), "alert": alert,
                      "error": rep.get("error")}, default=str))
    return 0 if ok and written is not None else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
