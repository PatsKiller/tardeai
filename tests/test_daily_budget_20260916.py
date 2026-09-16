"""D3 (2026-09-16): durable daily send budget for the general DM.

Ops-exempt (capital-risk / operator-actionable) messages always page. Non-ops
P0 sends count against a 30/day budget persisted to disk, so the cap survives
cron/systemd restarts (AGENTS.md §7). Over budget, non-ops P0 → digest, never
dropped silent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import telegram_alert_router as r  # noqa: E402


def _clear(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "_BUDGET_PATH", tmp_path / "budget.json")


def test_ops_exempt_never_counts(monkeypatch, tmp_path):
    _clear(monkeypatch, tmp_path)
    assert r._ops_exempt("🚨 STOP HEALTH — ORPHANED: ANET") is True
    assert r._ops_exempt("🟢 READY ENTRY ALERT — AXTI") is True
    assert r._ops_exempt("🔥 GO ARMP — momentum scalp") is True
    assert r._ops_exempt("Material change — 2 names") is True
    assert r._ops_exempt("watch alert XAR price cross") is False
    assert r._ops_exempt("INDUSTRY MOMENTUM Asset Management") is False


def test_budget_is_durable_across_processes(tmp_path, monkeypatch):
    # Simulate a second invocation: write the ledger file, then read it fresh.
    p = tmp_path / "budget.json"
    p.write_text(json.dumps({r._budget_day(): 30}))
    monkeypatch.setattr(r, "_BUDGET_PATH", p)
    assert r._budget_count_today() == 30


def test_record_and_read_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "budget.json"
    monkeypatch.setattr(r, "_BUDGET_PATH", p)
    assert r._budget_count_today() == 0
    r._record_budget_send()
    r._record_budget_send()
    assert r._budget_count_today() == 2
    # durable on disk
    assert json.loads(p.read_text())[r._budget_day()] == 2


def test_over_budget_non_ops_p0_is_suppressed_to_digest(tmp_path, monkeypatch):
    p = tmp_path / "budget.json"
    p.write_text(json.dumps({r._budget_day(): r.DAILY_SEND_BUDGET}))
    monkeypatch.setattr(r, "_BUDGET_PATH", p)
    # A non-ops P0 (scalp GO) at the budget ceiling → suppressed (digest), recorded.
    monkeypatch.setattr(r, "classify_alert", lambda m: "P0_INTERRUPT")
    monkeypatch.setattr(r, "apply_rate_limit", lambda m: {"allowed": True, "reason": "ok"})
    res = r.should_send_telegram("🔔 Watch alert XAR price cross below 265.5 (not exempt)")
    assert res is False
    assert any("daily_budget_exceeded" in s["reason"] for s in r.get_suppression_log())
    # Ops-exempt still pages at the ceiling.
    assert r.should_send_telegram("🚨 STOP HEALTH — ORPHANED: ANET") is True


def test_mark_sent_counts_non_ops_p0_only(tmp_path, monkeypatch):
    p = tmp_path / "budget.json"
    monkeypatch.setattr(r, "_BUDGET_PATH", p)
    monkeypatch.setattr(r, "classify_alert", lambda m: "P0_INTERRUPT")
    # ops-exempt → not counted
    r.mark_sent("🚨 STOP HEALTH — ORPHANED: ANET")
    assert r._budget_count_today() == 0
    # non-ops P0 → counted
    r.mark_sent("🔔 Watch alert XAR price cross")
    assert r._budget_count_today() == 1
