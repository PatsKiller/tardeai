"""CIO ↔ Hermes structured research contracts (WS2/WS3).

schema: hermes_request@v1 / hermes_result@v1
READ_ONLY_ADVISORY — research only, never orders/stops.

De-duplication path:
  canonicalize → hash (fp@v1) → in-flight lookup → priority bump
  → optional TTL reuse of fresh completed → create

Storage:
  data/cio/hermes_research_requests.jsonl
  data/cio/hermes_research_results.jsonl
  data/cio/hermes_research_projection.json
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from lib.hermes_research_fingerprint import (
        compute_fingerprint,
        compute_fingerprint_from_parts,
    )
    from lib.hermes_research_policy import parse_ts
    from lib.hermes_research_queue import (
        IN_FLIGHT,
        TERMINAL,
        EnqueueResult,
        enqueue_research_request as _enqueue_core,
        supersede_open_jobs_for_plan,
    )
except ImportError:  # pragma: no cover
    from scripts.lib.hermes_research_fingerprint import (  # type: ignore
        compute_fingerprint,
        compute_fingerprint_from_parts,
    )
    from scripts.lib.hermes_research_policy import parse_ts  # type: ignore
    from scripts.lib.hermes_research_queue import (  # type: ignore
        IN_FLIGHT,
        TERMINAL,
        EnqueueResult,
        enqueue_research_request as _enqueue_core,
        supersede_open_jobs_for_plan,
    )

SCHEMA_REQUEST = "hermes_request@v1"
SCHEMA_RESULT = "hermes_result@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

REQUEST_PATH = Path("data/cio/hermes_research_requests.jsonl")
RESULT_PATH = Path("data/cio/hermes_research_results.jsonl")
PROJECTION_PATH = Path("data/cio/hermes_research_projection.json")

PRIORITIES = frozenset({"critical", "high", "normal", "low"})
STATUSES = frozenset({
    "queued", "started", "running", "completed", "failed", "superseded", "cancelled",
})

EXEC_LINT = re.compile(
    r"\b(buy now|sell now|place stop|place order|submit order|execute trade|force fill)\b",
    re.I,
)

# Re-export for callers / tests
__all__ = [
    "SCHEMA_REQUEST",
    "SCHEMA_RESULT",
    "IN_FLIGHT",
    "TERMINAL",
    "EnqueueResult",
    "fingerprint_request",
    "compute_fingerprint",
    "default_questions_for_plan",
    "enqueue_research_request",
    "complete_research_result",
    "latest_research_for_plan",
    "hermes_research_evidence_ref",
    "find_in_flight_by_fingerprint",
    "find_latest_completed_by_fingerprint",
    "supersede_open_jobs_for_plan",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def fingerprint_request(
    *,
    plan_id: str,
    situation_type: str,
    symbol: str,
    thesis_version: str,
    questions: list[str],
) -> str:
    """Public fingerprint helper (fp@v1 sha256). Preferred over legacy fp_ prefix."""
    return compute_fingerprint_from_parts(
        plan_id=plan_id,
        situation_type=situation_type,
        symbol=symbol,
        thesis_version=thesis_version,
        questions=questions,
    )


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _empty_projection() -> dict[str, Any]:
    return {
        "by_research_id": {},
        "by_plan_id": {},
        "by_fingerprint_open": {},      # fp → open request summary
        "by_fingerprint_completed": {},  # fp → latest completed result summary
        "updated_ts": None,
    }


def _load_projection() -> dict[str, Any]:
    if not PROJECTION_PATH.exists():
        return _empty_projection()
    try:
        proj = json.loads(PROJECTION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _empty_projection()
    proj.setdefault("by_research_id", {})
    proj.setdefault("by_plan_id", {})
    proj.setdefault("by_fingerprint_open", {})
    proj.setdefault("by_fingerprint_completed", {})
    return proj


def _save_projection(proj: dict[str, Any]) -> None:
    PROJECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    proj["updated_ts"] = _now()
    tmp = PROJECTION_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(proj, indent=2, default=str), encoding="utf-8")
    tmp.replace(PROJECTION_PATH)


def default_questions_for_plan(plan: dict[str, Any]) -> list[dict[str, str]]:
    """Deterministic question set from situation type (intent vocabulary)."""
    st = str(plan.get("situation_type") or "")
    syms = [str(s).upper() for s in (plan.get("symbols") or []) if s]
    sym = syms[0] if syms else "BOOK"
    if "S6" in st or "CONCENTRATION" in st:
        return [
            {"intent": "drift_attribution", "text": f"Is {sym} weight drift price-driven or flow-driven?"},
            {"intent": "catalyst_map", "text": f"What catalysts land for {sym} in the next 10 sessions?"},
            {"intent": "invalidation", "text": f"What invalidation level keeps hold_with_thesis valid for {sym}?"},
        ]
    if "S1" in st or "LIFECYCLE" in st:
        return [
            {"intent": "catalyst_map", "text": f"What catalysts could change the {sym} drawdown thesis?"},
            {"intent": "invalidation", "text": f"What price/basis invalidation upgrades {sym} from awareness-only?"},
            {"intent": "thesis_check", "text": f"Does multi-domain evidence still support hold on {sym} under defensive_observe?"},
        ]
    if "S5" in st or "CASH" in st:
        return [
            {"intent": "deployment_candidates", "text": "Which staged deployment candidates have multi-domain support without force-fill?"},
            {"intent": "regime", "text": "Does current regime support staging cash or is hold_cash highest-signal?"},
            {"intent": "liquidity", "text": "Any liquidity or settlement constraints on a first stage slice?"},
        ]
    return [
        {"intent": "thesis_check", "text": f"What research would change the advisory on {sym} under the live desk thesis?"},
    ]


# ── projection helpers used by enqueue core ──────────────────────────────────

def find_in_flight_by_fingerprint(fp: str) -> Optional[dict[str, Any]]:
    """Return open (queued/running/started) request for fingerprint, if any."""
    proj = _load_projection()
    row = (proj.get("by_fingerprint_open") or {}).get(fp)
    if row and row.get("status") in IN_FLIGHT:
        return row
    # Fallback: scan by_research_id (migration from older projections)
    for rec in (proj.get("by_research_id") or {}).values():
        if rec.get("fingerprint") == fp and rec.get("status") in IN_FLIGHT:
            return rec
    return None


def find_latest_completed_by_fingerprint(fp: str) -> Optional[dict[str, Any]]:
    """Return latest completed result summary for fingerprint (for TTL reuse)."""
    proj = _load_projection()
    row = (proj.get("by_fingerprint_completed") or {}).get(fp)
    if not row:
        return None
    status = str(row.get("status") or "completed").lower()
    if status in ("failed", "cancelled", "superseded"):
        return None
    # Prefer full result body when available (answers/findings for quality gate)
    result_id = row.get("result_id")
    if result_id and RESULT_PATH.exists():
        try:
            for line in reversed(RESULT_PATH.read_text(encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("result_id") == result_id:
                    merged = {**row, **r, "status": "completed", "fingerprint": fp}
                    return merged
        except Exception:
            pass
    return {**row, "status": "completed", "fingerprint": fp}


def _list_open_by_plan(plan_id: str) -> list[dict[str, Any]]:
    proj = _load_projection()
    bp = (proj.get("by_plan_id") or {}).get(plan_id) or {}
    out: list[dict[str, Any]] = []
    for rid in bp.get("open") or []:
        rec = (proj.get("by_research_id") or {}).get(rid)
        if rec and rec.get("status") in IN_FLIGHT:
            out.append(rec)
    return out


def _patch_request(research_id: str, patch: dict[str, Any]) -> None:
    proj = _load_projection()
    rec = (proj.get("by_research_id") or {}).get(research_id)
    if not rec:
        return
    rec.update(patch)
    proj["by_research_id"][research_id] = rec
    fp = rec.get("fingerprint")
    status = rec.get("status")
    if fp:
        open_idx = proj.setdefault("by_fingerprint_open", {})
        if status in IN_FLIGHT:
            open_idx[fp] = {
                "research_id": research_id,
                "plan_id": rec.get("plan_id"),
                "symbol": rec.get("symbol"),
                "status": status,
                "fingerprint": fp,
                "priority": rec.get("priority"),
                "created_ts": rec.get("created_ts"),
                "thesis_version": rec.get("thesis_version"),
            }
        else:
            open_idx.pop(fp, None)
            # also clear if this rid was indexed under fp
            cur = open_idx.get(fp)
            if cur and cur.get("research_id") == research_id:
                open_idx.pop(fp, None)
    # plan open list
    pid = rec.get("plan_id")
    if pid and status not in IN_FLIGHT:
        bp = proj.setdefault("by_plan_id", {}).setdefault(pid, {"open": [], "latest_result_id": None})
        bp["open"] = [x for x in (bp.get("open") or []) if x != research_id]
    _save_projection(proj)
    _append_jsonl(REQUEST_PATH, {
        "event": "HERMES_RESEARCH_PATCHED",
        "research_id": research_id,
        **{k: v for k, v in patch.items()},
        "updated_ts": patch.get("updated_ts") or _now(),
    })


def _save_new_request(req: dict[str, Any]) -> None:
    research_id = req["research_id"]
    pid = req["plan_id"]
    fp = req["fingerprint"]
    pri = req.get("priority") or "normal"
    _append_jsonl(REQUEST_PATH, {"event": "HERMES_RESEARCH_REQUESTED", **req})
    _append_jsonl(REQUEST_PATH, {
        "event": "HERMES_RESEARCH_ENQUEUE",
        "created": True,
        "reason": "created",
        "research_id": research_id,
        "fingerprint": fp,
        "plan_id": pid,
        "priority": pri,
        "reuse_miss_reason": req.get("reuse_miss_reason"),
    })
    proj = _load_projection()
    by_rid = proj.setdefault("by_research_id", {})
    by_rid[research_id] = {
        "research_id": research_id,
        "plan_id": pid,
        "symbol": req.get("symbol"),
        "status": "queued",
        "fingerprint": fp,
        "priority": pri,
        "created_ts": req.get("created_ts"),
        "thesis_version": req.get("thesis_version"),
        "situation_type": req.get("situation_type"),
        "catalyst_event_ids": list(req.get("known_catalyst_event_ids") or [])[:40],
    }
    bp = proj.setdefault("by_plan_id", {}).setdefault(pid, {"open": [], "latest_result_id": None})
    opens = list(bp.get("open") or [])
    if research_id not in opens:
        opens.append(research_id)
    bp["open"] = opens[-20:]
    proj.setdefault("by_fingerprint_open", {})[fp] = dict(by_rid[research_id])
    _save_projection(proj)


def _record_reuse_event(event: dict[str, Any]) -> None:
    _append_jsonl(REQUEST_PATH, event)


def _log_enqueue(result: EnqueueResult, plan_id: str, priority: str) -> None:
    """Append HERMES_RESEARCH_ENQUEUE for non-create paths (create logs in _save_new_request)."""
    if result.reason == "created":
        return
    evt = dict(result.log_event) if result.log_event else {
        "event": "HERMES_RESEARCH_ENQUEUE",
        "created": result.created,
        "reason": result.reason,
        "research_id": result.research_id,
        "fingerprint": result.fingerprint,
        "plan_id": plan_id,
        "priority": priority,
    }
    if result.result_id:
        evt.setdefault("result_id", result.result_id)
    if result.age_seconds is not None:
        evt.setdefault("age_seconds", result.age_seconds)
    if result.ttl_seconds is not None:
        evt.setdefault("ttl_seconds", result.ttl_seconds)
    _append_jsonl(REQUEST_PATH, evt)


def enqueue_research_request(
    plan: dict[str, Any],
    *,
    reason: str = "",
    priority: str = "normal",
    questions: Optional[list[dict[str, str]]] = None,
    operator_forced: bool = False,
    force_refresh: bool = False,
    replace_open: bool = False,
    actor_id: str = "cio_research_emitter",
    enable_ttl_reuse: bool = True,
) -> dict[str, Any]:
    """Create de-duplicated ResearchRequest. Fail-soft returns ok=False.

    Reasons: created | duplicate_in_flight | priority_bumped | reused_fresh_result
    """
    try:
        pid = str(plan.get("plan_id") or "").strip()
        if not pid:
            return {"ok": False, "error": "plan_id_required"}
        pri = (priority or "normal").lower()
        if pri not in PRIORITIES:
            pri = "normal"
        st = str(plan.get("situation_type") or "")
        syms = [str(s).upper() for s in (plan.get("symbols") or []) if s]
        symbol = syms[0] if syms else "BOOK"
        thesis = str(plan.get("thesis_version") or "")
        qlist = questions or default_questions_for_plan(plan)
        q_norm: list[dict[str, str]] = []
        for i, q in enumerate(qlist[:6]):
            if isinstance(q, dict):
                text = str(q.get("text") or "").strip()
                if not text:
                    continue
                q_norm.append({
                    "question_id": str(q.get("question_id") or q.get("id") or f"q{i+1}"),
                    "intent": str(q.get("intent") or "thesis_check")[:40],
                    "text": text[:280],
                })
            else:
                text = str(q).strip()
                if not text:
                    continue
                q_norm.append({
                    "question_id": f"q{i+1}",
                    "intent": "thesis_check",
                    "text": text[:280],
                })
        if not q_norm:
            return {"ok": False, "error": "questions_required"}

        # Catalyst pack for TTL invalidation (medium+ add/change after result as_of)
        cat_pack = plan.get("_catalyst_pack") or plan.get("catalyst")
        if not isinstance(cat_pack, dict):
            for r in plan.get("evidence_refs") or []:
                if isinstance(r, dict) and r.get("domain") == "catalyst":
                    cat_pack = r
                    break
        inv_signals: list[str] = []
        if isinstance(cat_pack, dict) and cat_pack.get("events"):
            try:
                try:
                    from lib.catalyst_domain import catalyst_invalidation_signals
                except Exception:
                    from scripts.lib.catalyst_domain import catalyst_invalidation_signals  # type: ignore
                # known ids empty → any medium+ event within horizon is a potential invalidate
                # vs a prior result (checked fully in try_reuse against result as_of)
                inv_signals = list(
                    plan.get("invalidation_signals") or []
                )
            except Exception:
                inv_signals = list(plan.get("invalidation_signals") or [])

        request: dict[str, Any] = {
            "schema_version": SCHEMA_REQUEST,
            "plan_id": pid,
            "goal_id": (plan.get("linked_goal_ids") or [None])[0],
            "symbol": symbol,
            "symbols": syms[:4],
            "situation_type": st,
            "thesis_version": thesis,
            "priority": pri,
            "reason": (reason or f"Material {st} on {symbol}")[:400],
            "questions": q_norm,
            "success_criteria": (
                "Findings that would change hold/stage vs size-review under live desk thesis"
            ),
            "needed_by": None,
            "operator_forced": bool(operator_forced),
            "force_refresh": bool(force_refresh or operator_forced),
            "authority": AUTHORITY,
            "actor_id": actor_id,
            "subject": {
                "symbol": symbol,
                "symbols": syms[:4],
                "scope": "symbol" if symbol and symbol != "BOOK" else "book",
                "situation_type": st,
            },
            "provenance": {"operator_forced": bool(operator_forced), "actor_id": actor_id},
        }
        if isinstance(cat_pack, dict):
            request["catalyst"] = cat_pack
            request["catalyst_pack"] = cat_pack
            # Known event ids at enqueue time — stamped onto projection for complete
            eids = [
                str(e.get("event_id"))
                for e in (cat_pack.get("events") or [])
                if isinstance(e, dict) and e.get("event_id")
            ]
            request["known_catalyst_event_ids"] = eids
        if inv_signals:
            request["invalidation_signals"] = inv_signals

        result = _enqueue_core(
            request,
            find_in_flight_by_fingerprint=find_in_flight_by_fingerprint,
            save_request=_save_new_request,
            update_request=_patch_request,
            new_research_id=lambda: _new_id("res"),
            find_fresh_completed=(
                find_latest_completed_by_fingerprint if enable_ttl_reuse else None
            ),
            record_reuse_event=_record_reuse_event,
            replace_open=bool(replace_open and operator_forced),
            list_open_by_plan=_list_open_by_plan if replace_open else None,
        )
        _log_enqueue(result, pid, pri)

        out: dict[str, Any] = {
            "ok": True,
            "created": result.created,
            "deduped": not result.created and result.reason in (
                "duplicate_in_flight", "priority_bumped",
            ),
            "reused": result.reason == "reused_fresh_result",
            "reason": result.reason,
            "research_id": result.research_id,
            "fingerprint": result.fingerprint,
            "status": result.status,
        }
        if result.reason == "created":
            out["request"] = request
            out["deduped"] = False
        if result.existing is not None:
            out["existing"] = {
                k: result.existing.get(k)
                for k in (
                    "research_id", "result_id", "status", "priority",
                    "as_of", "completed_ts", "summary", "findings",
                )
                if result.existing.get(k) is not None
            }
        if result.result_id:
            out["result_id"] = result.result_id
        if result.age_seconds is not None:
            out["age_seconds"] = result.age_seconds
        if result.ttl_seconds is not None:
            out["ttl_seconds"] = result.ttl_seconds
        if result.reuse_miss_reason:
            out["reuse_miss_reason"] = result.reuse_miss_reason
        return out
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}:{e}"}


def complete_research_result(
    research_id: str,
    *,
    answers: list[dict[str, Any]],
    findings: Optional[list[str]] = None,
    desk_implications: Optional[dict[str, Any]] = None,
    summary: str = "",
    actor_id: str = "hermes_worker",
) -> dict[str, Any]:
    """Append ResearchResult and mark request completed. Lint execution language."""
    try:
        proj = _load_projection()
        req_meta = (proj.get("by_research_id") or {}).get(research_id)
        if not req_meta:
            return {"ok": False, "error": "unknown_research_id"}
        blob = json.dumps({"a": answers, "f": findings, "s": summary, "d": desk_implications}, default=str)
        if EXEC_LINT.search(blob):
            return {"ok": False, "error": "execution_language_in_result"}
        result_id = _new_id("rr")
        as_of = _now()
        # Stamp catalyst event ids seen at completion (for TTL invalidation diffs)
        cat_event_ids: list[str] = []
        for src in (
            req_meta.get("catalyst_event_ids"),
        ):
            if isinstance(src, list):
                cat_event_ids.extend(str(x) for x in src if x)
        result = {
            "schema_version": SCHEMA_RESULT,
            "result_id": result_id,
            "research_id": research_id,
            "plan_id": req_meta.get("plan_id"),
            "symbol": req_meta.get("symbol"),
            "fingerprint": req_meta.get("fingerprint"),
            "as_of": as_of,
            "completed_ts": as_of,
            "status": "completed",
            "answers": answers[:12],
            "findings": list(findings or [])[:12],
            "desk_implications": desk_implications or {},
            "summary": (summary or "")[:800],
            "authority": AUTHORITY,
            "created_ts": as_of,
            "actor_id": actor_id,
            "catalyst_event_ids": cat_event_ids[:40],
        }
        _append_jsonl(RESULT_PATH, {"event": "HERMES_RESEARCH_COMPLETED", **result})

        # Update request meta → terminal
        req_meta["status"] = "completed"
        req_meta["latest_result_id"] = result_id
        req_meta["completed_ts"] = as_of
        proj["by_research_id"][research_id] = req_meta

        fp = req_meta.get("fingerprint")
        if fp:
            # remove from in-flight index
            open_idx = proj.setdefault("by_fingerprint_open", {})
            cur = open_idx.get(fp)
            if cur and cur.get("research_id") == research_id:
                open_idx.pop(fp, None)
            # upsert completed-by-fingerprint (keep newest as_of)
            completed_idx = proj.setdefault("by_fingerprint_completed", {})
            prev = completed_idx.get(fp)
            prev_ts = parse_ts((prev or {}).get("as_of") or (prev or {}).get("completed_ts"))
            new_ts = parse_ts(as_of)
            if prev is None or (new_ts and (prev_ts is None or new_ts >= prev_ts)):
                completed_idx[fp] = {
                    "result_id": result_id,
                    "research_id": research_id,
                    "plan_id": req_meta.get("plan_id"),
                    "symbol": req_meta.get("symbol"),
                    "fingerprint": fp,
                    "status": "completed",
                    "as_of": as_of,
                    "completed_ts": as_of,
                    "summary": result.get("summary"),
                    "findings": result.get("findings"),
                    "catalyst_event_ids": list(result.get("catalyst_event_ids") or []),
                }

        pid = req_meta.get("plan_id")
        if pid:
            bp = proj.setdefault("by_plan_id", {}).setdefault(pid, {"open": [], "latest_result_id": None})
            bp["latest_result_id"] = result_id
            bp["latest_as_of"] = as_of
            bp["open"] = [x for x in (bp.get("open") or []) if x != research_id]
        _save_projection(proj)

        _append_jsonl(REQUEST_PATH, {
            "event": "HERMES_RESEARCH_COMPLETED",
            "research_id": research_id,
            "result_id": result_id,
            "plan_id": pid,
            "fingerprint": fp,
            "status": "completed",
            "updated_ts": as_of,
        })
        return {"ok": True, "result_id": result_id, "result": result}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}:{e}"}


def latest_research_for_plan(plan_id: str) -> dict[str, Any]:
    """Projection helper for evidence assembler / plan page."""
    proj = _load_projection()
    bp = (proj.get("by_plan_id") or {}).get(plan_id) or {}
    rid = bp.get("latest_result_id")
    open_ids = list(bp.get("open") or [])
    result = None
    if rid and RESULT_PATH.exists():
        try:
            for line in reversed(RESULT_PATH.read_text(encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("result_id") == rid:
                    result = row
                    break
        except Exception:
            result = None
    return {
        "plan_id": plan_id,
        "open": open_ids,
        "latest_result_id": rid,
        "latest_as_of": bp.get("latest_as_of"),
        "latest_result": result,
    }


def hermes_research_evidence_ref(
    plan_id: str,
    *,
    reused: bool = False,
    reuse_age_seconds: Optional[float] = None,
    ttl_seconds: Optional[int] = None,
) -> dict[str, Any]:
    """Build evidence_refs domain entry for enrich / plan page."""
    info = latest_research_for_plan(plan_id)
    ref: dict[str, Any] = {
        "domain": "hermes_research_findings",
        "as_of": info.get("latest_as_of") or _now()[:19],
        "fields_used": [],
        "quality_state": "DATA_UNAVAILABLE",
        "open_research_ids": info.get("open") or [],
    }
    res = info.get("latest_result")
    if not res:
        ref["gap_reason"] = "no_completed_research"
        return ref
    ref["quality_state"] = "OK"
    ref["result_id"] = res.get("result_id")
    ref["research_id"] = res.get("research_id")
    if res.get("fingerprint"):
        ref["fingerprint"] = res.get("fingerprint")
    if reused:
        ref["reused"] = True
        if reuse_age_seconds is not None:
            ref["reuse_age_seconds"] = reuse_age_seconds
        if ttl_seconds is not None:
            ref["ttl_seconds"] = ttl_seconds
    for k in ("summary", "findings", "desk_implications", "answers"):
        if res.get(k) is not None:
            ref[k] = res.get(k)
            ref["fields_used"].append(k)
    ref["as_of"] = str(res.get("as_of") or ref["as_of"])[:19]
    return ref
