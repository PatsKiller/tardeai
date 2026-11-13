"""Postgres store for precomputed products (LQ-20261107-2595, DSN-20261112-PRECOMPUTE-CACHE §4.2, §5.2).

Every function takes a psycopg2 cursor and leaves the transaction to the caller: nothing here commits, rolls back
or opens a connection. ``try_lock`` takes a transaction-scoped advisory lock, so the caller's connection must be in
a transaction (psycopg2's default, autocommit off) for the lock to outlive the statement.

Production tables come from the phase 0 migration; ``TEST_DDL`` exists only so tests can stand the tables up in an
isolated cluster.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

MAX_BODY_BYTES = 2 * 1024 * 1024

BUILD_OUTCOMES = frozenset({"OK", "UNCHANGED", "FAILED", "TIMEOUT", "REFUSED", "SKIPPED_BUSY"})

COLUMNS = (
    "product_id",
    "scope_key",
    "body",
    "etag",
    "seq",
    "as_of",
    "built_at",
    "next_refresh_at",
    "stale_after_s",
    "hard_expiry_s",
    "purge_after_s",
    "status",
    "source_watermarks",
    "builder_sha",
    "bytes",
    "build_ms",
)

TEST_DDL = """
CREATE TABLE IF NOT EXISTS cc_product_current (
    product_id        text        NOT NULL,
    scope_key         text        NOT NULL,
    body              bytea       NOT NULL,
    etag              text        NOT NULL,
    seq               bigint      NOT NULL,
    as_of             timestamptz NULL,
    built_at          timestamptz NOT NULL,
    next_refresh_at   timestamptz NULL,
    stale_after_s     int         NOT NULL,
    hard_expiry_s     int         NOT NULL,
    purge_after_s     int         NOT NULL,
    status            text        NOT NULL,
    source_watermarks jsonb,
    builder_sha       text,
    bytes             int,
    build_ms          int,
    PRIMARY KEY (product_id, scope_key)
);
CREATE TABLE IF NOT EXISTS cc_product_build_log (
    id          bigserial   PRIMARY KEY,
    product_id  text        NOT NULL,
    scope_key   text        NOT NULL,
    lane        text        NULL,
    started_at  timestamptz,
    finished_at timestamptz,
    outcome     text        NOT NULL,
    build_ms    int,
    peak_rss_kb int,
    bytes       int,
    error       text
);
"""


class BodyTooLarge(ValueError):
    """A product body over the 2 MB cap (DSN §4.4). The build is refused; the last good row stays."""


def etag_for(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _row_to_dict(cur, row) -> dict[str, Any]:
    if isinstance(row, dict):
        out = dict(row)
    else:
        names = [d[0] for d in cur.description]
        out = dict(zip(names, row))
    body = out.get("body")
    if body is not None and not isinstance(body, bytes):
        out["body"] = bytes(body)
    sw = out.get("source_watermarks")
    if isinstance(sw, str):
        out["source_watermarks"] = json.loads(sw)
    return out


_SELECT_SQL = "SELECT " + ", ".join(COLUMNS) + " FROM cc_product_current WHERE product_id = %s AND scope_key = %s"


def read_current(cur, product_id: str, scope_key: str = "global") -> dict | None:
    """One primary-key select. None when no row. Exceptions propagate to the caller."""
    cur.execute(_SELECT_SQL, (product_id, scope_key))
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


_UPSERT_SQL = """
WITH prev AS (
    SELECT etag FROM cc_product_current WHERE product_id = %(product_id)s AND scope_key = %(scope_key)s
)
INSERT INTO cc_product_current (
    product_id, scope_key, body, etag, seq, as_of, built_at, next_refresh_at,
    stale_after_s, hard_expiry_s, purge_after_s, status, source_watermarks, builder_sha, bytes, build_ms
) VALUES (
    %(product_id)s, %(scope_key)s, %(body)s, %(etag)s, 1, %(as_of)s, %(built_at)s, %(next_refresh_at)s,
    %(stale_after_s)s, %(hard_expiry_s)s, %(purge_after_s)s, %(status)s, %(source_watermarks)s::jsonb,
    %(builder_sha)s, %(bytes)s, %(build_ms)s
)
ON CONFLICT (product_id, scope_key) DO UPDATE SET
    built_at          = EXCLUDED.built_at,
    next_refresh_at   = EXCLUDED.next_refresh_at,
    body              = CASE WHEN cc_product_current.etag = EXCLUDED.etag
                             THEN cc_product_current.body ELSE EXCLUDED.body END,
    seq               = CASE WHEN cc_product_current.etag = EXCLUDED.etag
                             THEN cc_product_current.seq ELSE cc_product_current.seq + 1 END,
    as_of             = EXCLUDED.as_of,
    stale_after_s     = EXCLUDED.stale_after_s,
    hard_expiry_s     = EXCLUDED.hard_expiry_s,
    purge_after_s     = EXCLUDED.purge_after_s,
    status            = EXCLUDED.status,
    source_watermarks = EXCLUDED.source_watermarks,
    builder_sha       = CASE WHEN cc_product_current.etag = EXCLUDED.etag
                             THEN cc_product_current.builder_sha ELSE EXCLUDED.builder_sha END,
    bytes             = CASE WHEN cc_product_current.etag = EXCLUDED.etag
                             THEN cc_product_current.bytes ELSE EXCLUDED.bytes END,
    build_ms          = CASE WHEN cc_product_current.etag = EXCLUDED.etag
                             THEN cc_product_current.build_ms ELSE EXCLUDED.build_ms END,
    etag              = EXCLUDED.etag
RETURNING seq, etag, (SELECT etag FROM prev) AS prev_etag
"""


def write_current(
    cur,
    product_id,
    scope_key,
    body: bytes,
    *,
    as_of,
    built_at,
    next_refresh_at,
    stale_after_s,
    hard_expiry_s,
    purge_after_s,
    source_watermarks: dict,
    builder_sha: str,
    build_ms: int,
    status: str = "OK",
) -> dict:
    """One UPSERT. An unchanged body (same etag) moves only built_at and next_refresh_at; seq stays.

    Returns {"changed": bool, "seq": int, "etag": str}. Raises BodyTooLarge before touching the database when
    the body exceeds 2 MB.
    """
    import psycopg2  # local: keeps the module importable without a DB driver for pure-unit callers

    body = bytes(body)
    if len(body) > MAX_BODY_BYTES:
        raise BodyTooLarge(f"{product_id}/{scope_key}: body {len(body)} bytes exceeds cap {MAX_BODY_BYTES}")
    etag = etag_for(body)
    params = {
        "product_id": product_id,
        "scope_key": scope_key,
        "body": psycopg2.Binary(body),
        "etag": etag,
        "as_of": as_of,
        "built_at": built_at,
        "next_refresh_at": next_refresh_at,
        "stale_after_s": int(stale_after_s),
        "hard_expiry_s": int(hard_expiry_s),
        "purge_after_s": int(purge_after_s),
        "status": status,
        "source_watermarks": json.dumps(source_watermarks if source_watermarks is not None else {},
                                        sort_keys=True, default=str),
        "builder_sha": builder_sha,
        "bytes": len(body),
        "build_ms": None if build_ms is None else int(build_ms),
    }
    cur.execute(_UPSERT_SQL, params)
    row = cur.fetchone()
    if isinstance(row, dict):
        seq, new_etag, prev_etag = row["seq"], row["etag"], row["prev_etag"]
    else:
        seq, new_etag, prev_etag = row
    return {"changed": prev_etag != new_etag, "seq": int(seq), "etag": new_etag}


_LOG_SQL = """
INSERT INTO cc_product_build_log
    (product_id, scope_key, lane, started_at, finished_at, outcome, build_ms, peak_rss_kb, bytes, error)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def log_build(
    cur,
    product_id,
    scope_key,
    outcome,
    *,
    started_at,
    finished_at,
    build_ms,
    lane=None,
    peak_rss_kb=None,
    bytes_=None,
    error=None,
) -> None:
    """Append one build-attempt row (the receipt and the measurement, DSN §4.2)."""
    if outcome not in BUILD_OUTCOMES:
        raise ValueError(f"unknown build outcome {outcome!r}; expected one of {sorted(BUILD_OUTCOMES)}")
    cur.execute(
        _LOG_SQL,
        (product_id, scope_key, lane, started_at, finished_at, outcome, build_ms, peak_rss_kb, bytes_, error),
    )


_LOCK_SQL = "SELECT pg_try_advisory_xact_lock(hashtextextended(%s || '|' || %s, 0))"


def try_lock(cur, product_id: str, scope_key: str = "global") -> bool:
    """Single-flight per (product, scope). Never waits. Released at the end of the caller's transaction."""
    cur.execute(_LOCK_SQL, (product_id, scope_key))
    row = cur.fetchone()
    val = next(iter(row.values())) if isinstance(row, dict) else row[0]
    return bool(val)
