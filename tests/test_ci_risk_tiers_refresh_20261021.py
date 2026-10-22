"""Risk tiers refresh (Release Train v2 Phase 0, 2026-10-21).

CC auth, the portfolio server / api_v2.py, Telegram routing and the n8n executor / relay /
gateway are HIGH tier: their named gates run in full on every PR that touches them, and the job
summary flags independent review. A MEDIUM path from which no registered test is reachable has
UNKNOWN impact and makes the pr profile run the broader suite (every gate) instead of smoke only.
Hermetic: synthetic maps plus the committed tiers and GATES.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("test_impact_tiers_refresh", ROOT / "scripts" / "lib" / "test_impact.py")
ti = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(ti)
_spec2 = importlib.util.spec_from_file_location(
    "run_cio_ci_tiers_refresh", ROOT / "scripts" / "run_cio_hardening_ci.py"
)
ci = importlib.util.module_from_spec(_spec2)
assert _spec2.loader is not None
_spec2.loader.exec_module(ci)

TIERS = ti.load_tiers()


@pytest.mark.parametrize(
    "path,category",
    [
        ("config/cc_auth.yaml", "cc_auth"),
        ("scripts/lib/cc_auth.py", "cc_auth"),
        ("scripts/portfolio_server.py", "portfolio_server_api"),
        ("scripts/portfolio_server_watchdog.sh", "portfolio_server_api"),
        ("scripts/api_v2.py", "portfolio_server_api"),
        ("scripts/telegram_alert.py", "telegram_routing"),
        ("scripts/telegram_alert_router.py", "telegram_routing"),
        ("scripts/telegram_alert_routing_policy.py", "telegram_routing"),
        ("scripts/operator_alert_policy_v2.py", "telegram_routing"),
        ("scripts/n8n_run_executor.py", "n8n_executor_relay_gateway"),
        ("scripts/n8n_run_relay.py", "n8n_executor_relay_gateway"),
        ("scripts/n8n_coordination_gateway.py", "n8n_executor_relay_gateway"),
        ("scripts/lib/n8n_coordination_gateway.py", "n8n_executor_relay_gateway"),
        ("config/n8n_run_allowlist.json", "n8n_executor_relay_gateway"),
    ],
)
def test_sensitive_paths_classify_high(path, category):
    assert ti.classify(path, TIERS) == ("high", category)


def test_every_new_category_glob_matches_a_real_file():
    for cat in ("cc_auth", "portfolio_server_api", "telegram_routing", "n8n_executor_relay_gateway"):
        for g in TIERS["high"][cat]["globs"]:
            rx = ti.glob_to_re(g)
            if "*" in g:
                continue  # a forward-looking pattern may match nothing yet
            assert (ROOT / g).is_file() and rx.match(g), g


def test_every_named_gate_exists_and_the_worst_case_still_fits_the_budget():
    names = {n for n, _f in ci.GATES}
    for cat, spec in TIERS["high"].items():
        assert set(spec["gates"]) <= names, cat
    gf = dict(ci.GATES)
    hints = ci.load_duration_hints()
    gates = set(TIERS["smoke_gates"]) | {g for s in TIERS["high"].values() for g in s["gates"]}
    files = {p for g in gates for p in gf[g]}
    assert sum(hints.get(p, ci.DEFAULT_FILE_SECONDS) for p in files) <= TIERS["budget_seconds"]


def test_high_change_runs_its_named_gates_even_with_zero_budget():
    sel = ti.select(
        ["config/cc_auth.yaml"],
        ci.GATES,
        impact_map={"rdeps": {}},
        tiers={**TIERS, "budget_seconds": 0},
        hints={},
    )
    ran = {n for n, _f in sel["gates"]}
    assert sel["tier"] == "high" and sel["high"] == {"cc_auth": ["config/cc_auth.yaml"]}
    assert set(TIERS["high"]["cc_auth"]["gates"]) <= ran
    assert sel["broaden_to_fast"] is False


# ----------------------------------------------------------------------------- unknown impact


def _sel(changed, rdeps, action="fast"):
    gates = [("smoke", ["tests/test_s.py"]), ("a", ["tests/test_a.py"])]
    tiers = {
        "budget_seconds": 100,
        "smoke_gates": ["smoke"],
        "unknown_impact": {"action": action},
        "high": {"policy": {"globs": ["AGENTS.md"], "gates": []}},
        "low": {"globs": ["docs/**"], "gates": []},
    }
    return ti.select(changed, gates, impact_map={"rdeps": rdeps}, tiers=tiers, hints={})


def test_medium_path_reaching_no_test_broadens_to_the_full_suite():
    sel = _sel(["apps/ui/src/x.tsx"], {})
    assert sel["unknown_impact"] == ["apps/ui/src/x.tsx"] and sel["broaden_to_fast"] is True


def test_medium_path_reaching_a_registered_test_does_not_broaden():
    sel = _sel(["scripts/x.py"], {"scripts/x.py": ["tests/test_a.py"]})
    assert sel["unknown_impact"] == [] and sel["broaden_to_fast"] is False


def test_a_path_reaching_only_unregistered_tests_is_unknown():
    sel = _sel(["scripts/x.py"], {"scripts/x.py": ["tests/test_unregistered.py"]})
    assert sel["broaden_to_fast"] is True


@pytest.mark.parametrize("path", ["docs/x.md", "AGENTS.md", "tests/test_a.py"])
def test_low_high_and_registered_test_paths_never_trigger_unknown_impact(path):
    assert _sel([path], {})["broaden_to_fast"] is False


def test_unknown_impact_action_smoke_keeps_the_old_behaviour():
    sel = _sel(["apps/ui/src/x.tsx"], {}, action="smoke")
    assert sel["unknown_impact"] == ["apps/ui/src/x.tsx"] and sel["broaden_to_fast"] is False


def test_committed_tiers_broaden_on_unknown_impact():
    assert TIERS["unknown_impact"]["action"] == "fast"


def test_runner_returns_every_gate_on_unknown_impact(monkeypatch):
    import sys

    sys.path.insert(0, str(ROOT))
    from scripts.lib import test_impact

    monkeypatch.setattr(test_impact, "load_map", lambda root: ({"rdeps": {}}, "cache"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("CIO_CI_SELECTION_OUT", raising=False)
    monkeypatch.setenv("PYTEST_ADDOPTS", os.environ.get("PYTEST_ADDOPTS", ""))
    gates, profile = ci.select_pr_gates("origin/main", changed=["apps/ui/src/never_referenced.tsx"])
    assert profile == "fast" and gates is ci.GATES
    gates, profile = ci.select_pr_gates("origin/main", changed=["docs/x.md"])
    assert gates is not ci.GATES
