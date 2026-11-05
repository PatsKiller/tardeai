"""Find an issuer's newest 10-K/10-Q through companyconcept, then fetch that filing's XBRL instance documents.

Every network request goes through ``scripts/lib/sec_edgar_client.py`` (declared contact, fails closed, process-wide
spacing). The fetcher is injectable: :class:`LiveFetcher` (network), :class:`RecordingFetcher` (network + writes each
response byte for byte with its sha256 to a fixture directory) and :class:`FixtureFetcher` (offline replay; refuses a
URL that was not recorded). No store is written here.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

try:
    from scripts.lib import sec_edgar_client as _sec
except ImportError:  # scripts/ on sys.path
    from lib import sec_edgar_client as _sec  # type: ignore

DATA = "https://data.sec.gov"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
PERIODIC_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F")
MANIFEST = "manifest.json"


class FetchError(RuntimeError):
    def __init__(self, url: str, status: Optional[int], reason: str):
        super().__init__(f"{url}: {status or ''} {reason}".strip())
        self.url, self.status, self.reason = url, status, reason


class Fetcher(Protocol):
    def get(self, url: str, accept: str = "application/json") -> bytes: ...


class LiveFetcher:
    """Network fetch through sec_edgar_client (raises SecContactError before any request when unconfigured)."""

    def get(self, url: str, accept: str = "application/json") -> bytes:
        try:
            return _sec.fetch_bytes(url, accept)
        except urllib.error.HTTPError as exc:
            raise FetchError(url, exc.code, "http_error") from None


def _fixture_name(url: str) -> str:
    tail = url.split("://", 1)[-1]
    tail = re.sub(r"^(data\.sec\.gov|www\.sec\.gov)/", "", tail)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", tail)


@dataclass
class RecordingFetcher:
    """Live fetch that also records each response + a manifest row (sha256 and length of the exact response bytes).

    Each body is stored gzip-wrapped (``mtime=0``) to keep the public repo small; :class:`FixtureFetcher` unwraps it and
    checks the sha256 of the original bytes, so a replay serves exactly what SEC returned."""

    out_dir: Path
    inner: Fetcher = field(default_factory=LiveFetcher)
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def _manifest(self) -> dict[str, Any]:
        p = Path(self.out_dir) / MANIFEST
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"schema": "EdgarFixtureManifest@v1", "entries": {}}

    def _save(self, doc: dict[str, Any]) -> None:
        p = Path(self.out_dir) / MANIFEST
        p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def get(self, url: str, accept: str = "application/json") -> bytes:
        Path(self.out_dir).mkdir(parents=True, exist_ok=True)
        doc = self._manifest()
        try:
            body = self.inner.get(url, accept)
        except FetchError as exc:
            doc["entries"][url] = {"status": exc.status, "file": None, "sha256": None, "bytes": 0,
                                   "recorded_at": self.recorded_at}
            self._save(doc)
            raise
        name = _fixture_name(url) + ".gz"
        gz = gzip.compress(body, compresslevel=9, mtime=0)  # deterministic container; the payload is unchanged
        (Path(self.out_dir) / name).write_bytes(gz)
        doc["entries"][url] = {"status": 200, "file": name, "sha256": hashlib.sha256(body).hexdigest(),
                               "bytes": len(body), "gz_sha256": hashlib.sha256(gz).hexdigest(),
                               "recorded_at": self.recorded_at}
        self._save(doc)
        return body


@dataclass
class FixtureFetcher:
    """Offline replay of a RecordingFetcher directory. Verifies the sha256 of every file it serves."""

    fixture_dir: Path

    def __post_init__(self) -> None:
        self._entries = json.loads((Path(self.fixture_dir) / MANIFEST).read_text(encoding="utf-8"))["entries"]

    def get(self, url: str, accept: str = "application/json") -> bytes:
        e = self._entries.get(url)
        if e is None:
            raise FetchError(url, None, "not_recorded")
        if e.get("status") != 200:
            raise FetchError(url, e.get("status"), "recorded_error")
        raw = (Path(self.fixture_dir) / e["file"]).read_bytes()
        body = gzip.decompress(raw) if e["file"].endswith(".gz") else raw
        if hashlib.sha256(body).hexdigest() != e["sha256"] or len(body) != e.get("bytes", len(body)):
            raise FetchError(url, None, "sha256_mismatch")
        return body


def cik10(cik: Any) -> str:
    digits = "".join(ch for ch in str(cik) if ch.isdigit())
    if not digits:
        raise ValueError("cik required")
    return digits.zfill(10)


def concept_url(cik: Any, concept: str) -> str:
    return f"{DATA}/api/xbrl/companyconcept/CIK{cik10(cik)}/us-gaap/{concept}.json"


def filing_index_url(cik: Any, accession: str) -> str:
    return f"{ARCHIVES}/{int(cik10(cik))}/{accession.replace('-', '')}/index.json"


def filing_file_url(cik: Any, accession: str, name: str) -> str:
    return f"{ARCHIVES}/{int(cik10(cik))}/{accession.replace('-', '')}/{name}"


def latest_periodic_filing(fetcher: Fetcher, cik: Any, concepts: list[str]) -> Optional[dict[str, Any]]:
    """Newest 10-K/10-Q accession across the configured revenue concepts (companyconcept, USD units).

    Returns ``{accession, form, filed, concept, consolidated: {val, start, end}}`` or None. A concept the issuer never
    used returns 404 and is skipped (HON stopped tagging ``Revenues`` after FY2011).
    """
    best: Optional[dict[str, Any]] = None
    for concept in concepts:
        try:
            doc = json.loads(fetcher.get(concept_url(cik, concept)))
        except FetchError as exc:
            if exc.status == 404 or exc.reason == "not_recorded":
                continue
            raise
        rows = [r for r in ((doc.get("units") or {}).get("USD") or []) if str(r.get("form")) in PERIODIC_FORMS]
        if not rows:
            continue
        newest = max(rows, key=lambda r: (str(r.get("filed") or ""), str(r.get("end") or "")))
        accn = newest.get("accn")
        same = [r for r in rows if r.get("accn") == accn]
        # The filing's own current-period total: the latest end, then the shortest duration (the quarter in a 10-Q).
        def _dur(r: dict[str, Any]) -> int:
            try:
                return (datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])).days
            except Exception:  # noqa: BLE001
                return 10**6
        cur = sorted(same, key=lambda r: (str(r.get("end") or ""), -_dur(r)), reverse=True)[0]
        cand = {"accession": accn, "form": newest.get("form"), "filed": newest.get("filed"), "concept": concept,
                "consolidated": {"val": cur.get("val"), "start": cur.get("start"), "end": cur.get("end")}}
        if best is None or str(cand["filed"]) > str(best["filed"]):  # tie: the earlier concept in the list wins
            best = cand
    return best


def instance_documents(fetcher: Fetcher, cik: Any, accession: str) -> dict[str, Any]:
    """The filing's XBRL instance (``*_htm.xml``), label linkbase (``*_lab.xml``) and FilingSummary.xml names."""
    idx = json.loads(fetcher.get(filing_index_url(cik, accession)))
    names = [str(i.get("name") or "") for i in ((idx.get("directory") or {}).get("item") or [])]
    inst = [n for n in names if n.endswith("_htm.xml")]
    lab = [n for n in names if n.endswith("_lab.xml")]
    return {"instance": inst[0] if inst else None, "labels": lab[0] if lab else None,
            "filing_summary": "FilingSummary.xml" if "FilingSummary.xml" in names else None}


def fetch_filing(fetcher: Fetcher, cik: Any, concepts: list[str], accession: Optional[str] = None) -> dict[str, Any]:
    """companyconcept (newest filing) -> index -> instance + labels. Returns bytes and URLs; writes nothing."""
    latest = latest_periodic_filing(fetcher, cik, concepts)
    if accession and (latest is None or latest.get("accession") != accession):
        latest = {"accession": accession, "form": None, "filed": None, "concept": None, "consolidated": None,
                  "note": "accession pinned by caller"}
    if latest is None:
        return {"status": "no_periodic_filing", "cik": cik10(cik)}
    docs = instance_documents(fetcher, cik, latest["accession"])
    if not docs["instance"]:
        return {"status": "no_xbrl_instance", "cik": cik10(cik), **latest}
    inst_url = filing_file_url(cik, latest["accession"], docs["instance"])
    out = {"status": "ok", "cik": cik10(cik), **latest, "instance_url": inst_url,
           "instance": fetcher.get(inst_url, "application/xml")}
    if docs["labels"]:
        out["labels_url"] = filing_file_url(cik, latest["accession"], docs["labels"])
        out["labels"] = fetcher.get(out["labels_url"], "application/xml")
    if docs["filing_summary"]:
        out["filing_summary_url"] = filing_file_url(cik, latest["accession"], "FilingSummary.xml")
        out["filing_summary"] = fetcher.get(out["filing_summary_url"], "application/xml")
    return out
