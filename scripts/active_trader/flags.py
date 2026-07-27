"""Active Trader Stage 0 feature flags — default OFF, fail closed if live flags true."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXAMPLE = _REPO_ROOT / "config" / "active_trader.stage0.example.yaml"

# Flags that must never be true in Stage 0 tooling
HARD_OFF = frozenset({
    "live_canary",
    "order_routes",
    "session_authorize",
    "moomoo_order_path",
    "multi_account_live",
    "runner",
})


class FlagsError(ValueError):
    pass


@dataclass(frozen=True)
class Stage0Flags:
    path: Path
    stage: int
    write: bool
    canary: bool
    flags: Mapping[str, bool]
    contract: str
    registry_path: Path

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "write": False,  # hard
            "canary": False,  # hard
            "feature_flags": {k: bool(v) for k, v in self.flags.items()},
        }

    def assert_stage0_safe(self) -> None:
        if self.stage != 0:
            raise FlagsError(f"stage must be 0, got {self.stage}")
        if self.write or self.canary:
            raise FlagsError("Stage 0 authority.write/canary must be false")
        for name in HARD_OFF:
            if self.flags.get(name):
                raise FlagsError(f"Stage 0 forbids feature_flags.{name}=true")


def _parse_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise FlagsError("config root must be a mapping")
        return data
    except ImportError:
        return _fallback_defaults()


def _fallback_defaults() -> dict[str, Any]:
    return {
        "schema_version": "active-trader-stage0-v1",
        "stage": 0,
        "authority": {"write": False, "canary": False},
        "feature_flags": {k: False for k in (
            "active_trader_ui", "session_builder", "session_authorize",
            "live_canary", "order_routes", "moomoo_order_path",
            "multi_account_live", "runner", "night_run_controller",
        )},
        "read_api": {"contract": "active-trader-stage0-read-api-v1"},
        "registry": {"path": "docs/implementation/active_trader_stage0_registry.json"},
    }


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("ACTIVE_TRADER_STAGE0_CONFIG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_EXAMPLE.resolve()


def load_flags(path: str | Path | None = None) -> Stage0Flags:
    p = resolve_config_path(path)
    if not p.is_file():
        # Safe defaults when example is missing
        data = _fallback_defaults()
        p = DEFAULT_EXAMPLE
    else:
        data = _parse_yaml(p)

    authority = data.get("authority") if isinstance(data.get("authority"), dict) else {}
    raw_flags = data.get("feature_flags") if isinstance(data.get("feature_flags"), dict) else {}
    flags = {str(k): bool(v) for k, v in raw_flags.items()}
    # Ensure hard-off keys exist and default false
    for k in HARD_OFF:
        flags.setdefault(k, False)

    read_api = data.get("read_api") if isinstance(data.get("read_api"), dict) else {}
    reg = data.get("registry") if isinstance(data.get("registry"), dict) else {}
    reg_raw = str(reg.get("path") or "docs/implementation/active_trader_stage0_registry.json")
    reg_path = Path(reg_raw)
    if not reg_path.is_absolute():
        reg_path = (_REPO_ROOT / reg_path).resolve()

    out = Stage0Flags(
        path=p if p.is_file() else DEFAULT_EXAMPLE,
        stage=int(data.get("stage") or 0),
        write=bool(authority.get("write", False)),
        canary=bool(authority.get("canary", False)),
        flags=flags,
        contract=str(read_api.get("contract") or "active-trader-stage0-read-api-v1"),
        registry_path=reg_path,
    )
    out.assert_stage0_safe()
    return out
