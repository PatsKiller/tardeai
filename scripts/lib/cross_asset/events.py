"""Flag-gated reevaluation hooks."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .assemble import assemble_symbol_decision
from .persistence import append_symbol_decision
from .security_research_spine import upsert_from_hermes


def shadow_enabled() -> bool:
    return str(os.environ.get("CROSS_ASSET_SHADOW", "0")).strip() in {"1", "true", "TRUE", "yes"}


def spine_write_enabled() -> bool:
    """Shared spine writes: on when shadow is on OR CROSS_ASSET_SPINE=1 (production path)."""
    if shadow_enabled():
        return True
    return str(os.environ.get("CROSS_ASSET_SPINE", "0")).strip() in {"1", "true", "TRUE", "yes"}


def maybe_reevaluate_on_research_complete(
    symbol: str,
    *,
    hermes_result: dict[str, Any] | None = None,
    signal_kind: str = "buy",
    root: Path | None = None,
    ledger_path: Path | None = None,
    spine_path: Path | None = None,
) -> dict[str, Any]:
    """Upsert CIO spine always when CROSS_ASSET_SPINE/SHADOW on; assemble when shadow on."""
    hermes = hermes_result or {}
    spine_out = None
    if spine_write_enabled() and hermes:
        spine_out = upsert_from_hermes(symbol, hermes, path=spine_path, root=root)

    if not shadow_enabled():
        return {
            "ok": True,
            "skipped": not bool(spine_out and spine_out.get("ok")),
            "reason": "CROSS_ASSET_SHADOW_off",
            "spine": spine_out,
            "symbol": symbol.upper(),
        }

    obj = assemble_symbol_decision(
        symbol,
        hermes_result=hermes,
        signal={"kind": signal_kind, "lane": "hermes_research_complete"},
        route=True,
        spine_path=spine_path,
    )
    wr = append_symbol_decision(obj, path=ledger_path, root=root)
    return {
        "ok": bool(wr.get("ok")),
        "skipped": False,
        "write": wr,
        "spine": spine_out,
        "symbol": symbol.upper(),
    }