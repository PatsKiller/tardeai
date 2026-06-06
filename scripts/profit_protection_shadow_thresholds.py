#!/usr/bin/env python3
"""Phase 206 — Shadow profit-protection threshold recommendations (ADVISORY ONLY).

Reads trade_profit_capture_analysis + profit_protection_rule_backtests and produces SHADOW
recommendations per strategy family. These are NEVER grafted into config, strategy, GO/WAIT or
the executor — they are evidence for operator review only.

graft_verdict:
  DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE  — sample below MIN_SAMPLE (default 20) and no operator pilot.
  ELIGIBLE_FOR_OPERATOR_REVIEW        — positive net edge with adequate sample.
  REJECTED_NEGATIVE_EDGE              — best candidate rule does not beat baseline.

Writes `profit_protection_shadow_recommendations` only with --apply.
"""
import os, sys, json, argparse
from datetime import datetime, timezone
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

MIN_SAMPLE = 20   # operator may approve a strategy-specific pilot below this


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def current_thresholds(family):
    """Snapshot the family's current trailing tiers from strategy_trailing_policy (read-only)."""
    try:
        from strategy_trailing_policy import TRAILING_TIERS, DEFAULT_POLICY
        pol = TRAILING_TIERS.get(family, DEFAULT_POLICY)
        return {"trailing_tiers": [list(t) for t in pol.get("tiers", [])],
                "advisory_review_pct": 3.0, "advisory_lock_pct": 8.0}
    except Exception:
        return {}


def run(apply, json_path, md_path, run_id, min_sample):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # measurable population per family (sample size + baseline giveback)
    cur.execute("""
        SELECT coalesce(c.strategy_id,'unknown') strategy_id, c.measurable, c.winner,
               coalesce(c.money_left_usd,0) money_left
        FROM trade_profit_capture_analysis c WHERE c.measurable = true
    """)
    rows = cur.fetchall()

    # latest backtest run, best rule per family
    cur.execute("SELECT max(run_id) m FROM profit_protection_rule_backtests")
    latest = cur.fetchone()["m"]
    cur.execute("""SELECT rule_name, strategy_family, sample_size, baseline_money_left,
                          avoided_giveback, premature_exit_cost, net_improvement,
                          recommendation_confidence, recommended
                   FROM profit_protection_rule_backtests WHERE run_id = %s""", (latest,))
    backtests = [dict(r) for r in cur.fetchall()]
    conn.close()

    try:
        from strategy_trailing_policy import get_strategy_family
        fam_of = get_strategy_family
    except Exception:
        fam_of = lambda s: "unknown"

    # aggregate measurable population by family
    by_fam = defaultdict(lambda: {"n": 0, "winners": 0, "baseline_ml": 0.0})
    for r in rows:
        fam = fam_of(r["strategy_id"])
        by_fam[fam]["n"] += 1
        if r["winner"]:
            by_fam[fam]["winners"] += 1
        by_fam[fam]["baseline_ml"] += float(r["money_left"] or 0)

    # best applicable backtest rule per family (family-scoped first, else ALL)
    def best_rule_for(fam):
        cands = [b for b in backtests if b["strategy_family"] == fam] or \
                [b for b in backtests if b["strategy_family"] == "ALL"]
        cands = [b for b in cands if b["net_improvement"] is not None]
        return max(cands, key=lambda b: b["net_improvement"]) if cands else None

    recs = []
    for fam, agg in sorted(by_fam.items()):
        n = agg["n"]
        best = best_rule_for(fam)
        cur_th = current_thresholds(fam)
        if best is None:
            verdict, conf = "DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE", "low"
            proposed, exp_red, exp_prem = {}, 0.0, 0.0
            notes = "No backtest evidence available for this family."
        elif best["net_improvement"] is not None and best["net_improvement"] <= 0:
            verdict, conf = "REJECTED_NEGATIVE_EDGE", best["recommendation_confidence"]
            proposed = {"rejected_rule": best["rule_name"]}
            exp_red, exp_prem = 0.0, float(best["premature_exit_cost"] or 0)
            notes = f"Best candidate {best['rule_name']} net {best['net_improvement']} does not beat baseline."
        elif n < min_sample:
            verdict, conf = "DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE", "low"
            proposed = {"candidate_rule": best["rule_name"],
                        "trigger": best["rule_name"]}
            exp_red, exp_prem = float(best["avoided_giveback"] or 0), float(best["premature_exit_cost"] or 0)
            notes = (f"Positive edge ({best['rule_name']} net {best['net_improvement']}) but n={n} < {min_sample}. "
                     "Operator may approve a strategy-specific pilot.")
        else:
            verdict, conf = "ELIGIBLE_FOR_OPERATOR_REVIEW", best["recommendation_confidence"]
            proposed = {"candidate_rule": best["rule_name"]}
            exp_red, exp_prem = float(best["avoided_giveback"] or 0), float(best["premature_exit_cost"] or 0)
            notes = (f"{best['rule_name']} avoids ${best['avoided_giveback']} give-back at "
                     f"${best['premature_exit_cost']} premature-exit cost over n={n}. Operator review only.")

        recs.append({
            "run_id": run_id, "strategy_family": fam,
            "current_thresholds": json.dumps(cur_th),
            "proposed_thresholds": json.dumps(proposed),
            "evidence_sample_size": n,
            "expected_giveback_reduction": round(exp_red, 2),
            "expected_premature_exit_cost": round(exp_prem, 2),
            "confidence": conf, "graft_verdict": verdict, "notes": notes,
        })

    written = 0
    if apply:
        conn = db(); wc = conn.cursor()
        cols = ["run_id", "strategy_family", "current_thresholds", "proposed_thresholds",
                "evidence_sample_size", "expected_giveback_reduction", "expected_premature_exit_cost",
                "confidence", "graft_verdict", "notes"]
        for r in recs:
            wc.execute(f"""INSERT INTO profit_protection_shadow_recommendations ({','.join(cols)})
                VALUES ({','.join('%('+c+')s' for c in cols)})""", {c: r.get(c) for c in cols})
            written += 1
        conn.commit(); conn.close()

    report = {"run_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
              "applied": apply, "written": written, "min_sample": min_sample,
              "recommendations": [dict(r, current_thresholds=json.loads(r["current_thresholds"]),
                                       proposed_thresholds=json.loads(r["proposed_thresholds"])) for r in recs]}
    if json_path:
        json.dump(report, open(json_path, "w"), indent=2, default=str)
    if md_path:
        L = ["# Profit-Protection Shadow Threshold Recommendations (advisory only)", "",
             f"run_id: {run_id}  |  MIN_SAMPLE: {min_sample}", "",
             "**Shadow only. No config / strategy / GO-WAIT / executor mutation.**", "",
             "| family | n | exp reduction$ | exp premature$ | confidence | verdict |",
             "|--------|---|----------------|----------------|------------|---------|"]
        for r in recs:
            L.append(f"| {r['strategy_family']} | {r['evidence_sample_size']} | "
                     f"{r['expected_giveback_reduction']} | {r['expected_premature_exit_cost']} | "
                     f"{r['confidence']} | {r['graft_verdict']} |")
        open(md_path, "w").write("\n".join(L) + "\n")
    print(json.dumps({"run_id": run_id, "written": written,
                      "verdicts": {r["strategy_family"]: r["graft_verdict"] for r in recs}}, indent=2))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--min-sample", type=int, default=MIN_SAMPLE)
    ap.add_argument("--json", default=None)
    ap.add_argument("--markdown", default=None)
    a = ap.parse_args()
    rid = a.run_id or "ppsr_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run(a.apply, a.json, a.markdown, rid, a.min_sample)
