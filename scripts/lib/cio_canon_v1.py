"""CanonSource@v1, CanonClaim@v1, and MethodologyPolicy@v1.

The catalog is not a corpus. A source is ingestible only with a lawful access
receipt, exact bytes, and an operator authorization. Extracted claims remain
non-authoritative until separately reviewed, shadowed, validated where relevant,
and ratified for advisory use.
"""
from __future__ import annotations

import hashlib
import html
import json
import fcntl
import os
import re
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


AUTHORITY = "READ_ONLY_ADVISORY"
SOURCE_SCHEMA = "CanonSource@v1"
CLAIM_SCHEMA = "CanonClaim@v1"
POLICY_SCHEMA = "MethodologyPolicy@v1"
LAWFUL_BASES = frozenset({"LAWFUL_PRIVATE", "PUBLIC_DOMAIN", "LICENSED"})
CLAIM_TYPES = frozenset({
    "PRINCIPLE", "HEURISTIC", "QUANTITATIVE_RULE", "RISK_RULE",
    "CONSTRUCTION_RULE", "BEHAVIORAL_RULE",
})
CLAIM_STATUSES = frozenset({"EXTRACTED", "REVIEWED", "SHADOW", "RATIFIED_ADVISORY", "REJECTED", "RETIRED"})
QUANTITATIVE_TYPES = frozenset({"QUANTITATIVE_RULE", "RISK_RULE", "CONSTRUCTION_RULE"})
SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".html", ".htm", ".pdf", ".epub"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    digest = _sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode())
    return f"{prefix}_{digest[:20]}"


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return "\n".join(self.parts)


def load_catalog(catalog_path: str | Path) -> dict[str, dict[str, Any]]:
    document = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    sources = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(sources, list):
        raise ValueError("catalog sources must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in sources:
        if not isinstance(row, dict) or not row.get("source_id"):
            raise ValueError("catalog source missing source_id")
        if row["source_id"] in result:
            raise ValueError(f"duplicate source_id:{row['source_id']}")
        result[str(row["source_id"])] = row
    return result


def catalog_maturity(catalog_path: str | Path, claims: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    claim_rows = [row for row in claims or [] if isinstance(row, dict)]
    available = [row for row in catalog.values() if row.get("full_text_status") != "NOT_FOUND_IN_FILE_LIBRARY"]
    status_counts = {status: sum(1 for row in claim_rows if row.get("status") == status) for status in sorted(CLAIM_STATUSES)}
    return {
        "schema": "CanonMaturity@v1",
        "authority": AUTHORITY,
        "catalog_total": len(catalog),
        "source_text_present": len(available),
        "missing_sources": len(catalog) - len(available),
        "source_claim_incomplete": sum(1 for row in catalog.values() if row.get("claim_status") == "SOURCE_CLAIM_INCOMPLETE"),
        "claim_counts": status_counts,
        "ratified_claim_ids": sorted(str(row.get("claim_id")) for row in claim_rows if row.get("status") == "RATIFIED_ADVISORY"),
        "rag_target": "content_embeddings",
        "new_vector_database": False,
    }


def _extract_text(path: Path) -> list[tuple[str, str, str]]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        lines = path.read_text(encoding="utf-8").splitlines()
        chunks = []
        for start in range(0, len(lines), 80):
            segment = "\n".join(lines[start:start + 80]).strip()
            if segment:
                chunks.append((f"lines {start + 1}-{min(start + 80, len(lines))}", segment, "text_lines"))
        return chunks
    if suffix in {".html", ".htm"}:
        parser = _TextHTMLParser()
        parser.feed(path.read_text(encoding="utf-8"))
        lines = parser.text().splitlines()
        return [
            (f"html text {start + 1}-{min(start + 80, len(lines))}", "\n".join(lines[start:start + 80]), "html_parser")
            for start in range(0, len(lines), 80) if lines[start:start + 80]
        ]
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF_EXTRACTION_DEPENDENCY_MISSING") from exc
        rows = []
        for page_number, page in enumerate(PdfReader(str(path)).pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                rows.append((f"page {page_number}", text, "pypdf_text"))
        return rows
    if suffix == ".epub":
        rows = []
        with zipfile.ZipFile(path) as archive:
            members = sorted(name for name in archive.namelist() if name.lower().endswith((".html", ".htm", ".xhtml")))
            for member in members:
                parser = _TextHTMLParser()
                parser.feed(archive.read(member).decode("utf-8", errors="replace"))
                text = parser.text().strip()
                if text:
                    rows.append((f"epub:{member}", text, "epub_html_parser"))
        return rows
    raise ValueError(f"unsupported source extension:{suffix}")


def admit_canon_source(
    *,
    source_id: str,
    source_path: str | Path,
    catalog_path: str | Path,
    lawful_basis: str,
    operator_authorized: bool,
    edition: str,
    verified_at: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = load_catalog(catalog_path)
    if source_id not in catalog:
        raise ValueError("source_id not in canonical catalog")
    if lawful_basis not in LAWFUL_BASES:
        raise ValueError("lawful_basis must be explicit and permitted")
    if not operator_authorized:
        raise PermissionError("operator authorization required")
    if not str(edition or "").strip():
        raise ValueError("edition/version required")
    path = Path(source_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("unsupported source type")
    source_bytes = path.read_bytes()
    source_hash = _sha256(source_bytes)
    extracted = _extract_text(path)
    if not extracted:
        raise ValueError("source produced no extractable text")
    source = catalog[source_id]
    source_record = {
        "schema": SOURCE_SCHEMA,
        "authority": AUTHORITY,
        "source_id": source_id,
        "title": source.get("title"),
        "authors": source.get("authors") or [],
        "edition": edition.strip(),
        "copyright_license_state": lawful_basis,
        "authorized_source_path": str(path),
        "source_hash": source_hash,
        "ingestion_state": "EXTRACTED",
        "claim_state": "NO_CLAIMS",
        "operator_authorized": True,
        "verified_at": verified_at or _now(),
        "rag_target": "content_embeddings",
        "new_vector_database": False,
    }
    chunks: list[dict[str, Any]] = []
    for locator, text, method in extracted:
        normalized = html.unescape(re.sub(r"\n{3,}", "\n\n", text)).strip()
        chunk_hash = _sha256(normalized.encode())
        chunks.append({
            "schema": "CanonSourceChunk@v1",
            "chunk_id": _stable_id("canon_chunk", {"source_hash": source_hash, "locator": locator, "chunk_hash": chunk_hash}),
            "source_id": source_id,
            "source_hash": source_hash,
            "locator": locator,
            "extraction_method": method,
            "content_hash": chunk_hash,
            "text": normalized,
            "rag_target": "content_embeddings",
            "rag_status": "STAGED_NOT_INDEXED",
            "authority": AUTHORITY,
        })
    source_record["chunk_count"] = len(chunks)
    source_record["extraction_methods"] = sorted({row["extraction_method"] for row in chunks})
    return source_record, chunks


def build_canon_claim(
    *,
    source_record: dict[str, Any],
    chunk: dict[str, Any],
    claim_summary: str,
    domain: str,
    asset_class: str,
    claim_type: str,
    assumptions: list[str] | None = None,
    limitations: list[str] | None = None,
    testability: str = "REVIEW_REQUIRED",
) -> dict[str, Any]:
    if source_record.get("schema") != SOURCE_SCHEMA or source_record.get("ingestion_state") != "EXTRACTED":
        raise ValueError("admitted CanonSource@v1 required")
    if chunk.get("source_id") != source_record.get("source_id") or chunk.get("source_hash") != source_record.get("source_hash"):
        raise ValueError("claim source/chunk mismatch")
    if not chunk.get("locator") or not chunk.get("content_hash"):
        raise ValueError("exact source locator and chunk hash required")
    if claim_type not in CLAIM_TYPES:
        raise ValueError("invalid claim type")
    summary = str(claim_summary or "").strip()
    if not summary:
        raise ValueError("claim summary required")
    identity = {
        "source_id": source_record["source_id"],
        "source_hash": source_record["source_hash"],
        "locator": chunk["locator"],
        "chunk_hash": chunk["content_hash"],
        "summary": summary,
    }
    return {
        "schema": CLAIM_SCHEMA,
        "authority": AUTHORITY,
        "claim_id": _stable_id("canon_claim", identity),
        "source_id": source_record["source_id"],
        "claim_summary": summary,
        "exact_source_locator": chunk["locator"],
        "source_hash": source_record["source_hash"],
        "source_chunk_hash": chunk["content_hash"],
        "domain": domain,
        "asset_class": asset_class,
        "claim_type": claim_type,
        "assumptions": assumptions or [],
        "limitations": limitations or [],
        "support_refs": [chunk["chunk_id"]],
        "contradiction_refs": [],
        "testability": testability,
        "status": "EXTRACTED",
        "decision_eligible": False,
        "created_at": _now(),
    }


def transition_claim(
    claim: dict[str, Any],
    *,
    target_status: str,
    review_receipt: str | None = None,
    shadow_receipt: str | None = None,
    validation_receipt: str | None = None,
    operator_ratified: bool = False,
) -> dict[str, Any]:
    if target_status not in CLAIM_STATUSES:
        raise ValueError("invalid claim status")
    current = str(claim.get("status") or "")
    allowed = {
        "EXTRACTED": {"REVIEWED", "REJECTED"},
        "REVIEWED": {"SHADOW", "REJECTED"},
        "SHADOW": {"RATIFIED_ADVISORY", "REJECTED", "RETIRED"},
        "RATIFIED_ADVISORY": {"RETIRED"},
    }
    if target_status not in allowed.get(current, set()):
        raise ValueError(f"invalid transition:{current}->{target_status}")
    if target_status == "REVIEWED" and not review_receipt:
        raise ValueError("review receipt required")
    if target_status == "SHADOW" and not shadow_receipt:
        raise ValueError("shadow receipt required")
    if target_status == "RATIFIED_ADVISORY":
        if not operator_ratified:
            raise PermissionError("operator ratification required")
        if claim.get("claim_type") in QUANTITATIVE_TYPES and not validation_receipt:
            raise ValueError("quantitative validation receipt required")
    updated = dict(claim)
    updated.update({
        "status": target_status,
        "decision_eligible": target_status == "RATIFIED_ADVISORY",
        "review_receipt": review_receipt or claim.get("review_receipt"),
        "shadow_receipt": shadow_receipt or claim.get("shadow_receipt"),
        "validation_receipt": validation_receipt or claim.get("validation_receipt"),
        "operator_ratified": bool(operator_ratified) if target_status == "RATIFIED_ADVISORY" else claim.get("operator_ratified", False),
        "status_changed_at": _now(),
    })
    return updated


def build_methodology_policy(claims: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in claims if isinstance(row, dict) and row.get("schema") == CLAIM_SCHEMA]
    ratified = sorted(str(row["claim_id"]) for row in valid if row.get("status") == "RATIFIED_ADVISORY" and row.get("decision_eligible") is True)
    payload = {
        "schema": POLICY_SCHEMA,
        "authority": AUTHORITY,
        "ratified_advisory_claim_ids": ratified,
        "reviewed_claim_ids": sorted(str(row["claim_id"]) for row in valid if row.get("status") == "REVIEWED"),
        "shadow_claim_ids": sorted(str(row["claim_id"]) for row in valid if row.get("status") == "SHADOW"),
        "decision_influence": "RATIFIED_CLAIMS_ONLY",
        "automatic_promotion": False,
        "financial_action": False,
    }
    payload["version"] = _stable_id("methodology_policy", payload)
    return payload


def load_canon_claims(store_path: str | Path) -> list[dict[str, Any]]:
    path = Path(store_path)
    if not path.exists():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        claim = row.get("claim") if isinstance(row, dict) else None
        if isinstance(claim, dict) and claim.get("schema") == CLAIM_SCHEMA and claim.get("claim_id"):
            latest[str(claim["claim_id"])] = claim
    return sorted(latest.values(), key=lambda row: str(row["claim_id"]))


def append_claim_candidate(claim: dict[str, Any], *, store_path: str | Path) -> dict[str, Any]:
    if claim.get("schema") != CLAIM_SCHEMA or claim.get("status") != "EXTRACTED":
        raise ValueError("only extracted CanonClaim@v1 candidates may be appended")
    if claim.get("decision_eligible") is not False:
        raise ValueError("candidate cannot be decision eligible")
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o640)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        existing = {row["claim_id"] for row in load_canon_claims(path)}
        if claim["claim_id"] in existing:
            return {"appended": False, "reason": "DUPLICATE_CLAIM_ID", "claim_id": claim["claim_id"]}
        record = {
            "record_type": "CANON_CLAIM_CANDIDATE",
            "recorded_at": _now(),
            "claim": claim,
            "authority": AUTHORITY,
        }
        record["record_hash"] = _sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {"appended": True, "reason": "NEW_EXTRACTED_CANDIDATE", "claim_id": claim["claim_id"]}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
