"""Security / listing identity — ticker is an alias, not the permanent spine.

Ticker GUIDs remain the historical UUIDv5(symbol) namespace for idempotency.
Issuer / security / listing GUIDs are additive. Missing CIK/CUSIP/ISIN/FIGI is
allowed; those fields are never invented.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
ISSUER_SCHEMA = "IssuerIdentity@v1"
SECURITY_SCHEMA = "SecurityIdentity@v1"
LISTING_SCHEMA = "ListingIdentity@v1"
ALIAS_SCHEMA = "TickerAlias@v1"

_CUSIP_RE = re.compile(r"^[0-9]{3}[0-9A-Z]{5}[0-9]$")
_FUND_SUFFIX = ("X",)  # mutual-fund tickers often end in X (AMAGX, FSELX)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _uuid(namespace: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:{namespace}:{value}"))


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def is_cusip_like(value: str) -> bool:
    s = normalize_symbol(value).replace(" ", "")
    return bool(_CUSIP_RE.match(s)) and not s.isalpha()


def classify_unresolved_symbol(symbol: str) -> dict[str, Any]:
    """Classify without inventing sector/catalyst metadata."""
    sym = normalize_symbol(symbol)
    if not sym:
        return {"symbol": "", "kind": "invalid", "reason": "empty"}
    if is_cusip_like(sym):
        return {"symbol": sym, "kind": "cusip_or_fixed_income", "reason": "nine_char_cusip_like"}
    if len(sym) == 5 and sym.endswith("X") and sym.isalpha():
        return {"symbol": sym, "kind": "fund", "reason": "five_letter_x_fund_convention"}
    if not sym.isalpha() or not (1 <= len(sym) <= 5):
        return {"symbol": sym, "kind": "invalid_or_stale", "reason": "not_equity_ticker_shape"}
    return {"symbol": sym, "kind": "equity_unresolved", "reason": "no_canonical_symbol_card"}


def issuer_guid(*, cik: str | None = None, company: str | None = None) -> str | None:
    cik_n = str(cik or "").strip()
    if cik_n:
        return _uuid("issuer:cik", cik_n.zfill(10))
    company_n = str(company or "").strip().casefold()
    if company_n:
        return _uuid("entity:issuer", company_n)
    return None


def security_guid(
    *,
    issuer: str | None,
    share_class: str = "common",
    instrument: str = "equity",
) -> str | None:
    if not issuer:
        return None
    payload = "|".join((issuer, str(share_class or "common").casefold(), str(instrument or "equity").casefold()))
    return _uuid("security", payload)


def listing_guid(*, security: str | None, exchange: str = "UNKNOWN", symbol: str) -> str | None:
    sym = normalize_symbol(symbol)
    if not security or not sym:
        return None
    payload = "|".join((security, str(exchange or "UNKNOWN").upper(), sym))
    return _uuid("listing", payload)


def attach_identity_v2(profile: dict[str, Any], *, observed_at: str | None = None) -> dict[str, Any]:
    """Add issuer/security/listing GUIDs onto an existing ticker profile. Non-destructive."""
    row = dict(profile or {})
    sym = normalize_symbol(row.get("symbol"))
    if not sym:
        return row
    as_of = observed_at or _now()
    cik = row.get("cik") or (row.get("identifiers") or {}).get("cik")
    company = row.get("company")
    ig = row.get("issuer_guid") or issuer_guid(cik=cik, company=company)
    instrument = str(row.get("classification") or "equity").lower()
    if instrument in ("unknown", "", "stock", "equity_unresolved"):
        instrument = "equity"
    elif instrument == "etf":
        instrument = "etf"
    elif instrument == "fund":
        instrument = "fund"
    sg = row.get("security_guid") or security_guid(
        issuer=ig,
        share_class=str(row.get("share_class") or "common"),
        instrument=instrument,
    )
    lg = row.get("listing_guid") or listing_guid(
        security=sg,
        exchange=str(row.get("exchange") or "UNKNOWN"),
        symbol=sym,
    )
    alias = {
        "schema": ALIAS_SCHEMA,
        "ticker_guid": row.get("ticker_guid"),
        "listing_guid": lg,
        "security_guid": sg,
        "issuer_guid": ig,
        "symbol": sym,
        "valid_from": row.get("valid_from"),
        "valid_to": row.get("valid_to"),
        "observed_at": as_of,
        "source": row.get("source") or "ticker_knowledge_profile",
        "authority": AUTHORITY,
        "financial_action": False,
    }
    row.setdefault("issuer_guid", ig)
    row.setdefault("security_guid", sg)
    row.setdefault("listing_guid", lg)
    row.setdefault("ticker_alias", alias)
    row.setdefault("identity_status", "CONFIRMED" if company else "CANDIDATE")
    row.setdefault("identity_schema", "SecurityIdentityBundle@v1")
    return row
