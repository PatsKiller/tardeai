#!/usr/bin/env python3
"""report_proposal_technical_backtest_audit.py — Technical and backtest evidence audit.

Read-only. No mutations. No trade creation.

Usage:
    .venv/bin/python scripts/report_proposal_technical_backtest_audit.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

# Strategies that require Fib analysis
FIB_STRATEGIES = {"fib_retracement_bounce", "swing_breakout", "swing_trade", "recovery_watch"}
# Strategies that require ORB
ORB_STRATEGIES = {"gap_and_go", "momentum_scalp", "earnings_catalyst"}


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
            return None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def _json_safe(v):
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    try:
        return str(v)
    except Exception:
        return None


def audit_proposal_technical_backtest(proposal_id=None, symbol=None):
    """Audit technical/backtest evidence for pending proposals."""
    where = "WHERE ptp.status = 'PENDING'"
    params = []
    if proposal_id:
        where += " AND ptp.id = %s"
        params.append(proposal_id)
    if symbol:
        where += " AND ptp.symbol = %s"
        params.append(symbol)

    proposals = _db_query(f"""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id
        FROM paper_trade_proposals ptp
        {where}
        ORDER BY ptp.created_at DESC LIMIT 50
    """, params) or []

    results = []
    for p in proposals:
        pid = p["id"]
        sym = p["symbol"]
        sid = p["strategy_id"] or ""

        # Technical snapshot
        ts = _db_query("""
            SELECT technical_grade, rsi_14, atr_14, atr_pct, vwap, vwap_distance_pct,
                   above_vwap, ema_alignment, ema_8_distance_pct, ema_21_distance_pct,
                   ema_50_distance_pct, ema_200_distance_pct,
                   nearest_fib_level, nearest_fib_distance_pct, fib_context,
                   opening_range_status, opening_range_high, opening_range_low,
                   premarket_status, ohlcv_data_status, missing_data,
                   computed_at
            FROM proposal_technical_snapshots
            WHERE proposal_id = %s ORDER BY computed_at DESC LIMIT 1
        """, [pid], fetch="one")

        ts_exists = ts is not None
        ts_age = None
        if ts and ts.get("computed_at"):
            try:
                ca = ts["computed_at"]
                if isinstance(ca, str):
                    from datetime import datetime as _dt
                    ca = _dt.fromisoformat(ca.replace("Z", "+00:00"))
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=timezone.utc)
                ts_age = (datetime.now(timezone.utc) - ca).total_seconds()
            except Exception:
                pass

        # Fib status
        fib_required = sid in FIB_STRATEGIES
        fib_level = _json_safe(ts.get("nearest_fib_level")) if ts else None
        fib_dist = _json_safe(ts.get("nearest_fib_distance_pct")) if ts else None
        fib_context = ts.get("fib_context") if ts else None
        if fib_level is not None:
            fib_status = "available"
        elif fib_required:
            fib_status = "missing_required"
        else:
            fib_status = "not_applicable"

        # ORB status
        orb_required = sid in ORB_STRATEGIES
        orb_status_raw = _json_safe(ts.get("opening_range_status")) if ts else None
        if orb_status_raw:
            orb_status = orb_status_raw
        elif orb_required:
            orb_status = "missing_required"
        else:
            orb_status = "not_applicable"

        # EMA alignment
        ema_alignment = _json_safe(ts.get("ema_alignment")) if ts else None
        ema_status = ema_alignment if ema_alignment else ("missing" if ts_exists else "not_checked")

        # VWAP
        vwap_dist = _json_safe(ts.get("vwap_distance_pct")) if ts else None
        vwap_status = "available" if vwap_dist is not None else ("missing" if ts_exists else "not_checked")

        # OHLCV
        ohlcv_status = _json_safe(ts.get("ohlcv_data_status")) if ts else "not_checked"

        # Backtest snapshot
        bt = _db_query("""
            SELECT backtest_quality, sample_size, win_rate, profit_factor,
                   expectancy, avg_r, limitations
            FROM proposal_backtest_snapshots
            WHERE proposal_id = %s ORDER BY id DESC LIMIT 1
        """, [pid], fetch="one")

        bt_exists = bt is not None
        sample_count = int(bt["sample_size"] or 0) if bt else 0
        bt_quality_raw = _json_safe(bt.get("backtest_quality")) if bt else None

        if bt_quality_raw:
            bt_quality = bt_quality_raw
        elif sample_count >= 20:
            bt_quality = "SUFFICIENT"
        elif sample_count >= 5:
            bt_quality = "LIMITED"
        elif sample_count > 0:
            bt_quality = "INSUFFICIENT"
        elif bt_exists:
            bt_quality = "NO_DATA"
        else:
            bt_quality = "MISSING"

        # Missing sections
        missing_sections = []
        if not ts_exists:
            missing_sections.append("technical_snapshot")
        else:
            ts_missing = ts.get("missing_data")
            if isinstance(ts_missing, str):
                try:
                    ts_missing = json.loads(ts_missing)
                except Exception:
                    ts_missing = []
            if ts_missing:
                missing_sections.extend(ts_missing if isinstance(ts_missing, list) else [])
        if fib_status == "missing_required":
            missing_sections.append("fib_levels")
        if orb_status == "missing_required":
            missing_sections.append("opening_range")
        if not bt_exists:
            missing_sections.append("backtest")

        # Next action
        if not ts_exists:
            next_action = "Run Technical Snapshot"
        elif fib_status == "missing_required":
            next_action = "Run Fib analysis"
        elif orb_status == "missing_required":
            next_action = "Run Opening Range analysis"
        elif not bt_exists:
            next_action = "Run Backtest"
        else:
            next_action = None

        results.append({
            "proposal_id": pid,
            "symbol": sym,
            "strategy_id": sid,
            "technical_snapshot_exists": ts_exists,
            "technical_snapshot_age_seconds": round(ts_age) if ts_age else None,
            "technical_grade": _json_safe(ts.get("technical_grade")) if ts else None,
            "rsi": _json_safe(ts.get("rsi_14")) if ts else None,
            "atr": _json_safe(ts.get("atr_14")) if ts else None,
            "ema_status": ema_status,
            "vwap_status": vwap_status,
            "fib_status": fib_status,
            "nearest_fib_level": fib_level,
            "nearest_fib_distance_pct": fib_dist,
            "orb_status": orb_status,
            "ohlcv_status": ohlcv_status,
            "backtest_exists": bt_exists,
            "backtest_quality": bt_quality,
            "backtest_sample_count": sample_count,
            "backtest_win_rate": float(bt["win_rate"]) if bt and bt.get("win_rate") else None,
            "missing_required_sections": missing_sections,
            "next_action": next_action,
        })

    return results


def main():
    p = argparse.ArgumentParser(description="Technical/backtest evidence audit (read-only)")
    p.add_argument("--symbol", type=str)
    p.add_argument("--proposal-id", type=int)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    results = audit_proposal_technical_backtest(args.proposal_id, args.symbol)

    if args.verbose:
        print(f"Technical/Backtest Audit — {len(results)} proposals")
        for r in results:
            print(f"\n  {r['symbol']} [{r['strategy_id']}]")
            print(f"    Technical: {'exists' if r['technical_snapshot_exists'] else 'MISSING'} grade={r['technical_grade'] or '?'}")
            print(f"    Fib: {r['fib_status']}, ORB: {r['orb_status']}")
            print(f"    EMA: {r['ema_status']}, VWAP: {r['vwap_status']}")
            print(f"    Backtest: {r['backtest_quality']} n={r['backtest_sample_count']}")
            if r["missing_required_sections"]:
                print(f"    Missing: {', '.join(r['missing_required_sections'])}")
            if r["next_action"]:
                print(f"    Next: {r['next_action']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(results, indent=2, default=str))
    if args.output_md:
        md = ["# Technical / Backtest Audit", ""]
        md.append("| Symbol | Strategy | Grade | Fib | ORB | Backtest | Missing |")
        md.append("|--------|----------|-------|-----|-----|----------|---------|")
        for r in results:
            md.append(f"| {r['symbol']} | {r['strategy_id']} | {r['technical_grade'] or '-'} | {r['fib_status']} | {r['orb_status']} | {r['backtest_quality']} n={r['backtest_sample_count']} | {len(r['missing_required_sections'])} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
