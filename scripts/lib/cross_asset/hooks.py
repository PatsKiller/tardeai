"""Fail-soft hooks that publish / read the CIO-owned SecurityResearchSpine.

Never raise into Hermes or desk producers. Gate writes on CROSS_ASSET_SPINE /
CROSS_ASSET_SHADOW (see events.spine_write_enabled).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


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
        return upsert_from_hermes(sym, dict(result or {}), root=root_p)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160]}


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
