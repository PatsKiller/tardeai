"""snaptrade_read.py — SnapTrade client for holdings aggregation (READ today).

Scope today is READ-ONLY SYNC: list accounts, pull positions/balances/activities, normalize to the
holdings.json shape. Trading is intentionally NOT here yet — but this is a soft boundary, not a hard
block: when you decide to add SnapTrade trading later, add it (ideally a `snaptrade_trade.py` sibling
behind the same canary + 2FA rails as the Schwab write pilot, or here). Nothing in this module
prevents that.

Reads work as soon as the client keys + a connected user are present (no separate enable flag gating
reads). WRITING into the canonical holdings.json is a separate, explicit step owned by
scripts/snaptrade_sync.py (which defaults to a dry run and only persists with --apply, going through
schwab_position_sync.protected_holdings_write so the sanity/no-wipe gate still applies).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from . import snaptrade_credentials as _creds

# Money-market / cash-sweep tickers normalized to $1.00 NAV cash on sync (operator 2026-06-19): these
# trade at a fixed $1 NAV and are cash, not positions — aggregators sometimes report a drifted price.
MONEY_MARKET_SYMBOLS = {
    "SPAXX", "FDRXX", "FZFXX", "FZDXX", "SPRXX", "FGTXX", "FMPXX", "FNSXX",   # Fidelity
    "SWVXX", "SNVXX", "SNAXX", "SWGXX",                                          # Schwab
    "VMFXX", "VMRXX", "VUSXX",                                                   # Vanguard
    "CASH", "USD",                                                               # generic cash sweeps
}

# Optional manual overrides — empty by default. SnapTrade SPAXX *position units* often lag after trades;
# reconcile_cash_positions() uses balances.buying_power (matches Fidelity core cash) instead.
PINNED_CASH: dict[tuple[str, str], float] = {}


@dataclass(frozen=True)
class SnapTradeUser:
    """Per-end-user credentials minted by registerUser (stored in broker_credentials.env via the creds
    helper, or passed in directly)."""
    user_id: str
    user_secret: str

    @classmethod
    def from_env(cls) -> "SnapTradeUser":
        u = _creds.user_status()
        if not u.get("ready"):
            raise RuntimeError("SnapTrade user not connected — run snaptrade_connect.py first.")
        return cls(user_id=os.environ.get(_creds.USER_ID_KEY, ""),
                   user_secret=os.environ.get(_creds.USER_SECRET_KEY, ""))


def is_configured() -> bool:
    """True when both the client keys and a connected user are present (reads can run)."""
    return bool(_creds.status().get("ready") and _creds.user_status().get("ready"))


def _client():
    """Build the SnapTrade SDK client, or raise a clear error. Imported lazily so there's no hard
    dependency until you opt in (`pip install snaptrade-python-sdk`)."""
    st = _creds.status()
    if not st.get("ready"):
        raise RuntimeError("SnapTrade client keys not set — add them in the UI modal (Schwab Accounts → "
                           "Connect SnapTrade).")
    try:
        from snaptrade_client import SnapTrade  # type: ignore
    except Exception as e:  # pragma: no cover - optional dep
        raise RuntimeError(f"snaptrade-python-sdk not installed ({e}). `pip install snaptrade-python-sdk`.")
    return SnapTrade(
        consumer_key=os.environ.get(_creds.CONSUMER_KEY_KEY, ""),
        client_id=os.environ.get(_creds.CLIENT_ID_KEY, ""),
    )


def _body(resp):
    return list(getattr(resp, "body", resp) or [])


# ── READ surface ─────────────────────────────────────────────────────────────────────────────────

def list_accounts(user: SnapTradeUser) -> list[dict]:
    """GET connected brokerage accounts for the user."""
    c = _client()
    return _body(c.account_information.list_user_accounts(user_id=user.user_id, user_secret=user.user_secret))


def holdings(user: SnapTradeUser, account_id: str) -> list[dict]:
    """GET positions for one account (normalize via normalize_positions before any holdings write).

    Uses the unified positions endpoint (get_all_account_positions), which replaces the deprecated
    get_user_account_positions and returns equity + option + other asset classes in one call. The
    body is an object {"results": [...], "data_freshness": {...}}, so we return the `results` list;
    the per-position shape (symbol moved under `instrument`, per-unit `cost_basis`) is handled by
    normalize_positions.
    """
    c = _client()
    resp = c.account_information.get_all_account_positions(
        user_id=user.user_id, user_secret=user.user_secret, account_id=account_id)
    body = getattr(resp, "body", resp) or {}
    if isinstance(body, dict):
        return list(body.get("results") or [])
    return list(body or [])


def balances(user: SnapTradeUser, account_id: str) -> list[dict]:
    """GET cash/balances for one account."""
    c = _client()
    return _body(c.account_information.get_user_account_balance(
        user_id=user.user_id, user_secret=user.user_secret, account_id=account_id))


def activities(user: SnapTradeUser, account_id: str, *, start: Optional[str] = None,
               end: Optional[str] = None) -> list[dict]:
    """GET transactions/activities for one account (reconciliation).

    Uses the per-account endpoint (get_account_activities); the old
    transactions_and_reporting.get_activities was retired by SnapTrade (410 Gone). The body is an
    object {"data": [...], "pagination": {...}} — the SDK schema wrapper is unreliable for it, so
    parse the raw JSON response and page through until all rows in the window are collected.
    """
    import json as _json
    c = _client()
    rows: list[dict] = []
    offset, limit = 0, 1000
    while True:
        kwargs = dict(user_id=user.user_id, user_secret=user.user_secret, account_id=account_id,
                      offset=offset, limit=limit)
        if start:
            kwargs["start_date"] = start
        if end:
            kwargs["end_date"] = end
        resp = c.account_information.get_account_activities(**kwargs)
        body = _json.loads(resp.response.data.decode("utf-8")) or {}
        page = list(body.get("data") or [])
        rows.extend(page)
        if len(page) < limit:
            return rows
        offset += limit


# ── Normalization to the holdings.json shape (pure, no network) ─────────────────────────────────────

def normalize_positions(raw_positions: list[dict], account_key: str) -> list[dict]:
    """Map SnapTrade position dicts → the holdings.json holding shape, tagged with provenance so the merge
    never double-counts or silently replaces a direct-broker source. Pure / unit-testable."""
    out: list[dict] = []
    for p in raw_positions or []:
        # Unified endpoint (get_all_account_positions): symbol/description live under `instrument`.
        inst = p.get("instrument")
        if isinstance(inst, dict):
            symobj = inst  # so the money-market description check below reads instrument.description
            sym = inst.get("symbol") or inst.get("raw_symbol") or ""
        else:
            # Legacy/deprecated endpoint shape: nested universal symbol object.
            symobj = p.get("symbol") or {}
            sym = (((symobj.get("symbol") or {}) if isinstance(symobj, dict) else {}).get("symbol")
                   or (symobj.get("symbol") if isinstance(symobj, dict) else None)
                   or p.get("symbol") or "")
        sym = str(sym).upper().strip()
        if not sym:
            continue
        units = p.get("units") or p.get("quantity") or 0
        price = p.get("price") or 0
        try:
            units = float(units); price = float(price)
        except (TypeError, ValueError):
            continue
        avg = p.get("average_purchase_price") or p.get("average_price") or p.get("cost_basis")
        try:
            avg = float(avg) if avg is not None else None
        except (TypeError, ValueError):
            avg = None

        # Money-market / cash-sweep normalization (fix 2026-06-19): SnapTrade reported SPAXX with a
        # bogus price ($0.803) + stale units, so it came in as a stock with a phantom -19.7% "loss".
        # A money market is $1.00 NAV cash — present it as clean cash (no P/L, is_cash=True) using the
        # implied value (units*price), so it can never be mistreated as a position again.
        if sym in MONEY_MARKET_SYMBOLS or "MONEY MARKET" in str((symobj or {}).get("description", "")).upper():
            mv = PINNED_CASH.get((account_key, sym), round(units * max(price, 1.0), 2))
            out.append({
                "symbol": sym, "account": account_key, "shares": mv,
                "cost_basis": mv, "avg_cost": 1.0, "market_value": mv,
                "current_price": 1.0, "price": 1.0, "is_cash": True,
                "gain_loss": 0, "gain_loss_pct": 0, "sector_type": "Cash",
                "cost_basis_source": "snaptrade", "position_source": "snaptrade",
                "cash_source": "snaptrade_position_units",
            })
            continue

        out.append({
            "symbol": sym,
            "account": account_key,
            "shares": units,
            "cost_basis": (avg * units) if (avg is not None) else None,
            "avg_cost": avg,
            "market_value": units * price,
            "current_price": price,
            "is_cash": False,
            "cost_basis_source": "snaptrade",
            "position_source": "snaptrade",
        })
    return out


def _parse_balance_totals(balance_rows: list[dict]) -> tuple[float | None, float | None]:
    """Return (cash, buying_power) from SnapTrade balance rows (USD)."""
    cash = bp = None
    for b in balance_rows or []:
        cur = b.get("currency")
        if isinstance(cur, dict) and cur.get("code") not in (None, "USD"):
            continue
        try:
            if b.get("cash") is not None:
                cash = float(b["cash"])
        except (TypeError, ValueError):
            pass
        try:
            if b.get("buying_power") is not None:
                bp = float(b["buying_power"])
        except (TypeError, ValueError):
            pass
    return cash, bp


def reconcile_cash_positions(positions: list[dict], balance_rows: list[dict],
                            account_key: str) -> list[dict]:
    """Fix stale SPAXX units: SnapTrade positions keep pre-trade cash while balances.buying_power
    matches Fidelity 'core position' / available cash after stock purchases."""
    cash_bal, buying_power = _parse_balance_totals(balance_rows)
    pos_cash_mv = round(sum(
        float(p.get("market_value") or 0) for p in positions
        if p.get("is_cash") or str(p.get("symbol") or "").upper() in MONEY_MARKET_SYMBOLS
    ), 2)

    authoritative: float | None = None
    source = ""
    pin = PINNED_CASH.get((account_key, "SPAXX")) or PINNED_CASH.get((account_key, "FDRXX"))
    if pin is not None:
        authoritative, source = float(pin), "operator_pinned"
    elif buying_power is not None and buying_power >= 0:
        # buying_power tracks Fidelity core MM after deploys; position units often stay stale.
        if pos_cash_mv <= 0 or buying_power < pos_cash_mv - 500 or abs(buying_power - pos_cash_mv) > 500:
            authoritative, source = round(buying_power, 2), "snaptrade_buying_power"
    elif cash_bal is not None and cash_bal >= 0:
        if pos_cash_mv <= 0 or abs(cash_bal - pos_cash_mv) > 500:
            authoritative, source = round(cash_bal, 2), "snaptrade_cash_balance"

    if authoritative is None:
        return positions

    out: list[dict] = []
    cash_applied = False
    cash_sym = "SPAXX"
    for p in positions:
        sym = str(p.get("symbol") or "").upper()
        if p.get("is_cash") or sym in MONEY_MARKET_SYMBOLS:
            cash_sym = sym or "SPAXX"
            cash_applied = True
            out.append({
                **p,
                "symbol": cash_sym,
                "account": account_key,
                "shares": authoritative,
                "cost_basis": authoritative,
                "avg_cost": 1.0,
                "market_value": authoritative,
                "current_price": 1.0,
                "price": 1.0,
                "is_cash": True,
                "gain_loss": 0,
                "gain_loss_pct": 0,
                "sector_type": "Cash",
                "cost_basis_source": "snaptrade",
                "position_source": "snaptrade",
                "cash_source": source,
            })
        else:
            out.append(p)

    if not cash_applied and authoritative > 0:
        out.append({
            "symbol": cash_sym,
            "account": account_key,
            "shares": authoritative,
            "cost_basis": authoritative,
            "avg_cost": 1.0,
            "market_value": authoritative,
            "current_price": 1.0,
            "price": 1.0,
            "is_cash": True,
            "gain_loss": 0,
            "gain_loss_pct": 0,
            "sector_type": "Cash",
            "cost_basis_source": "snaptrade",
            "position_source": "snaptrade",
            "cash_source": source,
        })
    return out
