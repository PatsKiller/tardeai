#!/usr/bin/env python3
"""Trade Backtest Engine — reconstructs technical context at entry/exit for closed trades.
Grades entry quality (A-D) and exit quality (A-D) using historical OHLCV from yfinance."""
import os, sys, time, logging
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

for line in (ROOT / '.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import numpy as np
import yfinance as yf

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'dbname': os.getenv('DB_NAME', 'trade_ai'),
    'user': os.getenv('DB_USER', 'trade_ai'),
    'password': os.getenv('DB_PASSWORD', '')
}


def get_db():
    return psycopg2.connect(**DB_CONFIG)


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float('inf'))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def compute_atr(df, period=14):
    if len(df) < period + 1:
        return None
    high, low, close = df['High'], df['Low'], df['Close'].shift(1)
    tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def compute_macd(closes, fast=12, slow=26, sig=9):
    """MACD line/signal/histogram + a human state label, from daily closes."""
    if len(closes) < slow + sig:
        return None
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    signal = line.ewm(span=sig, adjust=False).mean()
    hist = line - signal
    l, s, h = float(line.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])
    h_prev = float(hist.iloc[-2]) if len(hist) > 1 else h
    crossed_up = h > 0 and h_prev <= 0
    crossed_dn = h < 0 and h_prev >= 0
    if crossed_up:
        state = 'bullish_crossover'
    elif crossed_dn:
        state = 'bearish_crossover'
    elif l > s and h >= h_prev:
        state = 'bullish_momentum'
    elif l > s and h < h_prev:
        state = 'bullish_fading'
    elif l < s and h <= h_prev:
        state = 'bearish_momentum'
    else:
        state = 'bearish_fading'
    return {'line': round(l, 4), 'signal': round(s, 4), 'hist': round(h, 4), 'state': state}


def compute_bollinger(closes, price, period=20, mult=2):
    """Position of price within Bollinger bands (0=lower, 1=upper) + state."""
    if len(closes) < period or price <= 0:
        return None
    win = closes.tail(period)
    mid = float(win.mean()); sd = float(win.std())
    if sd == 0:
        return None
    upper, lower = mid + mult * sd, mid - mult * sd
    pct = (price - lower) / (upper - lower) if upper > lower else 0.5
    state = 'above_upper' if price > upper else 'upper_half' if price >= mid else 'lower_half' if price > lower else 'below_lower'
    return {'pct': round(pct, 3), 'state': state}


def compute_adx(df, period=14):
    """Wilder ADX (trend strength) from daily OHLC."""
    if len(df) < period * 2 + 1:
        return None
    high, low, close = df['High'], df['Low'], df['Close']
    up = high.diff(); dn = -low.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, float('inf'))
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, float('inf'))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float('inf'))
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    v = float(adx.iloc[-1])
    return round(v, 1) if v == v else None  # NaN guard


def compute_fib(df_entry, price, lookback=60):
    """Nearest Fibonacci retracement level of entry within the recent swing leg."""
    win = df_entry.tail(lookback)
    if len(win) < 10 or price <= 0:
        return None
    hi, lo = float(win['High'].max()), float(win['Low'].min())
    if hi <= lo:
        return None
    # retracement from the high (uptrend pullback frame): 0 at high, 1 at low
    retr = (hi - price) / (hi - lo)
    levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    nearest = min(levels, key=lambda x: abs(x - retr))
    return {'level': nearest, 'leg_high': round(hi, 2), 'leg_low': round(lo, 2)}


def detect_candle(df_entry):
    """Simple daily candlestick label at the entry bar."""
    if len(df_entry) < 2:
        return None
    o, h, l, c = (float(df_entry['Open'].iloc[-1]), float(df_entry['High'].iloc[-1]),
                  float(df_entry['Low'].iloc[-1]), float(df_entry['Close'].iloc[-1]))
    po, pc = float(df_entry['Open'].iloc[-2]), float(df_entry['Close'].iloc[-2])
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o); lower_wick = min(o, c) - l; upper_wick = h - max(o, c)
    if c > o and pc < po and c >= po and o <= pc:
        return 'bullish_engulfing'
    if c < o and pc > po and c <= po and o >= pc:
        return 'bearish_engulfing'
    if body <= rng * 0.1:
        return 'doji'
    if lower_wick >= body * 2 and upper_wick <= body:
        return 'hammer'
    if upper_wick >= body * 2 and lower_wick <= body:
        return 'shooting_star'
    return 'bullish_marubozu' if c > o and body >= rng * 0.7 else 'bearish_marubozu' if c < o and body >= rng * 0.7 else 'neutral'


def detect_structure(df_entry, price):
    """Heuristic market-structure tag from recent swing behaviour."""
    win = df_entry.tail(40)
    if len(win) < 20:
        return None
    recent_hi = float(win['High'].tail(10).max())
    prior_hi = float(win['High'].head(20).max())
    recent_lo = float(win['Low'].tail(10).min())
    sma20 = float(win['Close'].tail(20).mean())
    near_hi = price >= recent_hi * 0.99
    if near_hi and recent_hi > prior_hi:
        return 'breakout'
    if price > sma20 and recent_lo > float(win['Low'].head(20).min()):
        return 'pullback_in_uptrend'
    if price < sma20 and recent_hi < prior_hi:
        return 'downtrend'
    if abs(price - sma20) / sma20 < 0.02:
        return 'range'
    return 'trend_continuation' if price > sma20 else 'reversal_attempt'


def grade_entry(rsi, volume_ratio, sma50_dist_pct):
    if rsi is None: return 'D'
    vr = volume_ratio or 1.0
    sd = abs(sma50_dist_pct or 0)
    if rsi < 40 and vr > 1.5 and sd <= 5: return 'A'
    if rsi < 55 and vr >= 1.0 and sd <= 10: return 'B'
    if rsi <= 70 and sd <= 20: return 'C'
    return 'D'


def grade_exit(exit_price, max_20d):
    if max_20d is None or exit_price == 0: return 'C'
    ratio = (max_20d - exit_price) / exit_price if exit_price > 0 else 0
    if ratio < 0.05: return 'A'
    if ratio < 0.15: return 'B'
    if ratio < 0.30: return 'C'
    return 'D'


def backtest_trade(trade, df_cache):
    sym = trade['symbol']
    open_date = pd.to_datetime(trade['open_date'])
    close_date = pd.to_datetime(trade['close_date'])
    entry_price = float(trade['buy_price'] or 0)
    exit_price = float(trade['sell_price'] or 0)
    shares = float(trade['shares'] or 0)

    result = {
        'trade_key': trade['trade_key'],
        'paper_trade_id': trade.get('paper_trade_id'),
        'symbol': sym,
        'open_date': trade['open_date'],
        'close_date': trade['close_date'],
        'actual_entry_price': entry_price,
        'actual_exit_price': exit_price,
        'actual_pnl': float(trade['pnl'] or 0),
        'actual_pnl_pct': float(trade['pnl_pct'] or 0),
        'hold_days': trade['hold_days'],
        'data_quality': 'insufficient',
        'error_msg': None,
    }

    if entry_price == 0:
        result['error_msg'] = 'Zero entry price'
        return result

    try:
        # Get or fetch OHLCV
        if sym not in df_cache:
            fetch_start = (open_date - timedelta(days=300)).strftime('%Y-%m-%d')
            fetch_end = (close_date + timedelta(days=30)).strftime('%Y-%m-%d')
            df = yf.download(sym, start=fetch_start, end=fetch_end, auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df_cache[sym] = df
            time.sleep(0.5)
        else:
            df = df_cache[sym]

        if df is None or len(df) < 20:
            result['error_msg'] = f'Only {len(df) if df is not None else 0} rows'
            return result

        # Entry metrics
        # PIT fix (2026-06-11): strictly BEFORE the entry date — the entry day's own (incomplete-at-entry) bar
        # contaminated entry grades (look-ahead). Grades regraded after this change.
        df_entry = df[df.index < open_date]
        if len(df_entry) < 20:
            result['error_msg'] = f'Only {len(df_entry)} rows before entry'
            return result

        entry_closes = df_entry['Close']

        # RSI
        result['entry_rsi'] = compute_rsi(entry_closes)

        # SMA distances
        for period, key in [(20, 'entry_sma20_dist_pct'), (50, 'entry_sma50_dist_pct'), (200, 'entry_sma200_dist_pct')]:
            if len(entry_closes) >= period:
                sma = float(entry_closes.tail(period).mean())
                result[key] = ((entry_price - sma) / sma * 100) if sma > 0 else None

        # Volume ratio
        try:
            entry_day_vol = float(df_entry['Volume'].iloc[-1])
            avg_vol = float(df_entry['Volume'].tail(21).iloc[:-1].mean())
            result['entry_volume_ratio'] = round(entry_day_vol / avg_vol, 2) if avg_vol > 0 else None
        except Exception:
            pass

        # 52-week percentile
        try:
            w52 = df_entry.tail(252)
            w_low, w_high = float(w52['Low'].min()), float(w52['High'].max())
            if w_high > w_low:
                result['entry_52w_percentile'] = round(((entry_price - w_low) / (w_high - w_low)) * 100, 1)
        except Exception:
            pass

        # ATR
        result['entry_atr'] = compute_atr(df_entry)
        if result['entry_atr'] and entry_price > 0:
            result['entry_atr_stop_pct'] = round((result['entry_atr'] * 2 / entry_price) * 100, 2)

        # MACD / Bollinger / ADX / Fibonacci / candle / structure (all from daily OHLCV)
        try:
            macd = compute_macd(entry_closes)
            if macd:
                result['entry_macd_line'] = macd['line']; result['entry_macd_signal'] = macd['signal']
                result['entry_macd_hist'] = macd['hist']; result['entry_macd_state'] = macd['state']
            bb = compute_bollinger(entry_closes, entry_price)
            if bb:
                result['entry_bb_pct'] = bb['pct']; result['entry_bb_state'] = bb['state']
            result['entry_adx'] = compute_adx(df_entry)
            fib = compute_fib(df_entry, entry_price)
            if fib:
                result['entry_fib_level'] = fib['level']; result['entry_fib_leg_high'] = fib['leg_high']; result['entry_fib_leg_low'] = fib['leg_low']
            result['entry_candle'] = detect_candle(df_entry)
            result['entry_structure'] = detect_structure(df_entry, entry_price)
        except Exception:
            pass

        # Better entry (lowest in 5d before)
        try:
            prior_5d = df_entry.tail(6).iloc[:-1]
            if len(prior_5d) > 0:
                best = float(prior_5d['Close'].min())
                result['best_entry_price'] = round(best, 2)
                result['better_entry_existed'] = best < entry_price * 0.98
                if result['better_entry_existed'] and shares > 0:
                    result['entry_savings'] = round((entry_price - best) * shares, 2)
        except Exception:
            pass

        # Exit metrics
        df_exit = df[df.index <= close_date]
        if len(df_exit) > 14:
            result['exit_rsi'] = compute_rsi(df_exit['Close'])
            try:
                em = compute_macd(df_exit['Close'])
                if em:
                    result['exit_macd_state'] = em['state']
            except Exception:
                pass

        # Forward prices after exit
        df_after = df[df.index > close_date]
        for days, key_max, key_left in [(5, 'max_price_5d_after', 'left_on_table_5d'),
                                         (10, 'max_price_10d_after', 'left_on_table_10d'),
                                         (20, 'max_price_20d_after', 'left_on_table_20d')]:
            window = df_after.head(days)
            if len(window) > 0:
                max_px = float(window['High'].max())
                result[key_max] = round(max_px, 2)
                if shares > 0 and exit_price > 0:
                    result[key_left] = round(max(0, (max_px - exit_price) * shares), 2)

        # Early exit?
        if result.get('max_price_5d_after') and exit_price > 0:
            result['exit_was_early'] = result['max_price_5d_after'] > exit_price * 1.05

        # Grades
        result['entry_grade'] = grade_entry(result.get('entry_rsi'), result.get('entry_volume_ratio'), result.get('entry_sma50_dist_pct'))
        result['exit_grade'] = grade_exit(exit_price, result.get('max_price_20d_after'))

        gm = {'A': 4, 'B': 3, 'C': 2, 'D': 1}
        avg = (gm.get(result['entry_grade'], 2) + gm.get(result['exit_grade'], 2)) / 2
        result['overall_grade'] = 'A' if avg >= 3.5 else 'B' if avg >= 2.5 else 'C' if avg >= 1.5 else 'D'

        nulls = sum(1 for k in ['entry_rsi', 'entry_sma50_dist_pct', 'entry_volume_ratio'] if result.get(k) is None)
        result['data_quality'] = 'full' if nulls == 0 else 'partial'

    except Exception as e:
        result['data_quality'] = 'error'
        result['error_msg'] = str(e)[:200]

    return result


def upsert_result(conn, result):
    # Canonical all-trades link: resolve trade_instance_id from the paper id or the trade_key (covers
    # paper AND imported Schwab/Fidelity backtests). paper_trade_id stays as legacy-compat.
    if not result.get('trade_instance_id'):
        rc = conn.cursor()
        if result.get('paper_trade_id') is not None:
            rc.execute("SELECT id FROM trade_instances WHERE source_table='paper_trades' AND source_trade_id=%s",
                       (str(result['paper_trade_id']),))
        else:
            rc.execute("SELECT id FROM trade_instances WHERE trade_key=%s", (result.get('trade_key'),))
        r = rc.fetchone()
        result['trade_instance_id'] = r[0] if r else None
    cols = ['trade_key', 'paper_trade_id', 'trade_instance_id', 'symbol', 'open_date', 'close_date',
            'actual_entry_price', 'actual_exit_price', 'actual_pnl', 'actual_pnl_pct', 'hold_days',
            'entry_rsi', 'entry_sma20_dist_pct', 'entry_sma50_dist_pct', 'entry_sma200_dist_pct',
            'entry_volume_ratio', 'entry_52w_percentile', 'entry_atr', 'entry_atr_stop_pct',
            'better_entry_existed', 'best_entry_price', 'entry_savings',
            'exit_rsi', 'max_price_5d_after', 'max_price_10d_after', 'max_price_20d_after',
            'left_on_table_5d', 'left_on_table_10d', 'left_on_table_20d', 'exit_was_early',
            'entry_grade', 'exit_grade', 'overall_grade', 'data_quality', 'error_msg',
            'entry_macd_line', 'entry_macd_signal', 'entry_macd_hist', 'entry_macd_state',
            'entry_bb_pct', 'entry_bb_state', 'entry_adx',
            'entry_fib_level', 'entry_fib_leg_high', 'entry_fib_leg_low',
            'entry_candle', 'entry_structure', 'exit_macd_state']
    values = [result.get(c) for c in cols]
    placeholders = ', '.join(['%s'] * len(cols))
    updates = ', '.join([f"{c}=EXCLUDED.{c}" for c in cols if c != 'trade_key'])
    cur = conn.cursor()
    cur.execute(f"""
        INSERT INTO trade_backtest_results ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT (trade_key) DO UPDATE SET {updates}, computed_at=NOW()
    """, values)


def run_all():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Schwab import (trade_closed) + the PAPER loop (closed paper_trades) — unified keyspace so backtest
    # comparison covers paper trades too. paper_trade_id is carried so the link is explicit.
    cur.execute("""
        SELECT symbol || ':' || account || ':' || close_date::text as trade_key,
               symbol, open_date, close_date, trade_type,
               buy_price, sell_price, shares, pnl, pnl_pct, hold_days,
               NULL::bigint AS paper_trade_id
        FROM trade_closed
        WHERE buy_price > 0 OR pnl != 0
        UNION ALL
        SELECT symbol || ':' || account || ':' || exit_time::date::text as trade_key,
               symbol, entry_time::date AS open_date, exit_time::date AS close_date, 'paper' AS trade_type,
               entry_price AS buy_price, exit_price AS sell_price, shares, pnl, pnl_pct,
               CASE WHEN hold_time_min IS NOT NULL THEN round(hold_time_min/1440.0)::int ELSE NULL END AS hold_days,
               id AS paper_trade_id
        FROM paper_trades
        WHERE exit_time IS NOT NULL AND symbol ~ '^[A-Z]{1,5}$' AND COALESCE(entry_price,0) > 0
        ORDER BY symbol, open_date
    """)
    trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    log.info(f"Backtesting {len(trades)} trades across {len(set(t['symbol'] for t in trades))} symbols")

    counts = {'full': 0, 'partial': 0, 'insufficient': 0, 'error': 0}
    df_cache = {}
    conn = get_db()

    for i, trade in enumerate(trades):
        result = backtest_trade(trade, df_cache)
        counts[result['data_quality']] += 1
        upsert_result(conn, result)
        if (i + 1) % 10 == 0:
            conn.commit()
            log.info(f"  [{i+1}/{len(trades)}] {counts}")

    conn.commit()
    conn.close()
    log.info(f"=== Complete: {counts}")
    return counts


def print_summary():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT entry_grade, COUNT(*) as count, AVG(actual_pnl) as avg_pnl,
               SUM(CASE WHEN actual_pnl > 0 THEN 1 ELSE 0 END) as wins
        FROM trade_backtest_results WHERE data_quality IN ('full','partial') AND entry_grade IS NOT NULL
        GROUP BY entry_grade ORDER BY entry_grade
    """)
    print("\n=== Entry Grade Distribution ===")
    print(f"{'GRADE':<6} {'COUNT':>6} {'AVG P&L':>10} {'WIN RATE':>10}")
    for r in cur.fetchall():
        wr = (r['wins'] / r['count'] * 100) if r['count'] > 0 else 0
        print(f"{r['entry_grade']:<6} {r['count']:>6} ${float(r['avg_pnl'] or 0):>9,.0f} {wr:>9.0f}%")

    cur.execute("""
        SELECT exit_grade, COUNT(*) as count, SUM(left_on_table_20d) as total_left, AVG(left_on_table_20d) as avg_left
        FROM trade_backtest_results WHERE data_quality IN ('full','partial') AND exit_grade IS NOT NULL
        GROUP BY exit_grade ORDER BY exit_grade
    """)
    print("\n=== Exit Grade Distribution ===")
    print(f"{'GRADE':<6} {'COUNT':>6} {'TOTAL LEFT':>14} {'AVG LEFT':>10}")
    for r in cur.fetchall():
        print(f"{r['exit_grade']:<6} {r['count']:>6} ${float(r['total_left'] or 0):>13,.0f} ${float(r['avg_left'] or 0):>9,.0f}")

    cur.execute("SELECT SUM(left_on_table_20d) as total FROM trade_backtest_results WHERE data_quality IN ('full','partial')")
    total = cur.fetchone()
    print(f"\nTotal left on table (20d): ${float(total['total'] or 0):,.0f}")
    conn.close()


if __name__ == '__main__':
    run_all()
    print_summary()
