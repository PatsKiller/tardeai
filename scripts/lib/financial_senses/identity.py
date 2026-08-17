"""OpenFIGI canonical instrument identity provider.

A financial agent must know exactly what instrument it reasons about. This
module produces a canonical InstrumentIdentity@v1 and fails closed on
ambiguity — it never guesses when multiple instruments match. Pure resolution
logic is separate from the network resolver so it is unit-testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

from .provider import BaseProvider, Capability
from .result import Fact, FinancialSenseResult, Quality, Subject, STATUS_OK
from .source_governance import (
    SOURCE_APPROVED_MARKET_DATA,
    SOURCE_CANONICAL_INTERNAL,
    SOURCE_PRIMARY_REGULATORY,
    grade_for_source,
)

# Identity statuses.
IDENTITY_RESOLVED = "RESOLVED"
IDENTITY_AMBIGUOUS = "AMBIGUOUS"
IDENTITY_NOT_FOUND = "NOT_FOUND"
IDENTITY_CONFLICT = "CONFLICT"
IDENTITY_NOT_CONFIGURED = "NOT_CONFIGURED"

VALID_IDENTITY_STATUSES = frozenset(
    {
        IDENTITY_RESOLVED,
        IDENTITY_AMBIGUOUS,
        IDENTITY_NOT_FOUND,
        IDENTITY_CONFLICT,
        IDENTITY_NOT_CONFIGURED,
    }
)


@dataclass
class InstrumentIdentity:
    """Canonical instrument identity (InstrumentIdentity@v1)."""

    instrument_id: Optional[str] = None
    figi: Optional[str] = None
    composite_figi: Optional[str] = None
    share_class_figi: Optional[str] = None
    ticker: Optional[str] = None
    name: Optional[str] = None
    security_type: Optional[str] = None
    market_sector: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    cik: Optional[str] = None
    cusip: Optional[str] = None
    isin: Optional[str] = None
    broker_symbols: list[str] = field(default_factory=list)
    underlying_id: Optional[str] = None
    identity_status: str = IDENTITY_RESOLVED
    identity_confidence: Optional[float] = None
    source_refs: list[str] = field(default_factory=list)
    as_of: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_ticker(ticker: str) -> str:
    """Normalize a ticker to a canonical comparison form.

    Handles BRK.B / BRK-B / BRK/B style class delimiters by converting '.' and
    '-' share-class delimiters to '/', uppercasing, and stripping whitespace.
    GOOG vs GOOGL remain distinct (no collapsing).
    """
    t = (ticker or "").strip().upper()
    if not t:
        return ""
    # Share-class delimiter normalization only ('.' and '-' are ambiguous in
    # broker feeds; '/' is the canonical delimiter form used here).
    return t.replace("-", "/").replace(".", "/")


def resolve_identity(
    candidates: list[dict],
    query: Optional[dict] = None,
    existing: Optional[dict] = None,
) -> InstrumentIdentity:
    """Fail-closed resolution of candidate identities into a canonical identity.

    candidates: normalized candidate dicts (each may carry figi, ticker, name,
        security_type, market_sector, exchange, currency, cusip, isin, ...).
    query: optional constraints {ticker, exchange, security_type, share_class}.
    existing: optional existing canonical identity to prefer/compose.

    Returns an InstrumentIdentity whose status is RESOLVED (unique or
    constraint-narrowed to exactly one), AMBIGUOUS (still >1), NOT_FOUND (0),
    or CONFLICT (existing canonical id disagrees).
    """
    query = query or {}
    pool = [dict(c) for c in candidates]

    want_ticker = normalize_ticker(str(query.get("ticker") or ""))
    want_exchange = str(query.get("exchange") or "").strip().upper()
    want_type = str(query.get("security_type") or "").strip()

    if want_ticker:
        pool = [c for c in pool if normalize_ticker(str(c.get("ticker") or "")) == want_ticker]
    if want_exchange:
        pool = [c for c in pool if str(c.get("exchange") or "").upper() == want_exchange]
    if want_type:
        pool = [c for c in pool if str(c.get("security_type") or "").upper() == want_type.upper()]

    if not pool:
        return InstrumentIdentity(
            ticker=query.get("ticker"),
            identity_status=IDENTITY_NOT_FOUND,
            source_refs=["openfigi"],
            as_of=query.get("as_of"),
        )

    if len(pool) > 1:
        # Try narrowing by share-class / composite to disambiguate.
        by_figi = {c.get("figi") for c in pool if c.get("figi")}
        if len(by_figi) == 1:
            pool = [pool[0]]
        else:
            return InstrumentIdentity(
                ticker=query.get("ticker"),
                identity_status=IDENTITY_AMBIGUOUS,
                identity_confidence=None,
                source_refs=["openfigi"],
                as_of=query.get("as_of"),
            )

    cand = pool[0]
    identity = InstrumentIdentity(
        figi=cand.get("figi"),
        composite_figi=cand.get("composite_figi"),
        share_class_figi=cand.get("share_class_figi"),
        ticker=cand.get("ticker") or query.get("ticker"),
        name=cand.get("name"),
        security_type=cand.get("security_type"),
        market_sector=cand.get("market_sector"),
        exchange=cand.get("exchange"),
        currency=cand.get("currency"),
        cusip=cand.get("cusip"),
        isin=cand.get("isin"),
        cik=cand.get("cik"),
        broker_symbols=list(cand.get("broker_symbols") or []),
        underlying_id=cand.get("underlying_id"),
        identity_status=IDENTITY_RESOLVED,
        identity_confidence=cand.get("confidence"),
        source_refs=["openfigi"],
        as_of=query.get("as_of"),
    )
    identity.instrument_id = identity.figi or f"ticker:{normalize_ticker(identity.ticker or '')}"

    # Compose with an existing canonical identity: reconcile, never silently
    # overwrite a working canonical id.
    if existing:
        if existing.get("figi") and cand.get("figi") and existing["figi"] != cand.get("figi"):
            identity.identity_status = IDENTITY_CONFLICT
            identity.source_refs = ["openfigi", "canonical_internal"]
        elif existing.get("figi"):
            identity.figi = existing["figi"]
            identity.instrument_id = existing["figi"]
            identity.source_refs = ["openfigi", "canonical_internal"]

    return identity


class OpenFigiProvider(BaseProvider):
    name = "identity"
    version = "1.0.0"
    source_type = SOURCE_APPROVED_MARKET_DATA

    def __init__(
        self,
        api_key: Optional[str] = None,
        resolver: Optional[Callable[[dict], list[dict]]] = None,
        existing_identity: Optional[Callable[[dict], Optional[dict]]] = None,
    ) -> None:
        self.api_key = api_key or ""
        self._resolver = resolver or (self._openfigi_resolve if api_key else None)
        self._existing_identity = existing_identity
        self._configured = bool(api_key) or resolver is not None
        self._config_detail = "OpenFIGI not configured" if not self._configured else ""

    def _capabilities(self) -> list[Capability]:
        return [
            Capability(
                "identity.resolve",
                "READ_ONLY",
                input_schema={
                    "ticker": "string?",
                    "exchange": "string?",
                    "security_type": "string?",
                    "cusip": "string?",
                    "isin": "string?",
                    "figi": "string?",
                },
            )
        ]

    def _query(self, capability: str, request: dict) -> FinancialSenseResult:
        if not self._configured:
            return self._not_configured("identity.resolve")
        if capability != "identity.resolve":
            return self._unavailable(capability, "unknown capability")
        query = dict(request)
        if not any(query.get(k) for k in ("ticker", "cusip", "isin", "figi")):
            return self._invalid("identity.resolve", "one of ticker/cusip/isin/figi required")
        existing = None
        if self._existing_identity:
            existing = self._existing_identity(query)
        candidates = self._resolver(query) or []
        identity = resolve_identity(candidates, query, existing)
        r = self._ok("identity.resolve")
        r.subject = Subject(symbol=identity.ticker, figi=identity.figi)
        r.data = {"identity": identity.to_dict()}
        r.as_of = identity.as_of
        if identity.identity_status == IDENTITY_RESOLVED:
            r.quality = Quality(
                grade=grade_for_source(SOURCE_APPROVED_MARKET_DATA),
                completeness="COMPLETE",
            )
            r.facts.append(
                Fact(
                    key="instrument_identity",
                    value=identity.figi or identity.instrument_id,
                    source_type=SOURCE_APPROVED_MARKET_DATA,
                    source_ids=identity.source_refs,
                    as_of=identity.as_of,
                    quality=grade_for_source(SOURCE_APPROVED_MARKET_DATA),
                )
            )
        elif identity.identity_status == IDENTITY_AMBIGUOUS:
            r.set_status("PARTIAL")
            r.add_warning("identity is AMBIGUOUS; refusing to guess")
        elif identity.identity_status == IDENTITY_NOT_FOUND:
            r.set_status("PARTIAL")
            r.add_warning("identity NOT_FOUND")
        elif identity.identity_status == IDENTITY_CONFLICT:
            r.set_status("CONFLICT")
            r.add_warning("identity CONFLICT with existing canonical identity")
        return r

    def _openfigi_resolve(self, query: dict) -> list[dict]:
        """Call the OpenFIGI mapping API (used only when configured)."""
        import json
        import urllib.request

        body = []
        if query.get("ticker"):
            body.append({"idType": "TICKER", "idValue": query["ticker"]})
        if query.get("cusip"):
            body.append({"idType": "ID_CUSIP", "idValue": query["cusip"]})
        if query.get("isin"):
            body.append({"idType": "ID_ISIN", "idValue": query["isin"]})
        if query.get("figi"):
            body.append({"idType": "ID_FIGI", "idValue": query["figi"]})
        if not body:
            return []
        req = urllib.request.Request(
            "https://api.openfigi.com/v3/mapping",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-OPENFIGI-APIKEY": self.api_key},
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            payload = json.loads(resp.read())
        out = []
        for item in payload or []:
            for d in item.get("data") or []:
                out.append(
                    {
                        "figi": d.get("figi"),
                        "composite_figi": d.get("compositeFIGI"),
                        "share_class_figi": d.get("shareClassFIGI"),
                        "ticker": d.get("ticker"),
                        "name": d.get("name"),
                        "security_type": d.get("securityType"),
                        "market_sector": d.get("marketSector"),
                        "exchange": d.get("exchCode"),
                        "currency": d.get("currency"),
                        "cusip": d.get("cusip"),
                        "isin": d.get("isin"),
                        "confidence": 0.9,
                    }
                )
        return out
