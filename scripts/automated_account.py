"""Canonical automated-trading account key (formerly alpaca_paper).

All runtime account matching should use is_automated_account() / normalize_account_key()
so legacy rows continue to work until the DB migration completes.
"""
from __future__ import annotations

import os

AUTOMATED_ACCOUNT_KEY = os.getenv("AUTOMATED_ACCOUNT_KEY", "tradeai_automated")
LEGACY_AUTOMATED_KEYS = frozenset({
    "alpaca_paper", "ALPACA_PAPER", "paper", "PAPER", AUTOMATED_ACCOUNT_KEY,
})
DISPLAY_LABEL = "Automated (Alpaca)"


def is_automated_account(account: str | None) -> bool:
    return (account or "").strip() in LEGACY_AUTOMATED_KEYS


def normalize_account_key(account: str | None) -> str:
    """Map legacy paper identifiers to the canonical automated account key."""
    if is_automated_account(account):
        return AUTOMATED_ACCOUNT_KEY
    return (account or "").strip()


def display_account_label(account: str | None) -> str:
    if is_automated_account(account):
        return DISPLAY_LABEL
    return (account or "").replace("_", " ").title()