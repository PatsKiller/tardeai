"""Design feature flags — and the signals that are not flags.

The point of this module is the exemption, so most of these tests are about
what the config REFUSES to do. A flag system for a truth surface is only safe
if the refusal is code; a convention that says "please don't switch off the
warnings" is not a rail.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.design_features import (  # noqa: E402
    COSMETIC_FLAGS,
    ENUM_FLAGS,
    PROTECTED_SIGNALS,
    env_override,
    load_design_features,
    validate_header_block,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "design_features.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# ── the exemption ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("signal", sorted(PROTECTED_SIGNALS))
def test_no_protected_signal_can_be_configured(signal: str, tmp_path: Path) -> None:
    """Naming a fault signal is an ERROR, not an override.

    It has to fail at load, loudly, because the alternative is a surface that
    goes quiet and still looks authoritative — which is the exact defect the
    header was shipped with.
    """
    cfg = _write(tmp_path, f"schema: DesignFeatures@v1\nheader:\n  {signal}: false\n")
    out = load_design_features(cfg)
    assert any(signal in e and "cannot be configured" in e for e in out["errors"]), out["errors"]
    # and it must not appear as a resolved flag anyone could read
    assert signal not in out["header"]


@pytest.mark.parametrize("signal", sorted(PROTECTED_SIGNALS))
def test_a_protected_signal_has_no_env_override_either(signal: str) -> None:
    """The exemption is about the signal, not about which file the switch is in."""
    assert env_override(signal) is None


def test_protected_and_cosmetic_sets_never_overlap() -> None:
    """A name in both would make the exemption depend on lookup order."""
    assert not (set(PROTECTED_SIGNALS) & set(COSMETIC_FLAGS))
    assert not (set(PROTECTED_SIGNALS) & set(ENUM_FLAGS))


def test_every_protected_signal_states_why() -> None:
    """A refusal with no reason gets deleted by the next person who hits it."""
    for name, reason in PROTECTED_SIGNALS.items():
        assert len(reason) > 40, f"{name} has no real justification"


# ── degrading, not failing ───────────────────────────────────────────────────


def test_a_missing_config_is_the_shipped_default_not_an_outage(tmp_path: Path) -> None:
    out = load_design_features(tmp_path / "absent.yaml")
    assert out["loaded"] is False
    assert out["header"] == {**COSMETIC_FLAGS, "density": ENUM_FLAGS["density"][0]}


def test_unparseable_config_degrades_to_defaults(tmp_path: Path) -> None:
    out = load_design_features(_write(tmp_path, "schema: [unclosed\n"))
    assert out["loaded"] is False
    assert out["header"]["state_dots"] is True
    assert out["errors"] and "unparseable" in out["errors"][0]


def test_a_bad_value_falls_back_and_says_so(tmp_path: Path) -> None:
    out = load_design_features(_write(tmp_path, "schema: DesignFeatures@v1\nheader:\n  state_dots: mayb\n"))
    assert out["header"]["state_dots"] is COSMETIC_FLAGS["state_dots"]
    assert any("not a boolean" in e for e in out["errors"])


def test_an_unknown_flag_is_reported_not_silently_kept(tmp_path: Path) -> None:
    """A key nobody reads is a switch the operator believes is doing something."""
    out = load_design_features(_write(tmp_path, "schema: DesignFeatures@v1\nheader:\n  hide_everything: true\n"))
    assert "hide_everything" not in out["header"]
    assert any("not a known design feature" in e for e in out["errors"])


def test_an_invalid_enum_falls_back_to_the_first_value(tmp_path: Path) -> None:
    out = load_design_features(_write(tmp_path, "schema: DesignFeatures@v1\nheader:\n  density: enormous\n"))
    assert out["header"]["density"] == "normal"
    assert any("density" in e for e in out["errors"])


# ── the cosmetics genuinely work ─────────────────────────────────────────────


def test_cosmetic_flags_actually_toggle(tmp_path: Path) -> None:
    """Negative control for the tests above: the refusals must not be blanket."""
    out = load_design_features(
        _write(
            tmp_path,
            "schema: DesignFeatures@v1\n"
            "header:\n"
            "  state_dots: false\n"
            "  tile_rails: off\n"
            "  quiet_provenance: no\n"
            "  coverage_pct_on_face: true\n"
            "  density: compact\n",
        )
    )
    assert out["errors"] == []
    assert out["header"]["state_dots"] is False
    assert out["header"]["tile_rails"] is False
    assert out["header"]["quiet_provenance"] is False
    assert out["header"]["coverage_pct_on_face"] is True
    assert out["header"]["density"] == "compact"


def test_the_shipped_config_is_valid() -> None:
    """The file in the repo must load with no errors, or it is documentation."""
    out = load_design_features()
    assert out["loaded"] is True, out["errors"]
    assert out["errors"] == [], out["errors"]


def test_protected_signals_are_published_to_clients() -> None:
    """A client must be able to see what is not configurable.

    Otherwise a UI infers it from absence, and the next person adds the flag.
    """
    out = load_design_features()
    assert set(out["protected_signals"]) == set(PROTECTED_SIGNALS)


def test_mixed_config_resolves_the_good_and_refuses_the_bad(tmp_path: Path) -> None:
    """One bad key must not discard the operator's valid intent."""
    out = load_design_features(
        _write(
            tmp_path,
            "schema: DesignFeatures@v1\nheader:\n  density: compact\n  run_health: false\n  state_dots: false\n",
        )
    )
    assert out["header"]["density"] == "compact"
    assert out["header"]["state_dots"] is False
    assert any("run_health" in e for e in out["errors"])


def test_a_non_mapping_header_is_rejected_whole() -> None:
    flags, errors = validate_header_block(["state_dots"])
    assert flags == {**COSMETIC_FLAGS, "density": ENUM_FLAGS["density"][0]}
    assert errors and "must be a mapping" in errors[0]
