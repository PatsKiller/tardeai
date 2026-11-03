"""Fail-closed guard for the authoritative holdings store.

A freshness manifest proves a producer ran; it does not prove the file it describes
is still the file on disk. The 2026-11-03 incident: holdings.json was 0 bytes while
_freshness.json still said FRESH with an old holdings hash, and consumers rendered
healthy. This guard reads the AUTHORITATIVE store itself and refuses to let cached
metadata report health when the payload is absent, empty, unparseable, empty of
positions, non-finite, or when the metadata's hash/clock no longer matches it.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "AuthoritativeStoreGuard@v1"
STATUS_OK = "OK"
STATUS_STALE = "STALE"
STATUS_UNAVAILABLE = "UNAVAILABLE"
MAX_AGE_HOURS = 36.0
FUTURE_TOLERANCE = timedelta(minutes=5)
REMEDIATION = "/ops#holdings-recovery"


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        value = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def holdings_hash(doc: dict[str, Any]) -> str:
    """Same rule the orchestrator writes (portfolio_orchestrator.py:1191-1204)."""
    rows = doc.get("holdings") or doc.get("positions") or []
    tuples = sorted(
        (str(r.get("symbol") or ""), str(r.get("account") or ""), round(float(r.get("shares") or 0), 4))
        for r in rows
        if isinstance(r, dict) and float(r.get("market_value") or 0) > 100
    )
    return hashlib.md5(str(tuples).encode()).hexdigest()[:12]


def effective_status(manifest_status: Any, guard: dict[str, Any]) -> str:
    """The status a consumer may publish: never healthy when the store is not."""
    if not guard.get("ok"):
        return str(guard.get("status") or STATUS_UNAVAILABLE)
    return str(manifest_status or "unknown")


def guard(state_dir: Path | str, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    sd = Path(state_dir)
    store, manifest = sd / "holdings.json", sd / "_freshness.json"
    reasons: list[str] = []
    out: dict[str, Any] = {
        "schema": SCHEMA, "checked_at": now.isoformat(), "remediation": REMEDIATION,
        "store_path": str(store), "manifest_path": str(manifest),
        "holdings_hash_expected": None, "holdings_hash_observed": None,
    }

    raw = b""
    try:
        raw = store.read_bytes()
    except FileNotFoundError:
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_store_absent"]}
    except OSError as exc:
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": [f"holdings_store_unreadable:{type(exc).__name__}"]}
    if not raw.strip():
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_store_empty"]}
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": [f"holdings_store_unparseable:{type(exc).__name__}"]}
    if not isinstance(doc, dict):
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_store_not_an_object"]}
    rows = doc.get("holdings") or doc.get("positions")
    if not isinstance(rows, list) or not rows:
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_store_has_no_positions"]}
    for row in rows:
        if not isinstance(row, dict):
            return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_row_not_an_object"]}
        for field in ("market_value", "value", "price", "shares", "qty"):
            if row.get(field) is None:
                continue
            try:
                numeric = float(row[field])
            except (TypeError, ValueError):
                return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": [f"holdings_row_non_numeric:{field}"]}
            if not math.isfinite(numeric):
                return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": [f"holdings_row_non_finite:{field}"]}

    observed = holdings_hash(doc)
    out["holdings_hash_observed"] = observed
    try:
        fresh = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        fresh = None
    if not isinstance(fresh, dict):
        return {**out, "ok": False, "status": STATUS_STALE, "reasons": ["freshness_manifest_absent_or_invalid"]}

    expected = fresh.get("holdings_hash")
    out["holdings_hash_expected"] = expected if isinstance(expected, str) else None
    if isinstance(expected, str) and expected and expected != observed:
        reasons.append("holdings_hash_mismatch")
    completed = _parse(fresh.get("completed_at"))
    if completed is None:
        reasons.append("freshness_clock_missing")
    else:
        if completed > now + FUTURE_TOLERANCE:
            reasons.append("freshness_clock_in_the_future")
        elif now - completed > timedelta(hours=MAX_AGE_HOURS):
            reasons.append("freshness_clock_too_old")
        data_clock = _parse(doc.get("as_of")) or _parse(doc.get("data_as_of"))
        if data_clock and data_clock > completed + FUTURE_TOLERANCE:
            reasons.append("freshness_predates_store_data")
    if reasons:
        return {**out, "ok": False, "status": STATUS_STALE, "reasons": reasons}
    return {**out, "ok": True, "status": STATUS_OK, "reasons": []}


__all__ = ["SCHEMA", "MAX_AGE_HOURS", "REMEDIATION", "holdings_hash", "guard", "effective_status"]
