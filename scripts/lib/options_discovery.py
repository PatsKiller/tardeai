"""Broad optionable-US membership via the governed Finviz HTTP path.

No price/liquidity filter silently removes a watched or held security. This is
membership discovery only, not research, a recommendation or execution approval.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse


class ScreenerPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.symbols = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        href = dict(attrs).get('href', '')
        parsed = urlparse(href)
        if not parsed.path.endswith('quote.ashx'):
            return
        symbol = (parse_qs(parsed.query).get('t') or [''])[0].upper()
        if re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}', symbol) and symbol not in self.symbols:
            self.symbols.append(symbol)

    def handle_data(self, value):
        self.text.append(value)

    def result(self):
        text = ' '.join(self.text)
        match = re.search(r'Total:\s*([\d,]+)', text, re.I) or re.search(r'#?\d+\s*/\s*([\d,]+)\s+Total', text, re.I)
        return {'symbols': self.symbols, 'total': int(match[1].replace(',', '')) if match else None}


def discover(fetch_page, *, max_pages: int = 1000) -> dict:
    """Require declared total and pagination exhaustion; errors retain partial history."""
    symbols = []
    seen = set()
    total = None
    status, reason = 'PARTIAL', 'page budget exhausted'
    pages = 0
    for page in range(max_pages):
        try:
            result = fetch_page(len(symbols) + 1)
        except Exception as exc:
            reason = type(exc).__name__  # no credential-bearing HTTP text
            break
        pages += 1
        count = result.get('total')
        if count is None or (total is not None and count != total):
            reason = 'missing or changing source total'
            for sym in result.get('symbols', []):
                if sym not in seen:
                    symbols.append(sym)
                    seen.add(sym)
            break
        total = count
        incoming = [s for s in result.get('symbols', []) if s not in seen]
        symbols.extend(incoming)
        seen.update(incoming)
        if len(seen) == total:
            status, reason = 'COMPLETE', None
            break
        if not incoming or len(seen) > total:
            reason = 'pagination repeated, truncated or inconsistent'
            break
    return {'status': status, 'reason': reason, 'source': 'finviz', 'as_of': datetime.now(timezone.utc).isoformat(), 'scope': 'US-listed optionable stocks/ETFs',
            'filters': ['sh_opt_option'], 'declared_total': total, 'count': len(symbols), 'pages': pages,
            'rows': [{'symbol': s, 'source': 'market_discovery', 'source_lanes': ['market_discovery'],
                      'research_status': 'research_required', 'optionable': True} for s in symbols]}


def fetch_discovery(*, max_pages: int = 1000) -> dict:
    """Worker-only provider access, cookie then token; never bypass a 429 cooldown."""
    from finviz_http import finviz_get
    from finviz_auth import finviz_secret, with_auth_token
    from lib.finviz_csv import parse_export

    cookie = finviz_secret('FINVIZ_COOKIE')
    headers = {'User-Agent': 'Mozilla/5.0'}
    if cookie:
        headers['Cookie'] = cookie

    def fetch_page(offset):
        response = finviz_get('https://elite.finviz.com/screener.ashx', headers=headers,
                              params={'v': '111', 'f': 'sh_opt_option', 'r': offset}, timeout=30)
        response.raise_for_status()
        parser = ScreenerPage()
        parser.feed(response.text)
        return parser.result()
    result = discover(fetch_page, max_pages=max_pages)
    result['transport'] = 'cookie_html' if cookie else 'public_html'
    if result['status'] == 'COMPLETE' or result.get('reason') == 'FinvizRateLimited':
        return result
    token = finviz_secret('FINVIZ_API_TOKEN')
    if not token:
        return result
    try:
        response = finviz_get(with_auth_token(
            'https://elite.finviz.com/export?v=111&f=sh_opt_option', token),
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        response.raise_for_status()
        symbols = sorted({r['Ticker'].upper() for r in parse_export(response.text, required=['Ticker'])
                          if r.get('Ticker')})
        # A successful export alone is not proof of an exhausted source universe.
        total = result.get('declared_total')
        fallback = discover(lambda offset: {'symbols': symbols, 'total': total}, max_pages=1)
        fallback['transport'] = 'token_export'
        fallback['previous_attempt'] = {k: result.get(k) for k in ('status', 'reason', 'count', 'pages')}
        return fallback
    except Exception as exc:
        result['fallback_error'] = type(exc).__name__
        return result
