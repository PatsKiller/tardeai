#!/usr/bin/env python3
"""Lane ``stop-coverage-incidents`` (LQ-20261107-2145/2146, Home v010 backend W1-b; folds LQ-2108's UNPROTECTED work).

Writes the protection-gap incident Home reads: ONE open ``alert_incidents`` row per (account, symbol) with
``alert_type='position_unprotected'``. It goes through the single writer, ``alert_outbox.publish_event`` ->
``alert_occurrence_store.record_occurrence`` (no second writer, no table of its own), so:

  * ``first_seen_at`` is set when the gap opens and never moves while the incident stays open;
  * one occurrence per scan, however many terminal stop orders the position has;
  * a gap that reappears after resolution reopens the same incident (record_occurrence reclaims by incident id):
    ``first_seen_at`` restarts, but ``occurrence_count`` keeps counting across episodes, because it is the source of
    the occurrence log's ``occurrence_seq`` (UNIQUE (incident_id, occurrence_seq); LQ-2667, REVIEW-2653 B1).

Input is stop_lifecycle_monitor.scan(persist=False): the SAME coverage logic stop-health-check uses (imported, not
copied). stop_last_known cannot serve as the input today: it holds no working-stop rows at all (measured 2026-11-11:
replaced/filled/not_in_read/pending_activation/rejected/expired/canceled), so a join on it would call every position
unprotected.

Resolution needs positive evidence from a COMPLETE scan: the same position present, no ``unprotected`` flag, health ok.
A position missing from the scan, a blind Schwab read, or a legacy row with no account identity stays open and is
reported as ``unresolved_unknown`` (unknown beats wrong). Off-hours, a DAY-duration stop that expired at the close is
reported as ``day_stop_expired`` and opens no incident (open decision D1: is that OK or WARN on Home?).

LQ-20261107-2968: the input is the PERSISTED ``stop_lifecycle`` snapshot (written every ~10 min in session by
``stop_health_check.py`` via system cron ``*/10 9-16 * * 1-5``, and on demand by ``/api/v2/stop-lifecycle``) joined to
``positions_current``. This lane NEVER calls Schwab, so it needs no broker-read grant. A snapshot older than 900 s in
session (5400 s off-hours) makes every position UNAVAILABLE: not covered, not uncovered, nothing opened or resolved.

Dry-run by default: prints the plan and writes nothing. ``--apply`` publishes. Account ids are stored as a hash only.
Never places, modifies or cancels an order; never calls a broker write route.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

ALERT_TYPE = "position_unprotected"
SOURCE_SYSTEM = "stop_lifecycle_monitor"
SOURCE_PRODUCER = "stop_coverage_incidents"
HEARTBEAT_NAME = "stop_coverage_incidents_last.json"   # the reader (home_status_verdict.ORDERS_HEARTBEAT) joins on this name


def account_hash(account: Any) -> str:
    return hashlib.sha256(str(account).encode("utf-8")).hexdigest()[:12]


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else None


def _complete(scan: dict) -> tuple[datetime | None, str]:
    """Same bar as stop_health_check._recover_current_scan: a blind or partial scan proves nothing."""
    stops, at = scan.get("stops"), _when(scan.get("generated_at"))
    if (not isinstance(stops, list) or not stops or at is None or scan.get("ok") is False or scan.get("errors")
            or scan.get("schwab_stops_status") == "UNAVAILABLE"
            or (scan.get("summary") or {}).get("total") != len(stops)):
        return None, "incomplete_scan"
    return at, ""


def plan(scan: dict, open_rows: list[tuple[str, str]], *, session_open: bool = True) -> dict:
    """Pure: what this scan says. ``open_rows`` = (hashed account, SYMBOL) of the currently open incidents."""
    at, why = _complete(scan)
    if at is None:
        return {"ok": False, "reason": why, "gaps": [], "resolve": [], "unresolved_unknown": [],
                "day_stop_expired": []}
    gaps: dict[tuple[str, str], dict] = {}
    covered: set[tuple[str, str]] = set()
    day_expired: dict[tuple[str, str], dict] = {}
    for r in scan["stops"]:
        sym, acct = r.get("symbol"), r.get("account")
        if not (isinstance(sym, str) and sym.strip() and acct not in (None, "")):
            continue                      # no identity: cannot be keyed or matched
        key = (account_hash(acct), sym.strip().upper())
        if "unprotected" in (r.get("flags") or []):
            if (not session_open and str(r.get("duration") or "").upper() == "DAY"
                    and str(r.get("status") or "").lower() == "expired"):
                day_expired[key] = r
            else:
                gaps.setdefault(key, r)
        elif r.get("health") == "ok":
            covered.add(key)
    covered -= set(gaps) | set(day_expired)   # an unprotected sibling outweighs a healthy one
    opened = {tuple(k) for k in open_rows}
    return {"ok": True, "at": at, "gaps": sorted(gaps), "gap_records": gaps,
            "resolve": sorted(k for k in opened if k in covered and k not in gaps),
            "unresolved_unknown": sorted(k for k in opened if k not in gaps and k not in covered),
            "day_stop_expired": sorted(day_expired)}


def _event(key: tuple[str, str], at: datetime, rec: dict | None):
    from operator_alert_policy_v2 import AlertEvent
    ah, sym = key
    payload = {"kind": "stop_coverage", "state": "unprotected" if rec else "covered"}
    if rec:
        payload.update(held_qty=rec.get("held_qty"), last_order_status=rec.get("status"),
                       duration=rec.get("duration"))
    return AlertEvent(alert_type=ALERT_TYPE, source_system=SOURCE_SYSTEM, source_producer=SOURCE_PRODUCER,
                      account_id=ah, symbol=sym, severity="critical", operator_action_required=True,
                      operator_action_type="PROTECTION_REPAIR", payload=payload, created_at=at)


def _open_keys(conn) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT account_id, symbol FROM alert_incidents WHERE alert_type = %s AND status = 'open' "
                    "AND source_producer = %s AND account_id IS NOT NULL AND account_id <> '' AND symbol IS NOT NULL",
                    (ALERT_TYPE, SOURCE_PRODUCER))
        return [(a, s) for a, s in cur.fetchall()]


MAX_AGE_SESSION_S = 900     # */10 writer + margin; the Home reader's bar (ORDERS_MAX_AGE_SESSION_S)
MAX_AGE_OFF_S = 5400
POSITIONS_MAX_AGE_SESSION_S = 7200
WORKING = ("working", "near_trigger")
SNAPSHOT_SQL = ("SELECT account, symbol, status, lifecycle, health, flags, held_qty, snapshot_at FROM stop_lifecycle")
POSITIONS_SQL = ("SELECT account_key, symbol, qty, broker_market_value, asset_type, is_cash, as_of "
                 "FROM positions_current WHERE NOT is_cash AND qty > 0")


def _held_filter() -> dict:
    """The held-position bar the desk-truth coverage check already uses (floor, paper accounts, aliases, exempt)."""
    try:
        cfg = json.loads((PROJECT_ROOT / "config" / "desk_truth_monitors.json").read_text(encoding="utf-8"))
        return dict(cfg.get("held_exit_coverage") or {})
    except (OSError, ValueError):
        return {}


def scan_from_snapshot(snapshot: list[dict], positions: list[dict], *, now: datetime, session_open: bool = True,
                       cfg: dict | None = None) -> dict:
    """Pure. Build a ``scan``-shaped dict from the persisted snapshot + positions; no broker is read.

    * snapshot missing or older than the limit -> ``stale_snapshot`` (every position UNAVAILABLE);
    * a held position with no WORKING stop in a snapshotted account -> one ``unprotected`` record (a gap);
    * a held position with a WORKING stop -> a healthy record (covered);
    * a held position in an account the snapshot has no row for at all (another broker) -> omitted: unknown, never a gap.
    """
    cfg = _held_filter() if cfg is None else cfg
    aliases = dict(cfg.get("account_aliases") or {})
    paper = {str(x) for x in cfg.get("paper_accounts") or []}
    exempt = {(str(e.get("account")), str(e.get("symbol")).upper()) for e in cfg.get("exempt") or []
              if isinstance(e, dict)}
    floor = float(cfg.get("min_position_value_usd", 0) or 0)
    skip_types = {str(x).lower() for x in cfg.get("exclude_asset_types") or []}
    labels = {str(k).lower(): str(v) for k, v in (cfg.get("not_stop_protectable_labels") or {}).items()}
    not_protectable: list[dict] = []
    limit = MAX_AGE_SESSION_S if session_open else MAX_AGE_OFF_S
    newest = max((t for t in (_when(r.get("snapshot_at")) for r in snapshot) if t is not None), default=None)
    if newest is None:
        return {"ok": False, "reason": "snapshot_missing", "stops": [], "snapshot_age_s": None}
    age = (now - newest).total_seconds()
    if age > limit:
        return {"ok": False, "reason": "snapshot_stale", "stops": [], "snapshot_age_s": round(age),
                "limit_s": limit}
    pos_at = max((t for t in (_when(r.get("as_of")) for r in positions) if t is not None), default=None)
    # positions are synced less often than the stop snapshot is written; in session a 2 h bar (the desk-truth check's
    # own), off-hours nothing moves so only "no positions at all" is unavailable
    if pos_at is None or (session_open and (now - pos_at).total_seconds() > POSITIONS_MAX_AGE_SESSION_S):
        return {"ok": False, "reason": "positions_stale", "stops": [], "snapshot_age_s": round(age),
                "limit_s": POSITIONS_MAX_AGE_SESSION_S}
    live_accts = {str(aliases.get(r.get("account"), r.get("account"))) for r in snapshot
                  if str(aliases.get(r.get("account"), r.get("account"))) not in paper}
    working = {(str(aliases.get(r.get("account"), r.get("account"))), str(r.get("symbol") or "").upper())
               for r in snapshot if str(r.get("lifecycle") or "") in WORKING}
    stops: list[dict] = []
    for p in positions:
        acct, sym = str(p.get("account_key")), str(p.get("symbol") or "").strip().upper()
        if not sym or acct in paper or acct not in live_accts or (acct, sym) in exempt:
            continue
        if str(p.get("asset_type") or "").lower() in skip_types:
            label = labels.get(str(p.get("asset_type") or "").lower())
            if label:   # not a gap, but never hidden (LQ-2964: a mutual fund cannot carry a stop)
                not_protectable.append({"symbol": sym, "asset_type": str(p.get("asset_type")), "label": label})
            continue
        mv = p.get("broker_market_value")
        if floor and mv is not None and abs(float(mv)) < floor:
            continue                       # dust: not checked (a missing value is checked)
        if (acct, sym) in working:
            stops.append({"account": acct, "symbol": sym, "health": "ok", "flags": []})
        else:
            stops.append({"account": acct, "symbol": sym, "health": "alert", "flags": ["unprotected"],
                          "held_qty": float(p.get("qty") or 0), "status": None})
    return {"ok": True, "stops": stops, "generated_at": now, "snapshot_age_s": round(age),
            "summary": {"total": len(stops)}, "errors": [], "schwab_stops_status": "SNAPSHOT",
            "not_stop_protectable": sorted(not_protectable, key=lambda r: r["symbol"])}


def _fetch(conn, sql: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def run(scan: dict, *, conn: Any = None, publish: Callable | None = None, apply: bool = False,
        session_open: bool = True) -> dict:
    """Plan, and with ``apply`` publish one occurrence per gap and one resolving occurrence per proven recovery."""
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()
    p = plan(scan, _open_keys(conn), session_open=session_open)
    out = {k: p[k] for k in ("ok", "gaps", "resolve", "unresolved_unknown", "day_stop_expired") if k in p}
    out["reason"] = p.get("reason")
    out["applied"] = False
    if not p["ok"] or not apply:
        return out
    if publish is None:
        from alert_outbox import publish_event as publish
    failed = 0
    for key, rec, resolving in ([(k, p["gap_records"][k], False) for k in p["gaps"]]
                                + [(k, None, True) for k in p["resolve"]]):
        try:    # one bad key must not hide the rest, and must not read as success (C3)
            res = publish(_event(key, p["at"], rec), resolving=True) if resolving else publish(_event(key, p["at"], rec))
            if not _durable(res):
                failed += 1
        except Exception:
            failed += 1
    out["failed"] = failed
    if failed:
        out["ok"], out["reason"] = False, "publish_failed"
    out["applied"] = not failed
    return out


def _durable(res: Any) -> bool:
    """C2: publish_event swallows DB errors into an in-memory fallback and still says ok. Only a row id is proof."""
    return (isinstance(res, dict) and res.get("ok") is True and not res.get("volatile_fallback")
            and bool(res.get("occurrence_id")))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv
    started = datetime.now(timezone.utc).isoformat()
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        now = datetime.now(timezone.utc)
        session_open = "--offhours" not in argv   # the -offhours lane passes --offhours (no clock guessing here)
        scan = scan_from_snapshot(_fetch(conn, SNAPSHOT_SQL), _fetch(conn, POSITIONS_SQL), now=now,
                                  session_open=session_open)
        out = run(scan, conn=conn, apply=apply, session_open=session_open)
        if scan.get("reason") in ("snapshot_missing", "snapshot_stale", "positions_stale"):
            out["reason"] = scan["reason"]
            out["snapshot_age_s"] = scan.get("snapshot_age_s")
        status = "ok" if out["ok"] else ("unavailable" if out.get("reason") in
                                         ("snapshot_missing", "snapshot_stale", "positions_stale") else "error")
        doc = {"started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(), "status": status,
               "dry_run": not apply, **{k: len(v) if isinstance(v, list) else v for k, v in out.items()}}
        doc["not_stop_protectable"] = list(scan.get("not_stop_protectable") or [])   # the list, not a count
    except BaseException as exc:
        _heartbeat({"started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
                    "status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]})
        raise
    print(json.dumps({k: v for k, v in out.items()}, default=str))
    if apply:   # a dry run is not a run: it must not advance the lane's freshness key
        _heartbeat(doc)
    return 0 if out["ok"] else 2


def heartbeat_path() -> Path:
    from lib.lane_last_receipt import runtime_dir   # honours TRADEAI_STATE_ROOT, same as the Home reader
    return Path(runtime_dir()) / HEARTBEAT_NAME


def _heartbeat(doc: dict, path: Path | None = None) -> None:
    path = path or heartbeat_path()
    if doc.get("status") == "ok":
        doc = {**doc, "ok_at": doc.get("finished_at")}
    else:
        try:
            doc = {**doc, "ok_at": (json.loads(path.read_text(encoding="utf-8")) or {}).get("ok_at")}
        except (OSError, ValueError):
            doc = {**doc, "ok_at": None}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": "StopCoverageIncidentsRun@v1", **doc}, indent=1, default=str) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    sys.exit(main())
