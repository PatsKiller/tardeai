#!/usr/bin/env python3
"""P4: LLM budget enforcement — no paid fallback, T3 defers (never local-31B) when cloud is down,
market-hour local 31B/27B is hard-blocked, local lane limits + budget thresholds, router logging."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from llm_budget_guard import decide, build, in_market_window, _policy  # noqa: E402

PASS, FAIL = [], []
POL = _policy()
CLOUD_OK = {"cloud_grok": {"reachable": True, "daily_pct": 10, "in_cooldown": False},
            "cloud_chatgpt_codex": {"reachable": True, "daily_pct": 10, "in_cooldown": False}}


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- HARD: market-hour local 31B/27B is blocked ----
    check("gemma4-31b market → hard_block", decide("T3", "gemma4-31b", True, CLOUD_OK)["action"] == "hard_block")
    check("gemma3:27b market → hard_block", decide("T2", "gemma3:27b", True, CLOUD_OK)["action"] == "hard_block")
    check("gemma4-31b OFF-market → allowed", decide("T3", "gemma4-31b", False, CLOUD_OK)["action"] != "hard_block")

    # ---- HARD: no paid fallback ----
    check("paid model → hard_fail", decide("T2", "gpt-4-paid", True, CLOUD_OK)["action"] == "hard_fail")
    check("paid model → never a lane", decide("T3", "claude-paid", True, CLOUD_OK)["selected_lane"] is None)

    # ---- HARD: T3 cloud-unavailable → DEFER (never local-31B, never paid) ----
    d = decide("T3", "gemma3:12b", True, {})
    check("T3 market cloud-DOWN → defer", d["action"] == "defer")
    check("T3 defer selects NO local lane", d["selected_lane"] is None)
    check("T3 defer reason names no-fallback", "no local-31B" in d["reason"] or "DEFER" in d["reason"])
    d2 = decide("T3", "gemma3:12b", True,
                {"cloud_grok": {"reachable": True, "daily_pct": 96}, "cloud_chatgpt_codex": {"reachable": True, "daily_pct": 99}})
    check("T3 over-budget (>=95%) → defer", d2["action"] == "defer")
    d3 = decide("T3", "gemma3:12b", True, {"cloud_grok": {"reachable": False}, "cloud_chatgpt_codex": {"reachable": True, "daily_pct": 5}})
    check("T3 picks the reachable lane", d3["action"] == "allow" and d3["selected_lane"] == "cloud_chatgpt_codex")

    # ---- T1 market: local only, never cloud ----
    check("T1 market → local lane", decide("T1", "gemma3:4b", True, CLOUD_OK)["selected_lane"] in ("local_fast", "local_quality"))
    check("T1 quality model → local_quality", decide("T1", "gemma3:12b", True, CLOUD_OK)["selected_lane"] == "local_quality")

    # ---- throttle / cooldown ----
    thr = decide("T3", "x", True, {"cloud_grok": {"reachable": True, "daily_pct": 85}})
    check("80-95% budget → allow but throttled", thr["action"] == "allow" and thr.get("throttled") is True)
    cd = decide("T3", "x", True, {"cloud_grok": {"reachable": True, "daily_pct": 10, "in_cooldown": True}})
    check("auth cooldown lane skipped → defer", cd["action"] == "defer")

    # ---- policy file integrity ----
    check("policy: T3 never_fallback_to_local_31b", POL["tier_policy"]["T3"]["never_fallback_to_local_31b"] is True)
    check("policy: T3 never_fallback_to_paid", POL["tier_policy"]["T3"]["never_fallback_to_paid"] is True)
    check("policy: blocked local models not market-allowed", POL["lanes"]["local_blocked_market"]["market_window_allowed"] is False)
    check("policy: cloud paid_fallback is hard_fail",
          POL["lanes"]["cloud_grok"]["paid_fallback"] == "hard_fail" and POL["lanes"]["cloud_chatgpt_codex"]["paid_fallback"] == "hard_fail")

    # ---- build() report + health-ingestible findings ----
    r = build()
    check("budget report ok", r["ok"] in (True, False) and "enforcement" in r)
    check("enforcement: market 31B hard_block", r["enforcement"]["market_local_31b_27b"] == "hard_block")
    check("enforcement: paid hard_fail", r["enforcement"]["paid_fallback"] == "hard_fail")
    check("findings is a list", isinstance(r["findings"], list))
    check("no broker writes note", "No broker writes" in r["note"])

    # ---- router logs a structured decision ----
    from llm_request_router import route
    d = route("test_job", "T3", "gemma3:12b")
    check("router returns an action", d["action"] in ("allow", "defer", "hard_block", "hard_fail"))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
