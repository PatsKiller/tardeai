"""reconcile_symbol_thesis — material content review over CIOThesisStore.

Uses existing architecture only. Publishes a new symbol_* version only when
content materially changes. READ_ONLY_ADVISORY. Never grants RE_ENTER.
Never mutates broker/order/stop/risk/2FA.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.portfolio_role import resolve_portfolio_role
from scripts.lib.symbol_thesis_coverage import classify_symbol, symbol_thesis_id
from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
from scripts.lib.symbol_universe import reconcile_universe

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolThesisReview@v1"

CLASSIFICATIONS = (
    "THESIS_CONFIRMED",
    "THESIS_STRENGTHENED",
    "THESIS_WEAKENED",
    "THESIS_BROKEN",
    "NO_MATERIAL_CHANGE",
    "CONFLICTED",
    "INSUFFICIENT_DATA",
)

# Soft stance ordering for strengthen/weaken classification
_STANCE_RANK = {
    "avoid": 0,
    "do_not_reenter": 0,
    "retired": 0,
    "trim": 1,
    "wait": 2,
    "watch": 2,
    "hold": 3,
    "add": 4,
    "reenter": 4,
    "buy": 4,
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _norm_text(v: Any) -> str:
    return " ".join(str(v or "").strip().lower().split())


def _content_fingerprint(payload: dict[str, Any]) -> str:
    keys = (
        "summary", "stance", "why_owned_or_watched", "why_exited",
        "what_changed_since_exit", "evidence_for", "counter_evidence",
        "invalidation_conditions", "research_gaps", "what_changes_my_mind",
        "portfolio_role",
    )
    slim = {k: payload.get(k) for k in keys}
    return _digest(json.dumps(slim, sort_keys=True, default=str))


def _extract_extra(thesis: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not thesis:
        return {}
    extra = dict(thesis.get("extra") or {}) if isinstance(thesis.get("extra"), dict) else {}
    out = {}
    for k in (
        "why_owned_or_watched", "why_exited", "what_changed_since_exit",
        "evidence_for", "counter_evidence", "invalidation_conditions",
        "research_gaps", "what_changes_my_mind", "portfolio_role",
        "universe_memberships",
    ):
        if k in thesis and thesis.get(k) is not None:
            out[k] = thesis.get(k)
        elif k in extra:
            out[k] = extra.get(k)
    return out


def _classify(
    *,
    old: Optional[dict[str, Any]],
    new_fp: str,
    old_fp: Optional[str],
    new_stance: str,
    coverage_state: str,
    evidence: dict[str, Any],
) -> str:
    delta_classification = str(evidence.get("delta_classification") or "").upper()
    governed_delta = {
        "CONFIRMS": "NO_MATERIAL_CHANGE",
        "STRENGTHENS": "THESIS_STRENGTHENED",
        "WEAKENS": "THESIS_WEAKENED",
        "INVALIDATES": "THESIS_BROKEN",
        "NO_NEW_INFO": "NO_MATERIAL_CHANGE",
        "CONFLICTED": "CONFLICTED",
        "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
    }
    if delta_classification in governed_delta:
        return governed_delta[delta_classification]
    if coverage_state == "CONFLICTED":
        return "CONFLICTED"
    if not old:
        # First review with insufficient evidence → INSUFFICIENT_DATA
        if not (evidence.get("summary") or "").strip() or len((evidence.get("summary") or "").strip()) < 40:
            return "INSUFFICIENT_DATA"
        return "THESIS_STRENGTHENED"  # establishing a living thesis is material
    if old_fp and new_fp == old_fp:
        return "NO_MATERIAL_CHANGE"
    if coverage_state == "INSUFFICIENT_DATA" and not (evidence.get("summary") or "").strip():
        return "INSUFFICIENT_DATA"

    old_stance = str((old or {}).get("stance") or "").lower()
    ns = str(new_stance or "").lower()
    old_r = _STANCE_RANK.get(old_stance, 2)
    new_r = _STANCE_RANK.get(ns, 2)

    # Explicit broken signals
    broken_markers = ("broken", "invalidated", "thesis broken", "do not reenter")
    summary_l = _norm_text(evidence.get("summary"))
    if ns in {"avoid", "do_not_reenter", "retired"} and old_r >= 3:
        return "THESIS_BROKEN"
    if any(m in summary_l for m in broken_markers) and old_r >= 2:
        return "THESIS_BROKEN"
    if new_r > old_r:
        return "THESIS_STRENGTHENED"
    if new_r < old_r:
        return "THESIS_WEAKENED"
    # Content changed but stance same
    if evidence.get("counter_evidence") and not (_extract_extra(old).get("counter_evidence")):
        return "THESIS_WEAKENED"
    if evidence.get("evidence_for") and len(list(evidence.get("evidence_for") or [])) > len(
        list(_extract_extra(old).get("evidence_for") or [])
    ):
        return "THESIS_STRENGTHENED"
    return "THESIS_CONFIRMED"


def reconcile_symbol_thesis(
    symbol: str,
    *,
    trigger: str = "manual_review",
    evidence: Optional[dict[str, Any]] = None,
    root: Path | str | None = None,
    store: CIOThesisStore | None = None,
    publish: bool = True,
    notify: bool = False,
    actor_id: str = "symbol_thesis_review",
) -> dict[str, Any]:
    """Review / refactor one symbol thesis.

    evidence may include:
      summary, stance, why_owned_or_watched, why_exited, what_changed_since_exit,
      evidence_for, counter_evidence, invalidation_conditions, research_gaps,
      what_changes_my_mind, portfolio_role, research_result, fs_receipts,
      ratified_lessons, memory_refs, market_temperament, sector_context,
      financial_truth_refs, operator_input.

    Publishes a new CIOThesisStore version ONLY for material content changes.
    """
    root = _root(root)
    sym = str(symbol or "").upper().strip()
    evidence = dict(evidence or {})
    tid = symbol_thesis_id(sym)

    store = store or CIOThesisStore(
        event_path=root / "data/cio/cio_theses.jsonl",
        projection_path=root / "data/cio/cio_theses_projection.json",
    )
    try:
        universe = reconcile_universe(root)
        uni = (universe.get("symbols") or {}).get(sym) or {"memberships": [], "held": False}
    except Exception:
        uni = {"memberships": [], "held": False}

    old = store.get_current(tid)
    old_extra = _extract_extra(old)
    cov = classify_symbol(sym, universe_rec=uni, store=store, root=root)
    role = resolve_portfolio_role(sym, universe_rec=uni, thesis_rec=old, root=root)

    # Merge: evidence overrides; else inherit prior
    summary = (evidence.get("summary") or (old or {}).get("summary") or "").strip()
    stance = (evidence.get("stance") or (old or {}).get("stance") or "").strip()
    merged = {
        "summary": summary,
        "stance": stance,
        "why_owned_or_watched": evidence.get("why_owned_or_watched")
            if "why_owned_or_watched" in evidence else old_extra.get("why_owned_or_watched") or "",
        "why_exited": evidence.get("why_exited")
            if "why_exited" in evidence else old_extra.get("why_exited") or "",
        "what_changed_since_exit": evidence.get("what_changed_since_exit")
            if "what_changed_since_exit" in evidence else old_extra.get("what_changed_since_exit") or "",
        "evidence_for": list(
            evidence.get("evidence_for")
            if "evidence_for" in evidence else (old_extra.get("evidence_for") or [])
        ),
        "counter_evidence": list(
            evidence.get("counter_evidence")
            if "counter_evidence" in evidence else (old_extra.get("counter_evidence") or [])
        ),
        "invalidation_conditions": list(
            evidence.get("invalidation_conditions")
            if "invalidation_conditions" in evidence else (old_extra.get("invalidation_conditions") or [])
        ),
        "research_gaps": list(
            evidence.get("research_gaps")
            if "research_gaps" in evidence else (old_extra.get("research_gaps") or [])
        ),
        "what_changes_my_mind": list(
            evidence.get("what_changes_my_mind")
            if "what_changes_my_mind" in evidence else (old_extra.get("what_changes_my_mind") or [])
        ),
        "portfolio_role": (
            evidence.get("portfolio_role")
            or role.get("portfolio_role")
            or old_extra.get("portfolio_role")
            or "UNKNOWN"
        ),
    }

    # Attach context refs (non-authoritative)
    context_refs = {
        "trigger": trigger,
        "financial_truth_refs": list(evidence.get("financial_truth_refs") or []),
        "fs_receipts": list(evidence.get("fs_receipts") or []),
        "ratified_lessons": list(evidence.get("ratified_lessons") or []),
        "memory_refs": list(evidence.get("memory_refs") or []),
        "market_temperament": evidence.get("market_temperament"),
        "sector_context": evidence.get("sector_context"),
        "research_result_id": evidence.get("research_result_id") or evidence.get("result_id"),
        "operator_input": evidence.get("operator_input"),
        "reviewed_at": _now(),
    }

    old_fp = _content_fingerprint({
        "summary": (old or {}).get("summary"),
        "stance": (old or {}).get("stance"),
        **{k: old_extra.get(k) for k in (
            "why_owned_or_watched", "why_exited", "what_changed_since_exit",
            "evidence_for", "counter_evidence", "invalidation_conditions",
            "research_gaps", "what_changes_my_mind", "portfolio_role",
        )},
    }) if old else None
    new_fp = _content_fingerprint(merged)

    classification = _classify(
        old=old,
        new_fp=new_fp,
        old_fp=old_fp,
        new_stance=stance,
        coverage_state=str(cov.get("coverage_state") or ""),
        evidence=merged,
    )

    published = None
    version_published = False
    if publish and classification not in {"NO_MATERIAL_CHANGE", "INSUFFICIENT_DATA"}:
        # Material change → publish new version
        change_note = (
            f"{classification} via {trigger}; "
            f"old_stance={(old or {}).get('stance') or 'none'} → {stance or 'none'}"
        )
        published = publish_symbol_thesis(
            sym,
            summary=summary or f"RESEARCH_REQUIRED: living thesis for {sym} incomplete.",
            stance=stance,
            portfolio_role=str(merged["portfolio_role"]),
            universe_memberships=list(uni.get("memberships") or []),
            why_owned_or_watched=str(merged["why_owned_or_watched"] or ""),
            why_exited=str(merged["why_exited"] or ""),
            what_changed_since_exit=str(merged["what_changed_since_exit"] or ""),
            evidence_for=list(merged["evidence_for"] or []),
            counter_evidence=list(merged["counter_evidence"] or []),
            invalidation_conditions=list(merged["invalidation_conditions"] or []),
            research_gaps=list(merged["research_gaps"] or []),
            what_changes_my_mind=list(merged["what_changes_my_mind"] or []),
            owner_agent="alex",
            change_note=change_note,
            store=store,
            notify=notify,
            actor_id=actor_id,
            provenance={
                "writer": evidence.get("writer") or actor_id,
                "writer_version": evidence.get("writer_version") or SCHEMA,
                "source_research_ids": list(evidence.get("source_research_ids") or []),
                "delta_id": evidence.get("delta_id"),
                "trigger": trigger,
                "run_id": evidence.get("run_id"),
                "source_sha": evidence.get("source_sha"),
                "previous_version": (old or {}).get("thesis_version"),
                "reason_for_change": change_note,
            },
        )
        # stash context on published extra via a follow-up is not needed —
        # publish_symbol_thesis already stores structured extra. Append refs into learning?
        version_published = True
    elif classification == "INSUFFICIENT_DATA" and publish and not old:
        # Do not churn empty versions — report only
        version_published = False

    return {
        "schema": SCHEMA,
        "symbol": sym,
        "thesis_id": tid,
        "trigger": trigger,
        "classification": classification,
        "version_published": version_published,
        "old_version": (old or {}).get("thesis_version"),
        "new_version": (published or {}).get("thesis_version") if published else (old or {}).get("thesis_version"),
        "old_stance": (old or {}).get("stance"),
        "new_stance": stance or None,
        "content_fingerprint": new_fp,
        "prior_fingerprint": old_fp,
        "coverage_state_before": cov.get("coverage_state"),
        "portfolio_role": merged["portfolio_role"],
        "memberships": list(uni.get("memberships") or []),
        "context_refs": context_refs,
        "authority": AUTHORITY,
        "financial_action": False,
        "as_of": _now(),
    }


def daily_thesis_changes(
    *,
    root: Path | str | None = None,
    store: CIOThesisStore | None = None,
    since_hours: float = 24.0,
) -> dict[str, Any]:
    """Summarize material symbol-thesis changes for daily CIO product.

    Does NOT emit unchanged symbols. Reads CIOThesisStore event log / versions.
    """
    root = _root(root)
    store = store or CIOThesisStore(
        event_path=root / "data/cio/cio_theses.jsonl",
        projection_path=root / "data/cio/cio_theses_projection.json",
    )
    cutoff = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
    buckets: dict[str, list[dict[str, Any]]] = {
        "NEW": [],
        "STRENGTHENED": [],
        "WEAKENED": [],
        "BROKEN": [],
        "RESEARCH_REQUIRED": [],
        "CONFLICTED": [],
        "RETIRED": [],
        "OTHER": [],
    }
    # Walk active symbol_* theses and recent versions
    for cur in store.list_active(limit=500):
        tid = str(cur.get("thesis_id") or "")
        if not tid.startswith("symbol_"):
            continue
        ts = cur.get("published_ts") or cur.get("updated_ts") or ""
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.timestamp() < cutoff:
                continue
        except Exception:
            continue
        note = str(cur.get("change_note") or "").upper()
        stance = str(cur.get("stance") or "").lower()
        row = {
            "symbol": (cur.get("symbol") or tid.replace("symbol_", "").upper()),
            "thesis_id": tid,
            "thesis_version": cur.get("thesis_version"),
            "stance": cur.get("stance"),
            "change_note": cur.get("change_note"),
            "published_ts": ts,
        }
        if "THESIS_BROKEN" in note or stance in {"avoid", "do_not_reenter"}:
            buckets["BROKEN"].append(row)
        elif "THESIS_WEAKENED" in note or stance == "trim":
            buckets["WEAKENED"].append(row)
        elif "THESIS_STRENGTHENED" in note or int(cur.get("version") or 0) == 1:
            buckets["NEW" if int(cur.get("version") or 0) == 1 else "STRENGTHENED"].append(row)
        elif "CONFLICTED" in note:
            buckets["CONFLICTED"].append(row)
        elif "RETIRED" in note or (cur.get("status") or "") == "archived":
            buckets["RETIRED"].append(row)
        elif "RESEARCH" in note:
            buckets["RESEARCH_REQUIRED"].append(row)
        else:
            buckets["OTHER"].append(row)

    return {
        "schema": "DailyThesisChanges@v1",
        "as_of": _now(),
        "since_hours": since_hours,
        "counts": {k: len(v) for k, v in buckets.items()},
        "changes": {k: v for k, v in buckets.items() if v},
        "authority": AUTHORITY,
        "financial_action": False,
    }
