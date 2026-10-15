"""ZETA 2026-10-15: a resting Schwab stop filled with NO near-trigger warning while Schwab was blind.

Since 2026-10-14 (config/schwab_access_mode.yaml mode=forbidden) the live stop read is UNAVAILABLE, the scan held
zero Schwab stops, and stop_health could only page "DEGRADED". Now, while blind, it warns from the LAST-KNOWN stop
levels priced on the non-Schwab canonical mark: NEAR_TRIGGER and TRIGGERED-LIKELY go out as immediate P1, never
digested, deduped; the DEGRADED page goes out at most once per ET day and names the unverifiable symbols.
Hermetic: no database, no broker, no holdings.json; Telegram captured at the transport.
"""
from __future__ import annotations

import json
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import stop_health_check as shc  # noqa: E402
import telegram_alert_router as R  # noqa: E402
from lib import last_known_stops as lks  # noqa: E402

COVERS = ["scripts/stop_health_check.py", "scripts/lib/last_known_stops.py"]

NOW = datetime(2026, 10, 15, 13, 40, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 10, 14, 18, 30, tzinfo=timezone.utc)


def _stop(sym="ZETA", sp=32.80, oid="1008253772223", acct="schwab_rollover_ira", **kw):
    return {"broker": "schwab", "account": acct, "symbol": sym, "order_id": oid, "order_type": "STOP",
            "stop_price": sp, "qty": 500.0, "captured_at": CAPTURED, "source": "alert_events", **kw}


def _quote(px, shares=500.0):
    return {"shares": shares, "price": px, "price_source": "finviz_elite", "price_at": "2026-10-15T13:30:21+00:00"}


def _blind_res(paused=True, failed=None):
    return {"generated_at": NOW.isoformat(), "stops": [], "alerts": [], "schwab_stops_status": "UNAVAILABLE",
            "summary": {"total": 0, "by_health": {"ok": 0, "warn": 0, "alert": 0},
                        "schwab_stops": {"status": "UNAVAILABLE", "reason": "schwab_paused: deactivated",
                                         "failed_accounts": failed or [], "paused": paused}}}


def _wire(monkeypatch, stops, quotes, *, sent=None, already=lambda *a, **k: False, siem=None):
    monkeypatch.setattr(lks, "load_config", lambda path=None: dict(lks.DEFAULTS))
    monkeypatch.setattr(lks, "load_last_known", lambda **k: list(stops))
    monkeypatch.setattr(lks, "holdings_quotes", lambda path=None: dict(quotes))
    monkeypatch.setattr(shc, "_alerted_since", already)
    monkeypatch.setattr(shc, "_recently_alerted", lambda *a, **k: False)
    monkeypatch.setattr(shc, "_siem", (lambda s, sev, t, p: siem.append((s, sev, t, p)) or 1) if siem is not None
                        else (lambda *a, **k: None))
    monkeypatch.setattr(shc, "_attach_telegram_id", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_portfolio_drawdown_guard", lambda: None)
    monkeypatch.setattr(shc, "_log_health_event", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_recover_current_scan", lambda res, t: {"ok": True})
    if sent is not None:
        monkeypatch.setattr(shc, "_send_telegram", lambda m, **k: sent.append((m, k)) or "77")


def _run(monkeypatch, res=None):
    res = res or _blind_res()
    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor", types.SimpleNamespace(scan=lambda persist=True: res))
    return shc.run(quiet=True)


# ── pure evaluation ─────────────────────────────────────────────────────────

def test_evaluate_near_triggered_and_far():
    stops = [_stop(sp=32.80), _stop(sym="DT", sp=63.85, oid="2"), _stop(sym="NFLX", sp=60.0, oid="3")]
    quotes = {("schwab_rollover_ira", "ZETA"): _quote(31.37), ("schwab_rollover_ira", "DT"): _quote(64.50, 100),
              ("schwab_rollover_ira", "NFLX"): _quote(71.63, 400)}
    out = {f["symbol"]: f for f in lks.evaluate(stops, quotes, near_pct=2.0)}
    assert out["ZETA"]["condition"] == lks.TRIGGERED_LIKELY and out["ZETA"]["proximity_pct"] < 0
    assert out["DT"]["condition"] == lks.NEAR_TRIGGER and 0 < out["DT"]["proximity_pct"] <= 2.0
    assert "NFLX" not in out


def test_evaluate_skips_unheld_and_translates_the_roth_label():
    stops = [_stop(sym="V", sp=390.0, acct="schwab_roth_ira"), _stop(sym="GONE", sp=10.0, oid="9")]
    quotes = {("schwab_roth", "V"): _quote(391.0, 1), ("schwab_rollover_ira", "GONE"): _quote(9.0, 0)}
    out = lks.evaluate(stops, quotes, near_pct=2.0, label=lambda a: {"schwab_roth_ira": "schwab_roth"}.get(a, a))
    assert [f["symbol"] for f in out] == ["V"]


def test_merge_newest_wins_and_dead_orders_drop():
    t0 = CAPTURED
    alert_rows = [
        _stop(sp=33.0, captured_at=t0 - timedelta(hours=3)),
        _stop(sp=32.8, captured_at=t0),                                       # newest observation wins
        _stop(sym="SPCX", oid="F", sp=151.5, captured_at=t0, last_condition="TRIGGERED"),   # already fired
        _stop(sym="OLD", oid="O", acct="schwab_taxable", sp=5.0, captured_at=t0 - timedelta(days=2)),
    ]
    snapshot = [{"broker": "schwab", "account": "schwab_taxable", "symbol": "X", "order_id": "X1",
                 "stop_price": 9.0, "status": "not_in_read", "captured_at": t0 - timedelta(days=1),
                 "source": "stop_last_known"}]
    out = lks.merge_sources(snapshot, alert_rows)
    assert [(r["symbol"], r["stop_price"]) for r in out] == [("ZETA", 32.8)]


def test_record_snapshot_marks_superseded_rows_never_deletes():
    calls = []

    class _Cur:
        def execute(self, sql, params=None):
            calls.append(sql)

    conn = types.SimpleNamespace(cursor=lambda: _Cur(), commit=lambda: None, rollback=lambda: None)
    n = lks.record_snapshot([{"broker": "schwab", "account": "a", "symbol": "z", "order_id": "1",
                              "stop_price": 1.0}], complete=True, conn=conn)
    assert n == 1
    assert not any("DELETE" in c.upper() for c in calls)
    assert any("not_in_read" in c for c in calls) and any("INSERT INTO stop_last_known" in c for c in calls)


def test_record_snapshot_never_raises():
    conn = types.SimpleNamespace(cursor=lambda: (_ for _ in ()).throw(RuntimeError("db down")),
                                 rollback=lambda: None)
    assert lks.record_snapshot([{"account": "a", "order_id": "1"}], complete=True, conn=conn) == 0


# ── stop_health while blind ─────────────────────────────────────────────────

def test_blind_near_trigger_pages_p1_with_the_last_known_label(monkeypatch):
    sent, siem = [], []
    _wire(monkeypatch, [_stop(sym="DT", sp=63.85, oid="1008253772551", qty=100.0)],
          {("schwab_rollover_ira", "DT"): _quote(64.50, 100)}, sent=sent, siem=siem)
    out = _run(monkeypatch)
    stop_msgs = [(m, k) for m, k in sent if "LAST-KNOWN" in m]
    assert len(stop_msgs) == 1
    msg, kw = stop_msgs[0]
    assert kw.get("priority") == "P1"
    assert "NEAR_TRIGGER" in msg and "*DT*" in msg and "$63.85" in msg
    assert "based on last-known stop levels captured 2026-10-14 14:30 ET; Schwab not monitored — verify at Schwab" in msg
    assert "DT:NEAR_TRIGGER:last_known" in out["telegram_fired"]
    assert siem[0][3]["condition_key"] == "lkstop:v1:NEAR_TRIGGER:schwab_rollover_ira:1008253772551"
    assert siem[0][3]["basis"] == "last_known_stop"


def test_blind_price_through_stop_pages_triggered_likely(monkeypatch):
    sent = []
    _wire(monkeypatch, [_stop()], {("schwab_rollover_ira", "ZETA"): _quote(31.37)}, sent=sent)
    out = _run(monkeypatch)
    msg, kw = next((m, k) for m, k in sent if "LAST-KNOWN" in m)
    assert kw.get("priority") == "P1"
    assert "TRIGGERED-LIKELY" in msg and "*ZETA*" in msg and "$32.80" in msg and "verify at Schwab" in msg
    assert "ZETA:TRIGGERED_LIKELY:last_known" in out["telegram_fired"]


def test_last_known_messages_are_never_digested():
    for msg in ("🚨 STOP HEALTH — LAST-KNOWN STOPS (TRIGGERED-LIKELY): 1 alert(s) — Schwab is NOT monitored\n\n"
                "🚨 TRIGGERED-LIKELY: *ZETA* (schwab_rollover_ira) — price $31.37 is AT/BELOW last-known stop $32.80",
                "🚨 STOP HEALTH — LAST-KNOWN STOPS (NEAR_TRIGGER): 1 alert(s)\n\n⚠️ NEAR_TRIGGER: *DT* — about to fire."):
        assert R.classify_alert(msg) == "P0_INTERRUPT"
        assert R.classify_alert(msg) != "P1_DIGEST"


def test_flood_policy_protects_the_page():
    policy = json.loads((ROOT / "config" / "incident_flood_policy.json").read_text())
    pat = re.compile(policy["protected"]["pattern"], re.I)
    assert pat.search("stop_health LAST-KNOWN STOPS TRIGGERED-LIKELY ZETA")


def test_blind_alert_reaches_the_transport_through_the_real_router(alarm_capture, monkeypatch):
    _wire(monkeypatch, [_stop()], {("schwab_rollover_ira", "ZETA"): _quote(31.37)})
    _run(monkeypatch)
    alarm_capture.assert_fired(contains="TRIGGERED-LIKELY")


def test_dedupe_suppresses_a_repeat_but_not_an_escalation(monkeypatch):
    sent = []
    seen = {"lkstop:v1:NEAR_TRIGGER:schwab_rollover_ira:1008253772223"}
    _wire(monkeypatch, [_stop()], {("schwab_rollover_ira", "ZETA"): _quote(33.10)}, sent=sent,
          already=lambda sym, since, condition_key=None, needle=None: condition_key in seen or bool(needle))
    _run(monkeypatch)
    assert not [m for m, _ in sent if "LAST-KNOWN" in m]          # NEAR already paged inside the window
    _wire(monkeypatch, [_stop()], {("schwab_rollover_ira", "ZETA"): _quote(32.50)}, sent=sent,
          already=lambda sym, since, condition_key=None, needle=None: condition_key in seen or bool(needle))
    _run(monkeypatch)
    assert any("TRIGGERED-LIKELY" in m for m, _ in sent)           # crossing the stop is a new condition


def test_triggered_likely_dedupes_from_the_et_day_start(monkeypatch):
    windows = []
    _wire(monkeypatch, [_stop()], {("schwab_rollover_ira", "ZETA"): _quote(31.37)}, sent=[],
          already=lambda sym, since, condition_key=None, needle=None: windows.append((condition_key, since)) or False)
    shc._last_known_blind_alerts(_blind_res(), now=NOW)
    (_, since), = [w for w in windows if w[0]]
    assert since == shc._et_day_start(NOW) and since.hour == 0


def test_only_the_blind_accounts_are_loaded(monkeypatch):
    got = {}
    _wire(monkeypatch, [], {}, sent=[])
    monkeypatch.setattr(lks, "load_last_known", lambda **k: got.update(k) or [])
    shc._last_known_blind_alerts(_blind_res(paused=False, failed=["schwab_taxable"]), now=NOW)
    assert got["accounts"] == ["schwab_taxable"]
    shc._last_known_blind_alerts(_blind_res(paused=True), now=NOW)
    assert got["accounts"] is None


def test_a_clean_scan_does_not_use_last_known(monkeypatch):
    sent = []
    _wire(monkeypatch, [_stop()], {("schwab_rollover_ira", "ZETA"): _quote(31.37)}, sent=sent)
    res = _blind_res()
    res["schwab_stops_status"] = "ok"
    res["summary"]["schwab_stops"] = {"status": "ok"}
    out = _run(monkeypatch, res)
    assert sent == [] and out["ok"] is True


# ── DEGRADED page: once per ET day, names what cannot be verified ───────────

def test_degraded_page_lists_unverifiable_symbols_once_per_day(monkeypatch):
    sent = []
    quotes = {("schwab_rollover_ira", "ZETA"): _quote(40.0), ("schwab_taxable", "BAH"): _quote(70.0, 9),
              ("schwab_taxable", "CASH"): _quote(1.0, 100), ("fidelity_rollover_ira", "ANET"): _quote(1.0, 5)}
    _wire(monkeypatch, [_stop()], quotes, sent=sent)
    out = _run(monkeypatch)
    msg, kw = next((m, k) for m, k in sent if "DEGRADED" in m)
    assert kw.get("priority") == "P1"
    assert "Stops NOT verifiable (2): BAH@schwab_taxable, ZETA@schwab_rollover_ira" in msg
    assert "Still warning from 1 last-known stop level(s) on: ZETA@schwab_rollover_ira" in msg
    assert out["status"] == "DEGRADED"
    # Same ET day: the DEGRADED page is not repeated.
    sent.clear()
    _wire(monkeypatch, [_stop()], quotes, sent=sent,
          already=lambda sym, since, condition_key=None, needle=None: needle == shc.SCHWAB_UNAVAILABLE_CONDITION)
    out = _run(monkeypatch)
    assert not [m for m, _ in sent if "DEGRADED" in m]
    assert out["summary"]["degraded"]["deduped"] is True


def test_operator_entry_supersedes_older_observations_of_that_position():
    t0 = CAPTURED
    alerts = [_stop(sp=33.51, oid="A", captured_at=t0), _stop(sym="DT", sp=63.85, oid="D", captured_at=t0)]
    op_new = {"broker": "schwab", "account": "schwab_rollover_ira", "symbol": "ZETA", "order_id": "operator-ZETA",
              "stop_price": 29.0, "status": "open", "origin": "operator", "captured_at": t0 + timedelta(hours=20),
              "source": "stop_last_known:operator"}
    out = lks.merge_sources([op_new], alerts)
    assert sorted((r["symbol"], r["stop_price"]) for r in out) == [("DT", 63.85), ("ZETA", 29.0)]
    # Retiring (status filled, no level) removes the position's stops entirely; DT's alert-era level is untouched.
    op_ret = {**op_new, "stop_price": None, "status": "filled"}
    out = lks.merge_sources([op_ret], alerts)
    assert [r["symbol"] for r in out] == ["DT"]


def test_record_operator_stop_writes_locally_only():
    calls = []

    class _Cur:
        def execute(self, sql, params=None):
            calls.append((sql, params))

    conn = types.SimpleNamespace(cursor=lambda: _Cur(), commit=lambda: None)
    row = lks.record_operator_stop(account="schwab_rollover_ira", symbol="nflx", stop_price=69.14, qty=400, conn=conn)
    assert row["symbol"] == "NFLX" and row["origin"] == "operator" and row["order_id"] == "operator-NFLX-schwab_rollover_ira"
    assert any("INSERT INTO stop_last_known" in sql for sql, _ in calls)
    import pytest
    with pytest.raises(ValueError):
        lks.record_operator_stop(account="a", symbol="X", stop_price=None, conn=conn)


def test_operator_cli_defaults_to_dry_run(monkeypatch, capsys):
    import record_last_known_stop as cli
    monkeypatch.setattr(lks, "record_operator_stop", lambda **k: (_ for _ in ()).throw(AssertionError("wrote")))
    assert cli.main(["--account", "schwab_rollover_ira", "--symbol", "NFLX", "--stop", "69.14"]) == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_degraded_page_says_when_no_warning_is_possible(monkeypatch):
    sent = []
    _wire(monkeypatch, [], {}, sent=sent)
    _run(monkeypatch)
    msg = next(m for m, _ in sent if "DEGRADED" in m)
    assert "NO stop warnings are possible" in msg
