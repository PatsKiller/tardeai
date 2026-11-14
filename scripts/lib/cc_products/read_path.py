"""Product read path: hot tier, then the Postgres stored copy, then an envelope (DSN §6.1, LQ-20261107-2595).

This module never computes a product and never imports a builder. It reads stored bytes, parses them with
``json.loads`` and stamps them with the product's clocks. A hot-tier outage falls back to Postgres. The two boundary
arms answer UNKNOWN with **different reasons** (F1, REL2 unknown-reads): a Postgres failure answers
``STORE_UNAVAILABLE`` ("product store unavailable"), and a read over ``budget_ms`` answers
``READ_BUDGET_EXCEEDED`` ("read budget exceeded (<elapsed> ms > <budget> ms)", elapsed to 0.1 ms so it can never
print two equal numbers). Every envelope also carries ``read_ms`` (elapsed since the call began, 0.1 ms) and ``tier``
(the tier that answered, qualified by a hot-tier failure that pushed the read to Postgres), so one log line names the
arm and its duration. On the budget arm the Postgres row *did* answer, so the tier says so: ``pg(over-budget)``.

``budget_ms`` is checked after the Postgres read returns; it does not interrupt a running query. Bound the real wait
inside ``fetch_row`` (for example ``SET LOCAL statement_timeout``).

The read path never writes the hot tier (rework 2026-11-13, blocker 3). Only the builder sets the hot key, after its
Postgres commit and while it still holds the host flock for (product, scope), so a slow reader can never overwrite a
newer row with the older one it fetched.

Schema compatibility: ``schema_version`` is the body schema this reader understands. The hot key carries it, and a
Postgres row with a different ``schema_version`` is rejected as UNKNOWN "incompatible schema_version" with no data and
no last good: an incompatible body is never parsed or served, and there is no fallback to a legacy path.
"""

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone

from scripts.lib.cc_products.hot_tier import HotTier, HotTierDown, product_key, unpack

STORE_UNAVAILABLE = "product store unavailable"
# F1 (REL2 unknown-reads): the budget arm used to answer with STORE_UNAVAILABLE too, so a log line could not tell a
# store failure from a slow read. The counter names already differed (store_unavailable / budget_exceeded); the
# reason now does as well. Status and counters are unchanged.
READ_BUDGET_EXCEEDED = "read budget exceeded"

# ``tier`` values on the envelope: which tier answered, qualified by tags in parentheses — a hot-tier failure that
# pushed the read to Postgres ("pg(hot-down)", "pg(hot-bad)"), or a Postgres row that answered but was discarded for
# being over budget ("pg(over-budget)"). A hot miss is the ordinary cold path and is not qualified. "none" is reserved
# for no stored body at all (store down, BUILDING).
TIER_HOT = "hot"
TIER_PG = "pg"
TIER_NONE = "none"
TIER_OVER_BUDGET = "over-budget"

# The read clock. A module-level seam so a test can pin the reported elapsed exactly (F1 r2, N3); product code never
# replaces it.
_now_s = time.monotonic

READ_COUNTERS: dict[str, int] = {
    "OK": 0,
    "STALE": 0,
    "UNKNOWN": 0,
    "BUILDING": 0,
    "hot_hit": 0,
    "hot_miss": 0,
    "hot_down": 0,
    "hot_bad_entry": 0,
    "incompatible_schema": 0,
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


# LQ-3140: keep equal to product_builder.FUTURE_CLOCK_SKEW_S (a test pins it); not imported, the reader stays light.
FUTURE_CLOCK_SKEW_S = 120


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _aware(v):
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    if isinstance(v, datetime) and v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v


def _tier_for(base: str, hot_state: str, *tags: str) -> str:
    """The tier that answered, qualified by every tag that applies.

    ``hot_state`` is ``hit`` / ``miss`` / ``down`` / ``bad`` / ``off`` (no hot tier configured). Only ``down`` and
    ``bad`` qualify the value: a miss is the ordinary cold path, so it prints plain ``pg``. Extra tags (for example
    ``over-budget``) are joined in the same parentheses, comma-separated in the order given.
    """
    all_tags = [t for t in ((f"hot-{hot_state}" if hot_state in ("down", "bad") else None),) + tags if t]
    return f"{base}({','.join(all_tags)})" if all_tags else base


def _envelope(product_id, scope_key, status, *, row=None, age_s=None, reason=None, data=None, last_good=None,
              served_from=None, read_ms=None, tier=None) -> dict:
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
        # F1 (REL2 unknown-reads): how long the read took and which tier answered. Free to carry here and the only
        # fields that tell the two boundary arms apart once the reason string has been logged.
        "read_ms": read_ms,
        "tier": tier,
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
                 now: datetime | None = None, budget_ms: int = 250, schema_version: int = 1) -> dict:
    t0 = _now_s()

    def _read_ms() -> float:
        """Elapsed since the call began, in ms to 0.1. The clock starts before the hot GET, so it also covers a cold
        connect; the budget arm reports its own raw elapsed value (F1)."""
        return round((_now_s() - t0) * 1000.0, 1)

    now = _aware(now) if now is not None else datetime.now(timezone.utc)
    key = product_key(product_id, scope_key, schema_version)

    row = None
    served_from = None
    tier = TIER_NONE
    hot_state = "off"
    if hot is not None:
        hot_state = "miss"
        try:
            raw = hot.get(key)
        except HotTierDown:
            _count("hot_down")
            raw = None
            hot_state = "down"
        else:
            _count("hot_hit" if raw is not None else "hot_miss")
        if raw is not None:
            try:
                row = unpack(raw)
                served_from = "hot"
                tier = TIER_HOT
            except Exception:  # noqa: BLE001 - a corrupt cache entry is a miss, never an error
                _count("hot_bad_entry")
                row = None
                hot_state = "bad"

    if row is None:
        try:
            row = fetch_row(product_id, scope_key)
        except Exception:  # noqa: BLE001 - the store being unavailable is an answer, not a crash
            _count("store_unavailable")
            _count("UNKNOWN")
            return _envelope(product_id, scope_key, "UNKNOWN", reason=STORE_UNAVAILABLE,
                             read_ms=_read_ms(), tier=_tier_for(TIER_NONE, hot_state))
        elapsed_ms = (_now_s() - t0) * 1000.0
        if elapsed_ms > budget_ms:
            _count("budget_exceeded")
            _count("UNKNOWN")
            # N3 (F1 r2): elapsed prints to 0.1 ms, so the reason can never read "250 ms > 250 ms" — the window a
            # read that hits the store's own statement_timeout lands in. N2: Postgres did return the row, so the
            # tier names it and the over-budget tag says why it was not served.
            return _envelope(product_id, scope_key, "UNKNOWN",
                             reason=f"{READ_BUDGET_EXCEEDED} ({elapsed_ms:.1f} ms > {budget_ms} ms)",
                             read_ms=round(elapsed_ms, 1),
                             tier=_tier_for(TIER_PG, hot_state, TIER_OVER_BUDGET))
        if row is None:
            _count("pg_miss")
            _count("BUILDING")
            return _envelope(product_id, scope_key, "BUILDING", reason="not built yet",
                             read_ms=_read_ms(), tier=_tier_for(TIER_NONE, hot_state))
        _count("pg_hit")
        served_from = "pg"
        tier = _tier_for(TIER_PG, hot_state)

    age = _age_seconds(row, now)
    age_s = None if math.isinf(age) else int(age)
    hard = row.get("hard_expiry_s")
    stale = row.get("stale_after_s")

    # The column is NOT NULL DEFAULT 1; a row without the field is a v1 row.
    row_schema = row.get("schema_version")
    row_schema = 1 if row_schema is None else row_schema
    if row_schema != schema_version:
        _count("incompatible_schema")
        _count("UNKNOWN")
        return _envelope(product_id, scope_key, "UNKNOWN", row={**row, "body": None}, age_s=age_s,
                         reason=f"incompatible schema_version {row_schema} (reader expects {schema_version})",
                         served_from=served_from, read_ms=_read_ms(), tier=tier)

    try:
        body = row.get("body")
        parsed = json.loads(bytes(body)) if body is not None else None
    except (ValueError, TypeError):
        _count("body_unreadable")
        _count("UNKNOWN")
        return _envelope(product_id, scope_key, "UNKNOWN", row=row, age_s=age_s, reason="product body unreadable",
                         served_from=served_from, read_ms=_read_ms(), tier=tier)

    # LQ-3140: an as_of ahead of now by more than the skew allowance is a bad clock. The age is clamped to 0 (never
    # negative), but such a row must not read as fresh: UNKNOWN, last good kept, the reason names the clock.
    ref_clock = _aware(row.get("as_of"))
    if ref_clock is not None and (ref_clock - now).total_seconds() > FUTURE_CLOCK_SKEW_S:
        _count("future_clock")
        _count("UNKNOWN")
        return _envelope(product_id, scope_key, "UNKNOWN", row=row, age_s=age_s,
                         reason=f"source clock is in the future ({_iso(ref_clock)}); last good {_iso(row.get('built_at'))}",
                         data=None, last_good=parsed, served_from=served_from, read_ms=_read_ms(), tier=tier)
    if hard is None or age > hard:
        _count("UNKNOWN")
        return _envelope(product_id, scope_key, "UNKNOWN", row=row, age_s=age_s,
                         reason=f"past hard expiry; last good {_iso(row.get('built_at'))}",
                         data=None, last_good=parsed, served_from=served_from, read_ms=_read_ms(), tier=tier)
    if stale is None or age > stale:
        _count("STALE")
        return _envelope(product_id, scope_key, "STALE", row=row, age_s=age_s,
                         reason=f"stale: age {age_s}s past stale_after {stale}s", data=parsed,
                         served_from=served_from, read_ms=_read_ms(), tier=tier)
    _count("OK")
    return _envelope(product_id, scope_key, "OK", row=row, age_s=age_s, data=parsed, served_from=served_from,
                     read_ms=_read_ms(), tier=tier)
