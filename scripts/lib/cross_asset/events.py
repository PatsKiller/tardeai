"""Flag-gated reevaluation hooks."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .assemble import assemble_symbol_decision
from .persistence import append_symbol_decision


def shadow_enabled() -> bool:
    return str(os.environ.get("CROSS_ASSET_SHADOW", "0")).strip() in {"1", "true", "TRUE", "yes"}


def maybe_reevaluate_on_research_complete(
    symbol: str,
    *,
    hermes_result: dict[str, Any] | None = None,
    signal_kind: str = "buy",
    root: Path | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """When CROSS_ASSET_SHADOW=1, assemble+route+persist. Otherwise no-op."""
    if not shadow_enabled():
        return {"ok": True, "skipped": True, "reason": "CROSS_ASSET_SHADOW_off"}
    obj = assemble_symbol_decision(
        symbol,
        hermes_result=hermes_result,
        signal={"kind": signal_kind, "lane": "hermes_research_complete"},
        route=True,
    )
    wr = append_symbol_decision(obj, path=ledger_path, root=root)
    return {"ok": bool(wr.get("ok")), "skipped": False, "write": wr, "symbol": symbol.upper()}
