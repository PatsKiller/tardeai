"""Market regime classifier — P0 fixes after the 2026-10-30 selloff RCA (DSN-20261031-market-risk-engine-P0-T1/T2).

Findings this test pins (docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md):
- classify() read `ORDER BY created_at DESC LIMIT 20` across collector runs and let the OLDEST row win per
  key, so the 2026-10-30 16:05 snapshot said `vix_close: normal` while the same-minute collector row said
  21.3 `high`. It must read only the latest collector snapshot_id.
- `scan_breadth_24h` counts how many symbols the scanner touched; it is not market breadth and must not
  score. `breadth_state` says so (`not_measured`) instead of `broad`.
- A regime change INTO risk_off / high_volatility is an operator-action intent (AGENTS.md §9.1): P1,
  dedupe window 0, never the P2 label-change ping that quiet hours archive. Alert errors surface instead
  of `except: pass`.
Hermetic: fake DB connection, telegram_alert / alert_dispatcher stubbed via sys.modules.
"""

from __future__ import annotations

#: C1 firing coverage — test_a_change_into_risk_off_is_a_p1_operator_action_intent injects the label change and asserts the
#: P1 reaches the (stubbed) transport; the one send_telegram site in the classifier funnels through that path.
COVERS = ["scripts/market_regime_classifier.py"]

import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import market_regime_classifier as mrc  # noqa: E402


def _row(key, signal, value=None, text=None):
    return (key, signal, Decimal(str(value)) if value is not None else None, text)


NEW_ROWS = [  # what the collector wrote one second ago (SNAP_new)
    _row("scan_breadth_24h", "broad", 60),
    _row("scan_score_avg", "bearish", 24.9),
    _row("gap_volatility_proxy", "high_vol", 4.52),
    _row("finviz_health", "risk_on", None, "healthy"),
    _row("news_sentiment_proxy", "neutral", 0.25),
    _row("vix_close", "high", 21.3),
    _row("market_session", "neutral", None, "afterhours"),
]
OLD_ROWS = [  # the previous run (SNAP_old), calm
    _row("scan_breadth_24h", "broad", 1243),
    _row("scan_score_avg", "bearish", 8.1),
    _row("gap_volatility_proxy", "neutral", 1.46),
    _row("finviz_health", "risk_on", None, "healthy"),
    _row("news_sentiment_proxy", "neutral", 16.06),
    _row("vix_close", "normal", 16.59),
    _row("market_session", "neutral", None, "afterhours"),
]


class FakeConn:
    """Serves indicator rows the way Postgres would: newest first for the legacy LIMIT 20 read."""

    def __init__(self, by_snapshot=None, latest="SNAP_new"):
        self.by_snapshot = by_snapshot if by_snapshot is not None else {"SNAP_new": NEW_ROWS, "SNAP_old": OLD_ROWS}
        self.latest = latest
        self.sql: list[str] = []

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, params=None):
                self._sql = " ".join(sql.split())
                self._params = list(params or [])
                conn.sql.append(self._sql)

            def fetchall(self):
                s = self._sql
                if "FROM market_regime_indicators" in s and "snapshot_id=%s" in s:
                    return list(conn.by_snapshot.get(self._params[0], []))
                if "FROM market_regime_indicators" in s and "LIMIT 20" in s:
                    # newest first, then older — the legacy shape that let the oldest row win per key
                    rows = []
                    for sid in ("SNAP_new", "SNAP_old", "SNAP_older"):
                        rows.extend(conn.by_snapshot.get(sid, []))
                    return rows[:20]
                return []

            def fetchone(self):
                s = self._sql
                if "SELECT snapshot_id FROM market_regime_indicators" in s:
                    return (conn.latest,) if conn.latest else None
                if "FROM market_regime_snapshots" in s:
                    return ("risk_on_trend",)
                return None

        return C()

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture(autouse=True)
def _session(monkeypatch):
    fake = types.ModuleType("market_session")
    fake.current_market_session = lambda: "afterhours"
    monkeypatch.setitem(sys.modules, "market_session", fake)


def test_classify_reads_only_the_latest_collector_snapshot():
    conn = FakeConn()
    snap = mrc.classify(conn)
    assert snap["inputs"]["vix_close"] == "high", snap["inputs"]
    assert snap["inputs"]["gap_volatility_proxy"] == "high_vol"
    assert snap["inputs"].get("_indicator_snapshot_id") == "SNAP_new"
    assert not any("LIMIT 20" in s for s in conn.sql), "the cross-run LIMIT 20 read must be gone"


def test_an_explicit_snapshot_id_is_honoured():
    conn = FakeConn()
    snap = mrc.classify(conn, snapshot_id="SNAP_old")
    assert snap["inputs"]["vix_close"] == "normal"
    assert snap["inputs"]["_indicator_snapshot_id"] == "SNAP_old"


def test_no_collector_rows_is_insufficient_not_a_calm_regime():
    conn = FakeConn(by_snapshot={}, latest=None)
    snap = mrc.classify(conn)
    assert snap["regime_label"] == "unknown"
    assert "insufficient_indicators" in snap["missing_data"]
    assert snap["stale_data"] is True


def test_scan_breadth_is_not_market_breadth_and_does_not_score():
    broad = FakeConn(by_snapshot={"SNAP_new": NEW_ROWS})
    narrow_rows = [r if r[0] != "scan_breadth_24h" else _row("scan_breadth_24h", "narrow", 12) for r in NEW_ROWS]
    narrow = FakeConn(by_snapshot={"SNAP_new": narrow_rows})
    a, b = mrc.classify(broad), mrc.classify(narrow)
    assert a["regime_label"] == b["regime_label"] and a["regime_score"] == b["regime_score"]
    assert a["breadth_state"] == "not_measured"
    assert "scan_breadth" not in a["missing_data"]


def test_high_vix_and_wide_gaps_classify_as_high_volatility_not_risk_on():
    snap = mrc.classify(FakeConn(by_snapshot={"SNAP_new": NEW_ROWS}))
    assert snap["regime_label"] in ("high_volatility", "risk_off"), snap
    assert snap["volatility_state"] == "high_vol"


def _stub_senders(monkeypatch):
    p1_calls, p2_calls = [], []
    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda msg, **k: p1_calls.append({"msg": msg, **k}) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    ad = types.ModuleType("alert_dispatcher")
    ad.dispatch_alert = lambda *a, **k: p2_calls.append({"args": a, **k}) or {"sent": True}
    monkeypatch.setitem(sys.modules, "alert_dispatcher", ad)
    return p1_calls, p2_calls


def _snap(label, vol="high_vol"):
    return {
        "regime_label": label,
        "volatility_state": vol,
        "trend_state": "bearish",
        "breadth_state": "not_measured",
        "confidence": 0.5,
        "inputs": {"vix_close": "high"},
    }


@pytest.mark.parametrize("label", ["risk_off", "high_volatility"])
def test_a_change_into_risk_off_is_a_p1_operator_action_intent(monkeypatch, label):
    p1, p2 = _stub_senders(monkeypatch)
    out = mrc._alert_regime_change("risk_on_trend", _snap(label))
    assert p1 and not p2, (p1, p2)
    call = p1[0]
    assert call["priority"] == "P1" and call["dedupe_minutes"] == 0
    assert call["producer"] == "market_regime_classifier"
    assert label in call["msg"] and "Market Regime Changed" in call["msg"]
    assert out["path"] == "p1_intent" and out["accepted"] is True and out.get("error") is None


def test_a_change_back_to_risk_on_keeps_the_p2_dispatcher_path(monkeypatch):
    p1, p2 = _stub_senders(monkeypatch)
    out = mrc._alert_regime_change("risk_off", _snap("risk_on_trend", vol="neutral"))
    assert p2 and not p1
    assert out["path"] == "dispatch_alert"


def test_an_alert_failure_is_surfaced_not_swallowed(monkeypatch):
    tg = types.ModuleType("telegram_alert")

    def boom(msg, **k):
        raise RuntimeError("transport down")

    tg.send_telegram = boom
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    out = mrc._alert_regime_change("risk_on_trend", _snap("risk_off"))
    assert out["accepted"] is False and "transport down" in (out.get("error") or "")
