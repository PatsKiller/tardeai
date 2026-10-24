"""Batch company evidence folded into InstrumentRecord.research (no provider calls).

This is an InstrumentRecord extension, not a second store or a Watch writer.
Original source clocks remain distinct from assembly/write clocks. Source verification
claims are carried as claims; relevance/confidence is never turned into a probability.
"""
from __future__ import annotations

from copy import deepcopy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

SCHEMA = "CIOCompanyFacts@v1"
FIELDS = ("company", "description", "sector", "industry")
REVIEW_FIELDS = ("status", "request_id", "requested_at", "started_at", "completed_at", "updated_at",
                 "created_at", "researching_at", "answered_at", "conflict_resolved_at", "conflict_id",
                 "research_id", "old_stance", "new_stance", "reason", "evidence_refs")


def timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Do not invent an offset for undocumented naive clocks.
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError, ValueError):
        return None


def iso(value: Any) -> str | None:
    d = timestamp(value)
    return d.isoformat() if d else None


def confirmed(identity: dict) -> bool:
    try:
        return identity.get("identity_status") == "CONFIRMED" and bool(UUID(str(identity.get("security_guid"))))
    except (ValueError, TypeError, AttributeError):
        return False


def missing(symbol: str, guid: str | None, reason: str) -> dict:
    return {"schema": SCHEMA, "symbol": symbol, "security_guid": guid, "status": "MISSING",
            "missing_reason": reason, **{k: {"value": None, "source": None, "observed_at": None,
                                            "missing_reason": reason} for k in FIELDS},
            "catalyst": {"headline": None, "status": "MISSING", "missing_reason": reason}, "conflicts": []}


def collect_inputs(root: Path, symbols: list[str], *, db_query=None, now: datetime) -> dict:
    """Two bulk stored-source reads per pass, never a per-page/per-symbol fetch."""
    from scripts.lib.data_broker.finviz_enrichment_snapshot import get_enrichment_batch
    from scripts.lib.data_broker.symbol_profile import get_symbol_profiles
    profiles, errors = {}, []
    if db_query is not None:
        try:
            profiles = get_symbol_profiles(db_query, symbols)
        except Exception as exc:  # caller receives the source gap
            errors.append(f"symbol_profiles:{type(exc).__name__}")
    else:
        errors.append("symbol_profiles:not_read_no_db")
    finviz = get_enrichment_batch(symbols, root=root, now=now)
    # Raw saved profiles only: do not call upgrade/build_profile (those mint clocks).
    identity_profiles = {}
    path = Path(root) / "data/cio/ticker_research_graph.jsonl"
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("schema") == "TickerKnowledgeProfile@v1" and r.get("symbol") in symbols:
                    identity_profiles[r["symbol"]] = r
    except FileNotFoundError:
        pass
    except OSError as exc:
        errors.append(f"identity_profile:{type(exc).__name__}")
    return {"identity_profiles": identity_profiles, "profiles": profiles, "finviz": finviz.get("symbols") or {}, "errors": errors}


def assemble(symbol: str, identity: dict, inputs: dict, *, catalyst: dict | None = None,
             prior: dict | None = None, now: datetime) -> dict:
    """GUID-bound facts only; no stance, ranking, account or trading judgment."""
    guid = identity.get("security_guid")
    if not confirmed(identity):
        return missing(symbol, guid, "identity_not_confirmed")
    prior = prior if (prior or {}).get("security_guid") == guid else {}
    out = missing(symbol, guid, "not_on_file")
    out.update(status="AVAILABLE", assembled_at=now.isoformat(), source_errors=list(inputs.get("errors") or []))
    profile = (inputs.get("profiles") or {}).get(symbol) or {}
    fv = (inputs.get("finviz") or {}).get(symbol) or {}
    rec = fv.get("record") or {}
    identity_profile = (inputs.get("identity_profiles") or {}).get(symbol) or {}
    sources = [
        (identity_profile, "ticker_research_graph.profile", iso(identity_profile.get("updated_at")), "profile_updated_at"),
        (profile, "symbol_profiles", iso(profile.get("updated_at")), "row_updated_at"),
        (rec, "finviz_enrichment", fv.get("as_of"), "cached_at"),
    ]
    conflicts = []
    for key in FIELDS:
        candidates = []
        for data, source, at, clock in sources:
            if data.get("security_guid") and data["security_guid"] != guid:
                conflicts.append({"field": key, "source": source, "reason": "source_guid_mismatch"})
                continue
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            candidates.append({"value": " ".join(value.split())[:1200], "source": source,
                               "observed_at": at, "clock_kind": clock, "missing_reason": None,
                               "identity_binding": "confirmed_registry_symbol_at_batch",
                               "source_identity": "guid_keyed" if data.get("security_guid") else "symbol_keyed",
                               "source_time_raw": str(data.get("updated_at") or data.get("cached_at") or "") or None,
                               "producer_source": data.get("source")})
        old = prior.get(key) or {}
        if old.get("value"):
            candidates.append(deepcopy(old))
        # A newly read undated value cannot displace an already dated fact.
        candidates.sort(key=lambda f: timestamp(f.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc),
                        reverse=True)
        if candidates:
            out[key] = candidates[0]
            if not out[key].get("observed_at"):
                out[key]["missing_reason"] = "source_observation_time_unavailable"
            if len({str(c["value"]).casefold() for c in candidates}) > 1:
                conflicts.append({"field": key, "reason": "source_values_disagree", "values": candidates})
    cutoff = now - timedelta(days=30)
    facts = list((catalyst or {}).get("facts") or [])
    old_cat = prior.get("catalyst") or {}
    if old_cat.get("headline"):
        facts.append(deepcopy(old_cat))
    eligible = []
    for f in facts:
        if f.get("subject_guid") and str(f["subject_guid"]) != str(guid):
            conflicts.append({"field": "catalyst", "reason": "source_guid_mismatch", "source": f.get("source")})
            continue
        headline = str(f.get("headline") or "").strip()
        if not headline or str(f.get("catalyst_type") or "").lower() in ("none", "no_clear_catalyst"):
            continue
        at = timestamp(f.get("published_at")) or timestamp(f.get("observed_at"))
        if at and cutoff <= at <= now:
            eligible.append(f)
    eligible.sort(key=lambda f: timestamp(f.get("published_at")) or timestamp(f.get("observed_at")), reverse=True)
    if eligible:
        f = eligible[0]
        out["catalyst"] = {k: f.get(k) for k in ("headline", "source", "feed", "published_at", "observed_at",
                                                     "url", "catalyst_type", "verification_basis",
                                                     "factual_verification_status")}
        out["catalyst"].update(status="CURRENT", missing_reason=None, source_verified_claim=bool(
            f.get("source_verified_claim", f.get("verified"))), independent_verification="NOT_MEASURED")
    else:
        out["catalyst"]["missing_reason"] = "no_dated_current_catalyst_on_file"
    out["conflicts"] = conflicts
    out["missing_reason"] = None
    if prior and {k: v for k, v in prior.items() if k != "assembled_at"} == {
            k: v for k, v in out.items() if k != "assembled_at"}:
        return deepcopy(prior)
    return out


def public_research(record: dict, guid: str | None) -> dict:
    """One shared, typed consumer shape; never leaks arbitrary private research keys."""
    if not guid or str(record.get("security_guid")) != str(guid):
        return {"company_facts": missing(str(record.get("symbol") or ""), guid, "record_guid_mismatch"),
                "review_lifecycle": {"status": "MISSING", "missing_reason": "record_guid_mismatch"}}
    research = record.get("research") or {}
    facts = research.get("company_facts") or {}
    if facts.get("schema") != SCHEMA or str(facts.get("security_guid")) != str(guid):
        facts = missing(str(record.get("symbol") or ""), guid, "company_facts_not_on_cio_record")
    review = research.get("review_lifecycle")
    review = {k: deepcopy(review[k]) for k in REVIEW_FIELDS if k in review} if isinstance(review, dict) else {
        "status": "MISSING", "missing_reason": "review_lifecycle_not_on_cio_record"}
    return {"company_facts": deepcopy(facts), "review_lifecycle": review}


def persist_company_facts(root: Path, prospects: list[dict], *, write: bool = False,
                          backend=None, registry=None, env=None) -> dict:
    """Use the existing prospect facade, merging only this extension into latest records.

    Not called by HTTP readers or --write-shadow. Explicit batch opt-in required.
    No prospect stance/conviction from a shadow proposal is promoted by this pass.
    """
    from scripts.lib.cio_instrument_record import InstrumentRecordStore, DEFAULT_PATH, apply_prospect, is_prospect_record, ProspectInvalid, BehaviorWriteRefused
    store = InstrumentRecordStore(Path(root) / DEFAULT_PATH)
    records = store.all()
    by_guid: dict[str, list[dict]] = {}
    for r in records:
        by_guid.setdefault(str(r.get("security_guid") or ""), []).append(r)
    result = {"mode": "write" if write else "dry_run", "written": 0, "would_write": 0, "gaps": [], "pg": [],
              "consumer_sync": "NOT_REQUESTED" if not write else "NOT_MEASURED"}
    for p in prospects:
        guid = str(p.get("security_guid") or "")
        facts = (p.get("research") or {}).get("company_facts") or {}
        if not guid or facts.get("security_guid") != guid or facts.get("schema") != SCHEMA:
            result["gaps"].append({"symbol": p.get("symbol"), "reason": "invalid_fact_identity"})
            continue
        matches = by_guid.get(guid) or []
        # Never mint a second canonical record or choose among contradictory heads.
        if len(matches) != 1:
            result["gaps"].append({"symbol": p.get("symbol"), "security_guid": guid,
                                   "reason": "cio_record_missing" if not matches else "multiple_cio_records_for_guid"})
            continue
        rec = deepcopy(matches[0])
        if not is_prospect_record(rec):
            result["gaps"].append({"symbol": p.get("symbol"), "security_guid": guid,
                                   "reason": "legacy_record_needs_cio_promotion"})
            continue
        research = deepcopy(rec.get("research") or {})
        if research.get("company_facts") == facts:
            continue
        research["company_facts"] = deepcopy(facts)
        try:
            rec, _ = apply_prospect(rec, prospect={"research": research})
        except (ProspectInvalid, BehaviorWriteRefused) as exc:
            result["gaps"].append({"symbol": p.get("symbol"), "security_guid": guid,
                                   "reason": f"record_validation_failed:{type(exc).__name__}"})
            continue
        result["would_write"] += 1
        if write:
            receipt = store.upsert_prospect(rec, backend=backend, registry=registry, env=env)
            result["written"] += 1
            pg = deepcopy(receipt["pg"])
            if pg.get("error"):
                pg["error"] = str(pg["error"]).split(":", 1)[0]  # no connection/SQL details in reports
            result["pg"].append({"security_guid": guid, **pg})
    if write:
        result["consumer_sync"] = "FAILED" if any(p.get("ok") is False for p in result["pg"]) else (
            "INERT" if any(p.get("mode") == "inert" for p in result["pg"]) else (
                "DUAL_WRITE_ACKNOWLEDGED" if result["pg"] else "NOT_MEASURED_NO_CHANGE"))
    result["ok"] = not result["gaps"] and result["consumer_sync"] not in ("FAILED", "INERT")
    return result
