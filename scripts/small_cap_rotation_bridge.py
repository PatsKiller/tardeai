#!/usr/bin/env python3
"""small_cap_rotation_bridge.py — Screen trend/screener hits into watchlist + proposals when criteria met.

When detect_small_cap_rotation() signals small_cap_outperform:
  1. Watchlist tier: GO/WAIT/A+ scans, score≥35, liquidity gates → watchlist + qualified_intel
  2. Proposal tier: GO/A+ score≥40 → strategy_signals → backfill plans → paper proposals (automatic)

Usage:
    .venv/bin/python scripts/small_cap_rotation_bridge.py --today
    .venv/bin/python scripts/small_cap_rotation_bridge.py --force --dry-run
    .venv/bin/python scripts/small_cap_rotation_bridge.py --run-label 1000 --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("small_cap_rotation_bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Screeners with small/mid-cap bias (assets/screeners.yaml + finviz_screeners catalog)
SMALL_CAP_SCREENERS = (
    "prime_setups",
    "watchlist_setups",
    "speculative_growth_breakouts",
    "pm_breakout_confirmation",
    "pm_volume_continuation",
    "swing_momentum",
    "swing_breakout_targeted",
    "speculative_catalyst",
    "tactical_momentum",
)

_SCREENER_MATCH_SQL = """
    AND (
        screener_label = ANY(%s)
        OR source_detail = ANY(%s)
        OR EXISTS (
            SELECT 1 FROM unnest(%s::text[]) AS sid
            WHERE COALESCE(source_detail, '') LIKE '%%' || sid || '%%'
               OR COALESCE(screener_label, '') = sid
        )
    )
"""

# Gates aligned with config/strategies/swing_breakout.yaml screen_filters
MIN_WATCHLIST_SCORE = 35
MIN_PROPOSAL_SCORE = 40
MIN_PRICE = 5.0
MAX_PRICE = 150.0
MIN_RVOL = 1.5
MAX_FLOAT_M = 500.0
LOOKBACK_DAYS = 7
LOOKBACK_DAYS_PROPOSAL = 2
MAX_QUOTE_AGE_MINUTES = 15
MAX_TREND_PROPOSAL_RISK = 200
MAX_WATCHLIST = 25
MAX_PROPOSAL_SYMBOLS = 15


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


def _screener_name(scan: dict) -> str:
    return (scan.get("screener_label") or scan.get("source_detail") or "screener").split("|")[0]


def passes_proposal_gates(scan: dict, *, conn=None) -> tuple[bool, list[str]]:
    """Stricter gates for proposal-tier promotion (fresh quote, verified catalyst, analyst)."""
    reasons = []
    sym = (scan.get("symbol") or "").upper()

    if not scan.get("catalyst_verified"):
        reasons.append("catalyst_not_verified")

    catalyst = scan.get("catalyst") or ""
    try:
        from analyst_coverage import is_junk_catalyst
        if is_junk_catalyst(catalyst):
            reasons.append("junk_listicle_catalyst")
    except Exception:
        pass

    try:
        from market_quote_provider import check_fresh_quote
        fq = check_fresh_quote(sym, max_age_minutes=MAX_QUOTE_AGE_MINUTES)
        if not fq.get("ok"):
            reasons.append(f"quote_gate: {fq.get('reason')}")
    except Exception as exc:
        reasons.append(f"quote_gate_error: {exc}")

    if conn is not None:
        try:
            from analyst_coverage import check_analyst_gate
            ok, reason, _ = check_analyst_gate(conn, sym, fetch_if_missing=True)
            if not ok:
                reasons.append(f"analyst_gate: {reason}")
        except Exception as exc:
            reasons.append(f"analyst_gate_error: {exc}")

    return len(reasons) == 0, reasons


def passes_liquidity_gates(scan: dict) -> tuple[bool, list[str]]:
    """Price, RVOL, and float gates for small-cap rotation candidates."""
    reasons = []
    price = float(scan.get("price") or 0)
    rvol = float(scan.get("rvol") or 0)
    float_m = float(scan.get("float_m") or 0)

    if price < MIN_PRICE:
        reasons.append(f"price {price:.2f} < {MIN_PRICE}")
    elif price > MAX_PRICE:
        reasons.append(f"price {price:.2f} > {MAX_PRICE}")

    if rvol < MIN_RVOL:
        reasons.append(f"rvol {rvol:.1f} < {MIN_RVOL}")

    if float_m > MAX_FLOAT_M:
        reasons.append(f"float {float_m:.0f}M > {MAX_FLOAT_M}M")

    return len(reasons) == 0, reasons


def fetch_rotation_candidates(
    conn,
    *,
    lookback_days: int = LOOKBACK_DAYS,
    run_label: Optional[str] = None,
    min_score: int = MIN_WATCHLIST_SCORE,
) -> List[dict]:
    """Recent small-cap screener hits from trade_ai_scans."""
    cur = conn.cursor()
    screeners = list(SMALL_CAP_SCREENERS)
    sql = f"""
        SELECT DISTINCT ON (symbol)
            id, symbol, score, grade, decision, rvol, float_m, gap_pct, price,
            catalyst, catalyst_verified, sector, screener_label, source_detail,
            run_label, scanned_at, intelligence_readiness, change_pct
        FROM trade_ai_scans
        WHERE scanned_at > NOW() - (%s || ' days')::interval
          AND decision IN ('GO', 'WAIT', 'A+')
          AND COALESCE(score, 0) >= %s
          {_SCREENER_MATCH_SQL}
    """
    params: list = [str(lookback_days), min_score, screeners, screeners, screeners]
    if run_label:
        sql += " AND run_label = %s"
        params.append(run_label)
    sql += " ORDER BY symbol, score DESC, scanned_at DESC"
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_broad_trend_candidates(
    conn,
    *,
    lookback_days: int = LOOKBACK_DAYS,
    min_score: int = MIN_PROPOSAL_SCORE,
) -> List[dict]:
    """Any GO/A+ screener hit meeting proposal score — catches new trends outside named screeners."""
    cur = conn.cursor()
    sql = """
        SELECT DISTINCT ON (symbol)
            id, symbol, score, grade, decision, rvol, float_m, gap_pct, price,
            catalyst, catalyst_verified, sector, screener_label, source_detail,
            run_label, scanned_at, intelligence_readiness, change_pct
        FROM trade_ai_scans
        WHERE scanned_at > NOW() - (%s || ' days')::interval
          AND decision IN ('GO', 'A+')
          AND COALESCE(score, 0) >= %s
          AND COALESCE(source, 'screener') = 'screener'
        ORDER BY symbol, score DESC, scanned_at DESC
    """
    cur.execute(sql, [str(lookback_days), min_score])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _merge_candidates(primary: List[dict], extra: List[dict]) -> List[dict]:
    seen = {(c.get("symbol") or "").upper() for c in primary}
    out = list(primary)
    for row in extra:
        sym = (row.get("symbol") or "").upper()
        if sym and sym not in seen:
            out.append(row)
            seen.add(sym)
    return out


def _upsert_watchlist(conn, scan: dict, rotation: dict, *, dry_run: bool) -> bool:
    symbol = (scan.get("symbol") or "").upper()
    if not symbol:
        return False

    detail = {
        "rotation_signal": rotation.get("signal"),
        "rs_1d": rotation.get("rs_1d"),
        "rs_5d": rotation.get("rs_5d"),
        "rs_20d": rotation.get("rs_20d"),
        "screener": _screener_name(scan),
        "score": scan.get("score"),
        "decision": scan.get("decision"),
        "grade": scan.get("grade"),
        "run_label": scan.get("run_label"),
        "scanned_at": str(scan.get("scanned_at") or ""),
    }
    provenance = (
        f"Rotation bridge: {_screener_name(scan)} {scan.get('decision')} "
        f"score={scan.get('score')} — {rotation.get('explain', 'IWM leading SPY')}"
    )[:500]
    score = int(scan.get("score") or 0)
    detail["thesis"] = provenance[:240]

    if dry_run:
        log.info("  [dry-run] watchlist %s score=%s %s", symbol, score, scan.get("decision"))
        return True

    cur = conn.cursor()
    payload = json.dumps(detail, default=str)
    cur.execute(
        """
        INSERT INTO watchlist_items
            (symbol, source, bucket, status, origin_system, origin_detail,
             score, provenance_reason, source_payload, price, rvol, float_m,
             first_seen_at, last_seen_at, updated_at)
        VALUES (%s, 'small_cap_rotation', 'rotation', 'active', 'small_cap_rotation',
                %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s, NOW(), NOW(), NOW())
        ON CONFLICT (symbol, source, COALESCE(bucket, '__none__'))
        DO UPDATE SET
            status = CASE WHEN watchlist_items.status = 'removed' THEN 'active' ELSE watchlist_items.status END,
            origin_detail = EXCLUDED.origin_detail,
            score = GREATEST(COALESCE(watchlist_items.score, 0), EXCLUDED.score),
            provenance_reason = EXCLUDED.provenance_reason,
            source_payload = EXCLUDED.source_payload,
            price = COALESCE(EXCLUDED.price, watchlist_items.price),
            rvol = COALESCE(EXCLUDED.rvol, watchlist_items.rvol),
            float_m = COALESCE(EXCLUDED.float_m, watchlist_items.float_m),
            last_seen_at = NOW(),
            updated_at = NOW()
        """,
        (
            symbol, payload, score, provenance, payload,
            scan.get("price"), scan.get("rvol"), scan.get("float_m"),
        ),
    )
    conn.commit()
    return True


def _upsert_qualified_intel(conn, scan: dict, rotation: dict, *, dry_run: bool) -> bool:
    symbol = (scan.get("symbol") or "").upper()
    if not symbol:
        return False

    scan_id = str(scan.get("id") or symbol)
    title = (
        f"Small-cap rotation: {symbol} via {_screener_name(scan)} "
        f"({scan.get('decision')} score {scan.get('score')})"
    )[:200]
    quality = min(95, max(50, int(scan.get("score") or MIN_WATCHLIST_SCORE) + 10))
    relevance = min(0.95, 0.5 + float(rotation.get("strength") or 0) * 0.4)

    if dry_run:
        log.info("  [dry-run] qualified_intel %s Q=%s", symbol, quality)
        return True

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO qualified_intelligence
            (source_type, source_table, source_id, symbol, title,
             quality_score, relevance_score, strategy_focus)
        VALUES ('screener', 'trade_ai_scans', %s, %s, %s, %s, %s, 'swing_breakout')
        ON CONFLICT DO NOTHING
        """,
        (scan_id, symbol, title, quality, relevance),
    )
    conn.commit()
    return cur.rowcount > 0


def _symbol_has_planned_signal_today(conn, symbol: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM strategy_signals
        WHERE symbol = %s AND fired_at::date = CURRENT_DATE
          AND entry_high IS NOT NULL AND stop_loss IS NOT NULL
          AND target_1 IS NOT NULL AND COALESCE(shares, 0) > 0
          AND status IN ('active', 'ACTIVE')
        LIMIT 1
        """,
        (symbol.upper(),),
    )
    return cur.fetchone() is not None


def ensure_trend_signals(
    conn,
    symbols: List[str],
    *,
    lookback_days: int = LOOKBACK_DAYS,
    dry_run: bool = False,
) -> dict:
    """Force today's planned strategy_signals for trend-qualified symbols missing them."""
    import uuid
    from datetime import timezone as _tz

    from strategy_signal_sync import (
        _get_strategy_signals_columns,
        _load_strategy_configs,
        find_trade_plan,
        get_today_go_scans,
        infer_strategy_id,
        insert_strategy_signal,
        route_candidate_to_strategies,
    )

    if not symbols:
        return {"forced": 0, "already_ok": 0, "errors": 0}

    available_cols = _get_strategy_signals_columns(conn)
    configs = _load_strategy_configs()
    sync_run_id = f"trend_{datetime.now(_tz.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    forced = already = errors = 0

    for sym in symbols:
        sym = sym.upper()
        if _symbol_has_planned_signal_today(conn, sym):
            already += 1
            continue
        scans = get_today_go_scans(conn, symbols=[sym], lookback_days=lookback_days)
        if not scans:
            log.warning("  %s: no GO/A+ scan in lookback for trend signal", sym)
            errors += 1
            continue
        scan = scans[0]
        # Re-price from live quote so stale screener rows (days old) still produce valid signals
        try:
            from market_quote_provider import get_best_quote
            live_q = get_best_quote(sym)
            if live_q and live_q.get("last_price"):
                scan = dict(scan)
                scan["price"] = float(live_q["last_price"])
        except Exception:
            pass
        plan = find_trade_plan(conn, sym)
        routes = route_candidate_to_strategies(scan, configs)
        if not routes:
            sid = infer_strategy_id(scan)
            routes = [(sid, ["trend_fallback"], [])]
        strategy_id, match_reasons, reject_reasons = routes[0]
        scan_copy = dict(scan)
        scan_copy["strategy_id"] = strategy_id
        route_data = {
            "route_match_reasons": match_reasons,
            "route_reject_reasons": reject_reasons,
        }
        if dry_run:
            log.info("  [dry-run] would force signal %s → %s", sym, strategy_id)
            forced += 1
            continue
        try:
            result = insert_strategy_signal(
                conn, scan_copy, plan, available_cols, sync_run_id,
                dry_run=False, route_data=route_data, max_price_drift_pct=25.0,
            )
            if result.get("status") == "inserted":
                forced += 1
                log.info("  %s: forced trend signal → %s (#%s)", sym, strategy_id, result.get("signal_id"))
            elif result.get("reason") == "duplicate":
                already += 1
            else:
                log.warning("  %s: trend signal skipped — %s", sym, result.get("reason"))
                errors += 1
        except Exception as exc:
            log.warning("  %s: trend signal error — %s", sym, exc)
            errors += 1
            try:
                conn.rollback()
            except Exception:
                pass

    if not dry_run:
        try:
            conn.commit()
        except Exception:
            conn.rollback()

    return {"forced": forced, "already_ok": already, "errors": errors}


def _sync_proposal_symbols(
    conn,
    symbols: List[str],
    *,
    run_label: Optional[str],
    dry_run: bool,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict:
    """Ensure GO/A+ proposal-tier symbols are in strategy_signals with plans."""
    if not symbols:
        return {"synced": 0, "plans_updated": 0, "forced": 0}

    from strategy_signal_sync import sync_strategy_signals

    sync_result = sync_strategy_signals(
        conn, run_label=run_label, symbols=symbols, lookback_days=lookback_days,
        dry_run=dry_run,
    )

    force_result = ensure_trend_signals(
        conn, symbols, lookback_days=lookback_days, dry_run=dry_run,
    )

    plan_result = {"updated": 0, "total": 0}
    if not dry_run:
        try:
            from backfill_trade_plans_for_signals import backfill_plans

            plan_result = backfill_plans(conn, run_label=run_label)
        except Exception as exc:
            log.warning("plan backfill non-fatal: %s", exc)

    return {
        "symbols": symbols,
        "sync_inserted": sync_result.get("inserted", 0),
        "sync_skipped": sync_result.get("skipped", 0),
        "forced": force_result.get("forced", 0),
        "plans_updated": plan_result.get("updated", 0),
    }


def promote_proposal_tier(
    conn,
    symbols: List[str],
    *,
    execution_label: str = "trend_bridge",
    dry_run: bool = False,
    limit_per_symbol: int = 1,
    max_risk_dollars: float | None = None,
    trend_lookback_days: int = LOOKBACK_DAYS_PROPOSAL,
) -> Dict[str, Any]:
    """Create paper proposals for every proposal-tier symbol that has a planned signal today."""
    if dry_run or not symbols:
        return {"proposals_created": 0, "symbols_attempted": 0, "details": []}

    from auto_proposal_generator import run_auto_proposals

    created = 0
    details: List[dict] = []
    for sym in symbols:
        try:
            r = run_auto_proposals(
                conn,
                symbol=sym,
                run_label=None,
                min_score=MIN_PROPOSAL_SCORE,
                limit=limit_per_symbol,
                dry_run=False,
                execution_label=execution_label,
                max_risk_dollars=max_risk_dollars,
                trend_lookback_days=trend_lookback_days,
            )
            n = int(r.get("proposals_created") or 0)
            created += n
            details.append({
                "symbol": sym,
                "created": n,
                "signals_checked": r.get("signals_checked", 0),
                "skipped": r.get("proposals_skipped", 0),
            })
            if n:
                log.info("  proposal %s: created %d", sym, n)
            else:
                log.info("  proposal %s: no create (checked=%s skipped=%s)",
                         sym, r.get("signals_checked"), r.get("proposals_skipped"))
        except Exception as exc:
            log.warning("  proposal %s failed: %s", sym, exc)
            details.append({"symbol": sym, "created": 0, "error": str(exc)[:120]})

    return {
        "proposals_created": created,
        "symbols_attempted": len(symbols),
        "details": details,
    }


def run_rotation_bridge(
    conn,
    *,
    run_label: Optional[str] = None,
    dry_run: bool = True,
    force: bool = False,
    lookback_days: int = LOOKBACK_DAYS,
) -> Dict[str, Any]:
    """Main bridge: watchlist + qualified intel + signal sync when rotation is active."""
    import market_rotation_signals as mrs

    rotation = mrs.detect_small_cap_rotation()
    active = rotation.get("signal") == "small_cap_outperform"

    result: Dict[str, Any] = {
        "rotation_active": active,
        "rotation": rotation,
        "dry_run": dry_run,
        "forced": force,
        "run_label": run_label,
        "watchlist_promoted": 0,
        "qualified_intel_added": 0,
        "proposal_symbols": [],
        "proposal_sync": {},
        "proposals": {},
        "candidates_screened": 0,
        "skipped_inactive": not active and not force,
        "at": datetime.now(timezone.utc).isoformat(),
    }

    if not active and not force:
        log.info("No small-cap rotation signal — bridge skipped (use --force to override)")
        return result

    wl_lookback = lookback_days
    prop_lookback = min(lookback_days, LOOKBACK_DAYS_PROPOSAL)

    candidates = fetch_rotation_candidates(
        conn, lookback_days=wl_lookback, run_label=run_label,
    )
    broad = fetch_broad_trend_candidates(conn, lookback_days=prop_lookback)
    candidates = _merge_candidates(candidates, broad)
    result["candidates_screened"] = len(candidates)
    log.info(
        "Rotation %s — %d candidates from %d screeners (lookback %dd)",
        rotation.get("explain", "active"),
        len(candidates),
        len(SMALL_CAP_SCREENERS),
        lookback_days,
    )

    watchlist_promoted = 0
    qualified_added = 0
    proposal_symbols: List[str] = []

    for scan in candidates:
        ok, reject = passes_liquidity_gates(scan)
        if not ok:
            log.debug("  %s: gate reject — %s", scan.get("symbol"), ", ".join(reject))
            continue

        decision = (scan.get("decision") or "").upper()
        score = float(scan.get("score") or 0)

        # Watchlist tier: GO, WAIT, or A+ with score ≥ 35
        if decision in ("GO", "WAIT", "A+") and score >= MIN_WATCHLIST_SCORE:
            if watchlist_promoted < MAX_WATCHLIST:
                if _upsert_watchlist(conn, scan, rotation, dry_run=dry_run):
                    watchlist_promoted += 1
                if _upsert_qualified_intel(conn, scan, rotation, dry_run=dry_run):
                    qualified_added += 1

        # Proposal tier: GO or A+ with score ≥ 40 + strict gates
        if decision in ("GO", "A+") and score >= MIN_PROPOSAL_SCORE:
            sym = (scan.get("symbol") or "").upper()
            if sym and sym not in proposal_symbols:
                pg_ok, pg_reject = passes_proposal_gates(scan, conn=conn)
                if pg_ok:
                    proposal_symbols.append(sym)
                else:
                    log.info("  %s: proposal gate reject — %s", sym, ", ".join(pg_reject))

    proposal_symbols = proposal_symbols[:MAX_PROPOSAL_SYMBOLS]
    result["proposal_lookback_days"] = prop_lookback
    result["watchlist_promoted"] = watchlist_promoted
    result["qualified_intel_added"] = qualified_added
    result["proposal_symbols"] = proposal_symbols

    if proposal_symbols:
        result["proposal_sync"] = _sync_proposal_symbols(
            conn, proposal_symbols, run_label=run_label, dry_run=dry_run,
            lookback_days=prop_lookback,
        )
        result["proposals"] = promote_proposal_tier(
            conn,
            proposal_symbols,
            execution_label="small_cap_rotation_bridge",
            dry_run=dry_run,
            max_risk_dollars=MAX_TREND_PROPOSAL_RISK,
            trend_lookback_days=prop_lookback,
        )
        log.info(
            "Proposal tier: %d symbols — sync_inserted=%s proposals_created=%s",
            len(proposal_symbols),
            result["proposal_sync"].get("sync_inserted"),
            result["proposals"].get("proposals_created"),
        )

    # Persist lightweight audit for API / health checks
    if not dry_run:
        try:
            cache_path = PROJECT_ROOT / "data" / "runtime" / "small_cap_rotation_bridge_latest.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(result, indent=2, default=str))
        except Exception as exc:
            log.debug("audit cache write failed: %s", exc)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Small-cap rotation bridge — watchlist + proposal screening when IWM leads SPY",
    )
    parser.add_argument("--today", action="store_true", help="Use today's run (no run_label filter)")
    parser.add_argument("--run-label", type=str, help="Filter scans by orchestrator run label")
    parser.add_argument("--apply", action="store_true", help="Write watchlist/signals (default dry-run)")
    parser.add_argument("--force", action="store_true", help="Run even when rotation signal inactive")
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    args = parser.parse_args()

    dry_run = not args.apply
    run_label = None if args.today else args.run_label

    conn = get_conn()
    try:
        result = run_rotation_bridge(
            conn,
            run_label=run_label,
            dry_run=dry_run,
            force=args.force,
            lookback_days=args.lookback_days,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()