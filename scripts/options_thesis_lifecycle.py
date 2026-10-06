#!/usr/bin/env python3
"""Advance every options thesis one lifecycle step (operator 2026-09-26).

Dry run by default: prints what it would do. ``--apply`` requests research through
the Hermes CIO queue, reads completed answers back, runs the CIO review (mode from
portfolio_intent.yaml options_desk_settings.options_thesis_lifecycle.cio_review_mode),
records each Decision GUID in the options thesis store and cio_decisions, and
archives theses still incomplete after abandon_after_hours.

    python3 scripts/options_thesis_lifecycle.py            # dry run
    python3 scripts/options_thesis_lifecycle.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    f = ROOT / ".env"
    if not f.is_file():
        return
    for raw in f.read_text(errors="ignore").splitlines():
        s = raw.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def request_research(p: dict, questions: list | None = None) -> dict:
    from lib.cio_plans import CIOPlanStore
    from lib.hermes_research_loop import emit_research_for_plan
    from lib.options_thesis_lifecycle import research_questions, settings
    from options_desk_enterprise import load_desk_config
    sym = str(p.get("symbol") or "").upper()
    revisit = (datetime.now(timezone.utc) + timedelta(hours=24)).replace(microsecond=0).isoformat()
    plan = CIOPlanStore().create_plan(
        situation_type="S7_WATCH_PROMOTION",
        symbols=[sym],
        title=(f"CIO follow-up research: {sym}" if questions else
               f"Options thesis research: {sym} {str(p.get('strategy') or '').replace('_', ' ')}"),
        summary="Options thesis is missing catalysts, exit criteria or a thesis. Operator rule 2026-09-26: "
                "an incomplete thesis starts research, it does not sit.",
        options=[{"id": "research", "label": "Fill the thesis gaps", "pros": "Decision possible", "cons": "Research spend"},
                 {"id": "archive", "label": "Archive after the window", "pros": "No spend", "cons": "Idea dropped"}],
        recommendation="Research catalysts, invalidation, bear case and thesis. READ_ONLY.",
        risks=["Idea is archived if the thesis cannot be completed in time"],
        revisit_at=revisit, owner_agent="alex", actor_id="options_thesis_lifecycle",
    )
    if not isinstance(plan, dict) or not plan.get("plan_id"):
        return {"ok": False, "error": "no_plan_id"}
    # COGX W1 shadow: retrieval ladder before an options research request (receipt only)
    _ic_ctx = None
    try:
        from lib import intelligence_client as _ic
        _qs = questions or research_questions(p)
        _ic_ctx = _ic.shadow_open("options-thesis-lifecycle", [sym], "RESEARCH",
                                  question={"text": (_qs[0].get("text") if _qs and isinstance(_qs[0], dict) else "") or "", "question_class": "thesis",
                                            "horizon": str(p.get("strategy") or "options")})
    except Exception:  # noqa: BLE001
        _ic_ctx = None
    # A CIO review that returned MORE_RESEARCH asks for this research on behalf of
    # that exact decision; carry its id so the request and result join to it.
    for_decision = str(p.get("for_decision") or "").strip()
    linked = {"decision_ids": [for_decision]} if for_decision else {}
    out = emit_research_for_plan({**plan, "hermes_requested": True, **linked}, reason="options_thesis_gap",
                                 priority=settings(load_desk_config())["research_priority"],
                                 questions=questions or research_questions(p), actor_id="options_thesis_lifecycle")
    out = dict(out) if isinstance(out, dict) else {}
    try:
        if _ic_ctx:
            _ic.shadow_commit(_ic_ctx, {"kind": "RESEARCH_REQUESTED", "ref": str(out.get("research_id") or ""), "plan_id": plan["plan_id"]})
    except Exception:  # noqa: BLE001
        pass
    out["plan_id"] = plan["plan_id"]
    return out


def recent_requests(symbol: str) -> list:
    """Hermes research requests naming this symbol (projection read; no writes)."""
    from lib import cio_hermes_research as h
    try:
        proj = json.loads(h.PROJECTION_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    sym = str(symbol or "").upper()
    return [r for r in (proj.get("by_research_id") or {}).values()
            if sym in [str(x).upper() for x in (r.get("symbols") or [r.get("symbol")]) if x]]


def research_status(research_id: str) -> dict:
    from lib import cio_hermes_research as h
    req = h.get_request(research_id) or {}
    status = str(req.get("status") or "").lower()
    result = None
    if status == "completed" and h.RESULT_PATH.exists():
        for line in reversed(h.RESULT_PATH.read_text(encoding="utf-8").splitlines()):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            body = row.get("payload", row)
            if body.get("research_id") == research_id:
                result = body
                break
    return {"status": status, "result": result}


def escalate(p: dict, question: str, lanes: list, timeout_s: float) -> dict:
    """Ask the Hermes external researcher lanes in order (operator 2026-09-26: "if web unsure
    use chatgpt grok deepseek"); the first lane that answers wins. The script stores the row in
    hermes_external_research and reconciles it into the symbol thesis."""
    import re
    import subprocess
    sym = str(p.get("symbol") or "").upper()
    tried = []
    for lane in lanes:
        cmd = [sys.executable, str(ROOT / "scripts" / "hermes_external_researcher.py"), "--lane", lane,
               "--symbol", sym, "--question", question, "--trigger", "proposal_review:options_escalation",
               "--family", "REGISTERED", "--producer", "options_thesis_lifecycle", "--apply"]
        try:
            out = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout_s)
            m = re.search(r"stored hermes_external_research id=(\d+) status=(\w+)", out.stdout or "")
        except subprocess.TimeoutExpired:
            m = None
        if not m:
            tried.append({"lane": lane, "status": "no_result"})
            continue
        row_id, status = int(m.group(1)), m.group(2)
        tried.append({"lane": lane, "status": status, "id": row_id})
        if status != "sent":
            continue
        rec, conf = "", None
        try:
            from db_adapter import _execute
            row = _execute("SELECT recommendation, confidence FROM hermes_external_research WHERE id=%s",
                           (row_id,), fetch="one") or {}
            rec, conf = row.get("recommendation") or "", row.get("confidence")
        except Exception:
            pass
        return {"lane": lane, "status": status, "row_id": row_id, "recommendation": rec,
                "confidence": conf, "tried": tried}
    return {"lane": None, "status": "no_lane_answered", "tried": tried}


def _priority_request(symbol: str, reason: str) -> None:
    from lib.symbol_thesis_priority import request
    request(symbol, reason=reason, source="options_thesis_lifecycle", root=ROOT)


def record_decision(res: dict) -> None:
    from db_adapter import _execute
    from lib.options_cio_review import INSERT_SQL, decision_row
    row = decision_row(res)
    if row:
        _execute(INSERT_SQL, row, fetch=None)
        try:  # Wave 2 item 2: the review goes through the single write path (SHADOW until its policy row flips)
            from lib import research_write_path as _rwp
            _rwp.submit("options-cio-review", str(res.get("symbol") or (res.get("review") or {}).get("symbol") or ""), dict(res),
                        research_id=str(res.get("decision_guid") or ""), trigger="options_cio_review")
        except Exception:  # noqa: BLE001
            pass


def record_analysis_disposition(proposal: dict, analysis: dict, note: str) -> dict:
    """Record an operator's model-objection disposition on the existing CIO review.

    This adds evidence to an existing APPROVE decision; it cannot create one or
    override a REJECT/MORE_RESEARCH decision, risk block, desk approval or 2FA.
    """
    from db_adapter import _execute
    from scripts.lib.options_workflow import analysis_binding
    from scripts.lib.options_thesis import OptionsThesisStore
    decision_id = (proposal.get("cio_decision") or {}).get("decision_guid")
    if not decision_id or not note.strip() or analysis.get("status") != "completed":
        return {"ok": False, "error": "Completed analysis, existing CIO decision and disposition note required"}
    disposition = {"analysis_id": analysis["id"], "binding": analysis_binding(proposal),
                   "cio_decision_ref": decision_id, "note": note.strip()[:2000],
                   "recorded_by": "operator", "proposal_revision": proposal["revision"]}
    row = _execute("""UPDATE cio_decisions SET metadata=COALESCE(metadata,'{}'::jsonb) || %s::jsonb
                      WHERE decision_id=%s AND action='APPROVE'
                        AND metadata->>'position_guid'=%s RETURNING decision_id""",
                   (json.dumps({"options_analysis_disposition": disposition}), decision_id,
                    proposal["option_strategy_guid"]), fetch="one")
    if not row:
        return {"ok": False, "error": "An existing CIO APPROVE review for this strategy is required"}
    OptionsThesisStore().append_event(proposal["option_strategy_guid"], "OPTIONS_ANALYSIS_DISPOSITION", **disposition)
    return {"ok": True, "disposition": disposition}


def acquire_lifecycle_lock(path: str):
    """('acquired'|'inherited'|'held', fh). 'inherited' = an ancestor process (the crontab's
    `flock -n path cmd`) already holds the lock on a descriptor we inherited, so this run IS
    the locked run and must proceed. 'held' = some other process holds it; do not run."""
    import fcntl
    target = os.path.realpath(path)
    fd_dir = Path("/proc/self/fd")
    if fd_dir.exists():
        for fd in fd_dir.iterdir():
            try:
                if os.path.realpath(os.readlink(str(fd))) == target:
                    return "inherited", None
            except OSError:
                continue
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return "held", None
    return "acquired", fh


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Advance options theses one lifecycle step")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--proposals", default=str(ROOT / "data" / "portfolios" / "state" / "options_proposals.json"))
    ap.add_argument("--lock", default="/tmp/options_thesis_lifecycle.lock",
                    help="the scheduler's flock path; a manual run must not race the :07/:22/:37/:52 cron")
    a = ap.parse_args(argv)
    # 2026-09-27: a manual --apply pass raced the cron's pass on the same DELL guid (both
    # reviewed it in the same second). Take the same lock the crontab line uses; if it is
    # held, say so and exit 0 without touching the store.
    # 2026-09-28: the crontab line ALREADY wraps this script in `flock -n <same path>`; the
    # lock taken here (added 09-27 for manual runs) then conflicted with its own parent's lock
    # and every scheduled pass printed "held by another run" and exited -- 57 skips, every
    # thesis stuck at CREATED, no CIO decisions. flock(1) leaves its descriptor open in the
    # child, so an ancestor's lock is visible in /proc/self/fd: inherit it instead of fighting it.
    lock_state, lock_fh = acquire_lifecycle_lock(a.lock)
    if lock_state == "held":
        print(json.dumps({"ok": False, "skipped": "lifecycle lock held by another run", "lock": a.lock}))
        return 0
    _load_env()
    from lib.options_cio_review import review
    from lib.options_thesis import OptionsThesisStore
    from lib.options_thesis_lifecycle import advance, memory_settings, settings
    from options_desk_enterprise import load_desk_config
    try:
        proposals = json.loads(Path(a.proposals).read_text(encoding="utf-8")).get("proposals") or []
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"proposals unreadable: {e}"}))
        return 1
    # Prepared account/quantity revisions enter the existing lifecycle and budgets.
    # This is not a new agent or cadence; the existing worker owns their review.
    if a.apply:
        from scripts.lib.options_workflow_service import active_proposals
        prepared = active_proposals()
        roots = {p.get("source_proposal_id") for p in prepared}
        ids = {p["id"] for p in prepared}
        proposals = [p for p in proposals if p.get("id") not in roots | ids] + prepared
    report = advance(
        proposals, OptionsThesisStore(), load_desk_config(),
        request_research=request_research, research_status=research_status,
        review_fn=lambda p, mode: review(p, mode=mode, max_tokens=int(settings(load_desk_config())["review_max_tokens"]),
                                         memory=memory_settings(settings(load_desk_config()))),
        record_decision=record_decision,
        apply=a.apply, escalate=escalate,
        request_thesis_acquisition=lambda sym, why: _priority_request(sym, why),
        recent_requests=recent_requests,
    )
    print(json.dumps({"mode": "apply" if a.apply else "dry_run", "steps": report}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
