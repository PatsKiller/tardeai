#!/usr/bin/env python3
"""report_maturity_control_board.py — Consolidated maturity/readiness report.

Read-only. No mutations. No trading.

Usage:
    .venv/bin/python scripts/report_maturity_control_board.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from maturity_control_policy import (classify_live_readiness, classify_strategy_decision_readiness,
    classify_agent_learning_readiness, classify_backup_readiness, classify_area_status,
    recommended_next_actions, A5_END_DATE)


def _load_json(path):
    p = PROJ / path
    if p.exists():
        try: return json.loads(p.read_text())
        except: pass
    return None


def main():
    p = argparse.ArgumentParser(description="Maturity control board (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    a5_complete = now.strftime("%Y-%m-%d") >= A5_END_DATE

    # Load inputs
    gov = _load_json("docs/governance/governance_status_latest.json") or {}
    backup = _load_json("docs/recovery/phase_br1_offsite_backup_restore/br1_backup_readiness_results.json") or {}
    funnel = _load_json("docs/strategy_proof/phase_sp1_strategy_proof_governance/sp1_strategy_evidence_funnel_results.json") or {}
    a5 = _load_json("docs/project/a5_observation/a5_interim_strategy_readiness_results.json") or {}
    a1a = _load_json("docs/governance/a1a_latest_check_results.json") or {}

    # Safety
    env_flags = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            if k.strip() in ("ALPACA_MODE", "LLM_DISABLE_LIVE_EXECUTION"):
                env_flags[k.strip()] = v.strip()

    closed_trades = sum(s.get("closed_count", 0) for s in funnel.get("strategies", []))

    # Area scores
    areas = {
        "execution_safety": classify_area_status(9.0),
        "architecture": classify_area_status(8.7),
        "strategy_proof": classify_area_status(4.0 if closed_trades < 20 else 6.5,
            ["insufficient closed trades"] if closed_trades < 20 else None),
        "agent_learning": classify_agent_learning_readiness({"evidence_quality": "weak" if closed_trades < 10 else "preliminary"}),
        "backup_recovery": classify_backup_readiness({
            "backup_score": backup.get("overall_score", 5.3),
            "offsite_configured": backup.get("offsite_configured", False),
            "restore_drill_passed": False}),
        "documentation": classify_area_status(6.5),
        "governance": classify_area_status(8.0 if a1a.get("status") == "healthy" else 6.0),
        "operational": classify_area_status(8.0),
        "live_readiness": classify_live_readiness({
            "alpaca_mode": env_flags.get("ALPACA_MODE"),
            "a5_complete": a5_complete, "backup_readiness": backup.get("overall_score", 5.3),
            "closed_trades": closed_trades, "win_rate": 0}),
    }

    strategy_decision = classify_strategy_decision_readiness({
        "a5_complete": a5_complete, "strategies_decision_ready": 0, "closed_trades": closed_trades})
    next_actions = recommended_next_actions({"offsite_configured": backup.get("offsite_configured", False)})

    overall = round(sum(a.get("score", 5) for a in areas.values() if "score" in a) /
                    max(1, sum(1 for a in areas.values() if "score" in a)), 1)

    blockers = []
    for name, area in areas.items():
        if area.get("status") == "blocked":
            blockers.extend([f"{name}: {b}" for b in area.get("blockers", [])])

    report = {
        "generated_at": now.isoformat(), "overall_score": overall,
        "a5_complete": a5_complete, "a5_end_date": A5_END_DATE,
        "closed_trades": closed_trades,
        "areas": {k: {kk: vv for kk, vv in v.items()} for k, v in areas.items()},
        "strategy_decision_readiness": strategy_decision,
        "next_actions": next_actions, "blockers": blockers,
        "safety": env_flags,
    }

    if args.verbose:
        print(f"Maturity Control Board — Score {overall}/10")
        print(f"  A-5: {'complete' if a5_complete else 'in progress'} (ends {A5_END_DATE})")
        print(f"  Closed trades: {closed_trades}")
        for name, area in areas.items():
            s = area.get("score", "?")
            st = area.get("status", "?")
            print(f"  {name:25s} {s}/10 [{st}]")
        if blockers:
            print(f"\n  Blockers ({len(blockers)}):")
            for b in blockers[:5]:
                print(f"    - {b}")
        print(f"\n  Next actions:")
        for a in next_actions:
            print(f"    [{a['status']}] {a['action']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Maturity Control Board — {overall}/10", "",
              f"A-5: {'complete' if a5_complete else 'in progress'} | Closed trades: {closed_trades}", "",
              "| Area | Score | Status |", "|------|-------|--------|"]
        for n, a in areas.items():
            md.append(f"| {n} | {a.get('score','?')} | {a.get('status','?')} |")
        if blockers:
            md.extend(["", "## Blockers"] + [f"- {b}" for b in blockers])
        md.extend(["", "## Next Actions"] + [f"- [{a['status']}] {a['action']}" for a in next_actions])
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
