#!/usr/bin/env python3
"""llm_request_router.py — route an LLM request to a lane per llm_budget_guard, logging every decision.

Advisory routing only — returns the lane an LLM call SHOULD use (or defer/block/fail). It does not call
any model or broker. Callers honor the decision; this centralizes the budget/market/tier policy + the
audit log. No broker writes.

    from llm_request_router import route
    d = route(job="hermes_topic_synth", tier="T3", model="gemma3:12b")
    # d = {"action": "allow"|"defer"|"hard_block"|"hard_fail", "selected_lane": ..., "reason": ...}
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "logs" / "llm_router.log"


def route(job: str, tier: str, model: str = None, requested_lane: str = None) -> dict:
    from llm_budget_guard import decide, in_market_window, _cloud_state, _policy
    pol = _policy()
    market = in_market_window(pol=pol)
    cs = _cloud_state()
    d = decide(tier, model, market, cs, pol)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(), "job": job, "tier": (tier or "").upper(),
        "model": model, "requested_lane": requested_lane,
        "selected_lane": d.get("selected_lane"), "action": d["action"], "reason": d["reason"],
        "market_window": market,
        "budget_state": {k: {"pct": v.get("daily_pct"), "reachable": v.get("reachable")}
                         for k, v in cs.items()},
        "result_status": d["action"],
    }
    # HARD invariants surfaced explicitly for the audit log.
    rec["paid_fallback"] = (d["action"] == "hard_fail")
    rec["local_31b_blocked"] = (d["action"] == "hard_block")
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--tier", required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    d = route(args.job, args.tier, args.model)
    print(json.dumps(d, indent=2, default=str) if args.json else
          f"route[{args.job}/{args.tier}] → {d['action']} lane={d.get('selected_lane')} ({d['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
