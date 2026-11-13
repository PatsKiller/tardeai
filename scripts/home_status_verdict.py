#!/usr/bin/env python3
"""Lane ``home-status-verdict``: compute the Home "Trade-ready" verdict and write it (LQ-20261107-2144).

Scheduled by the n8n dispatcher (config/lane_registry.json row ``home-status-verdict``): every minute 09:00-15:59 ET on
weekdays, every 5 minutes otherwise. Each run reads the required inputs (each query under a 2 s statement_timeout),
applies the approved rule (:func:`scripts.lib.home_trade_ready.compute_verdict`), and with ``--apply`` writes:

* one ``home_snapshots`` row, ``kind='status'``, keyed ``(kind, run_id)`` (system of record), plus the bounded 7-day
  retention delete of its own kind in the same transaction;
* a JSON mirror ``data/runtime/home_status_latest.json`` (fallback copy for when the DB is unreachable);
* the LaneRunReceipt@v2 ``data/runtime/home-status-verdict_last.json`` with ``produced_count=1``.

The default is a DRY RUN: a READ ONLY session, prints what it would write, writes nothing.

Inputs (spec HOME-BACKEND-SPEC-20261111 section 2, LQ-2144); each provider is a plain function so tests stub it:

* ``p0`` / ``p1_blocking`` / ``alerts``: open ``alert_incidents`` (not synthetic, not expired) classed by the LQ-2149
  map ``config/home_status_registry.json`` ``incident_classes`` (D2, operator-approved 2026-11-12 10:12 ET, LQ-2264).
  There is no built-in P-level mapping: the map must pass ``home_diagnostics.validate_incident_registry`` and carry
  ``incident_classes_approved: true``, else p0/p1_blocking/alerts/incident_classes are UNKNOWN. Per incident
  (``home_diagnostics.incident_surface``): D2-a P0 -> blocking (NO), P1 -> non-blocking unless blocks_trading;
  D2-b an unclassified type makes ``incident_classes`` UNKNOWN (named) while the classified ones still count, so an
  open P0 stays a good-read NO (R3); D2-c the blocks_trading column only raises, an attempt to lower a P0 is ignored
  and reported as a data-quality row; D2-d orphaned_stop is P1 non-blocking (registry). LQ-2411.
* R3: ``protection_verdict.confirmed_no_overrides_unknown`` from the same registry, passed to the rule.
* ``gates``: ``validation_gates`` open set (LQ-2141) + the ``validation-gates-sync`` receipt fresh.
* ``portfolio``: ``positions_current.max(as_of)`` judged by ``session_freshness`` with the ``positions_store``
  authority thresholds, plus the last ``positions_sync_runs`` status.
* ``orders``: the ``stop-coverage-incidents`` receipt (LQ-2145) fresh AND zero open ``position_unprotected``.
* ``data``: ``market_quotes`` for ``$VIX`` and every held symbol (never yfinance), ``quote_price`` thresholds;
  a held mutual fund is graded on its daily broker NAV from ``positions_current`` (LQ-20261107-2643), and a
  fund with no NAV is UNKNOWN for that symbol only, never a gate-wide NEEDS BACKEND.
* ``schedulers``: ``lane_health_current`` (LQ-2148), informational.

Read-only advisory surface: MBI_BEHAVIOR = 0. No broker, no order path, no send.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import home_trade_ready as htr  # noqa: E402
from scripts.lib.home_trade_ready import Item, Reading  # noqa: E402

REGISTRY_PATH = REPO_ROOT / "config" / "home_status_registry.json"
STATEMENT_TIMEOUT_MS = 2000
RETENTION_DAYS = 7
GATES_LANE = "validation-gates-sync"
GATES_WRITER_MAX_AGE_S = 900          # spec 2141: */5 writer, db_max 0.25 h
ORDERS_LANE = "stop-coverage-incidents"
# The LQ-2145 lane (stop_coverage_incidents.py) writes its own StopCoverageIncidentsRun@v1 heartbeat (not the
# lane_last_receipt name): ok_at, status, and the list lengths gaps / day_stop_expired / unresolved_unknown.
ORDERS_HEARTBEAT = "stop_coverage_incidents_last.json"
ORDERS_COUNT_KEYS = ("gaps", "day_stop_expired", "unresolved_unknown")
ORDERS_PRODUCER = "stop_coverage_incidents"
ORDERS_MAX_AGE_SESSION_S = 900        # spec 2145: */5 in session (3 cadences)
ORDERS_MAX_AGE_OFF_S = 5400           # */30 off-hours (3 cadences)
SCHEDULERS_MAX_AGE_S = 1800           # spec 2148: db_max lane_health_current.measured_at 0.5 h
INCIDENT_READ_MAX_AGE_S = 600
VIX_SYMBOL = "$VIX"
OPEN_GATE_EXCLUDED = ("PASSED", "CLOSED", "WAIVED", "CANCELLED")
UNPROTECTED_TYPE = "position_unprotected"
SYNC_OK_STATUSES = ("complete",)      # measured 2026-11-11: complete | partial
# Operator decisions 2026-11-11 (Portfolio v002 DECISIONS, binding for Home via LQ-2172): exempt by default are cash,
# money-market funds and sweep vehicles; ETFs, closed-end funds, mutual funds and stocks are NOT exempt; a position
# under $100 is listed, not counted, not hidden. Cash lines never reach the data input (is_cash is filtered in SQL).
# LQ-20261107-2962: a mutual fund prices once a day (NAV after the close), so the shared quote_price limit (0.25 h open)
# would call a good NAV STALE all session. Its limit is 1 trading day: hours with weekends and exchange holidays removed.
FUND_NAV_MAX_TRADING_HOURS = 24.0
DATA_EXEMPT_ASSET_TYPES = ("CASH", "MONEY_MARKET", "MONEY_MARKET_FUND", "SWEEP", "SWEEP_VEHICLE")
DATA_NOT_COUNTED_UNDER_USD = 100.0
# LQ-20261107-2643 (operator P0 2026-11-12 19:08 ET): a mutual fund strikes ONE NAV a day, after the close, so it
# has no intraday quote to read. The broker positions row carries that NAV (market value / qty) and the time it was
# read; a held fund is graded on that row — source named — instead of demanding an intraday quote. A fund with
# neither a broker NAV nor a non-yfinance quote is UNKNOWN for that symbol only and never blanks the gate.
MUTUAL_FUND_ASSET_TYPES = ("MUTUAL_FUND", "MUTUAL FUND", "MUTUALFUND", "FUND")
BROKER_NAV_SOURCE = "positions_current"

Query = Callable[[str, Optional[tuple]], list[dict[str, Any]]]


class Timeout(Exception):
    """A provider query exceeded the statement timeout."""


# ── shared readers ──────────────────────────────────────────────────────────────────────────────


def load_registry(path: Path = REGISTRY_PATH) -> Optional[dict[str, Any]]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def class_map_status(registry: Optional[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """(incident_classes, None) when usable, else (None, reason). No default mapping exists (D2).

    One approval reader for every consumer (READY-2397: the boolean ``incident_classes_approved`` written by LQ-2264,
    checked through the same validator the registry tests use), so the lane and the registry cannot disagree again.
    """
    from scripts.lib.home_diagnostics import RegistryError, validate_incident_registry
    if registry is None:
        return None, "incident class map missing: config/home_status_registry.json not present (LQ-2149)"
    classes = registry.get("incident_classes")
    if not isinstance(classes, dict) or not classes:
        return None, "incident class map empty (LQ-2149)"
    try:
        validate_incident_registry(registry)
    except RegistryError as exc:
        return None, f"incident class map invalid: {exc}"
    if registry.get("incident_classes_approved") is not True:
        return None, "incident class map not operator-approved (D2): verdict cannot go live"
    return classes, None


def read_receipt(lane_id: str, state_root: Optional[Path]) -> Optional[dict[str, Any]]:
    from scripts.lib.lane_last_receipt import receipt_path
    try:
        doc = json.loads(Path(receipt_path(lane_id, state_root)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _truthy(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "t", "1", "yes")


def _guard(name: str, fn: Callable[[], Reading], *, owner: Optional[str] = None, source_id: Optional[str] = None,
           lane_id: Optional[str] = None) -> Reading:
    """Run one provider; an exception is never OK: a timeout is TIMED_OUT, anything else UNKNOWN (type name only)."""
    try:
        return fn()
    except Timeout:
        r = htr.unknown(name, f"query exceeded {STATEMENT_TIMEOUT_MS} ms", owner=owner, source_id=source_id,
                        lane_id=lane_id)
        r.state = htr.TIMED_OUT
        return r
    except Exception as exc:  # noqa: BLE001 -- the reading records the failure; the verdict stays honest
        return htr.unknown(name, f"read failed: {type(exc).__name__}", owner=owner, source_id=source_id,
                           lane_id=lane_id)


# ── providers ───────────────────────────────────────────────────────────────────────────────────

INCIDENTS_SQL = (
    "SELECT a.incident_id, a.alert_type, a.severity, a.symbol, a.source_producer, a.first_seen_at, a.last_seen_at, "
    "to_jsonb(a)->>'blocks_trading' AS blocks_trading "
    "FROM alert_incidents a WHERE a.status = 'open' AND COALESCE(a.synthetic, false) = false "
    "AND (a.expires_at IS NULL OR a.expires_at > now())"
)


def read_incidents(q: Query) -> list[dict[str, Any]]:
    return q(INCIDENTS_SQL, None)


def incident_readings(rows: Optional[list[dict[str, Any]]], registry: Optional[dict[str, Any]], now: datetime,
                      read_error: Optional[Reading] = None) -> list[Reading]:
    """p0, p1_blocking and alerts from one read of open incidents and the class map."""
    if read_error is not None or rows is None:
        base = read_error or htr.unknown(htr.P0, "incidents not read")
        out = []
        for name in (htr.P0, htr.P1_BLOCKING, htr.ALERTS, htr.INCIDENT_CLASSES):
            out.append(Reading(name=name, state=base.state, reason=base.reason, source_id="alert_incidents",
                               owner="ops"))
        return out
    classes, why = class_map_status(registry)
    src = "alert_incidents"
    names = (htr.P0, htr.P1_BLOCKING, htr.ALERTS, htr.INCIDENT_CLASSES)
    if classes is None:
        if registry is None:   # the class-map file does not exist yet: no source (I2)
            return [htr.no_source(n, why, source_id=src, lane_id="home-status-registry", owner="operator")
                    for n in names]
        return [Reading(name=n, state=htr.UNKNOWN, reason=why, source_id=src, owner="operator",
                        cause="incident class map not approved") for n in names]
    from scripts.lib.home_diagnostics import incident_surface
    p0, p1_block, p1_info, unmapped, dq = [], [], [], {}, []
    for row in rows:
        atype = str(row.get("alert_type") or "")
        explicit = _truthy(row.get("blocks_trading"))
        surface = incident_surface(registry, atype, explicit)
        if not surface["classified"]:   # D2-b: never ignored, never OK
            unmapped[atype] = unmapped.get(atype, 0) + 1
            continue
        cls = classes[atype]
        prio = surface["priority"]
        blocks = prio == "P0" or bool(surface["blocks_trading"])   # D2-a/c: a P0 always blocks
        if explicit is False and cls.get("blocks_trading_default"):
            dq.append({"cause": f"override ignored: blocks_trading=false on {atype} ({prio}) cannot lower a "
                                "blocking class (D2-c)", "incident_id": str(row.get("incident_id")),
                       "priority": prio, "source_id": src, "owner": cls.get("owner")})
        first = htr.to_utc(row.get("first_seen_at"))
        last = htr.to_utc(row.get("last_seen_at"))
        ttl_h = cls.get("ttl_h")
        stale_cond = bool(ttl_h and last and (now - last).total_seconds() > float(ttl_h) * 3600)
        item = Item(id=str(row.get("incident_id")), title=atype, blocks_trading=blocks,
                    category=cls.get("category") or atype, priority=prio, source_id=src,
                    owner=cls.get("owner"), cause=atype.replace("_", " "), first_seen_at=htr.iso(first),
                    stale_condition=stale_cond)
        if prio == "P0":
            p0.append(item)
        elif blocks:          # D2-c: a P1 or INFO raised by its blocks_trading column blocks as a P1
            p1_block.append(item)
        elif prio == "P1":    # D2-a/d: WARN, Trade Ready unchanged
            p1_info.append(item)
        # INFO without an override: never on the verdict (LOG ONLY)
    read_at = htr.iso(now)
    common = dict(as_of=read_at, threshold_s=INCIDENT_READ_MAX_AGE_S, source_id=src)
    p0_r = Reading(name=htr.P0, state=htr.WARN if p0 else htr.OK, value=len(p0), items=p0,
                   data_quality=[d for d in dq if d["priority"] == "P0"], **common)
    # non-blocking P1s travel with p1_blocking so the rule can list them as non_blocking
    p1_r = Reading(name=htr.P1_BLOCKING, state=htr.WARN if p1_block else htr.OK, value=len(p1_block),
                   items=p1_block + p1_info, data_quality=[d for d in dq if d["priority"] != "P0"], **common)
    if unmapped:
        why = "open incidents of unclassified types: " + ", ".join(f"{k}={v}" for k, v in sorted(unmapped.items()))
        cls_r = Reading(name=htr.INCIDENT_CLASSES, state=htr.UNKNOWN, value=sum(unmapped.values()), reason=why,
                        owner="operator", cause="unclassified incident: classify me", source_id=src)
    else:
        cls_r = Reading(name=htr.INCIDENT_CLASSES, state=htr.OK, value=0, owner="operator", **common)
    n_warn = len(p1_info) + sum(unmapped.values())
    alerts_r = Reading(name=htr.ALERTS, state=htr.WARN if n_warn else htr.OK, value=n_warn,
                       cause=(f"{len(p1_info)} non-blocking P1, {sum(unmapped.values())} unclassified"
                              if n_warn else None), **common)
    return [p0_r, p1_r, alerts_r, cls_r]


def read_gates(q: Query, now: datetime, state_root: Optional[Path]) -> Reading:
    name, src = htr.GATES, "validation_gates"
    reg = q("SELECT to_regclass('public.validation_gates') IS NOT NULL AS present", None)
    if not reg or not reg[0].get("present"):
        return htr.no_source(name, "validation_gates table not present (LQ-2141 not applied)", source_id=src,
                             lane_id=GATES_LANE, owner="ops")
    receipt = read_receipt(GATES_LANE, state_root)
    ok_at = htr.to_utc((receipt or {}).get("ok_at"))
    if ok_at is None:
        return htr.unknown(name, f"no successful {GATES_LANE} run on record: an empty gate list is not evidence",
                           source_id=src, lane_id=GATES_LANE, owner="ops")
    rows = q("SELECT to_jsonb(g) AS g FROM validation_gates g", None)
    items = []
    for r in rows:
        g = r.get("g") if isinstance(r.get("g"), dict) else json.loads(r.get("g") or "{}")
        status = str(g.get("status") or "").upper()
        if g.get("closed_at") or status in OPEN_GATE_EXCLUDED:
            continue
        items.append(Item(id=str(g.get("gate_id") or g.get("id")), title=str(g.get("title") or ""),
                          blocks_trading=bool(_truthy(g.get("blocks_trading"))), category=None, source_id=src,
                          owner=g.get("owner"), cause=g.get("title"), first_seen_at=htr.iso(htr.to_utc(g.get("opened_at")))))
    blocking = [i for i in items if i.blocks_trading]
    return Reading(name=name, state=htr.WARN if blocking else htr.OK, value=len(blocking), as_of=htr.iso(ok_at),
                   threshold_s=GATES_WRITER_MAX_AGE_S, source_id=src, lane_id=GATES_LANE, owner="ops", items=items)


def _session_reading(name: str, as_of: Any, now: datetime, domain: str, *, source_id: str, lane_id: Optional[str],
                     owner: str, causes: dict[str, str]) -> Reading:
    from scripts.lib.session_freshness import authority_thresholds, evaluate
    th = authority_thresholds(domain)
    if not th:
        return htr.unknown(name, f"no authority thresholds for domain {domain}", source_id=source_id,
                           lane_id=lane_id, owner=owner)
    ev = evaluate(as_of, now, max_age_h=float(th["open_h"]), closed_max_age_h=float(th["closed_h"]))
    state = {"fresh": htr.OK, "latest_close": htr.OK, "stale": htr.STALE}.get(ev.get("state"), htr.UNKNOWN)
    limit_h = th["open_h"] if ev.get("market_open") else th["closed_h"]
    return Reading(name=name, state=state, as_of=htr.iso(htr.to_utc(as_of)), threshold_s=float(limit_h) * 3600,
                   threshold_basis="since_last_close" if ev.get("state") == "latest_close" else "fixed",
                   source_id=source_id, lane_id=lane_id, owner=owner,
                   cause=causes.get(state), reason=ev.get("reason"))


def read_portfolio(q: Query, now: datetime) -> Reading:
    rows = q("SELECT max(as_of) AS as_of, count(*) AS n FROM positions_current", None)
    as_of = rows[0].get("as_of") if rows else None
    r = _session_reading(htr.PORTFOLIO, as_of, now, "positions_store", source_id="positions_current",
                         lane_id="positions-sync", owner="portfolio",
                         causes={htr.STALE: "positions sync behind", htr.UNKNOWN: "positions store unreadable"})
    r.value = int(rows[0]["n"]) if rows and rows[0].get("n") is not None else None
    if r.state == htr.OK:
        last = q("SELECT status FROM positions_sync_runs WHERE finished_at IS NOT NULL "
                 "ORDER BY finished_at DESC LIMIT 1", None)
        status = str((last[0].get("status") if last else "") or "").lower()
        if not last:
            r.state, r.cause, r.reason = htr.UNKNOWN, "no finished positions sync on record", "positions_sync_runs empty"
        elif status not in SYNC_OK_STATUSES:
            r.state, r.cause, r.reason = htr.WARN, "last positions sync not OK", f"last positions_sync_runs status={status}"
    return r


def _count(value: Any) -> Optional[int]:
    """A non-negative int count, or None (missing or unreadable is never 0)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def read_orders(q: Query, now: datetime, state_root: Optional[Path], incident_rows: Optional[list[dict[str, Any]]]) -> Reading:
    """The Orders row under operator decision D1 (2026-11-11 23:19 ET).

    OK = protection exists and is active; WARN = protection existed but is no longer active (an expired DAY stop as
    the only protection after the close; never OK); GAP = confirmed unprotected (the latest coverage scan found a
    gap, or a structured-producer position_unprotected incident is open); UNKNOWN = cannot be determined (no
    heartbeat -> NEEDS BACKEND; a failed scan, a missing or unreadable count, an open incident the scan could neither
    confirm nor clear, or unreadable incidents).
    """
    from scripts.lib.lane_last_receipt import runtime_dir
    name, src, kw = htr.ORDERS, "stop_last_known", {"lane_id": ORDERS_LANE, "owner": "risk"}
    path = Path(runtime_dir(state_root)) / ORDERS_HEARTBEAT
    if not path.exists():
        return htr.no_source(name, f"no {ORDERS_LANE} heartbeat ({ORDERS_HEARTBEAT}; LQ-2145 not live)",
                             source_id=src, **kw)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return htr.unknown(name, f"{ORDERS_HEARTBEAT} unreadable: {type(exc).__name__}", source_id=src, **kw)
    if not isinstance(doc, dict):
        return htr.unknown(name, f"{ORDERS_HEARTBEAT} is not an object", source_id=src, **kw)
    ok_at = htr.to_utc(doc.get("ok_at"))
    if ok_at is None:
        return htr.unknown(name, f"no successful {ORDERS_LANE} scan on record", source_id=src, **kw)
    if doc.get("status") != "ok":
        return htr.unknown(name, f"last {ORDERS_LANE} scan failed ({doc.get('status')!r})", source_id=src, **kw)
    counts = {k: _count(doc.get(k)) for k in ORDERS_COUNT_KEYS}
    bad = [k for k, v in counts.items() if v is None]
    if bad:
        return htr.unknown(name, f"heartbeat count(s) missing or unreadable: {', '.join(bad)}", source_id=src, **kw)
    if incident_rows is None:
        return htr.unknown(name, "open position_unprotected incidents not readable", source_id="alert_incidents", **kw)
    open_gaps = [r for r in incident_rows
                 if r.get("alert_type") == UNPROTECTED_TYPE and r.get("source_producer") == ORDERS_PRODUCER]
    limit = ORDERS_MAX_AGE_SESSION_S if htr.in_session_window(now) else ORDERS_MAX_AGE_OFF_S
    # LQ-2964: held positions of a type that cannot carry a stop (mutual funds) are not gaps, and never hidden
    np_rows = [r for r in (doc.get("not_stop_protectable") or []) if isinstance(r, dict) and r.get("symbol")]
    dq = [{"code": "not_stop_protectable", "symbol": str(r["symbol"]), "asset_type": r.get("asset_type"),
           "label": str(r.get("label") or "not stop-protectable")} for r in np_rows]
    base = dict(value=counts, as_of=htr.iso(ok_at), threshold_s=limit, source_id=src, data_quality=dq, **kw)
    if counts["gaps"] or open_gaps:
        n = max(counts["gaps"], len(open_gaps))
        return Reading(name=name, state=htr.GAP, cause=f"{n} position(s) confirmed unprotected", **base)
    if counts["unresolved_unknown"]:
        return Reading(name=name, state=htr.UNKNOWN, reason=f"{counts['unresolved_unknown']} open protection "
                       "incident(s) the scan could neither confirm nor clear", **base)
    if counts["day_stop_expired"]:
        return Reading(name=name, state=htr.WARN, cause=f"{counts['day_stop_expired']} position(s) protected only "
                       "by an expired DAY stop (D1: protection no longer active)", **base)
    return Reading(name=name, state=htr.OK, **base)


DATA_SQL = (
    "WITH held AS (SELECT symbol, upper(COALESCE(asset_type, '')) AS asset_type, "
    "CASE WHEN count(broker_market_value) = count(*) THEN sum(broker_market_value) END AS market_value, "
    "max(CASE WHEN broker_market_value IS NOT NULL THEN as_of END) AS broker_as_of, "
    "max(CASE WHEN broker_market_value IS NOT NULL THEN source END) AS broker_source "
    "FROM positions_current WHERE NOT COALESCE(is_cash, false) AND qty > 0 GROUP BY 1, 2), "
    "want AS (SELECT symbol, asset_type, market_value, broker_as_of, broker_source FROM held "
    "UNION ALL SELECT %s, 'INDEX', NULL, NULL::timestamp with time zone, NULL::text) "
    "SELECT w.symbol, w.asset_type, w.market_value, w.broker_as_of, w.broker_source, max(m.fetched_at) AS as_of "
    "FROM want w LEFT JOIN market_quotes m ON m.symbol = w.symbol AND m.source <> 'yfinance' "
    "GROUP BY w.symbol, w.asset_type, w.market_value, w.broker_as_of, w.broker_source"
)


def data_exempt(row: dict[str, Any]) -> bool:
    return str(row.get("asset_type") or "").upper() in DATA_EXEMPT_ASSET_TYPES


def data_is_mutual_fund(row: dict[str, Any]) -> bool:
    return str(row.get("asset_type") or "").upper() in MUTUAL_FUND_ASSET_TYPES


def _data_price(row: dict[str, Any]) -> tuple[Any, Optional[str]]:
    """(as_of, source) that grades one counted symbol: a fund's broker NAV first, then a non-yfinance quote."""
    if data_is_mutual_fund(row) and row.get("broker_as_of") is not None:
        broker = str(row.get("broker_source") or "").strip()
        return row.get("broker_as_of"), f"{BROKER_NAV_SOURCE}:{broker}" if broker else BROKER_NAV_SOURCE
    if row.get("as_of") is not None:
        return row.get("as_of"), "market_quotes"
    return None, None


def data_not_counted(row: dict[str, Any]) -> bool:
    """Under $100: listed, not counted. A missing value cannot prove it is small, so it stays counted."""
    if row.get("symbol") == VIX_SYMBOL or row.get("market_value") is None:
        return False
    try:
        return abs(float(row["market_value"])) < DATA_NOT_COUNTED_UNDER_USD
    except (TypeError, ValueError):
        return False


_DATA_STATE_RANK = {htr.OK: 0, htr.STALE: 1, htr.UNKNOWN: 2}


def _quote_reading(name: str, as_of: Any, source: str, now: datetime, *, source_id: str, lane_id: str,
                   owner: str) -> Reading:
    """Grade ONE counted reading under the ``quote_price`` authority.

    A fund's NAV is struck once a day, after the close, so it is graded against the closed threshold even while
    the market is open: the last trading day's NAV is the freshest value that can exist for it (LQ-2643). A quote
    keeps the session-aware rule (wall clock while open, latest close while shut).
    """
    from scripts.lib.session_freshness import authority_thresholds, evaluate
    th = authority_thresholds("quote_price")
    if not th:
        return htr.unknown(name, "no authority thresholds for domain quote_price", source_id=source_id,
                           lane_id=lane_id, owner=owner)
    closed_h = float(th.get("closed_h", th["open_h"]))
    nav = source.startswith(BROKER_NAV_SOURCE)
    ev = evaluate(as_of, now, max_age_h=closed_h if nav else float(th["open_h"]), closed_max_age_h=closed_h)
    limit_h = closed_h if nav or not ev.get("market_open") else float(th["open_h"])
    state = {"fresh": htr.OK, "latest_close": htr.OK, "stale": htr.STALE}.get(ev.get("state"), htr.UNKNOWN)
    return Reading(name=name, state=state, as_of=htr.iso(htr.to_utc(as_of)), threshold_s=limit_h * 3600,
                   threshold_basis="since_last_close" if ev.get("state") == "latest_close" else "fixed",
                   source_id=source_id, lane_id=lane_id, owner=owner,
                   cause={htr.STALE: "mutual fund NAV behind" if nav else "quotes behind",
                          htr.UNKNOWN: "mutual fund NAV unreadable" if nav else "quote store unreadable"}.get(state),
                   reason=ev.get("reason"))


def read_data(q: Query, now: datetime) -> Reading:
    all_rows = q(DATA_SQL, (VIX_SYMBOL,))
    exempt = sorted(str(r.get("symbol")) for r in all_rows if data_exempt(r))
    small = sorted(str(r.get("symbol")) for r in all_rows if not data_exempt(r) and data_not_counted(r))
    rows = [r for r in all_rows if not data_exempt(r) and not data_not_counted(r)]
    if not any(r.get("symbol") == VIX_SYMBOL for r in rows):
        return htr.unknown(htr.DATA, "no quote rows read", source_id="market_quotes", lane_id="market-quotes",
                           owner="data")
    priced: list[tuple[dict[str, Any], Any, str]] = []
    missing_quotes: list[str] = []
    missing_nav: list[str] = []
    for row in rows:
        as_of, src = _data_price(row)
        if as_of is not None:
            priced.append((row, as_of, str(src)))
        elif data_is_mutual_fund(row):
            missing_nav.append(str(row.get("symbol")))
        else:
            missing_quotes.append(str(row.get("symbol")))
    missing_quotes.sort()
    missing_nav.sort()
    sources = {src for _row, _as_of, src in priced}
    fund_nav = {str(row.get("symbol")): src for row, _as_of, src in priced
                if src.startswith(BROKER_NAV_SOURCE)}
    source_id = "+".join(sorted(sources)) if sources else "market_quotes"
    kw = {"source_id": source_id, "lane_id": "market-quotes", "owner": "data"}
    missing = sorted(missing_quotes + missing_nav)
    if missing:
        # I2: missing data is never healthy. A fund's missing NAV is a per-symbol unknown, not a missing backend:
        # the broker positions source was read and simply carried no value for it.
        if missing_quotes:
            r = htr.no_source(htr.DATA, f"no quote source for {len(missing)} counted symbol(s): "
                                        f"{', '.join(missing)}", **kw)
        else:
            r = htr.unknown(htr.DATA, f"no daily NAV for {len(missing_nav)} counted mutual fund(s): "
                                      f"{', '.join(missing_nav)}", **kw)
        r.value = {"symbols": len(rows), "missing": missing, "missing_quotes": missing_quotes,
                   "missing_nav": missing_nav, "listed_not_counted": small, "exempt": exempt}
        if priced:
            oldest_row, oldest_at, _ = min(priced, key=lambda p: htr.to_utc(p[1]) or now)
            r.value["oldest_symbol"] = oldest_row.get("symbol")
            r.as_of = htr.iso(htr.to_utc(oldest_at))
        if fund_nav:
            r.value["fund_nav"] = fund_nav
        return r
    # One row per counted symbol is graded on its own reading, so a fund's daily NAV cannot mask a stale quote
    # and a stale quote cannot make a fresh NAV look old. The gate takes the worst, oldest on a tie.
    # LQ-20261107-2962: a fund priced from market_quotes (the Schwab quote lane's daily NAV) is graded as a NAV,
    # fresh for FUND_NAV_MAX_TRADING_HOURS trading hours; a broker NAV keeps the LQ-2643 rule in _quote_reading.
    graded = [(str(row.get("symbol")),
               _fund_quote_reading(htr.DATA, row, as_of, now, source_id=source_id, lane_id="market-quotes",
                                   owner="data")
               if data_is_mutual_fund(row) and not src.startswith(BROKER_NAV_SOURCE) else
               _quote_reading(htr.DATA, as_of, src, now, source_id=source_id, lane_id="market-quotes", owner="data"))
              for row, as_of, src in priced]
    graded_on, r = min(graded, key=lambda g: (-_DATA_STATE_RANK.get(g[1].state, 2), g[1].as_of or ""))
    # oldest_symbol names the symbol this gate's state is graded on: the worst reading, the oldest on a tie.
    r.value = {"symbols": len(rows), "listed_not_counted": small, "exempt": exempt, "oldest_symbol": graded_on}
    if fund_nav:
        r.value["fund_nav"] = fund_nav
    funds = sorted(str(row.get("symbol")) for row, _as_of, _src in priced if data_is_mutual_fund(row))
    if funds:
        r.value["funds"] = funds
    return r


def _fund_quote_reading(name: str, row: dict[str, Any], as_of: Any, now: datetime, *, source_id: str, lane_id: str,
                        owner: str) -> Reading:
    """Grade a mutual fund's market_quotes NAV (LQ-20261107-2962): OK within FUND_NAV_MAX_TRADING_HOURS trading hours
    (weekends and exchange holidays do not age it), STALE beyond, with the fund named. Unreadable age is UNKNOWN."""
    from scripts.lib.session_freshness import trading_age_hours

    sym = str(row.get("symbol"))
    age = trading_age_hours(as_of, now)
    kw = dict(source_id=source_id, lane_id=lane_id, owner=owner)
    if age is None:
        return htr.unknown(name, f"mutual fund NAV time unreadable: {sym}", **kw)
    stale = age > FUND_NAV_MAX_TRADING_HOURS
    # An OK NAV is the last session's close value; "since_last_close" stops home_trade_ready.field_of re-judging it on
    # wall-clock age (a Friday NAV read on Monday is ~62 wall hours but ~1 trading hour old).
    return Reading(name=name, state=htr.STALE if stale else htr.OK, as_of=htr.iso(htr.to_utc(as_of)),
                   threshold_s=FUND_NAV_MAX_TRADING_HOURS * 3600,
                   threshold_basis="fixed" if stale else "since_last_close",
                   cause=f"fund NAV older than 1 trading day: {sym}" if stale else None, **kw)


def read_schedulers(q: Query, now: datetime) -> Reading:
    """Home Schedulers row from ``lane_health_current`` (LQ-2148). Only the rows of the NEWEST run are read (a lane
    that left ACTIVE keeps its last row and must not count), and the status is the lane's own rollup rule
    (``lane_health.rollup``): a late/stale/failing lane is WARN, a lane that could not be measured (cron/systemd, or an
    unreadable ledger) leaves the row UNKNOWN, never OK. A present-but-empty table is UNKNOWN: no row is not "0 late"."""
    name = htr.SCHEDULERS
    kw = dict(source_id="lane_health_current", lane_id="lane-health-snapshot", owner="ops")
    reg = q("SELECT to_regclass('public.lane_health_current') IS NOT NULL AS present", None)
    if not reg or not reg[0].get("present"):
        return htr.no_source(name, "lane_health_current not present (LQ-2148)", **kw)
    from scripts.lib import lane_health as lh
    rows = q(lh.READ_CURRENT_SQL, None)
    if not rows:
        return htr.unknown(name, "lane_health_current has no row: the lane-health-snapshot lane has not written",
                           **kw)
    as_of = max((t for t in (htr.to_utc(r.get("measured_at")) for r in rows) if t is not None), default=None)
    if as_of is None:
        return htr.unknown(name, "lane_health_current rows carry no measured_at", **kw)
    roll = lh.rollup(list(rows), registry_ok=True, ledger={"readable": True}, policy=lh.load_config())
    counts = roll.get("counts") or {}
    bad = sum(int(counts.get(k) or 0) for k in ("late", "stale", "failing"))
    state = {"OK": htr.OK, "WARN": htr.WARN}.get(roll.get("status"), htr.UNKNOWN)
    return Reading(name=name, state=state, value=bad, as_of=htr.iso(as_of), threshold_s=SCHEDULERS_MAX_AGE_S,
                   cause=roll.get("cause") if state != htr.OK else None, **kw)


def gather(q: Query, now: datetime, *, state_root: Optional[Path], registry: Optional[dict[str, Any]]) -> list[Reading]:
    readings: list[Reading] = []
    incident_rows: Optional[list[dict[str, Any]]] = None
    inc_err: Optional[Reading] = None
    try:
        incident_rows = read_incidents(q)
    except Timeout:
        inc_err = Reading(name=htr.P0, state=htr.TIMED_OUT, reason=f"query exceeded {STATEMENT_TIMEOUT_MS} ms")
    except Exception as exc:  # noqa: BLE001 -- any failure is recorded as an UNKNOWN reading/failed receipt, never swallowed
        inc_err = htr.unknown(htr.P0, f"read failed: {type(exc).__name__}")
    readings.extend(incident_readings(incident_rows, registry, now, inc_err))
    readings.append(_guard(htr.GATES, lambda: read_gates(q, now, state_root), source_id="validation_gates", owner="ops"))
    readings.append(_guard(htr.PORTFOLIO, lambda: read_portfolio(q, now), source_id="positions_current",
                           owner="portfolio"))
    readings.append(_guard(htr.ORDERS, lambda: read_orders(q, now, state_root, incident_rows),
                           source_id="stop_last_known", owner="risk"))
    readings.append(_guard(htr.DATA, lambda: read_data(q, now), source_id="market_quotes", owner="data"))
    readings.append(_guard(htr.SCHEDULERS, lambda: read_schedulers(q, now), source_id="lane_health_current",
                           owner="ops"))
    return readings


# ── DB plumbing ─────────────────────────────────────────────────────────────────────────────────


def pg_connect(readonly: bool):
    import psycopg2
    conn = psycopg2.connect(host=os.environ.get("DB_HOST", "/var/run/postgresql"), port=os.environ.get("DB_PORT", "5432"),
                            dbname=os.environ.get("DB_NAME", "trade_ai"), user=os.environ.get("DB_USER") or None,
                            password=os.environ.get("DB_PASSWORD") or None, connect_timeout=10)
    conn.set_session(readonly=readonly, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
    return conn


def make_query(conn) -> Query:
    import psycopg2
    import psycopg2.extras

    def q(sql: str, params: Optional[tuple] = None) -> list[dict[str, Any]]:
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.errors.QueryCanceled as exc:
            raise Timeout() from exc
    return q


UPSERT_SQL = (
    "INSERT INTO home_snapshots (kind, schema, rule_version, computed_at, run_id, inputs, payload, payload_bytes) "
    "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) "
    "ON CONFLICT (kind, run_id) DO UPDATE SET schema = EXCLUDED.schema, rule_version = EXCLUDED.rule_version, "
    "computed_at = EXCLUDED.computed_at, inputs = EXCLUDED.inputs, payload = EXCLUDED.payload, "
    "payload_bytes = EXCLUDED.payload_bytes"
)
RETENTION_SQL = "DELETE FROM home_snapshots WHERE kind = %s AND computed_at < now() - %s::interval"


def write_snapshot(conn, payload: dict[str, Any]) -> int:
    """Upsert the row and apply retention in ONE transaction. Returns the retention delete count."""
    body = json.dumps(payload, default=str, sort_keys=True)
    inputs = json.dumps(payload.get("inputs") or {}, default=str, sort_keys=True)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(UPSERT_SQL, (htr.SNAPSHOT_KIND, htr.SCHEMA, htr.RULE_VERSION, payload["computed_at"],
                                     payload["run_id"], inputs, body, len(body.encode("utf-8"))))
            cur.execute(RETENTION_SQL, (htr.SNAPSHOT_KIND, f"{RETENTION_DAYS} days"))
            deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


def write_mirror(payload: dict[str, Any], state_root: Optional[Path]) -> Path:
    from scripts.lib.atomic_json_store import atomic_write_json
    from scripts.lib.lane_last_receipt import runtime_dir
    target = Path(runtime_dir(state_root)) / Path(htr.MIRROR_REL).name
    atomic_write_json(target, payload)
    return target


def run_id_for(now: datetime) -> str:
    rid = os.environ.get("TRADEAI_RUN_ID")
    if rid:
        return rid
    return "slot:" + now.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%MZ")


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_status": payload["verdict"],
        "rule_version": payload["rule_version"],
        "blockers": len(payload["blockers"]),
        "blocker_categories": [b["category"] for b in payload["blockers"]],
        "unknown_inputs": [u["input"] for u in payload["unknown_inputs"]],
        "needs_backend": list(payload.get("needs_backend") or []),
        "non_blocking": len(payload["non_blocking"]),
        "input_states": {k: v["state"] for k, v in payload["inputs"].items()},
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="read only, print, write nothing (default)")
    mode.add_argument("--apply", action="store_true", help="write the snapshot row, mirror and receipt")
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc)
    state_root = Path(os.environ["TRADEAI_STATE_ROOT"]) if os.environ.get("TRADEAI_STATE_ROOT") else None
    from scripts.lib.lane_last_receipt import dry_run_report, enforce_readonly, write_lane_receipt

    try:
        conn = pg_connect(readonly=not args.apply)
        if not args.apply:
            enforce_readonly(conn)
    except Exception as exc:  # noqa: BLE001 -- any failure is recorded as an UNKNOWN reading/failed receipt, never swallowed
        if args.apply:
            write_lane_receipt(htr.LANE_ID, ok=False, exit_code=2, started_at=started, script=Path(__file__).name,
                               error=type(exc).__name__, produced_count=0, empty_reason="db unreachable")
        print(f"home-status-verdict: db connect failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    try:
        now = datetime.now(timezone.utc)
        registry = load_registry()
        readings = gather(make_query(conn), now, state_root=state_root, registry=registry)
        payload = htr.compute_verdict(readings, now, run_id=run_id_for(now),
                                      policy=(registry or {}).get("protection_verdict"))
        summary = summarize(payload)
        if not args.apply:
            dry_run_report(htr.LANE_ID, summary, would_write=[f"{htr.TABLE} kind={htr.SNAPSHOT_KIND} run_id={payload['run_id']}",
                                                               htr.MIRROR_REL])
            return 0
        try:
            deleted = write_snapshot(conn, payload)
        except Exception as exc:  # noqa: BLE001 -- e.g. home_snapshots not migrated yet: an honest failed receipt
            write_lane_receipt(htr.LANE_ID, ok=False, exit_code=1, started_at=started, script=Path(__file__).name,
                               summary=summary, error=type(exc).__name__, produced_count=0,
                               empty_reason=f"snapshot write failed: {type(exc).__name__}")
            print(f"home-status-verdict: snapshot write failed: {type(exc).__name__}", file=sys.stderr)
            return 1
        write_mirror(payload, state_root)
        write_lane_receipt(htr.LANE_ID, ok=True, exit_code=0, started_at=started, script=Path(__file__).name,
                           summary={**summary, "retention_deleted": deleted}, produced_count=1, attempted_count=1,
                           output_evidence=[{"table": htr.TABLE, "kind": htr.SNAPSHOT_KIND, "run_id": payload["run_id"],
                                             "computed_at": payload["computed_at"]}])
        print(json.dumps({"lane": htr.LANE_ID, **summary}, sort_keys=True))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
