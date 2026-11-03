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
    tuples = sorted(
        (h.get("symbol", ""), h.get("account", ""), round(h.get("shares", 0) or 0, 4))
        for h in (doc.get("holdings") or [])
        if (h.get("market_value") or 0) > 100
    )
    # Integrity signature, not a security control; same rule and exact digest as the producer.
    return hashlib.md5(str(tuples).encode()).hexdigest()[:12]  # noqa: S324


#: The accessor's store state -> the reason a consumer publishes for that state.
_STORE_STATE_REASONS = {
    "absent": "holdings_store_absent",
    "empty": "holdings_store_empty",
    "unparseable": "holdings_store_unparseable",
    "unreadable": "holdings_store_unreadable",
    "not_object": "holdings_store_not_an_object",
}


def effective_status(manifest_status: Any, guard: dict[str, Any]) -> str:
    """The status a consumer may publish: never healthy when the store is not."""
    if not guard.get("ok"):
        return str(guard.get("status") or STATUS_UNAVAILABLE)
    return str(manifest_status or "unknown")


def guarded_manifest(state_dir: Path | str, *, now: datetime | None = None) -> dict[str, Any]:
    """The ONE read path for ``_freshness.json``: the manifest with the store guard applied.

    A manifest proves a producer ran; it does not prove the store it describes is readable.
    Every consumer that publishes, displays or acts on freshness reads the manifest through
    here, so a 0-byte/corrupt holdings.json (or a manifest whose hash/clock no longer matches
    it) cannot render FRESH on any surface. The returned document carries the manifest's own
    fields, a guarded ``status`` and the full ``guard`` verdict.

    The manifest is read EXACTLY ONCE and that same parsed document is what the guard validates.
    Reading metadata and then asking the guard to re-read could attach an ok verdict to a
    different (replaced) manifest — a later write would then be published under an earlier
    verdict (cx-openai-4 R2, 2026-11-03).
    """
    sd = Path(state_dir)
    doc: dict[str, Any] = {}
    try:
        text = (sd / "_freshness.json").read_text(encoding="utf-8")
        if text.strip():
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                doc = parsed
    except (OSError, UnicodeError, ValueError):
        doc = {}
    verdict = guard(sd, now=now, manifest_doc=doc or None, manifest_read=True)
    doc["status"] = effective_status(doc.get("status"), verdict)
    doc["guard"] = verdict
    return doc


def guard(
    state_dir: Path | str,
    *,
    now: datetime | None = None,
    manifest_doc: dict[str, Any] | None = None,
    manifest_read: bool = False,
) -> dict[str, Any]:
    """The store guard. ``manifest_read=True`` validates ``manifest_doc`` instead of re-reading.

    A reader that already parsed the manifest (``guarded_manifest``) passes it in, so the verdict and
    the published metadata describe one snapshot. A direct caller keeps the read-once behaviour.
    """
    now = now or datetime.now(timezone.utc)
    sd = Path(state_dir)
    # The store is read through the ONE approved accessor: this module reports the state it found,
    # it does not add a second reader of the file (test_portfolio_price_truth_20261005).
    from lib import portfolio_positions  # noqa: PLC0415 — no import-time work

    store = sd / portfolio_positions.STORE_REL[-1]
    manifest = sd / "_freshness.json"
    reasons: list[str] = []
    out: dict[str, Any] = {
        "schema": SCHEMA, "checked_at": now.isoformat(), "remediation": REMEDIATION,
        "store_path": str(store), "manifest_path": str(manifest),
        "holdings_hash_expected": None, "holdings_hash_observed": None,
    }

    doc, store_state = portfolio_positions.read_store_document(store)
    if doc is None or store_state != "ok":
        reason = _STORE_STATE_REASONS.get(store_state, "holdings_store_unreadable")
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": [reason]}
    rows = doc.get("holdings")
    if not isinstance(rows, list) or not rows:
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_store_has_no_positions"]}
    for row in rows:
        if not isinstance(row, dict):
            return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_row_not_an_object"]}
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            # A row with no identity is not a position. `[{}]` used to pass as a healthy book.
            return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_row_missing_symbol"]}
        account = row.get("account")
        if not isinstance(account, str) or not account.strip():
            # The producer tuple sorts (symbol, account, shares); a non-string account would raise
            # TypeError while sorting, so a wrong-shape store must fail closed here (not crash).
            return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_row_missing_account"]}
        for field in ("market_value", "value", "price", "shares", "qty"):
            if row.get(field) is None:
                continue
            value = row[field]
            # The producer hashes the parsed number (an integer stays an integer); a string or a
            # bool is schema drift, and float(10**400) raises OverflowError. Both are unusable rows.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": [f"holdings_row_non_numeric:{field}"]}
            try:
                numeric = float(value)
            except OverflowError:
                return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": [f"holdings_row_overflow:{field}"]}
            if not math.isfinite(numeric):
                return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": [f"holdings_row_non_finite:{field}"]}
        if row.get("market_value") is None:
            # The binding hash reads the producer's canonical fields. Alias-only rows (qty/value)
            # would hash as no represented positions while passing a looser check, falsely binding
            # a nonempty book to md5('[]') — reject them at this canonical boundary.
            return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_row_missing_canonical_market_value"]}
        if row.get("shares") is None:
            return {**out, "ok": False, "status": STATUS_UNAVAILABLE, "reasons": ["holdings_row_missing_canonical_shares"]}

    try:
        observed = holdings_hash(doc)
    except Exception as exc:  # noqa: BLE001 — a hash/schema failure is unavailable, never a crash or OK
        return {**out, "ok": False, "status": STATUS_UNAVAILABLE,
                "reasons": [f"holdings_hash_uncomputable:{type(exc).__name__}"]}
    out["holdings_hash_observed"] = observed
    if manifest_read:
        # The caller parsed the manifest once; validate THAT document, never a second read.
        fresh = manifest_doc if isinstance(manifest_doc, dict) else None
    else:
        try:
            fresh = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            fresh = None
    if not isinstance(fresh, dict):
        return {**out, "ok": False, "status": STATUS_STALE, "reasons": ["freshness_manifest_absent_or_invalid"]}

    expected = fresh.get("holdings_hash")
    out["holdings_hash_expected"] = expected if isinstance(expected, str) else None
    if not isinstance(expected, str) or not expected.strip():
        # The absence of the match evidence cannot satisfy the manifest-to-store match.
        reasons.append("freshness_manifest_missing_holdings_hash")
    elif expected != observed:
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


__all__ = [
    "SCHEMA",
    "MAX_AGE_HOURS",
    "REMEDIATION",
    "holdings_hash",
    "guard",
    "effective_status",
    "guarded_manifest",
]
