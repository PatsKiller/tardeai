#!/usr/bin/env python3
"""auto_proposal_generator.py — Stage 18f: Auto-create PENDING paper proposals from planned strategy signals.

Creates PENDING paper proposals from current-day planned strategy signals.
Does NOT approve trades or submit orders. Populates the review queue.

Usage:
    .venv/bin/python scripts/auto_proposal_generator.py --run-label 1000 --dry-run
    .venv/bin/python scripts/auto_proposal_generator.py --run-label 1000 --apply
    .venv/bin/python scripts/auto_proposal_generator.py --today --apply --limit 10
    .venv/bin/python scripts/auto_proposal_generator.py --symbol EVC --dry-run
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("auto_proposal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

DEFAULT_MAX_DOLLAR_SIZE = 2000
DEFAULT_MAX_DOLLAR_RISK = 150
DEFAULT_RISK_PER_TRADE = 150
STRATEGY_PRIORITY = ["momentum_scalp", "gap_and_go", "swing_breakout", "earnings_catalyst", "sector_rotation"]


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def _get_available_cols(conn, table: str) -> set:
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table])
    return {r[0] for r in cur.fetchall()}


def _load_strategy_config(strategy_id: str) -> dict:
    import yaml
    path = PROJECT_ROOT / "config" / "strategies" / f"{strategy_id}.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _load_shared_risk_rules() -> dict:
    import yaml
    path = PROJECT_ROOT / "config" / "strategies" / "shared_risk_rules.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def get_eligible_signals(conn, run_label=None, symbol=None, min_score=40) -> list:
    """Get current-day planned strategy signals eligible for auto-proposal."""
    cur = conn.cursor()
    sql = """
        SELECT id, symbol, strategy_id, setup_description, signal_grade, signal_score,
               price, rvol, float_m, gap_pct,
               catalyst, catalyst_verified, intel_readiness,
               entry_high, entry_low, stop_loss, target_1, target_2,
               shares, dollar_risk, risk_reward,
               sector, source_table, scan_run_label, discovery_source,
               fired_at
        FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
        AND entry_high IS NOT NULL AND stop_loss IS NOT NULL
        AND target_1 IS NOT NULL AND shares IS NOT NULL
        AND (signal_grade IN ('A','A+') OR signal_score >= %s)
        AND status IN ('active','ACTIVE')
    """
    params = [min_score]
    if run_label:
        sql += " AND (scan_run_label = %s OR scan_run_label IS NULL)"
        params.append(run_label)
    if symbol:
        sql += " AND symbol = %s"
        params.append(symbol)
    sql += " ORDER BY signal_score DESC NULLS LAST"
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def check_duplicate(conn, signal_id: int, symbol: str, strategy_id: str) -> dict | None:
    """Check for existing active proposal. Returns proposal dict if duplicate."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, status FROM paper_trade_proposals
        WHERE (
            source_signal_id = %s
            OR (
                symbol = %s AND strategy_id = %s
                AND created_at::date = CURRENT_DATE
                AND status IN ('PENDING','APPROVED','MODIFIED','BROKER_SUBMITTED')
            )
        )
        AND status IN ('PENDING','APPROVED','MODIFIED','BROKER_SUBMITTED')
        LIMIT 1
    """, [signal_id, symbol, strategy_id])
    row = cur.fetchone()
    return {"id": row[0], "status": row[1]} if row else None


def check_open_paper_trade(conn, symbol: str, strategy_id: str) -> dict | None:
    """Check for existing open paper trade."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, status FROM paper_trades
        WHERE symbol = %s
        AND COALESCE(strategy_id, '') = COALESCE(%s, '')
        AND status IN ('open','pending','submitted')
        LIMIT 1
    """, [symbol, strategy_id])
    row = cur.fetchone()
    return {"id": row[0], "status": row[1]} if row else None


def normalize_size(signal: dict, strategy_cfg: dict, shared_rules: dict) -> dict:
    """Normalize proposal sizing. Returns sizing dict."""
    entry = float(signal.get("entry_high") or signal.get("price") or 0)
    stop = float(signal.get("stop_loss") or 0)
    original_shares = int(signal.get("shares") or 0)

    if entry <= 0 or stop <= 0 or original_shares <= 0:
        return {"valid": False, "reason": "MISSING_PLAN_DATA"}

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return {"valid": False, "reason": "ZERO_RISK_PER_SHARE"}

    # Get caps from strategy config and shared rules
    live_rules = strategy_cfg.get("live_trade_rules", {})
    max_dollar_size = float(live_rules.get("max_position_size", DEFAULT_MAX_DOLLAR_SIZE))
    max_dollar_risk = float(live_rules.get("max_dollar_risk", DEFAULT_MAX_DOLLAR_RISK))
    risk_per_trade = float(shared_rules.get("risk_limits", {}).get("default_risk_per_trade", DEFAULT_RISK_PER_TRADE))

    # Use the more conservative risk cap
    max_dollar_risk = min(max_dollar_risk, risk_per_trade)

    original_dollar_size = round(original_shares * entry, 2)
    original_dollar_risk = round(original_shares * risk_per_share, 2)

    # Calculate max shares by each constraint
    max_shares_by_size = int(max_dollar_size / entry) if entry > 0 else 0
    max_shares_by_risk = int(max_dollar_risk / risk_per_share) if risk_per_share > 0 else 0
    adjusted_shares = min(original_shares, max_shares_by_size, max_shares_by_risk)
    adjusted_shares = max(adjusted_shares, 0)

    if adjusted_shares < 1:
        return {
            "valid": False,
            "reason": "SIZE_TOO_SMALL",
            "original_shares": original_shares,
            "max_shares_by_size": max_shares_by_size,
            "max_shares_by_risk": max_shares_by_risk,
        }

    sizing_adjusted = adjusted_shares != original_shares
    sizing_reason = None
    if sizing_adjusted:
        reasons = []
        if adjusted_shares < original_shares and max_shares_by_size < original_shares:
            reasons.append(f"dollar_size {original_dollar_size:.0f}>{max_dollar_size:.0f}")
        if adjusted_shares < original_shares and max_shares_by_risk < original_shares:
            reasons.append(f"dollar_risk {original_dollar_risk:.0f}>{max_dollar_risk:.0f}")
        sizing_reason = "; ".join(reasons) if reasons else "reduced_to_fit_limits"

    adjusted_dollar_size = round(adjusted_shares * entry, 2)
    adjusted_dollar_risk = round(adjusted_shares * risk_per_share, 2)
    rr = round((float(signal.get("target_1") or 0) - entry) / risk_per_share, 2) if risk_per_share > 0 else 0

    return {
        "valid": True,
        "original_shares": original_shares,
        "adjusted_shares": adjusted_shares,
        "original_dollar_size": original_dollar_size,
        "adjusted_dollar_size": adjusted_dollar_size,
        "original_dollar_risk": original_dollar_risk,
        "adjusted_dollar_risk": adjusted_dollar_risk,
        "sizing_adjusted": sizing_adjusted,
        "sizing_reason": sizing_reason,
        "stop_pct": round(risk_per_share / entry, 4) if entry > 0 else 0,
        "rr": rr,
    }


def check_risk_gate(conn, symbol: str, strategy_id: str, plan: dict) -> dict:
    """Run risk gate precheck. Returns {approved, result, codes}."""
    try:
        from risk_gate import RiskGate
        gate = RiskGate(conn)
        decision = gate.check(
            symbol=symbol,
            strategy_id=strategy_id,
            trade_plan=plan,
            account="TOS_PAPER",
            mode="paper",
            action_context="paper_proposal",
        )
        return {
            "approved": decision.approved,
            "result": decision.result,
            "codes": decision.reason_codes,
        }
    except Exception as e:
        log.warning(f"  {symbol}: risk gate error — {e}")
        return {"approved": False, "result": "RISK_GATE_ERROR", "codes": [str(e)]}


def check_quality(signal: dict, sizing: dict) -> tuple:
    """Quality filter. Returns (pass, reason_codes)."""
    reasons = []
    score = int(signal.get("signal_score") or 0)
    rr = sizing.get("rr", 0)
    entry = float(signal.get("entry_high") or 0)
    stop = float(signal.get("stop_loss") or 0)
    target = float(signal.get("target_1") or 0)

    if score < 40:
        reasons.append("LOW_SCORE")
    if rr < 1.2:
        reasons.append("BAD_RR")
    if entry <= 0 or stop <= 0 or target <= 0:
        reasons.append("NO_PLAN")
    if stop >= entry:
        reasons.append("PRICE_ORDER_INVALID")
    if target <= entry:
        reasons.append("TARGET_BELOW_ENTRY")

    # Source cap: reject social-only or youtube-only
    source = (signal.get("discovery_source") or "").lower()
    if source in ("social", "stocktwits", "reddit") and not signal.get("catalyst_verified"):
        reasons.append("SOURCE_CAP_SOCIAL_ONLY")

    return len(reasons) == 0, reasons


def create_auto_proposal(conn, signal: dict, sizing: dict, risk_gate: dict,
                         auto_run_id: int, available_cols: set,
                         auto_context: dict = None) -> int | None:
    """Insert a PENDING paper proposal. Returns proposal_id."""
    entry = float(signal.get("entry_high") or 0)
    stop = float(signal.get("stop_loss") or 0)
    target = float(signal.get("target_1") or 0)
    target2 = float(signal.get("target_2") or 0) if signal.get("target_2") else None
    shares = sizing["adjusted_shares"]
    expires = datetime.now(timezone.utc) + timedelta(hours=4)

    data = {
        "symbol": signal["symbol"],
        "strategy_id": signal.get("strategy_id", "momentum_scalp"),
        "setup_type": signal.get("setup_description"),
        "signal_score": signal.get("signal_score"),
        "signal_grade": signal.get("signal_grade"),
        "signal_decision": "GO",
        "source_signal_id": signal["id"],
        "rvol": signal.get("rvol"),
        "float_m": signal.get("float_m"),
        "gap_pct": signal.get("gap_pct"),
        "catalyst": (signal.get("catalyst") or "")[:200],
        "catalyst_verified": signal.get("catalyst_verified", False),
        "intel_readiness": signal.get("intel_readiness"),
        "proposed_account": "TOS_PAPER",
        "proposed_entry": entry,
        "proposed_stop": stop,
        "proposed_target1": target,
        "proposed_target2": target2,
        "proposed_shares": shares,
        "proposed_dollar_size": sizing["adjusted_dollar_size"],
        "proposed_dollar_risk": sizing["adjusted_dollar_risk"],
        "proposed_stop_pct": sizing.get("stop_pct", 0),
        "proposed_rr": sizing.get("rr", 0),
        "risk_gate_result": risk_gate.get("result", "UNKNOWN"),
        "risk_gate_codes": json.dumps(risk_gate.get("codes", [])),
        "proposed_by": "auto_proposal_generator",
        "status": "PENDING",
        "expires_at": expires,
        "auto_created": True,
        "auto_proposal_run_id": auto_run_id,
        "sizing_adjusted": sizing.get("sizing_adjusted", False),
        "original_shares": sizing.get("original_shares"),
        "adjusted_shares": sizing.get("adjusted_shares"),
        "sizing_reason": sizing.get("sizing_reason"),
        "sector": signal.get("sector"),
        "discovery_source": signal.get("discovery_source"),
        "setup_description": signal.get("setup_description"),
        "source_run_label": signal.get("scan_run_label"),
        "auto_execution_label": auto_context.get("execution_label", "manual") if auto_context else "manual",
    }

    # Filter to existing columns
    insert_data = {k: v for k, v in data.items() if k in available_cols and v is not None}
    cols_str = ", ".join(insert_data.keys())
    placeholders = ", ".join(["%s"] * len(insert_data))

    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO paper_trade_proposals ({cols_str}) VALUES ({placeholders}) RETURNING id",
        list(insert_data.values())
    )
    return cur.fetchone()[0]


def record_decision(conn, run_label: str, signal: dict, decision: str,
                     reason_codes: list, proposal_id: int | None,
                     sizing: dict | None, risk_gate: dict | None):
    """Record auto-proposal decision for diagnostics."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO auto_proposal_decisions
            (run_label, source_signal_id, symbol, strategy_id, decision, reason_codes,
             proposal_id, original_shares, adjusted_shares,
             original_dollar_size, adjusted_dollar_size,
             original_dollar_risk, adjusted_dollar_risk,
             risk_gate_result, risk_gate_codes, quality_pass, source_cap_pass)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, [
        run_label, signal.get("id"), signal["symbol"], signal.get("strategy_id"),
        decision, json.dumps(reason_codes),
        proposal_id,
        sizing.get("original_shares") if sizing else None,
        sizing.get("adjusted_shares") if sizing else None,
        sizing.get("original_dollar_size") if sizing else None,
        sizing.get("adjusted_dollar_size") if sizing else None,
        sizing.get("original_dollar_risk") if sizing else None,
        sizing.get("adjusted_dollar_risk") if sizing else None,
        risk_gate.get("result") if risk_gate else None,
        json.dumps(risk_gate.get("codes", [])) if risk_gate else None,
        "SOURCE_CAP" not in " ".join(reason_codes) if reason_codes else True,
        "SOURCE_CAP" not in " ".join(reason_codes) if reason_codes else True,
    ])


def run_auto_proposals(conn, run_label: str = None, symbol: str = None,
                       min_score: int = 40, limit: int = 20,
                       dry_run: bool = True,
                       execution_label: str = "manual") -> dict:
    """Main auto-proposal generation. Returns audit summary."""
    shared_rules = _load_shared_risk_rules()
    proposal_cols = _get_available_cols(conn, "paper_trade_proposals")
    cur = conn.cursor()

    # Record run start
    auto_run_id = None
    if not dry_run:
        cur.execute("""
            INSERT INTO auto_proposal_runs (run_label, run_date, status, started_at,
                                            execution_label, source_run_label)
            VALUES (%s, CURRENT_DATE, 'RUNNING', NOW(), %s, %s) RETURNING id
        """, [run_label or "manual", execution_label, run_label])
        auto_run_id = cur.fetchone()[0]
        conn.commit()

    signals = get_eligible_signals(conn, run_label=run_label, symbol=symbol, min_score=min_score)
    log.info(f"Found {len(signals)} eligible signals for auto-proposal")

    # Deduplicate: keep best signal per symbol (highest score, best strategy priority)
    best_by_symbol = {}
    for sig in signals:
        sym = sig["symbol"]
        sid = sig.get("strategy_id", "")
        priority = STRATEGY_PRIORITY.index(sid) if sid in STRATEGY_PRIORITY else 99
        existing = best_by_symbol.get(sym)
        if not existing:
            best_by_symbol[sym] = (sig, priority)
        else:
            _, ex_priority = existing
            if priority < ex_priority or (priority == ex_priority and (sig.get("signal_score") or 0) > (existing[0].get("signal_score") or 0)):
                best_by_symbol[sym] = (sig, priority)

    deduped = [sig for sig, _ in best_by_symbol.values()]
    deduped.sort(key=lambda s: -(s.get("signal_score") or 0))
    if limit:
        deduped = deduped[:limit]

    stats = {
        "signals_checked": len(deduped),
        "proposals_created": 0,
        "proposals_skipped": 0,
        "duplicates_skipped": 0,
        "risk_rejected": 0,
        "quality_rejected": 0,
        "source_cap_rejected": 0,
        "sizing_adjusted": 0,
        "errors": 0,
        "details": [],
    }

    for sig in deduped:
        sym = sig["symbol"]
        sid = sig.get("strategy_id", "momentum_scalp")
        sig_id = sig["id"]

        try:
            # 1. Duplicate check
            dup = check_duplicate(conn, sig_id, sym, sid)
            if dup:
                stats["duplicates_skipped"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_DUPLICATE (proposal #{dup['id']} {dup['status']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_DUPLICATE", [reason], None, None, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_DUPLICATE", "reason": reason})
                continue

            # 2. Open trade check
            open_trade = check_open_paper_trade(conn, sym, sid)
            if open_trade:
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_OPEN_TRADE (trade #{open_trade['id']} {open_trade['status']})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_OPEN_TRADE", [reason], None, None, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_OPEN_TRADE", "reason": reason})
                continue

            # 3. Normalize sizing
            strategy_cfg = _load_strategy_config(sid)
            sizing = normalize_size(sig, strategy_cfg, shared_rules)
            if not sizing.get("valid"):
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_SIZE ({sizing.get('reason')})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_SIZE", [sizing.get("reason", "")], None, sizing, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_SIZE", "reason": reason})
                continue

            if sizing.get("sizing_adjusted"):
                stats["sizing_adjusted"] += 1
                log.info(f"  {sym}: sizing adjusted {sizing['original_shares']}→{sizing['adjusted_shares']} shares ({sizing.get('sizing_reason')})")

            # 4. Quality check
            q_pass, q_reasons = check_quality(sig, sizing)
            if not q_pass:
                source_cap = any("SOURCE_CAP" in r for r in q_reasons)
                if source_cap:
                    stats["source_cap_rejected"] += 1
                else:
                    stats["quality_rejected"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_QUALITY ({', '.join(q_reasons)})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_QUALITY", q_reasons, None, sizing, None)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_QUALITY", "reason": reason})
                continue

            # 5. Risk gate precheck
            plan_for_gate = {
                "stop_loss": float(sig.get("stop_loss") or 0),
                "dollar_size": sizing["adjusted_dollar_size"],
                "dollar_risk": sizing["adjusted_dollar_risk"],
            }
            rg = check_risk_gate(conn, sym, sid, plan_for_gate)
            if not rg["approved"]:
                stats["risk_rejected"] += 1
                stats["proposals_skipped"] += 1
                reason = f"SKIPPED_RISK_GATE ({rg['result']}: {', '.join(rg.get('codes', []))})"
                log.info(f"  {sym}: {reason}")
                if not dry_run:
                    record_decision(conn, run_label, sig, "SKIPPED_RISK_GATE", rg.get("codes", []), None, sizing, rg)
                stats["details"].append({"symbol": sym, "decision": "SKIPPED_RISK_GATE", "reason": reason})
                continue

            # 6. Create proposal
            if dry_run:
                log.info(f"  {sym}: WOULD CREATE proposal — {sid} score={sig.get('signal_score')} "
                         f"entry=${float(sig.get('entry_high') or 0):.2f} stop=${float(sig.get('stop_loss') or 0):.2f} "
                         f"shares={sizing['adjusted_shares']} risk=${sizing['adjusted_dollar_risk']:.0f} rr={sizing['rr']:.1f}")
                stats["proposals_created"] += 1
                stats["details"].append({"symbol": sym, "decision": "WOULD_CREATE", "strategy_id": sid,
                                         "shares": sizing["adjusted_shares"], "dollar_risk": sizing["adjusted_dollar_risk"]})
            else:
                proposal_id = create_auto_proposal(conn, sig, sizing, rg, auto_run_id, proposal_cols,
                                                   auto_context={"execution_label": execution_label})
                conn.commit()
                record_decision(conn, run_label, sig, "CREATED", [], proposal_id, sizing, rg)
                conn.commit()
                stats["proposals_created"] += 1
                log.info(f"  {sym}: CREATED proposal #{proposal_id} — {sid} score={sig.get('signal_score')} "
                         f"shares={sizing['adjusted_shares']} risk=${sizing['adjusted_dollar_risk']:.0f}")
                stats["details"].append({"symbol": sym, "decision": "CREATED", "proposal_id": proposal_id,
                                         "strategy_id": sid, "shares": sizing["adjusted_shares"]})

        except Exception as e:
            stats["errors"] += 1
            stats["proposals_skipped"] += 1
            log.error(f"  {sym}: ERROR — {e}")
            stats["details"].append({"symbol": sym, "decision": "ERROR", "error": str(e)})
            if not dry_run:
                try:
                    record_decision(conn, run_label, sig, "ERROR", [str(e)], None, None, None)
                    conn.commit()
                except Exception:
                    conn.rollback()

    # Finalize run record
    if not dry_run and auto_run_id:
        reason_summary = {}
        for d in stats["details"]:
            dec = d.get("decision", "UNKNOWN")
            reason_summary[dec] = reason_summary.get(dec, 0) + 1
        cur.execute("""
            UPDATE auto_proposal_runs
            SET status = 'COMPLETED',
                signals_checked = %s, proposals_created = %s, proposals_skipped = %s,
                duplicates_skipped = %s, risk_rejected = %s, quality_rejected = %s,
                source_cap_rejected = %s, sizing_adjusted = %s,
                reason_summary = %s, finished_at = NOW()
            WHERE id = %s
        """, [
            stats["signals_checked"], stats["proposals_created"], stats["proposals_skipped"],
            stats["duplicates_skipped"], stats["risk_rejected"], stats["quality_rejected"],
            stats["source_cap_rejected"], stats["sizing_adjusted"],
            json.dumps(reason_summary), auto_run_id,
        ])
        conn.commit()

    log.info(f"\nAuto-proposal summary: checked={stats['signals_checked']} "
             f"created={stats['proposals_created']} skipped={stats['proposals_skipped']} "
             f"(dup={stats['duplicates_skipped']} risk={stats['risk_rejected']} "
             f"quality={stats['quality_rejected']} source_cap={stats['source_cap_rejected']} "
             f"sizing_adj={stats['sizing_adjusted']})")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Auto-generate PENDING paper proposals from strategy signals")
    parser.add_argument("--run-label", type=str, help="Filter by run label")
    parser.add_argument("--today", action="store_true", help="Process all today's signals")
    parser.add_argument("--symbol", type=str, help="Process single symbol")
    parser.add_argument("--apply", action="store_true", help="Actually create proposals (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    parser.add_argument("--limit", type=int, default=20, help="Max proposals to create")
    parser.add_argument("--min-score", type=int, default=40, help="Minimum signal score")
    args = parser.parse_args()

    if not args.run_label and not args.today and not args.symbol:
        print("Usage: --run-label 1000 or --today or --symbol MNKD")
        print("       Add --apply to actually create proposals")
        sys.exit(1)

    dry_run = not args.apply
    conn = get_conn()
    try:
        result = run_auto_proposals(
            conn,
            run_label=args.run_label,
            symbol=args.symbol,
            min_score=args.min_score,
            limit=args.limit,
            dry_run=dry_run,
        )
        print(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=2, default=str))
        if result.get("details"):
            print("\nDetails:")
            for d in result["details"]:
                print(f"  {d.get('symbol','?')}: {d.get('decision','?')} {d.get('reason','')}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
