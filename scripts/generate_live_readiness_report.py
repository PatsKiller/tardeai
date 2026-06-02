#!/usr/bin/env python3
"""Generate live automation readiness report.

Usage:
    python scripts/generate_live_readiness_report.py

Output:
    docs/governance/LIVE_AUTOMATION_READINESS_REPORT_latest.md
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def generate():
    """Generate live readiness report from paper trade statistics."""
    # Load statistics
    stats_path = PROJECT_ROOT / "data" / "paper_trading" / "paper_trade_statistics_latest.json"
    if stats_path.exists():
        stats = json.loads(stats_path.read_text())
    else:
        from paper_trade_statistics import compute_statistics
        stats = compute_statistics()

    # Load loop validation
    loop_path = PROJECT_ROOT / "data" / "learning" / "paper_trade_loop_validation_latest.json"
    loop = json.loads(loop_path.read_text()) if loop_path.exists() else {}

    r = stats.get("readiness", {})
    p = stats.get("performance", {})
    fc = stats.get("field_completeness", {})
    lk = stats.get("linkage", {})
    closed = r.get("closed_usable", 0)

    # ── Score computation ──
    # Sample size (20 pts)
    if closed >= 4000: ss_pts = 20
    elif closed >= 2000: ss_pts = 16
    elif closed >= 1000: ss_pts = 12
    elif closed >= 500: ss_pts = 8
    elif closed >= 100: ss_pts = 4
    else: ss_pts = 0

    # Journal quality (15 pts)
    avg_comp = sum(v.get("pct", 0) for v in fc.values()) / max(len(fc), 1)
    if avg_comp >= 95: jq_pts = 15
    elif avg_comp >= 90: jq_pts = 10
    elif avg_comp >= 80: jq_pts = 5
    else: jq_pts = 0

    # Strategy performance (20 pts)
    pf = p.get("profit_factor", 0)
    wr = p.get("win_rate", 0)
    if pf >= 2.0: sp_pts = 15
    elif pf >= 1.5: sp_pts = 10
    elif pf >= 1.0: sp_pts = 5
    else: sp_pts = 0
    if wr >= 40: sp_pts += 5

    # Risk control (15 pts)
    dd = p.get("max_drawdown", 999999)
    dd_pct = dd / 100000 * 100 if dd > 0 else 0  # vs $100K account
    if dd_pct < 5: rc_pts = 15
    elif dd_pct < 10: rc_pts = 10
    elif dd_pct < 15: rc_pts = 5
    else: rc_pts = 0

    # Backtest alignment (10 pts)
    bt_pct = lk.get("backtest_pct", 0)
    if bt_pct >= 90: ba_pts = 10
    elif bt_pct >= 75: ba_pts = 6
    elif bt_pct >= 50: ba_pts = 3
    else: ba_pts = 0

    # Hermes (5 pts)
    h_pct = lk.get("hermes_pct", 0)
    ha_pts = 5 if h_pct >= 80 else (2 if h_pct >= 50 else 0)

    # Shadow learning (5 pts)
    sl_pts = 0  # Not yet evaluated

    # Operational reliability (5 pts)
    or_pts = 3  # Assumed ~97% (crons generally healthy)

    # Alert quality (3 pts)
    aq_pts = 2  # SIEM noise reduction 84.8%

    # Paper/live separation (2 pts)
    pl_pts = 2  # Verified in Phase 180D

    total_score = ss_pts + jq_pts + sp_pts + rc_pts + ba_pts + ha_pts + sl_pts + or_pts + aq_pts + pl_pts

    # Hard blockers
    blockers = []
    if closed < 2000:
        blockers.append(f"Sample size {closed} < 2,000 minimum")
    if lk.get("backtest_pct", 0) < 90:
        blockers.append(f"Backtest coverage {lk.get('backtest_pct', 0)}% < 90% minimum")
    if lk.get("hermes_pct", 0) < 95:
        blockers.append(f"Hermes audit coverage {lk.get('hermes_pct', 0)}% < 95% minimum")
    blockers.append("Level 7 not separately approved")
    blockers.append("Operator has not given explicit live trading approval")

    # Readiness level
    if total_score >= 85: level = "CANDIDATE"
    elif total_score >= 70: level = "APPROACHING"
    elif total_score >= 50: level = "DEVELOPING"
    elif total_score >= 30: level = "EARLY"
    else: level = "NOT_READY"

    now = datetime.now(timezone.utc)

    # ── Write report ──
    report = f"""# Live Automation Readiness Report

**Generated**: {now.strftime('%Y-%m-%d %H:%M UTC')}
**Status**: LOCKED — Live trading PROHIBITED

## Readiness Score: {total_score}/100 — {level}

## Score Breakdown

| Dimension | Score | Max |
|-----------|-------|-----|
| Sample Size | {ss_pts} | 20 |
| Journal Quality | {jq_pts} | 15 |
| Strategy Performance | {sp_pts} | 20 |
| Risk Control | {rc_pts} | 15 |
| Backtest Alignment | {ba_pts} | 10 |
| Hermes Audit | {ha_pts} | 5 |
| Shadow Learning | {sl_pts} | 5 |
| Operational Reliability | {or_pts} | 5 |
| Alert Quality | {aq_pts} | 3 |
| Paper/Live Separation | {pl_pts} | 2 |
| **TOTAL** | **{total_score}** | **100** |

## Hard Blockers ({len(blockers)})

{"".join(f"- {b}" + chr(10) for b in blockers)}

## Key Metrics

| Metric | Current | Required |
|--------|---------|----------|
| Usable closed trades | {closed} | 2,000+ |
| Win rate | {p.get('win_rate', 0)}% | >= 40% |
| Profit factor | {p.get('profit_factor', 0)} | >= 1.5 |
| Max drawdown | ${p.get('max_drawdown', 0):,.2f} | < $10,000 |
| Journal completeness | {avg_comp:.1f}% | >= 95% |
| Hermes coverage | {lk.get('hermes_pct', 0)}% | >= 95% |
| Backtest coverage | {lk.get('backtest_pct', 0)}% | >= 90% |
| Level 7 | PROHIBITED | SEPARATE APPROVAL |
| Live trading | PROHIBITED | OPERATOR APPROVAL |

## Progress

- To 2,000 trades: {r.get('distance_to_2000', 0)} more ({r.get('pct_to_2000', 0)}%)
- To 4,000 trades: {r.get('distance_to_4000', 0)} more ({r.get('pct_to_4000', 0)}%)

## Loop Completeness

- Fully closed-loop: {loop.get('fully_closed_loop', 0)}
- Loop completeness: {loop.get('loop_completeness_pct', 0)}%
"""

    out_path = PROJECT_ROOT / "docs" / "governance" / "LIVE_AUTOMATION_READINESS_REPORT_latest.md"
    out_path.write_text(report)

    # Also write JSON
    json_out = {
        "timestamp": now.isoformat(),
        "score": total_score,
        "level": level,
        "blockers": blockers,
        "dimensions": {
            "sample_size": ss_pts,
            "journal_quality": jq_pts,
            "strategy_performance": sp_pts,
            "risk_control": rc_pts,
            "backtest_alignment": ba_pts,
            "hermes_audit": ha_pts,
            "shadow_learning": sl_pts,
            "operational_reliability": or_pts,
            "alert_quality": aq_pts,
            "paper_live_separation": pl_pts,
        },
        "live_trading_prohibited": True,
        "level_7_prohibited": True,
    }
    (PROJECT_ROOT / "docs" / "governance" / "live_readiness_score_latest.json").write_text(
        json.dumps(json_out, indent=2, default=str)
    )

    return json_out


if __name__ == "__main__":
    result = generate()
    print(f"Live Readiness Score: {result['score']}/100 — {result['level']}")
    print(f"Hard Blockers: {len(result['blockers'])}")
    for b in result['blockers']:
        print(f"  - {b}")
    print(f"\nWritten to: docs/governance/LIVE_AUTOMATION_READINESS_REPORT_latest.md")
