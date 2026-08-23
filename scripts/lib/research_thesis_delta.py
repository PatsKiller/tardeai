"""ResearchThesisDelta@v1 and the accepted-research thesis bridge."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.research_prompt_context import delta_path, latest_delta
from scripts.lib.thesis_substantiveness import grade_text, join_research_text

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchThesisDelta@v1"
CLASSIFICATIONS = frozenset({
    "CONFIRMS", "STRENGTHENS", "WEAKENS", "INVALIDATES", "NO_NEW_INFO",
    "CONFLICTED", "INSUFFICIENT_DATA",
})
MATERIAL_CLASSIFICATIONS = frozenset({"STRENGTHENS", "WEAKENS", "INVALIDATES", "CONFLICTED"})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any, n: int = 24) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:n]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _evidence_ids(rows: Any, polarity: str) -> list[str]:
    out: list[str] = []
    for row in _as_list(rows):
        if isinstance(row, dict):
            eid = row.get("evidence_id") or row.get("source_id")
            content = row.get("text") or row.get("fact") or row.get("title") or row
        else:
            eid, content = None, row
        stable = str(eid or f"ev_{_digest({'polarity': polarity, 'content': content}, 16)}")
        if stable not in out:
            out.append(stable)
    return out


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def build_research_thesis_delta(
    symbol: str,
    result: dict[str, Any],
    *,
    prompt_context: dict[str, Any],
    research_id: str,
    provider: str | None = None,
    model: str | None = None,
    cost: dict[str, Any] | None = None,
    prior_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    prior = prior_delta
    recommendation = str(result.get("recommendation") or result.get("summary") or result.get("answer") or "").strip()
    dissent = str(result.get("dissent") or "").strip()
    evidence = result.get("evidence") or result.get("evidence_json") or []
    supporting = _evidence_ids(evidence, "SUPPORT")
    contradictory = _evidence_ids(result.get("contradictory_evidence") or ([dissent] if dissent else []), "CONTRADICTION")
    prior_ids = set((prior or {}).get("supporting_evidence_ids") or []) | set((prior or {}).get("contradictory_evidence_ids") or [])
    new_ids = [eid for eid in supporting + contradictory if eid not in prior_ids]
    changes = list(prompt_context.get("deterministic_changes_since_prior_review") or [])

    fingerprint_payload = {
        "recommendation": _norm_text(recommendation),
        "dissent": _norm_text(dissent),
        "supporting": supporting,
        "contradictory": contradictory,
        "what_changed": result.get("what_changed"),
        "invalidation_triggered": bool(result.get("invalidation_triggered")),
    }
    result_fp = _digest(fingerprint_payload, 32)
    explicit = str(result.get("classification") or "").upper().strip()
    confidence = _confidence(result.get("confidence"))
    grade = grade_text(sym, join_research_text(recommendation, dissent, evidence))

    if (prior or {}).get("result_fingerprint") == result_fp:
        classification = "NO_NEW_INFO"
    elif explicit in CLASSIFICATIONS:
        classification = explicit
    elif result.get("invalidation_triggered"):
        classification = "INVALIDATES"
    elif not recommendation or grade.get("grade") == "F" or confidence < 0.25:
        classification = "INSUFFICIENT_DATA"
    elif not new_ids and not changes and prior:
        classification = "NO_NEW_INFO"
    elif not (prompt_context.get("standing_thesis") or {}).get("version"):
        classification = "STRENGTHENS"
    else:
        classification = "CONFIRMS"

    source_quality = result.get("source_quality") or {
        "grade": grade.get("grade"),
        "bucket": grade.get("bucket"),
        "supporting_count": len(supporting),
        "contradictory_count": len(contradictory),
    }
    freshness = result.get("freshness") or {
        "evidence_as_of": result.get("evidence_as_of") or prompt_context.get("as_of"),
        "state": "CURRENT" if result.get("evidence_as_of") or prompt_context.get("as_of") else "UNKNOWN",
    }
    standing = prompt_context.get("standing_thesis") or {}
    delta_core = {
        "symbol": sym,
        "standing_thesis_id": standing.get("thesis_id"),
        "standing_thesis_version": standing.get("version"),
        "research_id": research_id,
        "result_fingerprint": result_fp,
        "classification": classification,
    }
    delta_id = "rtd_" + _digest(delta_core, 20)
    return {
        "schema": SCHEMA,
        "delta_id": delta_id,
        "symbol": sym,
        "standing_thesis_id": standing.get("thesis_id"),
        "standing_thesis_version": standing.get("version"),
        "evidence_as_of": result.get("evidence_as_of") or prompt_context.get("as_of"),
        "new_evidence_ids": new_ids,
        "supporting_evidence_ids": supporting,
        "contradictory_evidence_ids": contradictory,
        "deterministic_changes": changes,
        "deterministic_snapshot": prompt_context.get("deterministic_current_data") or {},
        "classification": classification,
        "confidence": confidence,
        "reason_summary": str(result.get("reason_summary") or recommendation)[:800],
        "what_changed": _as_list(result.get("what_changed"))[:12],
        "what_did_not_change": _as_list(result.get("what_did_not_change"))[:12],
        "research_gaps_remaining": _as_list(result.get("research_gaps") or result.get("research_gaps_remaining"))[:12],
        "invalidation_triggered": bool(result.get("invalidation_triggered")),
        "source_quality": source_quality,
        "freshness": freshness,
        "provider": provider or result.get("provider") or result.get("lane"),
        "model": model or result.get("model"),
        "cost": cost or result.get("cost") or {},
        "prompt_context_hash": prompt_context.get("prompt_context_hash"),
        "source_refs": _as_list(result.get("source_refs"))[:20],
        "research_id": research_id,
        "result_fingerprint": result_fp,
        "thesis_publish_eligible": bool(grade.get("grade") == "A" and classification in MATERIAL_CLASSIFICATIONS),
        "thesis_quality_grade": grade,
        "authority": AUTHORITY,
        "raw_chain_of_thought": False,
        "created_at": _now(),
    }


def _append_delta(delta: dict[str, Any], root: Path | str | None) -> bool:
    path = delta_path(root)
    if latest_delta(delta.get("symbol") or "", root=root) and any(
        row.get("delta_id") == delta.get("delta_id")
        for row in _read_rows(path)
    ):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(delta, sort_keys=True, default=str) + "\n")
    return True


def _read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def accept_research_result(
    symbol: str,
    result: dict[str, Any],
    *,
    prompt_context: dict[str, Any],
    research_id: str,
    root: Path | str | None = None,
    provider: str | None = None,
    model: str | None = None,
    trigger: str = "research_completion",
    run_id: str | None = None,
    source_sha: str | None = None,
) -> dict[str, Any]:
    """Persist one delta, publish only a quality-gated material thesis change."""
    prior = latest_delta(symbol, root=root)
    delta = build_research_thesis_delta(
        symbol,
        result,
        prompt_context=prompt_context,
        research_id=research_id,
        provider=provider,
        model=model,
        prior_delta=prior,
    )
    appended = _append_delta(delta, root)
    if not appended:
        return {"ok": True, "duplicate": True, "delta": delta, "version_published": False, "authority": AUTHORITY}

    if not delta["thesis_publish_eligible"]:
        return {
            "ok": True,
            "duplicate": False,
            "delta": delta,
            "version_published": False,
            "publish_suppressed_reason": (
                "no_material_change" if delta["classification"] in {"CONFIRMS", "NO_NEW_INFO"}
                else "evidence_quality_gate"
            ),
            "authority": AUTHORITY,
        }

    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis
    evidence = {
        "summary": result.get("recommendation") or result.get("thesis_summary") or result.get("summary"),
        "stance": result.get("thesis_stance") or result.get("stance"),
        "evidence_for": list(delta.get("supporting_evidence_ids") or []),
        "counter_evidence": list(delta.get("contradictory_evidence_ids") or []),
        "research_gaps": list(delta.get("research_gaps_remaining") or []),
        "research_result_id": research_id,
        "source_research_ids": [research_id],
        "research_delta": delta,
        "delta_classification": delta["classification"],
        "delta_id": delta["delta_id"],
        "writer": "research_thesis_delta",
        "writer_version": SCHEMA,
        "run_id": run_id,
        "source_sha": source_sha,
    }
    review = reconcile_symbol_thesis(
        symbol,
        trigger=trigger,
        evidence=evidence,
        root=root,
        publish=True,
        notify=False,
        actor_id="research_thesis_delta",
    )
    card = None
    if review.get("version_published"):
        try:
            from scripts.lib.cio_held_thesis_coverage import write_thesis_change_card
            kind = {
                "STRENGTHENS": "upgraded",
                "WEAKENS": "downgraded",
                "INVALIDATES": "invalidated",
                "CONFLICTED": "downgraded",
            }.get(delta["classification"], "revised")
            version = int(str(review.get("new_version") or "@v0").rsplit("@v", 1)[-1])
            card = write_thesis_change_card(
                symbol=str(symbol),
                thesis_id=str(review.get("thesis_id") or ""),
                version=version,
                kind=kind,
                summary=str(result.get("recommendation") or result.get("summary") or ""),
                grade=str((delta.get("thesis_quality_grade") or {}).get("grade") or ""),
                root=Path(root) if root is not None else Path(__file__).resolve().parents[2],
                emit_bus=True,
            )
        except Exception as exc:
            card = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
    response = {
        "ok": True,
        "duplicate": False,
        "delta": delta,
        "review": review,
        "version_published": bool(review.get("version_published")),
        "thesis_change_card": card,
        "authority": AUTHORITY,
    }
    for key in (
        "classification", "version_published", "old_version", "new_version",
        "thesis_id", "symbol",
    ):
        if key in review:
            response[key] = review.get(key)
    return response
