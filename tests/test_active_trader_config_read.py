#!/usr/bin/env python3
"""AT-CFG-S1 Active Trader config read endpoint — read-only, zero-authority, all-8-panels,
NO secret-value leak, drift detection, and the feed-tier-ladder monotonicity invariant."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.read_http import dispatch, ACTIVE_TRADER_PREFIX          # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI                  # noqa: E402
from active_trader import config_read                                      # noqa: E402

API = ReadOnlyActiveTraderAPI()
PANELS = ("strategy_registry", "setup_taxonomy", "criteria_matrix", "data_sources",
          "feed_tier_ladder", "job_health", "execution_posture", "provenance")


@pytest.fixture(scope="module")
def overview():
    return config_read.config_overview()


# --------------------------------------------------------------------- routing / shape

def test_endpoint_returns_all_eight_panels():
    status, body = dispatch(API, "GET", f"{ACTIVE_TRADER_PREFIX}/config")
    assert status == 200
    for key in PANELS:
        assert key in body, f"missing panel: {key}"


def test_endpoint_get_only_no_write():
    status, body = dispatch(API, "POST", f"{ACTIVE_TRADER_PREFIX}/config")
    assert status == 405
    assert body["write"] is False


def test_top_level_read_only_zero_authority(overview):
    assert overview["read_only"] is True
    assert overview["write"] is False
    assert overview["contract"] == "active-trader-at-cfg-s1-read-v1"
    assert all(v is False for v in overview["authority"].values())


def test_every_panel_carries_read_only_and_authority(overview):
    for key in PANELS:
        panel = overview[key]
        assert panel.get("read_only") is True, f"{key} not read_only"
        auth = panel.get("authority", {})
        assert auth.get("mutation") is False and auth.get("order") is False
        assert auth.get("financial_action") is False


# --------------------------------------------------------------------- NO SECRET LEAK

# Known live secret VALUES must never appear. We read them from .env and assert their
# absence in the serialized payload (belt), plus a heuristic high-entropy scan (suspenders).
def _dotenv_values():
    p = ROOT / ".env"
    vals = {}
    if not p.is_file():
        return vals
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            vals[k.strip()] = v
    return vals


def test_no_known_secret_value_in_payload(overview):
    blob = json.dumps(overview, default=str)
    leaked = []
    for name, val in _dotenv_values().items():
        # only test values long enough to be a real secret (avoid 'true'/'paper' false hits)
        if len(val) >= 12 and val in blob:
            leaked.append(name)
    assert not leaked, f"secret VALUES leaked into payload: {leaked}"


def test_no_secret_like_token_patterns(overview):
    blob = json.dumps(overview, default=str)
    # secret-shaped tokens: long base64/hex/JWT/bearer-ish runs
    patterns = [
        r"eyJ[A-Za-z0-9_\-]{20,}",                 # JWT
        r"sk-[A-Za-z0-9]{20,}",                     # OpenAI-style
        r"xox[baprs]-[A-Za-z0-9\-]{10,}",           # slack
        r"AKIA[0-9A-Z]{16}",                        # AWS
        r"\b[0-9]{8,10}:[A-Za-z0-9_\-]{30,}\b",     # telegram bot token
        r"\b[A-Fa-f0-9]{40,}\b",                    # long hex secret
    ]
    hits = [p for p in patterns if re.search(p, blob)]
    assert not hits, f"secret-shaped token(s) present: {hits}"


def test_credential_slots_are_name_plus_bool_only(overview):
    slots = overview["execution_posture"]["credential_slots"]
    assert slots, "expected credential slots"
    for s in slots:
        assert set(s.keys()) == {"name", "populated"}, f"slot leaks extra fields: {s}"
        assert isinstance(s["populated"], bool)
        # the value itself must never be a field
        assert "value" not in s and "secret" not in s and "masked" not in s


# --------------------------------------------------------------------- drift detection

def test_drift_surfaces_float_ceiling_disagreement(overview):
    strategies = overview["strategy_registry"]["strategies"]
    ms = next(s for s in strategies if s["key"] == "momentum_scalp")
    fc = ms["drift"]["float_ceiling"]
    assert fc["agree"] is False, "known float-ceiling drift must be flagged"
    vals = {k: v["value"] for k, v in fc["values"].items()}
    # the three canonical live values (YAML 20, DB 100, engine 30) must all be present
    assert vals["yaml"] == 20
    assert vals["db"] == 100
    assert vals["engine"] == 30


def test_criteria_matrix_float_and_stop_contradictions(overview):
    crits = {c["criterion"]: c
             for c in overview["criteria_matrix"]["strategies"]["momentum_scalp"]["criteria"]}
    assert crits["float_ceiling"]["agree"] is False
    assert crits["stop_cap"]["agree"] is False
    # classifier guard evidence present and quotes enforcing lines
    guard = overview["criteria_matrix"]["strategies"]["momentum_scalp"]["_classifier_guard_evidence"]
    assert guard["enforcing_lines"]
    files = {e["file"] for e in guard["enforcing_lines"]}
    assert "scripts/social_scalp_scanner.py" in files


def test_setup_taxonomy_persisted_null_counts(overview):
    persisted = overview["setup_taxonomy"]["persisted"]
    assert persisted["table"] == "scalp_ignition_events"
    # populated + null must reconcile to total
    assert (persisted["primary_setup_id_populated_total"]
            + persisted["primary_setup_id_null_total"]) == persisted["total_rows"]


# --------------------------------------------------------------------- ladder invariant

def test_ladder_invariant_ok_on_live_config(overview):
    ladder = overview["feed_tier_ladder"]
    assert ladder["invariant_ok"] is True
    assert ladder["invariant_violations"] == []


def test_ladder_invariant_flags_synthetic_violation():
    # size multiplier INCREASES as quality descends (T0 > T2) -> must be flagged
    v = config_read.check_ladder_invariant(
        ["T2", "T1", "T0"],
        {"T2": 0.4, "T1": 0.7, "T0": 1.0},          # ascending = wrong
        {"T2": 8, "T1": 20, "T0": 40},
    )
    assert v, "increasing size multiplier must produce a violation"
    assert any(x["field"] == "size_multiplier" for x in v)

    # slippage DECREASES as quality descends -> must be flagged
    v2 = config_read.check_ladder_invariant(
        ["T2", "T1", "T0"],
        {"T2": 1.0, "T1": 0.7, "T0": 0.4},
        {"T2": 40, "T1": 20, "T0": 8},              # descending = wrong
    )
    assert any(x["field"] == "assumed_slippage_bps" for x in v2)


def test_ladder_invariant_clean_passes():
    assert config_read.check_ladder_invariant(
        ["T2", "T1", "T0"],
        {"T2": 1.0, "T1": 0.7, "T0": 0.4},
        {"T2": 8, "T1": 20, "T0": 40},
    ) == []


# --------------------------------------------------------------------- provenance

def test_provenance_has_shas_and_tree_state(overview):
    prov = overview["provenance"]
    assert "config_commit_sha" in prov and "working_tree_clean" in prov
    assert "fetched_at" in prov
    assert prov["config_files"]["momentum_scalp"]["path"] == "config/strategies/momentum_scalp.yaml"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
