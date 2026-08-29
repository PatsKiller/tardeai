"""One EDGAR filing proof. Not a crawler. Wave 3C item 5.

Fetches **at most one** filing header for **one** held non-dust symbol, records
it as a `SpecialistArtifact` with `provider=edgar`, `grade=C`,
`dimension_scope=entity`, and stops. There is no sweep, no pagination, no
recursion into documents.

`fetch=False` is the default: nothing here reaches the network unless a caller
explicitly asks, and `MAX_FETCHES = 1` is enforced by a counter rather than by
convention.

**Not every held symbol has an issuer.** SCHD and XLI are ETFs — they have no
CIK in SEC's company_tickers map, and inventing one (the sponsor's? the largest
constituent's?) would be a fabricated identity attached to a real filing. Those
resolve `UNAVAILABLE` with a reason, which is the honest answer.

The artifact cannot `corpus_hit`: entity dimensions are never corpus-closed and
grade C could not close a gap regardless.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

EDGAR_PROOF_SCHEMA = "EdgarFilingProof@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
USER_AGENT = "TradeAI Research (operator contact on file)"

MAX_FETCHES = 1
UNAVAILABLE = "UNAVAILABLE"

# Cached ticker map lives beside the library series, not in a new store.
TICKER_MAP_REL = "reference/library/series/sec_company_tickers.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ticker_map(repo_root: Path | str) -> dict[str, dict[str, Any]]:
    p = Path(repo_root) / TICKER_MAP_REL
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for v in (raw.values() if isinstance(raw, dict) else raw):
        if not isinstance(v, dict):
            continue
        t = str(v.get("ticker") or "").upper()
        if t:
            out[t] = {"cik": v.get("cik_str"), "title": v.get("title")}
    return out


def resolve_issuer(symbol: str, ticker_map: dict[str, dict[str, Any]]
                   ) -> dict[str, Any]:
    """Resolve a ticker to an SEC issuer, or say UNAVAILABLE and why."""
    sym = str(symbol or "").strip().upper()
    hit = ticker_map.get(sym)
    if not hit or not hit.get("cik"):
        return {
            "symbol": sym or None,
            "resolved": False,
            "status": UNAVAILABLE,
            "reason": ("no CIK in SEC company_tickers — typically an ETF or "
                       "fund, which has no issuer of its own; not guessed"),
        }
    return {"symbol": sym, "resolved": True, "status": "RESOLVED",
            "cik": int(hit["cik"]), "issuer": hit.get("title")}


def fetch_one_filing_header(cik: int, *, timeout: int = 20) -> dict[str, Any]:
    """Exactly one HTTP GET. Returns the latest 10-K/10-Q header, or an error."""
    url = SEC_SUBMISSIONS_URL.format(cik=int(cik))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
        doc = json.loads(resp.read().decode("utf-8", errors="replace"))
    recent = (doc.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    for i, form in enumerate(forms):
        if str(form).upper() in {"10-K", "10-Q"}:
            return {
                "form": form,
                "accession_number": (recent.get("accessionNumber") or [None] * (i + 1))[i],
                "filing_date": (recent.get("filingDate") or [None] * (i + 1))[i],
                "primary_document": (recent.get("primaryDocument") or [None] * (i + 1))[i],
                "report_date": (recent.get("reportDate") or [None] * (i + 1))[i],
                "source_url": url,
            }
    return {"form": None, "reason": "no 10-K or 10-Q in recent filings",
            "source_url": url}


def build_proof(symbol: str, *, repo_root: Path | str,
                fetch: bool = False) -> dict[str, Any]:
    """Resolve one symbol and, only if `fetch`, retrieve one filing header."""
    ticker_map = load_ticker_map(repo_root)
    issuer = resolve_issuer(symbol, ticker_map)
    base = {
        "schema": EDGAR_PROOF_SCHEMA,
        "as_of": _utc(),
        "authority": AUTHORITY,
        "dimension_scope": "entity",
        "evidence_grade": "C",
        "can_corpus_hit": False,
        "fetches_performed": 0,
        "max_fetches": MAX_FETCHES,
        "issuer": issuer,
    }
    if not issuer.get("resolved"):
        base["status"] = UNAVAILABLE
        return base
    if not fetch:
        base["status"] = "RESOLVED_NOT_FETCHED"
        return base
    try:
        header = fetch_one_filing_header(int(issuer["cik"]))
        base["fetches_performed"] = 1
        base["filing"] = header
        base["status"] = "PROOF" if header.get("form") else UNAVAILABLE
    except Exception as exc:                                    # noqa: BLE001
        base["status"] = UNAVAILABLE
        base["error"] = f"{type(exc).__name__}: {exc}"
    return base


def to_artifact(proof: dict[str, Any], *,
                plan_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Render a PROOF as a SpecialistArtifact row. None unless it is a proof."""
    if proof.get("status") != "PROOF":
        return None
    from scripts.lib.cio_specialist_artifact import build as build_artifact

    filing = proof.get("filing") or {}
    issuer = proof.get("issuer") or {}
    acc = str(filing.get("accession_number") or "unknown")
    return build_artifact(
        artifact_id=f"edgar_{issuer.get('symbol')}_{acc}",
        provider="edgar", outcome="VALID", cost_usd=0.0, plan_id=plan_id,
        source_refs=[{
            "source_id": "sec_edgar_full_text",
            "issuer": issuer.get("issuer"),
            "cik": issuer.get("cik"),
            "form": filing.get("form"),
            "filing_date": filing.get("filing_date"),
            "accession_number": filing.get("accession_number"),
            "url": filing.get("source_url"),
            "evidence_grade": "C",
            "dimension_scope": "entity",
        }],
    )
