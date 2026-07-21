"""alpaca_credentials.py — credential slots for Alpaca multi-account (R2).

HARD RULE: host is a function of the *slot name*, never of an env URL.
  ALPACA_PAPER_*   → paper-api.alpaca.markets
  ALPACA_TAXABLE_* → api.alpaca.markets  (structure only; no live adapter)
  ALPACA_IRA_*     → api.alpaca.markets

Legacy ALPACA_API_KEY/SECRET fall back for PAPER slot only (deprecation log).
No secrets are printed. Live slots may be empty — that is expected until arming.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

log = logging.getLogger(__name__)

PAPER_HOST = "paper-api.alpaca.markets"
LIVE_HOST = "api.alpaca.markets"
PAPER_BASE = f"https://{PAPER_HOST}"
LIVE_BASE = f"https://{LIVE_HOST}"

# slot → (key_env, secret_env, base_url constant)
_SLOTS = {
    "ALPACA_PAPER": (
        "ALPACA_PAPER_API_KEY",
        "ALPACA_PAPER_SECRET_KEY",
        PAPER_BASE,
    ),
    "ALPACA_TAXABLE": (
        "ALPACA_TAXABLE_API_KEY",
        "ALPACA_TAXABLE_SECRET_KEY",
        LIVE_BASE,
    ),
    "ALPACA_IRA": (
        "ALPACA_IRA_API_KEY",
        "ALPACA_IRA_SECRET_KEY",
        LIVE_BASE,
    ),
}

# synonym names accepted on broker_accounts.credential_slot
_SLOT_ALIASES = {
    "paper": "ALPACA_PAPER",
    "ALPACA_PAPER": "ALPACA_PAPER",
    "taxable": "ALPACA_TAXABLE",
    "ALPACA_TAXABLE": "ALPACA_TAXABLE",
    "ira": "ALPACA_IRA",
    "ALPACA_IRA": "ALPACA_IRA",
}


def normalize_slot(slot: Optional[str]) -> str:
    s = (slot or "ALPACA_PAPER").strip()  # hardcode-ok: default paper credential slot name
    return _SLOT_ALIASES.get(s, _SLOT_ALIASES.get(s.upper(), s.upper() if s else "ALPACA_PAPER"))  # hardcode-ok


def base_url_for_slot(slot: Optional[str]) -> str:
    """Host is derived from slot only — ALPACA_BASE_URL is never consulted."""
    key = normalize_slot(slot)
    if key not in _SLOTS:
        raise ValueError(f"unknown credential_slot {slot!r}")
    return _SLOTS[key][2]


def resolve_credentials(slot: Optional[str] = "ALPACA_PAPER") -> Tuple[str, str, str]:
    """Return (api_key, secret_key, base_url) for the slot.

    PAPER falls back to legacy ALPACA_API_KEY/SECRET if slot-specific unset.
    Live slots return empty strings when unset (scaffold).
    """
    key = normalize_slot(slot)
    if key not in _SLOTS:
        raise ValueError(f"unknown credential_slot {slot!r}")
    key_env, sec_env, base = _SLOTS[key]
    api_key = (os.environ.get(key_env) or "").strip()
    secret = (os.environ.get(sec_env) or "").strip()
    if key == "ALPACA_PAPER" and (not api_key or not secret):
        leg_k = (os.environ.get("ALPACA_API_KEY") or "").strip()
        leg_s = (os.environ.get("ALPACA_SECRET_KEY") or "").strip()
        if leg_k or leg_s:
            log.info(
                "credential slot ALPACA_PAPER falling back to legacy "
                "ALPACA_API_KEY/SECRET (deprecated — migrate to ALPACA_PAPER_*)"
            )
            api_key = api_key or leg_k
            secret = secret or leg_s
    return api_key, secret, base


def slot_for_account_key(account_key: str) -> str:
    """Map account_key → credential_slot default when DB slot null."""
    ak = (account_key or "").strip().lower()
    # hardcode-ok: static account_key → credential_slot map (R2 taxonomy D1/D2)
    if ak in ("tradeai_automated", "alpaca_paper"):
        return "ALPACA_PAPER"
    if ak in ("alpaca_taxable_live",):
        return "ALPACA_TAXABLE"
    if ak in ("alpaca_ira_live",):
        return "ALPACA_IRA"
    return "ALPACA_PAPER"
