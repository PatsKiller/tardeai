#!/usr/bin/env python3
"""Reopen an archived options thesis (operator action, 2026-09-27).

DELL was archived at 00:37 ET after three MORE_RESEARCH rounds, all run on the old
closed-world research, three minutes before web research went live. A reopen appends
OPTIONS_THESIS_REOPENED (who, why); the follow-up round count and the abandon clock
restart from it. Nothing is deleted. Dry run by default.

    python3 scripts/options_thesis_reopen.py --symbol DELL --reason "..."           # dry run
    python3 scripts/options_thesis_reopen.py --symbol DELL --reason "..." --apply
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
    ap.add_argument("--proposals", default=str(ROOT / "data" / "portfolios" / "state" / "options_proposals.json"))
    a = ap.parse_args(argv)
    from lib.options_thesis import OptionsThesisStore
    store = OptionsThesisStore()
    guids = [a.guid] if a.guid else []
    if a.symbol:
        props = json.loads(Path(a.proposals).read_text(encoding="utf-8")).get("proposals") or []
        guids = sorted({p.get("option_strategy_guid") for p in props
                        if str(p.get("symbol") or "").upper() == a.symbol.upper() and p.get("option_strategy_guid")})
    out = []
    for g_ in guids:
        life = store.lifecycle(g_)
        if not life.get("abandoned"):
            out.append({"position_guid": g_, "action": "SKIP", "reason": f"not archived (stage {life.get('stage')})"})
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
