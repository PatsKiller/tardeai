"""Product read path: hot tier, then the Postgres stored copy, then an envelope (DSN §6.1, LQ-20261107-2595).

This module never computes a product and never imports a builder. It reads stored bytes, parses them with
``json.loads`` and stamps them with the product's clocks. A hot-tier outage falls back to Postgres; a Postgres
failure, or a read over ``budget_ms``, answers UNKNOWN "product store unavailable".

``budget_ms`` is checked after the Postgres read returns; it does not interrupt a running query. Bound the real wait
inside ``fetch_row`` (for example ``SET LOCAL statement_timeout``).
"""

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone

from scripts.lib.cc_products.hot_tier import HotTier, HotTierDown, pack, product_key, unpack

STORE_UNAVAILABLE = "product store unavailable"

READ_COUNTERS: dict[str, int] = {
    "OK": 0,
    "STALE": 0,
    "UNKNOWN": 0,
    "BUILDING": 0,
    "hot_hit": 0,
    "hot_miss": 0,
    "hot_down": 0,
    "hot_bad_entry": 0,
    "hot_set": 0,
    "hot_set_failed": 0,
    "pg_hit": 0,
    "pg_miss": 0,
    "store_unavailable": 0,
    "budget_exceeded": 0,
    "body_unreadable": 0,
}
_COUNTER_LOCK = threading.Lock()


def _count(name: str) -> None:
    with _COUNTER_LOCK:
        READ_COUNTERS[name] = READ_COUNTERS.get(name, 0) + 1


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _aware(v):
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    if isinstance(v, datetime) and v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v


def _envelope(product_id, scope_key, status, *, row=None, age_s=None, reason=None, data=None, last_good=None,
              served_from=None) -> dict:
    row = row or {}
    return {
        "product": product_id,
        "scope": scope_key,
        "status": status,
        "as_of": _iso(row.get("as_of")),
        "built_at": _iso(row.get("built_at")),
        "next_refresh_at": _iso(row.get("next_refresh_at")),
        "stale_after_s": row.get("stale_after_s"),
        "hard_expiry_s": row.get("hard_expiry_s"),
        "age_s": age_s,
        "seq": row.get("seq"),
        "etag": row.get("etag"),
        "reason": reason,
        "data": data,
        "last_good": last_good,
        "served_from": served_from,
        # LQ-2600 (REVIEW-2606 F2): the stored per-section clocks travel with the envelope, so a reader can show the
        # oldest section's age instead of only the product clock (cio.pages stamps as_of at sources-read time).
        "source_watermarks": row.get("source_watermarks"),
        # Failure state of the stored row (operator 13 Nov contract): a DEGRADED body, or the reason the most recent
        # build failed while this last good was kept (``store_pg.mark_failed``). None when the last build succeeded.
        "build_status": row.get("status"),
        "build_failure": row.get("reason"),
        "schema_version": row.get("schema_version"),
    }


def _age_seconds(row: dict, now: datetime) -> float:
    """Age from as_of (when the data was true), falling back to built_at only when as_of is null."""
    ref = row.get("as_of")
    if ref is None:
        ref = row.get("built_at")
    ref = _aware(ref)
    if ref is None:
        return math.inf  # a product with no clock is treated as stale/expired (DSN Rule 5)
    return max(0.0, (now - ref).total_seconds())


def read_product(product_id: str, scope_key: str = "global", *, fetch_row, hot: HotTier | None = None,
                 now: datetime | None = None, budget_ms: int = 250) -> dict:
    t0 = time.monotonic()
    now = _aware(now) if now is not None else datetime.now(timezone.utc)
    key = product_key(product_id, scope_key)

    row = None
    served_from = None
    if hot is not None:
        try:
            raw = hot.get(key)
        except HotTierDown:
            _count("hot_down")
            raw = None
        else:
            _count("hot_hit" if raw is not None else "hot_miss")
        if raw is not None:
            try:
                row = unpack(raw)
                served_from = "hot"
            except Exception:  # noqa: BLE001 - a corrupt cache entry is a miss, never an error
                _count("hot_bad_entry")
                row = None

    if row is None:
        try:
            row = fetch_row(product_id, scope_key)
        except Exception:  # noqa: BLE001 - the store being unavailable is an answer, not a crash
            _count("store_unavailable")
            _count("UNKNOWN")
            return _envelope(product_id, scope_key, "UNKNOWN", reason=STORE_UNAVAILABLE)
        if (time.monotonic() - t0) * 1000.0 > budget_ms:
            _count("budget_exceeded")
            _count("UNKNOWN")
            return _envelope(product_id, scope_key, "UNKNOWN", reason=STORE_UNAVAILABLE)
        if row is None:
            _count("pg_miss")
            _count("BUILDING")
            return _envelope(product_id, scope_key, "BUILDING", reason="not built yet")
        _count("pg_hit")
        served_from = "pg"

    age = _age_seconds(row, now)
    age_s = None if math.isinf(age) else int(age)
    hard = row.get("hard_expiry_s")
    stale = row.get("stale_after_s")

    if served_from == "pg" and hot is not None and hard is not None and not math.isinf(age):
        ex_s = math.floor(hard - age)
        if ex_s > 0:
            try:
                hot.set(key, pack(row), ex_s)
                _count("hot_set")
            except HotTierDown:
                _count("hot_set_failed")

    try:
        body = row.get("body")
        parsed = json.loads(bytes(body)) if body is not None else None
    except (ValueError, TypeError):
        _count("body_unreadable")
        _count("UNKNOWN")
        return _envelope(product_id, scope_key, "UNKNOWN", row=row, age_s=age_s, reason="product body unreadable",
                         served_from=served_from)

    if hard is None or age > hard:
        _count("UNKNOWN")
        return _envelope(product_id, scope_key, "UNKNOWN", row=row, age_s=age_s,
                         reason=f"past hard expiry; last good {_iso(row.get('built_at'))}",
                         data=None, last_good=parsed, served_from=served_from)
    if stale is None or age > stale:
        _count("STALE")
        return _envelope(product_id, scope_key, "STALE", row=row, age_s=age_s,
                         reason=f"stale: age {age_s}s past stale_after {stale}s", data=parsed,
                         served_from=served_from)
    _count("OK")
    return _envelope(product_id, scope_key, "OK", row=row, age_s=age_s, data=parsed, served_from=served_from)
