"""
portfolio_loader.py — v3.0 (April 10, 2026)

Architecture:
  - holdings.json is the SINGLE SOURCE OF TRUTH for share counts
  - Pipeline reads holdings.json, reprices with Yahoo cache, saves back
  - NEVER zeros an account — if no data, keeps previous state
  - NEVER changes share counts during a pipeline run
  - Import Data modal (/api/import) is the ONLY way to update share counts
  - No CSV scanning, no positions_file, no file-based data ingestion
  - Sanity check: if new total < 50% of previous total, ABORT save

YAML contains: account keys, display names, targets, fund configs ONLY
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, date


# ── Constants ─────────────────────────────────────────────────────────────────

CASH_EQUIV = frozenset({
    "SNAXX", "SWVXX", "VMFXX", "SPRXX", "FDRXX",
    "CASH & CASH INVESTMENTS", "CASH", "MMKT"
})

MUTUAL_FUND_TICKERS = frozenset({
    "FID-CONTRA-F", "SS-SMMD", "TRP-LVAL", "SP500-D", "JPM-LGCG",
    "VANG-FTSE-SOC", "WM-BLAIR", "FID-DIVINTL", "SS-GACEQ", "AB-DISC-Z",
})


def _is_proprietary(sym: str) -> bool:
    """Fidelity institutional funds use hyphenated symbols — no Yahoo price."""
    return "-" in sym and len(sym) > 5


def _choose_anchor_holding(acct_holdings: List[Dict]) -> Optional[Dict]:
    candidates = [h for h in acct_holdings if not h.get("is_loan") and not h.get("is_cash")]
    if not candidates:
        return None
    proprietary = [h for h in candidates if _is_proprietary(str(h.get("symbol", "")))]
    if proprietary:
        contra = [h for h in proprietary if "CONTRA" in str(h.get("symbol", "")).upper() or "CONTRA" in str(h.get("name", "")).upper()]
        if contra:
            return max(contra, key=lambda x: x.get("market_value", 0) or 0)
        return max(proprietary, key=lambda x: x.get("market_value", 0) or 0)
    return max(candidates, key=lambda x: x.get("market_value", 0) or 0)


def _apply_reported_total_guard(acct_key: str, acct_holdings: List[Dict], summary: Dict) -> float:
    reported_total = float(summary.get("reported_total_value") or 0)
    source = str(summary.get("source", "")).lower()
    if reported_total <= 0:
        return round(sum(h.get("market_value", 0) or 0 for h in acct_holdings if not h.get("is_loan")), 2)

    derived_total = round(sum(h.get("market_value", 0) or 0 for h in acct_holdings if not h.get("is_loan")), 2)
    drift = round(reported_total - derived_total, 2)
    if abs(drift) < 0.01:
        return derived_total

    use_guard = acct_key == "fidelity_401k" or "fidelity" in source
    if not use_guard:
        return derived_total

    anchor = _choose_anchor_holding(acct_holdings)
    if anchor:
        before = round(anchor.get("market_value", 0) or 0, 2)
        anchor["market_value"] = round(before + drift, 2)
        shares = float(anchor.get("shares") or 0)
        if shares > 0 and not anchor.get("is_cash"):
            anchor["price"] = round(anchor["market_value"] / shares, 6)
        print(f"  [loader][guard] {acct_key}: derived ${derived_total:,.2f} vs reported ${reported_total:,.2f} → residual ${drift:+,.2f} applied to {anchor.get('symbol')}")
        return reported_total

    print(f"  [loader][guard] WARNING {acct_key}: reported ${reported_total:,.2f} but no anchor holding found; keeping derived ${derived_total:,.2f}")
    return derived_total


# ── YAML config loader ────────────────────────────────────────────────────────

def load_accounts_config(project_root: Path) -> Dict:
    """Load portfolio_accounts.yaml. Returns empty dict on failure."""
    yaml_path = project_root / "assets" / "portfolio_accounts.yaml"
    if not yaml_path.exists():
        print(f"  [loader] WARNING: {yaml_path} not found")
        return {}
    try:
        import yaml
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"  [loader] WARNING: could not load YAML: {e}")
        return {}


# ── Price cache repricing ─────────────────────────────────────────────────────

def reprice_holdings(holdings: List[Dict], price_cache: Dict,
                     as_of: str = None) -> List[Dict]:
    """
    Reprice holdings using Yahoo price cache.
    Updates price and market_value ONLY — NEVER touches share counts.
    Fidelity proprietary symbols are skipped (no Yahoo price exists).
    """
    repriced = []
    today = as_of or date.today().isoformat()

    for h in holdings:
        sym = h.get("symbol", "")
        shares = h.get("shares", 0) or 0

        # Keep cash and zero-share positions unchanged
        if h.get("is_cash") or sym in CASH_EQUIV or shares == 0:
            repriced.append(h)
            continue

        # Broker-sourced (SnapTrade) holdings: keep the broker value ONLY for fund/opaque codes that have no
        # public quote (the 401k Fidelity codes — broker value is authoritative there). Real exchange
        # tickers (stocks/ETFs, e.g. rollover-IRA holdings) fall through and reprice intraday from the quote
        # cache for freshness — shares still come from the periodic sync, prices update between syncs.
        if str(h.get("position_source") or "").lower() == "snaptrade":
            try:
                import holding_family as _hf
                _opaque = _hf.is_unstoppable_fund(sym) or not (sym.isalpha() and 1 <= len(sym) <= 5)
            except Exception:
                _opaque = not (sym.isalpha() and 1 <= len(sym) <= 5)
            if _opaque:
                repriced.append(h)
                continue

        # Skip Fidelity proprietary funds — they don't exist on Yahoo
        if _is_proprietary(sym):
            updated = dict(h)
            if abs(updated.get('day_change_pct', 0) or 0) > 5:
                updated['day_change'] = 0.0
                updated['day_change_pct'] = 0.0
            repriced.append(updated)
            continue

        # Look up price in cache
        cache_entry = price_cache.get(sym, {})
        if not cache_entry or not isinstance(cache_entry, dict):
            repriced.append(h)
            continue

        # Find price for today or most recent available date
        sorted_dates = sorted(cache_entry.keys())
        price = None
        if today in cache_entry:
            price = cache_entry[today]
        elif sorted_dates:
            price = cache_entry[sorted_dates[-1]]

        if price and float(price) > 0:
            updated = dict(h)
            prev_price = h.get("price") or 0
            new_price = float(price)
            updated["price"] = new_price
            updated["market_value"] = round(shares * new_price, 2)
            updated["as_of"] = today
            updated["updated_at"] = datetime.now().isoformat()
            if not updated.get("account_id"):
                updated["account_id"] = updated.get("account") or "unknown"
            if prev_price > 0:
                updated["day_change"] = round(
                    (new_price - prev_price) * shares, 2)
                updated["day_change_pct"] = round(
                    (new_price - prev_price) / prev_price * 100, 4)
            else:
                updated["day_change"] = updated.get("day_change", 0) or 0
                updated["day_change_pct"] = updated.get("day_change_pct", 0) or 0
            repriced.append(updated)
        else:
            repriced.append(h)

    return repriced


# ── Main loader ───────────────────────────────────────────────────────────────

def load_all_portfolios(project_root_str: str) -> Dict:
    """
    Load portfolio from holdings.json and reprice with Yahoo cache.

    1. Read holdings.json (source of truth for share counts)
    2. Load Yahoo price cache
    3. Reprice all non-proprietary positions
    4. Recompute account and portfolio totals
    5. Sanity check: if new total < 50% of previous, abort
    6. Return updated portfolio dict (caller must call save_state)
    """
    project_root = Path(project_root_str)
    state_dir = project_root / "data" / "portfolios" / "state"
    holdings_path = state_dir / "holdings.json"
    price_cache_path = state_dir / "price_cache.json"

    # ── Step 1: Load current holdings.json ───────────────────────────────────
    if not holdings_path.exists():
        print("  [loader] holdings.json not found — creating empty state")
        print("  [loader]   → Use Import Data modal to load account positions")
        current = _empty_portfolio()
        return current

    try:
        current = json.loads(holdings_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [loader] ERROR reading holdings.json: {e}")
        print("  [loader]   → holdings.json may be corrupted. Check the file.")
        return _empty_portfolio()

    holdings = current.get("holdings", [])
    prev_total = (current.get("portfolio_totals") or {}).get("total_value", 0) or 0

    if not holdings:
        print("  [loader] WARNING: No holdings in holdings.json")
        print("  [loader]   → Use Import Data modal to load account positions")
        # Still compute totals from account_summaries if present
        account_summaries = current.get("account_summaries", {})
        for acct_key, summary in account_summaries.items():
            display = summary.get("display_name", acct_key)
            total = summary.get("total_value", 0)
            count = summary.get("holdings_count", 0)
            print(f"  [loader]   {display}: {count} holdings | ${total:,.2f}")
        portfolio_total = sum(
            v.get("total_value", 0) for v in account_summaries.values()
        )
        print(f"  [loader] TOTAL PORTFOLIO: ${portfolio_total:,.2f}")
        return current

    # ── Step 2: Load price cache ──────────────────────────────────────────────
    price_cache = {}
    if price_cache_path.exists():
        try:
            price_cache = json.loads(
                price_cache_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [loader] WARNING: price cache error: {e} "
                  "— using stored prices")
    else:
        print("  [loader] WARNING: price cache not found — using stored prices")

    # ── Step 3: Reprice ───────────────────────────────────────────────────────
    today = date.today().isoformat()
    repriced = reprice_holdings(holdings, price_cache, today)

    # ── Step 3b: Zero impossible day_change on proprietary symbols ────────────
    # Fidelity proprietary funds (hyphenated, len>5) are never repriced by Yahoo.
    # If holdings.json contains a stale/wrong day_change (e.g. from a bad import),
    # it would survive forever. Zero any day_change_pct > 5% for these symbols.
    for _h in repriced:
        _sym = _h.get('symbol', '')
        if '-' in _sym and len(_sym) > 5:
            if abs(_h.get('day_change_pct', 0) or 0) > 5:
                _h['day_change'] = 0.0
                _h['day_change_pct'] = 0.0

    # ── Step 4: Recompute totals ──────────────────────────────────────────────
    cfg = load_accounts_config(project_root)
    accounts_cfg = cfg.get("accounts", {})

    account_summaries = dict(current.get("account_summaries", {}))
    holdings_by_acct: Dict[str, List] = {}
    for h in repriced:
        acct = h.get("account_id") or h.get("account") or "unknown"
        h["account_id"] = acct
        holdings_by_acct.setdefault(acct, []).append(h)

    for acct_key, acct_holdings in holdings_by_acct.items():
        valid = [h for h in acct_holdings if not h.get("is_loan")]
        if acct_key not in account_summaries:
            account_summaries[acct_key] = {}

        acct_total = _apply_reported_total_guard(acct_key, valid, account_summaries[acct_key])
        acct_day_change = round(
            sum(h.get("day_change", 0) or 0 for h in valid), 2)
        acct_prev_total = acct_total - acct_day_change
        acct_day_change_pct = round(
            (acct_day_change / acct_prev_total * 100) if acct_prev_total else 0, 4)

        account_summaries[acct_key]["total_value"] = acct_total
        account_summaries[acct_key]["holdings_count"] = len(valid)
        account_summaries[acct_key]["last_repriced"] = today
        account_summaries[acct_key]["day_change"] = acct_day_change
        account_summaries[acct_key]["day_change_pct"] = acct_day_change_pct

        acct_cfg = accounts_cfg.get(acct_key, {})
        if not account_summaries[acct_key].get("display_name"):
            account_summaries[acct_key]["display_name"] = acct_cfg.get(
                "display_name", acct_key)

    portfolio_total = round(
        sum(v.get("total_value", 0) for v in account_summaries.values()), 2)
    portfolio_day_change = round(
        sum((h.get("day_change", 0) or 0) for h in repriced if not h.get("is_loan")), 2)
    portfolio_prev_total = portfolio_total - portfolio_day_change
    portfolio_day_change_pct = round(
        (portfolio_day_change / portfolio_prev_total * 100) if portfolio_prev_total else 0, 4)

    # ── Step 5: Sanity check ──────────────────────────────────────────────────
    if prev_total > 0 and portfolio_total < prev_total * 0.50:
        print(f"  [loader] ⛔ SAFETY ABORT: new total ${portfolio_total:,.0f} "
              f"< 50% of previous ${prev_total:,.0f}")
        print("  [loader]   Price cache may be empty or corrupted.")
        print("  [loader]   holdings.json NOT updated — previous state preserved.")
        return current

    # ── Step 6: Build and return updated portfolio ────────────────────────────
    updated = dict(current)
    updated["holdings"] = repriced
    updated["account_summaries"] = account_summaries
    updated["as_of"] = today
    _now_iso = datetime.now().isoformat()
    updated["last_repriced"] = _now_iso
    # generated_at previously kept the date the POSITION LIST was first built and
    # was never touched by repricing, so a fully-repriced file still advertised
    # generated_at from days earlier (holdings.json read 2026-07-17 while
    # last_repriced read 2026-07-20T10:00). Any consumer using the obvious
    # freshness field would call live data three days stale. generated_at now
    # means "these contents are current as of", and the original build time is
    # preserved under positions_built_at (2026-07-20).
    if current.get("generated_at") and not updated.get("positions_built_at"):
        updated["positions_built_at"] = current["generated_at"]
    updated["generated_at"] = _now_iso
    updated["_freshness_note"] = (
        "generated_at = contents current as of (updated every reprice). "
        "positions_built_at = when the position list itself was constructed. "
        "last_repriced = price refresh time (same as generated_at after a reprice).")
    prev_pt = dict(current.get("portfolio_totals", {}))
    prev_pt["total_value"] = portfolio_total
    prev_pt["day_change"] = portfolio_day_change
    prev_pt["day_change_pct"] = portfolio_day_change_pct
    prev_pt["as_of"] = today
    prev_pt["last_pipeline_run"] = datetime.now().isoformat()
    updated["portfolio_totals"] = prev_pt

    # Print summary
    for acct_key in sorted(holdings_by_acct.keys()):
        display = account_summaries.get(acct_key, {}).get(
            "display_name", acct_key)
        total = account_summaries.get(acct_key, {}).get("total_value", 0)
        count = len([h for h in holdings_by_acct[acct_key]
                     if not h.get("is_loan")])
        print(f"  [loader]   {display}: {count} holdings | ${total:,.2f}")

    print(f"  [loader] TOTAL PORTFOLIO: ${portfolio_total:,.2f} "
          f"across {len(holdings_by_acct)} accounts")
    return updated


def save_state(portfolio: Dict, project_root_str: str) -> None:
    """Save portfolio state to holdings.json."""
    project_root = Path(project_root_str)
    state_dir = project_root / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    holdings_path = state_dir / "holdings.json"
    # MANDATORY wipe-guard: never zero/overwrite a good holdings snapshot with a bad payload.
    from holdings_guard import protected_holdings_write
    protected_holdings_write(portfolio, source="portfolio_loader.save_state", target_path=str(holdings_path))
    print(f"  [loader] State saved → "
          f"{holdings_path.relative_to(project_root)}")


def _empty_portfolio() -> Dict:
    return {
        "holdings": [],
        "account_summaries": {},
        "portfolio_totals": {
            "total_value": 0,
            "as_of": date.today().isoformat()
        },
        "transactions": [],
        "trade_journal": [],
    }


# ── Fidelity PDF parser ───────────────────────────────────────────────────────
# Used by portfolio_server.py /api/import endpoint when Fidelity PDF uploaded
# Validated April 10, 2026 against actual NetBenefits statement

def parse_fidelity_pdf_text(lines: List[str]) -> Dict:
    """
    Parse text lines extracted from a Fidelity NetBenefits PDF statement.

    Confirmed PDF structure (sandbox-validated April 10, 2026):
    - pdfminer extracts lines in visual top-to-bottom order
    - Page 2: ALL fund name lines appear before ALL number lines
    - Each fund has exactly 6 numbers:
        [shares_dec31, shares_apr, price_dec31, price_apr, mv_dec31, mv_apr]
    - First 2 numbers are Stock tier totals — skip them
    - 10 funds total, 60 numbers total (after skipping 2 tier totals)
    - Total computed from holdings matches $519,361.68 exactly
    """
    CATEGORIES = {
        'Small Growth', 'Small Value', 'Small Blend', 'Foreign',
        'Large Value', 'Large Blend', 'Large Growth', 'Mid Growth',
        'Mid Value', 'Mid Blend', 'Bond', 'Stable Value', 'Stock'
    }
    SKIP_SUBSTRINGS = [
        'https://', 'Investment', 'Shares as of', 'Price as of',
        'Market Value as', 'of 12/31', 'of 04/', 'Tier',
        'Account Totals', 'Market Value of Your Account',
        'Statement Period', 'Displayed in this section',
        'Fidelity NetBenefits',
    ]
    # Fund name lines → internal symbol
    # Keys are tuples of consecutive lines that identify each fund
    FUND_MAP = {
        ('WM Blair', 'Smmidcp GR'):         'WM-BLAIR',
        ('AB Disc', 'Value Z'):              'AB-DISC-Z',
        ('SS RSL', 'Smmdcp Idx', 'II'):      'SS-SMMD',
        ('FID Div Intl', 'PL CL C'):         'FID-DIVINTL',
        ('SS Gaceq', 'Exus Idx II'):         'SS-GACEQ',
        ('TRP Large-', 'Cap Val I'):         'TRP-LVAL',
        ('SP 500 Index', 'PL CL D'):         'SP500-D',
        ('Vang Ftse', 'SOC Idx IS'):         'VANG-FTSE-SOC',
        ('FID Contra', 'Pool CL F'):         'FID-CONTRA-F',
        ('JPM Lg CP', 'Grth CF-A'):          'JPM-LGCG',
    }
    SECTOR_MAP = {
        'WM-BLAIR': 'us_small',
        'AB-DISC-Z': 'us_large_value',
        'SS-SMMD': 'us_small',
        'FID-DIVINTL': 'international',
        'SS-GACEQ': 'international',
        'TRP-LVAL': 'us_large_value',
        'SP500-D': 'us_large_blend',
        'VANG-FTSE-SOC': 'international',
        'FID-CONTRA-F': 'us_large_blend',
        'JPM-LGCG': 'us_large_growth',
    }
    NAME_MAP = {
        'WM-BLAIR': 'WM Blair Smmidcp GR',
        'AB-DISC-Z': 'AB Disc Value Z',
        'SS-SMMD': 'SS RSL Smmdcp Idx II',
        'FID-DIVINTL': 'FID Div Intl PL CL C',
        'SS-GACEQ': 'SS Gaceq Exus Idx II',
        'TRP-LVAL': 'TRP LargeCap Val I',
        'SP500-D': 'SP 500 Index PL CL D',
        'VANG-FTSE-SOC': 'Vang Ftse SOC Idx IS',
        'FID-CONTRA-F': 'FID Contra Pool CL F',
        'JPM-LGCG': 'JPM Lg CP Grth CF-A',
    }

    def is_num(s):
        return bool(re.match(r'^-?\$?[\d,]+\.\d+$', s))

    def clean(s):
        return float(s.replace('$', '').replace(',', ''))

    def should_skip(l):
        if l in CATEGORIES:
            return True
        if re.match(r'^\d/4$', l):         # page numbers: 1/4 2/4 3/4 4/4
            return True
        if re.match(r'^\d{2}/\d{2}/\d{4}$', l):  # bare dates
            return True
        if re.match(r'^\d+/\d+/\d+,', l):  # "4/9/26, 11:21 PM"
            return True
        for sub in SKIP_SUBSTRINGS:
            if sub in l:
                return True
        return False

    # Extract as_of date from "Statement Period: ... to MM/DD/YYYY"
    as_of = None
    for l in lines[:50]:
        m = re.search(r'Statement Period:.*to (\d{2}/\d{2}/\d{4})', l)
        if m:
            d = m.group(1)
            as_of = f"{d[6:]}-{d[0:2]}-{d[3:5]}"
            break

    # Collect name lines and number lines from the holdings table
    name_lines, number_lines = [], []
    in_table = False
    tier_totals_skipped = 0

    for l in lines:
        if 'Market Value of Your Account' in l:
            in_table = True
            continue
        if l == 'Account Totals':
            break
        if not in_table:
            continue
        if should_skip(l):
            continue
        if is_num(l):
            if tier_totals_skipped < 2:
                tier_totals_skipped += 1  # skip Stock $530,241.63 and $519,361.68
            else:
                number_lines.append(l)
        else:
            name_lines.append(l)

    # Match fund name sequences to symbols
    fund_order = []
    i = 0
    while i < len(name_lines):
        matched = False
        for key, sym in FUND_MAP.items():
            kl = list(key)
            if name_lines[i:i + len(kl)] == kl:
                fund_order.append(sym)
                i += len(kl)
                matched = True
                break
        if not matched:
            i += 1  # skip unrecognized lines silently

    if not fund_order:
        return {
            "error": "No fund holdings found. "
                     "Verify this is a Fidelity NetBenefits statement."
        }

    expected_nums = len(fund_order) * 6
    if len(number_lines) != expected_nums:
        return {
            "error": f"Expected {expected_nums} data values for "
                     f"{len(fund_order)} funds, found {len(number_lines)}. "
                     "PDF format may have changed."
        }

    # Cost basis per share, sourced from the Fidelity 'Portfolio Positions.pdf' (Cost basis column).
    # The Statement Details PDF parsed here has no cost basis, so we read it from a side config that
    # is refreshed when a new Positions PDF is imported. Missing/zero → cost_basis stays None (honest).
    _cb_per_share = {}
    try:
        _cb_path = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "input" / "fidelity_cost_basis.json"
        if _cb_path.exists():
            _cb_per_share = {k: v for k, v in json.loads(_cb_path.read_text()).items() if not k.startswith("_")}
    except Exception:
        _cb_per_share = {}

    # Build holdings — each fund has 6 values, take indices 1,3,5 (April data)
    holdings = []
    for idx, sym in enumerate(fund_order):
        base = idx * 6
        shares = clean(number_lines[base + 1])   # April shares
        price  = clean(number_lines[base + 3])   # April price
        mv     = clean(number_lines[base + 5])   # April market value
        _ps = _cb_per_share.get(sym)
        _cb = round(_ps * shares, 2) if (_ps and shares) else None
        holdings.append({
            "symbol":       sym,
            "name":         NAME_MAP[sym],
            "shares":       shares,
            "price":        price,
            "market_value": mv,
            "account":      "fidelity_401k",
            "account_type": "401k",
            "broker":       "fidelity",
            "sector_type":  SECTOR_MAP[sym],
            "asset_type":   "Mutual Fund/Trust",
            "is_cash":      False,
            "is_fund":      True,
            "reinvest_div": True,
            "day_change":   0.0,
            "day_change_pct": 0.0,
            "cost_basis":   _cb,
            "gain_loss":    round(mv - _cb, 2) if _cb else None,
            "cost_basis_source": "fidelity_positions_pdf" if _cb else None,
        })

    total_value = round(sum(h["market_value"] for h in holdings), 2)

    return {
        "holdings":    holdings,
        "total_value": total_value,
        "as_of":       as_of or date.today().isoformat(),
        "source":      "fidelity_pdf",
    }
