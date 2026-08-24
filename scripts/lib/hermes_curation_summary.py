"""HermesCurationSummary@v1 — durable last-material-review snapshot.

A MATERIAL version is created only for material evidence-state change, never for
timestamp-only / duplicate / embedding / FRESH_NO_CHANGE / NO_NEW_INFO.

A missing prior is not "empty brain": the first write may be
kind=BASELINE_PROJECTION at version 0. That is not a material version.
Subsequent NO_NEW_INFO writes nothing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "HermesCurationSummary@v1"
PATH = "data/cio/hermes_curation_summary.jsonl"
KIND_BASELINE = "BASELINE_PROJECTION"
KIND_MATERIAL = "MATERIAL"
BASELINE_SCHEMA = "BaselineCurationSnapshot@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def summary_path(root: Path | str) -> Path:
    return Path(root) / PATH


def load_latest(root: Path | str, *, security_guid: str | None, symbol: str | None) -> dict[str, Any] | None:
    path = summary_path(root)
    if not path.exists():
        return None
    hit = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if security_guid and row.get("security_guid") == security_guid:
            hit = row
        elif not security_guid and row.get("current_ticker_alias") == symbol:
            hit = row
    return hit


def build_summary(
    *,
    security_guid: str | None,
    issuer_guid: str | None,
    listing_guid: str | None,
    symbol: str,
    evidence_watermark: str,
    previous: dict[str, Any] | None,
    support_guids: list[str],
    counter_guids: list[str],
    catalyst_guids: list[str],
    calendar_guids: list[str],
    sector_guid: str | None,
    industry_guid: str | None,
    theme_guids: list[str],
    peer_guids: list[str],
    open_gap_ids: list[str],
    contradictions: list[str],
    freshness_summary: str,
    source_mix: dict[str, int],
    source_sha: str,
    what_changed: str,
    next_review: str,
    material: bool,
    conclusion: str,
) -> dict[str, Any]:
    prev_ver = int((previous or {}).get("version") or 0)
    if material:
        kind = KIND_MATERIAL
        version = prev_ver + 1 if prev_ver >= 0 else 1
        curation_id = f"{security_guid or symbol}:v{version}"
    elif previous:
        kind = str(previous.get("kind") or KIND_BASELINE)
        version = prev_ver
        curation_id = str(previous.get("curation_id") or f"{security_guid or symbol}:v0:BASELINE")
    else:
        kind = KIND_BASELINE
        version = 0
        curation_id = f"{security_guid or symbol}:v0:BASELINE"
    return {
        "schema": SCHEMA,
        "kind": kind,
        "baseline_id": f"{security_guid or symbol}:baseline" if kind == KIND_BASELINE else (previous or {}).get("baseline_id"),
        "curation_id": curation_id,
        "security_guid": security_guid,
        "issuer_guid": issuer_guid,
        "listing_guid": listing_guid,
        "current_ticker_alias": symbol,
        "version": version,
        "previous_version": (prev_ver if previous else None),
        "created_at": _now(),
        "as_of": _now(),
        "source_sha": source_sha,
        "evidence_watermark": evidence_watermark,
        "previous_evidence_watermark": (previous or {}).get("evidence_watermark"),
        "current_symbol_thesis_id": None,
        "current_symbol_thesis_version": None,
        "portfolio_role": None,
        "current_conclusion": conclusion,
        "supporting_artifact_guids": support_guids,
        "contradictory_artifact_guids": counter_guids,
        "current_catalyst_guids": catalyst_guids,
        "calendar_event_guids": calendar_guids,
        "sector_guid": sector_guid,
        "industry_guid": industry_guid,
        "theme_guids": theme_guids,
        "peer_guids": peer_guids,
        "relevant_vertical_relationships": [],
        "open_research_gap_ids": open_gap_ids,
        "unresolved_contradictions": contradictions,
        "source_mix": source_mix,
        "source_quality_summary": "deterministic_rules_only",
        "freshness_summary": freshness_summary,
        "confidence": "low" if not support_guids else "medium",
        "materiality": "material" if material else "none",
        "what_changed": what_changed,
        "what_did_not_change": "content_hash_set" if not material else "",
        "next_review_condition": next_review,
        "last_provider_used": None,
        "last_model_used": None,
        "prompt_version": None,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def _rewrite(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _as_baseline(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    key = out.get("security_guid") or out.get("current_ticker_alias")
    out["kind"] = KIND_BASELINE
    out["version"] = 0
    out["previous_version"] = None
    out["materiality"] = "none"
    out["what_changed"] = "BASELINE_PROJECTION"
    out["curation_id"] = f"{key}:v0:BASELINE"
    out["baseline_id"] = f"{key}:baseline"
    return out


def upsert_summary(root: Path | str, summary: dict[str, Any], *, material: bool) -> dict[str, Any]:
    path = summary_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = load_latest(root, security_guid=summary.get("security_guid"), symbol=summary.get("current_ticker_alias"))
    if prev and prev.get("evidence_watermark") == summary.get("evidence_watermark"):
        return {"wrote": False, "reason": "NO_NEW_INFO", "summary": prev}
    rows = _load_rows(path)
    if not prev:
        baseline = _as_baseline(summary)
        rows.append(baseline)
        _rewrite(path, rows)
        if not material:
            return {"wrote": True, "reason": KIND_BASELINE, "summary": baseline}
        prev = baseline
    if not material:
        return {"wrote": False, "reason": "NO_NEW_INFO", "summary": prev}
    summary = dict(summary)
    summary["kind"] = KIND_MATERIAL
    prev_ver = int(prev.get("version") or 0)
    summary["version"] = prev_ver + 1
    summary["previous_version"] = prev_ver
    summary["baseline_id"] = prev.get("baseline_id")
    rows = _load_rows(path)
    rows.append(summary)
    _rewrite(path, rows)
    return {"wrote": True, "reason": KIND_MATERIAL, "summary": summary}
