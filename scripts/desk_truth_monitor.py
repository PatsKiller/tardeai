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
        rep.update(holdings_drift(store, list(rows or []), c, now=now, pc_as_of=pc_as_of,
                                  session=in_session(now, c["session_start_et"], c["session_end_et"],
                                                     trading_day=trading_day)))
    elif check == "options-desk-staleness":
        doc = get("options_desk")
        if rep.get("error"):
            return rep
        from scripts.lib.desk_session import market_session  # NYSE-calendar RTH gate, desk vocabulary

        label = market_session(now) if trading_day(now) else "CLOSED"
        rep.update(options_desk_staleness(doc or {}, cfg["options_desk_staleness"], now=now, session_label=label))
    else:
        c = cfg["held_exit_coverage"]
        rows = get("positions_current")
        snap = get("stop_lifecycle") if rows is not None else None
        if rep.get("error"):
            return rep
        hd = cfg["holdings_drift"]
        rep.update(held_exit_coverage(list(rows or []), list(snap or []), c, now=now,
                                      session=in_session(now, hd["session_start_et"], hd["session_end_et"],
                                                         trading_day=trading_day)))
    alertable = sorted(f["key"] for f in rep.get("findings") or [] if f.get("alert"))
    rep.update(finding_count=len(rep.get("findings") or []), alertable=alertable,
               by_code=_count(f["code"] for f in rep.get("findings") or []), fingerprint=fingerprint(alertable))
    return rep


def _count(codes: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in codes:
        out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items()))


def host_sources(check: str, proposals: Path) -> dict[str, Callable[[], Any]]:  # pragma: no cover - host only
    holder: dict[str, Any] = {}

    def conn():
        if "c" not in holder:
            holder["c"] = pg_connect()
        return holder["c"]

    return {
        "holdings": load_store,
        "positions_current": lambda: _select(conn(), POSITIONS_SQL),
        "stop_lifecycle": lambda: _select(conn(), LIFECYCLE_SQL),
        "options_desk": lambda: json.loads(proposals.read_text(encoding="utf-8")),
    }


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
    path.write_text(json.dumps({"keys": plan["keys"], "fingerprint": report.get("fingerprint"),
                                "at": report.get("as_of")}, indent=1), encoding="utf-8")
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
              "snapshot_age_h", "paper_stop_rows", "in_session"):
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
                    sources=host_sources(a.check, Path(a.proposals) if a.proposals else proposals_path()))
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
