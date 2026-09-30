"""SecurityResearchSpine@v1 — CIO-owned shared research memory per security.

Problem this closes: options / holdings / watchlist / re-entry each gather or
cache research independently. For one subject_guid, the house must have ONE
spine every silo reads.

Authority: READ_ONLY_ADVISORY. Writers append contributions; readers merge.
Does not place orders.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "SecurityResearchSpine@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
DEFAULT_REL = Path("data") / "cio" / "security_research_spine.jsonl"

# Silos that must read the same spine (documented contract).
CONSUMER_SILOS = frozenset({
    "cio",
    "hermes",
    "options_desk",
    "watchlist",
    "reentry",
    "holdings",
    "cross_asset",
    "aegis",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[3]
    return base / DEFAULT_REL


def empty_spine(symbol: str, *, subject_guid: str | None = None) -> dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    if not sym:
        raise ValueError("symbol_required")
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "symbol": sym,
        "subject_guid": subject_guid,
        "owner": "cio",
        "as_of": _now(),
        "thesis": {
            "state": "INSUFFICIENT_DATA",
            "stance": None,
            "summary": None,
            "conviction": None,
            "invalidation": [],
        },
        "contributions": [],  # {silo, artifact_id, kind, summary, ts, refs, tags}
        "tags": [],  # union of contribution tags (multi-producer memory)
        "by_silo": {s: {"last_read_at": None, "last_write_at": None} for s in sorted(CONSUMER_SILOS)},
        "latest_hermes": {"research_id": None, "result_id": None, "status": None, "as_of": None},
        "latest_operator": {"pending_id": None, "kind": None, "as_of": None},
        "latest_llm": {"source": None, "model": None, "kind": None, "as_of": None},
        # Active operator asks remain until a thesis_publish clears/archives them.
        "operator_asks": [],
        "transparency": {
            "shared_across_silos": True,
            "note": "All consumer silos MUST read this spine; do not fork private thesis copies. "
                    "LLM curation is CIO-owned contribution (tags llm_research/llm_curation); "
                    "never a fact source and never replaces house thesis tip.",
        },
    }


def validate_spine(obj: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return {"ok": False, "errors": ["not_a_dict"]}
    if obj.get("schema") != SCHEMA:
        errors.append(f"schema_expected_{SCHEMA}")
    if obj.get("authority") != AUTHORITY:
        errors.append("authority_must_be_READ_ONLY_ADVISORY")
    if obj.get("owner") != "cio":
        errors.append("owner_must_be_cio")
    if not str(obj.get("symbol") or "").strip():
        errors.append("symbol_required")
    if not isinstance(obj.get("contributions"), list):
        errors.append("contributions_must_be_list")
    # Identity 4/5: SECURITY spines must carry a registry UUID (not smoke/ticker).
    try:
        from scripts.lib.identity_carriage import is_registry_guid
        sg = obj.get("subject_guid")
        if sg is not None and not is_registry_guid(sg):
            errors.append("subject_guid_must_be_registry_uuid")
    except Exception:
        pass
    return {"ok": not errors, "errors": errors}


# Multi-tag vocabulary for shared security memory (not Hermes-only).
KNOWN_TAGS = frozenset({
    "hermes",
    "operator_qa",
    "operator_ask",
    "operator_deferred",
    "thesis",
    "llm_research",
    "llm_curation",
    "llm_flash",
    "deepseek",
    "ollama",
    "desk",
    "watchlist",
    "options",
    "holdings",
    "reentry",
    "aegis",
    "lifecycle",
    "backfill",
    "canary",
    "stale_sla",
    "sector",
    "sector_subject",
})


def _normalize_tags(tags: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        t = str(raw or "").strip().lower().replace(" ", "_")
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t[:48])
    return out[:24]


def contribute(
    spine: dict[str, Any],
    *,
    silo: str,
    kind: str,
    summary: str | None = None,
    artifact_id: str | None = None,
    refs: list[str] | None = None,
    tags: Iterable[str] | None = None,
    thesis_patch: dict[str, Any] | None = None,
    hermes: dict[str, Any] | None = None,
    operator: dict[str, Any] | None = None,
    llm: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a contribution from any producer silo; optional thesis/hermes/operator/llm upgrade."""
    out = deepcopy(spine)
    silo_n = str(silo or "unknown").strip().lower()
    ts = _now()
    tag_list = _normalize_tags(tags)
    out["contributions"] = list(out.get("contributions") or [])
    out["contributions"].append({
        "silo": silo_n,
        "kind": kind,
        "summary": (summary or "")[:800] or None,
        "artifact_id": artifact_id,
        "refs": list(refs or [])[:20],
        "tags": tag_list,
        "ts": ts,
        "model": (llm or {}).get("model") if llm else None,
        "owner": "cio",
    })
    out["contributions"] = out["contributions"][-100:]
    # Union tags onto the spine tip so readers can filter without scanning history.
    prior_tags = _normalize_tags(out.get("tags") or [])
    merged_tags = _normalize_tags([*prior_tags, *tag_list])
    out["tags"] = merged_tags
    by = dict(out.get("by_silo") or {})
    if silo_n not in by and silo_n:
        by[silo_n] = {"last_read_at": None, "last_write_at": None}
    slot = dict(by.get(silo_n) or {"last_read_at": None, "last_write_at": None})
    slot["last_write_at"] = ts
    by[silo_n] = slot
    out["by_silo"] = by
    if thesis_patch:
        th = dict(out.get("thesis") or {})
        th.update({k: v for k, v in thesis_patch.items() if v is not None})
        if th.get("summary"):
            th["state"] = th.get("state") or "POPULATED"
        out["thesis"] = th
    if hermes:
        out["latest_hermes"] = {
            "research_id": hermes.get("research_id"),
            "result_id": hermes.get("result_id"),
            "status": hermes.get("status"),
            "as_of": hermes.get("as_of") or hermes.get("completed_ts") or ts,
        }
    if operator:
        out["latest_operator"] = {
            "pending_id": operator.get("pending_id"),
            "kind": operator.get("kind"),
            "as_of": operator.get("as_of") or ts,
            "reply_source": operator.get("reply_source"),
        }
        # Persist operator asks until thesis changes (not last-write tip wipe).
        asks = list(out.get("operator_asks") or [])
        ask_row = {
            "pending_id": operator.get("pending_id"),
            "kind": operator.get("kind") or kind,
            "text": (summary or operator.get("text") or "")[:800] or None,
            "reply_source": operator.get("reply_source"),
            "ts": ts,
            "status": "active",
        }
        # Dedupe by pending_id when present.
        pid = str(ask_row.get("pending_id") or "")
        if pid:
            asks = [a for a in asks if str((a or {}).get("pending_id") or "") != pid]
        asks.append(ask_row)
        out["operator_asks"] = asks[-50:]
    if llm:
        out["latest_llm"] = {
            "source": llm.get("source"),
            "model": llm.get("model"),
            "kind": llm.get("kind") or kind,
            "as_of": llm.get("as_of") or ts,
            "note": llm.get("note") or "curation_not_fact_source",
        }
    # Thesis publish closes active operator asks (memory retained in contributions).
    if kind in {"thesis_publish", "thesis_backfill"} or "thesis" in tag_list:
        archived = []
        still = []
        for a in list(out.get("operator_asks") or []):
            if not isinstance(a, dict):
                continue
            if a.get("status") == "active":
                archived.append({**a, "status": "closed_by_thesis", "closed_ts": ts})
            else:
                still.append(a)
        if archived:
            out["operator_asks"] = (still + archived)[-50:]
    out["as_of"] = ts
    return out


def mark_read(spine: dict[str, Any], silo: str) -> dict[str, Any]:
    out = deepcopy(spine)
    silo_n = str(silo or "").strip().lower()
    by = dict(out.get("by_silo") or {})
    slot = dict(by.get(silo_n) or {"last_read_at": None, "last_write_at": None})
    slot["last_read_at"] = _now()
    by[silo_n] = slot
    out["by_silo"] = by
    return out


def append_spine(obj: dict[str, Any], *, path: Path | None = None, root: Path | None = None) -> dict[str, Any]:
    check = validate_spine(obj)
    if not check["ok"]:
        return {"ok": False, "error": "invalid_spine", "errors": check["errors"]}
    dest = path or default_path(root)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, separators=(",", ":"), default=str) + "\n")
        return {"ok": True, "path": str(dest)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160]}


def load_latest(
    symbol: str,
    *,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    sym = str(symbol or "").upper().strip()
    dest = path or default_path(root)
    if not dest.exists():
        return None
    latest = None
    with dest.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and str(row.get("symbol") or "").upper() == sym:
                latest = row
    return latest


def upsert_research_memory(
    symbol: str,
    *,
    silo: str,
    kind: str,
    summary: str | None = None,
    artifact_id: str | None = None,
    refs: list[str] | None = None,
    tags: Iterable[str] | None = None,
    thesis_patch: dict[str, Any] | None = None,
    hermes: dict[str, Any] | None = None,
    operator: dict[str, Any] | None = None,
    llm: dict[str, Any] | None = None,
    subject_guid: str | None = None,
    issuer_guid: str | None = None,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Generic multi-producer write: Hermes, operator Q, thesis, LLM research, desk.

    Requires a registry UUID subject_guid (resolved from symbol when omitted).
    Tags accumulate on the spine tip for full-lifecycle memory across producers.
    LLM rows are CIO-owned contributions; pass thesis_patch=None so curation
    never replaces the house tip thesis.
    """
    from scripts.lib.identity_carriage import is_registry_guid, resolve_security_identity, stamp_security_fields

    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "error": "symbol_required"}
    cand = subject_guid
    iss = issuer_guid
    if not is_registry_guid(cand):
        env = resolve_security_identity(sym, root=root)
        cand = env.get("subject_guid")
        iss = iss or env.get("issuer_guid")
    if not is_registry_guid(cand):
        return {
            "ok": False,
            "error": "subject_guid_required_registry_uuid",
            "symbol": sym,
            "identity_stamp_miss": True,
        }
    prior = load_latest(sym, path=path, root=root) or empty_spine(sym, subject_guid=cand)
    if not is_registry_guid(prior.get("subject_guid")):
        prior = dict(prior)
        prior["subject_guid"] = cand
    tag_list = _normalize_tags(tags)
    spine = contribute(
        prior,
        silo=silo,
        kind=kind,
        summary=str(summary)[:800] if summary else None,
        artifact_id=artifact_id,
        refs=list(refs or [])[:20],
        tags=tag_list,
        thesis_patch=thesis_patch,
        hermes=hermes,
        operator=operator,
        llm=llm,
    )
    spine["subject_guid"] = cand
    if iss:
        spine["issuer_guid"] = iss
    spine = stamp_security_fields(spine, symbol=sym, root=root)
    spine = contribute(
        spine,
        silo="cio",
        kind="accepted_into_spine",
        summary=f"CIO-owned spine updated from {silo}:{kind}",
        tags=["lifecycle"],
    )
    v = validate_spine(spine)
    if not v.get("ok"):
        return {"ok": False, "error": "validate_spine_failed", "errors": v.get("errors"), "spine": spine}
    wr = append_spine(spine, path=path, root=root)
    return {"ok": bool(wr.get("ok")), "spine": spine, "write": wr, "symbol": sym, "tags": spine.get("tags")}


def upsert_from_hermes(
    symbol: str,
    hermes_result: dict[str, Any],
    *,
    path: Path | None = None,
    root: Path | None = None,
    subject_guid: str | None = None,
    tags: Iterable[str] | None = None,
) -> dict[str, Any]:
    """CIO/Hermes write path: merge Hermes result into spine and persist."""
    hermes = dict(hermes_result or {})
    summary = hermes.get("summary") or hermes.get("recommendation")
    tag_list = _normalize_tags(list(tags or []) + ["hermes"])
    return upsert_research_memory(
        symbol,
        silo="hermes",
        kind="research_result",
        summary=str(summary)[:800] if summary else None,
        artifact_id=hermes.get("result_id"),
        refs=[x for x in [hermes.get("research_id"), hermes.get("result_id")] if x],
        tags=tag_list,
        thesis_patch={
            "stance": hermes.get("thesis_stance"),
            "summary": str(summary)[:1200] if summary else None,
            "conviction": hermes.get("confidence"),
            "state": "POPULATED" if summary else "INSUFFICIENT_DATA",
            "invalidation": list(hermes.get("research_gaps_remaining") or [])[:12],
        },
        hermes=hermes,
        subject_guid=subject_guid or hermes.get("subject_guid"),
        issuer_guid=hermes.get("issuer_guid"),
        path=path,
        root=root,
    )


def view_for_silo(
    symbol: str,
    silo: str,
    *,
    path: Path | None = None,
    root: Path | None = None,
    persist_read_receipt: bool = False,
) -> dict[str, Any]:
    """Canonical read API for any silo — same thesis, marked as shared."""
    spine = load_latest(symbol, path=path, root=root)
    if spine is None:
        return {
            "ok": True,
            "found": False,
            "silo": silo,
            "symbol": str(symbol).upper(),
            "thesis": {"state": "INSUFFICIENT_DATA", "summary": None},
            "note": "no_spine_yet — do not invent a silo-local thesis",
            "authority": AUTHORITY,
        }
    viewed = mark_read(spine, silo) if silo else spine
    if persist_read_receipt:
        append_spine(viewed, path=path, root=root)
    # Spine SLA currency (CLASS_SLA_DAYS vs tip as_of) — librarian/desk honesty gate.
    currency: dict[str, Any] = {"fresh": None, "age_days": None, "sla_days": None}
    try:
        from datetime import datetime, timezone
        from scripts.lib.symbol_thesis_coverage import stale_days_for

        sla_days = int(stale_days_for(str(viewed.get("symbol") or symbol), {}, {}, root=root))
        currency["sla_days"] = sla_days
        as_of = str(viewed.get("as_of") or "")
        if as_of:
            tip_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            if tip_dt.tzinfo is None:
                tip_dt = tip_dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - tip_dt).total_seconds() / 86400.0
            currency["age_days"] = round(age, 2)
            currency["fresh"] = age <= float(sla_days)
            currency["refuse_fresh_claim"] = not currency["fresh"]
    except Exception:
        pass
    tags = list(viewed.get("tags") or [])
    if currency.get("fresh") is False and "stale_sla" not in tags:
        tags = tags + ["stale_sla"]
    return {
        "ok": True,
        "found": True,
        "silo": silo,
        "symbol": viewed.get("symbol"),
        "subject_guid": viewed.get("subject_guid"),
        "owner": viewed.get("owner") or "cio",
        "thesis": viewed.get("thesis"),
        "tags": tags,
        "latest_hermes": viewed.get("latest_hermes"),
        "latest_operator": viewed.get("latest_operator"),
        "latest_llm": viewed.get("latest_llm"),
        "operator_asks": [
            a for a in (viewed.get("operator_asks") or [])
            if isinstance(a, dict) and a.get("status") == "active"
        ],
        "contribution_count": len(viewed.get("contributions") or []),
        "transparency": viewed.get("transparency"),
        "authority": AUTHORITY,
        "as_of": viewed.get("as_of"),
        "currency": currency,
        "spine_fresh": currency.get("fresh"),
        "spine_sla_days": currency.get("sla_days"),
        "spine_age_days": currency.get("age_days"),
    }


def spine_rows_for_options_universe(spines: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapter into options_research_universe.merge_research_rows shape."""
    out = []
    for sp in spines:
        if not isinstance(sp, dict):
            continue
        th = sp.get("thesis") or {}
        hermes = sp.get("latest_hermes") or {}
        out.append({
            "symbol": sp.get("symbol"),
            "source": "cio_research",
            "source_lanes": ["cio_research", "security_research_spine"],
            "research_status": "researched" if th.get("state") == "POPULATED" else "research_required",
            "research_artifact_id": hermes.get("result_id") or sp.get("subject_guid"),
            "summary": th.get("summary"),
            "subject_guid": sp.get("subject_guid"),
        })
    return out
