"""
trailing_stop_analyzer.py

For each closed paper trade, simulate what would have happened with different
trailing stop percentages (5%, 8%, 10%, 15%) vs the fixed stop used.

Determines:
1. High-water mark price during the holding period
2. At what price each trail % would have triggered
3. Whether trailing > fixed stop
4. The optimal trail % for this trade
5. An LLM-generated lesson and recommendation

Run via cron after market close, or manually.
Backfills all closed trades that haven't been analyzed yet.
"""

import os, sys, json, logging

# Load .env BEFORE importing db_adapter (it checks DB_* vars at import time)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_adapter import get_connection

log = logging.getLogger(__name__)

TRAIL_PCTS = [5.0, 8.0, 10.0, 15.0]


def fetch_holding_period_ohlc(symbol: str, entry_date: str, exit_date: str) -> dict:
    """
    Fetch daily OHLCV bars from Alpaca for the holding period.
    Returns highest high, lowest low, and daily close series.
    """
    import requests
    ALPACA_BASE = 'https://data.alpaca.markets/v2'
    key = os.environ.get('ALPACA_API_KEY') or os.environ.get('APCA_API_KEY_ID', '')
    secret = os.environ.get('ALPACA_SECRET_KEY') or os.environ.get('APCA_API_SECRET_KEY', '')
    if not key or not secret:
        return {}
    headers = {
        'APCA-API-KEY-ID': key,
        'APCA-API-SECRET-KEY': secret,
    }
    try:
        r = requests.get(
            f'{ALPACA_BASE}/stocks/{symbol}/bars',
            params={
                'start': entry_date,
                'end': exit_date,
                'timeframe': '1Day',
                'adjustment': 'raw',
                'limit': 60,
            },
            headers=headers, timeout=15,
        )
        if r.status_code != 200:
            log.warning(f"Alpaca bars {symbol}: HTTP {r.status_code}")
            return {}
        bars = r.json().get('bars', [])
        if not bars:
            return {}
        highs = [b['h'] for b in bars]
        closes = [{'date': b['t'][:10], 'close': b['c'], 'high': b['h'], 'low': b['l']} for b in bars]
        return {
            'bars': closes,
            'high_water_mark': max(highs),
            'bar_count': len(bars),
        }
    except Exception as e:
        log.warning(f"Alpaca bars {symbol}: {e}")
        return {}


def simulate_trailing_stop(entry_price: float, bars: list,
                           trail_pct: float, fixed_stop: float) -> dict:
    """
    Simulate a trailing stop at trail_pct% below the running high.
    """
    if not bars or not entry_price:
        return {}

    running_high = entry_price
    trail_stop = entry_price * (1 - trail_pct / 100)

    for i, bar in enumerate(bars):
        if bar['high'] > running_high:
            running_high = bar['high']
            trail_stop = running_high * (1 - trail_pct / 100)

        if bar['close'] <= trail_stop:
            trail_exit = trail_stop
            trail_pnl = (trail_exit - entry_price) / entry_price * 100
            fixed_pnl = (fixed_stop - entry_price) / entry_price * 100
            return {
                'trail_pct': trail_pct,
                'trail_exit_price': round(trail_exit, 4),
                'trail_exit_day': bar['date'],
                'trail_pnl_pct': round(trail_pnl, 2),
                'fixed_stop': fixed_stop,
                'fixed_pnl_pct': round(fixed_pnl, 2),
                'gained_vs_fixed_pct': round(trail_pnl - fixed_pnl, 2),
                'high_water_mark': round(running_high, 4),
                'optimal': trail_pnl > fixed_pnl,
                'triggered_on_bar': i + 1,
            }

    # Trail never triggered
    return {
        'trail_pct': trail_pct,
        'trail_exit_price': None,
        'trail_exit_day': None,
        'trail_pnl_pct': None,
        'fixed_stop': fixed_stop,
        'fixed_pnl_pct': round((fixed_stop - entry_price) / entry_price * 100, 2),
        'gained_vs_fixed_pct': None,
        'high_water_mark': round(running_high, 4),
        'optimal': None,
        'triggered_on_bar': None,
        'note': 'Trail never triggered'
    }


def analyze_trade_trailing_stop(trade_id: int) -> dict:
    """Run trailing stop analysis for one closed trade."""
    conn = get_connection()
    if not conn:
        return {'ok': False, 'error': 'no db connection'}

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, symbol, strategy_id,
                       entry_price, stop_loss as fixed_stop,
                       exit_price, pnl, r_multiple,
                       entry_time::date as entry_date,
                       COALESCE(closed_at, exit_time)::date as exit_date,
                       hold_time_min
                FROM paper_trades
                WHERE id = %s AND status = 'closed'
                  AND entry_price IS NOT NULL
                  AND stop_loss IS NOT NULL
            """, (trade_id,))
            row = cur.fetchone()
            if not row:
                return {'ok': False, 'error': f'trade {trade_id} not found or missing data'}
            cols = [d[0] for d in cur.description]
            trade = dict(zip(cols, row))
    except Exception as e:
        return {'ok': False, 'error': str(e)}

    entry = float(trade['entry_price'])
    fixed_stop = float(trade['fixed_stop'])
    entry_date = str(trade['entry_date']) if trade['entry_date'] else None
    exit_date = str(trade['exit_date']) if trade['exit_date'] else None
    symbol = trade['symbol']

    if not entry_date or not exit_date:
        return {'ok': False, 'error': f'{symbol}: missing entry/exit dates'}

    ohlc = fetch_holding_period_ohlc(symbol, entry_date, exit_date)
    if not ohlc or not ohlc.get('bars'):
        return {'ok': False, 'error': f'no OHLC data for {symbol} ({entry_date} to {exit_date})'}

    bars = ohlc['bars']
    high_water_mark = ohlc['high_water_mark']
    high_water_pct = round((high_water_mark - entry) / entry * 100, 2)
    fixed_pnl_pct = round((fixed_stop - entry) / entry * 100, 2)

    simulations = {}
    for pct in TRAIL_PCTS:
        simulations[pct] = simulate_trailing_stop(entry, bars, pct, fixed_stop)

    # Find optimal trail %
    valid_sims = {
        pct: sim for pct, sim in simulations.items()
        if sim.get('trail_pnl_pct') is not None
    }
    optimal_pct = None
    optimal_pnl = fixed_pnl_pct
    for pct, sim in sorted(valid_sims.items()):
        if sim.get('trail_pnl_pct', fixed_pnl_pct) > optimal_pnl:
            optimal_pnl = sim['trail_pnl_pct']
            optimal_pct = pct

    # Recommendation
    if optimal_pct is None:
        recommendation = 'keep_fixed'
    elif optimal_pct <= 5:
        recommendation = 'use_trail_5pct'
    elif optimal_pct <= 8:
        recommendation = 'use_trail_8pct'
    elif optimal_pct <= 10:
        recommendation = 'use_trail_10pct'
    else:
        recommendation = 'use_trail_15pct'

    # LLM lesson
    lesson = _generate_trail_lesson(trade, simulations, optimal_pct, high_water_pct, recommendation)

    # Write to DB
    s5 = simulations.get(5.0, {})
    s8 = simulations.get(8.0, {})
    s10 = simulations.get(10.0, {})
    s15 = simulations.get(15.0, {})

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trailing_stop_analysis (
                    trade_id, symbol, strategy_id,
                    entry_price, fixed_stop_price, fixed_pnl_pct,
                    high_water_mark, high_water_pct_gain,
                    trail_5pct_exit,  trail_5pct_pnl,  trail_5pct_gain_vs_fixed,
                    trail_8pct_exit,  trail_8pct_pnl,  trail_8pct_gain_vs_fixed,
                    trail_10pct_exit, trail_10pct_pnl, trail_10pct_gain_vs_fixed,
                    trail_15pct_exit, trail_15pct_pnl, trail_15pct_gain_vs_fixed,
                    optimal_trail_pct, optimal_trail_pnl, optimal_trail_exit,
                    recommendation, lesson_text, analyzed_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s,
                    %s,%s,%s, %s,%s,NOW()
                )
                ON CONFLICT (trade_id) DO UPDATE SET
                    high_water_mark=EXCLUDED.high_water_mark,
                    high_water_pct_gain=EXCLUDED.high_water_pct_gain,
                    optimal_trail_pct=EXCLUDED.optimal_trail_pct,
                    optimal_trail_pnl=EXCLUDED.optimal_trail_pnl,
                    optimal_trail_exit=EXCLUDED.optimal_trail_exit,
                    recommendation=EXCLUDED.recommendation,
                    lesson_text=EXCLUDED.lesson_text,
                    analyzed_at=NOW()
            """, (
                trade_id, symbol, trade['strategy_id'],
                entry, fixed_stop, fixed_pnl_pct,
                high_water_mark, high_water_pct,
                s5.get('trail_exit_price'), s5.get('trail_pnl_pct'), s5.get('gained_vs_fixed_pct'),
                s8.get('trail_exit_price'), s8.get('trail_pnl_pct'), s8.get('gained_vs_fixed_pct'),
                s10.get('trail_exit_price'), s10.get('trail_pnl_pct'), s10.get('gained_vs_fixed_pct'),
                s15.get('trail_exit_price'), s15.get('trail_pnl_pct'), s15.get('gained_vs_fixed_pct'),
                optimal_pct, optimal_pnl,
                simulations.get(optimal_pct, {}).get('trail_exit_price') if optimal_pct else None,
                recommendation, lesson,
            ))
            conn.commit()
    except Exception as e:
        conn.rollback()
        return {'ok': False, 'error': f'DB write failed: {e}'}

    return {
        'ok': True,
        'symbol': symbol,
        'strategy': trade['strategy_id'],
        'fixed_pnl_pct': fixed_pnl_pct,
        'high_water_pct': high_water_pct,
        'optimal_trail_pct': optimal_pct,
        'optimal_pnl_pct': optimal_pnl,
        'recommendation': recommendation,
        'gained_vs_fixed': round(optimal_pnl - fixed_pnl_pct, 2) if optimal_pct else 0,
    }


def _generate_trail_lesson(trade, simulations, optimal_pct, high_water_pct, recommendation):
    """Generate a 2-3 sentence lesson about this trade's trailing stop behavior."""
    try:
        import ollama
        s = trade['symbol']
        strat = trade['strategy_id'] or 'unknown'
        fixed_pnl = round((float(trade['fixed_stop']) - float(trade['entry_price'])) /
                          float(trade['entry_price']) * 100, 2)
        best_sim = simulations.get(optimal_pct, {})
        best_pnl = best_sim.get('trail_pnl_pct', fixed_pnl)

        prompt = (
            f"Trade: {s} ({strat})\n"
            f"Entry: ${float(trade['entry_price']):.2f}, Fixed stop: ${float(trade['fixed_stop']):.2f}\n"
            f"Fixed stop P&L: {fixed_pnl:.1f}%\n"
            f"Max unrealized gain during hold: {high_water_pct:.1f}%\n"
            f"Optimal trail: {optimal_pct}% -> P&L {best_pnl:.1f}%\n"
            f"Recommendation: {recommendation}\n\n"
            "In 2-3 sentences: what does this trade teach about stop placement? "
            "Should we use a trailing stop for this strategy, and at what percentage? "
            "No thinking tags, just the lesson."
        )
        resp = ollama.generate(
            model='qwen3:14b',
            prompt=prompt,
            options={'num_predict': 120, 'temperature': 0.3}
        )
        text = resp.get('response', '').strip()
        # Strip thinking tags if present
        import re
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        return text[:500] if text else None
    except Exception as e:
        log.debug(f"LLM lesson failed: {e}")
        return None


def backfill_all_closed_trades():
    """Analyze trailing stops for all closed trades not yet analyzed."""
    conn = get_connection()
    if not conn:
        log.error("No DB connection")
        return []

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pt.id FROM paper_trades pt
                LEFT JOIN trailing_stop_analysis tsa ON tsa.trade_id = pt.id
                WHERE pt.status = 'closed'
                  AND pt.entry_price IS NOT NULL
                  AND pt.stop_loss IS NOT NULL
                  AND tsa.trade_id IS NULL
                ORDER BY pt.closed_at DESC
            """)
            ids = [r[0] for r in cur.fetchall()]
    except Exception as e:
        log.error(f"Query failed: {e}")
        return []

    log.info(f"Analyzing trailing stops for {len(ids)} trades")
    results = []
    for tid in ids:
        result = analyze_trade_trailing_stop(tid)
        results.append(result)
        if result.get('ok'):
            log.info(f"  {result['symbol']}: optimal={result['optimal_trail_pct']}% "
                     f"gain vs fixed={result['gained_vs_fixed']:.1f}%")
        else:
            log.warning(f"  trade {tid}: {result.get('error')}")
        # Rate limit Alpaca
        import time
        time.sleep(0.3)

    return results


def get_strategy_trail_recommendations() -> list:
    """Aggregate trailing stop analysis by strategy."""
    conn = get_connection()
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    strategy_id,
                    COUNT(*) as trades_analyzed,
                    ROUND(AVG(fixed_pnl_pct)::numeric, 2) as avg_fixed_pnl,
                    ROUND(AVG(high_water_pct_gain)::numeric, 2) as avg_high_water,
                    ROUND((AVG(trail_5pct_pnl) FILTER (WHERE trail_5pct_pnl IS NOT NULL))::numeric, 2) as avg_5pct_pnl,
                    ROUND((AVG(trail_8pct_pnl) FILTER (WHERE trail_8pct_pnl IS NOT NULL))::numeric, 2) as avg_8pct_pnl,
                    ROUND((AVG(trail_10pct_pnl) FILTER (WHERE trail_10pct_pnl IS NOT NULL))::numeric, 2) as avg_10pct_pnl,
                    ROUND((AVG(trail_15pct_pnl) FILTER (WHERE trail_15pct_pnl IS NOT NULL))::numeric, 2) as avg_15pct_pnl,
                    ROUND(AVG(optimal_trail_pct)::numeric, 1) as avg_optimal_pct,
                    MODE() WITHIN GROUP (ORDER BY recommendation) as most_common_rec,
                    SUM(CASE WHEN recommendation != 'keep_fixed' THEN 1 ELSE 0 END) as trail_wins,
                    ROUND(AVG(CASE WHEN optimal_trail_pct IS NOT NULL
                             THEN optimal_trail_pnl - fixed_pnl_pct ELSE 0 END)::numeric, 2) as avg_gain_from_trail
                FROM trailing_stop_analysis
                GROUP BY strategy_id
                ORDER BY avg_gain_from_trail DESC
            """)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log.error(f"Recommendations query failed: {e}")
        return []


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    results = backfill_all_closed_trades()
    ok = [r for r in results if r.get('ok')]
    print(f"\nAnalyzed {len(ok)}/{len(results)} trades successfully")
    if ok:
        best = max(ok, key=lambda x: x.get('gained_vs_fixed', 0))
        print(f"Best trail improvement: {best['symbol']} +{best['gained_vs_fixed']:.1f}% "
              f"via {best['optimal_trail_pct']}% trail")

    recs = get_strategy_trail_recommendations()
    if recs:
        print("\nStrategy trailing stop recommendations:")
        for r in recs:
            print(f"  {r['strategy_id']}: {r['most_common_rec']} "
                  f"(avg gain vs fixed: {float(r['avg_gain_from_trail'] or 0):.1f}%)")
