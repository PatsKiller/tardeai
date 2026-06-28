#!/usr/bin/env python3
"""P0-4: paper-path diagnosis identifies the first bottleneck; read-only; no broker writes."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from diagnose_momentum_scalp_paper_path import build, to_markdown  # noqa: E402

PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def warn(name, msg):
    WARN.append(name)
    print(f"  [WARN] {name} — {msg}")


def main():
    r = build(365)
    check("diagnosis runs / structured", "first_bottleneck" in r or not r.get("ok"))
    if not r.get("ok"):
        warn("DB diagnosis", "; ".join(r.get("warnings", ["no db"])))
        print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
        return 1 if FAIL else 0

    check("identifies a single first bottleneck", isinstance(r["first_bottleneck"], str))
    check("bottleneck has a detail", bool(r.get("bottleneck_detail")))
    check("stages include proposals + paper trades", "proposals_created" in r["stages"]
          and "paper_trades_by_status" in r["stages"])
    check("reports confirmed paper trades (conservative)", "confirmed_paper_trades" in r["stages"])
    check("note affirms no broker writes / paper-only",
          "No broker writes" in r["note"] and "Paper-only" in r["note"])
    check("markdown renders the bottleneck", "First bottleneck" in to_markdown(r))
    # The known live bottleneck is approval failing on stale quotes (freshness gate working).
    if r["stages"].get("atm_rejection_gates", {}).get("approve_proposal_failed"):
        check("stale-quote approval failure is surfaced",
              r["first_bottleneck"] == "approval_fails_on_stale_quote")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
