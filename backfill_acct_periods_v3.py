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
    sym = FIDELITY_MAP.get(symbol, symbol)
    if sym in SKIP_SYMBOLS:
        return None
    prices = price_cache.get(sym, {})
    if date_str in prices:
        return prices[date_str]
    target = date.fromisoformat(date_str)
    for delta in range(1, 6):
        for d in [target - timedelta(days=delta), target + timedelta(days=delta)]:
            p = prices.get(d.isoformat())
            if p:
                return p
    return None

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

        # Proprietary Fidelity symbols — skip (no clean price history)
        if '-' in sym and len(sym) > 5:
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
