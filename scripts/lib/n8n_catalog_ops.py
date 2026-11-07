"""n8n catalog, LQ-20261107-180 commit 2: the `llm` and `fixes` sections of GET /api/v2/ops/n8n-catalog.

  * llm: how LLMs are used over the last 24 h, live from llm_consumption_log (the table behind
    /api/v2/consumption/*). Per purpose (process): model lanes and models, calls, failures, last call, the estimated
    spend the log records, and the newest error. Split Operations (self-heal, diagnosis, data quality) from Content.
    A model lane whose every call failed is flagged (all_failed).
  * fixes: open lead-ledger work items that touch n8n lanes, and what self-heal could not fix: fixer jobs that were
    refused, failed, interrupted or stuck at fix_requested for more than 24 h, plus open diagnosis escalations. Each
    has a plain reason and what the operator can do. Re-run is shown but never enabled here: it needs an operator grant.

Read-only: two SELECTs on llm_consumption_log and file reads of the fixer, escalation and ledger stores. Nothing
writes a store, calls a model or changes a schedule. A store that cannot be read becomes a note and a null, never a
zero.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

DIAG_STATE_REL = "data/runtime/n8n_failure_diagnosis_state.json"
FIXER_STATE_REL = "data/runtime/self_heal_fixer_state.json"
FIXER_RECEIPT_REL = "data/runtime/self_heal_fixer_last.json"
LEDGER_DIR_REL = "data/coordination/coordinator"
LEDGER_GLOB = "LEAD-WORK-LEDGER-*.json"
STUCK_AFTER = timedelta(hours=24)
GRANTS_HREF = "/v3/system/ops-controls?tab=grants"
RERUN = {"enabled": False, "why": "needs operator grant"}

#: Categories (llm_process_config.category) that are operations work, not content.
OPS_CATEGORIES = frozenset({"Operations", "N8nCoordination", "System", "AgentRuntime", "Alerts", "Compatibility"})
#: The approved panel's Operations rows: process -> (label, next step). Always listed, even with no call in 24 h.
OPS_ITEMS: dict[str, tuple[str, str]] = {
    "n8n_lane_failure_diagnosis": ("Failure diagnosis on n8n",
                                   "Diagnose every failed n8n run and post the cause on the lane (LQ-151)"),
    "self_heal_fixer": ("Code self-fix", "Intake on n8n with a daily cap; writes fixes once its grant is active (LQ-152)"),
    "incident_supervisor": ("Incident supervisor", "Restart under the program and tie it to the incident feed (LQ-153)"),
    "gap_resolver": ("Data gap resolver", "Weekday lane. Re-audit at its next slot"),
    "contradiction_adjudicator": ("Contradiction adjudicator", "Keep. Extend to the data-quality checks (LQ-154)"),
    "prospectus_fact_check": ("Fact check (prospectus)",
                              "Generalize into an AI-claim check on every AI-written lane (LQ-154)"),
    "ops_summary_draft": ("Ops summary draft", "Turn on or retire (LQ-155)"),
    "material_digest_draft": ("Material digest draft", "Turn on or retire (LQ-155)"),
}
#: The fixer runs the Claude Code CLI, which writes no llm_consumption_log row; its own state is shown instead.
NOT_IN_LOG = frozenset({"self_heal_fixer"})

LLM_24H_SQL = """
SELECT l.process_id, MAX(l.process_name) AS process_name, MAX(pc.category) AS category, l.model_lane,
       array_remove(array_agg(DISTINCT COALESCE(l.returned_model, l.model_name)), NULL) AS models,
       COUNT(*) AS calls, COUNT(*) FILTER (WHERE NOT l.success) AS failures,
       MAX(l.created_at) AS last_at, MAX(l.created_at) FILTER (WHERE l.success) AS last_ok_at,
       COALESCE(SUM(l.estimated_cost_usd), 0) AS spend_usd,
       (ARRAY_AGG(l.error_message ORDER BY l.created_at DESC)
            FILTER (WHERE NOT l.success AND l.error_message IS NOT NULL))[1] AS last_error
FROM llm_consumption_log l LEFT JOIN llm_process_config pc ON pc.process_id = l.process_id
WHERE l.created_at >= NOW() - INTERVAL '24 hours'
GROUP BY l.process_id, l.model_lane
"""
LAST_SEEN_SQL = """
SELECT process_id, MAX(created_at) AS last_at FROM llm_consumption_log
WHERE process_id = ANY(%s) AND created_at >= NOW() - INTERVAL '30 days' GROUP BY process_id
"""

ESCALATION_PLAIN = {
    "suggest_only": ("The diagnosis says this needs a code or data fix; self-heal is only allowed to suggest one here.",
                     "Read the diagnosis, then open or assign a fix item."),
    "low_confidence": ("The diagnosis was not confident enough for self-heal to act.",
                       "Check the last runs on the lane; re-run once the cause is clear."),
    "critical_unresolved": ("A critical failure from an earlier cycle is still open.",
                            "Treat it as urgent: open the lane and assign a fix item."),
    "remediation_not_done": ("Self-heal tried a remediation, but a precondition was not met.",
                             "Read the precondition below; fix it or re-run by hand."),
}
FIXER_PLAIN = {
    "fix_refused": "The fixer refused this job (the lane or change is outside what it may touch).",
    "fix_failed": "The fixer tried and failed: its change did not pass the checks.",
    "fix_interrupted": "The fixer's attempt was cut off before it finished.",
    "fix_requested": "The fix is waiting and has not been attempted.",
}
CLOSED_STATUS = re.compile(r"^(DONE|CLOSED|MERGED)", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _at(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> Optional[str]:
    d = _at(value)
    return d.isoformat() if d else None


def _clip(text: Any, limit: int = 240) -> Optional[str]:
    if text is None:
        return None
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _read_json(path: Path) -> tuple[Optional[dict], Optional[str]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"{path.name} is missing"
    except (OSError, ValueError) as exc:
        return None, f"{path.name} could not be read ({type(exc).__name__})"
    return (doc, None) if isinstance(doc, dict) else (None, f"{path.name} is not a JSON object")


# ── llm ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

QueryFn = Callable[[str, Any], Optional[list]]


def default_llm_query(sql: str, params: Any = None) -> Optional[list]:
    """Read-only SELECT through db_adapter. None when the DB is not reachable (callers turn it into a note)."""
    try:
        try:
            import db_adapter  # type: ignore[import-not-found]
        except ImportError:
            from scripts import db_adapter  # type: ignore[no-redef]
        if not getattr(db_adapter, "USE_DB", True):
            return None
        return db_adapter._execute(sql, params, fetch="all")
    except Exception:  # noqa: BLE001 -- an unreachable DB is a note on the llm tab, never a 500 on the page
        return None


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def read_llm_24h(query: QueryFn) -> tuple[Optional[list[dict]], dict[str, Optional[str]], Optional[str]]:
    """(rows per process x model lane over 24 h, last call within 30 days for idle approved ops rows, note)."""
    rows = query(LLM_24H_SQL, None)
    if rows is None:
        return None, {}, "llm_consumption_log could not be read, so LLM use is not shown (not zero)."
    out = []
    for r in rows:
        r = dict(r)
        out.append({"process_id": str(r.get("process_id") or "(none)"), "process_name": r.get("process_name"),
                    "category": r.get("category"), "lane": r.get("model_lane"),
                    "models": sorted({str(m) for m in (r.get("models") or []) if m}),
                    "calls": int(r.get("calls") or 0), "failures": int(r.get("failures") or 0),
                    "last_at": _iso(r.get("last_at")), "last_ok_at": _iso(r.get("last_ok_at")),
                    "spend_usd": _num(r.get("spend_usd")), "last_error": _clip(r.get("last_error"), 200)})
    seen = {r["process_id"] for r in out}
    missing = sorted(p for p in OPS_ITEMS if p not in seen and p not in NOT_IN_LOG)
    last_seen: dict[str, Optional[str]] = {}
    if missing:
        for h in query(LAST_SEEN_SQL, (missing,)) or []:
            h = dict(h)
            last_seen[str(h.get("process_id"))] = _iso(h.get("last_at"))
    return out, last_seen, None


def _item(pid: str, lanes: list[dict], last_seen: Mapping[str, Optional[str]]) -> dict:
    label, nxt = OPS_ITEMS.get(pid, (None, None))
    name = next((ln["process_name"] for ln in lanes if ln.get("process_name")), None)
    calls = sum(ln["calls"] for ln in lanes)
    fails = sum(ln["failures"] for ln in lanes)
    spends = [ln["spend_usd"] for ln in lanes if ln["spend_usd"] is not None]
    for ln in lanes:
        ln["all_failed"] = ln["calls"] > 0 and ln["failures"] == ln["calls"]
    lanes.sort(key=lambda ln: (not ln["all_failed"], -ln["calls"]))
    if not lanes:
        status = "no_calls_24h"
    elif fails == calls:
        status = "all_failed"
    elif any(ln["all_failed"] for ln in lanes):
        status = "lane_all_failed"
    else:
        status = "active"
    return {
        "process_id": pid, "label": label or name or pid, "process_name": name, "next": nxt,
        "category": next((ln["category"] for ln in lanes if ln.get("category")), None),
        "models": sorted({m for ln in lanes for m in ln["models"]}), "lanes": lanes,
        "calls": calls, "failures": fails, "spend_usd": round(sum(spends), 6) if spends else None,
        "last_at": max((ln["last_at"] for ln in lanes if ln["last_at"]), default=None) or last_seen.get(pid),
        "status": status, "red": status in ("all_failed", "lane_all_failed"),
    }


def llm_section(query: Optional[QueryFn] = None, *, fixer: Optional[Mapping[str, Any]] = None,
                now: Optional[datetime] = None) -> dict:
    now = now or _now()
    rows, last_seen, note = read_llm_24h(query or default_llm_query)
    base = {"as_of": now.isoformat(), "window": "24h", "source": "llm_consumption_log", "note": note,
            "spend_note": "Spend is the estimate the consumption log records per call. OAuth routes (grok, chatgpt) "
                          "record $0."}
    if rows is None:
        return {**base, "groups": None}
    by_pid: dict[str, list[dict]] = {}
    for r in rows:
        by_pid.setdefault(r["process_id"], []).append(r)
    for pid in OPS_ITEMS:
        by_pid.setdefault(pid, [])
    groups: dict[str, list[dict]] = {"ops": [], "content": []}
    for pid, lanes in by_pid.items():
        it = _item(pid, lanes, last_seen)
        if pid in NOT_IN_LOG:
            it["status"] = "not_in_log"
            it["not_in_log"] = "Runs the Claude Code CLI, which writes no consumption-log row; its own state is shown."
            it["fixer"] = dict(fixer) if fixer else None
        key = "ops" if (pid in OPS_ITEMS or it["category"] in OPS_CATEGORIES) else "content"
        groups[key].append(it)
    out = []
    for key, label in (("ops", "Operations: self-heal, diagnosis, data quality"), ("content", "Content and analysis")):
        items = sorted(groups[key], key=lambda i: (not i["red"], i["calls"] == 0, -i["calls"], i["label"]))
        spends = [i["spend_usd"] for i in items if i["spend_usd"] is not None]
        out.append({"key": key, "label": label, "items": items,
                    "calls": sum(i["calls"] for i in items), "failures": sum(i["failures"] for i in items),
                    "spend_usd": round(sum(spends), 6) if spends else None,
                    "active": sum(1 for i in items if i["calls"] > i["failures"]),
                    "red": sum(1 for i in items if i["red"]), "total": len(items)})
    return {**base, "groups": out}


# ── fixes ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _plain_escalation(reason: str) -> tuple[str, str]:
    for key, (text, action) in ESCALATION_PLAIN.items():
        if key in (reason or ""):
            if reason.startswith("p1_floor:"):
                sev = reason.split(";", 1)[0].split(":", 1)[1]
                text = f"Severity {sev}: always goes to a person. " + text
            if key == "remediation_not_done":
                text += f" ({reason.rsplit(':', 1)[-1].replace('_', ' ')})"
            return text, action
    return f"Escalated: {reason or 'no reason recorded'}.", "Open the lane and decide."


def read_escalations(path: Path) -> tuple[list[dict], Optional[str]]:
    doc, err = _read_json(path)
    if doc is None:
        return [], f"Diagnosis escalations: {err}."
    out = []
    for key, e in (doc.get("escalations") or {}).items():
        if not isinstance(e, dict):
            continue
        reason = str(e.get("reason") or "")
        plain, action = _plain_escalation(reason)
        detail = str(e.get("detail") or "")
        i = detail.find("cause=")
        out.append({"kind": "escalation", "key": e.get("key") or key, "lane": e.get("lane"), "at": e.get("at"),
                    "state": "escalated", "priority": e.get("priority"), "event_type": e.get("event_type"),
                    "reason": reason, "plain": plain, "action": action, "tried": _clip(e.get("tried"), 200),
                    "cause": _clip(detail[i + 6:], 300) if i >= 0 else None, "grant_href": None, "rerun": RERUN})
    out.sort(key=lambda x: (str(x["priority"] or "P9"), str(x["at"] or "")))
    return out, None


def read_fixer(state_path: Path, receipt_path: Path, now: datetime) -> tuple[list[dict], dict, Optional[str]]:
    """Fixer jobs self-heal could not complete, and the fixer's arming state from its last receipt."""
    doc, err = _read_json(state_path)
    receipt, _ = _read_json(receipt_path)
    arming = (receipt or {}).get("arming") or {}
    why = str(arming.get("why") or "")
    summary: dict[str, Any] = {"armed": arming.get("armed"), "why": why or None,
                               "receipt_at": (receipt or {}).get("finished_at"), "waiting": None, "oldest": None,
                               "grant_href": GRANTS_HREF if "grant" in why else None}
    if doc is None:
        return [], summary, f"Self-heal fixer: {err}."
    summary["waiting"] = 0
    out = []
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        state = job.get("state")
        created = _at(job.get("created_at"))
        if state == "fix_requested":
            summary["waiting"] += 1
            if created and (summary["oldest"] is None or created < _at(summary["oldest"])):
                summary["oldest"] = created.isoformat()
        stuck = state == "fix_requested" and created is not None and now - created > STUCK_AFTER
        if state not in ("fix_refused", "fix_failed", "fix_interrupted") and not stuck:
            continue
        plain = FIXER_PLAIN.get(state, f"Fixer state {state}.")
        action, grant = "Open the lane and decide whether to fix it by hand or close the job.", None
        if state == "fix_requested" and arming.get("armed") is False:
            plain = f"Self-heal is not armed: {why or 'no reason recorded'}. The fix has waited since it was requested."
            if "grant" in why:
                action, grant = "Issue the grant in Ops Controls → Grants (passkey and typed phrase).", GRANTS_HREF
        hist = job.get("history") if isinstance(job.get("history"), list) else []
        last = hist[-1] if hist and isinstance(hist[-1], dict) else {}
        out.append({"kind": "fixer", "key": job.get("job_id"), "lane": job.get("lane"), "at": job.get("created_at"),
                    "state": state, "since": last.get("at") or job.get("created_at"),
                    "failure_kind": job.get("failure_kind"), "incident": job.get("incident_key"),
                    "plain": plain, "action": action, "grant_href": grant, "rerun": RERUN})
    out.sort(key=lambda x: str(x["at"] or ""))
    return out, summary, None


def _lq_num(item_id: str) -> int:
    tail = str(item_id).rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 10 ** 6


def read_n8n_work(state: Path, lanes: Mapping[str, Mapping[str, Any]], work_refs: Mapping[str, Mapping[str, Any]]
                  ) -> tuple[Optional[list[dict]], Optional[str], Optional[str]]:
    """Open items of the newest lead ledger that touch n8n lanes: a lane's audit fix item, "n8n" in the title, or a
    lane id in the title. Returns (items, ledger file name, note); items is None when the ledger cannot be read."""
    try:
        paths = sorted((state / LEDGER_DIR_REL).glob(LEDGER_GLOB))
    except OSError:
        paths = []
    if not paths:
        return None, None, "No lead work ledger found, so open n8n work items are not shown."
    doc, err = _read_json(paths[-1])
    if doc is None:
        return None, paths[-1].name, f"The lead work ledger {err}."
    by_fix: dict[str, list[str]] = {}
    for lane_id, lane in lanes.items():
        ref = lane.get("work_item")
        if ref:
            rid = str((work_refs.get(ref) or {}).get("id") or ref)
            by_fix.setdefault(rid, []).append(lane_id)
    ids = sorted(lanes, key=len, reverse=True)
    out = []
    for it in doc.get("items") or []:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        status = str(it.get("status") or "")
        if CLOSED_STATUS.match(status):
            continue
        iid, title = str(it["id"]), str(it.get("title") or "")
        low = title.lower()
        touched = list(by_fix.get(iid, []))
        touched += [lid for lid in ids if lid not in touched and len(lid) > 3 and lid.lower() in low]
        if not touched and "n8n" not in low:
            continue
        out.append({"id": iid, "owner": it.get("owner"), "priority": it.get("priority"), "status": status or None,
                    "title": _clip(title, 220), "lanes": sorted(touched), "audit_fix": iid in by_fix})
    out.sort(key=lambda x: (str(x["priority"] or "P9"), _lq_num(x["id"])))
    return out, paths[-1].name, None


def fixes_section(state: Path, lanes: Mapping[str, Mapping[str, Any]], work_refs: Mapping[str, Mapping[str, Any]],
                  *, now: Optional[datetime] = None) -> tuple[dict, dict]:
    """(fixes section, fixer summary for the llm tab)."""
    now = now or _now()
    work, ledger, wnote = read_n8n_work(state, lanes, work_refs)
    fixer, summary, fnote = read_fixer(state / FIXER_STATE_REL, state / FIXER_RECEIPT_REL, now)
    esc, enote = read_escalations(state / DIAG_STATE_REL)
    notes = [n for n in (wnote, fnote, enote) if n]
    return ({"as_of": now.isoformat(), "ledger": ledger, "work": work, "self_heal": fixer + esc,
             "fixer": summary, "rerun": RERUN, "notes": notes}, summary)


def build_ops(state: Path, lanes: Mapping[str, Mapping[str, Any]], work_refs: Mapping[str, Mapping[str, Any]], *,
              query: Optional[QueryFn] = None, now: Optional[datetime] = None) -> dict:
    fixes, summary = fixes_section(state, lanes, work_refs, now=now)
    return {"llm": llm_section(query, fixer=summary, now=now), "fixes": fixes}
