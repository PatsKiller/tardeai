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

import re

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

try:  # one map for the lifecycle and the symbol-thesis bridge
    from scripts.lib.cio_question_ids import ANSWER_MAP
except ImportError:  # run as scripts/options_thesis_lifecycle.py (scripts/ on sys.path)
    from lib.cio_question_ids import ANSWER_MAP  # type: ignore[no-redef]

DEFAULTS = {
    "abandon_after_hours": 48,
    "research_rerequest_hours": 24,
    "cio_review_mode": "dry",
    "max_reviews_per_run": 6,
    "research_priority": "high",
    "research_drain_per_tick": 2,
    "research_tick_minutes": 15,
    "review_max_tokens": 2500,
    "followup_due_hours": 24,
    "max_followup_rounds": 2,
    "monitor_recheck_hours": 24,
    "max_deliverables": 5,
    # CIO review reads prior options facts from bitemporal memory (M2). Env
    # MEMORY_BEHAVIOR_INFLUENCE_OPTIONS, when set, overrides this.
    "memory_reads": False,
    "memory_reads_limit": 8,
    "memory_reads_lookback_days": 180,
    # Operator 2026-09-26: "if web unsure use chatgpt grok deepseek". Follow-up answers
    # still weak after web research go to the Hermes external researcher lanes in order.
    "escalation_enabled": False,
    "escalation_lanes": ["chatgpt", "grok", "deepseek"],
    "escalation_min_answered_ratio": 0.6,   # share of deliverables fully "answered"
    "escalation_min_cited_urls": 2,         # web urls cited across the answers
    "escalation_timeout_s": 300,            # per lane
    "escalation_max_per_run": 1,
    # 2026-09-27: DELL ran 11 research requests in 26h -- each new strike/expiry is a new
    # strategy GUID, and each GUID asked again. Research is about the SYMBOL: reuse a
    # same-symbol, same-strategy thesis request, and join an in-flight CIO follow-up.
    "research_reuse_hours": 24,
    "followup_reuse_hours": 6,
}


def memory_settings(s: dict[str, Any]) -> dict[str, Any]:
    """The ``memory`` argument options_cio_review.review/build_facts takes."""
    return {"memory_reads": s.get("memory_reads"), "limit": s.get("memory_reads_limit"),
            "lookback_days": s.get("memory_reads_lookback_days")}


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


def followup_questions(p: dict[str, Any], review: dict[str, Any], limit: int) -> list[dict[str, str]]:
    """Turn the CIO's unknowns and concerns into named research deliverables."""
    sym = str(p.get("symbol") or "").upper()
    items: list[str] = []
    for key in ("unknowns", "concerns", "assumptions_challenged"):
        for x in (review or {}).get(key) or []:
            t = str(x).strip()
            if t and t not in items:
                items.append(t)
    # 2026-09-26: the concerns were pasted in as statements ("DELL: No authored DELL
    # thesis ...") and research answered "Confirmed: no thesis exists". Each one is
    # now a research task, and a symbol with no standing thesis also gets the four
    # thesis questions, whose answers feed the living symbol thesis (ANSWER_MAP).
    base = research_questions(p) if str(p.get("thesis_state") or "").upper() == "INSUFFICIENT_DATA" else []
    tasks = [{"intent": f"cio_followup_{i + 1}",
              "text": f"{sym}: find dated, sourced facts that resolve this CIO concern "
                      f"(do not restate it): {t}"} for i, t in enumerate(items[:limit])]
    return base + tasks


REUSABLE_STATES = ("queued", "running", "in_progress", "claimed", "completed")
FOLLOWUP_MARK = ": find dated, sourced facts that resolve this CIO concern"


def reusable_request(requests: list[dict[str, Any]], *, symbol: str, first_text: str, kind: str,
                     now: datetime, hours: float) -> Optional[dict[str, Any]]:
    """A recent request for the same symbol that answers the same thing, or None.

    kind "thesis": the first question text is identical (it names symbol and strategy,
    never the strike). kind "followup": an in-flight CIO follow-up for the symbol."""
    best = None
    for r in requests or []:
        syms = [str(x).upper() for x in (r.get("symbols") or [r.get("symbol")]) if x]
        if symbol.upper() not in syms:
            continue
        status = str(r.get("status") or "").lower()
        if status not in REUSABLE_STATES or _hours_since(r.get("created_ts"), now) > float(hours):
            continue
        qs = r.get("questions") or []
        first = str((qs[0] or {}).get("text") or "") if qs else ""
        if kind == "thesis":
            ok = first == first_text
        else:
            ok = status != "completed" and any(FOLLOWUP_MARK in str((q or {}).get("text") or "") for q in qs)
        if ok and (best is None or str(r.get("created_ts") or "") > str(best.get("created_ts") or "")):
            best = r
    return best


def followup_answers(result: Optional[dict[str, Any]], deliverables: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_id = {str(a.get("question_id") or ""): a for a in (result or {}).get("answers") or []}
    out = []
    for i, q in enumerate(deliverables):
        a = by_id.get(f"q_{q.get('intent')}") or by_id.get(f"q_cio_followup_{i + 1}") or {}
        answered = str(a.get("status") or "").lower() != "unanswered" and (a.get("summary") or a.get("detail"))
        text = " ".join(x for x in (str(a.get("summary") or "").strip(), str(a.get("detail") or "").strip()) if x)
        urls = [c for c in a.get("citations") or [] if isinstance(c, str) and c.startswith("http")]
        out.append({"deliverable": q.get("text"), "answered": bool(answered), "answer": text[:600] if answered else None,
                    "status": str(a.get("status") or "unanswered").lower(), "cited_urls": urls[:8]})
    return out


def needs_escalation(answers: list[dict[str, Any]], s: dict[str, Any]) -> Optional[str]:
    """Why the web-backed answers are still too weak for the CIO, or None."""
    if not s.get("escalation_enabled") or not answers:
        return None
    full = sum(1 for a in answers if a.get("status") == "answered")
    ratio = full / len(answers)
    urls = {u for a in answers for u in a.get("cited_urls") or []}
    if ratio < float(s["escalation_min_answered_ratio"]):
        return f"only {full} of {len(answers)} deliverables fully answered"
    if len(urls) < int(s["escalation_min_cited_urls"]):
        return f"only {len(urls)} web sources cited"
    return None


def escalation_question(p: dict[str, Any], answers: list[dict[str, Any]], limit: int = 1800) -> str:
    """One question for an external research lane: what is still open, and what the web found.

    House-only findings ("Confirmed: no authored thesis exists") are left out -- they are the
    gap, not an answer -- and repeated concerns are asked once."""
    sym = str(p.get("symbol") or "").upper()
    strat = str(p.get("strategy") or "").replace("_", " ")
    exp = p.get("expiration")
    lines = [f"Research {sym} for a {strat} expiring {exp}. The CIO is still unsure. Give dated, "
             f"sourced facts for: the investment thesis; dated catalysts before {exp}; the analyst "
             "rating, price target and recent revisions; the main risks and what would invalidate "
             "the thesis. Say plainly what you could not establish. Open items:"]
    seen: set[str] = set()
    n = 0
    for a in answers:
        if a.get("status") == "answered":
            continue
        item = str(a.get("deliverable") or "").split("): ", 1)[-1]
        item = re.sub(rf"^\s*{re.escape(sym)}\s*:\s*", "", item)
        key = " ".join(sorted(set(re.findall(r"[a-z]{4,}", item.lower())))[:80])
        if not item or key in seen:
            continue
        seen.add(key)
        n += 1
        lines.append(f"{n}. {item[:200]}")
        if a.get("answer") and a.get("cited_urls"):
            lines.append(f"   Web found so far: {str(a['answer'])[:220]}")
    return "\n".join(lines)[:limit]

def with_followup_facts(p: dict[str, Any], life: dict[str, Any]) -> dict[str, Any]:
    """The re-review sees the delivered follow-up and any external escalation directly
    from the thesis store, not only when the desk has rebuilt the proposals since."""
    ra = dict(p.get("research_answers") or {})
    fc, fu, esc = life.get("followup_complete"), life.get("followup"), life.get("escalation")
    if fc and _after(fc, fu):
        ra["followup"] = [{k: a.get(k) for k in ("deliverable", "status", "answer", "cited_urls")}
                          for a in fc.get("answers") or []]
    if esc and _after(esc, fu) and esc.get("status") == "sent":
        ra["external_research"] = {"lane": esc.get("lane"), "confidence": esc.get("confidence"),
                                   "id": esc.get("external_research_id"),
                                   "findings": str(esc.get("recommendation") or "")[:2500]}
    return {**p, "research_answers": ra}


def _after(a: Optional[dict[str, Any]], b: Optional[dict[str, Any]]) -> bool:
    """True when event a was recorded after event b (both present)."""
    return bool(a and b and str(a.get("recorded_at") or "") > str(b.get("recorded_at") or ""))


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
    escalate: Optional[Callable[[dict[str, Any], str, list[str], float], dict[str, Any]]] = None,
    request_thesis_acquisition: Optional[Callable[[str, str], Any]] = None,
    recent_requests: Optional[Callable[[str], list[dict[str, Any]]]] = None,
) -> list[dict[str, Any]]:
    """One pass. Returns what it did (or would do, when apply=False).

    ``escalate(p, question, lanes, timeout_s)`` asks the Hermes external researcher
    lanes in order and returns {lane, status, row_id, recommendation, confidence, tried}."""
    now = now or datetime.now(timezone.utc)
    s = settings(cfg)
    report: list[dict[str, Any]] = []
    reviews = 0
    escalations = 0
    made: dict[str, list[dict[str, Any]]] = {}  # requests made in this pass, by symbol

    def _reuse(p: dict[str, Any], kind: str, first_text: str) -> Optional[dict[str, Any]]:
        sym = str(p.get("symbol") or "").upper()
        pool = list(made.get(sym) or [])
        if recent_requests is not None:
            try:
                pool += list(recent_requests(sym) or [])
            except Exception:  # noqa: BLE001 -- reuse is an optimisation, never a blocker
                pass
        hours = s["research_reuse_hours"] if kind == "thesis" else s["followup_reuse_hours"]
        return reusable_request(pool, symbol=sym, first_text=first_text, kind=kind, now=now, hours=hours)

    def _remember(p: dict[str, Any], out: dict[str, Any], qs: list[dict[str, str]]) -> None:
        if out.get("research_id"):
            made.setdefault(str(p.get("symbol") or "").upper(), []).append(
                {"research_id": out["research_id"], "plan_id": out.get("plan_id"), "status": "queued",
                 "symbols": [p.get("symbol")], "questions": qs, "created_ts": now.isoformat()})

    for p in proposals:
        guid = p.get("option_strategy_guid")
        ot = p.get("options_thesis") or {}
        if not guid or not ot.get("pin"):
            continue
        life = store.lifecycle(guid)
        if life.get("abandoned"):
            continue
        missing = list(ot.get("missing_required") or [])
        age = _hours_since(life.get("created_at"), now)
        step: dict[str, Any] = {"symbol": p.get("symbol"), "position_guid": guid, "pin": ot.get("pin")}
        dec = life.get("decision")
        rereview = False
        if dec:
            # 2026-09-26 (operator): "this needs to be a continuous automated process".
            # A decision is not the end unless it is final: MORE_RESEARCH starts named
            # follow-up research with a due time and re-reviews; MONITOR_ONLY re-checks.
            outcome = str(dec.get("outcome") or "")
            if outcome in ("REJECT", "APPROVE"):
                continue  # final; APPROVE waits for the operator's confirmation
            if outcome == "MONITOR_ONLY":
                if _hours_since(dec.get("recorded_at"), now) < float(s["monitor_recheck_hours"]):
                    step.update(action="WAIT_MONITOR", recheck_hours=s["monitor_recheck_hours"])
                    report.append(step)
                    continue
                rereview = True
            elif outcome == "MORE_RESEARCH":
                fu, fc = life.get("followup"), life.get("followup_complete")
                rounds = sum(1 for d in life.get("decisions_since_reopen", life.get("decisions")) or []
                             if d.get("outcome") == "MORE_RESEARCH")
                if not _after(fu, dec):
                    if rounds > int(s["max_followup_rounds"]):
                        step.update(action="ABANDON", reason=f"CIO asked for more research {rounds} times; "
                                                              "archived rather than looping")
                        if apply:
                            store.append_event(guid, "OPTIONS_THESIS_ABANDONED", reason=step["reason"])
                        report.append(step)
                        continue
                    qs = followup_questions(p, dec.get("review") or {}, int(s["max_deliverables"]))
                    due = (now + timedelta(hours=float(s["followup_due_hours"]))).isoformat()
                    shared = _reuse(p, "followup", "")
                    if shared:
                        qs = [{"intent": q.get("intent") or q.get("question_id") or "", "text": q.get("text") or ""}
                              for q in (shared.get("questions") or [])]
                    step.update(action="JOIN_FOLLOWUP" if shared else "REQUEST_FOLLOWUP",
                                deliverables=[q["text"] for q in qs], due_at=due,
                                decision_guid=dec.get("decision_guid"))
                    if shared:
                        step.update(reused_research_id=shared.get("research_id"))
                    if apply:
                        out = ({"research_id": shared.get("research_id"), "plan_id": shared.get("plan_id")}
                               if shared else request_research(p, qs))
                        if not shared:
                            _remember(p, out, qs)
                        store.append_event(guid, "OPTIONS_THESIS_FOLLOWUP_REQUESTED",
                                           research_id=out.get("research_id"), plan_id=out.get("plan_id"),
                                           deliverables=qs, due_at=due, for_decision=dec.get("decision_guid"),
                                           reused=bool(shared))
                    report.append(step)
                    continue
                if not _after(fc, fu):
                    st = research_status(fu.get("research_id"))
                    state = str(st.get("status") or "").lower()
                    if state == "completed":
                        ans = followup_answers(st.get("result"), fu.get("deliverables") or [])
                        step.update(action="FOLLOWUP_COMPLETE",
                                    answered=sum(1 for a in ans if a["answered"]), of=len(ans))
                        if apply:
                            store.append_event(guid, "OPTIONS_THESIS_FOLLOWUP_COMPLETE",
                                               research_id=fu.get("research_id"), answers=ans)
                        why = needs_escalation(ans, s)
                        if why and escalate is not None and escalations < int(s["escalation_max_per_run"]):
                            escalations += 1
                            step.update(escalation_reason=why)
                            if apply:
                                esc = escalate(p, escalation_question(p, ans), list(s["escalation_lanes"]),
                                               float(s["escalation_timeout_s"])) or {}
                                step.update(escalated_to=esc.get("lane"), escalation_status=esc.get("status"))
                                store.append_event(guid, "OPTIONS_THESIS_ESCALATED", reason=why,
                                                   lane=esc.get("lane"), status=esc.get("status"),
                                                   external_research_id=esc.get("row_id"),
                                                   tried=esc.get("tried") or [],
                                                   recommendation=str(esc.get("recommendation") or "")[:3000],
                                                   confidence=esc.get("confidence"))
                    elif _hours_since(fu.get("due_at"), now) > 0 and now.isoformat() > str(fu.get("due_at")):
                        step.update(action="ABANDON", reason="CIO follow-up research not delivered by its due time")
                        if apply:
                            store.append_event(guid, "OPTIONS_THESIS_ABANDONED", reason=step["reason"])
                    else:
                        step.update(action="WAIT_FOLLOWUP", status=state or "unknown", due_at=fu.get("due_at"))
                    report.append(step)
                    continue
                rereview = True  # follow-up delivered: the CIO reviews again, new Decision GUID
            else:
                continue
        # Research cannot fix liquidity: an idea with a non-thesis enterprise block
        # (OI 0, 185% spread) is not researched or reviewed (2026-09-26 dry test).
        ent_blocks = [b for b in ((p.get("enterprise") or {}).get("blocks") or [])
                      if not str((b or {}).get("code", "") if isinstance(b, dict) else b).startswith(("thesis_", "awaiting_cio"))]
        if ent_blocks:
            step.update(action="SKIP_ENTERPRISE_BLOCK", reason="blocked for liquidity or risk; research cannot clear it")
            report.append(step)
            continue
        if missing and not rereview:
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
                qs = research_questions(p)
                shared = _reuse(p, "thesis", qs[0]["text"])
                step.update(action="REUSE_RESEARCH" if shared else "REQUEST_RESEARCH", missing=missing)
                if shared:
                    step.update(reused_research_id=shared.get("research_id"))
                if apply:
                    out = ({"research_id": shared.get("research_id"), "plan_id": shared.get("plan_id")}
                           if shared else request_research(p))
                    if not shared:
                        _remember(p, out, qs)
                    store.append_event(guid, "OPTIONS_THESIS_RESEARCH_REQUESTED",
                                       research_id=out.get("research_id"), plan_id=out.get("plan_id"),
                                       missing=missing, reused=bool(shared))
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
        if rereview:
            p = with_followup_facts(p, life)
        res = review_fn(p, mode)
        if res.get("status") == "OK":
            r = res["review"]
            store.append_event(guid, "OPTIONS_THESIS_DECISION", decision_guid=res["decision_guid"],
                               outcome=r["outcome"], confidence=r.get("confidence"), review=r,
                               model=res.get("model"), reviewed_pin=ot.get("pin"),
                               supersedes=(dec or {}).get("decision_guid"))
            record_decision(res)
            step.update(action="DECISION", outcome=r["outcome"], decision_guid=res["decision_guid"])
            # 2026-09-27: the CIO keeps asking for more research when the symbol has
            # no house thesis; ask the symbol-thesis acquisition worker for one.
            if (r["outcome"] == "MORE_RESEARCH" and request_thesis_acquisition is not None
                    and str(p.get("thesis_state") or "").upper() in ("", "INSUFFICIENT_DATA")):
                try:
                    request_thesis_acquisition(str(p.get("symbol") or ""),
                                               f"options CIO MORE_RESEARCH {res['decision_guid']}: no house thesis")
                    step.update(thesis_acquisition_requested=True)
                except Exception:  # noqa: BLE001
                    step.update(thesis_acquisition_requested=False)
        else:
            if not any(t.get("stage") == "CIO_REVIEW_QUEUED" for t in life.get("timeline") or []):
                store.append_event(guid, "OPTIONS_THESIS_CIO_REVIEW_QUEUED", mode=mode, status=res.get("status"))
            step.update(action="CIO_REVIEW_NOT_ISSUED", status=res.get("status"), errors=res.get("errors"))
        report.append(step)
    return report
