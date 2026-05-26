#!/usr/bin/env python3
"""proposal_route_audit_integration.py — Shared route audit helper for proposal creation.

Call after proposal INSERT to store strategy evaluation evidence.
Does NOT change proposal strategy_id. Does NOT create trades/orders.

Usage:
    from proposal_route_audit_integration import ensure_route_audit_for_proposal
"""
import json, logging

log = logging.getLogger("route_audit_integration")


def ensure_route_audit_for_proposal(
    conn,
    proposal_id: int,
    symbol: str,
    original_strategy_id: str,
    candidate_payload: dict,
    source: str = "pipeline",
    dry_run: bool = False,
) -> dict:
    """Generate and store route audit evidence for a proposal.

    Args:
        conn: DB connection (must be open, caller manages commit)
        proposal_id: ID of the just-created proposal
        symbol: ticker symbol
        original_strategy_id: the strategy_id already assigned to proposal
        candidate_payload: dict with price, rvol, float_m, gap_pct, etc.
        source: label for audit trail (auto_proposal_generator, incubator_promoter, etc.)
        dry_run: if True, evaluate but do not write to DB

    Returns:
        dict with route_audit_created, evaluated count, top match, mismatch, blockers
    """
    result = {
        "route_audit_created": False,
        "evaluated_strategy_count": 0,
        "passed_strategy_count": 0,
        "top_match_strategy_id": None,
        "original_strategy_id": original_strategy_id,
        "mismatch": False,
        "invalid_strategy_id": False,
        "blockers": [],
        "warnings": [],
    }

    # Load configs
    try:
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
    except Exception as e:
        result["blockers"].append("route_audit_failed: could not load strategy configs")
        log.warning(f"[route_audit] Config load failed for {symbol}: {e}")
        return result

    # Check if original strategy_id is valid
    valid_ids = set(configs.keys())
    if original_strategy_id and original_strategy_id not in valid_ids:
        result["invalid_strategy_id"] = True
        result["blockers"].append(f"invalid_strategy_id: '{original_strategy_id}' not in YAML configs")

    # Check if route audit already exists
    if conn and not dry_run:
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM strategy_setup_matches WHERE proposal_id = %s", [proposal_id])
            existing = cur.fetchone()[0]
            if existing > 0:
                result["route_audit_created"] = True
                result["warnings"].append("route_audit_already_exists")
                return result
        except Exception:
            pass

    # Route symbol
    try:
        from multi_setup_router import route_symbol
        route_result = route_symbol(symbol, candidate_payload, configs)
    except Exception as e:
        result["blockers"].append(f"route_audit_failed: router error: {e}")
        log.warning(f"[route_audit] Router failed for {symbol}: {e}")
        return result

    matches = route_result.get("setup_stack", [])
    top_match = route_result.get("primary_strategy_id")

    result["evaluated_strategy_count"] = len(matches)
    result["passed_strategy_count"] = len([m for m in matches if (m.get("match_score", 0) or 0) >= 40])
    result["top_match_strategy_id"] = top_match
    result["mismatch"] = top_match is not None and top_match != original_strategy_id

    if result["mismatch"]:
        result["warnings"].append(f"mismatch: router top={top_match} vs original={original_strategy_id}")

    # Store
    if not dry_run and conn and matches:
        try:
            from multi_setup_router import store_setup_matches
            config_hashes = {sid: cfg.get("_config_hash", "") for sid, cfg in configs.items()}
            run_label = f"SP-2C-{source}"
            store_setup_matches(conn, symbol, proposal_id, run_label, matches, config_hashes)
            result["route_audit_created"] = True
            log.info(f"[route_audit] {symbol} #{proposal_id}: {len(matches)} strategies evaluated, top={top_match}, orig={original_strategy_id}")
        except Exception as e:
            result["blockers"].append(f"route_audit_store_failed: {e}")
            log.warning(f"[route_audit] Store failed for {symbol} #{proposal_id}: {e}")
    elif dry_run:
        result["route_audit_created"] = False
        result["warnings"].append("dry_run: no DB write")

    return result
