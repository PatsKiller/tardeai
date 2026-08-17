"""OpenFIGI canonical instrument identity provider.

A financial agent must know exactly what instrument it reasons about. This
module produces a canonical InstrumentIdentity@v1 and fails closed on
ambiguity — it never guesses when multiple instruments match.

Multiple identifiers (ticker + CUSIP + ISIN + FIGI) are cross-validated by
intersecting the FIGI sets produced by each OpenFIGI mapping job. Conflicting
inputs produce CONFLICT, never a silent RESOLVED.
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

# Current OpenFIGI v3 identifier type for a FIGI lookup.
ID_BB_GLOBAL = "ID_BB_GLOBAL"


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
    return t.replace("-", "/").replace(".", "/")


def _identity_from_candidate(cand: dict, query: dict) -> InstrumentIdentity:
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
        cusip=query.get("cusip") or cand.get("cusip"),
        isin=query.get("isin") or cand.get("isin"),
        cik=cand.get("cik"),
        broker_symbols=list(cand.get("broker_symbols") or []),
        underlying_id=cand.get("underlying_id"),
        identity_status=IDENTITY_RESOLVED,
        identity_confidence=cand.get("confidence"),
        source_refs=["openfigi"],
        as_of=query.get("as_of"),
    )
    identity.instrument_id = identity.figi or f"ticker:{normalize_ticker(identity.ticker or '')}"
    return identity


def _compose_existing(identity: InstrumentIdentity, cand: dict, existing: dict) -> None:
    """Reconcile with an existing canonical identity, never silently overwrite."""
    if existing.get("figi") and cand.get("figi") and existing["figi"] != cand.get("figi"):
        identity.identity_status = IDENTITY_CONFLICT
        identity.source_refs = ["openfigi", "canonical_internal"]
    elif existing.get("figi"):
        identity.figi = existing["figi"]
        identity.instrument_id = existing["figi"]
        identity.source_refs = ["openfigi", "canonical_internal"]


def resolve_identity(
    candidates: list[dict],
    query: Optional[dict] = None,
    existing: Optional[dict] = None,
) -> InstrumentIdentity:
    """Fail-closed resolution of a single identifier's candidate set."""
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
            cusip=query.get("cusip"),
            isin=query.get("isin"),
            identity_status=IDENTITY_NOT_FOUND,
            source_refs=["openfigi"],
            as_of=query.get("as_of"),
        )

    if len(pool) > 1:
        by_figi = {c.get("figi") for c in pool if c.get("figi")}
        if len(by_figi) == 1:
            pool = [pool[0]]
        else:
            return InstrumentIdentity(
                ticker=query.get("ticker"),
                cusip=query.get("cusip"),
                isin=query.get("isin"),
                identity_status=IDENTITY_AMBIGUOUS,
                identity_confidence=None,
                source_refs=["openfigi"],
                as_of=query.get("as_of"),
            )

    identity = _identity_from_candidate(pool[0], query)
    if existing:
        _compose_existing(identity, pool[0], existing)
    return identity


def cross_validate_identities(
    jobs: list[dict],
    query: Optional[dict] = None,
    existing: Optional[dict] = None,
):
    """Cross-validate multiple identifier mapping jobs.

    Each job is {"identifier", "id_type", "id_value", "candidates", "warning"}.
    Returns (InstrumentIdentity, notes).

    exactly one common FIGI -> RESOLVED
    >1 common FIGI          -> AMBIGUOUS
    empty intersection      -> CONFLICT
    an identifier with no candidates -> noted (PARTIAL) but not silently dropped
    """
    query = query or {}
    provided = [j for j in jobs if j.get("id_value")]
    notes: list[str] = []

    base = InstrumentIdentity(
        ticker=query.get("ticker"),
        cusip=query.get("cusip"),
        isin=query.get("isin"),
        source_refs=["openfigi"],
        as_of=query.get("as_of"),
    )

    if not provided:
        base.identity_status = IDENTITY_NOT_FOUND
        return base, ["no identifiers"]

    figi_sets: dict[str, set] = {}
    by_figi: dict[str, dict] = {}
    for j in provided:
        figis = {c.get("figi") for c in (j.get("candidates") or []) if c.get("figi")}
        figi_sets[j["identifier"]] = figis
        for c in (j.get("candidates") or []):
            if c.get("figi"):
                by_figi.setdefault(c["figi"], c)

    unavailable = [j for j in provided if not figi_sets[j["identifier"]] and not j.get("warning")]

    # Single identifier falls back to classic resolution.
    if len(provided) == 1:
        j = provided[0]
        return resolve_identity(j.get("candidates") or [], query, existing), notes

    non_empty = [figi_sets[j["identifier"]] for j in provided if figi_sets[j["identifier"]]]
    common = set.intersection(*non_empty) if non_empty else set()

    if unavailable:
        notes.append(f"identifiers unresolved: {[j['identifier'] for j in unavailable]}")

    if len(common) == 1:
        figi = next(iter(common))
        identity = _identity_from_candidate(by_figi[figi], query)
        # Supplied CUSIP/ISIN are asserted inputs, not OpenFIGI returns.
        identity.cusip = query.get("cusip")
        identity.isin = query.get("isin")
        identity.identity_status = IDENTITY_RESOLVED
        identity.source_refs = ["openfigi"]
        if existing:
            _compose_existing(identity, by_figi[figi], existing)
        return identity, notes
    elif len(common) > 1:
        base.identity_status = IDENTITY_AMBIGUOUS
        return base, notes
    else:
        base.identity_status = IDENTITY_CONFLICT
        return base, notes


def build_mapping_jobs(query: dict) -> list[dict]:
    """Build OpenFIGI v3 mapping request jobs (pure; unit-testable offline).

    Preserves input order so response index i maps to job i. FIGI lookups use
    the current official identifier type ID_BB_GLOBAL. Narrowing fields
    (exchCode, securityType) are forwarded for TICKER jobs.
    """
    jobs: list[dict] = []
    if query.get("ticker"):
        job = {"idType": "TICKER", "idValue": str(query["ticker"])}
        if query.get("exchange"):
            job["exchCode"] = str(query["exchange"])
        if query.get("security_type"):
            job["securityType"] = str(query["security_type"])
        jobs.append(job)
    if query.get("cusip"):
        jobs.append({"idType": "ID_CUSIP", "idValue": str(query["cusip"])})
    if query.get("isin"):
        jobs.append({"idType": "ID_ISIN", "idValue": str(query["isin"])})
    if query.get("figi"):
        jobs.append({"idType": ID_BB_GLOBAL, "idValue": str(query["figi"])})
    return jobs


def _parse_openfigi_job(identifier: str, id_type: str, id_value: str, item: dict) -> dict:
    candidates = []
    for d in item.get("data") or []:
        candidates.append(
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
                "confidence": 0.9,
            }
        )
    return {
        "identifier": identifier,
        "id_type": id_type,
        "id_value": id_value,
        "candidates": candidates,
        "warning": item.get("warning") or item.get("error"),
    }


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
        jobs = self._resolver(query) or []
        provided = [j for j in jobs if j.get("id_value")]
        if len(provided) > 1:
            identity, notes = cross_validate_identities(jobs, query, existing)
        else:
            candidates = (jobs[0].get("candidates") or []) if jobs else []
            identity = resolve_identity(candidates, query, existing)
            notes = []

        r = self._ok("identity.resolve")
        r.subject = Subject(symbol=identity.ticker, figi=identity.figi)
        r.data = {"identity": identity.to_dict(), "notes": notes}
        r.as_of = identity.as_of
        partial = bool(notes)
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
                    as_of=identity.as_of or r.requested_at,
                    quality=grade_for_source(SOURCE_APPROVED_MARKET_DATA),
                )
            )
            if partial:
                r.set_status("PARTIAL")
                for n in notes:
                    r.add_warning(n)
        elif identity.identity_status == IDENTITY_AMBIGUOUS:
            r.set_status("PARTIAL")
            r.add_warning("identity is AMBIGUOUS; refusing to guess")
        elif identity.identity_status == IDENTITY_NOT_FOUND:
            r.set_status("PARTIAL")
            r.add_warning("identity NOT_FOUND")
        elif identity.identity_status == IDENTITY_CONFLICT:
            r.set_status("CONFLICT")
            r.add_warning("identity CONFLICT between supplied identifiers")
        return r

    def _openfigi_resolve(self, query: dict) -> list[dict]:
        """Call OpenFIGI mapping, preserving per-job boundaries.

        Returns one job dict per supplied identifier, in input order, so
        callers can cross-validate rather than union the candidate pools.
        """
        import json
        import urllib.request

        id_specs: list[tuple[str, str, str]] = []
        if query.get("ticker"):
            id_specs.append(("ticker", "TICKER", str(query["ticker"])))
        if query.get("cusip"):
            id_specs.append(("cusip", "ID_CUSIP", str(query["cusip"])))
        if query.get("isin"):
            id_specs.append(("isin", "ID_ISIN", str(query["isin"])))
        if query.get("figi"):
            id_specs.append(("figi", ID_BB_GLOBAL, str(query["figi"])))
        if not id_specs:
            return []

        body = build_mapping_jobs(query)

        req = urllib.request.Request(
            "https://api.openfigi.com/v3/mapping",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-OPENFIGI-APIKEY": self.api_key},
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            payload = json.loads(resp.read())

        jobs = []
        for i, (identifier, id_type, id_value) in enumerate(id_specs):
            item = (payload or [])[i] if i < len(payload or []) else {}
            jobs.append(_parse_openfigi_job(identifier, id_type, id_value, item))
        return jobs
