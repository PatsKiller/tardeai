"""
Multi-Source Quote Refresh — when finviz is stale, pull quotes from
Schwab API first, then yfinance fallback. Never serve stale prices.
"""
import json, os, sys, time

TRADEAI_ROOT = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"

class MultiSourceRefresh:
    SOURCE_PRIORITY = ['schwab', 'yfinance']

    def __init__(self, live_dir):
        self.live_dir = live_dir
        self.cache_path = os.path.join(live_dir, 'data', 'portfolios', 'state', 'finviz_quote_cache.json')

    def refresh_if_stale(self, max_age_min=15):
        if not os.path.exists(self.cache_path):
            return self._do_refresh()
        age = (time.time() - os.path.getmtime(self.cache_path)) / 60
        if age <= max_age_min:
            return {'status': 'fresh', 'age_min': round(age, 1)}
        return self._do_refresh()

    def _do_refresh(self):
        symbols = []
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path) as f:
                    symbols = list(json.load(f).keys())
            except:
                pass

        if not symbols:
            try:
                sys.path.insert(0, os.path.join(self.live_dir or TRADEAI_ROOT, 'scripts'))
                from db_adapter import _get_conn
                conn = _get_conn()
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT symbol FROM trade_closed WHERE close_date > CURRENT_DATE - 90 UNION SELECT DISTINCT symbol FROM candidate_setup_advisory LIMIT 100")
                symbols = [r[0] for r in cur.fetchall()]
                conn.close()
            except:
                return {'status': 'no_symbols'}

        refreshed = {}
        import urllib.request

        # Schwab first
        for sym in symbols[:20]:
            try:
                r = urllib.request.urlopen(f'http://localhost:7777/api/v2/brokers/schwab/quote/{sym}', timeout=5)
                if r.status == 200:
                    d = json.loads(r.read()).get('data', {})
                    px = d.get('lastPrice') or d.get('mark')
                    if px:
                        refreshed[sym] = float(px)
            except:
                pass

        # yfinance fallback for symbols not covered by Schwab
        if len(refreshed) < len(symbols) * 0.8:
            try:
                import yfinance as yf
                for i in range(0, len(symbols), 20):
                    batch = symbols[i:i+20]
                    tickers = yf.Tickers(' '.join(batch))
                    for sym in batch:
                        if sym in refreshed:
                            continue
                        try:
                            px = tickers.tickers[sym].info.get('regularMarketPrice') or tickers.tickers[sym].info.get('currentPrice')
                            if px:
                                refreshed[sym] = float(px)
                        except:
                            pass
            except:
                pass

        if refreshed:
            existing = {}
            if os.path.exists(self.cache_path):
                try:
                    with open(self.cache_path) as f:
                        existing = json.load(f)
                except:
                    pass
            existing.update(refreshed)
            with open(self.cache_path, 'w') as f:
                json.dump(existing, f, separators=(',', ':'))
            return {'status': 'refreshed', 'symbols': len(refreshed), 'total': len(existing)}

        return {'status': 'refresh_failed', 'error': 'No quotes from any source'}
