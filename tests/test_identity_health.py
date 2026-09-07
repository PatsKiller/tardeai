"""The GUID spine's custodian. Deterministic by construction.

Audited 2026-09-06: **nothing watched identity at all.** 10,279 entities that
research, news and catalysts join against, with no freshness check, no coverage
regression alarm, and `build_catalyst_graph.py` carrying no cron and no timer.

The first live run fired `producer_unscheduled:build_catalyst_graph.py`, which is
the point: a control that has never been observed firing is indistinguishable
from its absence.
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import identity_health as IH  # noqa: E402

SRC = (ROOT / "scripts" / "lib" / "identity_health.py").read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


CODE = _code_only(SRC)


# ── no model may run in this lane ───────────────────────────────────────────

def test_no_llm_in_the_identity_path():
    """uuid5 is a pure function; a model in this path destroys auditability
    without adding information. An LLM's only legitimate identity role is
    proposing CANDIDATEs, which happens elsewhere and never commits."""
    lowered = CODE.lower()
    for banned in ("openai", "anthropic", "llm", "gpt", "deepseek", "grok",
                   "ollama", "completion", "prompt"):
        assert banned not in lowered, f"a model reference leaked into the custodian: {banned}"


def test_it_makes_no_network_calls_of_its_own():
    for banned in ("requests.", "urllib.request", "httpx", "aiohttp"):
        assert banned not in CODE, f"{banned} — the custodian must be local and deterministic"


# ── freshness must not false-positive over a weekend ────────────────────────

def test_the_freshness_grace_covers_a_weekend():
    """The minter runs weekdays. Alarming on Sunday because Friday was the last
    weekday run is the false positive this system produces most often — the same
    shape that made ticker_prices page at 26h."""
    assert IH.REGISTRY_MAX_AGE_HOURS >= 72, (
        f"{IH.REGISTRY_MAX_AGE_HOURS}h will fire every weekend")


# ── coverage regression ─────────────────────────────────────────────────────

def test_a_confirmed_drop_is_a_regression(tmp_path, monkeypatch):
    """The registry's rank is one-way, so CONFIRMED should never fall on its own.
    A fall means a feed stopped publishing identifiers."""
    state = tmp_path / "identity_health_state.json"
    state.write_text(json.dumps({"confirmed": 5000, "total": 10000}), encoding="utf-8")
    monkeypatch.setattr(IH, "_state_path", lambda: state)
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"entities": {
        f"E{i}": {"identity_status": "CONFIRMED", "identifiers": {"cusip": "X"}}
        for i in range(10)}}), encoding="utf-8")
    monkeypatch.setattr(IH, "_registry_path", lambda: reg)
    r = IH.collect_identity_health(check_schedulers=False)
    assert any(f.startswith("coverage_regressed") for f in r["firing"]), r["firing"]


def test_growth_is_not_a_regression(tmp_path, monkeypatch):
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"confirmed": 2, "total": 2}), encoding="utf-8")
    monkeypatch.setattr(IH, "_state_path", lambda: state)
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"entities": {
        f"E{i}": {"identity_status": "CONFIRMED", "identifiers": {"cusip": "X"}}
        for i in range(9)}}), encoding="utf-8")
    monkeypatch.setattr(IH, "_registry_path", lambda: reg)
    r = IH.collect_identity_health(check_schedulers=False)
    assert not any(f.startswith("coverage_regressed") for f in r["firing"])


def test_a_missing_registry_is_loud_not_silent(tmp_path, monkeypatch):
    """Zero entities must not read as healthy — two states cannot express
    'no input'."""
    monkeypatch.setattr(IH, "_registry_path", lambda: tmp_path / "nope.json")
    monkeypatch.setattr(IH, "_state_path", lambda: tmp_path / "s.json")
    r = IH.collect_identity_health(check_schedulers=False)
    assert "registry_unreadable" in r["firing"]
    assert r["ok"] is False


# ── scheduler check ─────────────────────────────────────────────────────────

def test_a_commented_cron_does_not_count_as_scheduled():
    """taxonomy_tagger's cron was commented out for two months and every audit
    that grepped for the filename found it."""
    fn = CODE.split("def _is_scheduled", 1)[1].split("\ndef ", 1)[0]
    assert "startswith('#')" in fn or 'startswith("#")' in fn


def test_both_schedulers_are_checked():
    """cron OR systemd — this system uses both, so checking one is how an
    unscheduled producer hides."""
    fn = CODE.split("def _is_scheduled", 1)[1].split("\ndef ", 1)[0]
    assert "crontab" in fn and "list-timers" in fn


def test_the_spine_producers_are_named():
    assert "mint_identity_registry.py" in IH.REQUIRED_PRODUCERS
    assert "build_catalyst_graph.py" in IH.REQUIRED_PRODUCERS


def test_state_is_not_tree_relative():
    """A per-checkout baseline resets on every deploy, which would make coverage
    regression permanently undetectable. Fifth instance of this shape today."""
    fn = CODE.split("def _state_path", 1)[1].split("\ndef ", 1)[0]
    assert "__file__" not in fn
    assert "TRADEAI_STATE_ROOT" in fn


def test_the_lane_shape_matches_its_siblings():
    r = IH.collect_identity_health(check_schedulers=False)
    for k in ("lane", "ok", "firing", "schema", "authority", "as_of"):
        assert k in r
    assert r["financial_action"] is False
    assert r["authority"] == "READ_ONLY_ADVISORY"
