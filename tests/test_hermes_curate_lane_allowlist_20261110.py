"""ANCHOR: HERMES_CURATE_LANE_ALLOWLIST_20261110 — the curate endpoints may offer only lanes the admission gate admits.

LQ-1831 M1 (rework, LQ-1834): after LQ-1808 r2 closed the ungated Anthropic lane, ``POST
/api/v2/hermes/curate-symbol`` still accepted and advertised ``lane="claude"`` and answered ``{"ok": true,
"status": "started"}``. The child it spawned always exits 75 at the admission gate (``LaneNotAdmitted``) and writes
no ``hermes_external_research`` row, so the endpoint's own "lane_status_summary on /hermes/intel will show why" could
show nothing. ``POST /api/v2/hermes/curate-top20`` filtered lanes through a second hardcoded tuple that still listed
``claude`` and, when nothing survived, silently substituted ``chatgpt``.

The pins: the endpoint's offer is the gate's decision (one authority, ``hermes_external_researcher.admission_for``),
a refused lane starts no child, an unreadable gate refuses everything and names the error, and a partial top-20
request names the lane it did not start instead of dropping it.

AUTHORITY: READ_ONLY_ADVISORY — no broker, no order, no live path; ``subprocess.Popen`` is replaced with a recorder,
so no child is ever spawned.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: The live registry row's allowlist for ``hermes_external_research`` (no claude, no anthropic, no claude model).
ROW_ALLOWED = {"mode": "automated", "allowed_lanes": ["fast", "deepseek-flash", "grok", "chatgpt"]}
CLAUDE_REFUSED = "lane=claude provider=anthropic not in allowed_lanes"

ADMISSIONS = {
    "deepseek": {"admitted": True, "reason": ""},
    "grok": {"admitted": True, "reason": ""},
    "chatgpt": {"admitted": True, "reason": ""},
    "claude": {"admitted": False, "reason": CLAUDE_REFUSED},
}


@pytest.fixture()
def endpoint_api(monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "_hermes_curate_running", lambda: False, raising=True)
    spawned: list[str] = []

    def _record(argv, **kwargs):
        spawned.append(" ".join(argv) if isinstance(argv, (list, tuple)) else str(argv))
        return object()

    monkeypatch.setattr(subprocess, "Popen", _record, raising=True)
    api_v2.spawned = spawned  # recorder handle for the test body
    return api_v2


def _gate(endpoint_api, monkeypatch, mapping=None):
    # raising=False so this file can also be run against the pre-fix head: there the endpoint ignores the
    # patch and answers from its own hardcoded tuple — which is exactly the defect the refusal tests must see.
    monkeypatch.setattr(endpoint_api, "_hermes_challenger_lane_admissions",
                        lambda: dict(mapping or ADMISSIONS), raising=False)


def _registry(monkeypatch, row):
    import lib.llm_consumption as LC

    monkeypatch.setattr(LC, "get_process_config", lambda process_id: dict(row), raising=True)


# ── the gate is the authority ────────────────────────────────────────────────


def test_the_real_gate_admits_exactly_the_registry_lanes(endpoint_api, monkeypatch):
    _registry(monkeypatch, ROW_ALLOWED)
    adm = endpoint_api._hermes_challenger_lane_admissions()
    assert sorted(lane for lane, v in adm.items() if v["admitted"]) == ["chatgpt", "deepseek", "grok"]
    assert adm["claude"]["admitted"] is False
    assert adm["claude"]["reason"] == CLAUDE_REFUSED


def test_the_offer_follows_the_gate_when_the_registry_changes(endpoint_api, monkeypatch):
    _registry(monkeypatch, {"mode": "automated", "allowed_lanes": ["grok"]})
    adm = endpoint_api._hermes_challenger_lane_admissions()
    assert [lane for lane, v in adm.items() if v["admitted"]] == ["grok"]
    out = endpoint_api._hermes_curate_symbol_challenger({"symbol": "SPCX", "lane": "deepseek"})
    assert out["ok"] is False and out["error"] == "lane_not_allowed"
    assert out["allowed"] == ["grok"]
    assert endpoint_api.spawned == []


def test_an_unreadable_registry_admits_nothing(endpoint_api, monkeypatch):
    import lib.llm_consumption as LC

    def _boom(process_id):
        raise RuntimeError("registry down")

    monkeypatch.setattr(LC, "get_process_config", _boom, raising=True)
    adm = endpoint_api._hermes_challenger_lane_admissions()
    assert not any(v["admitted"] for v in adm.values())
    assert all(v["reason"].startswith("registry_unreadable:RuntimeError") for v in adm.values())
    out = endpoint_api._hermes_curate_symbol_challenger({"symbol": "SPCX", "lane": "deepseek"})
    assert out["ok"] is False and out["allowed"] == []
    assert "registry_unreadable:RuntimeError" in out["refused"]["deepseek"]
    assert endpoint_api.spawned == []


# ── POST /hermes/curate-symbol ───────────────────────────────────────────────


def test_curate_symbol_refuses_claude_and_starts_nothing(endpoint_api, monkeypatch):
    _gate(endpoint_api, monkeypatch)
    out = endpoint_api._hermes_curate_symbol_challenger({"symbol": "SPCX", "lane": "claude"})
    assert out["ok"] is False
    assert out["error"] == "lane_not_allowed"
    assert out["requested"] == "claude"
    assert "claude" not in out["allowed"]
    assert out["refused"] == {"claude": CLAUDE_REFUSED}
    assert "exit 75" in out["message"] and "no research row" in out["message"]
    assert endpoint_api.spawned == [], "a refused lane must not spawn a child"


def test_curate_symbol_starts_an_admitted_lane(endpoint_api, monkeypatch):
    _gate(endpoint_api, monkeypatch)
    out = endpoint_api._hermes_curate_symbol_challenger({"symbol": "SPCX", "lane": "deepseek"})
    assert out["ok"] is True and out["status"] == "started" and out["lane"] == "deepseek"
    assert len(endpoint_api.spawned) == 1
    cmd = endpoint_api.spawned[0]
    assert "--lane deepseek" in cmd and "--symbol SPCX" in cmd


def test_curate_symbol_default_lane_is_still_deepseek(endpoint_api, monkeypatch):
    _gate(endpoint_api, monkeypatch)
    out = endpoint_api._hermes_curate_symbol_challenger({"symbol": "SPCX"})
    assert out["ok"] is True and out["lane"] == "deepseek"
    assert "--lane deepseek" in endpoint_api.spawned[0]


# ── POST /hermes/curate-top20 ────────────────────────────────────────────────


def test_curate_top20_names_a_refused_lane_and_starts_the_admitted_one(endpoint_api, monkeypatch):
    _gate(endpoint_api, monkeypatch)
    out = endpoint_api._hermes_curate_top20_trigger({"lanes": "chatgpt,claude"})
    assert out["ok"] is True and out["status"] == "started"
    assert out["lanes"] == "chatgpt"
    assert out["refused"] == {"claude": CLAUDE_REFUSED}
    assert "Not started" in out["message"] and "claude" in out["message"]
    assert len(endpoint_api.spawned) == 1 and "--lanes chatgpt" in endpoint_api.spawned[0]


def test_curate_top20_refuses_when_no_requested_lane_is_admitted(endpoint_api, monkeypatch):
    _gate(endpoint_api, monkeypatch)
    out = endpoint_api._hermes_curate_top20_trigger({"lanes": "claude"})
    assert out["ok"] is False and out["error"] == "lane_not_allowed"
    assert out["requested"] == ["claude"] and "claude" not in out["allowed"]
    assert "nothing was started" in out["message"]
    assert endpoint_api.spawned == []


def test_curate_top20_accepts_a_lane_list(endpoint_api, monkeypatch):
    _gate(endpoint_api, monkeypatch)
    out = endpoint_api._hermes_curate_top20_trigger({"lanes": ["chatgpt", "claude"]})
    assert out["ok"] is True and out["lanes"] == "chatgpt"
    assert out["refused"] == {"claude": CLAUDE_REFUSED}
    assert "--lanes chatgpt" in endpoint_api.spawned[0]


def test_a_lane_outside_the_candidate_list_says_unknown(endpoint_api, monkeypatch):
    _gate(endpoint_api, monkeypatch)
    out = endpoint_api._hermes_curate_symbol_challenger({"symbol": "SPCX", "lane": "gemini"})
    assert out["ok"] is False and out["error"] == "lane_not_allowed"
    assert out["refused"] == {"gemini": "unknown_lane"}
    assert endpoint_api.spawned == []


def test_curate_top20_default_is_still_chatgpt(endpoint_api, monkeypatch):
    _gate(endpoint_api, monkeypatch)
    out = endpoint_api._hermes_curate_top20_trigger({})
    assert out["ok"] is True and out["lanes"] == "chatgpt"
    assert "--lanes chatgpt" in endpoint_api.spawned[0]
