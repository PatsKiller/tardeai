"""GET /api/v2/cio/pages served from the precomputed product store (LQ-20261107-2595, DSN-20261112 §6.1).

The legacy response shape is the ``w7_pages.page_payload`` dict. This module returns that dict as it
was stored by the ``cio.pages`` builder, plus one top-level ``_product`` key carrying the clocks. It
never computes: it does not import or call ``page_payload``, ``cio_truth.resolve``,
``w7_pages.project_pages`` or anything else in the build path. A request costs one primary-key read
(hot tier first, then Postgres) and one ``json.loads``.

Statuses (operator Q2 for UNKNOWN):

* OK / STALE: the stored payload, ``_product.greyed`` False.
* UNKNOWN past hard expiry with a last good body: that body, ``_product.greyed`` True, so the page
  draws it greyed under "UNKNOWN · last good <time>". Never shown as current.
* BUILDING (no row yet), or the store unreadable with no body: ``w7_pages.unavailable(reason)``,
  the same gap shape every panel already renders, plus ``_product``.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Callable

PRODUCT_ID = "cio.pages"
SCOPE_KEY = "global"

#: Store reads that take longer than this are cancelled by Postgres and served as UNKNOWN (DSN §6.1).
STATEMENT_TIMEOUT_MS = 250

_PRODUCT_FIELDS = ("status", "as_of", "built_at", "age_s", "stale_after_s", "hard_expiry_s", "next_refresh_at",
                   "seq", "reason", "served_from", "build_status", "build_failure")

_COLUMNS = ("product_id, scope_key, body, etag, seq, as_of, built_at, next_refresh_at, stale_after_s, "
            "hard_expiry_s, purge_after_s, status, reason, schema_version, source_watermarks, builder_sha, bytes, "
            "build_ms")


class StoreUnavailable(RuntimeError):
    """The product store could not be read (no database configured, no connection)."""


def _select_sql(timeout_ms: int) -> str:
    # SET LOCAL and the SELECT go in one simple-query message, so they share one transaction whether or
    # not the connection is in autocommit; the caller's commit/rollback ends it and resets the timeout.
    return (f"SET LOCAL statement_timeout = '{int(timeout_ms)}ms'; "
            f"SELECT {_COLUMNS} FROM cc_product_current WHERE product_id = %s AND scope_key = %s")


def make_pg_fetch_row(query: Callable[..., Any], *, timeout_ms: int = STATEMENT_TIMEOUT_MS) -> Callable:
    """Build the production ``fetch_row`` over a RAISING query callable (api_v2 ``_db_query_raising``).

    ``query(sql, params, fetch="all")`` must let errors propagate. ``_db_query`` must not be used: it turns
    every error into None, which would make "store down" look like "no row" and serve BUILDING instead of
    UNKNOWN. ``fetch="all"`` keeps the two apart here as well: no row is ``[]``, while a None return
    (no database configured, or no connection) raises ``StoreUnavailable``.
    """
    sql = _select_sql(timeout_ms)

    def fetch_row(product_id: str, scope_key: str = SCOPE_KEY) -> dict | None:
        rows = query(sql, (product_id, scope_key), fetch="all")
        if rows is None:
            raise StoreUnavailable("no database connection")
        if not rows:
            return None
        row = dict(rows[0])
        body = row.get("body")
        if isinstance(body, memoryview):
            row["body"] = body.tobytes()
        elif isinstance(body, bytearray):
            row["body"] = bytes(body)
        return row

    return fetch_row


_HOT_LOCK = threading.Lock()
_HOT: list = []


def production_hot():
    """The process-wide hot tier client (Valkey on 127.0.0.1:6379), or None when the module is absent.

    One instance per process; it opens a short connection per call with a 50 ms timeout, so a down
    Valkey costs a refused connect and the read falls through to Postgres."""
    with _HOT_LOCK:
        if not _HOT:
            try:
                from scripts.lib.cc_products.hot_tier import HotTier

                _HOT.append(HotTier())
            except Exception:  # noqa: BLE001 - no hot tier means Postgres only, never an error page
                _HOT.append(None)
        return _HOT[0]


def _unavailable(reason: str) -> dict:
    # w7_pages imports only json/datetime/pathlib and w7_lookthrough (pure helpers); page_payload is not called.
    from scripts.lib.w7_pages import unavailable

    return unavailable(reason)


def _as_dict(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray, memoryview, str)):
        try:
            parsed = json.loads(bytes(value) if not isinstance(value, str) else value)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


def oldest_section(env: dict, now: datetime) -> dict:
    """The oldest section clock the builder recorded, aged at serve time (LQ-2600, REVIEW-2606 F2).

    ``cio.pages`` stamps its product ``as_of`` when the build read its sources, so a page whose one section is a
    week old still reads OK on the product clock. This surfaces that section's clock beside it. A missing or
    unreadable watermark is ``None`` (unknown), never an age of 0."""
    out = {"oldest_section": None, "oldest_section_as_of": None, "oldest_section_age_s": None}
    marks = env.get("source_watermarks")
    if isinstance(marks, (str, bytes, bytearray)):
        try:
            marks = json.loads(marks)
        except (ValueError, TypeError):
            return out
    if not isinstance(marks, dict):
        return out
    product = marks.get("_product")
    oldest = _parse_ts(product.get("oldest_section_as_of")) if isinstance(product, dict) else None
    if oldest is None:
        return out
    out["oldest_section_as_of"] = oldest.astimezone(timezone.utc).isoformat()
    out["oldest_section_age_s"] = max(0, int((now - oldest).total_seconds()))
    for name, mark in marks.items():
        if name != "_product" and isinstance(mark, dict) and _parse_ts(mark.get("as_of")) == oldest:
            out["oldest_section"] = name
            break
    return out


def _meta(env: dict, *, status: str, reason: Any, greyed: bool, now: datetime) -> dict:
    meta = {k: env.get(k) for k in _PRODUCT_FIELDS}
    meta["status"] = status
    meta["reason"] = reason
    meta["greyed"] = greyed
    meta.update(oldest_section(env, now))
    return meta


def serve_cio_pages(*, read_product: Callable | None = None, fetch_row: Callable | None = None, hot=None,
                    now: datetime | None = None) -> dict:
    """The /api/v2/cio/pages response, read from the ``cio.pages`` product. Never builds."""
    if read_product is None:
        from scripts.lib.cc_products.read_path import read_product as _rp

        read_product = _rp
    if fetch_row is None:
        def fetch_row(product_id, scope_key=SCOPE_KEY):  # noqa: ARG001 - no store wired: read as unavailable
            raise StoreUnavailable("no product store configured")

    served_at = now if now is not None else datetime.now(timezone.utc)
    if served_at.tzinfo is None:
        served_at = served_at.replace(tzinfo=timezone.utc)
    try:
        env = read_product(PRODUCT_ID, SCOPE_KEY, fetch_row=fetch_row, hot=hot, now=now)
    except Exception as e:  # noqa: BLE001 - a reader defect is UNKNOWN, never a compute and never a 500
        env = {"status": "UNKNOWN", "reason": f"product store unavailable ({type(e).__name__})", "data": None}
    if not isinstance(env, dict):
        env = {"status": "UNKNOWN", "reason": "product store unavailable", "data": None}

    status = str(env.get("status") or "UNKNOWN")
    reason = env.get("reason")

    if status in ("OK", "STALE"):
        data = _as_dict(env.get("data"))
        if data is not None:
            return {**data, "_product": _meta(env, status=status, reason=reason, greyed=False, now=served_at)}
        status, reason = "UNKNOWN", "stored CIO page record is unreadable"
    elif status == "UNKNOWN":
        last_good = _as_dict(env.get("last_good"))
        if last_good is not None:
            return {**last_good, "_product": _meta(env, status="UNKNOWN", reason=reason, greyed=True, now=served_at)}

    if status == "BUILDING":
        gap = "The CIO page record is being built; no stored copy yet"
    else:
        status = "UNKNOWN"
        gap = f"The CIO page record cannot be read: {reason or 'product store unavailable'}"
    return {**_unavailable(gap), "_product": _meta(env, status=status, reason=reason or gap, greyed=False, now=served_at)}
