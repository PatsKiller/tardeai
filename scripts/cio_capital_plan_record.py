#!/usr/bin/env python3
"""Record the capital plan's position decisions on a schedule (LQ-20261107-1608).

**ADVISORY ONLY.** This job never sizes, orders, stops, weights or writes to a broker. The only
thing it writes is the decision journal — the append-only record of the position decisions the
operator was shown — plus its own lane receipt.

Why this job exists
-------------------
``data/cio/cio_capital_plan_decisions.jsonl`` had exactly one writer: the request path of
``GET /api/v2/cio/capital-plan``. Every page view of the plan (and every v3 call into
``api_v2._cio_capital_plan()``) could therefore append to an authoritative store — the
side-effecting GET forbidden by AGENTS.md §28.9, with no exception under §28.11. The read route now
builds with ``record=False``; this script is the one owner of the recording, and it runs on a
schedule so a decision's ``recorded_at`` is the time the CIO job evaluated the book, not the time
somebody opened a page.

Behaviour
---------
Dry run by default (rule 7): builds the plan, reports how many decisions the journal does not
already hold, and writes nothing. ``--apply`` records them and writes the ``cio-capital-plan-record``
lane receipt.

Exit codes: 0 ok; 1 the plan could not be built or the journal could not be written; 2 bad usage.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

LANE_ID = "cio-capital-plan-record"


def _build_plan() -> dict:
    """The same build the GET serves, with recording off: this job decides when to write."""
    import api_v2

    return api_v2._cio_capital_plan_build(record=False)


def _pending(decisions) -> list[str]:
    """Decision ids the journal does not already hold, in plan order."""
    from scripts.lib.cio_capital_plan_decision_store import load_decision

    out: list[str] = []
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        did = str(d.get("decision_id") or "").strip()
        if not did:
            continue
        try:
            if load_decision(did) is None:
                out.append(did)
        except Exception:
            # A journal we cannot read is not evidence the row is absent; record it.
            out.append(did)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="record the decisions (default: dry run)")
    parser.add_argument("--journal", default=None, help="override the decision journal path")
    args = parser.parse_args(argv)

    if args.journal:
        os.environ["CIO_CAPITAL_PLAN_DECISIONS_JSONL"] = str(Path(args.journal))

    plan = _build_plan()
    if not plan.get("ok"):
        print(json.dumps({"ok": False, "error": plan.get("error"), "applied": False}, sort_keys=True))
        return 1

    decisions = plan.get("position_decisions") or []
    pending = _pending(decisions)
    result = {
        "ok": True,
        "applied": bool(args.apply),
        "decisions": len(decisions),
        "pending": len(pending),
        "already_recorded": len(decisions) - len(pending),
        "lane": LANE_ID,
    }

    if args.apply:
        from scripts.lib.cio_capital_plan_decision_store import record_position_decisions
        from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt

        written = record_position_decisions(decisions)
        # A count the store did not return stays unknown, never 0: "we could not tell" and "nothing
        # was written" are different facts and the receipt must not merge them (tq taxonomy #2).
        count = written.get("written")
        result["written"] = count if isinstance(count, int) else None
        if written.get("error"):
            result["write_error"] = written["error"]
        ok = "error" not in written
        result["ok"] = ok
        # An empty run is only allowed when it names why it was empty (health contract, `empty_allowed`).
        # Nothing left to append is this job's normal steady state: every decision the plan produced is already
        # in the journal. Naming it `already_recorded` is what stops idle runs grading RUN_FAILED and opening
        # the breaker (LQ-20261107-1822). Nothing written while decisions ARE pending is not named: that is an
        # anomaly, and it stays a failure rather than borrowing a reason that would excuse it.
        empty_reason = None
        if not result["written"]:
            if not decisions:
                empty_reason = "no_position_decisions"
            elif not pending:
                empty_reason = "already_recorded"
        receipt = write_lane_receipt(
            LANE_ID,
            ok=ok,
            exit_code=0 if ok else 1,
            started_at=now_iso(),
            script="cio_capital_plan_record.py",
            produced_count=result["written"],
            attempted_count=len(decisions),
            summary={"decisions": len(decisions), "pending": len(pending), "written": result["written"]},
            empty_reason=empty_reason,
            error=written.get("error"),
        )
        result["receipt"] = str(receipt) if receipt else None
        print(json.dumps(result, sort_keys=True))
        return 0 if ok else 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
