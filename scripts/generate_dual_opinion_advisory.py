#!/usr/bin/env python3
"""
Generate dual-opinion advisory records: TradeAI original vs Hermes enhancement.
Hermes audits, enhances, and adds a second opinion without overwriting TradeAI.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def generate_dual_opinions(max_items=10):
    """Generate side-by-side TradeAI vs Hermes opinions."""
    from strategy_learning_shadow_scorer import shadow_score
    from generate_candidate_decision_lineage import generate_lineage

    shadow = shadow_score()
    lineage = generate_lineage()

    # Build lineage lookup
    lineage_map = {l["symbol"]: l for l in lineage.get("lineage", [])}

    opinions = []
    for r in shadow["results"][:max_items]:
        sym = r["symbol"]
        lin = lineage_map.get(sym, {})
        delta = r["delta"]

        # TradeAI original
        tradeai_original = {
            "score": r["original_score"],
            "decision": r.get("decision", "unknown"),
            "strategy": r.get("strategy", "unknown"),
            "summary": f"{sym} scored {r['original_score']} by TradeAI. Decision: {r.get('decision', 'unknown')}.",
        }

        # Hermes audit
        missing = []
        if not lin.get("has_learning_links"):
            missing.append("No learning data available for this strategy")
        if r.get("sample_size_warning"):
            missing.append("Sample size insufficient for strategy validation")

        risk_flags = []
        for lt in lin.get("lesson_types", []):
            if lt == "stop_too_tight":
                risk_flags.append("Stop placement defect detected in this strategy")
            elif lt == "premature_exit":
                risk_flags.append("Prior trades stopped out prematurely (price recovered after)")
            elif lt == "weak_backtest":
                risk_flags.append("Backtest performance below minimum viability threshold")
            elif lt == "sample_size_insufficient":
                risk_flags.append("No live trades to validate — backtest-only strategy")

        # Hermes agreement
        if delta == 0:
            agreement = "AGREE"
            hermes_summary = f"Hermes agrees with TradeAI score of {r['original_score']}. No learning data contradicts this candidate."
        elif delta > -3:
            agreement = "AGREE_WITH_CAUTION"
            hermes_summary = f"Hermes mostly agrees but flags minor concerns. Shadow adjustment: {delta:+d} ({r['original_score']}→{r['shadow_score']})."
        elif delta >= -6:
            agreement = "NEEDS_MORE_EVIDENCE"
            hermes_summary = f"Hermes suggests caution. {len(risk_flags)} risk flag(s). Shadow: {delta:+d} ({r['original_score']}→{r['shadow_score']})."
        else:
            agreement = "DISAGREE"
            hermes_summary = f"Hermes disagrees with current score. Significant learning evidence: {delta:+d} delta. {len(risk_flags)} risk flag(s)."

        opinions.append({
            "object_type": "momentum_candidate",
            "object_id": sym,
            "symbol": sym,
            "strategy": r.get("strategy"),
            "tradeai_original": tradeai_original,
            "hermes_audit": {
                "missing_context": missing,
                "risk_flags": risk_flags,
                "learning_links": lin.get("lesson_count", 0),
            },
            "hermes_enhancement": {
                "shadow_score": r["shadow_score"],
                "delta": delta,
                "lesson_types": lin.get("lesson_types", []),
                "summary": hermes_summary,
            },
            "hermes_agreement_status": agreement,
            "hermes_confidence": min(0.8, 0.3 + lin.get("lesson_count", 0) * 0.1),
            "recommended_operator_choice": "KEEP_TRADEAI_ORIGINAL" if agreement == "AGREE" else "REVIEW_BOTH",
            "operator_choice": None,
            "no_overwrite": True,
            "advisory_only": True,
            "created_at": datetime.now().isoformat(),
        })

    # Summary
    agrees = sum(1 for o in opinions if o["hermes_agreement_status"] == "AGREE")
    caution = sum(1 for o in opinions if o["hermes_agreement_status"] == "AGREE_WITH_CAUTION")
    needs_evidence = sum(1 for o in opinions if o["hermes_agreement_status"] == "NEEDS_MORE_EVIDENCE")
    disagrees = sum(1 for o in opinions if o["hermes_agreement_status"] == "DISAGREE")

    return {
        "timestamp": datetime.now().isoformat(),
        "total": len(opinions),
        "agrees": agrees,
        "agrees_with_caution": caution,
        "needs_more_evidence": needs_evidence,
        "disagrees": disagrees,
        "opinions": opinions,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    output = generate_dual_opinions(args.max)
    print(f"Dual-Opinion Advisory")
    print(f"  Total: {output['total']}")
    print(f"  Agrees: {output['agrees']}")
    print(f"  Agrees w/ caution: {output['agrees_with_caution']}")
    print(f"  Needs more evidence: {output['needs_more_evidence']}")
    print(f"  Disagrees: {output['disagrees']}")
    print(f"\nSample opinions:")
    for o in output["opinions"][:5]:
        print(f"  {o['symbol']:8s} TradeAI={o['tradeai_original']['score']} Shadow={o['hermes_enhancement']['shadow_score']} "
              f"Agreement={o['hermes_agreement_status']} Recommend={o['recommended_operator_choice']}")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(output, indent=2, default=str))
        print(f"\nWritten to {args.json_out}")
