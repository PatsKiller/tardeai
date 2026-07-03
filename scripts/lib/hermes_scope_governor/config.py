"""Load and validate Hermes Scope Governor configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_CFG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "hermes_scope_governor.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    import yaml
    p = path or DEFAULT_CFG_PATH
    return yaml.safe_load(p.read_text()) or {}


def scoring_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("scoring") or {}


def tier_order() -> dict[str, int]:
    return {"S0": 0, "S1": 1, "S2": 2, "S3": 3}


def tier_better(a: str, b: str) -> bool:
    """True when tier a is hotter (lower index) than b."""
    o = tier_order()
    return o.get(a, 9) < o.get(b, 9)