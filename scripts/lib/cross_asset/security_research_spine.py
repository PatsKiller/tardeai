"""SecurityResearchSpine@v1 — CIO-owned shared research memory per security.

Problem this closes: options / holdings / watchlist / re-entry each gather or
cache research independently. For one subject_guid, the house must have ONE
spine every silo reads.

Authority: READ_ONLY_ADVISORY. Writers append contributions; readers merge.
Does not place orders.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "SecurityResearchSpine@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
DEFAULT_REL = Path("data") / "cio" / "security_research_spine.jsonl"

# Silos that must read the same spine (documented contract).
CONSUMER_SILOS = frozenset({
    "cio",
    "hermes",
    "options_desk",
    "watchlist",
    "reentry",
    "holdings",
    "cross_asset",
    "aegis",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[3]
    return base / DEFAULT_REL


def empty_spine(symbol: str, *, subject_guid: str | None = None) -> dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    if not sym:
        raise ValueError("symbol_required")
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "symbol": sym,
        "subject_guid": subject_guid,
        "owner": "cio",
        "as_of": _now(),
        "thesis": {
            "state": "INSUFFICIENT_DATA",
            "stance": None,
            "summary": None,
            "conviction": None,
            "invalidation": [],
        },
        "contributions": [],  # {silo, artifact_id, kind, summary, ts, refs}
        "by_silo": {s: {"last_read_at": None, "last_write_at": None} for s in sorted(CONSUMER_SILOS)},
        "latest_hermes": {"research_id": None, "result_id": None, "status": None, "as_of": None},
        "transparency": {
            "shared_across_silos": True,
            "note": "All consumer silos MUST read this spine; do not fork private thesis copies",
        },
    }


def validate_spine(obj: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return {"ok": False, "errors": ["not_a_dict"]}
    if obj.get("schema") != SCHEMA:
        errors.append(f"schema_expected_{SCHEMA}")
    if obj.get("authority") != AUTHORITY:
        errors.append("authority_must_be_READ_ONLY_ADVISORY")
    if obj.get("owner") != "cio":
        errors.append("owner_must_be_cio")
    if not str(obj.get("symbol") or "").strip():
        errors.append("symbol_required")
    if not isinstance(obj.get("contributions"), list):
        errors.append("contributions_must_be_list")
    return {"ok": not errors, "errors": errors}


def contribute(
    spine: dict[str, Any],
    *,
    silo: str,
    kind: str,
    summary: str | None = None,
    artifact_id: str | None = None,
    refs: list[str] | None = None,
    thesis_patch: dict[str, Any] | None = None,
    hermes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a contribution from a silo; optional thesis/hermes upgrade."""
    out = deepcopy(spine)
    silo_n = str(silo or "unknown").strip().lower()
    ts = _now()
    out["contributions"] = list(out.get("contributions") or [])
    out["contributions"].append({
        "silo": silo_n,
        "kind": kind,
        "summary": (summary or "")[:800] or None,
        "artifact_id": artifact_id,
        "refs": list(refs or [])[:20],
        "ts": ts,
    })
    out["contributions"] = out["contributions"][-100:]
    by = dict(out.get("by_silo") or {})
    slot = dict(by.get(silo_n) or {"last_read_at": None, "last_write_at": None})
    slot["last_write_at"] = ts
    by[silo_n] = slot
    out["by_silo"] = by
    if thesis_patch:
        th = dict(out.get("thesis") or {})
        th.update({k: v for k, v in thesis_patch.items() if v is not None})
        if th.get("summary"):
            th["state"] = th.get("state") or "POPULATED"
        out["thesis"] = th
    if hermes:
        out["latest_hermes"] = {
            "research_id": hermes.get("research_id"),
            "result_id": hermes.get("result_id"),
            "status": hermes.get("status"),
            "as_of": hermes.get("as_of") or hermes.get("completed_ts") or ts,
        }
    out["as_of"] = ts
    return out


def mark_read(spine: dict[str, Any], silo: str) -> dict[str, Any]:
    out = deepcopy(spine)
    silo_n = str(silo or "").strip().lower()
    by = dict(out.get("by_silo") or {})
    slot = dict(by.get(silo_n) or {"last_read_at": None, "last_write_at": None})
    slot["last_read_at"] = _now()
    by[silo_n] = slot
    out["by_silo"] = by
    return out


def append_spine(obj: dict[str, Any], *, path: Path | None = None, root: Path | None = None) -> dict[str, Any]:
    check = validate_spine(obj)
    if not check["ok"]:
        return {"ok": False, "error": "invalid_spine", "errors": check["errors"]}
    dest = path or default_path(root)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, separators=(",", ":"), default=str) + "\n")
        return {"ok": True, "path": str(dest)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160]}


def load_latest(
    symbol: str,
    *,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    sym = str(symbol or "").upper().strip()
    dest = path or default_path(root)
    if not dest.exists():
        return None
    latest = None
    with dest.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and str(row.get("symbol") or "").upper() == sym:
                latest = row
    return latest


def upsert_from_hermes(
    symbol: str,
    hermes_result: dict[str, Any],
    *,
    path: Path | None = None,
    root: Path | None = None,
    subject_guid: str | None = None,
) -> dict[str, Any]:
    """CIO/Hermes write path: merge Hermes result into spine and persist."""
    prior = load_latest(symbol, path=path, root=root) or empty_spine(
        symbol, subject_guid=subject_guid or hermes_result.get("subject_guid")
    )
    summary = hermes_result.get("summary") or hermes_result.get("recommendation")
    spine = contribute(
        prior,
        silo="hermes",
        kind="research_result",
        summary=str(summary)[:800] if summary else None,
        artifact_id=hermes_result.get("result_id"),
        refs=[x for x in [hermes_result.get("research_id"), hermes_result.get("result_id")] if x],
        thesis_patch={
            "stance": hermes_result.get("thesis_stance"),
            "summary": str(summary)[:1200] if summary else None,
            "conviction": hermes_result.get("confidence"),
            "state": "POPULATED" if summary else "INSUFFICIENT_DATA",
            "invalidation": list(hermes_result.get("research_gaps_remaining") or [])[:12],
        },
        hermes=hermes_result,
    )
    if subject_guid or hermes_result.get("subject_guid"):
        spine["subject_guid"] = subject_guid or hermes_result.get("subject_guid")
    spine = contribute(spine, silo="cio", kind="accepted_into_spine", summary="CIO-owned spine updated from Hermes")
    wr = append_spine(spine, path=path, root=root)
    return {"ok": bool(wr.get("ok")), "spine": spine, "write": wr}


def view_for_silo(
    symbol: str,
    silo: str,
    *,
    path: Path | None = None,
    root: Path | None = None,
    persist_read_receipt: bool = False,
) -> dict[str, Any]:
    """Canonical read API for any silo — same thesis, marked as shared."""
    spine = load_latest(symbol, path=path, root=root)
    if spine is None:
        return {
            "ok": True,
            "found": False,
            "silo": silo,
            "symbol": str(symbol).upper(),
            "thesis": {"state": "INSUFFICIENT_DATA", "summary": None},
            "note": "no_spine_yet — do not invent a silo-local thesis",
            "authority": AUTHORITY,
        }
    viewed = mark_read(spine, silo) if silo else spine
    if persist_read_receipt:
        append_spine(viewed, path=path, root=root)
    return {
        "ok": True,
        "found": True,
        "silo": silo,
        "symbol": viewed.get("symbol"),
        "subject_guid": viewed.get("subject_guid"),
        "thesis": viewed.get("thesis"),
        "latest_hermes": viewed.get("latest_hermes"),
        "contribution_count": len(viewed.get("contributions") or []),
        "transparency": viewed.get("transparency"),
        "authority": AUTHORITY,
        "as_of": viewed.get("as_of"),
    }


def spine_rows_for_options_universe(spines: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapter into options_research_universe.merge_research_rows shape."""
    out = []
    for sp in spines:
        if not isinstance(sp, dict):
            continue
        th = sp.get("thesis") or {}
        hermes = sp.get("latest_hermes") or {}
        out.append({
            "symbol": sp.get("symbol"),
            "source": "cio_research",
            "source_lanes": ["cio_research", "security_research_spine"],
            "research_status": "researched" if th.get("state") == "POPULATED" else "research_required",
            "research_artifact_id": hermes.get("result_id") or sp.get("subject_guid"),
            "summary": th.get("summary"),
            "subject_guid": sp.get("subject_guid"),
        })
    return out
