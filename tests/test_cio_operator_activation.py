"""Production activation tests for the CIO operator product.

Contract tests only — do not declare live COP PASS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_defer_revisit import process_due_defers
from scripts.lib.cio_holdings_delta import diff_holdings
from scripts.lib.cio_material_scan import scan_office, select_publications
from scripts.lib.cio_office_state import classify_reentry_rows, compact_holdings_rows
from scripts.lib.cio_alex_telegram import record_defer


def _plan(tmp_path, *, act_now=0, schg=True):
    decisions = [
        {
            "symbol": "SCHD",
            "stance": "Trim",
            "stance_code": "TRIM",
            "decision_id": "dec_5866156741de9046",
            "current_value_usd": 226513.15,
            "recommended_delta_usd": -44334.57,
            "why_now": "Advisory TRIM — SCHD concentration above single-name fire.",
            "counter_thesis": "Income sleeve may tolerate concentration.",
            "what_changes_call": "Weight falls under fire.",
            "act_now": False,
            "action_label": "STALE_REFRESH_REQUIRED",
        }
    ]
    if schg:
        decisions.append({
            "symbol": "SCHG",
            "stance": "Hold",
            "stance_code": "HOLD",
            "decision_id": "dec_59a0fe621eae74e5",
            "current_value_usd": 11.74,
            "recommended_delta_usd": 0,
            "why_now": "no new desk signal; hold",
            "act_now": False,
            "action_label": "STALE_REFRESH_REQUIRED",
        })
    return {
        "ok": True,
        "digest": "plan_test",
        "portfolio_value_usd": 1_282_947.74,
        "cash_total_usd": 578_107.50,
        "cash_reserved_usd": 256_589.55,
        "cash_investable_usd": 321_517.95,
        "cash_posture_status": "ABOVE_BAND",
        "net_recommended_deploy_usd": 370_637.05,
        "net_recommended_raise_usd": 49_119.10,
        "capital_uses": {"adds_usd": 0, "reentry_usd": 0, "new_positions": [
            {"symbol": "ADBE", "amount_usd": 5000, "note": "Re-entry NEAR ENTRY — ADBE"}
        ]},
        "position_decisions": decisions,
        "freshness_materiality_gate": {
            "act_now_count": act_now,
            "counts": {"ACT_NOW": act_now, "STALE_REFRESH_REQUIRED": 22, "WATCH": 0},
        },
    }


def test_baseline_does_not_invent_opens(tmp_path, monkeypatch):
    monkeypatch.setenv("CIO_HOLDINGS_SNAPSHOT_JSON", str(tmp_path / "snap.json"))
    monkeypatch.setenv("CIO_OFFICE_STATE_JSON", str(tmp_path / "state.json"))
    holdings = {
        "ok": True,
        "holdings": [
            {"symbol": "SCHG", "account": "schwab_taxable", "market_value": 8.21, "shares": 0.23},
            {"symbol": "SCHD", "account": "ira", "market_value": 226000, "shares": 800},
        ],
    }
    office = {
        "baseline_needed": True,
        "holdings": holdings,
        "previous_snapshot": None,
        "previous_office_state": None,
        "capital_plan": _plan(tmp_path),
        "reentry": {"rows": [], "freshness": {"actionable_count": 0}},
        "office_home": {},
    }
    rec = scan_office(dry_run=True, office=office, persist=True, max_publish=3)
    assert rec["baseline_captured"] is True
    assert rec["holdings_events"] == []
    assert not any(e.get("event") == "POSITION_OPENED" for e in rec["holdings_events"])
    ids = [((r.get("evaluate") or {}).get("decision_id")) for r in rec["results"]]
    assert not any(i and str(i).startswith("dec_open_SCHG") for i in ids)
    cash_ids = [i for i in ids if i and str(i).startswith("dec_cash_")]
    assert cash_ids, rec["results"]


def test_real_open_after_baseline(tmp_path, monkeypatch):
    prev = [{"symbol": "SCHD", "account": "ira", "market_value": 226000, "shares": 800}]
    curr = prev + [{"symbol": "NEW", "account": "ira", "market_value": 900, "shares": 2}]
    ev = diff_holdings(prev, curr)
    assert ev[0]["event"] == "POSITION_OPENED"
    assert ev[0]["symbol"] == "NEW"


def test_schg_transfer_not_purchase():
    ev = diff_holdings(
        [{"symbol": "SCHG", "account": "ira", "market_value": 11, "shares": 0.3}],
        [{"symbol": "SCHG", "account": "roth", "market_value": 11, "shares": 0.3}],
    )
    assert ev[0]["event"] == "ACCOUNT_TRANSFER_DETECTED"
    assert ev[0]["purchase_claimed"] is False


def test_hold_cash_when_no_act_now(tmp_path, monkeypatch):
    monkeypatch.setenv("CIO_HOLDINGS_SNAPSHOT_JSON", str(tmp_path / "snap.json"))
    monkeypatch.setenv("CIO_OFFICE_STATE_JSON", str(tmp_path / "state.json"))
    office = {
        "baseline_needed": True,
        "holdings": {"ok": True, "holdings": []},
        "previous_snapshot": None,
        "previous_office_state": None,
        "capital_plan": _plan(tmp_path, act_now=0),
        "reentry": {"rows": [{"symbol": "FATN", "intel": {"state": "WAIT"}}],
                    "freshness": {"actionable_count": 0}},
        "office_home": {},
    }
    rec = scan_office(dry_run=True, office=office, persist=False)
    actions = [((r.get("evaluate") or {}).get("decision_id"), r.get("event_type")) for r in rec["results"]]
    assert rec["reentry"]["call"] == "WAIT"
    assert rec["cash"]["cash_posture_status"] == "ABOVE_BAND"
    assert any(et == "HOLD_CASH" for _, et in actions), actions


def test_reentry_ready_classification():
    desk = {"rows": [
        {"symbol": "AAA", "intel": {"state": "READY TO REVIEW"}},
        {"symbol": "BBB", "intel": {"state": "NEAR ENTRY"}},
        {"symbol": "CCC", "wash_blocked": True, "intel": {"state": "READY TO REVIEW"}},
    ]}
    c = classify_reentry_rows(desk)
    assert c["call"] == "RE_ENTER"
    assert c["ready"] == ["AAA"]
    assert "CCC" in c["wash_blocked"]


def test_select_publications_caps_flood():
    cands = [
        {"decision_id": "dec_open_X_ira", "symbol": "X", "action": "RESEARCH"},
        {"decision_id": "dec_cash_1", "symbol": "CASH", "action": "HOLD_CASH"},
        {"decision_id": "dec_reentry_1", "symbol": "REENTRY", "action": "WAIT"},
        {"decision_id": "dec_trim_a", "symbol": "SCHD", "action": "TRIM"},
        {"decision_id": "dec_trim_b", "symbol": "V", "action": "TRIM"},
    ]
    got = select_publications(cands, max_publish=3)
    assert [g["decision_id"] for g in got] == ["dec_open_X_ira", "dec_cash_1", "dec_reentry_1"]


def test_defer_reopen_same_lineage(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("CIO_DEFER_LINEAGE_PATH", str(tmp_path / "defer.jsonl"))
    rec = record_defer(
        {"decision_id": "dec_defer_test", "symbol": "SCHD", "action": "TRIM",
         "why_now": "concentration fire line"},
        revisit_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    assert rec["ok"]
    monkeypatch.setenv("CIO_OFFICE_API_BASE", "http://127.0.0.1:9")  # fail-soft plan fetch
    out = process_due_defers(dry_run=True)
    assert out["due"] >= 1
    assert out["processed"]
    assert out["processed"][0]["decision_id"] == "dec_defer_test"
    # Isolated / unmarked test defers cannot become a live thesis.
    assert out["processed"][0]["reopened"] is False
    assert out["processed"][0].get("published") is False
    assert out["processed"][0]["reason"] in {
        "not_production_advisory_eligible",
        "exact_parent_unavailable",
    }


def test_compact_holdings_skips_cash():
    rows = compact_holdings_rows({
        "holdings": [
            {"symbol": "USD", "is_cash": True, "market_value": 100},
            {"symbol": "SCHG", "account": "t", "market_value": 11.74, "shares": 0.3},
        ]
    })
    assert [r["symbol"] for r in rows] == ["SCHG"]


def test_units_are_not_shadow_or_count_only():
    root = ROOT / "config/systemd/user"
    delivery = (root / "tradeai-cio-delivery.service").read_text()
    scan = (root / "tradeai-cio-material-scan.service").read_text()
    defer = (root / "tradeai-cio-defer-revisit.service").read_text()
    converse = (root / "tradeai-cio-telegram.service").read_text()
    assert "--mode live" in delivery
    assert "--mode shadow" not in delivery
    assert "--live" in scan
    assert "--dry-run" not in scan
    assert "due_defers()" not in defer
    assert "cio_defer_revisit.py" in defer
    assert "trade-ai-releases/portfolio-server/CURRENT/scripts/cio_telegram_bot.py" in converse
    assert (root / "tradeai-cio-delivery-shadow.service").is_file()
    assert (root / "tradeai-cio-material-scan-dry.service").is_file()
