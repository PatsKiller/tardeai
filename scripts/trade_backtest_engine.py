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
        df_entry = df[df.index <= open_date]
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
    cols = ['trade_key', 'symbol', 'open_date', 'close_date',
            'actual_entry_price', 'actual_exit_price', 'actual_pnl', 'actual_pnl_pct', 'hold_days',
            'entry_rsi', 'entry_sma20_dist_pct', 'entry_sma50_dist_pct', 'entry_sma200_dist_pct',
            'entry_volume_ratio', 'entry_52w_percentile', 'entry_atr', 'entry_atr_stop_pct',
            'better_entry_existed', 'best_entry_price', 'entry_savings',
            'exit_rsi', 'max_price_5d_after', 'max_price_10d_after', 'max_price_20d_after',
            'left_on_table_5d', 'left_on_table_10d', 'left_on_table_20d', 'exit_was_early',
            'entry_grade', 'exit_grade', 'overall_grade', 'data_quality', 'error_msg']
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
    cur.execute("""
        SELECT symbol || ':' || account || ':' || close_date::text as trade_key,
               symbol, open_date, close_date, trade_type,
               buy_price, sell_price, shares, pnl, pnl_pct, hold_days
        FROM trade_closed
        WHERE buy_price > 0 OR pnl != 0
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
