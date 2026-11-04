"""Every DeepSeek lane alias must survive the model registry's id check.

2026-11-04: the `deepseek` research lane ran a 37.9% error rate / streak of 50 on
`RegistryError: legacy DeepSeek model id rejected: 'deepseek-v4-flash'`. The alias list in
scripts/llm_lane.py still accepted a model id that scripts/lib/llm_model_registry.py refuses, so the
failure was reachable from the tree we run. An alias list that drifts from the registry is the defect;
this test is the invariant that stops the next rename reproducing it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.llm_model_registry import RegistryError, reject_legacy_model_id  # noqa: E402
from scripts import llm_lane  # noqa: E402


def test_no_lane_alias_is_an_id_the_registry_rejects():
    # The ROUTING set only: _AMBIGUOUS_DEEPSEEK exists to raise a typed error and never routes, so its names are
    # deliberately not registry ids. Every alias that can select a model must be one.
    assert not (llm_lane._DEEPSEEK_LANES & llm_lane._AMBIGUOUS_DEEPSEEK)
    for alias in sorted(llm_lane._DEEPSEEK_LANES):
        if not alias.startswith("deepseek"):
            continue          # "fast", "pro", … are logical names, not model ids
        try:
            reject_legacy_model_id(alias)
        except RegistryError as exc:  # pragma: no cover - failure path
            raise AssertionError(f"lane alias {alias!r} is not a registry id: {exc}") from exc


def test_the_legacy_v4_names_are_not_accepted_lanes():
    assert "deepseek-v4-flash" not in llm_lane._DEEPSEEK_LANES
    assert "deepseek-v4-pro" not in llm_lane._DEEPSEEK_LANES
    assert llm_lane.available("deepseek-v4-flash") is False


def test_the_exact_alias_still_routes(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm_lane, "_deepseek_model_available", lambda mid: seen.setdefault("id", mid) and True)
    llm_lane.available("deepseek-flash")
    assert seen.get("id") == "deepseek-flash", seen


def test_the_run_manual_surface_agrees_about_the_legacy_names():
    """cc4 (2026-11-04): the invariant covered llm_lane only, and the run-manual endpoint still accepted
    `deepseek-v4-flash` as a WORKING lane one module away. Two surfaces disagreeing about one name is the drift this
    test exists to stop, so it covers every surface that can select a model id. Fails before the fix."""
    from scripts.lib import consumption_run_manual as crm

    for alias in sorted(crm.LANE_TO_POLICY):
        if alias.startswith("deepseek"):
            try:
                reject_legacy_model_id(alias)
            except RegistryError as exc:
                raise AssertionError(f"run-manual lane {alias!r} is not a registry id: {exc}") from exc
    assert "deepseek-v4-flash" not in crm.LANE_TO_POLICY
    assert "deepseek-v4-flash" not in crm.FLASH_LANES
    assert crm.classify_manual_lane("deepseek-v4-flash")["ok"] is False
    assert crm.classify_manual_lane("deepseek-flash")["ok"] is True
