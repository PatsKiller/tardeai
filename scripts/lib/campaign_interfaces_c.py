"""VENDORED: replaced by campaign_interfaces at integration.

Lane C local copy of CampaignInterfaces@v1 identifier helpers needed to mint
ResearchObjectId and ConsumptionReceiptId before the integration-owned module
lands. Do not import this from other lanes.
"""
from __future__ import annotations

import uuid
from typing import Optional

# Fixed namespaces — must match the integration module when it lands.
NS_RESEARCH = uuid.UUID("a7c3e910-5b2d-4f81-9c44-1d6e8a0b3f27")
NS_RECEIPT = uuid.UUID("b8d4f021-6c3e-5092-ad55-2e7f9b1c4038")
NS_WAKE = uuid.UUID("c9e5a132-7d4f-61a3-be66-3f80ac2d5149")

INTERFACE_VERSION = "CampaignInterfaces@v1"


def mint_research_object_id(
    source_url_canonical: str,
    published_at: str,
    subject_guid: str,
) -> str:
    key = f"{source_url_canonical}|{published_at}|{subject_guid}"
    return str(uuid.uuid5(NS_RESEARCH, key))


def mint_consumption_receipt_id(
    agent_id: str,
    source_kind: str,
    source_id: str,
    purpose: str,
) -> str:
    key = f"{agent_id}|{source_kind}|{source_id}|{purpose}"
    return str(uuid.uuid5(NS_RECEIPT, key))


def mint_wake_id(
    agent_id: str,
    wake_reason: str,
    schedule_slot_utc: str,
    subject_guid: str,
) -> str:
    key = f"{agent_id}|{wake_reason}|{schedule_slot_utc}|{subject_guid}"
    return str(uuid.uuid5(NS_WAKE, key))


def canonical_url(url: str) -> str:
    """Normalize a source URL for identity. Strip fragment and trailing slash."""
    u = (url or "").strip()
    if not u:
        raise ValueError("source_url required")
    if "#" in u:
        u = u.split("#", 1)[0]
    if u.endswith("/") and u.count("/") > 2:
        u = u.rstrip("/")
    return u
