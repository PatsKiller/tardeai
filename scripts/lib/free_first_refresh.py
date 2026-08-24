"""FREE_FIRST_ONLY evidence refresh — no paid provider path.

A SYMBOL_EVIDENCE_REFRESH job may not jump PLANNED → paid. Modes:

  FREE_FIRST_ONLY   this prompt; default
  LLM_ELIGIBLE      mark only; do not call
  PAID_AUTHORIZED   requires explicit operator grant (not this module)

Default outcome is NO_NEW_INFO.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from scripts.lib.evidence_freshness_policy import is_decision_fresh, classify_evidence_class
from scripts.lib.librarian_assessment import assess_artifact
from scripts.lib.security_identity import attach_identity_v2, classify_unresolved_symbol, normalize_symbol
from scripts.lib.ticker_knowledge_graph import graph_path, upgrade_record_guids

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "FreeFirstRefreshReport@v1"
MODES = ("FREE_FIRST_ONLY", "LLM_ELIGIBLE", "PAID_AUTHORIZED")
PAID_ERROR = "PAID_PROVIDER_FORBIDDEN: PLANNED cannot enter a paid provider from FREE_FIRST_ONLY"


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def reject_paid_transition(from_state: str, to_paid: bool, mode: str = "FREE_FIRST_ONLY") -> None:
    if to_paid and mode != "PAID_AUTHORIZED":
        raise RuntimeError(PAID_ERROR)
    if to_paid and str(from_state or "").upper() in ("PLANNED", "FREE_FIRST_ONLY", ""):
        raise RuntimeError(PAID_ERROR)


def load_profiles(root: Path | str) -> list[dict[str, Any]]:
    path = graph_path(root)
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = upgrade_record_guids(json.loads(line))
        except json.JSONDecodeError:
            continue
        if row.get("research_artifact_guid"):
            continue
        if row.get("ticker_guid") or row.get("schema") == "TickerKnowledgeProfile@v1":
            out.append(attach_identity_v2(row))
    return out


def _watermark(items: Iterable[dict[str, Any]]) -> str:
    hashes = sorted(str(x.get("content_hash") or x.get("id") or "") for x in items)
    return _digest(hashes)


def classify_symbol(
    profile: dict[str, Any],
    *,
    hermes_rows: list[dict[str, Any]] | None = None,
    news_rows: list[dict[str, Any]] | None = None,
    thesis: dict[str, Any] | None = None,
    searx_hits: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Deterministic per-symbol free-first decision. Never calls a model."""
    reject_paid_transition("PLANNED", False)
    sym = normalize_symbol(profile.get("symbol"))
    unresolved = classify_unresolved_symbol(sym)
    hermes = list(hermes_rows or [])
    news = list(news_rows or [])
    hits = list(searx_hits or [])
    fresh_hermes = [
        r for r in hermes
        if is_decision_fresh(
            r.get("created_at") or r.get("freshness_date") or r.get("as_of"),
            row=r,
            now=now,
        )
    ]
    prior_hashes = {str(r.get("content_hash") or r.get("id") or "") for r in fresh_hermes}
    assessments = [assess_artifact(r, prior_hashes=prior_hashes) for r in hits[:6]]
    material = [a for a in assessments if a.get("material")]
    reasons: list[str] = []
    bucket = "unresolved_after_free"
    llm = None
    if unresolved["kind"] in ("cusip_or_fixed_income", "invalid_or_stale", "fund"):
        bucket = "structured_resolved"
        reasons.append(unresolved["reason"])
    elif fresh_hermes:
        bucket = "existing_Hermes_reuse"
        reasons.append("fresh_hermes_no_delta" if not material else "fresh_hermes_plus_new_hits")
        if material:
            llm = "Flash"
    elif thesis and not hits:
        bucket = "no_refresh_needed" if profile.get("company") else "RAG_sufficient"
        reasons.append("standing_thesis_no_new_hash")
    elif hits:
        bucket = "SearXNG_resolved"
        reasons.append("searxng_hits")
        llm = "Flash"
    elif profile.get("company") and profile.get("sector"):
        bucket = "structured_resolved"
        reasons.append("canonical_card")
    else:
        bucket = "unresolved_after_free"
        reasons.append(unresolved.get("reason") or "no_canonical_symbol_card")
        llm = "Flash"
    no_new = bucket in ("existing_Hermes_reuse", "no_refresh_needed", "structured_resolved", "RAG_sufficient") and not material
    return {
        "symbol": sym,
        "ticker_guid": profile.get("ticker_guid"),
        "issuer_guid": profile.get("issuer_guid"),
        "security_guid": profile.get("security_guid"),
        "listing_guid": profile.get("listing_guid"),
        "identity_status": profile.get("identity_status"),
        "unresolved_kind": unresolved["kind"] if not profile.get("company") else None,
        "bucket": bucket,
        "no_new_info": no_new,
        "llm_eligible": llm,
        "challenger_eligible": False,
        "pro_eligible": False,
        "reasons": reasons,
        "fresh_hermes_n": len(fresh_hermes),
        "news_n": len(news),
        "searx_n": len(hits),
        "material_n": len(material),
        "evidence_watermark": _watermark(fresh_hermes + hits),
        "assessments": assessments[:4],
        "mode": "FREE_FIRST_ONLY",
        "authority": AUTHORITY,
        "financial_action": False,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[str]] = {}
    flash: list[str] = []
    for r in rows:
        buckets.setdefault(r["bucket"], []).append(r["symbol"])
        if r.get("llm_eligible") == "Flash":
            flash.append(r["symbol"])
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "mode": "FREE_FIRST_ONLY",
        "paid_calls_attempted": 0,
        "paid_calls_completed": 0,
        "spend_delta": 0,
        "total_symbols": len(rows),
        "no_refresh_needed": len(buckets.get("no_refresh_needed") or []),
        "existing_Hermes_reuse": len(buckets.get("existing_Hermes_reuse") or []),
        "RAG_sufficient": len(buckets.get("RAG_sufficient") or []),
        "structured_resolved": len(buckets.get("structured_resolved") or []),
        "SearXNG_resolved": len(buckets.get("SearXNG_resolved") or []),
        "unresolved_after_free": len(buckets.get("unresolved_after_free") or []),
        "Flash_eligible_count": len(flash),
        "Flash_symbols": sorted(flash),
        "OAuth_challenger_count": 0,
        "challenger_symbols": [],
        "Pro_eligible_count": 0,
        "Pro_symbols": [],
        "buckets": {k: sorted(v) for k, v in buckets.items()},
        "no_new_info": sum(1 for r in rows if r.get("no_new_info")),
        "memory_behavior_influence": int(os.getenv("MEMORY_BEHAVIOR_INFLUENCE", "0") or 0),
    }


def run_free_first(
    root: Path | str,
    *,
    hermes_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    thesis_by_symbol: dict[str, dict[str, Any]] | None = None,
    searx_fn: Callable[[str], list[dict[str, Any]]] | None = None,
    max_searx: int = 0,
) -> dict[str, Any]:
    """Classify every graph profile. searx_fn is optional and never paid."""
    profiles = load_profiles(root)
    hermes_by_symbol = hermes_by_symbol or {}
    thesis_by_symbol = thesis_by_symbol or {}
    rows = []
    searx_used = 0
    for profile in profiles:
        sym = normalize_symbol(profile.get("symbol"))
        hits: list[dict[str, Any]] = []
        if searx_fn and searx_used < max_searx and not profile.get("company"):
            try:
                hits = list(searx_fn(sym) or [])
                searx_used += 1
            except Exception:
                hits = []
        rows.append(classify_symbol(
            profile,
            hermes_rows=hermes_by_symbol.get(sym) or [],
            thesis=thesis_by_symbol.get(sym),
            searx_hits=hits,
        ))
    report = summarize(rows)
    report["free_searches"] = searx_used
    report["rows"] = rows
    report["as_of"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return report
