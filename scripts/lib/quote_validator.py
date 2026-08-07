"""
Quote Validator — cross-references quotes from multiple sources
and identifies pricing discrepancies that cause P&L errors.
"""
import json, os, sys, time, subprocess
from pathlib import Path

TRADEAI_ROOT = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"

class QuoteValidator:
    TOLERANCE_PCT = 2.0
    SPOT_CHECK_COUNT = 10

    def __init__(self, live_dir=None):
        self.live_dir = live_dir or TRADEAI_ROOT
        self.findings = []

    def resolve_cache_path(self):
        path = os.path.join(self.live_dir, 'data', 'portfolios', 'state', 'finviz_quote_cache.json')
        return path if os.path.exists(path) else None

    def get_cached_quotes(self):
        path = self.resolve_cache_path()
        if not path:
            return {}
        with open(path) as f:
            return json.load(f)

    def _call_script(self, code, timeout=15):
        try:
            result = subprocess.run(
                [sys.executable, '-c', code],
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ, 'PYTHONPATH': os.path.join(TRADEAI_ROOT, 'scripts')}
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except:
            return None

    def get_schwab_quotes(self, symbols):
        """Get quotes from Schwab API via localhost."""
        quotes = {}
        syms = symbols[:10]
        if not syms:
            return quotes

        for sym in syms:
            try:
                code = f"""
import urllib.request, json
try:
    r = urllib.request.urlopen('http://localhost:7777/api/v2/brokers/schwab/quote/{sym}', timeout=5)
    d = json.loads(r.read()).get('data', {{}})
    px = d.get('lastPrice') or d.get('last_price') or d.get('mark')
    print(json.dumps({{'{sym}': px}}) if px else '')
except:
    pass
"""
                out = self._call_script(code)
                if out:
                    merged = json.loads(out)
                    quotes.update(merged)
            except:
                pass
        return quotes

    def get_yfinance_quotes(self, symbols):
        quotes = {}
        try:
            for i in range(0, len(symbols), 10):
                batch = symbols[i:i+10]
                sym_str = ' '.join(batch)
                code = f"""
import yfinance as yf, json
tickers = yf.Tickers('{sym_str}')
out = {{}}
for sym in {json.dumps(batch)}:
    try:
        info = tickers.tickers[sym].info
        px = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')
        if px:
            out[sym] = float(px)
    except:
        pass
print(json.dumps(out))
"""
                out = self._call_script(code)
                if out:
                    quotes.update(json.loads(out))
        except:
            pass
        return quotes

    def validate_all(self, symbols=None):
        cached = self.get_cached_quotes()
        if not cached:
            self.findings.append({
                'severity': 'P0', 'type': 'quote_cache_missing',
                'message': 'No finviz quote cache found — P&L based on stale/missing prices',
                'live_dir': self.live_dir
            })
            return self.findings

        cache_path = self.resolve_cache_path()
        if cache_path:
            age_min = (time.time() - os.path.getmtime(cache_path)) / 60
            if age_min > 30:
                self.findings.append({
                    'severity': 'P1', 'type': 'quote_cache_stale',
                    'message': f'Quote cache is {age_min:.0f}min old',
                    'age_minutes': round(age_min), 'path': cache_path
                })

        if symbols is None:
            symbols = list(cached.keys())
        import random
        spot = random.sample(symbols, min(self.SPOT_CHECK_COUNT, len(symbols))) if symbols else []
        check = symbols if len(symbols) <= 50 else spot

        schwab_quotes = self.get_schwab_quotes(check)
        yf_quotes = self.get_yfinance_quotes(check)

        for sym in check:
            cached_px = cached.get(sym)
            if not cached_px:
                continue
            if isinstance(cached_px, dict):
                cached_px = cached_px.get('price', cached_px.get('last', 0))
            cached_px = float(cached_px)

            schwab_px = schwab_quotes.get(sym)
            if schwab_px and cached_px > 0:
                diff = abs(cached_px - schwab_px) / cached_px * 100
                if diff > self.TOLERANCE_PCT:
                    self.findings.append({
                        'severity': 'P1' if diff > 5 else 'P2',
                        'type': 'price_mismatch_schwab', 'symbol': sym,
                        'cached_price': round(cached_px, 4),
                        'schwab_price': round(schwab_px, 4),
                        'diff_pct': round(diff, 2),
                        'message': f'{sym}: cached ${cached_px} vs Schwab ${schwab_px} ({diff:.1f}% diff)'
                    })

            yf_px = yf_quotes.get(sym)
            if yf_px and cached_px > 0:
                diff = abs(cached_px - yf_px) / cached_px * 100
                if diff > self.TOLERANCE_PCT:
                    self.findings.append({
                        'severity': 'P1' if diff > 5 else 'P2',
                        'type': 'price_mismatch_yfinance', 'symbol': sym,
                        'cached_price': round(cached_px, 4),
                        'yfinance_price': round(yf_px, 4),
                        'diff_pct': round(diff, 2),
                        'message': f'{sym}: cached ${cached_px} vs yfinance ${yf_px} ({diff:.1f}% diff)'
                    })

        # Check live cache vs dev cache staleness
        dev_path = os.path.join(TRADEAI_ROOT, 'data', 'portfolios', 'state', 'finviz_quote_cache.json')
        if cache_path and cache_path != dev_path and os.path.exists(dev_path):
            live_age = (time.time() - os.path.getmtime(cache_path)) / 60
            dev_age = (time.time() - os.path.getmtime(dev_path)) / 60
            if live_age > dev_age + 10:
                self.findings.append({
                    'severity': 'P1', 'type': 'live_cache_behind_dev',
                    'message': f'Live cache ({live_age:.0f}min) behind dev ({dev_age:.0f}min)'
                })

        return self.findings
