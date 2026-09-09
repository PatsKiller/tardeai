"""Provenance quarantine for synthetic provider ids in production deliveries.

Lane E: exclude by delivery_id + row hash + provenance_class — never channel-wide.
Does not rewrite or delete historical rows.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


NO_CONSUMER_REASON = (
    "maturity-gap-closure-20260909 hermetic lane helpers; serving-SHA producers/"
    "consumers await merge+promote+operator grants (telegram/service/drive). "
    "Zero live consumers is correct until then — not a silent dark contract "
    "(MBI_BEHAVIOR=0; recommendation≠mutation)."
)

log = logging.getLogger("tradeai.delivery_provenance_quarantine")

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = _ROOT / "config" / "delivery_provenance_quarantine.json"

_SYNTHETIC_PMID_RE = re.compile(
    r"^(wamid\.test(_\d+)?|test[_-]?message|fake[_-]?pmid|synthetic[_-])",
    re.IGNORECASE,
)


@lru_cache(maxsize=4)
def load_quarantine(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else _DEFAULT
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != "DeliveryProvenanceQuarantine@v1":
        raise ValueError(f"unexpected quarantine schema: {data.get('schema')}")
    return data


def quarantine_index(path: str | None = None) -> dict[str, dict[str, Any]]:
    data = load_quarantine(path)
    out: dict[str, dict[str, Any]] = {}
    for entry in data.get("entries") or []:
        did = str(entry.get("delivery_id") or "").strip()
        if did:
            out[did] = dict(entry)
    return out


def is_quarantined_delivery(
    *,
    delivery_id: str | None,
    row_sha256: str | None = None,
    provider_message_id: str | None = None,
    path: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Match exact delivery_id; when row_sha256 provided it must also match."""
    did = str(delivery_id or "").strip()
    if not did:
        return False, None
    entry = quarantine_index(path).get(did)
    if not entry:
        return False, None
    expected = str(entry.get("row_sha256") or "").strip()
    if row_sha256 and expected and str(row_sha256).strip() != expected:
        log.warning(
            "quarantine_row_hash_mismatch delivery_id=%s expected=%s got=%s",
            did,
            expected[:16],
            str(row_sha256)[:16],
        )
        return False, entry
    if provider_message_id:
        exp_pmid = str(entry.get("provider_message_id") or "").strip()
        if exp_pmid and str(provider_message_id).strip() != exp_pmid:
            return False, entry
    return True, entry


def exclude_quarantined(
    rows: Iterable[dict[str, Any]], *, path: str | None = None
) -> list[dict[str, Any]]:
    """Filter maturity-count rows; never drops an entire channel."""
    kept: list[dict[str, Any]] = []
    for row in rows:
        q, _ = is_quarantined_delivery(
            delivery_id=row.get("delivery_id"),
            row_sha256=row.get("row_sha256"),
            provider_message_id=row.get("provider_message_id"),
            path=path,
        )
        if not q:
            kept.append(row)
    return kept


def detect_synthetic_provider_ids(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Contamination detector: flag synthetic-looking provider ids in any channel."""
    hits: list[dict[str, Any]] = []
    for row in rows:
        pmid = str(row.get("provider_message_id") or "").strip()
        if not pmid:
            continue
        if _SYNTHETIC_PMID_RE.match(pmid) or pmid.lower().endswith(".test_1"):
            hits.append(
                {
                    "delivery_id": row.get("delivery_id"),
                    "channel": row.get("channel"),
                    "provider_message_id": pmid,
                    "provenance_class": "SYNTHETIC_TEST_PROVIDER_ID",
                    "already_quarantined": is_quarantined_delivery(
                        delivery_id=row.get("delivery_id"),
                        row_sha256=row.get("row_sha256"),
                        provider_message_id=pmid,
                        path=None,
                    )[0],
                }
            )
    return hits


def maturity_sql_exclusion_predicate(alias: str = "d") -> str:
    """SQL fragment excluding quarantined delivery_ids (not channels)."""
    ids = sorted(quarantine_index().keys())
    if not ids:
        return "TRUE"
    quoted = ", ".join("'" + i.replace("'", "''") + "'" for i in ids)
    return f"{alias}.delivery_id NOT IN ({quoted})"
