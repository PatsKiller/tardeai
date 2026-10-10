"""provider_ticker_guard — the one check a symbol passes before it is sent to a market-data provider.

2026-10-10 (GAP 14, operator-approved): CUSIP-like identifiers (e.g. ``12507E201``) reached Finviz as tickers
and were stored as symbols (``watchlist_items``). Finviz answers an unknown ``t=`` with an empty export, so the
enrichment run still wrote a cache record for it and every later run asked again. Before this module eleven
modules each carried their own ticker regex (``^[A-Z]{1,5}$``, ``^[A-Z][A-Z0-9.\\-]{0,9}$`` ...) and the Finviz
paths carried none.

The CUSIP test is not re-invented: ``security_identity.is_cusip_like`` (the identity spine's classifier) is
the first rule; a 9-character identifier whose CUSIP check digit verifies (``G1151C101``) and a 12-character
ISIN are rejected too. Then the symbol must have an exchange-ticker shape for the profile:

* ``finviz`` (default): 1-5 letters, optional share-class suffix ``.X``/``-X``/``/X`` (1-2 letters).
  ``BRK-B``, ``BF.B``, ``AMAGX`` pass; ``12507E201``, ``US0378331005``, ``^VIX``, ``BTC-USD`` do not.
* ``quote``: the finviz shape, plus a leading ``^`` (index) and a 1-3 letter suffix (``BTC-USD``). For the
  quote fallback (``market_quote_provider``) once PR #1678 (n8nmat/broker-domains-q1) has merged.

Pure: no I/O, no network, no clock. AUTHORITY: READ_ONLY_ADVISORY; market-data symbols only, never an order.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

try:  # scripts/ on sys.path (script mode)
    from lib.security_identity import is_cusip_like
except ImportError:  # imported as scripts.lib.provider_ticker_guard
    from scripts.lib.security_identity import is_cusip_like

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ProviderTickerGuard@v1"

_SHAPES = {
    "finviz": re.compile(r"^[A-Z]{1,5}(?:[.\-/][A-Z]{1,2})?$"),
    "quote": re.compile(r"^\^?[A-Z]{1,5}(?:[.\-/][A-Z]{1,3})?$"),
}
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_CUSIP9_RE = re.compile(r"^[0-9A-Z*@#]{8}[0-9]$")


def _cusip_check_digit_ok(s: str) -> bool:
    """The CUSIP mod-10 'double-add-double' check over the first eight characters."""
    if not _CUSIP9_RE.match(s):
        return False
    total = 0
    for i, ch in enumerate(s[:8]):
        if ch.isdigit():
            v = int(ch)
        elif ch.isalpha():
            v = ord(ch) - 55  # A=10
        else:
            v = {"*": 36, "@": 37, "#": 38}[ch]
        if i % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10 == int(s[8])


def normalize(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def classify(symbol: Any, profile: str = "finviz") -> tuple[bool, str]:
    """``(ok, reason)``. Reasons: ``ok``, ``empty``, ``cusip_like``, ``isin_like``, ``not_ticker_shape``."""
    if profile not in _SHAPES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {sorted(_SHAPES)}")
    s = normalize(symbol)
    if not s:
        return False, "empty"
    compact = s.replace(" ", "")
    if is_cusip_like(compact) or (len(compact) == 9 and any(c.isdigit() for c in compact)
                                  and _cusip_check_digit_ok(compact)):
        return False, "cusip_like"
    if _ISIN_RE.match(compact) and any(c.isdigit() for c in compact[2:]):
        return False, "isin_like"
    if not _SHAPES[profile].match(s):
        return False, "not_ticker_shape"
    return True, "ok"


def is_provider_ticker(symbol: Any, profile: str = "finviz") -> bool:
    return classify(symbol, profile)[0]


def partition(symbols: Iterable[Any], profile: str = "finviz") -> tuple[list[str], list[dict[str, str]]]:
    """Split into (valid normalized symbols in first-seen order, deduplicated; rejected ``{symbol, reason}``)."""
    ok: list[str] = []
    seen: set[str] = set()
    rejected: list[dict[str, str]] = []
    for raw in symbols or []:
        good, reason = classify(raw, profile)
        s = normalize(raw)
        if not good:
            rejected.append({"symbol": s, "reason": reason})
        elif s not in seen:
            seen.add(s)
            ok.append(s)
    return ok, rejected
