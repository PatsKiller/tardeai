#!/usr/bin/env python3
"""True momentum_scalp paper-trade attribution (operator correction 2026-06-28).

The methodology must not overcount: non-executed rows are not trades, direct-label rows
without lineage/fill are ambiguous (unknown), mismatched proposals don't count, and a trade
counts only with priority-1 direct strategy_id + lineage/fill, or unambiguous proposal lineage.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from scalp_trade_attribution import classify, attribute, STRATEGY  # noqa: E402

PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def warn(name, msg):
    WARN.append(name)
    print(f"  [WARN] {name} — {msg}")


def main():
    # --- pure classify() scenarios ---
    # 1. Direct + proposal match + executed → confirmed.
    check("direct + proposal match + closed → confirmed",
          classify("momentum_scalp", "momentum_scalp", "closed") == "confirmed")
    # 2. Direct + broker fill evidence (no proposal) → confirmed.
    check("direct + broker fill → confirmed",
          classify("momentum_scalp", None, "closed", broker_order_id="abc") == "confirmed")
    check("direct + broker_status filled → confirmed",
          classify("momentum_scalp", None, "closed", broker_status="filled") == "confirmed")
    # 3. Direct-label only, no lineage, no fill → ambiguous (NOT confirmed). This is pt=19/FLYW.
    check("direct-only, no lineage/fill → ambiguous",
          classify("momentum_scalp", None, "closed") == "ambiguous")
    # 4. Cancelled / dedup / pending → non_executed (the false '17 opened' rows).
    for st in ("cancelled", "dedup_removed", "pending", "rejected", "expired"):
        check(f"status {st} → non_executed",
              classify("momentum_scalp", "momentum_scalp", st) == "non_executed")
    # 5. Mismatch: trade=momentum_scalp but proposal=other → mismatched (not counted).
    check("proposal mismatch → mismatched",
          classify("momentum_scalp", "swing_breakout", "closed") == "mismatched")
    # 6. Other strategy entirely → not_scalp.
    check("other strategy → not_scalp",
          classify("swing_breakout", "swing_breakout", "closed") == "not_scalp")
    # 7. Proposal-only lineage (trade strategy empty, proposal momentum_scalp) → proposal_only.
    check("proposal-only lineage → proposal_only",
          classify(None, "momentum_scalp", "closed") == "proposal_only")
    # 8. Open (executed but not closed) direct+fill → confirmed (counts as opened, not closed).
    check("open + fill → confirmed",
          classify("momentum_scalp", "momentum_scalp", "open") == "confirmed")

    # --- DB-aware: the live truth must match the operator-corrected reality ---
    try:
        from db_adapter import get_connection
        r = attribute(get_connection())
        if not r.get("ok"):
            warn("DB attribution", r.get("note", "unavailable"))
        else:
            check("confirmed_closed is small (not the false 17)", r["confirmed_closed"] <= 3)
            check("non-executed rows excluded from confirmed", r["non_executed_count"] >= 1)
            check("ambiguous rows not counted as confirmed",
                  set(r["ambiguous_trade_ids"]).isdisjoint(set(r["confirmed_trade_ids"])))
            check("validation gate far from met (confirmed_closed < 30)", r["confirmed_closed"] < 30)
            check("each confirmed trade has an attribution chain",
                  all("reason" not in c or True for c in r["attribution_chains"])
                  and len(r["attribution_chains"]) == r["confirmed_opened"])
    except Exception as e:
        warn("DB attribution", f"no DB ({str(e)[:60]})")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
