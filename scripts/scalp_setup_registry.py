#!/usr/bin/env python3
"""Momentum-scalp NAMED SETUP registry — backend-owned single source of truth.

Loads config/scalp_setup_registry.yaml, validates its shape, exposes the canonical setups, computes a
STABLE registry hash (so the UI/API can pin the exact rules a fired event was judged against), and
implements the deterministic PRIMARY-setup selection when several setups match one event.

Read-only. No write authority, no order path, no LLM: this module decides nothing about money — it only
describes the deterministic taxonomy. A lane (IGN_60/IGN_ACCEL/TRIGGER) is NOT a setup; setups live here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise RuntimeError("PyYAML required for the scalp setup registry") from e

_REPO = Path(__file__).resolve().parent.parent
_REGISTRY_PATH = _REPO / "config" / "scalp_setup_registry.yaml"

# canonical setup ids (the taxonomy the rest of the engine must agree with)
CANONICAL_SETUP_IDS = (
    "SCALP_PREMARKET_MOMENTUM_V1",
    "SCALP_L2_MOMENTUM_V1",
    "SCALP_VWAP_PULLBACK_V1",
    "SCALP_VWAP_REVERSION_V1",
    "SCALP_ORB_15_BREAKOUT_V1",
    "SCALP_MICRO_PULLBACK_V1",
    "SCALP_IGNITION_BREAKOUT_V1",
)

VALID_OPERATING_STATES = ("SHADOW", "MANUAL_PAPER_TEST_ONLY", "DISABLED")
VALID_SESSIONS = ("PREMARKET", "REGULAR")
VALID_PROVENANCE = ("SOURCE_DERIVED", "ENGINE_ADAPTATION", "EXISTING_ENGINE_RULE")

_REQUIRED_SETUP_FIELDS = (
    "setup_id", "display_label", "family", "version", "enabled", "operating_state",
    "supported_sessions", "active_window_et", "required_data_tier", "best_conditions",
    "entry_rule", "invalidation_rule", "stop_rule", "target_rule", "exit_if_wrong",
    "required_inputs", "optional_confirmations", "source_attribution", "rule_provenance",
    "source_rule_notes", "engine_adaptations",
)


class SetupRegistryError(Exception):
    ...


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_registry(path: Path | str | None = None) -> dict:
    """Load + validate the registry. Raises SetupRegistryError on any structural problem (fail-closed)."""
    p = Path(path) if path else _REGISTRY_PATH
    if not p.exists():
        raise SetupRegistryError(f"registry not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    setups = data.get("setups")
    if not isinstance(setups, list) or not setups:
        raise SetupRegistryError("registry has no setups")

    seen_ids: set[str] = set()
    for s in setups:
        missing = [f for f in _REQUIRED_SETUP_FIELDS if f not in s]
        if missing:
            raise SetupRegistryError(f"setup {s.get('setup_id')!r} missing fields: {missing}")
        sid = s["setup_id"]
        if sid in seen_ids:
            raise SetupRegistryError(f"duplicate setup_id: {sid}")
        seen_ids.add(sid)
        if s["operating_state"] not in VALID_OPERATING_STATES:
            raise SetupRegistryError(f"{sid}: bad operating_state {s['operating_state']!r}")
        if s["rule_provenance"] not in VALID_PROVENANCE:
            raise SetupRegistryError(f"{sid}: bad rule_provenance {s['rule_provenance']!r}")
        for sess in s["supported_sessions"]:
            if sess not in VALID_SESSIONS:
                raise SetupRegistryError(f"{sid}: bad session {sess!r}")

    missing_canonical = [c for c in CANONICAL_SETUP_IDS if c not in seen_ids]
    if missing_canonical:
        raise SetupRegistryError(f"registry missing canonical setups: {missing_canonical}")
    return data


def registry_hash(registry: Mapping | None = None) -> str:
    """Stable content hash of the registry (sha256 of canonical JSON). No timestamps → reproducible."""
    reg = dict(registry) if registry is not None else load_registry()
    return "sha256:" + hashlib.sha256(_canonical_json(reg).encode("utf-8")).hexdigest()[:32]


def list_setups(registry: Mapping | None = None) -> list[dict]:
    reg = registry if registry is not None else load_registry()
    return list(reg["setups"])


def get_setup(setup_id: str, registry: Mapping | None = None) -> dict:
    for s in list_setups(registry):
        if s["setup_id"] == setup_id:
            return s
    raise SetupRegistryError(f"unknown setup_id: {setup_id}")


def label_for(setup_id: str, registry: Mapping | None = None) -> str:
    return get_setup(setup_id, registry)["display_label"]


def select_primary(matches: Sequence[Mapping], registry: Mapping | None = None) -> str | None:
    """Deterministically choose the primary setup_id from >=1 matched setups. Every match is retained by
    the caller; this only picks which one is `primary`. Ordering (highest priority first):
      1. data-tier specificity of the setup's required_data_tier (T2>T1>T0)
      2. mandatory-criteria satisfied (match['mandatory_satisfied'], default 0)
      3. family specificity rank from the registry
      4. setup version (higher wins)
      5. setup_id lexical (final deterministic tie-break)
    """
    reg = registry if registry is not None else load_registry()
    if not matches:
        return None
    sel = reg.get("primary_selection", {})
    tier_rank = sel.get("tier_specificity", {"T2": 3, "T1": 2, "T0": 1})
    fam_rank = sel.get("family_specificity_rank", {})
    by_id = {s["setup_id"]: s for s in reg["setups"]}

    def key(m: Mapping):
        sid = m["setup_id"]
        s = by_id.get(sid, {})
        return (
            tier_rank.get(s.get("required_data_tier"), 0),
            int(m.get("mandatory_satisfied", 0)),
            fam_rank.get(s.get("display_label"), 0),
            int(str(s.get("version", "0")).split(".")[0] or 0),
            # lexical tie-break: negate by using reverse ordering on the id via a stable transform
        )

    # sort by the numeric keys desc, then setup_id asc as the final deterministic tie-break
    ordered = sorted(matches, key=lambda m: (tuple(-k for k in key(m)), m["setup_id"]))
    return ordered[0]["setup_id"]


def public_view(registry: Mapping | None = None) -> dict:
    """Read-only projection the API/UI consumes. Includes the hash so a fired event can pin the rules."""
    reg = registry if registry is not None else load_registry()
    return {
        "registry_version": reg.get("registry_version"),
        "schema_version": reg.get("schema_version"),
        "registry_hash": registry_hash(reg),
        "sessions": reg.get("sessions", {}),
        "setups": reg["setups"],
        "read_only": True,
        "write_authority": False,
    }


if __name__ == "__main__":  # pragma: no cover
    r = load_registry()
    print(f"registry_version={r.get('registry_version')} setups={len(r['setups'])} hash={registry_hash(r)}")
    for s in r["setups"]:
        print(f"  {s['setup_id']:32} {s['display_label']:20} {s['operating_state']:22} {s['active_window_et']}")
