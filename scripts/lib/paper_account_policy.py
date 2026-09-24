"""Paper/training accounts never page the operator -- one policy, every sender.

OPERATOR DECISION 2026-09-22: "Anything being traded in the alpaca paper
account is just for training purposes. We don't need to be alerted on it...
I only want to care about being alerted about what I should be trading real
money with."

This was first enforced only inside open_trade_monitor.py (523878c18). The
M5 audit (2026-09-23) found four more senders still paging for paper:
eod_open_trade_alert (sent 09-22 16:05 and 09-23 16:05), alpaca_stop_manager,
paper_trade_monitor and atm_auto_approver. They all import this module so the
policy has ONE definition.

The gate is on the ACCOUNT, not on the script: a real-money row that ever
appears in these tables still alerts instead of being swallowed by a blanket
mute. Unknown accounts fail OPEN (they alert).

Extra paper accounts can be declared without a code change through
``TRADEAI_PAPER_ONLY_ACCOUNTS`` (comma-separated).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Iterable, Mapping

log = logging.getLogger(__name__)

#: Measured 2026-09-22: every paper_trades row belongs to one of these --
#: ALPACA_PAPER, tradeai_automated (the SANDBOX_ACCOUNT named at
#: validation_submitter.py:20) and TOS_PAPER. paper_trade_proposals also uses
#: the lower-case spelling ``alpaca_paper`` as a target_account, so matching is
#: case-insensitive. The real accounts are schwab_taxable / schwab_rollover_ira
#: / schwab_roth_ira (and the *_live broker accounts) and are never listed here.
PAPER_ONLY_ACCOUNTS = {"ALPACA_PAPER", "TOS_PAPER", "tradeai_automated"}
PAPER_ONLY_BROKERS = {"alpaca_paper", "tos_paper"}

#: The account every Alpaca-paper-API-only module (alpaca_stop_manager) acts on.
ALPACA_PAPER_ACCOUNT = "ALPACA_PAPER"

_ACCOUNT_KEYS = ("account", "execution_account", "target_account")


def _paper_accounts_lower() -> set[str]:
    extra = os.environ.get("TRADEAI_PAPER_ONLY_ACCOUNTS", "")
    names = set(PAPER_ONLY_ACCOUNTS) | {x.strip() for x in extra.split(",") if x.strip()}
    return {n.lower() for n in names}


def is_paper_only(trade: Mapping[str, Any] | None) -> bool:
    """True when this trade/proposal is simulation/training and must never page anyone."""
    try:
        t = trade or {}
        accts = [str(t.get(k) or "").strip() for k in _ACCOUNT_KEYS]
        broker = str(t.get("broker") or "").strip().lower()
    except Exception:
        return False
    paper = _paper_accounts_lower()
    if any(a and a.lower() in paper for a in accts):
        return True
    return broker in PAPER_ONLY_BROKERS


def all_paper_only(accounts: Iterable[str]) -> bool:
    """True when there is at least one account and EVERY one is paper-only."""
    accts = [str(a or "").strip() for a in accounts]
    accts = [a for a in accts if a]
    return bool(accts) and all(is_paper_only({"account": a}) for a in accts)


def suppress_paper_alert(source: str, trade: Mapping[str, Any] | None, summary: str = "") -> bool:
    """Return True (and log it) when the Telegram for ``trade`` must be dropped."""
    if not is_paper_only(trade):
        return False
    log.info("[paper-mute] %s: Telegram suppressed for paper account %s%s",
             source,
             next((str(trade.get(k)) for k in _ACCOUNT_KEYS if trade and trade.get(k)), "?"),
             f" -- {summary[:80]}" if summary else "")
    return True
