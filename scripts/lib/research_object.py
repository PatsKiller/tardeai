"""ResearchObject@v1 — immutable research identity + provenance (Lane C).

Maintains: research_id, subject_guid, source_url, authoritative-source ranking,
capture_time, content_hash, provenance, and multi-security mention roles.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from scripts.lib.campaign_interfaces_c import (
    INTERFACE_VERSION,
    canonical_url,
    mint_research_object_id,
)

SCHEMA = "ResearchObject@v1"
Clock = Callable[[], datetime]

# Authoritative-source ranking: lower rank number = more authoritative.
SOURCE_RANK = {
    "sec.gov": 1,
    "edgar": 1,
    "federalreserve.gov": 2,
    "bls.gov": 2,
    "reuters.com": 3,
    "bloomberg.com": 3,
    "wsj.com": 3,
    "ft.com": 3,
    "nytimes.com": 4,
    "cnbc.com": 5,
    "yahoo.com": 6,
    "seekingalpha.com": 7,
    "default": 50,
}

MENTION_ROLES = frozenset({"primary", "mentioned", "compared", "sector_peer"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def rank_source(url: str) -> int:
    host = ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    for needle, rank in SOURCE_RANK.items():
        if needle == "default":
            continue
        if host == needle or host.endswith("." + needle):
            return rank
    return SOURCE_RANK["default"]


@dataclass(frozen=True)
class SecurityMention:
    symbol: str
    subject_guid: Optional[str]
    role: str  # primary | mentioned | compared | sector_peer

    def __post_init__(self) -> None:
        if self.role not in MENTION_ROLES:
            raise ValueError(f"invalid mention role: {self.role}")
        if not self.symbol:
            raise ValueError("symbol required")


@dataclass
class ResearchObject:
    research_id: str
    subject_guid: str
    source_url: str
    source_url_canonical: str
    published_at: str
    captured_at: str
    content_hash: str
    title: str
    body: str
    authoritative_source_rank: int
    mentions: list[dict[str, Any]]
    provenance: dict[str, Any]
    schema_version: str = SCHEMA
    interface_version: str = INTERFACE_VERSION
    lifecycle_state: str = "INGESTED"
    correlation_id: str = ""
    idempotency_key: str = ""
    source_sha: str = ""
    retention_class: str = "evidence_2y"
    parent_id: Optional[str] = None
    parent_kind: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def primary_symbol(self) -> Optional[str]:
        for m in self.mentions:
            if m.get("role") == "primary":
                return m.get("symbol")
        return None

    def mentioned_symbols(self) -> list[str]:
        return [m["symbol"] for m in self.mentions if m.get("role") != "primary"]


def validate_provenance(prov: Mapping[str, Any]) -> None:
    if not isinstance(prov, Mapping):
        raise ValueError("provenance must be a mapping")
    if "producer" not in prov:
        raise ValueError("missing provenance.producer")
    if "inputs" not in prov or not isinstance(prov["inputs"], list):
        raise ValueError("provenance.inputs must be a list")


def validate_url(url: str) -> str:
    cu = canonical_url(url)
    if not (cu.startswith("http://") or cu.startswith("https://")):
        raise ValueError(f"source_url must be http(s): {cu}")
    return cu


def build_research_object(
    *,
    source_url: str,
    title: str,
    body: str,
    primary_symbol: str,
    primary_subject_guid: str,
    mentioned: Sequence[Mapping[str, Any]] | None = None,
    published_at: str = "",
    captured_at: Optional[str] = None,
    producer: str = "brave_router",
    policy_decisions: Optional[list] = None,
    source_sha: str = "fixture",
    correlation_id: str = "",
    clock: Optional[Clock] = None,
    provenance_extra: Optional[Mapping[str, Any]] = None,
) -> ResearchObject:
    """Build an immutable research object. Mentions are preserved, never collapsed."""
    clock = clock or _utc_now
    now = clock()
    cu = validate_url(source_url)
    pub = published_at or now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    cap = captured_at or now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not primary_subject_guid:
        raise ValueError("primary_subject_guid required")
    if not primary_symbol:
        raise ValueError("primary_symbol required")

    mentions: list[dict[str, Any]] = [
        {
            "symbol": primary_symbol.upper(),
            "subject_guid": primary_subject_guid,
            "role": "primary",
        }
    ]
    seen = {primary_symbol.upper()}
    for m in mentioned or []:
        sym = str(m.get("symbol") or "").strip().upper()
        if not sym or sym in seen:
            continue
        role = str(m.get("role") or "mentioned")
        if role not in MENTION_ROLES:
            role = "mentioned"
        if role == "primary":
            role = "mentioned"  # only one primary
        mentions.append(
            {
                "symbol": sym,
                "subject_guid": m.get("subject_guid"),
                "role": role,
            }
        )
        seen.add(sym)

    ch = content_hash(f"{title}\n{body}\n{cu}")
    rid = mint_research_object_id(cu, pub, primary_subject_guid)
    prov: dict[str, Any] = {
        "producer": producer,
        "inputs": [{"source_url": cu, "title": title}],
        "policy_decisions": list(policy_decisions or []),
        "llm": None,
        "content_hash": ch,
        "capture_time": cap,
    }
    if provenance_extra:
        prov.update(dict(provenance_extra))
    validate_provenance(prov)

    return ResearchObject(
        research_id=rid,
        subject_guid=primary_subject_guid,
        source_url=source_url,
        source_url_canonical=cu,
        published_at=pub,
        captured_at=cap,
        content_hash=ch,
        title=title,
        body=body,
        authoritative_source_rank=rank_source(cu),
        mentions=mentions,
        provenance=prov,
        correlation_id=correlation_id or rid,
        idempotency_key=rid,
        source_sha=source_sha,
        lifecycle_state="IDENTIFIED",
    )
