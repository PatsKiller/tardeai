"""
proposal_strategy_fit.py — Score how well a proposal fits its assigned strategy YAML.

CLI:
  .venv/bin/python scripts/proposal_strategy_fit.py --pending --dry-run
  .venv/bin/python scripts/proposal_strategy_fit.py --pending --apply
  .venv/bin/python scripts/proposal_strategy_fit.py --proposal-id 123 --apply
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import yaml
from psycopg2.extras import RealDictCursor

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

STRATEGIES_DIR = PROJECT_ROOT / "config" / "strategies"

# ── Grade thresholds ────────────────────────────────────────────────────────
GRADE_THRESHOLDS = [
    (80, "STRONG_FIT"),
    (60, "GOOD_FIT"),
    (40, "MARGINAL_FIT"),
    (0, "POOR_FIT"),
]

# ── Setup class definitions per strategy ────────────────────────────────────
SETUP_CLASSES = {
    "momentum_scalp": {
        "high_rvol_low_float_momentum": lambda d: d["rvol"] >= 8 and d["float_m"] <= 20,
        "news_momentum_scalp": lambda d: d["catalyst_verified"] and d["rvol"] >= 5,
        "vwap_reclaim": lambda d: d.get("vwap_position") == "above" and d["rvol"] >= 5,
        "opening_range_breakout": lambda d: d["rvol"] >= 5 and d["gap_pct"] >= 5,
    },
    "gap_and_go": {
        "earnings_gap_and_go": lambda d: d["gap_pct"] >= 5 and "earning" in (d.get("catalyst_text") or "").lower(),
        "premarket_gap_with_catalyst": lambda d: d["gap_pct"] >= 5 and d["catalyst_present"],
        "low_float_gap_continuation": lambda d: d["gap_pct"] >= 5 and d["float_m"] <= 20,
    },
    "swing_breakout": {
        "earnings_breakout_from_base": lambda d: d["catalyst_verified"] and "earning" in (d.get("catalyst_text") or "").lower(),
        "multi_day_base_breakout": lambda d: d["rvol"] >= 1.5 and not d["catalyst_verified"],
        "resistance_breakout_with_volume": lambda d: d["rvol"] >= 2.0,
    },
    "earnings_catalyst": {
        "earnings_beat_continuation": lambda d: d["catalyst_verified"] and d["gap_pct"] >= 3,
        "guidance_raise": lambda d: d["catalyst_verified"] and "guidance" in (d.get("catalyst_text") or "").lower(),
        "surprise_profitability": lambda d: d["catalyst_verified"] and "profit" in (d.get("catalyst_text") or "").lower(),
    },
}


# ── Helpers ─────────────────────────────────────────────────────────────────
def _load_strategy_yaml(strategy_id: str) -> dict:
    """Load and return the strategy YAML config."""
    path = STRATEGIES_DIR / f"{strategy_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Strategy YAML not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def _safe_float(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _grade_from_score(score: int) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "POOR_FIT"


def _classify_setup(strategy_id: str, data: dict) -> str:
    """Pick the best-matching setup class for this strategy."""
    classes = SETUP_CLASSES.get(strategy_id, {})
    for name, predicate in classes.items():
        try:
            if predicate(data):
                return name
        except (KeyError, TypeError):
            continue
    return "unclassified"


# ── Criteria checkers ───────────────────────────────────────────────────────
def _check_criteria(strategy_id: str, cfg: dict, proposal: dict,
                    scan: dict, indicators: dict) -> tuple:
    """
    Return (criteria_met: list[str], criteria_failed: list[str], raw_points: int).
    Each criterion is worth a share of 100 points.
    """
    met, failed = [], []
    filters = cfg.get("screen_filters", {})
    setup = cfg.get("setup_qualification", {})

    rvol = _safe_float(proposal.get("rvol") or scan.get("rvol"))
    float_m = _safe_float(proposal.get("float_m") or scan.get("float_m"))
    gap_pct = _safe_float(proposal.get("gap_pct") or scan.get("gap_pct"))
    catalyst = proposal.get("catalyst") or scan.get("catalyst") or ""
    catalyst_verified = bool(
        proposal.get("catalyst_verified") or scan.get("catalyst_verified")
    )
    signal_score = _safe_float(proposal.get("signal_score"))
    rr = _safe_float(proposal.get("proposed_rr"))

    # ── RSI from indicators ─────────────────────────────────────────────
    rsi = None
    vwap_pos = None
    atr = None
    if indicators:
        signals = indicators.get("signals", {})
        rsi_block = signals.get("rsi", {})
        rsi = rsi_block.get("value")
        vwap_block = signals.get("vwap", {})
        vwap_details = vwap_block.get("details", {})
        vwap_pos = vwap_details.get("position")
        atr_block = signals.get("atr", {})
        atr = atr_block.get("value")

    criteria = []  # (label, passed)

    # ── RVOL ────────────────────────────────────────────────────────────
    min_rvol = filters.get("min_rvol")
    if min_rvol is not None:
        passed = rvol >= float(min_rvol)
        criteria.append((f"RVOL {rvol:.1f}x >= {min_rvol}x", passed))

    # ── Float ───────────────────────────────────────────────────────────
    max_float = filters.get("max_float_m")
    if max_float is not None:
        passed = float_m <= float(max_float)
        criteria.append((f"Float {float_m:.0f}M <= {max_float}M", passed))

    # ── Gap % ───────────────────────────────────────────────────────────
    min_gap = filters.get("min_gap_pct")
    if min_gap is not None:
        passed = gap_pct >= float(min_gap)
        criteria.append((f"Gap {gap_pct:.1f}% >= {min_gap}%", passed))

    # ── Catalyst presence / verification ────────────────────────────────
    cat_required = (
        setup.get("catalyst_present") == "required"
        or setup.get("catalyst_required") is True
    )
    cat_verify_required = setup.get("catalyst_verification") == "required"

    if cat_required:
        passed = bool(catalyst)
        criteria.append(("Catalyst present" if passed else "Catalyst missing", passed))

    if cat_verify_required:
        passed = catalyst_verified
        criteria.append(("Verified catalyst" if passed else "Catalyst not verified", passed))
    elif catalyst_verified:
        # Bonus credit for verified even if not required
        criteria.append(("Verified catalyst (bonus)", True))

    # ── Signal score ────────────────────────────────────────────────────
    min_score = filters.get("min_score")
    if min_score is not None:
        passed = signal_score >= float(min_score)
        criteria.append((f"Score {signal_score:.0f} >= {min_score}", passed))

    # ── R:R ratio ───────────────────────────────────────────────────────
    if rr > 0:
        passed = rr >= 2.0
        criteria.append((f"R:R {rr:.1f} >= 2.0", passed))

    # ── RSI ─────────────────────────────────────────────────────────────
    if rsi is not None:
        rsi_val = _safe_float(rsi)
        if strategy_id in ("momentum_scalp", "gap_and_go"):
            passed = 30 <= rsi_val <= 80
            criteria.append((f"RSI {rsi_val:.0f} in [30-80]", passed))
        else:
            passed = rsi_val <= 70
            criteria.append((f"RSI {rsi_val:.0f} <= 70", passed))
    else:
        criteria.append(("RSI unavailable", False))

    # ── VWAP position (momentum / gap) ──────────────────────────────────
    if strategy_id in ("momentum_scalp", "gap_and_go"):
        if vwap_pos:
            passed = vwap_pos == "above"
            criteria.append((f"VWAP position: {vwap_pos}", passed))
        else:
            criteria.append(("VWAP data unavailable", False))

    # ── ATR sanity (stop distance) ──────────────────────────────────────
    if atr is not None:
        atr_val = _safe_float(atr)
        entry = _safe_float(proposal.get("proposed_entry"))
        stop = _safe_float(proposal.get("proposed_stop"))
        if entry > 0 and stop > 0:
            stop_dist = abs(entry - stop)
            passed = stop_dist <= 2 * atr_val if atr_val > 0 else True
            criteria.append(
                (f"Stop distance ${stop_dist:.2f} <= 2*ATR ${2*atr_val:.2f}", passed)
            )

    # ── Risk gate ───────────────────────────────────────────────────────
    rg = proposal.get("risk_gate_result")
    if rg:
        passed = str(rg).upper() in ("APPROVED", "PASS", "TRUE")
        criteria.append((f"Risk gate: {rg}", passed))

    # ── Tally ───────────────────────────────────────────────────────────
    for label, passed in criteria:
        (met if passed else failed).append(label)

    total = len(criteria)
    passed_count = len(met)
    raw_score = int(round(100 * passed_count / total)) if total > 0 else 0

    return met, failed, raw_score


def _build_narrative(symbol: str, strategy_id: str, met: list,
                     failed: list, grade: str) -> str:
    total = len(met) + len(failed)
    return (
        f"{symbol} meets {len(met)} of {total} {strategy_id} criteria "
        f"({grade}). "
        + (f"Key strengths: {', '.join(met[:3])}. " if met else "")
        + (f"Gaps: {', '.join(failed[:3])}." if failed else "All criteria satisfied.")
    )


# ── Main scoring function ──────────────────────────────────────────────────
def score_proposal(conn, proposal_id: int) -> dict:
    """Score a single proposal and return the fit result dict."""
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Fetch proposal
    cur.execute(
        "SELECT * FROM paper_trade_proposals WHERE id = %s", (proposal_id,)
    )
    proposal = cur.fetchone()
    if not proposal:
        return {"error": f"Proposal {proposal_id} not found"}

    strategy_id = proposal["strategy_id"]
    symbol = proposal["symbol"]

    # Load strategy YAML
    try:
        cfg = _load_strategy_yaml(strategy_id)
    except FileNotFoundError as e:
        return {"error": str(e), "proposal_id": proposal_id}

    # Fetch scan data
    cur.execute(
        """SELECT * FROM trade_ai_scans
           WHERE symbol = %s
           ORDER BY scanned_at DESC LIMIT 1""",
        (symbol,),
    )
    scan = cur.fetchone() or {}

    # Fetch indicator data
    cur.execute(
        """SELECT full_result FROM indicator_confluence_cache
           WHERE symbol = %s
           ORDER BY computed_at DESC LIMIT 1""",
        (symbol,),
    )
    ind_row = cur.fetchone()
    indicators = {}
    if ind_row and ind_row.get("full_result"):
        raw = ind_row["full_result"]
        indicators = raw if isinstance(raw, dict) else json.loads(raw)

    # Check criteria
    met, failed, raw_score = _check_criteria(
        strategy_id, cfg, dict(proposal), dict(scan) if scan else {}, indicators
    )

    grade = _grade_from_score(raw_score)

    # Build classification data dict
    data = {
        "rvol": _safe_float(proposal.get("rvol") or scan.get("rvol", 0)),
        "float_m": _safe_float(proposal.get("float_m") or scan.get("float_m", 0)),
        "gap_pct": _safe_float(proposal.get("gap_pct") or scan.get("gap_pct", 0)),
        "catalyst_present": bool(proposal.get("catalyst") or scan.get("catalyst")),
        "catalyst_verified": bool(
            proposal.get("catalyst_verified") or scan.get("catalyst_verified")
        ),
        "catalyst_text": str(proposal.get("catalyst") or scan.get("catalyst") or ""),
        "vwap_position": indicators.get("signals", {}).get("vwap", {}).get("details", {}).get("position"),
    }
    setup_class = _classify_setup(strategy_id, data)

    narrative = _build_narrative(symbol, strategy_id, met, failed, grade)

    return {
        "proposal_id": proposal_id,
        "symbol": symbol,
        "fit_score": raw_score,
        "fit_grade": grade,
        "strategy_id": strategy_id,
        "setup_class": setup_class,
        "criteria_met": met,
        "criteria_failed": failed,
        "narrative": narrative,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Score proposal fit against strategy YAML."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pending", action="store_true",
                       help="Score all pending proposals")
    group.add_argument("--proposal-id", type=int,
                       help="Score a single proposal by ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results only, do not apply")
    parser.add_argument("--apply", action="store_true",
                        help="Apply results (write JSON output)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    conn = get_conn()
    results = []

    try:
        if args.proposal_id:
            result = score_proposal(conn, args.proposal_id)
            results.append(result)
        else:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT id FROM paper_trade_proposals
                   WHERE risk_gate_result IS NOT NULL
                   ORDER BY id"""
            )
            rows = cur.fetchall()
            log.info("Found %d pending proposals to score", len(rows))
            for row in rows:
                result = score_proposal(conn, row["id"])
                results.append(result)

        # Output
        for r in results:
            grade = r.get("fit_grade", "ERROR")
            symbol = r.get("symbol", "?")
            score = r.get("fit_score", 0)
            log.info(
                "%-6s  %-14s  score=%3d  grade=%-12s  setup=%s",
                symbol,
                r.get("strategy_id", "?"),
                score,
                grade,
                r.get("setup_class", "?"),
            )

        if args.apply:
            outfile = PROJECT_ROOT / "data" / "proposal_fit_results.json"
            outfile.parent.mkdir(parents=True, exist_ok=True)
            with open(outfile, "w") as f:
                json.dump(results, f, indent=2, default=str)
            log.info("Wrote %d results to %s", len(results), outfile)
        else:
            print(json.dumps(results, indent=2, default=str))

    finally:
        conn.close()


if __name__ == "__main__":
    main()
