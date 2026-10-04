"""Active Trader alerts go live (operator decisions 2026-10-04):

- the comms editor exempts ONLY Active Trader scalp alerts from the missing-CIO hold; ordinary
  bullish text and CIO disagreements are still held;
- alerts are sent straight to Telegram (router bypassed) with their own class;
- every live pass writes a heartbeat; the read API serves the feed, counts, vetoes and precision.

Stubs only: no Telegram, no database, no OpenD.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import momentum_alert_pass as mp  # noqa: E402
from active_trader import momentum_alerts_api as api  # noqa: E402
from active_trader import read_http  # noqa: E402
from scripts.lib import comms_editor as ce  # noqa: E402

NOW = 1_790_000_000.0


@pytest.fixture(autouse=True)
def _dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    monkeypatch.setattr(ma, "_cc_base", lambda: "https://cc.example")
    return tmp_path / "at"


class _Ledger(ce.DuplicateLedger):
    def __init__(self):
        pass

    def check(self, *a, **k):
        return None

    def record(self, *a, **k):
        pass


def _resolve(text):
    return [{"symbol": "SOUN", "guid": "f6994413-0000-0000-0000-000000000000"}] if "SOUN" in text else []


def _alert_text(kind=ma.TRIGGERED):
    c = ma.Candidate(symbol="SOUN", lane="BELOW", ign=41, fsm_state="FIRED", setup_label="Bull flag",
                     last=5.86, entry_ref=5.86, stop_ref=5.70, rvol=6.2, float_mm=310.0)
    l2 = {"source": "moomoo", "levels": 10, "depth_ratio": 1.45, "spread_bps": 17.1, "age_s": 1.0}
    tape = {"source": "moomoo", "buy_ratio": 0.71, "prints": 50, "age_s": 2.0}
    t, b = ma.build_message(c, kind, l2, tape, {"quote_age_s": 1.0})
    return f"{t}\n{b}"


def _edit(text, db_query=None):
    return ce.edit(text, chat_id="test", ledger=_Ledger(), resolve=_resolve, db_query=db_query)


# ── comms editor exemption ────────────────────────────────────────────────────

def test_triggered_alert_is_not_held_for_missing_cio_decision():
    d = _edit(_alert_text())
    assert d.held_reason is None
    assert "at_scalp_cio_missing_exempt:SOUN" in d.changes
    assert "exempt by operator, 2026-10-04" in d.text


def test_ordinary_bullish_message_is_still_held():
    d = _edit("SOUN looks like a BUY here")
    assert d.held_reason == "cio_decision_missing"


def test_forged_header_without_not_an_order_line_is_still_held():
    d = _edit("ACTIVE TRADER · SCALP ALERT\nSOUN BUY now")
    assert d.held_reason == "cio_decision_missing"


def test_cio_disagreement_still_holds_a_scalp_alert():
    def bearish(sql, params=None):
        return [{"symbol": "SOUN", "action": "AVOID", "status": "ACTIVE", "created_at": "2026-10-04"}]
    d = _edit(_alert_text(), db_query=bearish)
    assert d.held_reason is not None


def test_header_is_the_first_line_and_carries_the_deep_link():
    text = _alert_text()
    assert text.splitlines()[0] == ma.AT_SCALP_ALERT_HEADER == ce.AT_SCALP_ALERT_HEADER
    assert "https://cc.example/v3/active-trader?tab=Alerts" in text
    assert ce.is_active_trader_scalp_alert(text)


# ── delivery ──────────────────────────────────────────────────────────────────

def test_telegram_send_bypasses_router_with_own_class(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(send_telegram=lambda msg, **kw: calls.append((msg, kw)) or True)
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    res = ma.telegram_send(alert_type="at_scalp_triggered", title="T", body="B")
    assert res == {"sent": True, "alert_type": "at_scalp_triggered", "channel": "telegram"}
    assert calls[0][0] == "T\nB"
    assert calls[0][1] == {"bypass_router": True, "message_class": "active_trader_scalp_alert"}


class _Src:
    def quote(self, s): return 5.01, NOW - 2
    def book(self, s): return {"bids": [(5.00, 5000)] * 10, "asks": [(5.01, 2000)] * 10, "ts_epoch": NOW - 1}
    def tape(self, s): return [{"ts_epoch": NOW - 3 - i, "price": 5.0, "volume": 100, "direction": "BUY"} for i in range(30)][::-1]
    def close(self): pass


def _fire_pass(cfg, monkeypatch, sent):
    from datetime import datetime, timezone
    fake = types.SimpleNamespace(send_telegram=lambda msg, **kw: sent.append(msg) or True)
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    results = [{"symbol": "ABCD", "lane": "BELOW", "ign": 40.0, "rvol_tod": 9.0}]
    fires = [{"symbol": "ABCD", "fire_minute": 61, "entry": 5.01, "stop": 4.90,
              "fire_ts": datetime.fromtimestamp(NOW - 20, timezone.utc).isoformat()}]
    return mp.run_from_logger(None, cfg, results, fires, {"ABCD": "FIRED"}, day="2026-10-05", now=NOW, source=_Src())


def test_send_mode_delivers_through_telegram(monkeypatch, _dir):
    sent = []
    res = _fire_pass({"active_trader_alerts": {"mode": "send"}}, monkeypatch, sent)
    assert res["sent"] == 1 and len(sent) == 1 and sent[0].startswith(ma.AT_SCALP_ALERT_HEADER)
    hb = json.loads((_dir / "momentum_alerts_heartbeat.json").read_text())
    assert hb["mode"] == "send" and hb["last_pass"]["sent"] == 1


def test_shadow_mode_never_sends(monkeypatch):
    sent = []
    res = _fire_pass({}, monkeypatch, sent)
    assert res["alerts"] == 1 and res["sent"] == 0 and sent == []


def test_heartbeat_written_even_when_nothing_qualifies(_dir):
    res = mp.run_from_logger(None, {}, [{"symbol": "Q", "lane": "BELOW", "ign": 1.0}], [], {"Q": "IDLE"},
                             day="2026-10-05", now=NOW, source=_Src())
    assert res["evaluated"] == 0
    assert json.loads((_dir / "momentum_alerts_heartbeat.json").read_text())["symbols_scored"] == 1


def test_dry_run_writes_no_heartbeat(_dir):
    mp.run_from_logger(None, {}, [], [], {}, day="2026-10-05", now=NOW, source=_Src(), dry_run=True)
    assert not (_dir / "momentum_alerts_heartbeat.json").exists()


# ── read API ──────────────────────────────────────────────────────────────────

def test_alerts_feed_counts_vetoes_and_mode(monkeypatch, _dir):
    sent = []
    _fire_pass({"active_trader_alerts": {"mode": "send"}}, monkeypatch, sent)
    ma.append_journal({"contract": ma.CONTRACT, "run_id": "r2", "ts_epoch": NOW + 5, "kind": ma.TRIGGERED,
                       "verdict": ma.VETO, "veto_reasons": ["TAPE_SELLERS"], "sent": False,
                       "candidate": {"symbol": "PLUG", "session_date": "2026-10-05"}, "l2": {}, "tape": {}})
    monkeypatch.setattr(api, "_alert_config", lambda: ma.AlertConfig(mode="send"))
    snap = api.alerts_snapshot(session_date="2026-10-05", now=NOW + 60)
    assert snap["contract"] == "active-trader-alerts-feed-v1" and snap["mode"] == "send"
    assert snap["counts"] == {"triggered_alerts": 1, "armed_alerts": 0, "vetoes": 1, "sent": 1, "decisions": 2}
    assert snap["veto_reasons"] == {"TAPE_SELLERS": 1}
    assert [d["symbol"] for d in snap["decisions"]] == ["PLUG", "ABCD"]
    assert snap["engine"]["last_pass_age_s"] == 60
    assert snap["authority"]["order"] is False


def test_alerts_feed_empty_and_route(monkeypatch):
    monkeypatch.setattr(api, "_alert_config", lambda: ma.AlertConfig())
    snap = api.alerts_snapshot(session_date="2026-10-05", now=NOW)
    assert snap["decisions"] == [] and snap["mode"] == "shadow" and snap["engine"]["last_pass_at"] is None
    status, body = read_http.dispatch(None, "GET", "/api/v3/active-trader/alerts", {"limit": ["5"]})
    assert status == 200 and body["contract"] == "active-trader-alerts-feed-v1"
    status, _ = read_http.dispatch(None, "POST", "/api/v3/active-trader/alerts", {})
    assert status == 405


def test_repo_config_sets_send_mode():
    import yaml
    raw = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text(encoding="utf-8"))
    assert ma.AlertConfig.from_mapping(raw.get("active_trader_alerts")).mode == "send"
