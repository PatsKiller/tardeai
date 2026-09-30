"""PR-7 (2026-09-28, root cause 5): GO alerts carry delivery evidence; collectors own the lane.

- `screener_go_alerts` sends through `send_telegram_with_id`; the ledger and receipt record the
  provider message id, `accepted_no_id` is not "sent", a failed send is not recorded, and a
  CIO-held GO says whether the mandatory review was enqueued (`review_requested`).
- health collectors: GO→proposal conversion, underfilled streaks for real reasons (never
  PREOPEN_WINDOW_BY_DESIGN), social-inject failures.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402


def _by_path(name: str, rel: str):
    # conftest also puts the DEV tree's scripts/ on sys.path; a bare import can resolve to that copy
    # (memory: "module import picked wrong copy"). Load THIS tree's file explicitly.
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ha = _by_path("health_agent_pr7", "scripts/health_agent.py")
g = _by_path("screener_go_alerts_pr7", "scripts/screener_go_alerts.py")
sg = _by_path("cio_telegram_stance_gate_pr7", "scripts/lib/cio_telegram_stance_gate.py")

ITEM = {
    "row": {"symbol": "TEST", "run_label": "0700", "scanned_at": "2026-09-28T11:00:00", "score": 49, "grade": "A+",
            "decision": "GO", "rvol": 8.2, "price": 6.4, "change_pct": 12.0, "gap_pct": 9.5, "float_m": 12.0,
            "volume": 3_400_000, "catalyst": "FDA", "catalyst_verified": True, "source": "screener"},
    "tier": "A+",
    "passed": ["price", "float", "rvol", "gap", "volume", "score", "catalyst"],
}


def _allow_gate(monkeypatch):
    monkeypatch.setenv("TELEGRAM_RICH_ALERTS", "0")
    monkeypatch.setattr(g, "_cio_go_gate", lambda sym, text, db_query=None: {"allow": True, "annotation_text": ""})


def test_receipt_records_message_id_as_sent(monkeypatch):
    _allow_gate(monkeypatch)
    r = g._send_go_receipt(ITEM, sender_with_id=lambda text, **kw: {"accepted": True, "message_id": "777"})
    assert r["sent"] and r["message_id"] == "777" and r["delivery"] == "sent"


def test_accepted_without_id_is_not_sent(monkeypatch):
    _allow_gate(monkeypatch)
    r = g._send_go_receipt(ITEM, sender_with_id=lambda text, **kw: {"accepted": True, "message_id": None})
    assert r["sent"] and r["delivery"] == "accepted_no_id"
    r2 = g._send_go_receipt(ITEM, sender_with_id=lambda text, **kw: {"accepted": False})
    assert not r2["sent"] and r2["delivery"] == "failed"


def test_plain_transport_fallback_when_module_has_no_id_entry(monkeypatch):
    _allow_gate(monkeypatch)
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda msg, **kw: True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    r = g._send_go_receipt(ITEM)
    assert r["sent"] and r["delivery"] == "accepted_no_id"


def test_held_go_carries_review_requested(monkeypatch):
    monkeypatch.setenv("TELEGRAM_RICH_ALERTS", "0")
    monkeypatch.setattr(g, "_cio_go_gate", lambda sym, text, db_query=None: {"allow": False, "held_reason": sg.HELD_MISSING,
                                                                            "review_requested": True, "review_status": "queued"})
    r = g._send_go_receipt(ITEM, sender_with_id=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send")))
    assert not r["sent"] and r["held_reason"] == sg.HELD_MISSING and r["review_requested"] is True


def test_stance_gate_verdict_exposes_review_request(monkeypatch):
    monkeypatch.setattr(sg, "load_cio_view", lambda sym, q=None: None)
    monkeypatch.setattr(sg, "request_missing_stance_review", lambda sym, source=None, **k: {"review_requested": True, "review_status": "queued"})
    monkeypatch.setattr(sg, "record_hold", lambda *a, **k: None)
    v = sg.check_investment_send(symbol="TEST", message_text="GO", asserted_stance="bullish", db_query=lambda *a, **k: [])
    assert v.allow is False and v.held_reason == sg.HELD_MISSING and v.review_requested is True and v.review_status == "queued"
    v2 = sg.check_investment_send(symbol="TEST", message_text="GO", asserted_stance="bullish", db_query=lambda *a, **k: [], request_review=False)
    assert v2.review_requested is False and v2.review_status == "skipped_observe_only"


def test_main_report_lists_deliveries_and_review_flags():
    src = (ROOT / "scripts/screener_go_alerts.py").read_text()
    assert '"deliveries": deliveries' in src and '"review_requested": rcpt.get("review_requested")' in src
    assert 'rcpt = _send_go_receipt(item, db_query=_cio_db)' in src


# ---- collectors

def test_go_conversion_assessor():
    assert ha._assess_go_conversion(0, 0, {}, 5)["finding"] is False
    assert ha._assess_go_conversion(3, 1, {}, 5)["finding"] is False
    # Policy-gate skips only → warning (gates working; not a silent pipeline death)
    a = ha._assess_go_conversion(6, 0, {"SKIPPED_STRATEGY_CRITERIA": 20, "SKIPPED_NO_ANALYST": 59}, 5)
    assert a["type"] == "momentum_scalp_go_not_converting" and a["severity"] == "warning"
    assert "SKIPPED_NO_ANALYST=59" in a["message"]
    assert ha._assess_go_conversion(2, 0, {}, 5)["severity"] == "warning"
    # Unexpected skip reason with enough GO rows → still critical
    b = ha._assess_go_conversion(6, 0, {"SKIPPED_UNKNOWN_BUG": 3, "SKIPPED_NO_ANALYST": 1}, 5)
    assert b["severity"] == "critical"


def test_go_conversion_collector_reads_db(monkeypatch):
    calls = []

    def fake_db(sql, params=None, fetch="one"):
        calls.append(sql)
        if "trade_ai_scans" in sql:
            return {"n": 4}
        return [{"decision": "SKIPPED_LOW_SCORE", "n": 18}, {"decision": "CREATED", "n": 0}]

    monkeypatch.setattr(ha, "_db", fake_db)
    monkeypatch.setattr(ha, "_POLICY", {"lane_ownership": {"enabled": True, "conversion_window_days": 5}})
    out = ha.collect_go_to_proposal_conversion()
    assert len(out) == 1 and out[0]["type"] == "momentum_scalp_go_not_converting" and out[0]["skips"] == {"SKIPPED_LOW_SCORE": 18}


def test_underfilled_streak_ignores_by_design():
    hist = [("RUN_UNDERFILLED", ["UNIVERSE_TOO_SMALL"]), ("RUN_UNDERFILLED", ["UNIVERSE_TOO_SMALL"]), ("RUN_FAILED", ["CSV_EMPTY"]), ("RUN_HEALTHY", [])]
    a = ha._assess_underfilled_streak(hist, 3)
    assert a["finding"] and a["type"] == "screener_run_underfilled_streak"
    by_design = [("RUN_UNDERFILLED", ["PREOPEN_WINDOW_BY_DESIGN"])] * 5
    assert ha._assess_underfilled_streak(by_design, 3)["finding"] is False
    assert ha._assess_underfilled_streak(hist[:2] + [("RUN_HEALTHY", [])], 3)["finding"] is False


def test_social_inject_counter_and_glob(tmp_path, monkeypatch):
    text = "x\n  [live] social inject ERROR: boom\n  [live] social inject warning: 'bool' object is not iterable\n  [live] 20 tickers\n"
    assert ha._count_social_inject_errors(text) == 2
    (tmp_path / "continuous_20260927.log").write_text("old")
    newer = tmp_path / "continuous_20260928.log"; newer.write_text(text * 2)
    monkeypatch.setattr(ha, "LOG_DIR", tmp_path)
    monkeypatch.setattr(ha, "DEV_ROOT", tmp_path / "nowhere")
    assert ha._freshest_glob_log("continuous_*.log") == newer
    monkeypatch.setattr(ha, "_POLICY", {"lane_ownership": {"enabled": True, "social_inject_errors": 3}})
    out = ha.collect_social_inject_errors()
    assert len(out) == 1 and out[0]["type"] == "scanner_social_inject_failing"


def test_collectors_registered_and_policy_declared():
    for fn in (ha.collect_go_to_proposal_conversion, ha.collect_underfilled_streak, ha.collect_social_inject_errors):
        assert fn in ha.COLLECTORS
    pol = json.loads((ROOT / "config/health_agent_policy.json").read_text())["lane_ownership"]
    assert pol["enabled"] is True and pol["conversion_window_days"] == 5 and pol["underfilled_streak"] == 3
