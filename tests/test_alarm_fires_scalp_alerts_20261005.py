"""C1 firing tests (2026-10-05) for the two send_telegram sites added on 10-03/10-04 without one.

`scripts/lib/scalp_advisory_alert.py` (#1424) and `scripts/active_trader/momentum_alerts.py`
(#1431/#1432) each gained a Telegram send that the alarm-coverage gate
(`tests/test_alarm_coverage.py`) counted as untested, so `main` failed `alarm_fires` after merge
(PR runs do not select that gate). Each test injects the alert condition and asserts the message
reaches the transport through the real telegram_alert.send_telegram chokepoint (comms editor
included), and that the failure path is recorded durably.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import scalp_advisory_alert as saa  # noqa: E402
from active_trader import momentum_alerts as ma  # noqa: E402

COVERS = ["scripts/lib/scalp_advisory_alert.py", "scripts/active_trader/momentum_alerts.py"]

NOW = 1_790_000_000.0
SIGNAL = {"symbol": "ZZTST", "strategy_id": "momentum_scalp", "setup_description": "gap and go",
          "signal_grade": "A", "signal_score": 82, "price": 4.12, "rvol": 9.4, "float_m": 7.1,
          "gap_pct": 31.0, "catalyst": "contract award", "catalyst_verified": True,
          "entry_high": 4.20, "stop_loss": 3.95, "target_1": 4.70}


def test_scalp_advisory_alert_reaches_the_transport(alarm_capture, tmp_path):
    r = saa.send_advisory_alert(SIGNAL, gates={"liquidity": "PASS"}, window_end_et="12:00", session="2026-10-05",
                                ledger_path=tmp_path / "sent.json", receipts_path=tmp_path / "r.jsonl")
    assert r["sent"] is True and r["status"] == "SENT"
    alarm_capture.assert_fired(contains="SCALP SETUP ZZTST")


def test_scalp_advisory_send_failure_is_recorded(tmp_path):
    def _boom(text):
        raise RuntimeError("telegram down")
    r = saa.send_advisory_alert(SIGNAL, gates={}, window_end_et="12:00", session="2026-10-05", send=_boom,
                                ledger_path=tmp_path / "sent.json", receipts_path=tmp_path / "r.jsonl")
    rows = [json.loads(x) for x in (tmp_path / "r.jsonl").read_text().splitlines() if x.strip()]
    assert r["status"] == "SEND_FAILED" and rows[-1]["status"] == "SEND_FAILED" and "telegram down" in rows[-1]["error"]


def _book():
    return {"bids": [(4.11, 5000)] * 10, "asks": [(4.12, 2000)] * 10, "ts_epoch": NOW - 1, "ts_source": "opend_server"}


def _tape():
    return [{"ts_epoch": NOW - 3 - i, "price": 4.12, "volume": 100, "direction": "BUY"} for i in range(30)][::-1]


def _candidate():
    return ma.Candidate(symbol="ZZTST", lane="BELOW", ign=40.0, fsm_state="FIRED", entry_ref=4.12, stop_ref=3.95,
                        rvol=9.4, float_mm=7.1, last=4.12, quote_ts_epoch=NOW - 2, fire_ts_epoch=NOW - 30,
                        session_date="2026-10-05")


def test_active_trader_alert_reaches_the_transport(alarm_capture, tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path))
    rows = ma.evaluate_pass([_candidate()], cfg=ma.AlertConfig(mode="send"), now=NOW,
                            fetch_primary_book=lambda s: _book(), fetch_primary_tape=lambda s: _tape(),
                            send_fn=ma.telegram_send)
    assert rows[0]["verdict"] == ma.ALERT and rows[0]["sent"] is True
    alarm_capture.assert_fired(contains=ma.AT_SCALP_ALERT_HEADER)


def test_active_trader_send_failure_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path))

    def _boom(**kw):
        raise RuntimeError("telegram down")
    ma.evaluate_pass([_candidate()], cfg=ma.AlertConfig(mode="send"), now=NOW,
                     fetch_primary_book=lambda s: _book(), fetch_primary_tape=lambda s: _tape(), send_fn=_boom)
    row = json.loads((tmp_path / "momentum_alerts.jsonl").read_text().splitlines()[-1])
    assert row["sent"] is False and "telegram down" in row["send_error"]


def test_pr_selection_pulls_alarm_gates_when_a_sender_changes():
    """PR runs never selected the coverage gate, so these sites went red only after merge."""
    import run_cio_hardening_ci as ci
    assert ci._touches_alarm_sites(["scripts/lib/scalp_advisory_alert.py"]) is True
    assert ci._touches_alarm_sites(["docs/INDEX.md", "tests/test_alarm_coverage.py"]) is False
    names = {n for n, _f in ci.GATES}
    assert set(ci.ALARM_GATE_NAMES) <= names
