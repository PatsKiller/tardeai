"""Shadow run: fetch (or replay) -> parse -> map -> a receipt file under a temp or runtime path. Never a store.

The issuer_segments store and its §7A grant are not approved yet (DSN-20261101 §6). Until they are, extraction output
exists only as this receipt; nothing in scripts/lib/market_risk/ reads it and config/issuer_segments.json stays the
only live source. :func:`write_receipt` refuses any path that is not under the temp directory or a ``data/runtime``
directory, so a shadow run cannot land in config/ or the repository tree.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import classifier, edgar_fetch, mapping, xbrl_segments

SCHEMA = "IssuerSegmentsShadow@v1"


def extract_issuer(fetcher: edgar_fetch.Fetcher, *, symbol: str, cik: Any, profile_group: Optional[str],
                   cfg: dict[str, Any], accession: Optional[str] = None) -> dict[str, Any]:
    ext = cfg["extraction"]
    try:
        got = edgar_fetch.fetch_filing(fetcher, cik, list(ext["revenue_concepts"]), accession=accession)
    except edgar_fetch.FetchError as exc:
        return {"symbol": symbol, "cik": edgar_fetch.cik10(cik), "status": "fetch_failed",
                "error": {"url": exc.url, "status": exc.status, "reason": exc.reason}, "flags": ["no_filing_split"]}
    if got.get("status") != "ok":
        return {"symbol": symbol, "cik": edgar_fetch.cik10(cik), "status": got.get("status"), "flags": ["no_filing_split"]}
    labels = xbrl_segments.parse_labels(got.get("labels"))
    parsed = xbrl_segments.parse_instance(
        got["instance"], revenue_concepts=list(ext["revenue_concepts"]), segment_axis=ext["segment_axis"],
        drilldown_axes=list(ext["drilldown_axes"]), consolidation_axis=ext["consolidation_axis"],
        operating_segments_member=ext["operating_segments_member"],
        reconciling_members=list(ext["reconciling_members"]), labels=labels,
        sum_tolerance=float(ext.get("sum_tolerance", 0.01)))
    split = mapping.map_issuer(parsed, cik=cik, symbol=symbol, profile_group=profile_group, cfg=cfg)
    split["classifier"] = [classifier.classify(q) for q in split.get("queue") or []]
    split["source"] = {"accession": got.get("accession"), "form": got.get("form"), "filed": got.get("filed"),
                       "companyconcept": got.get("concept"), "companyconcept_total": got.get("consolidated"),
                       "instance_url": got.get("instance_url"), "filing_summary_url": got.get("filing_summary_url")}
    split["basis_kind"] = "filing" if split.get("status") == "ok" else "profile_fallback"
    return split


def run(issuers: list[dict[str, Any]], fetcher: edgar_fetch.Fetcher, cfg: dict[str, Any], *, mode: str,
        now: Optional[datetime] = None) -> dict[str, Any]:
    results = [extract_issuer(fetcher, symbol=i["symbol"], cik=i["cik"], profile_group=i.get("profile_group"),
                              cfg=cfg, accession=i.get("accession")) for i in issuers]
    return build_receipt(results, mode=mode, now=now)


def build_receipt(results: list[dict[str, Any]], *, mode: str, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    return {"schema": SCHEMA, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": mode,
            "shadow": True, "store_written": False, "live_lookthrough_wired": False,
            "live_source": "config/issuer_segments.json (APPROVED entries only)",
            "issuers": results}


def _allowed_receipt_path(path: Path) -> bool:
    p = path.expanduser().resolve()
    roots = {Path(tempfile.gettempdir()).resolve()}
    if os.environ.get("TMPDIR"):
        roots.add(Path(os.environ["TMPDIR"]).resolve())
    if any(p.is_relative_to(r) for r in roots):
        return True
    parts = p.parts
    return any(parts[i] == "data" and parts[i + 1] == "runtime" for i in range(len(parts) - 1))


def default_receipt_path(now: Optional[datetime] = None) -> Path:
    now = now or datetime.now(timezone.utc)
    return Path(tempfile.gettempdir()) / "tradeai-issuer-segments-shadow" / f"receipt-{now.strftime('%Y%m%dT%H%M%SZ')}.json"


def write_receipt(receipt: dict[str, Any], path: Path) -> Path:
    from ..market_risk.contract import assert_no_behavior_fields  # payload never carries weight/size/order keys

    if not _allowed_receipt_path(Path(path)):
        raise PermissionError(f"shadow receipt must go under the temp directory or a data/runtime directory: {path}")
    assert_no_behavior_fields(receipt)
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p
