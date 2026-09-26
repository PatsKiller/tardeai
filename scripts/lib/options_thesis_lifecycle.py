"""Move every options thesis to a tracked outcome (operator 2026-09-26).

"Insufficient data should not sit indefinitely." Each pass advances a thesis one
step, using only real queues:

  CREATED -> RESEARCH_QUEUED (Hermes CIO research; measured p50 ~12 min)
          -> RESEARCH_COMPLETE (answers: catalysts, invalidation, bear case, thesis)
          -> CIO_REVIEW_QUEUED / DECISION_ISSUED (options_cio_review, Decision GUID)
          -> or ARCHIVED_ABANDONED after ``abandon_after_hours`` with the reason.

Queue position and ETA come from the Hermes projection and the worker cadence in
config, never from a guess. Advisory only: nothing sizes or orders.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable, Optional

ANSWER_MAP = {
    "q_catalyst_map": "catalysts",
    "q_invalidation": "invalidation",
    "q_bear_case": "bear_case",
    "q_thesis_check": "thesis",
}

DEFAULTS = {
    "abandon_after_hours": 48,
    "research_rerequest_hours": 24,
    "cio_review_mode": "dry",
    "max_reviews_per_run": 6,
    "research_priority": "high",
    "research_drain_per_tick": 2,
    "research_tick_minutes": 15,
}


def settings(cfg: Optional[dict[str, Any]]) -> dict[str, Any]:
    blk = (cfg or {}).get("options_thesis_lifecycle") or {}
    return {k: blk.get(k, v) for k, v in DEFAULTS.items()}


def research_questions(p: dict[str, Any]) -> list[dict[str, str]]:
    sym = str(p.get("symbol") or "").upper()
    strat = str(p.get("strategy") or "").replace("_", " ")
    return [
        {"intent": "thesis_check", "text": f"What is the investment thesis for {sym} that would justify a {strat}, and what would break it?"},
        {"intent": "catalyst_map", "text": f"What dated catalysts (earnings, events, filings) fall before {p.get('expiration')} for {sym}?"},
        {"intent": "invalidation", "text": f"What specific evidence would invalidate the {sym} thesis and should trigger exiting the {strat}?"},
        {"intent": "bear_case", "text": f"What is the strongest bear case against {sym} over the next {p.get('dte')} days?"},
    ]


def answers_from_result(result: Optional[dict[str, Any]], research_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {"research_id": research_id}
    for a in (result or {}).get("answers") or []:
        key = ANSWER_MAP.get(str(a.get("question_id") or ""))
        if not key or str(a.get("status") or "").lower() == "unanswered":
            continue
        text = " ".join(x for x in (str(a.get("summary") or "").strip(), str(a.get("detail") or "").strip()) if x)
        if text:
            out[key] = text[:600]
    return out


def queue_position(projection: dict[str, Any], research_id: str, s: dict[str, Any]) -> dict[str, Any]:
    rows = [(r.get("created_ts") or "", rid) for rid, r in (projection.get("by_research_id") or {}).items()
            if str(r.get("status") or "").lower() in ("queued", "running", "pending")]
    rows.sort()
    ids = [rid for _, rid in rows]
    if research_id not in ids:
        return {"position": None, "of": len(ids), "eta_minutes": None}
    pos = ids.index(research_id) + 1
    per, tick = max(1, int(s["research_drain_per_tick"])), max(1, int(s["research_tick_minutes"]))
    return {"position": pos, "of": len(ids), "eta_minutes": math.ceil(pos / per) * tick + tick}


def _hours_since(ts: Optional[str], now: datetime) -> float:
    if not ts:
        return 0.0
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (now - t).total_seconds() / 3600.0


def advance(
    proposals: list[dict[str, Any]],
    store: Any,
    cfg: Optional[dict[str, Any]],
    *,
    request_research: Callable[[dict[str, Any]], dict[str, Any]],
    research_status: Callable[[str], dict[str, Any]],
    review_fn: Callable[[dict[str, Any], str], dict[str, Any]],
    record_decision: Callable[[dict[str, Any]], None],
    apply: bool,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """One pass. Returns what it did (or would do, when apply=False)."""
    now = now or datetime.now(timezone.utc)
    s = settings(cfg)
    report: list[dict[str, Any]] = []
    reviews = 0
    for p in proposals:
        guid = p.get("option_strategy_guid")
        ot = p.get("options_thesis") or {}
        if not guid or not ot.get("pin"):
            continue
        life = store.lifecycle(guid)
        if life.get("abandoned") or life.get("decision"):
            continue
        missing = list(ot.get("missing_required") or [])
        age = _hours_since(life.get("created_at"), now)
        step: dict[str, Any] = {"symbol": p.get("symbol"), "position_guid": guid, "pin": ot.get("pin")}
        # Research cannot fix liquidity: an idea with a non-thesis enterprise block
        # (OI 0, 185% spread) is not researched or reviewed (2026-09-26 dry test).
        ent_blocks = [b for b in ((p.get("enterprise") or {}).get("blocks") or [])
                      if not str((b or {}).get("code", "") if isinstance(b, dict) else b).startswith(("thesis_", "awaiting_cio"))]
        if ent_blocks:
            step.update(action="SKIP_ENTERPRISE_BLOCK", reason="blocked for liquidity or risk; research cannot clear it")
            report.append(step)
            continue
        if missing:
            if age >= float(s["abandon_after_hours"]):
                step.update(action="ABANDON", reason=f"no complete thesis within {s['abandon_after_hours']}h; "
                                                      f"still missing: {', '.join(missing)}")
                if apply:
                    store.append_event(guid, "OPTIONS_THESIS_ABANDONED", reason=step["reason"], missing=missing)
                report.append(step)
                continue
            req = life.get("research_request")
            done = life.get("research")
            if req and not done:
                st = research_status(req.get("research_id"))
                state = str(st.get("status") or "").lower()
                if state == "completed":
                    ans = answers_from_result(st.get("result"), req.get("research_id"))
                    step.update(action="RESEARCH_COMPLETE", answers=sorted(k for k in ans if k != "research_id"))
                    if apply:
                        store.append_event(guid, "OPTIONS_THESIS_RESEARCH_COMPLETE",
                                           research_id=req.get("research_id"), answers=ans)
                elif state == "failed" and _hours_since(req.get("recorded_at"), now) >= float(s["research_rerequest_hours"]):
                    step.update(action="RESEARCH_REREQUEST", prior=req.get("research_id"))
                    if apply:
                        out = request_research(p)
                        store.append_event(guid, "OPTIONS_THESIS_RESEARCH_REQUESTED",
                                           research_id=out.get("research_id"), plan_id=out.get("plan_id"))
                else:
                    step.update(action="WAIT_RESEARCH", status=state or "unknown")
                report.append(step)
                continue
            if not req:
                step.update(action="REQUEST_RESEARCH", missing=missing)
                if apply:
                    out = request_research(p)
                    store.append_event(guid, "OPTIONS_THESIS_RESEARCH_REQUESTED",
                                       research_id=out.get("research_id"), plan_id=out.get("plan_id"),
                                       missing=missing)
                report.append(step)
                continue
            # research done but gaps remain: wait for abandonment or a re-run of the desk
            step.update(action="RESEARCH_DONE_GAPS_REMAIN", missing=missing)
            report.append(step)
            continue
        if reviews >= int(s["max_reviews_per_run"]):
            step.update(action="REVIEW_DEFERRED", reason="max_reviews_per_run reached")
            report.append(step)
            continue
        reviews += 1
        mode = str(s["cio_review_mode"])
        if not apply:
            step.update(action="CIO_REVIEW", mode=mode)
            report.append(step)
            continue
        res = review_fn(p, mode)
        if res.get("status") == "OK":
            r = res["review"]
            store.append_event(guid, "OPTIONS_THESIS_DECISION", decision_guid=res["decision_guid"],
                               outcome=r["outcome"], confidence=r.get("confidence"), review=r,
                               model=res.get("model"), reviewed_pin=ot.get("pin"))
            record_decision(res)
            step.update(action="DECISION", outcome=r["outcome"], decision_guid=res["decision_guid"])
        else:
            if not any(t.get("stage") == "CIO_REVIEW_QUEUED" for t in life.get("timeline") or []):
                store.append_event(guid, "OPTIONS_THESIS_CIO_REVIEW_QUEUED", mode=mode, status=res.get("status"))
            step.update(action="CIO_REVIEW_NOT_ISSUED", status=res.get("status"), errors=res.get("errors"))
        report.append(step)
    return report
