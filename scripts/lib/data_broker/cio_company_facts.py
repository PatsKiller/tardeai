"""Read-only projection of saved CIO InstrumentRecord research, keyed by GUID.

No Watch cache is a company-fact authority. No HTTP reader joins upstream sources.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from scripts.lib.cio_company_facts import missing, public_research, timestamp
from scripts.lib import cio_company_quality as quality


def load_snapshot(root: Path | str | None = None, *, records: list[dict] | None = None) -> dict:
    if records is None:
        from scripts.lib.cio_instrument_record import _store_for_root
        records = _store_for_root(root).all()
    from scripts.lib.cio_instrument_record import select_canonical_record
    grouped: dict[str, list[dict]] = {}
    for r in records:
        if r.get("security_guid"):
            grouped.setdefault(str(r["security_guid"]), []).append(r)
    out: dict[str, dict] = {}
    for guid, rs in grouped.items():
        canonical, violation = select_canonical_record(rs)
        if violation:
            out[guid] = {
                "company_facts": missing("", guid, violation),
                "review_lifecycle": {"status": "MISSING", "missing_reason": violation},
            }
            continue
        out[guid] = public_research(_with_facts_fallback(canonical, rs, guid), guid)
    return out


def _with_facts_fallback(canonical: dict, records: list[dict], guid: str) -> dict:
    """Render company facts even when the canonical (judged prospect) record lacks them.

    The fact-only SECURITY record is the designed home of ``research.company_facts``
    (2026-10-24 design). If the canonical record carries no facts but a sibling fact-only
    record does, surface the sibling's facts instead of silently dropping them.
    """
    if _public_facts_status(public_research(canonical, guid)) != "MISSING":
        return canonical
    for r in records:
        if r is canonical:
            continue
        sibling = public_research(r, guid)
        if _public_facts_status(sibling) != "MISSING":
            merged = dict(canonical)
            merged["research"] = {
                **(canonical.get("research") or {}),
                "company_facts": sibling["company_facts"],
            }
            return merged
    return canonical


def _public_facts_status(rendered: dict) -> str | None:
    return ((rendered or {}).get("company_facts") or {}).get("status")


def for_security(snapshot: dict, symbol: str, security_guid: str | None, *, now=None) -> dict:
    out = deepcopy(snapshot.get(str(security_guid)) or {
        "company_facts": missing(symbol, security_guid, "cio_record_missing" if security_guid else "identity_unresolved"),
        "review_lifecycle": {"status": "MISSING", "missing_reason": "cio_record_missing"}})
    facts = out["company_facts"]
    catalyst = facts.get("catalyst") or {}
    ref = now or datetime.now(timezone.utc)
    _legacy_quality(facts, symbol)
    if catalyst.get("status") == "CURRENT" and catalyst.get("catalyst_class") == quality.UPCOMING:
        # A scheduled event is current until its date passes, not for 30 days after it was published.
        when = quality.parse_when(catalyst.get("event_at"))
        if not when or when.date() < ref.date():
            catalyst.update(status="STALE", missing_reason="scheduled_event_date_passed")
        return out
    at = timestamp(catalyst.get("published_at")) or timestamp(catalyst.get("observed_at"))
    if catalyst.get("status") == "CURRENT" and (not at or not ref - timedelta(days=30) <= at <= ref):
        catalyst.update(status="STALE", missing_reason="catalyst_outside_30_day_window")
    return out


def _legacy_quality(facts: dict, symbol: str) -> None:
    """Records written before the C1 quality rules carry no display name, date or class. The read projection
    applies the same reviewed rules to what is stored (no new evidence, no provider): a display name derived
    from the stored registered name/description, the stored event's own date, and a stored non-catalyst
    (price prediction, insider trade ...) shown as None on file until the next populate pass rewrites it."""
    company = facts.get("company")
    if isinstance(company, dict) and company.get("value") and not company.get("display_name"):
        company.update(quality.display_name(symbol or str(facts.get("symbol") or ""), company.get("value"),
                                            description=(facts.get("description") or {}).get("value")))
    cat = facts.get("catalyst")
    if not isinstance(cat, dict) or cat.get("status") != "CURRENT" or cat.get("catalyst_class"):
        return
    names = [n for n in ((company or {}).get("display_name"), (company or {}).get("value")) if n]
    verdict = quality.classify(cat, symbol=symbol or str(facts.get("symbol") or ""), names=names)
    day, kind = quality.fact_date(cat)
    cat.update(date=day, date_kind=kind, source_label=quality.source_label(cat))
    if verdict["class"] == quality.NEWS:
        facts.setdefault("recent_news", [{"headline": cat.get("headline"), "date": day, "date_kind": kind,
                                          "source_label": cat.get("source_label"), "feed": cat.get("feed"),
                                          "url": cat.get("url"), "not_catalyst_reason": verdict["reason"]}])
        cat.update(status="NONE_ON_FILE", headline=None, missing_reason="stored_catalyst_fails_quality_rules",
                   reason=f"Stored headline is news, not a catalyst ({str(verdict['reason']).replace('_', ' ')}).")
    else:
        cat.update(catalyst_class=verdict["class"], event_type=verdict["event_type"])
