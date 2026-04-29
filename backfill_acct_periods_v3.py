"""
backfill_acct_periods_v3.py
Computes per-account period returns using CURRENT holdings x historical prices.
Skips CASH and money market positions which have bad price cache data.
For unpriced symbols, uses current market_value as approximation.
Run from project root with venv active.
"""
import json
from pathlib import Path
from datetime import date, timedelta

state_dir = Path('data/portfolios/state')
ph_path = state_dir / 'performance_history.json'
ph = json.loads(ph_path.read_text())
portfolio = json.loads((state_dir / 'holdings.json').read_text())
price_cache = json.loads((state_dir / 'price_cache.json').read_text())
current_holdings = portfolio.get('holdings', [])
account_summaries = portfolio.get('account_summaries', {})

ACCOUNTS = {
    'fidelity_401k': 'Fidelity 401k',
    'schwab_rollover_ira': 'Rollover IRA',
    'schwab_roth': 'Roth IRA',
    'schwab_taxable': 'Taxable',
}

FIDELITY_MAP = {
    'FID-CONTRA-F': 'FCNTX', 'SP500-D': 'FXAIX', 'SS-SMMD': 'SLYG',
    'TRP-LVAL': 'TILCX', 'VANG-FTSE-SOC': 'VFTNX', 'AB-DISC-Z': 'ABSZX',
    'SS-INTL-IDX': 'SWISX', 'PGIM-HIYD-Z': 'PHYZX', 'JHN-DISC-I': 'JDVAX',
    'TRW-STBL-VAL': 'TRSVX',
}

# Skip these in historical repricing — cash/money market have bad price history
SKIP_SYMBOLS = frozenset(['CASH', 'SNSXX', 'SWVXX', 'SPRXX', 'VMFXX', 
                           'VMMXX', 'FDRXX', 'FCASH', '--'])

def get_price(symbol, date_str):
    """Get price for a symbol on a date.

    Source priority:
    1. PostgreSQL ticker_prices table (canonical source of truth)
    2. JSON price_cache.json (fallback if DB unavailable)

    For Fidelity proprietary funds, maps to public ticker and applies scale factor.
    """
    mapped = FIDELITY_MAP.get(symbol, symbol)
    if mapped in SKIP_SYMBOLS:
        return None

    # Try DB first (source of truth)
    raw_price = None
    try:
        from price_db_sync import get_price_from_db
        raw_price = get_price_from_db(mapped, date_str)
    except Exception:
        pass  # DB unavailable, fall through to JSON

    # Fallback to JSON cache
    if raw_price is None:
        prices = price_cache.get(mapped, {})
        if date_str in prices:
            raw_price = prices[date_str]
        else:
            target = date.fromisoformat(date_str)
            for delta in range(1, 6):
                for d in [target - timedelta(days=delta), target + timedelta(days=delta)]:
                    p = prices.get(d.isoformat())
                    if p:
                        raw_price = p
                        break
                if raw_price:
                    break

    if raw_price is None:
        return None

    # For Fidelity proprietary symbols, apply scale factor
    # Scale = current_fidelity_price / current_public_price
    if symbol != mapped and symbol in FIDELITY_MAP:
        fid_holding = next((h for h in current_holdings if h.get('symbol') == symbol), None)
        if fid_holding:
            fid_price = fid_holding.get('price', 0)
            # Get latest public price for ratio
            try:
                from price_db_sync import get_latest_price_from_db
                latest_pub = get_latest_price_from_db(mapped)
            except Exception:
                prices = price_cache.get(mapped, {})
                latest_dates = sorted(prices.keys()) if prices else []
                latest_pub = prices[latest_dates[-1]] if latest_dates else 0
            if latest_pub and latest_pub > 0 and fid_price > 0:
                scale = fid_price / latest_pub
                return raw_price * scale

    return raw_price

def compute_account_value_at_historical(acct_key, target_date_str):
    """
    Value account at historical date using CURRENT shares x historical prices.
    Cash positions use current market_value as approximation (stable).
    Proprietary Fidelity symbols use mapped ticker prices.
    """
    acct_holdings = [h for h in current_holdings if h.get('account') == acct_key]
    total = 0.0
    priced = 0
    cash_total = 0.0

    for h in acct_holdings:
        sym = h.get('symbol', '')
        shares = h.get('shares', h.get('quantity', 0)) or 0
        mv = h.get('market_value', 0) or 0

        # Cash/money market — use current value as approximation
        if sym in SKIP_SYMBOLS or sym == 'CASH':
            cash_total += mv
            continue

        # For symbols with no price cache at all, use current MV as approximation
        mapped_sym = FIDELITY_MAP.get(sym, sym)
        if mapped_sym not in price_cache or len(price_cache.get(mapped_sym, {})) == 0:
            cash_total += mv  # treat as stable value
            continue

        if shares <= 0:
            continue

        price = get_price(sym, target_date_str)
        if price:
            total += shares * price
            priced += 1

    return round(total + cash_total, 2) if (priced > 0 or cash_total > 0) else None

periods = ph.get('periods', {})
acct_periods = ph.get('accounts', {})

for acct_key, acct_label in ACCOUNTS.items():
    current_val = account_summaries.get(acct_key, {}).get('total_value', 0)
    if not current_val:
        continue
    if acct_key not in acct_periods:
        acct_periods[acct_key] = {'label': acct_label, 'current_value': round(current_val,2), 'periods': {}}
    acct_periods[acct_key]['current_value'] = round(current_val, 2)

    for pk, pd_data in periods.items():
        existing = acct_periods[acct_key]['periods'].get(pk)
        if existing and existing.get('source') == 'snapshot':
            continue
        start_date = pd_data.get('start_date')
        if not start_date:
            continue
        print(f"  {acct_label} {pk} ({start_date})...", end=' ', flush=True)
        start_val = compute_account_value_at_historical(acct_key, start_date)
        if not start_val:
            print("no data")
            acct_periods[acct_key]['periods'][pk] = None
            continue
        change = current_val - start_val
        change_pct = round((change / start_val) * 100, 2)
        acct_periods[acct_key]['periods'][pk] = {
            'period': pk,
            'start_date': start_date,
            'start_value': round(start_val, 2),
            'end_value': round(current_val, 2),
            'change': round(change, 2),
            'change_pct': change_pct,
            'source': 'repriced',
        }
        print(f"{change_pct:+.2f}% (start ${start_val:,.0f})")

ph['accounts'] = acct_periods
ph_path.write_text(json.dumps(ph, indent=2))
print("\nDone:")
for acct_key, data in acct_periods.items():
    avail = sum(1 for p in data['periods'].values() if p)
    print(f"  {data['label']}: {avail}/7 periods")
