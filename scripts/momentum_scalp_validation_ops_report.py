#!/usr/bin/env python3
"""P1: Momentum Scalp VALIDATION operations report.

Operator-facing read-only ops view of the validation fast path: candidates found, would-submit /
deferred / rejected with reasons, route + freshness distribution, and progress toward the empirical
validation gate (confirmed closed validation trades / 30, win, profit factor, months). Says clearly
whether the 4.5 validation gate is met and what the next operational action is. NO broker writes.

    python3 scripts/momentum_scalp_validation_ops_report.py --days 30 --json
    python3 scripts/momentum_scalp_validation_ops_report.py --days 30 --markdown > docs/diligence/current/MOMENTUM_SCALP_VALIDATION_OPS.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

GATE = {"min_closed_validation_trades": 30, "min_win_rate": 0.50,
        "min_profit_factor": 1.30, "min_calendar_months": 6}


def build(days: int = 30) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    warnings = []

    # Validation fast-path snapshot (dry-run, read-only).
    fp = {}
    reasons = Counter()
    try:
        import momentum_scalp_validation_fast_path as _fp
        fpr = _fp.run(dry_run=True)
        if fpr.get("ok"):
            for c in fpr.get("candidates", []):
                for rc in (c.get("reason_codes") or []):
                    if rc != "ALL_GATES_PASS":
                        reasons[rc] += 1
            fp = {"candidates_found": fpr.get("candidates_evaluated", 0),
                  "would_submit_validation": fpr.get("would_submit_validation", 0),
                  "deferred": fpr.get("would_defer", 0),
                  "rejected": fpr.get("would_reject", 0),
                  "submitted_validation_trades": len(fpr.get("validation_submitted_symbols") or [])}
        else:
            warnings.append(f"validation_fast_path: {fpr.get('note', 'unavailable')}")
    except Exception as e:
        warnings.append(f"validation_fast_path: {str(e).splitlines()[0][:100]}")

    # Confirmed validation-trade outcome progress (conservative attribution).
    gate = {}
    try:
        import scalp_trade_attribution as _attr
        from db_adapter import get_connection
        a = _attr.attribute(get_connection())
        if a.get("ok"):
            closed = a["confirmed_closed"]
            gate = {
                "confirmed_closed_validation_trades": closed,
                "win_rate": a.get("confirmed_win_rate"),
                "profit_factor": a.get("confirmed_profit_factor"),
                "months_observed": None,
                "validation_gate_met": bool(
                    closed >= GATE["min_closed_validation_trades"]
                    and (a.get("confirmed_win_rate") or 0) >= GATE["min_win_rate"]
                    and (a.get("confirmed_profit_factor") or 0) >= GATE["min_profit_factor"]),
            }
    except Exception as e:
        warnings.append(f"attribution: {str(e).splitlines()[0][:100]}")

    closed = gate.get("confirmed_closed_validation_trades")
    gate_met = bool(gate.get("validation_gate_met"))
    if closed in (None, 0):
        next_action = ("No confirmed validation sample yet. Run the validation fast path promptly "
                       "during 06:00–12:00 ET (MOMENTUM_SCALP_VALIDATION_FAST_PATH=1, and "
                       "MOMENTUM_SCALP_VALIDATION_SUBMIT=1 for sandbox submit) so fresh in-window "
                       "micro-float candidates convert before the 30-min TTL.")
    elif not gate_met:
        next_action = (f"{closed}/{GATE['min_closed_validation_trades']} confirmed closed validation "
                       f"trades — keep collecting samples on the validation fast path. Do NOT promote "
                       f"to live; promotion needs human review + the existing operator/2FA path.")
    else:
        next_action = "Trade-count/win/PF thresholds met — request human promotion review (6-month span still required)."

    return {
        "ok": True,
        "status": "PASS" if not warnings else "WARN",
        "generated_at": started,
        "window_days": days,
        "validation_fast_path": fp,
        "top_reject_defer_reasons": [{"reason": k, "count": v} for k, v in reasons.most_common(8)],
        "validation_gate": {**GATE, **gate},
        "validation_gate_met": gate_met,
        "live_ready_claim": False,
        "next_operational_action": next_action,
        "warnings": warnings,
        "note": "Read-only validation ops report. No broker writes. Validation execution is "
                "sandbox/simulated and needs no human approval; live trading is unchanged (operator "
                "confirmation + 2FA). Large-float scouts manual-review only; social-only WATCH/WAIT only.",
    }


def to_markdown(r: dict) -> str:
    L = ["# Momentum Scalp Validation Ops", "",
         f"**Status: {r['status']}** | validation gate met: **{r.get('validation_gate_met')}** | "
         f"live-ready: **{r.get('live_ready_claim')}**  ",
         f"_Generated: {r['generated_at']} | window {r.get('window_days')}d_  ",
         "_Source: `python3 scripts/momentum_scalp_validation_ops_report.py --days N --json`_  ", ""]
    fp = r.get("validation_fast_path", {})
    L += ["## Validation fast-path snapshot (dry-run)", "",
          f"- candidates found: {fp.get('candidates_found')}",
          f"- would-submit validation: {fp.get('would_submit_validation')} · deferred: {fp.get('deferred')} "
          f"· rejected: {fp.get('rejected')} · submitted: {fp.get('submitted_validation_trades')}", ""]
    if r.get("top_reject_defer_reasons"):
        L += ["### Top reject/defer reasons", "", "| Reason | Count |", "|--------|-------|"]
        for x in r["top_reject_defer_reasons"]:
            L.append(f"| {x['reason']} | {x['count']} |")
    vg = r.get("validation_gate", {})
    L += ["", "## Validation gate progress", "",
          f"- confirmed closed validation trades: **{vg.get('confirmed_closed_validation_trades')}** "
          f"/ {vg.get('min_closed_validation_trades')}",
          f"- win rate: {vg.get('win_rate')} (need ≥ {vg.get('min_win_rate')})",
          f"- profit factor: {vg.get('profit_factor')} (need ≥ {vg.get('min_profit_factor')})",
          f"- months observed: {vg.get('months_observed') or 'unknown'} (need ≥ {vg.get('min_calendar_months')})",
          f"- **validation gate met: {r.get('validation_gate_met')}**", "",
          "## Next operational action", "", f"> {r['next_operational_action']}", "",
          "> " + r["note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = build(args.days)
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Validation ops: gate_met={r.get('validation_gate_met')} "
              f"confirmed_closed={r.get('validation_gate', {}).get('confirmed_closed_validation_trades')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
