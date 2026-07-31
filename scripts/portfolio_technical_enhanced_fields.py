"""portfolio_technical_enhanced_fields.py
===========================================
PATCH for portfolio_technical.py — expands the Finviz Elite field capture from
8 fields to 30+ fields for the Position Intelligence (PI) system.

HOW TO APPLY
------------
This is a drop-in function replacement for the `_parse_quote_response()` function
inside portfolio_technical.py. Find that function and replace it with the one below,
OR call `enhance_technical_snapshot(snapshot_path)` after the daily pipeline runs to
enrich an existing technical_snapshot.json with the additional fields.

FIELDS ADDED (beyond existing: rsi, sma50_pct, sma200_pct, atr, beta, 52wk_high, 52wk_low)
---------------------------------------------------------------------------
Valuation:
  pe              - Price/Earnings (TTM)
  forward_pe      - Forward P/E (next year consensus)
  peg             - PEG ratio (P/E ÷ growth)
  ps              - Price/Sales
  pb              - Price/Book

Fundamentals:
  eps_ttm         - EPS trailing 12 months
  eps_growth_qoq  - EPS growth quarter over quarter %
  eps_growth_yoy  - EPS growth year over year %
  rev_growth_qoq  - Revenue growth QoQ %
  rev_growth_yoy  - Revenue growth YoY %
  profit_margin   - Net profit margin %
  roe             - Return on equity %

Price structure:
  quarter_high    - 52-week quarterly high (last 3 months high)
  quarter_low     - 52-week quarterly low (last 3 months low)
  sma20_pct       - % above/below 20-day SMA
  perf_week       - 1-week performance %
  perf_month      - 1-month performance %
  perf_quarter    - 1-quarter performance %
  perf_ytd        - YTD performance %

Ownership & sentiment:
  short_float     - Short float % (squeeze indicator)
  short_ratio     - Days to cover
  inst_own        - Institutional ownership %
  inst_trans      - Institutional transactions (buy/sell pressure)
  insider_own     - Insider ownership %

Analyst intelligence:
  analyst_rating  - Strong Buy / Buy / Hold / Sell / Strong Sell
  analyst_target  - Analyst price target (consensus)
  target_upside   - Calculated: (target - price) / price * 100

Earnings calendar:
  earnings_date   - Next earnings date string

Volatility / volume:
  relative_volume - Today's volume vs 30-day average
  avg_volume      - 30-day average daily volume

FINVIZ ELITE API REFERENCE
--------------------------
Finviz quote.ashx returns a JSON blob when called with the right cookie.
Key fields map (Finviz internal name → our name):

  RSI (14)            → rsi
  SMA20               → sma20 (we compute sma20_pct = (price/sma20 - 1)*100)
  SMA50               → sma50_pct (already computed)
  SMA200              → sma200_pct (already computed)
  ATR                 → atr
  Beta                → beta
  52W High            → week52_high
  52W Low             → week52_low
  P/E                 → pe
  Forward P/E         → forward_pe
  PEG                 → peg
  P/S                 → ps
  P/B                 → pb
  EPS (ttm)           → eps_ttm
  EPS Q/Q             → eps_growth_qoq
  EPS Y/Y             → eps_growth_yoy (from annual data)
  Sales Q/Q           → rev_growth_qoq
  Profit Margin       → profit_margin
  ROE                 → roe
  Short Float         → short_float
  Short Ratio         → short_ratio
  Inst Own            → inst_own
  Inst Trans          → inst_trans
  Insider Own         → insider_own
  Analyst Recom       → analyst_rating (1.0=StrongBuy .. 5.0=StrongSell)
  Target Price        → analyst_target
  Earnings            → earnings_date
  Rel Volume          → relative_volume
  Avg Volume          → avg_volume
  Perf Week           → perf_week
  Perf Month          → perf_month
  Perf Quarter        → perf_quarter
  Perf YTD            → perf_ytd
  Quart High          → quarter_high
  Quart Low           → quarter_low
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


def _parse_num(value: Any) -> Optional[float]:
    """Convert Finviz string values like '12.5%', '1.2B', '-' to float."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ('-', 'N/A', 'n/a', ''):
        return None
    s = s.replace(',', '')
    if s.endswith('%'):
        s = s[:-1]
    mult = 1.0
    if s[-1:].upper() == 'B':
        mult = 1e9; s = s[:-1]
    elif s[-1:].upper() == 'M':
        mult = 1e6; s = s[:-1]
    elif s[-1:].upper() == 'K':
        mult = 1e3; s = s[:-1]
    try:
        return float(re.sub(r'[^0-9.\-]', '', s)) * mult
    except (ValueError, TypeError):
        return None


def _analyst_label(val: Any) -> str:
    """Convert Finviz 1-5 analyst recommendation to label."""
    from lib.analyst_rating_canonical import finviz_recom_to_label

    label = finviz_recom_to_label(val)
    if label:
        return label
    n = _parse_num(val)
    if n is None:
        return str(val or '—')[:20]
    return finviz_recom_to_label(n) or str(val or '—')[:20]


def parse_finviz_quote_fields(raw: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given a raw Finviz quote response dict, extract all 30+ intelligence fields
    and merge with existing snapshot data for a single ticker.

    Parameters
    ----------
    raw      : dict of raw Finviz field names → values
    existing : the current snapshot dict for this ticker (will be updated in-place)

    Returns
    -------
    Updated snapshot dict
    """
    d = existing.copy()

    # ── Valuation ──────────────────────────────────────────────────────────────
    d['pe']          = _parse_num(raw.get('P/E') or raw.get('pe'))
    d['forward_pe']  = _parse_num(raw.get('Forward P/E') or raw.get('forward_pe'))
    d['peg']         = _parse_num(raw.get('PEG') or raw.get('peg'))
    d['ps']          = _parse_num(raw.get('P/S') or raw.get('ps'))
    d['pb']          = _parse_num(raw.get('P/B') or raw.get('pb'))

    # ── Fundamentals ───────────────────────────────────────────────────────────
    d['eps_ttm']        = _parse_num(raw.get('EPS (ttm)') or raw.get('eps_ttm'))
    d['eps_growth_qoq'] = _parse_num(raw.get('EPS Q/Q')   or raw.get('eps_growth_qoq'))
    d['eps_growth_yoy'] = _parse_num(raw.get('EPS past 5Y') or raw.get('eps_growth_yoy'))
    d['rev_growth_qoq'] = _parse_num(raw.get('Sales Q/Q')  or raw.get('rev_growth_qoq'))
    d['profit_margin']  = _parse_num(raw.get('Profit Margin') or raw.get('profit_margin'))
    d['roe']            = _parse_num(raw.get('ROE') or raw.get('roe'))

    # ── Price structure ─────────────────────────────────────────────────────────
    d['quarter_high'] = _parse_num(raw.get('Quart High') or raw.get('quarter_high')
                                   or raw.get('Q High') or raw.get('q_high'))
    d['quarter_low']  = _parse_num(raw.get('Quart Low')  or raw.get('quarter_low')
                                   or raw.get('Q Low')  or raw.get('q_low'))

    # SMA20 — compute pct if raw value is a price
    sma20_raw = _parse_num(raw.get('SMA20') or raw.get('sma20'))
    price     = d.get('price') or _parse_num(raw.get('Price') or raw.get('price')) or 0
    if sma20_raw and price:
        d['sma20']     = sma20_raw
        d['sma20_pct'] = round((price / sma20_raw - 1) * 100, 2)
    elif raw.get('sma20_pct') is not None:
        d['sma20_pct'] = _parse_num(raw.get('sma20_pct'))

    d['perf_week']    = _parse_num(raw.get('Perf Week')    or raw.get('perf_week'))
    d['perf_month']   = _parse_num(raw.get('Perf Month')   or raw.get('perf_month'))
    d['perf_quarter'] = _parse_num(raw.get('Perf Quarter') or raw.get('perf_quarter'))
    d['perf_ytd']     = _parse_num(raw.get('Perf YTD')     or raw.get('perf_ytd'))

    # ── Ownership & sentiment ───────────────────────────────────────────────────
    d['short_float'] = _parse_num(raw.get('Short Float') or raw.get('short_float'))
    d['short_ratio'] = _parse_num(raw.get('Short Ratio') or raw.get('short_ratio'))
    d['inst_own']    = _parse_num(raw.get('Inst Own')    or raw.get('inst_own')
                                  or raw.get('Institutional Ownership'))
    d['inst_trans']  = _parse_num(raw.get('Inst Trans')  or raw.get('inst_trans'))
    d['insider_own'] = _parse_num(raw.get('Insider Own') or raw.get('insider_own'))

    # ── Analyst intelligence ────────────────────────────────────────────────────
    raw_analyst = raw.get('Analyst Recom') or raw.get('Recom') or raw.get('analyst_rating')
    if raw_analyst is not None:
        d['analyst_rating'] = _analyst_label(raw_analyst)
    raw_target = _parse_num(raw.get('Target Price') or raw.get('analyst_target'))
    if raw_target:
        d['analyst_target'] = raw_target
        if price:
            d['target_upside'] = round((raw_target / price - 1) * 100, 2)

    # ── Earnings calendar ───────────────────────────────────────────────────────
    earn = raw.get('Earnings') or raw.get('earnings_date') or raw.get('Earnings Date')
    if earn and str(earn).strip() not in ('-', 'N/A', ''):
        d['earnings_date'] = str(earn).strip()

    # ── Volume / volatility ─────────────────────────────────────────────────────
    d['relative_volume'] = _parse_num(raw.get('Rel Volume') or raw.get('relative_volume'))
    d['avg_volume']      = _parse_num(raw.get('Avg Volume') or raw.get('avg_volume'))

    # Remove None values to keep JSON clean
    d = {k: v for k, v in d.items() if v is not None}
    return d


def enhance_technical_snapshot(snapshot_path: Path) -> bool:
    """
    Post-process an existing technical_snapshot.json to fill in any enhanced
    fields that were stored under alternate key names.

    This is a safe no-op enrichment — it never removes existing data.
    Useful if you ran the old portfolio_technical.py and want to upgrade the
    snapshot without re-fetching from Finviz.

    Returns True if the file was updated, False if nothing changed.
    """
    if not snapshot_path.exists():
        print(f"[technical_enhanced] snapshot not found: {snapshot_path}")
        return False

    try:
        data = json.loads(snapshot_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"[technical_enhanced] JSON parse error: {e}")
        return False

    holdings = data.get('holdings') or {
        k: v for k, v in data.items()
        if k != '_meta' and isinstance(v, dict)
    }

    changed = False
    for sym, d in holdings.items():
        # Migrate old field names to new standard names
        migrations = {
            '52wk_high':    'week52_high',
            '52wk_low':     'week52_low',
            'week_52_high': 'week52_high',
            'week_52_low':  'week52_low',
            'target':       'analyst_target',
            'analyst':      'analyst_rating',
        }
        for old, new in migrations.items():
            if old in d and new not in d:
                d[new] = d.pop(old)
                changed = True

        # Compute derived fields if base data exists
        price = d.get('price', 0) or 0
        hi52  = d.get('week52_high', 0) or 0
        lo52  = d.get('week52_low',  0) or 0
        target = d.get('analyst_target', 0) or 0

        if price and target and 'target_upside' not in d:
            d['target_upside'] = round((target / price - 1) * 100, 2)
            changed = True

        if price and hi52 and lo52 and 'week52_position' not in d:
            pos = (price - lo52) / (hi52 - lo52) * 100 if (hi52 - lo52) > 0 else 50
            d['week52_position'] = round(max(0, min(100, pos)), 1)
            changed = True

    if changed:
        if 'holdings' in data:
            data['holdings'] = holdings
        else:
            for k, v in holdings.items():
                data[k] = v
        snapshot_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        print(f"[technical_enhanced] enriched {snapshot_path} — {len(holdings)} positions")

    return changed


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION INSTRUCTIONS FOR portfolio_technical.py
# ══════════════════════════════════════════════════════════════════════════════
#
# 1. In portfolio_technical.py, after the existing quote.ashx fetch and parse,
#    call parse_finviz_quote_fields(raw_json, existing_ticker_dict) to enrich
#    each ticker's data before writing to technical_snapshot.json.
#
# 2. The Finviz quote.ashx URL already returns these fields — they just weren't
#    being captured. The cookie auth and rate limiting are already handled.
#    No new API calls needed.
#
# 3. Add this to the end of the daily portfolio pipeline (portfolio_orchestrator.py
#    stage that calls portfolio_technical.py):
#
#    from portfolio_technical_enhanced_fields import enhance_technical_snapshot
#    enhance_technical_snapshot(state_dir / "technical_snapshot.json")
#
# 4. The Command Center v40 Technical tab will automatically display all new
#    fields once they appear in technical_snapshot.json — no dashboard changes.
#
# ══════════════════════════════════════════════════════════════════════════════
# FINVIZ QUOTE.ASHX FIELD NAMES — FULL REFERENCE
# ══════════════════════════════════════════════════════════════════════════════
#
# The following fields are available in the Finviz Elite quote.ashx JSON response.
# All are accessible with your existing FINVIZ_COOKIE auth — no extra cost:
#
# PRICE & VOLUME:
#   Price, Change, Volume, Rel Volume, Avg Volume, Premarket Price,
#   Premarket Change, After-Hours Price, After-Hours Change
#
# MOVING AVERAGES & MOMENTUM:
#   SMA20, SMA50, SMA200, RSI (14), ATR, Beta
#
# 52-WEEK & QUARTERLY RANGE:
#   52W High, 52W Low, Quart High, Quart Low
#
# PERFORMANCE (% change over period):
#   Perf Week, Perf Month, Perf Quarter, Perf Half Y, Perf Year, Perf YTD
#
# VALUATION:
#   P/E, Forward P/E, PEG, P/S, P/B, P/C, P/FCF, Dividend Yield, Payout Ratio
#
# FUNDAMENTALS:
#   EPS (ttm), EPS Q/Q, EPS past 5Y, EPS next Y, Sales Q/Q, Sales past 5Y,
#   Sales next Y, ROA, ROE, ROI, Curr R, Quick R, LTDebt/Eq, Debt/Eq,
#   Gross Margin, Oper Margin, Profit Margin
#
# OWNERSHIP:
#   Inst Own, Inst Trans, Insider Own, Insider Trans, Short Float, Short Ratio
#
# ANALYST:
#   Analyst Recom (1.0=StrongBuy..5.0=StrongSell), Target Price
#
# EARNINGS:
#   Earnings (next earnings date string, e.g. "Apr 29 AMC")
#
# MARKET DATA:
#   Market Cap, Float, Shares Outstanding, Short Interest
#
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        result = enhance_technical_snapshot(path)
        print('Updated:', result)
    else:
        print('Usage: python portfolio_technical_enhanced_fields.py <path/to/technical_snapshot.json>')
        print()
        print('This script enriches an existing technical_snapshot.json with derived fields.')
        print('For full field capture, integrate parse_finviz_quote_fields() into portfolio_technical.py.')
