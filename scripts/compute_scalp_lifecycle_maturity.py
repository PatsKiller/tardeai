#!/usr/bin/env python3
"""P1-2: Social / Momentum Scalp lifecycle maturity score.

Transparent weighted score from machine-derived evidence (tests, validators, funnel),
bounded by hard caps that can only LOWER it. It does NOT assert 4.5 — it must earn it.
The momentum_scalp validation gate (≥30 closed paper trades, ≥6 months) being unmet caps
the combined score at 4.4: the lifecycle ENGINEERING can be complete while the EMPIRICAL
sample is still accumulating.

    python3 scripts/compute_scalp_lifecycle_maturity.py --json
    python3 scripts/compute_scalp_lifecycle_maturity.py --markdown > docs/diligence/current/SCALP_LIFECYCLE_MATURITY.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# (key, label, weight). Weights sum to 1.0.
DIMENSIONS = [
    ("strategy_config_consistency", "Strategy config consistency", 0.15),
    ("intraday_ttl_window_enforcement", "Intraday TTL / window enforcement", 0.15),
    ("social_only_catalyst_discipline", "Social-only catalyst discipline", 0.15),
    ("route_policy_correctness", "Route policy correctness", 0.15),
    ("liquidity_data_freshness", "Liquidity / data-freshness handling", 0.10),
    ("traceability", "End-to-end traceability", 0.10),
    ("empirical_funnel_evidence", "Empirical funnel evidence", 0.10),
    ("outcome_learning_loop", "Outcome-learning loop", 0.10),
]


def _run_test(name: str, timeout: int = 90) -> bool:
    try:
        p = subprocess.run([sys.executable, str(ROOT / "tests" / name)],
                           cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0
    except Exception:
        return False


def gather_evidence() -> dict:
    ev: dict = {}

    # config consistency
    try:
        from strategy_config_validator import validate_strategy_config
        ev["config_ok"] = bool(validate_strategy_config("momentum_scalp")["ok"])
    except Exception:
        ev["config_ok"] = False

    # test-backed dimensions
    ev["expiry_test"] = _run_test("test_momentum_scalp_expiry_enforced.py")
    ev["window_test"] = _run_test("test_intraday_window_fail_closed.py")
    ev["alerts_test"] = _run_test("test_social_scalp_decision_alerts.py")
    ev["route_test"] = _run_test("test_social_route_policy.py")
    ev["liquidity_test"] = _run_test("test_momentum_scalp_liquidity_unknown.py")
    ev["trace_test"] = _run_test("test_social_traceability.py")
    ev["no_bypass_test"] = _run_test("test_no_broker_write_bypass.py", timeout=120)
    ev["config_test"] = _run_test("test_momentum_scalp_config_consistency.py")

    # traceability columns present
    try:
        from db_adapter import get_connection
        from migrate_discovery_trace_id import check as col_check
        cols = col_check(get_connection())
        ev["trace_cols_present"] = all(v is True for v in cols.values())
    except Exception:
        ev["trace_cols_present"] = False

    # funnel report + validation sample
    try:
        from scalp_lifecycle_funnel_report import build_funnel
        f = build_funnel(180)
        ev["funnel_runs"] = bool(f.get("ok"))
        ev["funnel_gate_met"] = bool(f.get("validation_gate", {}).get("gate_met"))
        ev["closed_paper_trades"] = f.get("validation_gate", {}).get("closed_paper_trades")
    except Exception:
        ev["funnel_runs"] = False
        ev["funnel_gate_met"] = False
        ev["closed_paper_trades"] = None

    # outcome learning loop
    try:
        from scalp_outcome_learning import learn
        ol = learn(180)
        ev["outcome_runs"] = bool(ol.get("ok"))
    except Exception:
        ev["outcome_runs"] = False

    return ev


def score_dimensions(ev: dict) -> dict:
    return {
        "strategy_config_consistency": 1.0 if ev["config_ok"] and ev["config_test"] else 0.0,
        "intraday_ttl_window_enforcement": 1.0 if (ev["expiry_test"] and ev["window_test"]) else 0.0,
        "social_only_catalyst_discipline": 1.0 if ev["alerts_test"] else 0.0,
        "route_policy_correctness": 1.0 if ev["route_test"] else 0.0,
        "liquidity_data_freshness": 1.0 if ev["liquidity_test"] else 0.0,
        "traceability": 1.0 if (ev["trace_cols_present"] and ev["trace_test"]) else 0.0,
        "empirical_funnel_evidence": 1.0 if ev["funnel_runs"] else 0.0,
        "outcome_learning_loop": 1.0 if ev["outcome_runs"] else 0.0,
    }


def apply_caps(raw: float, ev: dict, dims: dict) -> tuple[float, list[dict]]:
    caps: list[dict] = []
    if not (ev["config_ok"] and ev["config_test"]):
        caps.append({"cap": 4.0, "reason": "conflicting / unvalidated strategy config"})
    if not ev["expiry_test"]:
        caps.append({"cap": 3.8, "reason": "expired intraday proposals could be approved"})
    if not ev["alerts_test"]:
        caps.append({"cap": 3.8, "reason": "social-only could send GO-style alert"})
    if not (ev["trace_cols_present"] and ev["trace_test"]):
        caps.append({"cap": 4.1, "reason": "no end-to-end traceability"})
    if not ev["funnel_runs"]:
        caps.append({"cap": 4.2, "reason": "no funnel report"})
    if not ev["funnel_gate_met"]:
        caps.append({"cap": 4.4, "reason": "validation sample not met (momentum_scalp still TESTING)"})
    if not ev["no_bypass_test"]:
        caps.append({"cap": 3.5, "reason": "broker-write bypass introduced"})
    final = raw
    for c in sorted(caps, key=lambda x: x["cap"]):
        if final > c["cap"]:
            c["lowered_from"] = round(final, 3)
            final = c["cap"]
    return round(final, 3), caps


def compute() -> dict:
    ev = gather_evidence()
    dims = score_dimensions(ev)
    lines, raw = [], 0.0
    for key, label, weight in DIMENSIONS:
        s = dims[key]
        pts = round(weight * s * 5, 4)
        raw += pts
        lines.append({"key": key, "label": label, "weight": weight,
                      "dimension_score_0_1": s, "weighted_points_of_5": pts})
    raw = round(raw, 3)
    final, caps = apply_caps(raw, ev, dims)

    # Sub-views for the two lifecycles (same evidence, subset of dimensions, same caps).
    def _subscore(keys):
        wsum = sum(w for k, _, w in DIMENSIONS if k in keys)
        sc = sum(w * dims[k] for k, _, w in DIMENSIONS if k in keys) / wsum * 5 if wsum else 0
        return apply_caps(round(sc, 3), ev, dims)[0]

    momentum = _subscore({"strategy_config_consistency", "intraday_ttl_window_enforcement",
                          "liquidity_data_freshness", "empirical_funnel_evidence", "outcome_learning_loop"})
    social = _subscore({"social_only_catalyst_discipline", "route_policy_correctness",
                        "traceability", "empirical_funnel_evidence"})

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_weighted_score_of_5": raw,
        "final_maturity_score_of_5": final,
        "meets_4_5": final >= 4.5,
        "momentum_scalp_lifecycle_of_5": momentum,
        "social_scalp_lifecycle_of_5": social,
        "combined_lifecycle_of_5": final,
        "caps_applied": caps,
        "score_lines": lines,
        "evidence": ev,
        "note": ("Earned from machine evidence, bounded by hard caps. momentum_scalp remains TESTING "
                 "until its validation gate (≥30 closed paper trades, ≥6 months) is met; that gate "
                 "caps the combined score at 4.4. No broker writes. LLMs advisory only; operator/2FA "
                 "path unchanged and out of scope."),
    }


def to_markdown(r: dict) -> str:
    L = ["# Scalp Lifecycle Maturity", "",
         f"**Combined: {r['final_maturity_score_of_5']} / 5** "
         f"(raw {r['raw_weighted_score_of_5']}) — meets 4.5: **{r['meets_4_5']}**  ",
         f"_Generated: {r['generated_at']}_  ",
         "_Source: `python3 scripts/compute_scalp_lifecycle_maturity.py --json`_  ", "",
         f"- Momentum Scalp lifecycle: **{r['momentum_scalp_lifecycle_of_5']} / 5**",
         f"- Social Scalp lifecycle: **{r['social_scalp_lifecycle_of_5']} / 5**", "",
         "| Dimension | Weight | Score | Points/5 |", "|-----------|--------|-------|----------|"]
    for ln in r["score_lines"]:
        L.append(f"| {ln['label']} | {int(ln['weight']*100)}% | {ln['dimension_score_0_1']} "
                 f"| {ln['weighted_points_of_5']} |")
    L += ["", "## Caps applied", ""]
    if r["caps_applied"]:
        for c in r["caps_applied"]:
            frm = f" (from {c['lowered_from']})" if "lowered_from" in c else " (not binding)"
            L.append(f"- Cap **{c['cap']}**{frm}: {c['reason']}")
    else:
        L.append("- None.")
    L += ["", "## Evidence", "", "| Check | Result |", "|-------|--------|"]
    for k, v in r["evidence"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "> " + r["note"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    r = compute()
    if args.markdown:
        print(to_markdown(r))
    elif args.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(f"Scalp lifecycle maturity: combined={r['final_maturity_score_of_5']}/5 "
              f"(raw {r['raw_weighted_score_of_5']}), meets_4_5={r['meets_4_5']}")
        for c in r["caps_applied"]:
            print(f"  cap {c['cap']}: {c['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
