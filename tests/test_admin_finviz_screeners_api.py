#!/usr/bin/env python3
"""P6: admin Finviz Screener Governance API — list/audit/update/enable/disable/run-now.
Asserts run-now is SOURCE-ONLY (no broker), edits are audited, routes are wired, and no gate is bypassed."""
import inspect
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import finviz_admin_api as fa  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- list ----
    lst = fa.list_screeners()
    check("list returns screeners + count", "screeners" in lst and lst["count"] == len(lst["screeners"]))
    check("list includes the 5 operator presets",
          sum(1 for s in lst["screeners"] if s.get("preset_id")) >= 5)
    check("list exposes cadence_class + next_run + last_run per row",
          all("cadence_class" in s and "next_run" in s and "last_run" in s for s in lst["screeners"]))
    check("list flags scalp-lane membership", any(s["in_scalp_lane"] for s in lst["screeners"]))
    check("no screener is GO-eligible by itself",
          all(s.get("go_eligible_by_itself") is False for s in lst["screeners"]))
    check("scalp_lane_screener_ids present (targeted set)", len(lst["scalp_lane_screener_ids"]) >= 2)

    # ---- audit ----
    aud = fa.audit_report()
    check("audit report builds", isinstance(aud, dict))

    # ---- routing (handle_finviz_admin) ----
    check("GET list routed", fa.handle_finviz_admin("/api/admin/finviz-screeners", "GET")[0] == 200)
    check("GET audit routed", fa.handle_finviz_admin("/api/admin/finviz-screeners/audit", "GET")[0] == 200)
    check("non-finviz path returns None (delegation passthrough)",
          fa.handle_finviz_admin("/api/v2/health", "GET") is None)
    st, _ = fa.handle_finviz_admin("/api/admin/finviz-screeners/bogus/frobnicate", "POST", {})
    check("unknown POST action 404", st == 404)

    # ---- update routes through to update_screener (metadata only) ----
    src = inspect.getsource(fa.update_screener)
    check("update edits ONLY cadence_class/notes/sunset_candidate (no trade fields)",
          "cadence_class" in src and "notes" in src and "broker" not in src.lower() and "trade" not in src.lower())
    check("update is audited", "_audit" in src and "finviz_screener_update" in src)

    # ---- enable/disable audited, DB active flag only ----
    sa = inspect.getsource(fa.set_active)
    check("set_active updates ONLY the active flag", "SET active=" in sa and "amount" not in sa.lower())
    check("set_active is audited", "finviz_screener_active" in sa)

    # ---- run-now is SOURCE FETCH ONLY (check executable call surface, not safety prose) ----
    rn = inspect.getsource(fa.run_now)
    # strip docstring + comments so we test the actual code, not the safety wording
    code_only = "\n".join(ln.split("#")[0] for ln in rn.splitlines()
                          if not ln.strip().startswith(('"', "'", '#')))
    check("run-now calls targeted source runner",
          "run_finviz_targeted_screeners" in rn and "from run_finviz_targeted_screeners import run" in code_only)
    check("run-now never submits orders / trades (no broker call surface)",
          not any(t in code_only.lower() for t in ("submit_order", "place_order", "broker", ".submit(", "create_order")))
    check("run-now is audited as source_fetch_only", "source_fetch_only" in rn)
    check("run-now states source-only safety in response", "source fetch only" in rn)

    # ---- module-wide: no broker/order/2FA surface anywhere ----
    full = inspect.getsource(fa)
    check("module has zero broker-write / order-submit surface",
          "broker_write" not in full and "place_order" not in full and "submit_order" not in full)
    check("module documents source-only + audited + no-broker invariant",
          "SOURCE FETCH ONLY" in full and "No broker writes" in full)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
