#!/usr/bin/env python3
"""proposal_technical_snapshot.py — Technical intelligence snapshot for paper proposals.

Generates ATR/RSI/VWAP/Fib/ORB/float rotation context for a proposal.

Usage:
    .venv/bin/python scripts/proposal_technical_snapshot.py --proposal-id 2
    .venv/bin/python scripts/proposal_technical_snapshot.py --symbol SEAT
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

log = logging.getLogger("technical_snapshot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ── Classification helpers ─────────────────────────────────────────────────

def classify_rsi(rsi):
    if rsi is None:
        return None
    rsi = float(rsi)
    if rsi >= 80: return "extremely overbought"
    if rsi >= 70: return "overbought"
    if rsi >= 55: return "bullish momentum"
    if rsi >= 45: return "neutral"
    if rsi >= 30: return "weak"
    return "oversold"


def classify_atr(atr, price):
    if atr is None or price is None or price <= 0:
        return None, None
    atr_pct = float(atr) / float(price) * 100
    if atr_pct > 10: state = "highly volatile"
    elif atr_pct >= 5: state = "volatile"
    elif atr_pct >= 2: state = "normal active"
    else: state = "low volatility"
    return round(atr_pct, 2), state


def classify_rvol(rvol):
    if rvol is None:
        return None
    rvol = float(rvol)
    if rvol >= 10: return "exceptional attention"
    if rvol >= 5: return "high attention"
    if rvol >= 2: return "elevated"
    return "normal / weak"


def classify_vwap(price, vwap):
    if price is None or vwap is None or vwap <= 0:
        return None, None
    dist = (float(price) - float(vwap)) / float(vwap) * 100
    if dist > 3: state = "extended above VWAP"
    elif dist > 0: state = "above VWAP"
    elif dist > -0.5: state = "near VWAP"
    else: state = "below VWAP / weak intraday control"
    return round(dist, 2), state


def classify_float_rotation(volume, float_shares):
    if volume is None or float_shares is None or float_shares <= 0:
        return None, None
    ratio = float(volume) / float(float_shares)
    if ratio > 1.0: state = "full float rotation"
    elif ratio >= 0.5: state = "major float rotation"
    elif ratio >= 0.1: state = "active but not full rotation"
    else: state = "weak rotation"
    return round(ratio, 3), state


def classify_gap(gap_pct):
    if gap_pct is None:
        return None
    gap = float(gap_pct)
    if gap > 20: return "massive gap"
    if gap > 10: return "strong gap"
    if gap > 5: return "moderate gap"
    if gap > 2: return "small gap"
    if gap > 0: return "micro gap"
    if gap < -5: return "gap down"
    return "flat open"


def get_fib_context(conn, symbol):
    """Try to get fib context from indicator cache."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT full_result FROM indicator_confluence_cache
            WHERE symbol = %s ORDER BY computed_at DESC LIMIT 1
        """, [symbol])
        row = cur.fetchone()
        if row and row[0]:
            result = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            signals = result.get('signals', {})
            if 'fib' in signals:
                fib = signals['fib']
                if fib.get('available', True):
                    return fib
        return {"available": False, "summary": f"Fib context unavailable — no fib cache populated for {symbol}"}
    except Exception:
        return {"available": False, "summary": f"Fib context unavailable — no fib cache populated for {symbol}"}


def get_orb_context(conn, symbol):
    """Try to get ORB/intraday context."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT full_result FROM indicator_confluence_cache
            WHERE symbol = %s ORDER BY computed_at DESC LIMIT 1
        """, [symbol])
        row = cur.fetchone()
        if row and row[0]:
            result = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            signals = result.get('signals', {})
            if 'orb' in signals:
                return signals['orb']
        return {"available": False, "summary": "ORB context unavailable — no intraday candle data"}
    except Exception:
        return {"available": False, "summary": "ORB context unavailable — no intraday candle data"}


def build_overbought_oversold_summary(rsi_state, vwap_state, atr_state):
    parts = []
    if rsi_state:
        if 'overbought' in rsi_state:
            parts.append(f"RSI {rsi_state}")
        elif rsi_state == 'oversold':
            parts.append("RSI oversold")
    if vwap_state and 'extended' in vwap_state:
        parts.append("Extended above VWAP")
    if not parts:
        return "Not overbought or oversold based on available data"
    return "; ".join(parts)


def generate_snapshot(conn, proposal_id=None, symbol=None):
    """Generate technical snapshot for a proposal or symbol."""
    cur = conn.cursor()

    # Load proposal data
    proposal = None
    if proposal_id:
        cur.execute("""
            SELECT id, symbol, strategy_id, proposed_entry, proposed_stop,
                   proposed_target1, rvol, float_m, gap_pct, atr, rsi,
                   vwap_distance, above_vwap, fib_context
            FROM paper_trade_proposals WHERE id = %s
        """, [proposal_id])
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row:
            proposal = dict(zip(cols, row))
            symbol = proposal['symbol']

    if not symbol:
        return {"error": "No symbol specified"}

    # Load scan data
    cur.execute("""
        SELECT price, rvol, float_m, gap_pct, change_pct, volume,
               catalyst, catalyst_verified, catalyst_confidence,
               sector, industry, ticker_perf_1m, sector_perf_1m, vs_sector_pct,
               scanned_at
        FROM trade_ai_scans WHERE symbol = %s
        ORDER BY scanned_at DESC LIMIT 1
    """, [symbol])
    scan_cols = [d[0] for d in cur.description]
    scan_row = cur.fetchone()
    scan = dict(zip(scan_cols, scan_row)) if scan_row else {}

    # Load indicator data
    cur.execute("""
        SELECT atr, adx_regime, full_result, confluence_score, confluence_tier,
               entry_quality, computed_at
        FROM indicator_confluence_cache WHERE symbol = %s
        ORDER BY computed_at DESC LIMIT 1
    """, [symbol])
    ind_cols = [d[0] for d in cur.description]
    ind_row = cur.fetchone()
    ind = dict(zip(ind_cols, ind_row)) if ind_row else {}

    # Extract signals from full_result
    full_result = ind.get('full_result') or {}
    if isinstance(full_result, str):
        try:
            full_result = json.loads(full_result)
        except Exception:
            full_result = {}
    signals = full_result.get('signals', {})

    # Core values
    current_price = float(scan.get('price') or 0)
    proposed_entry = float(proposal.get('proposed_entry') or current_price) if proposal else current_price

    atr = proposal.get('atr') if proposal else None
    atr = atr or ind.get('atr')
    if atr:
        atr = float(atr)

    rsi = proposal.get('rsi') if proposal else None
    rsi = rsi or (signals.get('rsi', {}).get('value') if signals else None)
    if rsi is not None:
        rsi = float(rsi)

    vwap = signals.get('vwap', {}).get('value') if signals else None
    vwap_dist_raw = signals.get('vwap', {}).get('distance_pct') if signals else None
    if vwap_dist_raw is None and proposal and proposal.get('vwap_distance') is not None:
        vwap_dist_raw = float(proposal['vwap_distance'])

    adx = signals.get('adx', {}).get('value') if signals else None
    adx_regime = ind.get('adx_regime')

    volume = scan.get('volume')
    avg_volume = signals.get('volume', {}).get('avg') if signals else None
    rvol = proposal.get('rvol') if proposal else None
    rvol = rvol or scan.get('rvol')
    float_m = proposal.get('float_m') if proposal else None
    float_m = float_m or scan.get('float_m')
    gap_pct = proposal.get('gap_pct') if proposal else None
    gap_pct = gap_pct or scan.get('gap_pct')

    sma20_dist = signals.get('sma20', {}).get('distance_pct') if signals else None
    sma50_dist = signals.get('sma50', {}).get('distance_pct') if signals else None

    # Classifications
    atr_pct, atr_state = classify_atr(atr, current_price or proposed_entry)
    rsi_state = classify_rsi(rsi)
    rvol_state = classify_rvol(rvol)
    gap_state = classify_gap(gap_pct)

    vwap_distance_pct, vwap_state = (None, None)
    if vwap_dist_raw is not None:
        vwap_distance_pct = round(float(vwap_dist_raw), 2)
        if vwap_distance_pct > 3: vwap_state = "extended above VWAP"
        elif vwap_distance_pct > 0: vwap_state = "above VWAP"
        elif vwap_distance_pct > -0.5: vwap_state = "near VWAP"
        else: vwap_state = "below VWAP / weak intraday control"
    elif vwap and current_price:
        vwap_distance_pct, vwap_state = classify_vwap(current_price, vwap)

    float_rotation_ratio, float_rotation_state = (None, None)
    if volume and float_m:
        float_shares = float(float_m) * 1_000_000
        float_rotation_ratio, float_rotation_state = classify_float_rotation(volume, float_shares)

    fib_context = get_fib_context(conn, symbol)
    orb_context = get_orb_context(conn, symbol)

    ob_os_summary = build_overbought_oversold_summary(rsi_state, vwap_state, atr_state)

    # Price vs entry
    price_vs_entry_pct = None
    if current_price and proposed_entry and proposed_entry > 0:
        price_vs_entry_pct = round((current_price - proposed_entry) / proposed_entry * 100, 2)

    # Trend strength
    trend_strength = None
    if adx is not None:
        adx_val = float(adx)
        if adx_val >= 40: trend_strength = "strong trend"
        elif adx_val >= 25: trend_strength = "moderate trend"
        elif adx_val >= 15: trend_strength = "weak trend"
        else: trend_strength = "no trend / ranging"

    # Normal trading pattern
    normal_pattern = "Pattern comparison unavailable — no historical pattern data for this symbol/setup yet"
    try:
        cur.execute("""
            SELECT pattern_description FROM pattern_library
            WHERE symbol = %s AND status IN ('PROVEN', 'WATCH')
            ORDER BY created_at DESC LIMIT 1
        """, [symbol])
        row = cur.fetchone()
        if row and row[0]:
            normal_pattern = row[0]
    except Exception:
        pass

    # Technical vote
    bullish = 0
    bearish = 0
    if rsi_state in ('bullish momentum',): bullish += 1
    if rsi_state in ('overbought', 'extremely overbought'): bearish += 1
    if rsi_state in ('oversold',): bullish += 1  # contrarian
    if vwap_state and 'above' in vwap_state and 'extended' not in vwap_state: bullish += 1
    if vwap_state and 'below' in vwap_state: bearish += 1
    if rvol_state in ('exceptional attention', 'high attention'): bullish += 1
    if atr_state == 'highly volatile': bearish += 1

    if bullish > bearish + 1:
        technical_vote = "bullish"
    elif bearish > bullish + 1:
        technical_vote = "bearish"
    elif bullish > bearish:
        technical_vote = "lean bullish"
    elif bearish > bullish:
        technical_vote = "lean bearish"
    else:
        technical_vote = "neutral"

    # Technical concerns
    concerns = []
    if rsi_state and 'overbought' in rsi_state:
        concerns.append(f"RSI {rsi_state}")
    if vwap_state and 'extended' in vwap_state:
        concerns.append("Extended above VWAP — risk of mean reversion")
    if atr_state == 'highly volatile':
        concerns.append("Highly volatile — wide stops needed")
    if gap_state and 'massive' in gap_state:
        concerns.append("Massive gap — gap-fade risk")
    if price_vs_entry_pct is not None and abs(price_vs_entry_pct) > 3:
        concerns.append(f"Price {price_vs_entry_pct:+.1f}% from proposed entry — may be stale")
    if atr is None:
        concerns.append("ATR missing — indicator engine has not populated this symbol")
    if rsi is None:
        concerns.append("RSI missing — indicator engine pending")

    snapshot = {
        "symbol": symbol,
        "proposal_id": proposal_id,
        "current_price": current_price or None,
        "proposed_entry": proposed_entry or None,
        "price_vs_entry_pct": price_vs_entry_pct,
        "atr": round(atr, 4) if atr else None,
        "atr_pct": atr_pct,
        "normal_atr": None,
        "atr_state": atr_state if atr else "ATR missing — indicator engine has not populated this symbol",
        "rsi": round(rsi, 2) if rsi is not None else None,
        "rsi_state": rsi_state if rsi is not None else "RSI missing — indicator engine pending",
        "vwap": round(float(vwap), 4) if vwap else None,
        "vwap_distance_pct": vwap_distance_pct,
        "vwap_state": vwap_state if vwap_distance_pct is not None else "VWAP missing — no intraday VWAP data",
        "adx": round(float(adx), 2) if adx is not None else None,
        "adx_regime": adx_regime,
        "trend_strength": trend_strength if adx is not None else "ADX missing — trend unknown",
        "sma20_distance_pct": round(float(sma20_dist), 2) if sma20_dist is not None else None,
        "sma50_distance_pct": round(float(sma50_dist), 2) if sma50_dist is not None else None,
        "volume": int(volume) if volume else None,
        "avg_volume": int(avg_volume) if avg_volume else None,
        "rvol": round(float(rvol), 2) if rvol else None,
        "rvol_state": rvol_state if rvol else "RVOL missing",
        "float_m": round(float(float_m), 2) if float_m else None,
        "float_rotation_ratio": float_rotation_ratio,
        "float_rotation_state": float_rotation_state or "Float rotation unavailable",
        "gap_pct": round(float(gap_pct), 2) if gap_pct else None,
        "gap_state": gap_state if gap_pct else "No gap data",
        "fib_context": fib_context,
        "orb_context": orb_context,
        "overbought_oversold_summary": ob_os_summary,
        "normal_trading_pattern": normal_pattern,
        "technical_vote": technical_vote,
        "technical_concerns": concerns,
        "scan_timestamp": str(scan.get('scanned_at')) if scan.get('scanned_at') else None,
        "indicator_timestamp": str(ind.get('computed_at')) if ind.get('computed_at') else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Store on proposal
    if proposal_id:
        try:
            conn.rollback()  # clear any prior aborted transaction
        except Exception:
            pass
        try:
            cur.execute("""
                UPDATE paper_trade_proposals
                SET technical_context = %s, updated_at = NOW()
                WHERE id = %s
            """, [json.dumps(snapshot, default=str), proposal_id])
            conn.commit()
        except Exception as e:
            log.warning(f"Failed to update proposal {proposal_id}: {e}")
            try: conn.rollback()
            except: pass

    return snapshot


def main():
    parser = argparse.ArgumentParser(description="Technical snapshot for proposals")
    parser.add_argument("--proposal-id", type=int)
    parser.add_argument("--symbol", type=str)
    parser.add_argument("--all-pending", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.all_pending:
            cur = conn.cursor()
            cur.execute("SELECT id FROM paper_trade_proposals WHERE status='PENDING' ORDER BY created_at DESC")
            for (pid,) in cur.fetchall():
                snap = generate_snapshot(conn, proposal_id=pid)
                log.info(f"  {snap.get('symbol')} (#{pid}): ATR={snap.get('atr')} RSI={snap.get('rsi')} VWAP={snap.get('vwap_state')}")
        elif args.proposal_id:
            snap = generate_snapshot(conn, proposal_id=args.proposal_id)
            print(json.dumps(snap, indent=2, default=str))
        elif args.symbol:
            snap = generate_snapshot(conn, symbol=args.symbol.upper())
            print(json.dumps(snap, indent=2, default=str))
        else:
            print("Usage: --proposal-id N or --symbol TICK or --all-pending")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
