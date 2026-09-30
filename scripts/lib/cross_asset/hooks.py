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
    llm: dict[str, Any] | None = None,
    subject_guid: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Generic multi-producer spine write (LLM / desk / any research artifact).

    Owner is always CIO on the tip. LLM curation must pass thesis_patch=None
    so model prose never replaces the house thesis tip.
    """
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
            llm=llm,
            subject_guid=subject_guid,
            root=root_p,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160]}


def notify_llm_curation(
    symbols: list[str] | None,
    *,
    text: str | None,
    source: str,
    model: str | None = None,
    curated_from: list[str] | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Stamp LLM curation / flash onto each named security — CIO-owned, tagged, not a fact source.

    Tags: llm_research + llm_curation (or llm_flash) + provider (deepseek/ollama) + lifecycle.
    Never patches tip thesis.
    """
    syms = [str(s).upper() for s in (symbols or []) if s]
    if not syms or not (text or "").strip():
        return {"ok": True, "skipped": True, "reason": "no_symbols_or_text"}
    src = str(source or "llm_curation").strip().lower()
    tags = ["llm_research", "lifecycle"]
    if "flash" in src:
        tags.append("llm_flash")
    else:
        tags.append("llm_curation")
    model_l = str(model or "").lower()
    if "deepseek" in src or "deepseek" in model_l:
        tags.append("deepseek")
    if "ollama" in src or "ollama" in model_l or "gemma" in model_l:
        tags.append("ollama")
    outs = []
    for sym in syms[:12]:
        outs.append(
            notify_research_contribution(
                sym,
                silo="cio",
                kind=f"llm_{src}"[:48],
                summary=str(text)[:800],
                artifact_id=f"llm:{src}:{model or 'unknown'}",
                refs=[x for x in [src, model, *(curated_from or [])[:8]] if x],
                tags=tags,
                thesis_patch=None,
                llm={
                    "source": src,
                    "model": model,
                    "kind": "llm_curation",
                    "note": "curation_of_gathered_evidence_not_a_fact_source",
                },
                root=root,
            )
        )
    ok_n = sum(1 for o in outs if o.get("ok"))
    return {"ok": ok_n > 0, "written": ok_n, "symbols": syms[:12], "owner": "cio", "tags": tags, "results": outs}


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
                    # Do NOT patch tip thesis from operator text — that overwrote
                    # house research. Operator asks live in operator_asks until thesis changes.
                    thesis_patch=None,
                    operator={
                        "pending_id": result.get("pending_id"),
                        "kind": kind,
                        "reply_source": result.get("reply_source"),
                        "text": summary,
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
    out["latest_llm"] = view.get("latest_llm")
    out["operator_asks"] = list(view.get("operator_asks") or [])
    # Spine SLA: reuse symbol-thesis CLASS_SLA_DAYS against tip as_of.
    try:
        from datetime import datetime, timezone
        from scripts.lib.symbol_thesis_coverage import stale_days_for

        sla_days = int(stale_days_for(str(symbol), {}, {}, root=root_p))
        out["spine_sla_days"] = sla_days
        as_of = str(view.get("as_of") or "")
        age_days = None
        if as_of:
            raw = as_of.replace("Z", "+00:00")
            tip_dt = datetime.fromisoformat(raw)
            if tip_dt.tzinfo is None:
                tip_dt = tip_dt.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - tip_dt).total_seconds() / 86400.0
        out["spine_age_days"] = round(age_days, 2) if age_days is not None else None
        spine_fresh = age_days is None or age_days <= float(sla_days)
        out["spine_fresh"] = spine_fresh
        out["spine_sla_days"] = sla_days
        # Librarian/desk hard honesty: stale spine tip ⇒ not fresh for answers.
        if spine_fresh is False:
            out["fresh"] = False
            tags = list(out.get("spine_tags") or [])
            if "stale_sla" not in tags:
                tags.append("stale_sla")
            out["spine_tags"] = tags
            # Prefer spine age when overlay owns the tip.
            if age_days is not None:
                out["thesis_age_days"] = round(age_days, 2)
            out["sla_days"] = sla_days
        elif spine_fresh is True and out.get("fresh") is None:
            out["fresh"] = True
    except Exception:
        out.setdefault("spine_fresh", None)
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
