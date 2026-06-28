#!/usr/bin/env python3
"""P0-5: dry-run paper-path simulator — valid candidate would convert; invalid ones blocked."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from simulate_momentum_scalp_paper_path import simulate, run_all, SCENARIOS  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    r = simulate(SCENARIOS["valid_in_window"])
    check("valid candidate WOULD_CREATE_PAPER_TRADE", r["result"] == "WOULD_CREATE_PAPER_TRADE")
    check("valid candidate passed route+config+window+expiry+liquidity+risk",
          len(r["gates_passed"]) >= 6)
    check("would-create payload is strategy_id=momentum_scalp + paper",
          r.get("would_create_paper_trade", {}).get("strategy_id") == "momentum_scalp"
          and r["would_create_paper_trade"].get("execution_environment") == "paper")

    check("expired candidate blocked at atm_expiry",
          simulate(SCENARIOS["expired"])["blocked_at"] == "atm_expiry")
    check("social-only candidate is WATCH/WAIT (never paper)",
          simulate(SCENARIOS["social_only_unverified"])["result"] == "WATCH_WAIT")
    check("liquidity-unknown candidate DEFERRED",
          simulate(SCENARIOS["liquidity_unknown"])["result"] == "DEFERRED")
    check("stale-quote candidate DEFERRED/blocked",
          simulate(SCENARIOS["stale_quote"])["result"] in ("DEFERRED", "BLOCKED"))
    check("out-of-window candidate blocked",
          simulate(SCENARIOS["out_of_window"])["blocked_at"] == "intraday_window")

    # No DB writes / no broker — run_all completes purely in-process.
    rep = run_all()
    check("run_all returns all scenarios", set(rep["results"].keys()) == set(SCENARIOS.keys()))
    check("note affirms no broker writes / no db writes",
          "NO broker orders" in rep["note"] and "NO database writes" in rep["note"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
