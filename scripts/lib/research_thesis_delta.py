"""ResearchThesisDelta@v1 and the accepted-research thesis bridge."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_question_ids import structured_answers
from scripts.lib.research_prompt_context import delta_path, latest_delta
from scripts.lib.thesis_substantiveness import grade_text, join_research_text

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchThesisDelta@v1"
CLASSIFICATIONS = frozenset({
    "CONFIRMS", "STRENGTHENS", "WEAKENS", "INVALIDATES", "NO_NEW_INFO",
    "CONFLICTED", "INSUFFICIENT_DATA",
})
MATERIAL_CLASSIFICATIONS = frozenset({"STRENGTHENS", "WEAKENS", "INVALIDATES", "CONFLICTED"})
ENRICHES = "ENRICHES"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_INTENT_CONFIG = _REPO_ROOT / "assets/portfolio_intent.yaml"
# Fallback only; the operator values live in assets/portfolio_intent.yaml
# options_desk_settings.symbol_thesis_enrich (same pattern as options_thesis_lifecycle).
ENRICH_DEFAULTS: dict[str, Any] = {
    "scope": "options_horizon",
    "cooldown_hours": 24,
    "invalidation_cap": 8,
    "catalyst_cap": 8,
    "evidence_cap": 60,
    "item_max_chars": 2000,
    "machine_writers": [
        "research_thesis_delta", "thesis_mint_from_research", "thesis_mint_dryrun",
        "symbol_thesis_canary", "symbol_thesis_freshness",
    ],
}
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


def enrich_settings(override: dict[str, Any] | None = None) -> dict[str, Any]:
    """ENRICHES thresholds from portfolio_intent.yaml; `override` wins (tests)."""
    blk: dict[str, Any] = {}
    try:
        import yaml
        cfg = yaml.safe_load(_INTENT_CONFIG.read_text(encoding="utf-8")) or {}
        blk = ((cfg.get("options_desk_settings") or {}).get("symbol_thesis_enrich") or {})
    except Exception:
        blk = {}
    out = {k: blk.get(k, v) for k, v in ENRICH_DEFAULTS.items()}
    out.update(override or {})
    return out


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
    from scripts.lib.research_metadata import build_research_metadata
    metadata_inputs = prompt_context.get("metadata_inputs") or {}
    metadata = build_research_metadata(
        symbol=sym,
        symbol_profile=metadata_inputs.get("symbol_profile") or {},
        market_data=metadata_inputs.get("market_data") or {},
        analyst_data=metadata_inputs.get("analyst_data") or {},
        judgment=result.get("judgment_tags") or result.get("tags") or {},
        provider=str(provider or result.get("provider") or result.get("lane") or "UNKNOWN"),
        model=str(model or result.get("model") or "UNKNOWN"),
        research_id=research_id,
    )
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
        "metadata": metadata,
        "research_id": research_id,
        "result_fingerprint": result_fp,
        "thesis_publish_eligible": bool(grade.get("grade") == "A" and classification in MATERIAL_CLASSIFICATIONS),
        "thesis_quality_grade": grade,
        "authority": AUTHORITY,
        "raw_chain_of_thought": False,
        "created_at": _now(),
    }



def _index_delta(delta: dict[str, Any], symbol: str) -> dict[str, Any]:
    try:
        try:
            import research_index_writer as riw  # type: ignore
        except ImportError:
            from scripts.lib import research_index_writer as riw  # type: ignore
        guid = None
        try:
            try:
                import intelligence_client as ic  # type: ignore
            except ImportError:
                from scripts.lib import intelligence_client as ic  # type: ignore
            ent = ic.default_loaders().resolve_subject(symbol)
            guid = (ent or {}).get("security_guid") or (ent or {}).get("guid")
        except Exception:  # noqa: BLE001
            guid = None
        if not guid:
            return {"pg": "skipped", "reason": "IDENTITY_UNRESOLVED"}
        return riw.index_delta(delta, subject_guid=str(guid))
    except Exception as exc:  # noqa: BLE001
        return {"pg": "error", "error": f"{type(exc).__name__}:{str(exc)[:120]}"}

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


def _thesis_store(root: Path | str | None):
    from scripts.lib.cio_theses import CIOThesisStore
    base = Path(root) if root is not None else _REPO_ROOT
    return CIOThesisStore(
        event_path=base / "data/cio/cio_theses.jsonl",
        projection_path=base / "data/cio/cio_theses_projection.json",
    )


def _field(thesis: dict[str, Any] | None, key: str) -> Any:
    """A structured field lives top-level on the record, or under legacy `extra`."""
    thesis = thesis or {}
    if thesis.get(key) is not None:
        return thesis.get(key)
    extra = thesis.get("extra") if isinstance(thesis.get("extra"), dict) else {}
    return extra.get(key)


def _merge_ids(old: Any, new: Any, cap: int) -> list[str]:
    out: list[str] = []
    for eid in list(_as_list(old)) + list(_as_list(new)):
        s = str(eid)
        if s and s not in out:
            out.append(s)
    return out[-cap:] if cap > 0 else out  # newest kept


def _merge_texts(old: Any, new: str | None, cap: int, max_chars: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in list(_as_list(old)) + ([new] if new else []):
        text = str(t or "").strip()[:max_chars]
        key = _norm_text(text)
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return out[:cap]  # prior (possibly authored) conditions are never evicted by new text


def _latest_date(text: str) -> date | None:
    found = []
    for y, m, d in _ISO_DATE.findall(text or ""):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return max(found) if found else None


def _merge_catalysts(
    old: Any, new_text: str | None, *, research_id: str, as_of: Any,
    cap: int, max_chars: int, today: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [dict(c) for c in _as_list(old) if isinstance(c, dict) and c.get("text")]
    if new_text:
        text = new_text.strip()[:max_chars]
        row: dict[str, Any] = {"text": text, "as_of": as_of, "source_research_id": research_id}
        when = _latest_date(text)
        if when:
            row["event_date"] = when.isoformat()
        rows.append(row)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        when = _latest_date(str(row.get("event_date") or "")) or _latest_date(str(row.get("text") or ""))
        if when and when < today:
            continue  # every date it names is past: the catalyst has happened
        key = _norm_text(row.get("text"))
        if key and key not in seen:
            seen.add(key)
            out.append(row)
    return out[:cap]


def _machine_summary(thesis: dict[str, Any] | None, cfg: dict[str, Any]) -> bool:
    """True when the standing summary may be replaced by research text."""
    if not thesis:
        return True
    if str(thesis.get("summary") or "").startswith("RESEARCH_REQUIRED:"):
        return True
    writer = (_field(thesis, "write_provenance") or {}).get("writer")
    if writer:
        return str(writer) in set(cfg.get("machine_writers") or [])
    return bool(thesis.get("mint_state"))  # thesis_mint_from_research predates write_provenance


def _enrich_cooldown_ok(store: Any, thesis_id: str, cfg: dict[str, Any], now: datetime) -> bool:
    hours = float(cfg.get("cooldown_hours") or 0)
    if hours <= 0:
        return True
    for row in store.list_versions(thesis_id, limit=200):
        if (_field(row, "write_provenance") or {}).get("trigger") != ENRICHES:
            continue
        try:
            ts = datetime.fromisoformat(str(row.get("published_ts")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() >= hours * 3600
    return True


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
    source_result_id: str | None = None,
    enrich_config: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist one delta, publish only a quality-gated material thesis change.

    Per-question answers (q_thesis_check / q_catalyst_map / q_invalidation /
    q_bear_case) feed the symbol thesis: invalidation and catalysts are merged
    into the standing lists, the bear case becomes a contradictory evidence id,
    and evidence lists are merged old+new. When the existing gates would not
    publish, the governed ENRICHES rule may still fill EMPTY invalidation /
    catalyst fields (operator 2026-09-26) without touching stance or summary.
    """
    cfg = enrich_settings(enrich_config)
    now = now or datetime.now(timezone.utc)
    cap_chars = int(cfg["item_max_chars"])
    answers = structured_answers(result)
    # Ring 2 (01 §2): every research write carries the MemoryContext it was produced under.
    _ctx_id = result.get("context_id") or (prompt_context or {}).get("context_id")
    try:
        try:
            from memory_ring2 import check as _ring2_check, MemoryContextRequired as _MCR  # type: ignore
        except ImportError:  # pragma: no cover
            from scripts.lib.memory_ring2 import check as _ring2_check, MemoryContextRequired as _MCR  # type: ignore
        _r2 = _ring2_check("accept_research_result", f"research:{research_id}", _ctx_id,
                           extra={"symbol": symbol, "retrieval_receipt_id": result.get("retrieval_receipt_id")})
    except _MCR as exc:
        return {"ok": False, "refused": True, "refusal_reason": "MEMORY_CONTEXT_MISSING", "detail": str(exc)[:200],
                "version_published": False, "research_id": research_id, "symbol": symbol, "authority": AUTHORITY}
    except Exception:  # noqa: BLE001
        _r2 = {"decision": "ALLOW"}
    from scripts.lib.symbol_thesis_coverage import symbol_thesis_id
    store = _thesis_store(root)
    thesis_id = symbol_thesis_id(str(symbol or "").upper().strip())
    standing = store.get_current(thesis_id)

    # (c) bear case -> contradictory evidence BEFORE the delta, so it gets an ev id.
    work = dict(result)
    evidence_text: dict[str, str] = {}
    bear = answers.get("bear_case")
    if bear:
        dissent = str(result.get("dissent") or "").strip()
        base = list(_as_list(result.get("contradictory_evidence"))) or ([dissent] if dissent else [])
        row = {"text": bear[:cap_chars], "kind": "bear_case"}
        work["contradictory_evidence"] = base + [row]
        evidence_text[_evidence_ids([row], "CONTRADICTION")[0]] = row["text"]

    prior = latest_delta(symbol, root=root)
    delta = build_research_thesis_delta(
        symbol,
        work,
        prompt_context=prompt_context,
        research_id=research_id,
        provider=provider,
        model=model,
        prior_delta=prior,
    )
    appended = _append_delta(delta, root)
    if not appended:
        return {"ok": True, "duplicate": True, "delta": delta, "version_published": False, "authority": AUTHORITY}
    # Wave 2 item 8 (pkg-20260928-wave-2-enforcement-35c4): deterministic + citation index rows for the
    # accepted delta (03 §3 steps 1 and 5). Fail-soft; the delta row above is canonical.
    delta["research_index"] = _index_delta(delta, symbol)

    contradiction_result = None
    try:
        from scripts.lib.research_contradiction import persist_candidates
        root_path = Path(root) if root is not None else Path(__file__).resolve().parents[2]
        contradiction_result = persist_candidates(
            _read_rows(delta_path(root)),
            path=root_path / "data/cio/research_contradiction_candidates.jsonl",
            new_records=[delta],
        )
    except Exception as exc:
        contradiction_result = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}

    # (a)/(b) merged lists: standing entries first, research answers appended.
    prior_inval = list(_as_list(_field(standing, "invalidation_conditions")))
    prior_cats = list(_as_list(_field(standing, "catalysts")))
    merged_inval = _merge_texts(prior_inval, answers.get("invalidation"),
                                int(cfg["invalidation_cap"]), cap_chars)
    merged_cats = _merge_catalysts(
        prior_cats, answers.get("catalysts"), research_id=research_id,
        as_of=result.get("evidence_as_of") or result.get("as_of") or now.isoformat(),
        cap=int(cfg["catalyst_cap"]), max_chars=cap_chars, today=now.date(),
    )
    merged_text = {**dict(_field(standing, "evidence_text") or {}), **evidence_text}
    provenance_keys = {
        "research_result_id": research_id,
        "source_research_ids": [research_id],
        "source_result_id": source_result_id,
        "research_delta": delta,
        "delta_id": delta["delta_id"],
        "writer": "research_thesis_delta",
        "writer_version": SCHEMA,
        "run_id": run_id,
        "source_sha": source_sha,
        "context_id": _ctx_id,
        "retrieval_receipt_id": result.get("retrieval_receipt_id"),
        "memory_context_miss": _r2.get("decision") == "ALLOW_MISS",
    }
    grade = str((delta.get("thesis_quality_grade") or {}).get("grade") or "")
    enrich_fields: dict[str, Any] = {}
    if standing and grade == "A" and delta["classification"] != "INSUFFICIENT_DATA":
        if not prior_inval and merged_inval:
            enrich_fields["invalidation_conditions"] = merged_inval
        if not prior_cats and merged_cats:
            enrich_fields["catalysts"] = merged_cats

    from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis
    enriched = False
    if not delta["thesis_publish_eligible"]:
        suppressed = (
            "no_material_change" if delta["classification"] in {"CONFIRMS", "NO_NEW_INFO"}
            else "evidence_quality_gate"
        )
        if not enrich_fields:
            return {
                "ok": True,
                "duplicate": False,
                "delta": delta,
                "version_published": False,
                "publish_suppressed_reason": suppressed,
                "contradiction_candidates": contradiction_result,
                "authority": AUTHORITY,
            }
        if not _enrich_cooldown_ok(store, thesis_id, cfg, now):
            return {
                "ok": True,
                "duplicate": False,
                "delta": delta,
                "version_published": False,
                "publish_suppressed_reason": "enrich_cooldown",
                "enrich_fields": sorted(enrich_fields),
                "contradiction_candidates": contradiction_result,
                "authority": AUTHORITY,
            }
        # ENRICHES: only the empty fields; stance, summary, evidence and role inherited.
        evidence = {
            **enrich_fields,
            **provenance_keys,
            "delta_classification": ENRICHES,
            "scope": cfg["scope"],
        }
        role = _field(standing, "portfolio_role")
        if role:
            evidence["portfolio_role"] = role
        review = reconcile_symbol_thesis(
            symbol,
            trigger=ENRICHES,
            evidence=evidence,
            root=root,
            publish=True,
            notify=False,
            actor_id="research_thesis_delta",
        )
        enriched = bool(review.get("version_published"))
    else:
        evidence_cap = int(cfg["evidence_cap"])
        evidence = {
            # (d) merged old+new, never new-only
            "evidence_for": _merge_ids(_field(standing, "evidence_for"),
                                       delta.get("supporting_evidence_ids"), evidence_cap),
            "counter_evidence": _merge_ids(_field(standing, "counter_evidence"),
                                           delta.get("contradictory_evidence_ids"), evidence_cap),
            "invalidation_conditions": merged_inval,
            "catalysts": merged_cats,
            "stance": result.get("thesis_stance") or result.get("stance"),
            "research_gaps": list(delta.get("research_gaps_remaining") or []),
            **provenance_keys,
            "delta_classification": delta["classification"],
        }
        evidence["evidence_text"] = {k: v for k, v in merged_text.items()
                                     if k in set(evidence["counter_evidence"]) | set(evidence["evidence_for"])}
        # (e) research text replaces only a machine / placeholder summary; an
        # authored summary is omitted here so reconcile inherits it.
        if _machine_summary(standing, cfg):
            evidence["summary"] = (
                answers.get("thesis") or result.get("recommendation")
                or result.get("thesis_summary") or result.get("summary")
            )
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
            }.get(ENRICHES if enriched else delta["classification"], "revised")
            version = int(str(review.get("new_version") or "@v0").rsplit("@v", 1)[-1])
            card = write_thesis_change_card(
                symbol=str(symbol),
                thesis_id=str(review.get("thesis_id") or ""),
                version=version,
                kind=kind,
                summary=(
                    f"Filled empty {', '.join(sorted(enrich_fields))} from research {research_id}"
                    if enriched else str(result.get("recommendation") or result.get("summary") or "")
                ),
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
        "enriched": enriched,
        "enrich_fields": sorted(enrich_fields) if enriched else [],
        "thesis_change_card": card,
        "contradiction_candidates": contradiction_result,
        "authority": AUTHORITY,
    }
    for key in (
        "classification", "version_published", "old_version", "new_version",
        "thesis_id", "symbol",
    ):
        if key in review:
            response[key] = review.get(key)
    return response
