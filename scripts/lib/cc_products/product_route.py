"""Stored-product reads for the Home/route products (operator 13 Nov 2026, DSN-20261112 §6.1).

Every function here serves a STORED product: one primary-key read (hot tier, then Postgres under a 250 ms statement
timeout) and one ``json.loads``. Nothing here imports a builder, ``builders.py``, ``api_v2`` or any of the libraries
the builders call, and nothing computes on a miss. The four cases the operator named all answer without compute:

* missing product (no row yet)      -> UNKNOWN-shaped legacy body, ``_product.status`` BUILDING
* expired product (past hard expiry) -> the last good body, ``_product.greyed`` True, ``_product.status`` UNKNOWN
* Valkey down                        -> the Postgres row (read_path falls through)
* store unreadable                   -> UNKNOWN-shaped legacy body

Each read logs one line ``cc_product_read product=... hit=...`` and counts into ``PRODUCT_READS`` (per product:
OK/STALE/UNKNOWN/BUILDING plus hit/miss), so hit/miss is measurable per product.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from scripts.lib.cc_products import cio_pages_route as _cpr

log = logging.getLogger("cc_products.read")

PRODUCT_READS: dict[str, dict[str, int]] = {}
_LOCK = threading.Lock()


def _count(product: str, *keys: str) -> None:
    with _LOCK:
        c = PRODUCT_READS.setdefault(product, {})
        for k in keys:
            c[k] = c.get(k, 0) + 1


def read_envelope(product_id: str, scope_key: str = "global", *, read_product: Callable | None = None,
                  fetch_row: Callable | None = None, hot=None, now: datetime | None = None) -> dict:
    """The §6.1 envelope for one stored product. Never raises, never computes."""
    if read_product is None:
        from scripts.lib.cc_products.read_path import read_product as read_product
    if fetch_row is None:
        def fetch_row(pid, scope=scope_key):  # noqa: ARG001
            raise _cpr.StoreUnavailable("no product store configured")
    try:
        env = read_product(product_id, scope_key, fetch_row=fetch_row, hot=hot, now=now)
    except Exception as e:  # noqa: BLE001 - a reader defect is UNKNOWN, never a compute and never a 500
        env = {"status": "UNKNOWN", "reason": f"product store unavailable ({type(e).__name__})", "data": None}
    if not isinstance(env, dict):
        env = {"status": "UNKNOWN", "reason": "product store unavailable", "data": None}
    status = str(env.get("status") or "UNKNOWN")
    hit = status in ("OK", "STALE")
    _count(product_id, status, "hit" if hit else "miss")
    log.info("cc_product_read product=%s scope=%s status=%s served_from=%s hit=%s age_s=%s seq=%s",
             product_id, scope_key, status, env.get("served_from"), int(hit), env.get("age_s"), env.get("seq"))
    return env


def _now(now):
    n = now if now is not None else datetime.now(timezone.utc)
    return n if n.tzinfo else n.replace(tzinfo=timezone.utc)


def _meta(env: dict, *, status: str, greyed: bool, now: datetime) -> dict:
    return _cpr._meta(env, status=status, reason=env.get("reason"), greyed=greyed, now=now) | {
        "product": env.get("product")}


def _as_dict(v):
    return _cpr._as_dict(v)


def _pick(env: dict, now: datetime, part: Callable[[dict], Any]):
    """(body_part, meta) from an envelope, or (None, meta) when there is no servable body."""
    status = str(env.get("status") or "UNKNOWN")
    if status in ("OK", "STALE"):
        data = _as_dict(env.get("data"))
        if data is not None:
            return part(data), _meta(env, status=status, greyed=False, now=now)
        env = {**env, "reason": "stored product body unreadable"}
        status = "UNKNOWN"
    elif status == "UNKNOWN":
        lg = _as_dict(env.get("last_good"))
        if lg is not None:
            return part(lg), _meta(env, status="UNKNOWN", greyed=True, now=now)
    if status != "BUILDING":
        status = "UNKNOWN"
    return None, _meta(env, status=status, greyed=False, now=now)


def _why(meta: dict) -> str:
    if meta.get("status") == "BUILDING":
        return "product not built yet (no stored copy)"
    return meta.get("reason") or "product store unavailable"


# ------------------------------------------------------------------------------------ market_risk.latest


def serve_market_risk_latest(*, now=None, **io) -> dict:
    """GET /api/v2/market-risk/latest from ``market_risk.latest``.``projection``."""
    now = _now(now)
    env = read_envelope("market_risk.latest", now=now, **io)
    body, meta = _pick(env, now, lambda d: d.get("projection"))
    if isinstance(body, dict):
        return {**body, "_product": meta}
    return {"state": "not_evaluated", "reason": f"market risk record unavailable: {_why(meta)}", "_product": meta}


def serve_home_cio_card(*, now=None, **io) -> dict:
    """GET /api/v2/home/cio-card from ``market_risk.latest``.``home_cio_card`` (one record, two routes)."""
    now = _now(now)
    env = read_envelope("market_risk.latest", now=now, **io)
    body, meta = _pick(env, now, lambda d: d.get("home_cio_card"))
    if isinstance(body, dict):
        return {**body, "_product": meta}
    return {"schema": "HomeCioCard@v1", "state": "UNKNOWN", "advisory_only": True,
            "reason": f"CIO card record unavailable: {_why(meta)}", "_product": meta}


# ------------------------------------------------------------------------------------------------ risk


def serve_risk(*, now=None, **io) -> dict:
    """GET /api/v2/risk from ``risk``. Unavailable is null values (unknown), never empty lists (nothing at risk)."""
    now = _now(now)
    env = read_envelope("risk", now=now, **io)
    body, meta = _pick(env, now, lambda d: d)
    if isinstance(body, dict):
        return {**body, "_product": meta}
    why = _why(meta)
    return {"positions": None, "portfolio_heat_pct": None, "total_risk_dollars": None, "source": "cc_product:risk",
            "truth": {"source": None, "as_of": None, "stale": True, "gap": f"risk record unavailable: {why}"},
            "_product": meta}


# ----------------------------------------------------------------------------------- reports.analyst_links


def serve_analyst_links(query=None, *, now=None, **io) -> dict:
    """GET /api/v2/reports/analyst/links from the stored full map; ``symbol`` and ``limit`` applied here (the legacy
    route filtered by symbol, sorted by generated_at desc, then truncated to ``limit``; the stored map is already
    in that order)."""
    now = _now(now)
    q = query or {}
    env = read_envelope("reports.analyst_links", now=now, **io)
    body, meta = _pick(env, now, lambda d: d)
    if not isinstance(body, dict) or not isinstance(body.get("links"), dict):
        return {"links": None, "count": None, "updated_at": None,
                "reason": f"analyst links unavailable: {_why(meta)}", "_product": meta}
    sym = str(q.get("symbol") or "").strip().upper()
    try:
        limit = int(q.get("limit", 300) or 300)
    except (TypeError, ValueError):
        limit = 300
    items = [(k, v) for k, v in body["links"].items() if not sym or k == sym]
    if limit and len(items) > limit:
        items = items[:limit]
    links = dict(items)
    return {"links": links, "count": len(links), "updated_at": body.get("updated_at"), "_product": meta}


# ------------------------------------------------------------------------------------------------ home

HOME_SLICES = ("since_close", "incidents", "approvals_summary", "priorities_live", "status", "gates")

_SLICE_UNKNOWN = {
    "since_close": lambda why: {"status": "UNKNOWN", "reason": why},
    "incidents": lambda why: {"schema": "HomeIncidents@v1", "state": "UNKNOWN", "reason": why},
    "priorities_live": lambda why: {"schema": "HomePrioritiesLive@v1", "state": "UNKNOWN", "reason": why},
    "status": lambda why: {"verdict": "UNKNOWN", "reason": why,
                           "trade_ready": {"verdict": "UNKNOWN", "cause": why, "computed_at": None}},
    "gates": lambda why: {"state": "UNKNOWN", "reason": why},
    "approvals_summary": lambda why: {"state": "UNKNOWN", "reason": why},
}


def _slice_meta(data: dict, name: str, now: datetime) -> dict:
    from scripts.lib.cc_products.cio_pages_route import _parse_ts

    clock = ((data.get("slice_clocks") or {}).get(name) or {}).get("as_of")
    stale_after = (data.get("slice_stale_after_s") or {}).get(name)
    ts = _parse_ts(clock)
    age = None if ts is None else max(0, int((now - ts).total_seconds()))
    return {"slice": name, "slice_as_of": clock, "slice_age_s": age, "slice_stale_after_s": stale_after,
            # a slice with no clock, or older than its own limit, is stale whatever the product build time says
            "slice_stale": age is None or (stale_after is not None and age > stale_after)}


def serve_home_product(query=None, *, now=None, **io) -> dict:
    """GET /api/v2/products/home: the whole Home product (both sections' server reads) with every slice's own clock
    aged at serve time. ``?slice=<name>`` returns one slice as its legacy route would."""
    q = query or {}
    if q.get("slice"):
        return serve_home_slice(str(q["slice"]), now=now, **io)
    now = _now(now)
    env = read_envelope("home", now=now, **io)
    body, meta = _pick(env, now, lambda d: d)
    out = {"product": "home", "_product": meta, "slices": None}
    if isinstance(body, dict):
        out["slices"] = {n: {"data": (body.get("slices") or {}).get(n), **_slice_meta(body, n, now)}
                         for n in HOME_SLICES}
    return out


def serve_home_slice(name: str, *, now=None, **io) -> dict:
    """One Home slice in its legacy route shape plus ``_product`` (product clocks + the slice's own clock)."""
    now = _now(now)
    if name not in HOME_SLICES:
        return {"state": "UNKNOWN", "reason": f"unknown home slice {name!r}"}
    env = read_envelope("home", now=now, **io)
    body, meta = _pick(env, now, lambda d: d)
    if isinstance(body, dict):
        sl = (body.get("slices") or {}).get(name)
        smeta = _slice_meta(body, name, now)
        if isinstance(sl, dict) and "error" not in sl and not sl.get("scope_excluded"):
            if name == "since_close" and sl.get("status") == "ok":
                sl = _refresh_since_close_freshness(sl, now)
            return {**sl, "_product": {**meta, **smeta}}
        why = (sl or {}).get("error") or (sl or {}).get("reason") or "slice missing from the stored product"
        return {**_SLICE_UNKNOWN[name](f"home slice {name} unavailable: {why}"), "_product": {**meta, **smeta}}
    return {**_SLICE_UNKNOWN[name](f"home record unavailable: {_why(meta)}"), "_product": meta}


def _refresh_since_close_freshness(sl: dict, now: datetime) -> dict:
    """``freshness`` was computed at build time; age it again now (pure arithmetic over generated_at + window)."""
    try:
        from zoneinfo import ZoneInfo

        from lib import since_close_card as _sc

        now_et = now.astimezone(ZoneInfo("America/New_York"))
        return {**sl, "freshness": _sc.freshness(sl, now=now_et), "window_now": _sc.window(now_et),
                "as_of_now": now_et.isoformat()}
    except Exception:  # noqa: BLE001 - keep the stored body; the slice meta still carries its own age
        return sl


def counters() -> dict:
    with _LOCK:
        return json.loads(json.dumps(PRODUCT_READS))
