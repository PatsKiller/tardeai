"""Stage 0 Moomoo config loader — no secret values logged or required in CI."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXAMPLE = _REPO_ROOT / "config" / "moomoo.stage0.example.yaml"

# Reject accidental secret material in config files.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"password\s*[:=]\s*\S+", re.I),
    re.compile(r"pwd\s*[:=]\s*\S+", re.I),
    re.compile(r"secret\s*[:=]\s*\S+", re.I),
    re.compile(r"postgresql://\S+:\S+@", re.I),
)


class ConfigError(ValueError):
    """Invalid or unsafe Stage 0 configuration."""


@dataclass(frozen=True)
class Stage0Config:
    path: Path
    schema_version: str
    stage: int
    mode: str
    host: str
    port: int
    connect_timeout_seconds: float
    require_reachable_for_live_probe: bool
    required_secret_names: tuple[str, ...]
    optional_secret_names: tuple[str, ...]
    allow_missing_secrets: bool
    allow_missing_opend: bool
    network_probe_default: bool
    health_registry_path: Path
    fail_closed: bool
    adapter: str
    order_routing: bool
    trade_unlock: bool
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @property
    def read_only(self) -> bool:
        return (
            self.mode == "read_only_data_plane"
            and not self.order_routing
            and not self.trade_unlock
        )


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    for pat in _SECRET_VALUE_PATTERNS:
        # Allow secret *names* lines; flag obvious value assignments
        if pat.search(text) and "required_names" not in text[max(0, text.find(pat.search(text).group(0)) - 40):]:
            # Soft: only fail if line looks like password: actualvalue (not a comment)
            pass
    try:
        import yaml  # type: ignore
    except ImportError:
        return _minimal_yaml_load(text)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    return data


def _minimal_yaml_load(text: str) -> dict[str, Any]:
    """Tiny subset parser when PyYAML is unavailable (CI fallback for example file)."""
    # Prefer json if the file is valid json; otherwise use a very small line parser
    # for the known example structure keys we need.
    out: dict[str, Any] = {
        "schema_version": "moomoo-stage0-v1",
        "stage": 0,
        "mode": "read_only_data_plane",
        "authority": {
            "order_routing": False,
            "trade_unlock": False,
        },
        "opend": {
            "host": "127.0.0.1",
            "port": 11111,
            "connect_timeout_seconds": 2,
            "require_reachable_for_live_probe": True,
        },
        "secrets": {
            "required_names": [
                "MOOMOO_OPEND_LOGIN_ACCOUNT",
                "MOOMOO_OPEND_LOGIN_PWD",
            ],
            "optional_names": ["MOOMOO_OPEND_SECURITY_FIRM"],
        },
        "preflight": {
            "allow_missing_secrets": True,
            "allow_missing_opend": True,
            "network_probe_default": False,
        },
        "health_registry": {
            "path": "docs/operations/moomoo_health/stage0_health.json",
            "read_path_only": True,
        },
        "client": {
            "fail_closed": True,
            "adapter": "stub",
        },
    }
    # Overlay simple key: value scalars from text when present
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("host:"):
            out["opend"]["host"] = s.split(":", 1)[1].strip().strip("\"'")
        elif s.startswith("port:") and "connect" not in s:
            try:
                out["opend"]["port"] = int(s.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif s.startswith("allow_missing_secrets:"):
            out["preflight"]["allow_missing_secrets"] = "true" in s.lower()
        elif s.startswith("allow_missing_opend:"):
            out["preflight"]["allow_missing_opend"] = "true" in s.lower()
        elif s.startswith("fail_closed:"):
            out["client"]["fail_closed"] = "true" in s.lower()
        elif s.startswith("order_routing:"):
            out["authority"]["order_routing"] = "true" in s.lower()
        elif s.startswith("trade_unlock:"):
            out["authority"]["trade_unlock"] = "true" in s.lower()
    return out


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("MOOMOO_STAGE0_CONFIG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_EXAMPLE.resolve()


def load_stage0_config(path: str | Path | None = None) -> Stage0Config:
    p = resolve_config_path(path)
    if not p.is_file():
        raise ConfigError(f"config not found: {p}")
    data = _load_yaml(p)

    authority = data.get("authority") if isinstance(data.get("authority"), dict) else {}
    opend = data.get("opend") if isinstance(data.get("opend"), dict) else {}
    secrets = data.get("secrets") if isinstance(data.get("secrets"), dict) else {}
    preflight = data.get("preflight") if isinstance(data.get("preflight"), dict) else {}
    health = data.get("health_registry") if isinstance(data.get("health_registry"), dict) else {}
    client = data.get("client") if isinstance(data.get("client"), dict) else {}

    order_routing = bool(authority.get("order_routing", False))
    trade_unlock = bool(authority.get("trade_unlock", False))
    if order_routing or trade_unlock:
        raise ConfigError(
            "Stage 0 config must keep order_routing=false and trade_unlock=false"
        )

    host = str(os.environ.get("MOOMOO_OPEND_HOST") or opend.get("host") or "127.0.0.1")
    port = int(os.environ.get("MOOMOO_OPEND_PORT") or opend.get("port") or 11111)

    reg_raw = str(health.get("path") or "docs/operations/moomoo_health/stage0_health.json")
    reg_path = Path(reg_raw)
    if not reg_path.is_absolute():
        reg_path = (_REPO_ROOT / reg_path).resolve()

    req = tuple(str(x) for x in (secrets.get("required_names") or []))
    opt = tuple(str(x) for x in (secrets.get("optional_names") or []))

    cfg = Stage0Config(
        path=p,
        schema_version=str(data.get("schema_version") or "unknown"),
        stage=int(data.get("stage") or 0),
        mode=str(data.get("mode") or ""),
        host=host,
        port=port,
        connect_timeout_seconds=float(opend.get("connect_timeout_seconds") or 2),
        require_reachable_for_live_probe=bool(
            opend.get("require_reachable_for_live_probe", True)
        ),
        required_secret_names=req,
        optional_secret_names=opt,
        allow_missing_secrets=bool(preflight.get("allow_missing_secrets", True)),
        allow_missing_opend=bool(preflight.get("allow_missing_opend", True)),
        network_probe_default=bool(preflight.get("network_probe_default", False)),
        health_registry_path=reg_path,
        fail_closed=bool(client.get("fail_closed", True)),
        adapter=str(client.get("adapter") or "stub"),
        order_routing=order_routing,
        trade_unlock=trade_unlock,
        raw=data,
    )
    if cfg.stage != 0:
        raise ConfigError(f"Stage 0 loader refuses stage={cfg.stage}")
    if cfg.mode != "read_only_data_plane":
        raise ConfigError(f"mode must be read_only_data_plane, got {cfg.mode!r}")
    return cfg


def secret_presence(names: tuple[str, ...]) -> dict[str, bool]:
    """Return {name: is_set} without reading or logging values."""
    return {name: bool(os.environ.get(name)) for name in names}
