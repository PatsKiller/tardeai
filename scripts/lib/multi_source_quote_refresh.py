"""
Multi-Source Quote Refresh — when the local Finviz cache is stale, ask the
Schwab quote route, then fill gaps from that same Finviz cache. CUSIP-like
symbols are not quoted. No other network quote library (LQ-20261107-1418).
"""
try:  # cc_auth (2026-10-14): service token for loopback Command Center (:7777) calls
    from lib.cc_client import cc_urlopen as _cc_urlopen
except ImportError:  # pragma: no cover - scripts/ not on sys.path
    import sys as _cc_sys
    from pathlib import Path as _CcPath
    _cc_sys.path.insert(0, str(next(p for p in _CcPath(__file__).resolve().parents if p.name == "scripts")))
    from lib.cc_client import cc_urlopen as _cc_urlopen

import json, os, sys, time

TRADEAI_ROOT = "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"

def _is_cusip_like(sym):
    try:
        from lib.dead_cusip_holdings import is_cusip_like
    except ImportError:
        sys.path.insert(0, os.path.join(TRADEAI_ROOT, 'scripts'))
        from lib.dead_cusip_holdings import is_cusip_like
    return bool(is_cusip_like(str(sym or '')))


class MultiSourceRefresh:
    SOURCE_PRIORITY = ['schwab', 'finviz']

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
        cache_read_error = None
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path) as f:
                    symbols = list(json.load(f).keys())
            except (OSError, ValueError) as exc:
                cache_read_error = type(exc).__name__
                symbols = []

        if not symbols:
            try:
                sys.path.insert(0, os.path.join(self.live_dir or TRADEAI_ROOT, 'scripts'))
                from db_adapter import _get_conn
                conn = _get_conn()
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT symbol FROM trade_closed WHERE close_date > CURRENT_DATE - 90 UNION SELECT DISTINCT symbol FROM candidate_setup_advisory LIMIT 100")
                symbols = [r[0] for r in cur.fetchall()]
                conn.close()
            except Exception as exc:
                return {'status': 'no_symbols', 'error': type(exc).__name__}

        symbols = [s for s in symbols if s and not _is_cusip_like(s)]
        if not symbols:
            return {'status': 'no_symbols'}

        refreshed = {}
        quote_errors = []

        # Schwab first. CUSIP-like symbols are already gone. A failed quote is recorded, not hidden.
        for sym in symbols[:20]:
            try:
                r = _cc_urlopen(f'http://localhost:7777/api/v2/brokers/schwab/quote/{sym}', timeout=5)
                if r.status == 200:
                    d = json.loads(r.read()).get('data', {})
                    px = d.get('lastPrice') or d.get('mark')
                    if px:
                        refreshed[sym] = float(px)
                    else:
                        quote_errors.append(f"{sym}:no_price")
                else:
                    quote_errors.append(f"{sym}:http_{r.status}")
            except Exception as exc:
                quote_errors.append(f"{sym}:{type(exc).__name__}")

        # Local Finviz cache for symbols Schwab did not price. No network.
        finviz_error = None
        try:
            from pathlib import Path
            try:
                from lib.portfolio_positions import finviz_cache
            except ImportError:
                sys.path.insert(0, os.path.join(self.live_dir or TRADEAI_ROOT, 'scripts'))
                from lib.portfolio_positions import finviz_cache
            cached = finviz_cache(Path(self.cache_path))
            for sym in symbols:
                if sym in refreshed:
                    continue
                row = cached.get(str(sym).upper()) if isinstance(cached, dict) else None
                px = row.get('price') if isinstance(row, dict) else None
                if px:
                    refreshed[sym] = float(px)
        except Exception as exc:
            finviz_error = type(exc).__name__

        notes = {}
        if cache_read_error:
            notes['cache_read_error'] = cache_read_error
        if quote_errors:
            notes['quote_errors'] = quote_errors
        if finviz_error:
            notes['finviz_error'] = finviz_error

        if refreshed:
            existing = {}
            if os.path.exists(self.cache_path):
                try:
                    with open(self.cache_path) as f:
                        existing = json.load(f)
                except (OSError, ValueError) as exc:
                    notes['cache_merge_error'] = type(exc).__name__
                    existing = {}
            existing.update({sym: refreshed[sym] for sym in refreshed})
            tmp_name = self.cache_path + '.tmp'
            try:
                with open(tmp_name, 'w') as f:
                    json.dump(existing, f, separators=(',', ':'))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, self.cache_path)
            except OSError as exc:
                notes['cache_write_error'] = type(exc).__name__
                return {'status': 'refresh_failed', 'error': 'cache write failed', **notes}
            return {'status': 'refreshed', 'symbols': len(refreshed), 'total': len(existing), **notes}

        return {'status': 'refresh_failed', 'error': 'No quotes from any source', **notes}
