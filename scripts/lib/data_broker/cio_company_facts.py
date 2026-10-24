"""Read-only projection of saved CIO InstrumentRecord research, keyed by GUID.

No Watch cache is a company-fact authority. No HTTP reader joins upstream sources.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from scripts.lib.cio_company_facts import missing, public_research, timestamp


def load_snapshot(root: Path | str | None = None, *, records: list[dict] | None = None) -> dict:
    if records is None:
        from scripts.lib.cio_instrument_record import _store_for_root
        records = _store_for_root(root).all()
    grouped: dict[str, list[dict]] = {}
    for r in records:
        if r.get("security_guid"):
            grouped.setdefault(str(r["security_guid"]), []).append(r)
    return {guid: public_research(rs[0], guid) if len(rs) == 1 else {
        "company_facts": missing("", guid, "multiple_cio_records_for_guid"),
        "review_lifecycle": {"status": "MISSING", "missing_reason": "multiple_cio_records_for_guid"}}
            for guid, rs in grouped.items()}


def for_security(snapshot: dict, symbol: str, security_guid: str | None, *, now=None) -> dict:
    out = deepcopy(snapshot.get(str(security_guid)) or {
        "company_facts": missing(symbol, security_guid, "cio_record_missing" if security_guid else "identity_unresolved"),
        "review_lifecycle": {"status": "MISSING", "missing_reason": "cio_record_missing"}})
    catalyst = out["company_facts"].get("catalyst") or {}
    at = timestamp(catalyst.get("published_at")) or timestamp(catalyst.get("observed_at"))
    ref = now or datetime.now(timezone.utc)
    if catalyst.get("status") == "CURRENT" and (not at or not ref - timedelta(days=30) <= at <= ref):
        catalyst.update(status="STALE", missing_reason="catalyst_outside_30_day_window")
    return out
