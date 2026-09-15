"""The CIO entry-state alerts reach the Telegram transport (operator decision 2026-09-15 (b)).

Both operator sends in cio_entry_state_runner (the per-name alert and the overflow digest) go
through operator_send(). Firing it with a BUY READY and a digest body proves the router does not
swallow either message class.
"""
from __future__ import annotations

import sys
import types
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

COVERS = ["scripts/cio_entry_state_runner.py"]

from lib import cio_entry_state as ces  # noqa: E402
from lib.market_cap_label import cap_label  # noqa: E402


def _evidence(**kw):
    base = {"symbol": "ACHV", "price": 7.0, "quote_age_h": 0.2, "entry_low": 6.9, "entry_high": 7.15,
            "stop": 6.6, "target": 9.5, "atr": 0.40, "quality_state": "ADMITTED", "cio_action": "RESEARCH_MORE",
            "wash_blocked": False, "held": False, "earnings_date": "2026-11-05",
            "market_cap_label": cap_label(744), "catalyst": "new institutional stake", "plan_source": "reentry_desk"}
    base.update(kw)
    return base


def _runner(monkeypatch):
    sent_cio, emitted = [], []
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_telegram_transport", types.SimpleNamespace(
        send_cio_message=lambda text, **kw: sent_cio.append((text, kw)) or {"sent": True}))

    class _Bus:
        def emit(self, event_type, payload, **kw):
            emitted.append((event_type, payload, kw))

    monkeypatch.setitem(sys.modules, "scripts.lib.cio_event_bus", types.SimpleNamespace(CIOEventBus=_Bus))
    import cio_entry_state_runner as runner
    return runner, sent_cio, emitted


def test_buy_ready_alert_reaches_the_operator_the_cio_desk_and_the_cio_bus(alarm_capture, monkeypatch):
    runner, sent_cio, emitted = _runner(monkeypatch)
    e = _evidence()
    r = ces.evaluate(e, today=date(2026, 9, 15))
    assert r["state"] == "BUY_READY"
    out = runner.send_alerts(r, e)
    alarm_capture.assert_fired(contains="BUY READY")
    assert out["operator"] is True and out["cio_desk"] is True and out["cio_bus"] is True
    assert sent_cio and sent_cio[0][1]["dedupe_key"] == ces.transition_key(r)
    assert emitted[0][0] == "watch.new_signal" and emitted[0][1]["state"] == "BUY_READY"


def test_overflow_digest_reaches_the_operator(alarm_capture, monkeypatch):
    runner, _, _ = _runner(monkeypatch)
    rows = [ces.evaluate(_evidence(symbol=s, price=7.25), today=date(2026, 9, 15)) for s in ("ACHV", "MYSZ")]
    out = runner.operator_send(ces.render_digest(rows))
    alarm_capture.assert_fired(contains="MYSZ")
    assert out == {"operator": True}


def test_a_transport_failure_is_reported_not_raised(monkeypatch):
    runner, _, _ = _runner(monkeypatch)
    import telegram_alert as TA

    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(TA, "send_telegram", _boom)
    out = runner.operator_send("🟢 CIO entry — BUY READY: ACHV")
    assert out["operator"] is False and "RuntimeError" in out["operator_error"]
