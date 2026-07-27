#!/usr/bin/env python3
"""M3-S7 unit tests — ignition alert emitter (§3.4). Alerts only, NEVER proposals; gated + capped."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_alert_emitter as ae  # noqa: E402
from scalp_alert_emitter import lane_to_tier, emit_alerts, AlertBudget, build_alert, NOT_A_PROPOSAL  # noqa: E402


def row(sym, lane, ign=70.0):
    return {"symbol": sym, "lane": lane, "ign": ign, "subscores": {"v_rvol": 0.8, "v_burst": 0.3},
            "rvol_tod": 6.3}


def cfg(emit=True, cap=8):
    return {"notifications": {"emit": emit, "session_cap": cap, "info_min": 45, "alert_min": 60}}


class Recorder:
    def __init__(self): self.calls = []
    def __call__(self, **kw): self.calls.append(kw); return {"sent": True}


# ── lane → tier ─────────────────────────────────────────────────────
def test_lane_tier_mapping():
    assert lane_to_tier("IGN_45") == "INFO"
    assert lane_to_tier("IGN_60") == "ALERT"
    assert lane_to_tier("IGN_ACCEL") == "ALERT"
    assert lane_to_tier("IGN_75") == "ALERT"      # NOT a proposal in S7
    assert lane_to_tier("BELOW") is None


# ── gating ──────────────────────────────────────────────────────────
def test_emit_off_sends_nothing():
    rec = Recorder()
    assert emit_alerts([row("A", "IGN_60")], cfg(emit=False), AlertBudget(), dispatch_fn=rec) == []
    assert rec.calls == []

def test_below_never_alerts():
    rec = Recorder()
    d = emit_alerts([row("A", "BELOW")], cfg(), AlertBudget(), dispatch_fn=rec)
    assert d == [] and rec.calls == []


# ── tiers ───────────────────────────────────────────────────────────
def test_info_lane_dashboard_only_no_telegram_cap():
    rec = Recorder()
    b = AlertBudget(session_cap=8)
    d = emit_alerts([row("A", "IGN_45")], cfg(), b, dispatch_fn=rec)
    assert d[0]["tier"] == "INFO" and b.telegram_sent == 0   # INFO doesn't consume the telegram cap
    assert rec.calls[0]["tier"] == "INFO"

def test_alert_lane_dispatched_and_not_a_proposal():
    rec = Recorder()
    d = emit_alerts([row("A", "IGN_60")], cfg(), AlertBudget(), dispatch_fn=rec)
    assert d[0]["tier"] == "ALERT" and d[0]["proposal"] is False
    assert rec.calls[0]["tier"] == "ALERT" and rec.calls[0]["alert_type"] == "scalp_ignition"

def test_ign75_is_alert_not_proposal():
    rec = Recorder()
    d = emit_alerts([row("A", "IGN_75", ign=80)], cfg(), AlertBudget(), dispatch_fn=rec)
    assert d[0]["tier"] == "ALERT" and d[0]["proposal"] is False
    # no proposal-ish call ever
    assert all("proposal" not in c.get("alert_type", "") for c in rec.calls)

def test_alert_body_tagged_not_a_proposal():
    _, body = build_alert(row("A", "IGN_60"))
    assert NOT_A_PROPOSAL in body and "not tradeable" in body


# ── session cap + summary ───────────────────────────────────────────
def test_session_cap_and_one_summary():
    rec = Recorder()
    rows = [row(f"S{i}", "IGN_60") for i in range(12)]
    d = emit_alerts(rows, cfg(cap=8), AlertBudget(), dispatch_fn=rec)
    dispatched = [x for x in d if x.get("action") == "dispatch"]
    summaries = [x for x in d if x.get("action") == "cap_summary"]
    assert len(dispatched) == 8 and len(summaries) == 1
    # 8 symbol alerts + 1 summary send
    assert sum(1 for c in rec.calls if c["alert_type"] == "scalp_ignition") == 8
    assert sum(1 for c in rec.calls if c["alert_type"] == "scalp_ignition_summary") == 1


# ── dry-run ─────────────────────────────────────────────────────────
def test_dry_run_computes_but_never_sends():
    rec = Recorder()
    d = emit_alerts([row("A", "IGN_60")], cfg(), AlertBudget(), dispatch_fn=rec, dry_run=True)
    assert d[0]["tier"] == "ALERT" and rec.calls == []       # decision made, nothing sent


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
