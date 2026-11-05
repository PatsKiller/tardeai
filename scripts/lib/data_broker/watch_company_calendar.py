"""Read stored house calendar fields only; never fetch, regenerate or read a plan."""

from datetime import datetime, timedelta, timezone
import re


def snapshot(root, symbols):
    from scripts.lib.prospectus.store import base_dir, read_prospectus

    out = {}
    for symbol in symbols:
        doc = read_prospectus(base_dir(root), symbol)
        calendar = (doc or {}).get("blocks", {}).get("catalyst_calendar")
        if not isinstance(calendar, dict):
            out[symbol] = {"status": "MISSING", "reason": "house_calendar_not_produced"}
            continue
        out[symbol] = {
            "status": "STORED",
            "symbol": doc.get("symbol"),
            "name": doc.get("name"),
            "security_guid": doc.get("security_guid"),
            "version": doc.get("version"),
            "observed_at": calendar.get("source_observed_at"),
            "report_generated_at": doc.get("generated_at"),
            "forward": calendar.get("forward") or [],
        }
    return out


def _name(value):
    return " ".join(
        w
        for w in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if w not in {"inc", "corp", "corporation", "incorporated", "ltd", "limited", "plc", "co"}
    )


def facts_for(doc, symbol, guid, company, *, now):
    if doc.get("status") != "STORED":
        return [], doc.get("reason") or "house_calendar_not_produced"
    names = {_name(company.get(k)) for k in ("value", "display_name", "legal_name") if company.get(k)}
    if doc.get("symbol") != symbol or (doc.get("security_guid") and doc["security_guid"] != guid):
        return [], "calendar_identity_mismatch"
    if not doc.get("security_guid") and (not _name(doc.get("name")) or _name(doc["name"]) not in names):
        return [], "calendar_company_identity_unverified"
    from scripts.lib.cio_company_quality import rules

    out, gap = [], None
    for event in doc.get("forward") or []:
        if event.get("kind") not in {"earnings", "ex_dividend"}:
            continue  # macro events are market context, not company catalysts
        observed_raw = event.get("source_observed_at") or doc.get("observed_at")
        try:
            observed = datetime.fromisoformat(str(observed_raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            gap = "calendar_source_time_unavailable"
            continue
        if observed.tzinfo is None or observed > now:
            gap = "calendar_source_time_unavailable"
            continue
        if now - observed > timedelta(days=rules()["catalyst"]["scheduled_source_max_age_days"]):
            gap = "calendar_source_stale"
            continue
        try:
            at = datetime.fromisoformat(str(event.get("date")).replace("Z", "+00:00"))
            at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
        except (ValueError, TypeError):
            continue
        if at.date() < now.date() or not event.get("source"):
            continue
        out.append(
            {
                "headline": f"{company.get('display_name') or company.get('value')} — {event.get('label') or event['kind']} · {event['date']}",
                "source": event["source"],
                "producer_source": "stored_prospectus_calendar",
                "source_ref": f"prospectus:{symbol}:{doc.get('version') or 'version_unknown'}",
                "observed_at": observed_raw,
                "event_at": event["date"],
                "catalyst_type": event["kind"],
                "event_type": event["kind"],
                "estimated": bool(event.get("estimated") or "estimated" in str(event.get("label")).lower()),
            }
        )
    return out, gap
