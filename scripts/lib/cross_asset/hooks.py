"""Fail-soft hooks that publish / read the CIO-owned SecurityResearchSpine.

Never raise into Hermes, desk, thesis, or LLM producers. Gate writes on
CROSS_ASSET_SPINE / CROSS_ASSET_SHADOW (see events.spine_write_enabled).

Memory is multi-producer: Hermes, operator Q&A, theses, LLM research — each
contribution carries tags so the full lifecycle is queryable per security.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def _root_from(result: dict[str, Any] | None = None) -> Path:
    return Path(__file__).resolve().parents[3]


def notify_hermes_result_completed(
    result: dict[str, Any],
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """CADI-011: after Hermes stamps a completed result, upsert the shared spine."""
    try:
        from scripts.lib.cross_asset.events import spine_write_enabled
        from scripts.lib.cross_asset.security_research_spine import upsert_from_hermes
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skipped": True, "error": f"import:{type(exc).__name__}"}
    if not spine_write_enabled():
        return {"ok": True, "skipped": True, "reason": "CROSS_ASSET_SPINE_off"}
    sym = str((result or {}).get("symbol") or "").upper().strip()
    if not sym:
        return {"ok": False, "skipped": True, "reason": "no_symbol"}
    root_p = Path(root) if root is not None else _root_from()
    try:
        return upsert_from_hermes(sym, dict(result or {}), root=root_p, tags=["hermes", "lifecycle"])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160]}


def notify_research_contribution(
    symbol: str,
    *,
    silo: str,
    kind: str,
    summary: str | None = None,
    artifact_id: str | None = None,
    refs: list[str] | None = None,
    tags: Iterable[str] | None = None,
    thesis_patch: dict[str, Any] | None = None,
    subject_guid: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Generic multi-producer spine write (LLM / desk / any research artifact)."""
    try:
        from scripts.lib.cross_asset.events import spine_write_enabled
        from scripts.lib.cross_asset.security_research_spine import upsert_research_memory
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skipped": True, "error": f"import:{type(exc).__name__}"}
    if not spine_write_enabled():
        return {"ok": True, "skipped": True, "reason": "CROSS_ASSET_SPINE_off"}
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"ok": False, "skipped": True, "reason": "no_symbol"}
    root_p = Path(root) if root is not None else _root_from()
    try:
        return upsert_research_memory(
            sym,
            silo=silo,
            kind=kind,
            summary=summary,
            artifact_id=artifact_id,
            refs=refs,
            tags=tags,
            thesis_patch=thesis_patch,
            subject_guid=subject_guid,
            root=root_p,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160]}


def notify_operator_desk_result(
    intent: dict[str, Any] | None,
    result: dict[str, Any] | None,
    *,
    operator_text: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Full lifecycle: operator ask → answered/deferred lands on each named security spine."""
    try:
        from scripts.lib.cross_asset.events import spine_write_enabled
        from scripts.lib.cross_asset.security_research_spine import upsert_research_memory
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skipped": True, "error": f"import:{type(exc).__name__}"}
    if not spine_write_enabled():
        return {"ok": True, "skipped": True, "reason": "CROSS_ASSET_SPINE_off"}
    intent = intent or {}
    result = result or {}
    symbols = [str(s).upper() for s in (intent.get("symbols") or []) if s]
    if not symbols:
        return {"ok": True, "skipped": True, "reason": "no_symbols"}
    kind = str(result.get("kind") or "operator_turn")
    tags = ["operator_qa", "lifecycle", "operator_ask"]
    if kind == "deferred":
        tags.append("operator_deferred")
    summary = (result.get("text") or operator_text or "")[:800] or None
    root_p = Path(root) if root is not None else _root_from()
    outs: list[dict[str, Any]] = []
    for sym in symbols[:12]:
        try:
            outs.append(
                upsert_research_memory(
                    sym,
                    silo="cio",
                    kind=f"operator_{kind}",
                    summary=summary,
                    artifact_id=result.get("pending_id"),
                    refs=[x for x in [result.get("pending_id"), result.get("reply_source")] if x],
                    tags=tags,
                    thesis_patch={
                        "summary": summary,
                        "state": "POPULATED" if summary else "INSUFFICIENT_DATA",
                    }
                    if kind == "answered" and summary
                    else None,
                    operator={
                        "pending_id": result.get("pending_id"),
                        "kind": kind,
                        "reply_source": result.get("reply_source"),
                    },
                    root=root_p,
                )
            )
        except Exception as exc:  # noqa: BLE001
            outs.append({"ok": False, "symbol": sym, "error": f"{type(exc).__name__}:{exc}"[:120]})
    ok_n = sum(1 for o in outs if o.get("ok"))
    return {"ok": ok_n > 0, "symbols": symbols[:12], "written": ok_n, "results": outs}


def notify_thesis_published(
    payload: dict[str, Any],
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Thesis publish → spine contribution for each linked security."""
    linked = [str(s).upper() for s in (payload or {}).get("linked_symbols") or [] if s]
    if not linked:
        return {"ok": True, "skipped": True, "reason": "no_linked_symbols"}
    summary = str((payload or {}).get("summary") or "")[:800] or None
    outs = []
    for sym in linked[:24]:
        outs.append(
            notify_research_contribution(
                sym,
                silo="cio",
                kind="thesis_publish",
                summary=summary,
                artifact_id=str((payload or {}).get("thesis_version") or (payload or {}).get("thesis_id") or ""),
                refs=[
                    x
                    for x in [
                        (payload or {}).get("thesis_id"),
                        (payload or {}).get("thesis_version"),
                    ]
                    if x
                ],
                tags=["thesis", "lifecycle", "llm_research"],
                thesis_patch={
                    "stance": (payload or {}).get("stance"),
                    "summary": summary,
                    "state": "POPULATED" if summary else "INSUFFICIENT_DATA",
                },
                subject_guid=(payload or {}).get("subject_guid") if sym == linked[0] else None,
                root=root,
            )
        )
    ok_n = sum(1 for o in outs if o.get("ok"))
    return {"ok": ok_n > 0 or all(o.get("skipped") for o in outs), "written": ok_n, "results": outs}


def overlay_thesis_fields_from_spine(
    fields: dict[str, Any],
    symbol: str,
    *,
    root: Path | str | None = None,
    silo: str = "cio",
) -> dict[str, Any]:
    """CADI-012: prefer shared spine summary/stance when POPULATED."""
    try:
        from scripts.lib.cross_asset.security_research_spine import view_for_silo
    except Exception:
        return fields
    root_p = Path(root) if root is not None else _root_from()
    try:
        view = view_for_silo(symbol, silo, root=root_p, persist_read_receipt=False)
    except Exception:
        return fields
    if not view.get("found"):
        return fields
    th = view.get("thesis") or {}
    if th.get("state") != "POPULATED" and not th.get("summary"):
        return fields
    out = dict(fields)
    if th.get("summary"):
        out["thesis_summary"] = th.get("summary")
        out["thesis_state"] = th.get("state") or out.get("thesis_state") or "POPULATED"
    if th.get("stance") is not None:
        out["thesis_stance"] = th.get("stance")
    if th.get("conviction") is not None:
        out["thesis_confidence"] = th.get("conviction")
    hermes = view.get("latest_hermes") or {}
    refs = list(out.get("source_refs") or [])
    if hermes.get("result_id") and hermes.get("result_id") not in refs:
        refs.append(hermes["result_id"])
    out["source_refs"] = refs
    out["security_research_spine"] = True
    out["spine_as_of"] = view.get("as_of")
    out["spine_silo"] = silo
    out["spine_tags"] = list(view.get("tags") or [])
    return out


def spine_rows_for_root(root: Path | str | None = None, *, limit: int = 500) -> list[dict[str, Any]]:
    """Load latest spines from the ledger for options/watch universe merge."""
    try:
        from scripts.lib.cross_asset.security_research_spine import (
            default_path,
            spine_rows_for_options_universe,
        )
    except Exception:
        return []
    root_p = Path(root) if root is not None else _root_from()
    path = default_path(root_p)
    if not path.exists():
        return []
    import json

    latest: dict[str, dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("symbol"):
                    latest[str(row["symbol"]).upper()] = row
    except OSError:
        return []
    spines = list(latest.values())[-limit:]
    return spine_rows_for_options_universe(spines)
