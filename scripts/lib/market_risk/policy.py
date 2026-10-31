"""Load config/market_risk_policy.yaml — the operator-owned thresholds of the Market Risk Engine."""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = PROJECT_ROOT / "config" / "market_risk_policy.yaml"


def load_policy(path: Path | str = POLICY_PATH) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if data.get("schema") != "MarketRiskPolicy@v1":
        raise ValueError(f"{path}: expected schema MarketRiskPolicy@v1, got {data.get('schema')!r}")
    return data
