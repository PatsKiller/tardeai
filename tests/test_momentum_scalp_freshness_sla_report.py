#!/usr/bin/env python3
"""P1: freshness SLA report — separates stale-quote from TTL, latency stats, cadence eligibility."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_freshness_sla_report import build, to_markdown  # noqa: E402

PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    r = build(365)
    check("report structured", "status" in r)
    if not r.get("ok"):
        WARN.append("db")
        print(f"  [WARN] {r.get('warnings')}")
    else:
        check("separates stale-quote from TTL expiries",
              "stale_quote_failures" in r["failure_breakdown"] and "ttl_expiries" in r["failure_breakdown"])
        check("latency has median + p95",
              "median" in r["latency_created_to_first_atm_min"] and "p95" in r["latency_created_to_first_atm_min"])
        check("cadence eligibility for 1/3/5 min",
              set(r["atm_cadence_eligibility"].keys()) == {"within_1_min", "within_3_min", "within_5_min"})
        check("each cadence has eligible + missed",
              all("eligible_if_atm_ran" in v and "missed_by_slower_cadence" in v
                  for v in r["atm_cadence_eligibility"].values()))
        check("note affirms no broker writes + no weakening",
              "No broker writes" in r["note"] and "must not be weakened" in r["note"])
        check("markdown renders", "Freshness SLA" in to_markdown(r))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
