#!/usr/bin/env python3
"""multi_setup_router.py — Evaluate symbols against all strategy YAMLs, build setup stacks.

A symbol can match multiple strategies. This router:
1. Evaluates each strategy's entry criteria and auto-disqualifiers
2. Calculates match scores
3. Determines primary strategy by deterministic priority
4. Records setup_stack in strategy_setup_matches

Usage:
    .venv/bin/python scripts/multi_setup_router.py --symbol SMX --dry-run
    .venv/bin/python scripts/multi_setup_router.py --pending-proposals --apply
    .venv/bin/python scripts/multi_setup_router.py --today-signals --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn
from strategy_config_loader import load_all_strategy_configs, get_strategy_prompt_context

log = logging.getLogger("multi_setup_router")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Strategies that are fast-execution eligible (not just review/governance)
EXECUTION_STRATEGIES = {
    "momentum_scalp", "gap_and_go", "earnings_catalyst",
    "swing_breakout", "swing_trade", "speculative_growth",
    "sector_rotation", "income_add", "recovery_watch", "tax_loss_harvest",
}

# Derive from YAML configs — no hardcoded list
try:
    from proposal_lifecycle import INTRADAY_STRATEGIES
except ImportError:
    INTRADAY_STRATEGIES = {"momentum_scalp", "gap_and_go"}  # safe fallback


def evaluate_strategy_match(config: dict, signal: dict) -> dict:
    """Evaluate how well a signal matches a strategy config."""
    sid = config.get("strategy_id", "?")
    criteria_met = []
    criteria_failed = []
    disqualifiers_hit = []
    missing_data = []
    score = 0

    # Check entry criteria
    for criterion in (config.get("entry_criteria") or []):
        cid = criterion.get("id", "?")
        metric = criterion.get("metric", "")
        operator = criterion.get("operator", "gte")
        value = criterion.get("value")

        actual = signal.get(metric)
        if actual is None:
            missing_data.append(cid)
            continue

        try:
            actual_num = float(actual) if not isinstance(actual, bool) else (1 if actual else 0)
            value_num = float(value) if value is not None else 0

            passed = False
            if operator == "gte":
                passed = actual_num >= value_num
            elif operator == "lte":
                passed = actual_num <= value_num
            elif operator == "gt":
                passed = actual_num > value_num
            elif operator == "lt":
                passed = actual_num < value_num
            elif operator == "eq":
                passed = actual_num == value_num
            elif operator == "exists":
                passed = actual is not None and actual != ""
            elif operator == "in":
                passed = str(actual) in (value if isinstance(value, list) else [value])

            if passed:
                criteria_met.append(cid)
                score += 10
            else:
                criteria_failed.append(cid)
        except (ValueError, TypeError):
            missing_data.append(cid)

    # Check auto-disqualifiers
    for disq in (config.get("auto_disqualifiers") or []):
        did = disq.get("id", "?")
        condition = disq.get("condition", "")
        # Simple condition evaluation
        if _check_disqualifier(condition, signal):
            disqualifiers_hit.append(did)

    # Scoring adjustments
    universe = config.get("universe", {})
    if isinstance(universe, dict):
        price_cfg = universe.get("price", {})
        if isinstance(price_cfg, dict):
            min_p = price_cfg.get("min")
            max_p = price_cfg.get("max")
            price = signal.get("price") or signal.get("proposed_entry")
            if price and min_p and float(price) >= float(min_p):
                score += 5
            if price and max_p and float(price) <= float(max_p):
                score += 5

        rvol_cfg = universe.get("rvol", {})
        if isinstance(rvol_cfg, dict):
            min_rvol = rvol_cfg.get("min")
            rvol = signal.get("rvol") or signal.get("relative_volume")
            if rvol and min_rvol and float(rvol) >= float(min_rvol):
                score += 15

    # Bonus for catalyst match
    if signal.get("catalyst") and signal.get("catalyst_verified"):
        score += 10
    elif signal.get("catalyst"):
        score += 5

    # Determine match status
    is_blocked = len(disqualifiers_hit) > 0
    match_status = "BLOCKED" if is_blocked else (
        "STRONG_MATCH" if score >= 50 else
        "MODERATE_MATCH" if score >= 30 else
        "WEAK_MATCH" if score >= 10 else
        "NO_MATCH"
    )

    return {
        "strategy_id": sid,
        "match_score": score,
        "match_status": match_status,
        "criteria_met": criteria_met,
        "criteria_failed": criteria_failed,
        "disqualifiers_hit": disqualifiers_hit,
        "missing_data": missing_data,
        "is_blocked": is_blocked,
        "is_execution_strategy": sid in EXECUTION_STRATEGIES,
    }


def _check_disqualifier(condition: str, signal: dict) -> bool:
    """Simple condition evaluator for auto-disqualifiers."""
    if not condition:
        return False
    try:
        # Parse simple conditions like "price > 25", "float_m > 100"
        parts = condition.replace("_", " ").split()
        if len(parts) >= 3:
            field = condition.split()[0]
            val = signal.get(field)
            if val is None:
                return False
            op = parts[1] if len(parts) > 1 else ""
            threshold = float(parts[-1]) if parts[-1].replace(".", "").isdigit() else 0
            actual = float(val)
            if ">" in condition and "=" not in condition:
                return actual > threshold
            if ">=" in condition:
                return actual >= threshold
            if "<" in condition and "=" not in condition:
                return actual < threshold
    except (ValueError, IndexError, TypeError):
        pass
    return False


def select_primary_strategy(matches: list) -> list:
    """Deterministic primary strategy selection from a list of matches."""
    # Filter out blocked
    executable = [m for m in matches if not m["is_blocked"] and m["match_status"] != "NO_MATCH"]
    blocked = [m for m in matches if m["is_blocked"]]

    if not executable:
        # All blocked or no matches
        for m in matches:
            m["is_primary"] = False
            m["priority_rank"] = 99
            m["reason"] = "BLOCKED" if m["is_blocked"] else "NO_MATCH"
        return matches

    # Sort by: execution_strategy first, then score descending
    executable.sort(key=lambda m: (
        0 if m["is_execution_strategy"] else 1,
        -m["match_score"],
    ))

    # Assign ranks
    for i, m in enumerate(executable):
        m["priority_rank"] = i + 1
        m["is_primary"] = i == 0
        if i == 0:
            m["reason"] = "PRIMARY: highest-scoring executable strategy"
        else:
            m["reason"] = f"SECONDARY: rank {i+1}"

    for m in blocked:
        m["is_primary"] = False
        m["priority_rank"] = 99
        m["reason"] = f"BLOCKED: {m['disqualifiers_hit']}"

    return executable + blocked


def route_symbol(symbol: str, signal: dict, configs: dict) -> dict:
    """Route a symbol through all strategies, return setup stack.

    The proposal's strategy_id is always the primary. The router adds
    secondary matches but does not override the assigned strategy.
    """
    proposal_strategy = signal.get("strategy_id", "momentum_scalp")

    matches = []
    for sid, config in configs.items():
        match = evaluate_strategy_match(config, signal)
        if match["match_status"] != "NO_MATCH" or match["is_blocked"]:
            matches.append(match)

    if not matches:
        return {
            "symbol": symbol,
            "primary_strategy_id": proposal_strategy,
            "secondary_strategy_ids": [],
            "setup_stack": [],
            "match_count": 0,
        }

    # Mark the proposal's own strategy as primary
    for m in matches:
        if m["strategy_id"] == proposal_strategy:
            m["is_primary"] = True
            m["priority_rank"] = 1
            m["reason"] = "PRIMARY: proposal strategy"
        else:
            m["is_primary"] = False

    # Rank secondaries by score
    secondaries = sorted(
        [m for m in matches if not m["is_primary"] and not m.get("is_blocked")],
        key=lambda m: -m["match_score"]
    )
    for i, m in enumerate(secondaries):
        m["priority_rank"] = i + 2
        m["reason"] = f"SECONDARY: rank {i + 2}"

    blocked = [m for m in matches if m.get("is_blocked") and not m.get("is_primary")]
    for m in blocked:
        m["priority_rank"] = 99
        m["reason"] = f"BLOCKED: {m['disqualifiers_hit']}"

    primary_match = next((m for m in matches if m["is_primary"]), None)
    all_ranked = ([primary_match] if primary_match else []) + secondaries + blocked

    return {
        "symbol": symbol,
        "primary_strategy_id": proposal_strategy,
        "secondary_strategy_ids": [m["strategy_id"] for m in secondaries[:5]],
        "setup_stack": all_ranked,
        "match_count": len(all_ranked),
    }


def store_setup_matches(conn, symbol, proposal_id, run_label, matches, config_hashes):
    """Store all setup matches in strategy_setup_matches."""
    cur = conn.cursor()
    for m in matches:
        cur.execute("""
            INSERT INTO strategy_setup_matches
                (symbol, proposal_id, run_label, strategy_id, setup_class,
                 match_score, match_status, criteria_met, criteria_failed,
                 disqualifiers_hit, missing_data, is_primary, priority_rank,
                 reason, config_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [
            symbol, proposal_id, run_label, m["strategy_id"],
            m.get("setup_class"),
            m["match_score"], m["match_status"],
            json.dumps(m["criteria_met"]),
            json.dumps(m["criteria_failed"]),
            json.dumps(m["disqualifiers_hit"]),
            json.dumps(m["missing_data"]),
            m.get("is_primary", False),
            m.get("priority_rank"),
            m.get("reason"),
            config_hashes.get(m["strategy_id"]),
        ])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Multi-setup router")
    parser.add_argument("--symbol", type=str)
    parser.add_argument("--pending-proposals", action="store_true")
    parser.add_argument("--today-signals", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configs = load_all_strategy_configs()
    config_hashes = {sid: c["_config_hash"] for sid, c in configs.items()}
    conn = get_conn()

    try:
        if args.symbol:
            # Build signal from latest scan
            cur = conn.cursor()
            cur.execute("""
                SELECT symbol, price, score, decision, rvol, float_m, gap_pct,
                       catalyst, catalyst_verified, sector, change_pct
                FROM trade_ai_scans WHERE symbol=%s
                ORDER BY scanned_at DESC LIMIT 1
            """, [args.symbol.upper()])
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            signal = dict(zip(cols, row)) if row else {"symbol": args.symbol.upper()}

            result = route_symbol(args.symbol.upper(), signal, configs)
            print(json.dumps(result, indent=2, default=str))

        elif args.pending_proposals:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, symbol, strategy_id, proposed_entry, proposed_stop,
                       proposed_target1, rvol, float_m, gap_pct, catalyst, catalyst_verified
                FROM paper_trade_proposals WHERE status='PENDING'
            """)
            cols = [d[0] for d in cur.description]
            proposals = [dict(zip(cols, r)) for r in cur.fetchall()]

            results = []
            for p in proposals:
                signal = {**p, "price": p.get("proposed_entry")}
                result = route_symbol(p["symbol"], signal, configs)
                result["proposal_id"] = p["id"]

                if args.apply:
                    store_setup_matches(conn, p["symbol"], p["id"], None,
                                       result["setup_stack"], config_hashes)
                    # Update proposal with setup stack
                    cur.execute("""
                        UPDATE paper_trade_proposals
                        SET primary_strategy_id=%s, secondary_strategy_ids=%s,
                            setup_stack=%s, strategy_config_hash=%s
                        WHERE id=%s
                    """, [
                        result["primary_strategy_id"],
                        json.dumps(result["secondary_strategy_ids"]),
                        json.dumps(result["setup_stack"], default=str),
                        config_hashes.get(result["primary_strategy_id"]),
                        p["id"],
                    ])
                    conn.commit()

                log.info(f"  {p['symbol']} (#{p['id']}): primary={result['primary_strategy_id']} "
                         f"secondaries={result['secondary_strategy_ids']} matches={result['match_count']}")
                results.append(result)

            print(json.dumps({"routed": len(results), "results": results}, indent=2, default=str))

        elif args.today_signals:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT ON (symbol) symbol, strategy_id, signal_score,
                       rvol, float_m, gap_pct, catalyst, catalyst_verified,
                       scan_run_label
                FROM strategy_signals
                WHERE created_at > CURRENT_DATE
                ORDER BY symbol, created_at DESC
            """)
            cols = [d[0] for d in cur.description]
            signals = [dict(zip(cols, r)) for r in cur.fetchall()]

            results = []
            for s in signals:
                signal = {**s, "price": 0}
                result = route_symbol(s["symbol"], signal, configs)
                log.info(f"  {s['symbol']}: primary={result['primary_strategy_id']} "
                         f"secondaries={result['secondary_strategy_ids']}")
                results.append(result)

            print(json.dumps({"routed": len(results), "results": results}, indent=2, default=str))

        else:
            print("Usage: --symbol TICK | --pending-proposals | --today-signals")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
