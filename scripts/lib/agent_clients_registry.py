"""Load and validate AgentClientsRegistry@v1 (coding/governance clients)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_YAML = ROOT / "config" / "agent_clients.yaml"
DEFAULT_SCHEMA = ROOT / "config" / "agent_clients.schema.json"
SCHEMA_NAME = "AgentClientsRegistry@v1"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError("PyYAML required to load agent_clients.yaml") from e
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("agent_clients.yaml must be a mapping")
    return data


def load_registry(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_YAML
    return _load_yaml(p)


def validate_registry(reg: dict[str, Any], *, schema_path: Path | None = None) -> list[str]:
    """Structural validation. Prefer jsonschema when installed; else built-in checks."""
    errors: list[str] = []
    if reg.get("schema") != SCHEMA_NAME:
        errors.append(f"schema must be {SCHEMA_NAME}")
    if not reg.get("version"):
        errors.append("version required")
    unk = reg.get("unknown_client_default") or {}
    if unk.get("enforcement_level") != "ADVISORY":
        errors.append("unknown_client_default.enforcement_level must be ADVISORY")
    if unk.get("mutating") is not False:
        errors.append("unknown_client_default.mutating must be false")
    clients = reg.get("clients")
    if not isinstance(clients, list) or not clients:
        errors.append("clients must be a non-empty list")
        return errors
    seen: set[str] = set()
    required = (
        "agent_id", "display_name", "adapter_type", "adapter_version",
        "instruction_discovery", "launcher", "enforcement_level",
        "hook_bootstrap", "validation_test", "last_verified", "limitations",
    )
    for i, c in enumerate(clients):
        if not isinstance(c, dict):
            errors.append(f"clients[{i}] not a mapping")
            continue
        for k in required:
            if k not in c:
                errors.append(f"clients[{i}].{k} required")
        aid = str(c.get("agent_id") or "")
        if not aid:
            errors.append(f"clients[{i}].agent_id empty")
        elif aid in seen:
            errors.append(f"duplicate agent_id {aid}")
        else:
            seen.add(aid)
        lvl = c.get("enforcement_level")
        if lvl not in ("MECHANICAL", "ADVISORY", "UNSUPPORTED"):
            errors.append(f"{aid}: bad enforcement_level {lvl!r}")
    # Optional jsonschema
    sp = schema_path or DEFAULT_SCHEMA
    if sp.is_file():
        try:
            import jsonschema  # type: ignore
            schema = json.loads(sp.read_text(encoding="utf-8"))
            jsonschema.validate(reg, schema)
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            errors.append(f"jsonschema: {e}")
    return errors


def get_client(agent_id: str, reg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    reg = reg or load_registry()
    aid = str(agent_id or "").strip().lower()
    for c in reg.get("clients") or []:
        if str(c.get("agent_id") or "").lower() == aid:
            return dict(c)
    unk = dict(reg.get("unknown_client_default") or {})
    return {
        "agent_id": aid or "unknown",
        "display_name": "UNKNOWN_CLIENT",
        "adapter_type": "none",
        "adapter_version": "0",
        "instruction_discovery": ["AGENTS.md"],
        "launcher": "",
        "enforcement_level": unk.get("enforcement_level") or "ADVISORY",
        "hook_bootstrap": "none",
        "validation_test": "",
        "last_verified": "",
        "limitations": "Unregistered client — fail closed",
        "unknown": True,
        "mutating_allowed": False,
        "remote_sync_allowed": False,
        "production_allowed": False,
        "financial_allowed": False,
    }


def mutating_allowed(agent_id: str, reg: Optional[dict[str, Any]] = None) -> bool:
    c = get_client(agent_id, reg)
    if c.get("unknown"):
        return False
    return c.get("enforcement_level") == "MECHANICAL"
