"""CIO ↔ Hermes structured research contracts (WS2/WS3 MVP).

schema: hermes_request@v1 / hermes_result@v1
READ_ONLY_ADVISORY — research only, never orders/stops.

Storage:
  data/cio/hermes_research_requests.jsonl
  data/cio/hermes_research_results.jsonl
  data/cio/hermes_research_projection.json
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_REQUEST = "hermes_request@v1"
SCHEMA_RESULT = "hermes_result@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

REQUEST_PATH = Path("data/cio/hermes_research_requests.jsonl")
RESULT_PATH = Path("data/cio/hermes_research_results.jsonl")
PROJECTION_PATH = Path("data/cio/hermes_research_projection.json")

PRIORITIES = frozenset({"high", "normal", "low"})
STATUSES = frozenset({
    "queued", "started", "completed", "failed", "superseded", "cancelled",
})

EXEC_LINT = re.compile(
    r"\b(buy now|sell now|place stop|place order|submit order|execute trade|force fill)\b",
    re.I,
)


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
    qnorm = "|".join(" ".join(str(q).lower().split()) for q in questions if str(q).strip())
    raw = f"{plan_id}|{situation_type}|{symbol}|{thesis_version}|{qnorm}"
    return "fp_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _load_projection() -> dict[str, Any]:
    if not PROJECTION_PATH.exists():
        return {"by_research_id": {}, "by_plan_id": {}, "updated_ts": None}
    try:
        return json.loads(PROJECTION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"by_research_id": {}, "by_plan_id": {}, "updated_ts": None}


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


def enqueue_research_request(
    plan: dict[str, Any],
    *,
    reason: str = "",
    priority: str = "normal",
    questions: Optional[list[dict[str, str]]] = None,
    operator_forced: bool = False,
    actor_id: str = "cio_research_emitter",
) -> dict[str, Any]:
    """Create de-duplicated ResearchRequest. Fail-soft returns ok=False."""
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
        qtexts = [str(q.get("text") if isinstance(q, dict) else q).strip() for q in qlist]
        qtexts = [q for q in qtexts if q][:6]
        if not qtexts:
            return {"ok": False, "error": "questions_required"}
        # normalize questions with ids
        q_norm = []
        for i, q in enumerate(qlist[:6]):
            if isinstance(q, dict):
                q_norm.append({
                    "question_id": q.get("question_id") or f"q{i+1}",
                    "intent": str(q.get("intent") or "thesis_check")[:40],
                    "text": str(q.get("text") or "")[:280],
                })
            else:
                q_norm.append({
                    "question_id": f"q{i+1}",
                    "intent": "thesis_check",
                    "text": str(q)[:280],
                })
        fp = fingerprint_request(
            plan_id=pid,
            situation_type=st,
            symbol=symbol,
            thesis_version=thesis,
            questions=[q["text"] for q in q_norm],
        )
        # de-dupe: open request with same fingerprint
        proj = _load_projection()
        by_plan = (proj.get("by_plan_id") or {}).get(pid) or {}
        for rid in by_plan.get("open") or []:
            rec = (proj.get("by_research_id") or {}).get(rid) or {}
            if rec.get("fingerprint") == fp and rec.get("status") in ("queued", "started"):
                return {
                    "ok": True,
                    "deduped": True,
                    "research_id": rid,
                    "fingerprint": fp,
                    "status": rec.get("status"),
                }

        research_id = _new_id("res")
        req = {
            "schema_version": SCHEMA_REQUEST,
            "research_id": research_id,
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
            "status": "queued",
            "fingerprint": fp,
            "operator_forced": bool(operator_forced),
            "authority": AUTHORITY,
            "created_ts": _now(),
            "updated_ts": _now(),
            "actor_id": actor_id,
        }
        _append_jsonl(REQUEST_PATH, {"event": "HERMES_RESEARCH_REQUESTED", **req})
        # projection
        by_rid = proj.setdefault("by_research_id", {})
        by_rid[research_id] = {
            "research_id": research_id,
            "plan_id": pid,
            "symbol": symbol,
            "status": "queued",
            "fingerprint": fp,
            "priority": pri,
            "created_ts": req["created_ts"],
            "thesis_version": thesis,
        }
        bp = proj.setdefault("by_plan_id", {}).setdefault(pid, {"open": [], "latest_result_id": None})
        opens = list(bp.get("open") or [])
        if research_id not in opens:
            opens.append(research_id)
        bp["open"] = opens[-20:]
        _save_projection(proj)
        return {"ok": True, "deduped": False, "research_id": research_id, "request": req}
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
        result = {
            "schema_version": SCHEMA_RESULT,
            "result_id": result_id,
            "research_id": research_id,
            "plan_id": req_meta.get("plan_id"),
            "symbol": req_meta.get("symbol"),
            "as_of": _now(),
            "answers": answers[:12],
            "findings": list(findings or [])[:12],
            "desk_implications": desk_implications or {},
            "summary": (summary or "")[:800],
            "authority": AUTHORITY,
            "created_ts": _now(),
            "actor_id": actor_id,
        }
        _append_jsonl(RESULT_PATH, {"event": "HERMES_RESEARCH_COMPLETED", **result})
        req_meta["status"] = "completed"
        req_meta["latest_result_id"] = result_id
        req_meta["completed_ts"] = result["as_of"]
        proj["by_research_id"][research_id] = req_meta
        pid = req_meta.get("plan_id")
        if pid:
            bp = proj.setdefault("by_plan_id", {}).setdefault(pid, {"open": [], "latest_result_id": None})
            bp["latest_result_id"] = result_id
            bp["latest_as_of"] = result["as_of"]
            bp["open"] = [x for x in (bp.get("open") or []) if x != research_id]
        _save_projection(proj)
        # also mark request file event
        _append_jsonl(REQUEST_PATH, {
            "event": "HERMES_RESEARCH_COMPLETED",
            "research_id": research_id,
            "result_id": result_id,
            "plan_id": pid,
            "status": "completed",
            "updated_ts": _now(),
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
        # scan tail for result_id (MVP; small files)
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


def hermes_research_evidence_ref(plan_id: str) -> dict[str, Any]:
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
    for k in ("summary", "findings", "desk_implications", "answers"):
        if res.get(k) is not None:
            ref[k] = res.get(k)
            ref["fields_used"].append(k)
    ref["as_of"] = str(res.get("as_of") or ref["as_of"])[:19]
    return ref
