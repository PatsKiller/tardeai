"""Batch company evidence folded into InstrumentRecord.research (no provider calls).

This is an InstrumentRecord extension, not a second store or a Watch writer.
Original source clocks remain distinct from assembly/write clocks. Source verification
claims are carried as claims; relevance/confidence is never turned into a probability.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

SCHEMA = "CIOCompanyFacts@v1"
FIELDS = ("company", "description", "sector", "industry")
REVIEW_FIELDS = (
    "status",
    "request_id",
    "requested_at",
    "started_at",
    "completed_at",
    "updated_at",
    "created_at",
    "researching_at",
    "answered_at",
    "conflict_resolved_at",
    "conflict_id",
    "research_id",
    "old_stance",
    "new_stance",
    "reason",
    "evidence_refs",
)


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
    return {
        "schema": SCHEMA,
        "symbol": symbol,
        "security_guid": guid,
        "status": "MISSING",
        "missing_reason": reason,
        **{k: {"value": None, "source": None, "observed_at": None, "missing_reason": reason} for k in FIELDS},
        "catalyst": {"headline": None, "status": "MISSING", "missing_reason": reason},
        "conflicts": [],
    }


# A company label is a registered name, never its business-description prose.
COMPANY_NAME_MAX_CHARS = 180


def company_name_issue(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "company_name_not_on_file"
    text = " ".join(value.split())
    if len(text) > COMPANY_NAME_MAX_CHARS:
        return "company_name_too_long"
    if re.search(r"[,;]\s*(?:together\b|which\b|through\b|a\s|an\s)", text, re.I) or re.search(
        r"\b(?:together with|its subsidiaries|is a |is an |develops |manufactures |provides |operates |specializes in )",
        text,
        re.I,
    ):
        return "company_name_is_description"
    if re.search(r"\b(?:Inc|Corp|Ltd|Co)\.\s+(?:It|They|Its|This|The company)\b", text, re.I):
        return "company_name_multiple_sentences"
    # Legal abbreviations/initials are allowed; a following sentence is not.
    without_abbreviations = re.sub(r"\b(?:Inc|Corp|Ltd|Co|S\.A|N\.V|S\.p\.A)\.", "", text, flags=re.I)
    without_abbreviations = re.sub(r"\b[A-Z]\.", "", without_abbreviations)
    if re.search(r"[.!?]\s+\S", without_abbreviations) or "\n" in value or "\r" in value:
        return "company_name_multiple_sentences"
    return None


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
    # AGENTS company-name source: the already stored instrument description.
    # Read the actual file, not load()'s empty_evidence() which mints a clock.
    names = {}
    name_path = Path(root) / "data/runtime/schwab_instrument_evidence.json"
    try:
        doc = json.loads(name_path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("schema") == "SchwabInstrumentEvidence@v1":
            for sym in symbols:
                entry = (doc.get("instruments") or {}).get(sym) or {}
                if entry.get("description"):
                    names[sym] = {
                        "company": entry["description"],
                        "updated_at": entry.get("observed_at"),
                        "source": "schwab_instrument_evidence.description",
                    }
        else:
            errors.append("instrument_names:invalid_schema")
    except FileNotFoundError:
        errors.append("instrument_names:not_on_file")
    except (OSError, ValueError) as exc:
        errors.append(f"instrument_names:{type(exc).__name__}")
    return {
        "instrument_names": names,
        "identity_profiles": identity_profiles,
        "profiles": profiles,
        "finviz": finviz.get("symbols") or {},
        "errors": errors,
    }


def assemble(
    symbol: str, identity: dict, inputs: dict, *, catalyst: dict | None = None, prior: dict | None = None, now: datetime
) -> dict:
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
        (
            identity_profile,
            "ticker_research_graph.profile",
            iso(identity_profile.get("updated_at")),
            "profile_updated_at",
        ),
        (profile, "symbol_profiles", iso(profile.get("updated_at")), "row_updated_at"),
        (rec, "finviz_enrichment", fv.get("as_of"), "cached_at"),
    ]
    conflicts = []
    rejected_names = deepcopy(prior.get("rejected_company_names") or [])
    for key in FIELDS:
        candidates = []
        field_sources = sources
        if key == "company":
            name = (inputs.get("instrument_names") or {}).get(symbol) or {}
            field_sources = [
                (name, "schwab_instrument_evidence.description", iso(name.get("updated_at")), "instrument_observed_at"),
                *sources,
            ]
        for data, source, at, clock in field_sources:
            if data.get("security_guid") and data["security_guid"] != guid:
                conflicts.append({"field": key, "source": source, "reason": "source_guid_mismatch"})
                continue
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            if key == "company" and company_name_issue(value):
                rejected_names.append({"source": source, "observed_at": at, "reason": company_name_issue(value)})
                continue
            candidates.append(
                {
                    "value": " ".join(value.split())[:1200],
                    "source": source,
                    "observed_at": at,
                    "clock_kind": clock,
                    "missing_reason": None,
                    "identity_binding": "confirmed_registry_symbol_at_batch",
                    "source_identity": "guid_keyed" if data.get("security_guid") else "symbol_keyed",
                    "source_time_raw": str(data.get("updated_at") or data.get("cached_at") or "") or None,
                    "producer_source": data.get("source"),
                }
            )
        old = prior.get(key) or {}
        if old.get("value"):
            if key == "company" and company_name_issue(old["value"]):
                rejected_names.append(
                    {
                        "source": old.get("source"),
                        "observed_at": old.get("observed_at"),
                        "reason": company_name_issue(old["value"]),
                        "retained_value_rejected": True,
                    }
                )
            else:
                candidates.append(deepcopy(old))
        # A newly read undated value cannot displace an already dated fact.
        candidates.sort(
            key=lambda f: timestamp(f.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True
        )
        if key == "company":
            # Registered stored instrument names have explicit authority; source
            # clocks stay original and disagreement remains visible.
            candidates.sort(key=lambda f: f.get("source") == "schwab_instrument_evidence.description", reverse=True)
        if candidates:
            out[key] = candidates[0]
            if not out[key].get("observed_at"):
                out[key]["missing_reason"] = "source_observation_time_unavailable"
            if len({str(c["value"]).casefold() for c in candidates}) > 1:
                conflicts.append({"field": key, "reason": "source_values_disagree", "values": candidates})
        elif key == "company" and rejected_names:
            out[key]["missing_reason"] = "no_valid_registered_company_name_on_file"
    # Card display name (common name); the registered legal name stays as a secondary field.
    from scripts.lib import cio_company_quality as quality

    fv_name = rec.get("company") if not (rec.get("security_guid") and rec["security_guid"] != guid) else None
    out["company"] = {
        **out["company"],
        **quality.display_name(
            symbol,
            out["company"].get("value"),
            finviz_name=fv_name,
            description=(out.get("description") or {}).get("value"),
        ),
    }
    out["catalyst"], out["recent_news"] = select_catalyst(
        symbol,
        guid,
        list((catalyst or {}).get("facts") or []),
        inputs,
        profile=profile,
        prior=prior,
        names=[n for n in (out["company"].get("display_name"), out["company"].get("value")) if n],
        company_conflict=any(c.get("field") == "company" for c in conflicts),
        conflicts=conflicts,
        now=now,
    )
    if rejected_names:
        out["rejected_company_names"] = list({json.dumps(r, sort_keys=True): r for r in rejected_names}.values())
    out["conflicts"] = conflicts
    out["missing_reason"] = None
    if prior and {k: v for k, v in prior.items() if k != "assembled_at"} == {
        k: v for k, v in out.items() if k != "assembled_at"
    }:
        return deepcopy(prior)
    return out


CATALYST_KEYS = (
    "headline",
    "source",
    "feed",
    "published_at",
    "observed_at",
    "url",
    "source_ref",
    "event_id",
    "created_at",
    "clock_kind",
    "catalyst_type",
    "verification_basis",
    "factual_verification_status",
    "identity_verification",
    "identity_record",
    "event_at",
    "producer_source",
    "estimated",
)


def select_catalyst(
    symbol: str,
    guid: str | None,
    facts: list[dict],
    inputs: dict,
    *,
    profile: dict | None,
    prior: dict | None,
    names: list[str],
    company_conflict: bool,
    conflicts: list[dict],
    now: datetime,
) -> tuple[dict, list[dict]]:
    """(catalyst, recent_news) under the reviewed C1 quality rules (config/cio_company_facts_quality.json).

    The next dated upcoming event wins, then the newest recent material corporate event. Everything else that is
    dated and about this company is recent news, never the catalyst. Nothing qualifies -> NONE_ON_FILE + reason.
    """
    from scripts.lib import cio_company_quality as quality

    cfg = quality.rules()["catalyst"]
    cutoff = now - timedelta(days=int(cfg["material_window_days"]))
    horizon = now + timedelta(days=int(cfg["upcoming_horizon_days"]))
    facts = list(facts) + quality.scheduled_events(symbol, profile, now=now)
    old_cat = (prior or {}).get("catalyst") or {}
    # A retained scheduled event is re-read from its schedule every pass (dates move); never carried forward.
    if old_cat.get("headline") and old_cat.get("catalyst_class") != quality.UPCOMING:
        facts.append(deepcopy(old_cat))
    upcoming, material, news = [], [], []
    for f in facts:
        if f.get("subject_guid") and str(f["subject_guid"]) != str(guid):
            conflicts.append({"field": "catalyst", "reason": "source_guid_mismatch", "source": f.get("source")})
            continue
        headline = str(f.get("headline") or "").strip()
        if not headline or str(f.get("catalyst_type") or "").lower() in ("none", "no_clear_catalyst"):
            continue
        if f.get("source") == "hermes_momentum_catalysts":
            from scripts.lib.hermes_scalp_catalyst_record import verify_identity, VERIFIED

            name = names[0] if names else None
            raw = f.get("identity_record") or {"catalyst_summary": headline, "sources": []}
            proof = verify_identity(symbol, raw, [n for n in names if n])
            # A missing/conflicting company name is a collection gap, never
            # permission to bind arbitrary search evidence by ticker alone.
            if not name or company_conflict:
                proof = {**proof, "status": "UNVERIFIED_IDENTITY", "reason": "company_name_missing_or_conflicting"}
            if proof.get("status") != VERIFIED:
                conflicts.append(
                    {
                        "field": "catalyst",
                        "source": f.get("source"),
                        "reason": "hermes_company_identity_unverified",
                        "identity_verification": proof,
                    }
                )
                continue
            f = {**f, "identity_verification": proof, "identity_record": raw}
        verdict = quality.classify(f, symbol=symbol, names=names)
        if verdict["class"] == quality.UPCOMING:
            at = quality.parse_when(f.get("event_at"))
            if at and now.date() <= at.date() and at <= horizon:
                upcoming.append((at, f, verdict))
            continue
        at = timestamp(f.get("published_at")) or timestamp(f.get("observed_at"))
        if not at or not cutoff <= at <= now:
            continue
        (material if verdict["class"] == quality.MATERIAL else news).append((at, f, verdict))
    upcoming.sort(key=lambda x: x[0])
    material.sort(key=lambda x: x[0], reverse=True)
    news.sort(key=lambda x: x[0], reverse=True)
    recent, seen = [], set()
    for _, f, verdict in news:
        if verdict["reason"] in ("headline_does_not_name_subject", "foreign_listing"):
            continue  # probably another company's story; not this company's news either
        key = " ".join(str(f.get("headline")).lower().split())[:120]
        if key in seen:
            continue
        seen.add(key)
        day, kind = quality.fact_date(f)
        recent.append(
            {
                "headline": f.get("headline"),
                "date": day,
                "date_kind": kind,
                "source_label": quality.source_label(f),
                "feed": f.get("feed"),
                "source": f.get("source"),
                "url": f.get("url"),
                "published_at": f.get("published_at"),
                "catalyst_type": f.get("catalyst_type"),
                "not_catalyst_reason": verdict["reason"],
            }
        )
        if len(recent) >= int(cfg["recent_news_max"]):
            break
    chosen = (upcoming or material or [None])[0]
    if chosen:
        _, f, verdict = chosen
        out = {k: f.get(k) for k in CATALYST_KEYS}
        day, kind = quality.fact_date(f)
        out.update(
            status="CURRENT",
            missing_reason=None,
            reason=None,
            catalyst_class=verdict["class"],
            event_type=verdict["event_type"],
            date=day,
            date_kind=kind,
            source_label=quality.source_label(f),
            source_verified_claim=bool(f.get("source_verified_claim", f.get("verified")))
            and f.get("verification_basis") != "LEGACY_CONFIDENCE_THRESHOLD",
            independent_verification="NOT_MEASURED",
            rules="config/cio_company_facts_quality.json",
        )
        return out, recent
    unmeasured = any(str(e).startswith("catalyst_events:") for e in inputs.get("errors") or [])
    skipped = sorted({v["reason"].split(":")[0] for _, _, v in news})
    code = (
        "catalyst_source_not_measured"
        if unmeasured
        else "no_qualifying_catalyst_only_news_on_file"
        if news
        else "no_dated_current_catalyst_on_file"
    )
    reason = (
        "Catalyst source was not read this pass."
        if unmeasured
        else "No dated upcoming event or recent material corporate event on file"
        + (
            f"; {len(news)} recent news item(s) are not catalysts ({', '.join(r.replace('_', ' ') for r in skipped)})."
            if news
            else "."
        )
    )
    return (
        {
            "headline": None,
            "status": "MISSING" if unmeasured else "NONE_ON_FILE",
            "missing_reason": code,
            "reason": reason,
            "date": None,
            "date_kind": "date_unknown",
            "rules": "config/cio_company_facts_quality.json",
        },
        recent,
    )


def public_research(record: dict, guid: str | None) -> dict:
    """One shared, typed consumer shape; never leaks arbitrary private research keys."""
    if not guid or str(record.get("security_guid")) != str(guid):
        return {
            "company_facts": missing(str(record.get("symbol") or ""), guid, "record_guid_mismatch"),
            "review_lifecycle": {"status": "MISSING", "missing_reason": "record_guid_mismatch"},
        }
    research = record.get("research") or {}
    facts = research.get("company_facts") or {}
    if facts.get("schema") != SCHEMA or str(facts.get("security_guid")) != str(guid):
        facts = missing(str(record.get("symbol") or ""), guid, "company_facts_not_on_cio_record")
    review = research.get("review_lifecycle")
    review = (
        {k: deepcopy(review[k]) for k in REVIEW_FIELDS if k in review}
        if isinstance(review, dict)
        else {"status": "MISSING", "missing_reason": "review_lifecycle_not_on_cio_record"}
    )
    return {"company_facts": deepcopy(facts), "review_lifecycle": review}


def persist_company_facts(
    root: Path, prospects: list[dict], *, write: bool = False, backend=None, registry=None, env=None
) -> dict:
    """Use the existing prospect facade, merging only this extension into latest records.

    Not called by HTTP readers or --write-shadow. Explicit batch opt-in required.
    No prospect stance/conviction from a shadow proposal is promoted by this pass.
    """
    from scripts.lib.cio_instrument_record import (
        InstrumentRecordStore,
        DEFAULT_PATH,
        apply_prospect,
        is_prospect_record,
        select_canonical_record,
        ProspectInvalid,
        BehaviorWriteRefused,
    )

    store = InstrumentRecordStore(Path(root) / DEFAULT_PATH)
    records = store.all()
    by_guid: dict[str, list[dict]] = {}
    for r in records:
        by_guid.setdefault(str(r.get("security_guid") or ""), []).append(r)
    result = {
        "mode": "write" if write else "dry_run",
        "written": 0,
        "would_write": 0,
        "gaps": [],
        "pg": [],
        "consumer_sync": "NOT_REQUESTED" if not write else "NOT_MEASURED",
    }
    for p in prospects:
        guid = str(p.get("security_guid") or "")
        facts = (p.get("research") or {}).get("company_facts") or {}
        if not guid or facts.get("security_guid") != guid or facts.get("schema") != SCHEMA:
            result["gaps"].append({"symbol": p.get("symbol"), "reason": "invalid_fact_identity"})
            continue
        matches = by_guid.get(guid) or []
        # A judged prospect plus its fact-only sibling is one canonical record, not
        # two heads. Never mint a second canonical record or choose among >1 prospects.
        rec, violation = select_canonical_record(matches)
        if violation:
            result["gaps"].append(
                {
                    "symbol": p.get("symbol"),
                    "security_guid": guid,
                    "reason": violation,
                }
            )
            continue
        if rec is None:
            result["gaps"].append(
                {
                    "symbol": p.get("symbol"),
                    "security_guid": guid,
                    "reason": "cio_record_missing",
                }
            )
            continue
        rec = deepcopy(rec)
        if not is_prospect_record(rec):
            result["gaps"].append(
                {"symbol": p.get("symbol"), "security_guid": guid, "reason": "legacy_record_needs_cio_promotion"}
            )
            continue
        research = deepcopy(rec.get("research") or {})
        if research.get("company_facts") == facts:
            continue
        research["company_facts"] = deepcopy(facts)
        try:
            rec, _ = apply_prospect(rec, prospect={"research": research})
        except (ProspectInvalid, BehaviorWriteRefused) as exc:
            result["gaps"].append(
                {
                    "symbol": p.get("symbol"),
                    "security_guid": guid,
                    "reason": f"record_validation_failed:{type(exc).__name__}",
                }
            )
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
        result["consumer_sync"] = (
            "FAILED"
            if any(p.get("ok") is False for p in result["pg"])
            else (
                "INERT"
                if any(p.get("mode") == "inert" for p in result["pg"])
                else ("DUAL_WRITE_ACKNOWLEDGED" if result["pg"] else "NOT_MEASURED_NO_CHANGE")
            )
        )
    result["ok"] = not result["gaps"] and result["consumer_sync"] not in ("FAILED", "INERT")
    return result
