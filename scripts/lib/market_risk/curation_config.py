"""Read-only loader for ``config/market_risk_curation.yaml`` — no model client, no DB, no broker reach.

Split out of ``curation.py`` (review of #2399, 2026-10-31): the read-only projection
(``lib/market_risk_projection.curation_status``) only needs to know whether curation is ON and when it is due back.
Importing ``curation`` for that pulled ``llm_fallback -> llm_lane -> llm_consumption -> db_adapter -> holdings_guard ->
schwab_position_sync`` into the import closure of every read-only lane that renders the projection
(``cio-portfolio-thesis``), i.e. a broker / order-placement module (``MBI_BEHAVIOR = 0``,
``tests/test_cio_portfolio_thesis_lane_20261021.py``). Keep this module dependency-free: pathlib and yaml only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "market_risk_curation.yaml"
CONFIG_SCHEMA = "MarketRiskCuration@v1"


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if data.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"{path}: expected schema {CONFIG_SCHEMA}, got {data.get('schema')!r}")
    return data
