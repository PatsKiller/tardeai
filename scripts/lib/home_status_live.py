"""GET /api/v2/home/status served from STORED data, computed on the request (home-status-backend, 2026-11-12).

Why this exists: the 2144/2411 design has the n8n lane ``home-status-verdict`` write a ``home_snapshots`` row and the
route only read it. Measured 2026-11-12 14:2x ET: the lane is shadow (dry_run) and ``home_snapshots`` is not migrated,
so that route could only ever serve UNKNOWN "no snapshot written". This module keeps the same rule and the same
providers and only changes WHERE the providers run:

1. A fresh, valid ``home_snapshots`` snapshot (once the lane is live) is served as is (``home_trade_ready.served_status``).
2. Otherwise the lane's own read-only providers (``scripts/home_status_verdict.gather``) run on the request against
   the database the API already holds, each statement in a READ ONLY transaction under a 2 s ``statement_timeout``,
   and ``compute_verdict`` applies the operator rule (D2-a..d, R3 from config/home_status_registry.json).
3. The result is cached for ``CACHE_TTL_S`` so a page poll storm costs one computation per window.

Never: a broker call, a credential-health probe, /api/v2/overview, any network, any write. Every read is bounded
(aggregates or the open-incident set; no whole-table and no JSONL loads). Any failure is UNKNOWN with a named reason;
nothing here can turn an unread input into YES (the rule's own YES guard still applies).

The served body is the HomeStatus@v1 payload plus two flat views the page draws directly:

* ``trade_ready``: ``{"verdict": YES|NO|UNKNOWN, "cause": str, "computed_at", "read_from"}``;
* ``gates``: one row per verdict input, ``{"id", "label", "required", "state", "source_id", "as_of", "age_s",
  "threshold_s", "reason", "needs_backend"}``.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

CACHE_TTL_S = 30
STATEMENT_TIMEOUT_MS = 2000
READ_FROM_COMPUTED = "computed_on_request"

GATE_LABELS = (
    ("p0", "Open P0 incidents"),
    ("p1_blocking", "P1 blocking trading"),
    ("incident_classes", "Incident classification"),
    ("gates", "Validation gates"),
    ("portfolio", "Portfolio (positions sync)"),
    ("orders", "Orders / protection"),
    ("data", "Data freshness (quotes)"),
    ("schedulers", "Schedulers (info)"),
    ("alerts", "Alerts (info)"),
)

_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def _modules():
    """(home_trade_ready, home_status_verdict) under ONE import root so Timeout/Reading identities match the lane's."""
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts import home_status_verdict as hsv
    from scripts.lib import home_trade_ready as htr
    return htr, hsv


def readonly_query(get_conn: Callable[[], Any], timeout_cls: type) -> Callable[..., list]:
    """A lane-style ``q(sql, params)`` over the API's connection: READ ONLY transaction + 2 s statement_timeout, always
    rolled back (a read-only session never commits). A statement timeout raises ``timeout_cls`` (-> TIMED_OUT)."""

    def q(sql: str, params: Optional[tuple] = None) -> list[dict[str, Any]]:
        conn = get_conn()
        if conn is None:
            raise ConnectionError("database connection unavailable")
        import psycopg2
        import psycopg2.extras

        try:
            conn.rollback()  # start from a clean transaction; nothing of ours is ever pending
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.errors.QueryCanceled as exc:
            raise timeout_cls() from exc
        finally:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 -- a broken connection is the next call's ConnectionError
                pass

    return q


def _cause(payload: dict[str, Any]) -> str:
    v = payload.get("verdict")
    if v == "NO":
        b = (payload.get("blockers") or [{}])[0]
        more = len(payload.get("blockers") or []) - 1
        tail = f" (+{more} more)" if more > 0 else ""
        return f"{b.get('category')}: {b.get('cause')}{tail}"
    if v == "YES":
        return "every required input read OK and nothing blocks trading"
    u = payload.get("unknown_inputs") or []
    if not u:
        return payload.get("reason") or "verdict could not be computed"
    return "; ".join(f"{x.get('input')}: {x.get('reason')}" for x in u[:3]) + (f" (+{len(u) - 3} more)" if len(u) > 3 else "")


def flatten(payload: dict[str, Any], read_from: Optional[str]) -> dict[str, Any]:
    """Add ``trade_ready`` and ``gates`` (the page's flat views) to a HomeStatus@v1 payload."""
    fields = {**(payload.get("rows") or {}), **(payload.get("inputs") or {})}
    gates = []
    for gid, label in GATE_LABELS:
        f = fields.get(gid)
        if not isinstance(f, dict):
            continue
        gates.append({"id": gid, "label": label, "required": bool(f.get("required")), "state": f.get("state"),
                      "source_id": f.get("source_id"), "as_of": f.get("as_of"), "age_s": f.get("age_s"),
                      "threshold_s": f.get("threshold_s"), "value": f.get("value") if isinstance(f.get("value"), int) else None,
                      "reason": f.get("reason") or f.get("cause"), "needs_backend": bool(f.get("needs_backend"))})
    out = dict(payload)
    out["trade_ready"] = {"verdict": payload.get("verdict"), "cause": _cause(payload),
                          "computed_at": payload.get("computed_at") or (payload.get("snapshot") or {}).get("computed_at"),
                          "read_from": read_from}
    out["gates"] = gates
    out["read_from"] = read_from
    return out


def compute(q: Callable[..., list], now: datetime, *, state_root: Optional[Path] = None,
            registry_loader: Optional[Callable[[], Any]] = None) -> dict[str, Any]:
    htr, hsv = _modules()
    registry = (registry_loader or hsv.load_registry)()
    readings = hsv.gather(q, now, state_root=state_root, registry=registry)
    payload = htr.compute_verdict(readings, now, run_id="request:" + now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  policy=(registry or {}).get("protection_verdict"))
    payload["served_at"] = htr.iso(now)
    return flatten(payload, READ_FROM_COMPUTED)


def _unknown(reason: str, now: datetime) -> dict[str, Any]:
    htr, _ = _modules()
    payload = {"schema": htr.SCHEMA, "rule_version": htr.RULE_VERSION, "verdict": htr.UNKNOWN, "computed_at": htr.iso(now),
               "served_at": htr.iso(now), "reason": reason, "blockers": [], "non_blocking": [], "data_quality": [],
               "unknown_inputs": [{"input": "home_status", "state": htr.UNKNOWN, "reason": reason}], "inputs": {}, "rows": {}}
    return flatten(payload, None)


def serve(get_conn: Callable[[], Any], *, now: Optional[datetime] = None, state_root: Optional[Path] = None,
          snapshot_query: Optional[Callable[..., Any]] = None, use_cache: bool = True,
          registry_loader: Optional[Callable[[], Any]] = None) -> dict[str, Any]:
    """The body of GET /api/v2/home/status. Fresh lane snapshot first; else computed on the request; cached 30 s.

    A cache-miss storm serialises on ``_LOCK``; the cache is therefore checked a second time *inside* the lock, so
    the waiters return the body the lock holder just computed instead of each running the provider set again
    (REVIEW-20261107-2446 B-1). ``snapshot_query`` only enables the snapshot-first path: the snapshot SELECT itself
    runs through ``readonly_query`` (READ ONLY + ``statement_timeout``) like every other statement.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if use_cache:
        hit = _CACHE.get("v")
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return {**hit[1], "cache_age_s": int(time.monotonic() - hit[0])}
    with _LOCK:
        if use_cache:  # double-checked: another request may have filled the cache while this one waited for the lock
            hit = _CACHE.get("v")
            if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
                return {**hit[1], "cache_age_s": int(time.monotonic() - hit[0])}
        try:
            htr, hsv = _modules()
            q = readonly_query(get_conn, hsv.Timeout)

            def snapshot_read(sql: str, params: Optional[tuple] = None) -> Optional[list]:
                """The stored snapshot under the same READ ONLY txn + timeout as every other read.
                An unreadable store is ``None`` so ``served_status`` reports ``db_readable: false``, not a 500."""
                try:
                    return q(sql, params)
                except Exception:  # noqa: BLE001 -- latest_from_db treats None as "store unreadable"
                    return None

            if snapshot_query is not None:
                try:
                    present = q("SELECT to_regclass('public.home_snapshots') IS NOT NULL AS present", None)
                    if present and present[0].get("present"):
                        snap = htr.served_status(query=snapshot_read, mirror=Path("/nonexistent"), now=now)
                        if snap.get("state") == htr.OK:
                            out = flatten(snap, "snapshot")
                            if use_cache:  # same rule as the computed path (LQ-2470)
                                _CACHE["v"] = (time.monotonic(), out)
                            return out
                except Exception:  # noqa: BLE001 -- the snapshot is optional; fall through to the computed read
                    pass
            out = compute(q, now, state_root=state_root, registry_loader=registry_loader)
        except Exception as exc:  # noqa: BLE001 -- never a 500 and never YES: UNKNOWN with the failure named
            return _unknown(f"home status read failed: {type(exc).__name__}", now)
        if use_cache:
            _CACHE["v"] = (time.monotonic(), out)
        return out
