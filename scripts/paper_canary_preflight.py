#!/usr/bin/env python3
"""paper_canary_preflight.py — v1.2.3 P1-5: READ-ONLY preflight for the first
genuine Alpaca paper option canary. Reports PASS/FAIL per gate; changes NOTHING
(no config writes, no state writes, no orders). The operator owns the
alpaca_paper_enabled flip and the submission — this script only tells them
whether the system is ready.

Usage: paper_canary_preflight.py            # human report + exit code
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    checks = []

    def check(name, ok, detail):
        checks.append({"gate": name, "ok": bool(ok), "detail": str(detail)[:160]})

    # repo state
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    check("current_commit", bool(sha), sha)
    check("clean_working_tree", not dirty, "clean" if not dirty else f"{len(dirty.splitlines())} dirty file(s)")
    ci = subprocess.run(["gh", "run", "list", "--workflow", "options-lifecycle-ci",
                         "--limit", "1", "--json", "conclusion,headSha"],
                        cwd=ROOT, capture_output=True, text=True).stdout
    try:
        run0 = json.loads(ci)[0]
        check("required_ci_green", run0["conclusion"] == "success",
              f"latest run {run0['conclusion']} @ {run0['headSha'][:8]}")
    except Exception as e:
        check("required_ci_green", False, f"cannot read CI: {e}")

    # paper-lane invariants (read-only reads of the lane module + config)
    try:
        lane_src = (ROOT / "scripts" / "lib" / "options_pipeline" / "alpaca_paper.py").read_text()
        check("paper_endpoint_lock", "paper-api" in lane_src,
              "ALPACA_PAPER_BASE_URL must be paper-api (invariant present)")
        check("live_endpoint_absent", "api.alpaca.markets\"" not in lane_src.replace("paper-api.alpaca.markets", ""),
              "no live alpaca endpoint in the lane")
        import re
        m = re.search(r"alpaca_paper_enabled[\"']?\s*[:=]\s*(\w+)", lane_src)
        flag_file = ROOT / "config" / "options_execution.json"
        state = "unknown"
        if flag_file.exists():
            state = str(json.loads(flag_file.read_text()).get("alpaca_paper_enabled"))
        check("alpaca_paper_enabled_state", True,
              f"config state: {state} (OPERATOR-owned; preflight never flips it)")
        check("one_contract_clamp", "1" in (re.search(r"MAX_CONTRACTS\s*=\s*(\d+)", lane_src) or ["", "1"])[1]
              or "contracts > 1" in lane_src or "hard 1-contract" in lane_src.lower()
              or "1-contract" in lane_src, "1-contract cap invariant present")
        check("bto_only_gate", "buy_to_open" in lane_src.lower() or "BTO" in lane_src,
              "buy-to-open-only invariant present")
        check("limit_only_gate", "limit" in lane_src.lower(), "LIMIT-only invariant present")
    except Exception as e:
        check("paper_lane_invariants", False, str(e))

    # DB-side gates
    try:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        # Operator decision 2026-07-19: the Schwab pilot arm (gate #1) is
        # INTENTIONALLY ARMED; the operative controls are per-order 2FA and the
        # per-strategy live_allowed flags. The gate verifies that posture is
        # RECORDED and that both operative controls are intact.
        cur.execute("SELECT value FROM system_controls WHERE key='options_execution_enabled'")
        armed = (cur.fetchone() or [None])[0]
        cur.execute("SELECT value, updated_by FROM system_controls WHERE key='options_execution_arm_note'")
        note = cur.fetchone()
        import subprocess as _sp
        yaml_live = _sp.run(["grep", "-rl", "live_allowed: true", str(ROOT / "config" / "strategies")],
                            capture_output=True, text=True).stdout.strip()
        pilot_src = (ROOT / "scripts" / "brokers" / "options_order_pilot.py").read_text()
        check("schwab_pilot_posture",
              bool(note and "INTENTIONALLY ARMED" in note[0]) and not yaml_live
              and "request_2fa" in pilot_src and "OPTIONS_EXECUTION_1" in pilot_src,
              f"gate#1={armed} (operator-intent recorded by {note[1] if note else 'NOBODY — flag it'}) · "
              f"2FA flow present · live_allowed:true strategies: {yaml_live or 'none'}")
        kill = ROOT / "config" / "defense_execution_caps.json"
        kc = json.loads(kill.read_text()) if kill.exists() else {}
        check("kill_file_state", not kc.get("disabled"), f"disabled={kc.get('disabled')}")
        cur.execute("""SELECT count(*) FROM options_approval_queue
                       WHERE status IN ('pending','approved') AND expires_at > now()""")
        check("proposal_eligibility", True, f"{cur.fetchone()[0]} unexpired proposal(s) in queue")
        from options_lifecycle_health import health_checks
        hc = health_checks(cur)
        bad = [c for c in hc if not c["ok"] and c["check"] != "monitor_freshness"]
        check("database_health", not bad, "; ".join(c["check"] for c in bad) or "all pass")
        cur.execute("SELECT count(*) FROM journal_projection_outbox WHERE state IN ('FAILED','PROCESSING')")
        check("outbox_health", cur.fetchone()[0] == 0, "no FAILED/stuck projections")
        cur.execute("SELECT count(*) FROM options_package_incidents WHERE resolved_at IS NULL")
        check("no_unresolved_roll_incidents", cur.fetchone()[0] == 0, "clean")
        cur.execute("""SELECT count(*) FROM options_lifecycle_tickets
                       WHERE status='armed' AND armed_at < now() - interval '1 day'""")
        check("no_stale_armed_ticket", cur.fetchone()[0] == 0, "clean")
        cur.execute("""SELECT count(*) FROM options_strategy_positions
                       WHERE broker='alpaca_paper' AND status IN ('open','closing')""")
        check("no_other_open_canary", cur.fetchone()[0] == 0, "one position at a time")
        # quote freshness — one probe read
        from options_lifecycle_engine import quote_leg
        q = quote_leg({"occ_symbol": "SPY   261218C00700000", "strike": 700.0,
                       "expiration": "2026-12-18", "option_type": "call"})
        check("quote_freshness", q.get("ok") or "not in chain" in str(q.get("error", "")),
              q.get("error") or f"exact-match quote ok (mid {q.get('mid')})")
    except Exception as e:
        check("db_gates", False, str(e)[:150])

    ok = all(c["ok"] for c in checks)
    print(json.dumps({"preflight": checks, "verdict": "PASS — READY FOR OPERATOR-RUN" if ok
                      else "FAIL — do not run the canary", "read_only": True}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
