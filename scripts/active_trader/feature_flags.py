"""Active Trader (P5) server-side audited feature flags.

SAFETY-CRITICAL. A flag may EXPOSE a capability but must NEVER create
authorization or enable a live path. In this build the live-session flag is
hard-disabled: it can never be set true from a config file, and
``is_live_session_enabled()`` always returns False.

Every read is auditable: :func:`load_flags` returns a :class:`Flags` dataclass
that records the config source and any coercion notes applied while loading.
Pure, deterministic, typed. No network.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "active_trader_flags.json"
ENV_CONFIG_VAR = "ACTIVE_TRADER_FLAGS"

# Canonical flag names in mandate order.
FLAG_NAMES: tuple[str, ...] = (
    "active_trader_live_data_enabled",
    "active_trader_session_builder_enabled",
    "active_trader_simulation_enabled",
    "active_trader_automation_engine_enabled",
    "active_trader_live_session_enabled",
    "active_trader_multi_account_enabled",
    "active_trader_fallback_enabled",
)

# Hard-coded safe mandate defaults. These are the inert posture.
MANDATE_DEFAULTS: dict[str, bool] = {
    "active_trader_live_data_enabled": True,
    "active_trader_session_builder_enabled": True,
    "active_trader_simulation_enabled": True,
    # Automation engine is exposed but SIMULATION ONLY (see automation_mode()).
    "active_trader_automation_engine_enabled": True,
    # Live posture — hard OFF, never enableable by config in this build.
    "active_trader_live_session_enabled": False,
    "active_trader_multi_account_enabled": False,
    "active_trader_fallback_enabled": False,
}

# Flags that can NEVER be enabled from a config file in this build. A config
# attempting to set these true is coerced to False with an audit note.
LIVE_LOCKED = frozenset({"active_trader_live_session_enabled"})

# Non-live flags a config file is permitted to RELAX (toggle on/off).
RELAXABLE = frozenset(FLAG_NAMES) - LIVE_LOCKED

SIMULATION_MODE = "SIMULATION"
LIVE_MODE = "LIVE"


@dataclass(frozen=True)
class Flags:
    """Resolved, audited Active Trader feature flags.

    ``values`` holds the effective (post-coercion) flag states. ``source``
    records where overrides came from. ``notes`` records every coercion or
    safety action applied during load, making each read auditable.
    """

    values: Mapping[str, bool]
    source: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def get(self, name: str) -> bool:
        return bool(self.values[name])

    @property
    def active_trader_live_data_enabled(self) -> bool:
        return bool(self.values["active_trader_live_data_enabled"])

    @property
    def active_trader_session_builder_enabled(self) -> bool:
        return bool(self.values["active_trader_session_builder_enabled"])

    @property
    def active_trader_simulation_enabled(self) -> bool:
        return bool(self.values["active_trader_simulation_enabled"])

    @property
    def active_trader_automation_engine_enabled(self) -> bool:
        return bool(self.values["active_trader_automation_engine_enabled"])

    @property
    def active_trader_live_session_enabled(self) -> bool:
        # Hard-disabled in this build regardless of stored value.
        return False

    @property
    def active_trader_multi_account_enabled(self) -> bool:
        return bool(self.values["active_trader_multi_account_enabled"])

    @property
    def active_trader_fallback_enabled(self) -> bool:
        return bool(self.values["active_trader_fallback_enabled"])

    def automation_mode(self) -> str:
        """SIMULATION whenever the live session is not enabled (always here)."""
        return automation_mode(self)

    def is_live_session_enabled(self) -> bool:
        return is_live_session_enabled(self)

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "values": {k: bool(v) for k, v in self.values.items()},
            "source": self.source,
            "notes": list(self.notes),
            "automation_mode": self.automation_mode(),
            "live_session_enabled": self.is_live_session_enabled(),
        }


def automation_mode(flags: Flags) -> str:
    """Return 'SIMULATION' whenever live_session_enabled is False.

    Because the live session is hard-disabled in this build, this always
    returns 'SIMULATION'.
    """
    return LIVE_MODE if flags.is_live_session_enabled() else SIMULATION_MODE


def is_live_session_enabled(flags: Flags | None = None) -> bool:
    """Always False in this build. Live session cannot be enabled."""
    return False


def _resolve_config_path(explicit: str | Path | None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser()
    env = os.environ.get(ENV_CONFIG_VAR, "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_CONFIG_PATH


def _read_overrides(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Read raw override mapping from a JSON config file, if present."""
    notes: list[str] = []
    if not path.is_file():
        return {}, notes
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        notes.append(f"config unreadable ({exc}); using mandate defaults")
        return {}, notes
    if not isinstance(raw, dict):
        notes.append("config root is not an object; using mandate defaults")
        return {}, notes
    # Allow flags nested under a "flags" key, or at top level.
    section = raw.get("flags") if isinstance(raw.get("flags"), dict) else raw
    return dict(section), notes


def load_flags(path: str | Path | None = None) -> Flags:
    """Load flags with hard-coded safe defaults, applying any config overrides.

    A config file may only RELAX non-live flags. The live-session flag is
    coerced to False and an audit note is recorded if a config tries to enable
    it. Every coercion is captured in ``Flags.notes`` for auditability.
    """
    cfg_path = _resolve_config_path(path)
    overrides, notes = _read_overrides(cfg_path)

    values: dict[str, bool] = dict(MANDATE_DEFAULTS)

    if not cfg_path.is_file():
        source = "mandate-defaults (no config file)"
    else:
        source = f"config:{cfg_path}"

    for name, raw_val in overrides.items():
        if name not in FLAG_NAMES:
            notes.append(f"ignored unknown flag '{name}' from config")
            continue
        desired = bool(raw_val)
        if name in LIVE_LOCKED:
            if desired:
                notes.append(
                    f"COERCED {name}=true -> False: live session cannot be "
                    f"enabled by config in this build"
                )
            # Live-locked flags are always forced to their safe default.
            values[name] = False
            continue
        values[name] = desired

    # Final safety enforcement: live-locked flags are ALWAYS False.
    for name in LIVE_LOCKED:
        if values.get(name):
            notes.append(f"ENFORCED {name}=False (live-locked)")
        values[name] = False

    return Flags(values=values, source=source, notes=tuple(notes))
