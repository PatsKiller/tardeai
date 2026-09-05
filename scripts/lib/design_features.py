"""design_features.py — config-driven design toggles, with faults structurally exempt.

READ_ONLY_ADVISORY. Presentation only: this module can change how a surface
LOOKS. It can never change what a surface is willing to SAY.

WHY THE EXEMPTION IS CODE AND NOT A CONVENTION
----------------------------------------------
The header this serves spent a fortnight reporting a degraded run in healthy
green, because the tile coloured on `count_integrity` (RECONCILED) while
`freshness_status` said RUN_UNDERFILLED on the same object. That was an accident.
A feature flag that could switch off "▲ RUN UNDERFILLED" would let anyone
reproduce it deliberately, from a config file, with no code review — and the
green tile would look exactly as authoritative as it did before.

So the protected signals are not "flags that default to on". They are not flags
at all. Naming one in the config is a load ERROR, not an override: the operator
finds out at load time that the thing they tried to hide cannot be hidden,
rather than discovering months later that a surface went quiet.

Follows the activation-scope pattern in ``agent_feature_flags.py``: an explicit
allow set, an explicit deny set, and fail-closed on anything unrecognised.

    from lib.design_features import load_design_features
    flags = load_design_features()            # never raises; returns defaults on any fault

No network, no secrets, no side effects. Deterministic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SCHEMA = "DesignFeatures@v1"

DEFAULT_CONFIG_REL = "config/design_features.yaml"

# ── What may be switched ─────────────────────────────────────────────────────
# Cosmetics only: how loud, how dense, how much quiet provenance. Every one of
# these can be off and the header still reports every fault it knows about.
COSMETIC_FLAGS: dict[str, bool] = {
    # The ● / ▲ glyph beside each tile label.
    "state_dots": True,
    # The 3px coloured spine down the left of a tile (rowRail).
    "tile_rails": True,
    # Provenance on tiles that have no fault to report — "schwab · all_time",
    # "bearish · broad · neutral". Off leaves those tiles' meta line empty.
    "quiet_provenance": True,
    # "covers 99.6% of value" inline on the PORTFOLIO face. Off keeps it in the
    # tooltip and drill, which is where it lives by default.
    "coverage_pct_on_face": False,
    # The scheduled-slot / finished-at clocks on the SETUPS face. Off keeps them
    # in the tooltip. The UNDERFILLED verdict itself is protected, below.
    "run_clocks_on_face": True,
}

#: Non-boolean settings, with their permitted values. Fail closed to the first.
ENUM_FLAGS: dict[str, tuple[str, ...]] = {
    # normal = the shipped three-line tile. compact = tighter padding only;
    # it never removes a line, because removing a line is how content gets lost.
    "density": ("normal", "compact"),
}

# ── What may NOT be switched, and why ────────────────────────────────────────
# Each of these reports a fault. A surface that can be configured to stay quiet
# about a fault is worse than one that never had the signal: it looks healthy.
PROTECTED_SIGNALS: dict[str, str] = {
    "clock_divergence": (
        "two copies of the position clock disagreeing. Hiding it re-creates the "
        "defect where account_summaries.as_of said 2026-07-17 and the position "
        "rows said 2026-09-04, and the header showed one of them."
    ),
    "run_health": (
        "RUN_UNDERFILLED / RUN_PARTIAL / RUN_FAILED. A run that scanned 21 "
        "symbols against a floor of 40 must not be able to render as a healthy "
        "run, which is exactly what it did when only reconciliation was shown."
    ),
    "quote_coverage": (
        "degraded or unpriced quote coverage. The standing rule is that the "
        "quote surface may never read live while part of the aggregate depends "
        "on degraded input without stating its extent."
    ),
    "unaccounted_rows": (
        "scanned rows the tally cannot name. 48 classified of 60 scanned left 12 rows unnamed on screen for weeks."
    ),
    "missing_accounts": (
        "a funded account that did not report into today's P&L. Distinct from "
        "an empty account, which is cosmetic and is summarised, not hidden."
    ),
    "stale_surface": "a surface serving data older than its own freshness contract.",
    "undated_surface": "a value with no date at all — UNDATED must always be visible as UNDATED.",
}


class DesignFeatureError(ValueError):
    """A config that tried to do something the schema forbids."""


def _default_flags() -> dict[str, Any]:
    out: dict[str, Any] = dict(COSMETIC_FLAGS)
    for name, allowed in ENUM_FLAGS.items():
        out[name] = allowed[0]
    return out


def _coerce_bool(value: Any) -> bool | None:
    """YAML-ish truthiness, strict. Anything unrecognised is None (= use default)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "on", "1", "enabled"):
            return True
        if v in ("false", "no", "off", "0", "disabled"):
            return False
    return None


def validate_header_block(block: Any) -> tuple[dict[str, Any], list[str]]:
    """Resolve a raw `header:` mapping into flags, collecting every problem.

    Returns ``(flags, errors)``. Errors never stop the resolve — the caller gets
    usable defaults AND the list of what was wrong, so a typo degrades to the
    shipped behaviour instead of to a blank header.
    """
    flags = _default_flags()
    errors: list[str] = []
    if block is None:
        return flags, errors
    if not isinstance(block, dict):
        return flags, [f"header: must be a mapping, got {type(block).__name__}"]

    for key, raw in block.items():
        name = str(key).strip().lower()

        # 1. A protected signal is an ERROR, not an override. Fail loudly here
        #    so it cannot fail silently on screen.
        if name in PROTECTED_SIGNALS:
            errors.append(
                f"'{name}' is not a feature flag and cannot be configured — it reports "
                f"{PROTECTED_SIGNALS[name]} Remove it from the config."
            )
            continue

        # 2. Enumerated settings.
        if name in ENUM_FLAGS:
            allowed = ENUM_FLAGS[name]
            v = str(raw).strip().lower()
            if v in allowed:
                flags[name] = v
            else:
                errors.append(f"'{name}': {raw!r} is not one of {list(allowed)}; using {allowed[0]!r}")
            continue

        # 3. Cosmetic booleans.
        if name in COSMETIC_FLAGS:
            b = _coerce_bool(raw)
            if b is None:
                errors.append(f"'{name}': {raw!r} is not a boolean; using {COSMETIC_FLAGS[name]!r}")
            else:
                flags[name] = b
            continue

        # 4. Unknown: fail closed. A key nobody reads is a flag the operator
        #    thinks is doing something.
        errors.append(f"'{name}' is not a known design feature — ignored")

    return flags, errors


def load_design_features(path: Any = None, *, root: Any = None) -> dict[str, Any]:
    """Load and resolve the design feature config. Never raises.

    Any fault — missing file, unparseable YAML, wrong shape — degrades to the
    shipped defaults with the reason recorded. A design config is not worth
    taking a surface down for.
    """
    root_path = Path(root) if root else Path(__file__).resolve().parent.parent.parent
    cfg_path = Path(path) if path else root_path / DEFAULT_CONFIG_REL

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "source": str(cfg_path),
        "loaded": False,
        "errors": [],
        "protected_signals": sorted(PROTECTED_SIGNALS),
        "header": _default_flags(),
    }

    if not cfg_path.is_file():
        result["errors"] = [f"no config at {cfg_path}; using defaults"]
        return result

    try:
        import yaml  # local import: the defaults must work without pyyaml
    except ImportError:
        result["errors"] = ["pyyaml unavailable; using defaults"]
        return result

    try:
        doc = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — any parse fault degrades identically
        result["errors"] = [f"unparseable: {str(exc)[:200]}; using defaults"]
        return result

    if not isinstance(doc, dict):
        result["errors"] = ["top level must be a mapping; using defaults"]
        return result

    flags, errors = validate_header_block(doc.get("header"))
    result["header"] = flags
    result["errors"] = errors
    result["loaded"] = True
    return result


def env_override(name: str) -> bool | None:
    """One-shot override for a cosmetic flag, e.g. CC_DESIGN_STATE_DOTS=0.

    Protected signals have no env override either — the exemption is about the
    signal, not about which file the switch lives in.
    """
    key = str(name).strip().lower()
    if key in PROTECTED_SIGNALS or key not in COSMETIC_FLAGS:
        return None
    return _coerce_bool(os.environ.get(f"CC_DESIGN_{key.upper()}", ""))
