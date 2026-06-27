"""broker_config.py — Central broker/account configuration.

All scripts should import from here instead of hardcoding account names.
The source of truth is the `accounts` DB table + ATM config YAML.

Usage:
    from broker_config import get_default_paper_account, get_account_display_name
    account = get_default_paper_account()  # e.g. 'tradeai_automated'
"""
import os
import logging

log = logging.getLogger(__name__)

_cached_default = None
_cached_accounts = None


def get_default_paper_account() -> str:
    """Return the default paper trading account label from ATM config.
    Falls back to first enabled account, then to env var, then 'paper'.
    NEVER hardcode a broker name — always call this function.
    """
    global _cached_default
    if _cached_default:
        return _cached_default

    # Try ATM config first
    try:
        from atm_config_manager import get_enabled_accounts
        enabled = get_enabled_accounts()
        if enabled:
            _cached_default = enabled[0]
            return _cached_default
    except Exception:
        pass

    # Try env var
    env_account = os.environ.get("DEFAULT_PAPER_ACCOUNT", "")
    if env_account:
        _cached_default = env_account
        return _cached_default

    # Fallback to DB
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT account_label FROM accounts WHERE mode='paper' LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                _cached_default = row[0]
                return _cached_default
    except Exception:
        pass

    _cached_default = "paper"
    return _cached_default


def get_all_accounts() -> list:
    """Return all accounts from DB: [{account_label, broker, mode}, ...]"""
    global _cached_accounts
    if _cached_accounts is not None:
        return _cached_accounts

    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT account_label, broker, mode FROM accounts ORDER BY account_label")
            cols = [d[0] for d in cur.description]
            _cached_accounts = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()
            return _cached_accounts
    except Exception:
        pass

    _cached_accounts = []
    return _cached_accounts


def get_account_display_name(account_label: str) -> str:
    """Return human-readable account name. e.g. 'alpaca_paper' → 'Alpaca Paper'"""
    accounts = get_all_accounts()
    for a in accounts:
        if a["account_label"] == account_label:
            broker = (a.get("broker") or "").title()
            mode = (a.get("mode") or "").title()
            return f"{broker} {mode}".strip()
    from automated_account import display_account_label, is_automated_account
    if is_automated_account(account_label):
        return display_account_label(account_label)
    return account_label.replace("_", " ").title()


def get_account_broker(account_label: str) -> str:
    """Return broker name for an account. e.g. 'alpaca_paper' → 'alpaca'"""
    accounts = get_all_accounts()
    for a in accounts:
        if a["account_label"] == account_label:
            return a.get("broker", "unknown")
    return "unknown"


def clear_cache():
    """Clear cached values (call after config changes)."""
    global _cached_default, _cached_accounts
    _cached_default = None
    _cached_accounts = None
