"""Read-only Hermes cross-surface API (v3).

  GET /api/v3/hermes/research-links       — HermesResearchLinks@v1
        ?limit=&result_id=&decision_id=&symbol=
        Hermes result -> CIO decisions consuming it, thesis refs, symbol.
  GET /api/v3/agents/runtime-proof        — AgentRuntimeProof@v1  ?agents=a,b
        Per-agent last natural wake / research action / memory retrieval /
        decisions contributed, from production evidence stores.

READ_ONLY_ADVISORY: no writes, no provider calls, no financial authority.
Links absent from every store are NOT_RECORDED; proof the stores cannot
attribute to an agent is NOT_EXPOSED.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _cio_root() -> Path:
    return Path(os.getenv("TRADEAI_CIO_DIR") or PROJECT_ROOT / "data" / "cio")


def _q(query: Optional[dict], key: str) -> Optional[str]:
    if not isinstance(query, dict):
        return None
    value = query.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    text = str(value).strip() if value is not None else ""
    return text or None


def get_hermes_research_links(query: Optional[dict] = None) -> dict[str, Any]:
    from scripts.lib.cio_cross_surface_links import cached_hermes_research_links

    try:
        limit = int(_q(query, "limit") or 50)
    except ValueError:
        limit = 50
    return cached_hermes_research_links(
        cio_root=_cio_root(),
        limit=limit,
        result_id=_q(query, "result_id"),
        decision_id=_q(query, "decision_id"),
        symbol=_q(query, "symbol"),
    )


def get_agent_runtime_proof(query: Optional[dict] = None) -> dict[str, Any]:
    from scripts.lib.cio_cross_surface_links import cached_agent_runtime_proof

    agents = [a for a in (_q(query, "agents") or "").split(",") if a.strip()]
    return cached_agent_runtime_proof(_cio_root(), agent_ids=agents)
