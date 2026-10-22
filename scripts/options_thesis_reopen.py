#!/usr/bin/env python3
"""Reopen an archived options thesis (operator action, 2026-09-27).

DELL was archived at 00:37 ET after three MORE_RESEARCH rounds, all run on the old
closed-world research, three minutes before web research went live. A reopen appends
OPTIONS_THESIS_REOPENED (who, why); the follow-up round count and the abandon clock
restart from it. Nothing is deleted. Dry run by default.

    python3 scripts/options_thesis_reopen.py --symbol DELL --reason "..."           # dry run
    python3 scripts/options_thesis_reopen.py --symbol DELL --reason "..." --apply

2026-10-22 (--review-cap): an idea that is NOT archived but has hit the lifecycle's max_review_failures
(REVIEW_FAILURE_CAP: the desk stopped spending on it) can be reopened the same way. The cap counts
CIO_REVIEW_FAILED events after the last REOPENED or DECISION (lib/options_thesis.lifecycle), so one REOPENED
event (reopened_from "review_failure_cap") gives it a fresh set of attempts. Use it only after the cause of the
failures is fixed (SPCX 2026-10-05..22: POLICY_NOT_ALLOWED, the review prompt escalated to FAST_THINK on a
process that did not allow it). Without --review-cap a non-archived idea is skipped, as before.

    python3 scripts/options_thesis_reopen.py --guid <g> --review-cap --reason "..."          # dry run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reopen an archived options thesis")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol")
    g.add_argument("--guid")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--actor", default="operator")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--review-cap", action="store_true",
                    help="also reopen a non-archived idea that hit max_review_failures (REVIEW_FAILURE_CAP)")
    ap.add_argument("--proposals", default=str(ROOT / "data" / "portfolios" / "state" / "options_proposals.json"))
    a = ap.parse_args(argv)
    from lib.options_thesis import OptionsThesisStore
    store = OptionsThesisStore()
    guids = [a.guid] if a.guid else []
    if a.symbol:
        props = json.loads(Path(a.proposals).read_text(encoding="utf-8")).get("proposals") or []
        guids = sorted({p.get("option_strategy_guid") for p in props
                        if str(p.get("symbol") or "").upper() == a.symbol.upper() and p.get("option_strategy_guid")})
    from lib.options_thesis_lifecycle import DEFAULTS as _LIFE
    cap = int(_LIFE["max_review_failures"])
    out = []
    for g_ in guids:
        life = store.lifecycle(g_)
        failures = int(life.get("review_failures") or 0)
        if not life.get("abandoned") and a.review_cap and failures >= cap:
            step = {"position_guid": g_, "action": "REOPEN_REVIEW_CAP", "review_failures": failures, "cap": cap,
                    "stage": life.get("stage"), "decisions_before": len(life.get("decisions") or [])}
            if a.apply:
                store.append_event(g_, "OPTIONS_THESIS_REOPENED", actor=a.actor, reason=a.reason,
                                   reopened_from="review_failure_cap")
                step["review_failures_now"] = store.lifecycle(g_).get("review_failures")
            out.append(step)
            continue
        if not life.get("abandoned"):
            why = f"not archived (stage {life.get('stage')})"
            if failures >= cap:
                why += f"; at the review-failure cap ({failures}/{cap}): rerun with --review-cap"
            out.append({"position_guid": g_, "action": "SKIP", "reason": why})
            continue
        step = {"position_guid": g_, "action": "REOPEN", "was": life["abandoned"].get("reason"),
                "decisions_before": len(life.get("decisions") or [])}
        if a.apply:
            store.append_event(g_, "OPTIONS_THESIS_REOPENED", actor=a.actor, reason=a.reason,
                               reopened_from=life["abandoned"].get("event_hash"))
            step["stage_now"] = store.lifecycle(g_).get("stage")
        out.append(step)
    print(json.dumps({"mode": "apply" if a.apply else "dry_run", "steps": out}, indent=1))
    return 0 if guids else 1


if __name__ == "__main__":
    raise SystemExit(main())
