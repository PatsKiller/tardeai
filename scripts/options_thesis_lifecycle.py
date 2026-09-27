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
    out = emit_research_for_plan({**plan, "hermes_requested": True}, reason="options_thesis_gap",
                                 priority=settings(load_desk_config())["research_priority"],
                                 questions=questions or research_questions(p), actor_id="options_thesis_lifecycle")
    out = dict(out) if isinstance(out, dict) else {}
    out["plan_id"] = plan["plan_id"]
    return out


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


def record_decision(res: dict) -> None:
    from db_adapter import _execute
    from lib.options_cio_review import INSERT_SQL, decision_row
    row = decision_row(res)
    if row:
        _execute(INSERT_SQL, row, fetch=None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Advance options theses one lifecycle step")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--proposals", default=str(ROOT / "data" / "portfolios" / "state" / "options_proposals.json"))
    a = ap.parse_args(argv)
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
    report = advance(
        proposals, OptionsThesisStore(), load_desk_config(),
        request_research=request_research, research_status=research_status,
        review_fn=lambda p, mode: review(p, mode=mode, max_tokens=int(settings(load_desk_config())["review_max_tokens"]),
                                         memory=memory_settings(settings(load_desk_config()))),
        record_decision=record_decision,
        apply=a.apply, escalate=escalate,
    )
    print(json.dumps({"mode": "apply" if a.apply else "dry_run", "steps": report}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
