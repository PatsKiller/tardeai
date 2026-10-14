"""READ-ONLY broker lock — behaviour tests (incident SPCX 2026-10-14).

Every test here is hermetic: broker clients, HTTP and db_adapter are STUBS that record calls (and a DB stub
that raises if touched where it must not be). No broker, no credential, no real database. The default for
this module is the production default — no unlock file → LOCKED (``pytestmark = trading_locked``); tests
that need an unlock write one into the per-test tmp UNLOCK_PATH the conftest fixture provides.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib import trading_lock as tl  # noqa: E402

pytestmark = pytest.mark.trading_locked

# C1 alarm-firing coverage (tests/test_alarm_coverage.py): the refusal alert in trading_lock._send_alert is
# observed reaching the Telegram transport in test_refusal_alert_reaches_the_transport below.
COVERS = ["scripts/lib/trading_lock.py"]


class _Recorder:
    """A callable that records invocations (a stub broker client method)."""

    def __init__(self, ret=None):
        self.calls = []
        self.ret = ret

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return self.ret


class _NoDB:
    """db_adapter._get_conn stub: any use before the lock is a test failure."""

    def __call__(self, *a, **k):
        raise AssertionError("database touched on a locked write path")


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(tl, "_ALERT_SENDER", sent.append)
    return sent


@pytest.fixture
def audit(tmp_path, monkeypatch):
    p = tmp_path / "audit.jsonl"
    monkeypatch.setenv("TRADEAI_TRADING_LOCK_AUDIT_PATH", str(p))
    return p


@pytest.fixture
def nodb(monkeypatch):
    import db_adapter

    monkeypatch.setattr(db_adapter, "_get_conn", _NoDB())


def _write_unlock(doc, *, mode=0o600):
    tl.UNLOCK_PATH.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    os.chmod(tl.UNLOCK_PATH, mode)


def _valid(hours=1.0, **kw):
    doc = {
        "unlocked_until": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).isoformat(),
        "reason": "operator test",
        "operator": "john",
        "brokers": ["schwab"],
    }
    doc.update(kw)
    return doc


def _intent(broker="schwab", account="schwab_taxable"):
    return types.SimpleNamespace(
        broker=broker,
        account_key=account,
        intent_id="iid-1",
        correlation_id="cid-1",
        meta=types.SimpleNamespace(signal_evidence={}, strategy_id=None),
    )


# ── lock state: fail secure ──────────────────────────────────────────────────────────────────────────
def test_default_without_unlock_file_is_locked(audit, alerts):
    assert not tl.UNLOCK_PATH.exists()
    assert tl.lock_state()["locked"] is True
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("cancel", broker="schwab", caller="t")


def test_valid_unlock_allows_only_listed_broker_and_actions(audit):
    _write_unlock(_valid(actions=["cancel"]))
    assert tl.assert_trading_unlocked("cancel", broker="schwab", caller="t")["locked"] is False
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("place", broker="schwab", caller="t")
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("cancel", broker="snaptrade", caller="t")


@pytest.mark.parametrize(
    "doc,why",
    [
        (_valid(hours=-0.1), "expired"),
        (_valid(hours=24 * 365 * 70), "2099-style standing unlock"),
        ({**_valid(), "unlocked_until": "2026-10-14T23:00:00"}, "naive timestamp"),
        ({k: v for k, v in _valid().items() if k != "reason"}, "no reason"),
        ({k: v for k, v in _valid().items() if k != "brokers"}, "no brokers"),
        ({**_valid(), "brokers": []}, "empty brokers"),
        ({**_valid(), "actions": ["place", "liquidate"]}, "unknown action"),
        ("{not json", "malformed json"),
        ("[1, 2]", "not an object"),
    ],
)
def test_malformed_or_expired_unlock_is_locked(doc, why, audit, alerts):
    _write_unlock(doc)
    assert tl.lock_state(broker="schwab", action="place")["locked"] is True, why
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("place", broker="schwab", caller="t")


def test_unreadable_unlock_file_is_locked(audit, alerts):
    _write_unlock(_valid(), mode=0o000)
    if os.access(tl.UNLOCK_PATH, os.R_OK):  # running as root: permissions do not bite
        pytest.skip("root can read mode 000")
    assert tl.lock_state()["locked"] is True


def test_group_writable_and_symlinked_unlock_are_locked(tmp_path, audit):
    _write_unlock(_valid(), mode=0o620)
    assert tl.lock_state()["locked"] is True
    real = tmp_path / "real.json"
    real.write_text(json.dumps(_valid()))
    os.chmod(real, 0o600)
    tl.UNLOCK_PATH.unlink()
    tl.UNLOCK_PATH.symlink_to(real)
    assert tl.lock_state()["locked"] is True


def test_directory_at_unlock_path_is_locked(audit):
    tl.UNLOCK_PATH.mkdir()
    assert tl.lock_state()["locked"] is True


def test_panic_file_beats_a_valid_unlock(audit):
    _write_unlock(_valid())
    assert tl.lock_state()["locked"] is False
    tl.PANIC_LOCK_PATH.write_text("{}")
    assert tl.lock_state()["locked"] is True


def test_no_environment_variable_moves_the_unlock_path():
    src = (ROOT / "scripts" / "lib" / "trading_lock.py").read_text()
    unlock_line = next(ln for ln in src.splitlines() if ln.startswith("UNLOCK_PATH"))
    assert "environ" not in unlock_line and "getenv" not in unlock_line
    # and nothing in scripts/ writes the unlock file
    for p in (ROOT / "scripts").rglob("*.py"):
        if "archive" in p.parts:
            continue
        t = p.read_text(errors="replace")
        assert "trading_unlock.json" not in t or p.name == "trading_lock.py", p


# ── audit + alert ────────────────────────────────────────────────────────────────────────────────────
def test_refusal_writes_audit_and_alerts_once_per_hour_per_caller(audit, alerts):
    for _ in range(3):
        with pytest.raises(tl.TradingLocked):
            tl.assert_trading_unlocked("place", broker="schwab", account="schwab_taxable", caller="A")
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("cancel", broker="schwab", caller="B")
    rows = [json.loads(x) for x in audit.read_text().splitlines()]
    assert len(rows) == 4 and all(r["event"] == "refused" for r in rows)
    assert {r["caller"] for r in rows} == {"A", "B"}
    assert len(alerts) == 2, alerts
    assert all(a.startswith("P0 URGENT TRADING LOCKED") for a in alerts)


def test_house_send_path_uses_explicit_never_digest_priority(monkeypatch, audit):
    calls = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda msg, **k: calls.append(k) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(tl, "_ALERT_SENDER", None)
    monkeypatch.setattr(tl, "_under_test", lambda: False)
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("place", broker="schwab", caller="house-path")
    assert calls and calls[0]["priority"] == "P1" and calls[0]["dedupe_minutes"] == 0
    assert calls[0]["producer"] == "trading_lock"


# ── paper vs live ────────────────────────────────────────────────────────────────────────────────────
def test_alpaca_paper_is_allowed_while_locked_and_live_is_not(audit, alerts):
    assert tl.alpaca_environment("https://paper-api.alpaca.markets") == "paper"
    assert tl.alpaca_environment("https://api.alpaca.markets") == "live"
    assert tl.alpaca_environment("https://paper-api.alpaca.markets.evil.example") == "live"
    assert tl.assert_trading_unlocked("place", broker="alpaca_paper")["paper"] is True
    assert tl.assert_trading_unlocked("cancel", broker="alpaca", environment="paper")["paper"] is True
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("place", broker="alpaca", environment="live")
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("place", broker="alpaca")  # environment unknown → live


def test_alpaca_paper_adapter_posts_on_paper_and_refuses_a_live_host(monkeypatch, audit, alerts):
    import requests
    from alpaca_paper_adapter import AlpacaPaperAdapter

    post = _Recorder(types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"id": "x"}))
    monkeypatch.setattr(requests, "post", post)
    paper = types.SimpleNamespace(base_url="https://paper-api.alpaca.markets", headers={})
    assert AlpacaPaperAdapter._api_post(paper, "/v2/orders", {"symbol": "SPY"}) == {"id": "x"}
    assert len(post.calls) == 1
    live = types.SimpleNamespace(base_url="https://api.alpaca.markets", headers={})
    with pytest.raises(tl.TradingLocked):
        AlpacaPaperAdapter._api_post(live, "/v2/orders", {"symbol": "SPY"})
    assert len(post.calls) == 1


def test_alpaca_factory_live_branch_is_locked(monkeypatch, audit, alerts):
    from brokers import alpaca_factory

    monkeypatch.setattr(alpaca_factory, "_row", lambda k: {"broker": "alpaca", "environment": "live"})
    with pytest.raises(tl.TradingLocked):
        alpaca_factory.adapter_for("alpaca_live_x")


# ── Schwab transport ─────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def transport(monkeypatch, nodb):
    import schwab_transport as st

    built = _Recorder((None, {"status": "stub"}))
    monkeypatch.setattr(st, "build_client", built)
    st._test_built = built
    return st


def test_transport_place_cancel_replace_refuse_before_any_io(transport, audit, alerts):
    st = transport
    with pytest.raises(tl.TradingLocked):
        st.place_order("schwab_taxable", {"orderType": "STOP"}, _intent())
    with pytest.raises(tl.TradingLocked):
        st.cancel_order("schwab_taxable", "123")
    with pytest.raises(tl.TradingLocked):
        st.cancel_order_for_replace("schwab_taxable", "123")
    with pytest.raises(tl.TradingLocked):
        st.replace_order()
    with pytest.raises(tl.TradingLocked):
        st._pilot_preconditions("schwab_taxable", "protective_stop", action="cancel")
    assert st._test_built.calls == []  # the broker client was never even built


def test_schwab_py_client_writes_are_guarded_and_reads_pass(audit, alerts):
    import schwab_transport as st

    client = types.SimpleNamespace(
        place_order=_Recorder(),
        cancel_order=_Recorder(),
        replace_order=_Recorder(),
        get_orders_for_account=_Recorder({"ok": 1}),
    )
    raw = {k: getattr(client, k) for k in ("place_order", "cancel_order", "replace_order")}
    st._lock_guard_client_writes(client, "schwab_taxable")
    for name in ("place_order", "cancel_order", "replace_order"):
        with pytest.raises(tl.TradingLocked):
            getattr(client, name)("hash", {})
        assert raw[name].calls == []
    assert client.get_orders_for_account("hash") == {"ok": 1}  # reads still work while locked


def test_transport_reads_still_work_while_locked(monkeypatch, audit):
    import schwab_transport as st

    monkeypatch.setattr(st, "_read", lambda *a, **k: {"status": "ok", "orders": []})
    assert st.get_orders("schwab_taxable", account_hash="h")["status"] == "ok"
    assert tl.is_trading_locked(broker="schwab") is True  # …and the lock is engaged while reading


def test_unlocked_transport_proceeds_to_its_own_gates(transport, monkeypatch, audit):
    """With a valid unlock the lock steps aside; the existing gates (here: the stubbed DB) take over."""
    _write_unlock(_valid())
    with pytest.raises(AssertionError, match="database touched"):
        transport.cancel_order("schwab_taxable", "123")


# ── pilots / router / approvals ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def no_transport(monkeypatch):
    import schwab_transport as st

    rec = _Recorder({"status": "submitted"})
    monkeypatch.setattr(st, "place_order", rec)
    monkeypatch.setattr(st, "cancel_order", rec)
    return rec


@pytest.mark.parametrize("modname", ["protective_stop_pilot", "options_order_pilot", "broker_entry_pilot"])
def test_pilot_submit_and_2fa_request_refuse(modname, no_transport, nodb, audit, alerts):
    mod = __import__(f"brokers.{modname}", fromlist=["submit"])
    with pytest.raises(tl.TradingLocked):
        mod.submit("schwab_taxable", {}, _intent())
    with pytest.raises(tl.TradingLocked):
        mod.request_2fa(_intent())
    assert no_transport.calls == []


def test_entry_pilot_confirm_and_route_return_refusal(no_transport, nodb, audit, alerts):
    from brokers import broker_entry_pilot as bep

    assert bep.confirm_and_submit("iid")["mode"] == "trading_locked"
    assert bep.request_route(1)["mode"] == "trading_locked"
    assert no_transport.calls == []


def test_router_and_approval_refuse_without_consuming_approval(monkeypatch, no_transport, nodb, audit, alerts):
    from brokers import approval_service, intent_submit_router as isr

    monkeypatch.setattr(approval_service, "_load_intent_any", lambda iid: _intent())
    consulted = _Recorder(True)
    monkeypatch.setattr(approval_service, "is_fully_approved", consulted)
    r = isr.submit_fully_approved("iid-1")
    assert r["ok"] is False and r["mode"] == "trading_locked" and r["broker_submitted"] is False
    assert consulted.calls == [] and no_transport.calls == []
    c = approval_service.confirm("iid-1", "telegram", "123456")  # DB is _NoDB → must not be reached
    assert c["ok"] is False and c["locked"] is True
    assert approval_service.request_approval(_intent())["mode"] == "trading_locked"
    assert isr.cancel_replace_stop_if_needed(_intent())["mode"] == "trading_locked"


def test_schwab_order_adapter_refuses_with_lock_first(audit, alerts):
    from brokers.schwab_order_adapter import SchwabOrderAdapter

    a = SchwabOrderAdapter()
    for call in (lambda: a.submit(_intent(), {}), lambda: a.replace(_intent(), "1"), lambda: a.cancel("1")):
        with pytest.raises(tl.TradingLocked):
            call()


def test_execution_guard_denies_every_write_action_including_cancel(monkeypatch, audit, alerts):
    from brokers import execution_guard as eg, audit as br_audit
    from brokers.order_intent import OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity

    monkeypatch.setattr(br_audit, "record_guard_decision", lambda *a, **k: None)
    it = OrderIntent(
        instrument=Instrument("SPCX"),
        direction=Direction.LONG,
        entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=1.0),
        quantity=Quantity(qty=1),
        broker="schwab",
        account_key="schwab_taxable",
    )
    for action in ("submit", "replace", "cancel"):
        d = eg.authorize(it, action)
        assert d.allowed is False and d.reason.startswith("TRADING_LOCKED"), (action, d.reason)


def test_lock_wins_over_a_standing_2099_arm(monkeypatch, audit):
    """Pilot disarm in code: env flag + DB standing unlock + 2099 session + approvals all 'armed' → still False."""
    from brokers import execution_guard as eg
    import db_adapter

    class _Cur:
        def execute(self, *a, **k):
            self.q = a[0]

        def fetchone(self):
            if "count(*)" in self.q:
                return (5,)
            if "pilot_armed_until" in self.q:
                return ("2099-12-31T23:59:59+00:00",)
            return ("true",)

    monkeypatch.setattr(db_adapter, "_get_conn", lambda: types.SimpleNamespace(cursor=_Cur))
    monkeypatch.setenv("BROKER_LIVE_ENABLED", "true")
    assert eg._live_future_unlocked() is False
    assert eg._protective_unlocked() is False
    assert eg._options_unlocked() is False
    assert eg._fidelity_monitored_unlocked() is False
    _write_unlock(_valid())
    assert eg._live_future_unlocked() is True  # same arm rows, lock lifted → the arm is honoured again


def test_kill_switch_reports_the_lock(monkeypatch, audit):
    from brokers import kill_switches as ks

    monkeypatch.setattr(ks, "list_active", _NoDB())
    blocked, reasons = ks.is_blocked(live_submit=True)
    assert blocked and reasons[0].startswith("trading_lock:locked")


def test_pilot_arm_refused_and_status_reports_lock(monkeypatch, nodb, audit, alerts):
    import schwab_pilot_arm as arm
    import datetime as _d

    r = arm.arm(f"ARM SCHWAB PILOT {_d.date.today().isoformat()}")
    assert r["ok"] is False and r["mode"] == "trading_locked"


# ── SnapTrade / tastytrade / moomoo ──────────────────────────────────────────────────────────────────
def test_snaptrade_paths_refuse(monkeypatch, audit, alerts):
    from brokers import snaptrade_trade as stt, snaptrade_transport as sttr
    from brokers import snaptrade_protective_stop_pilot as spsp, snaptrade_trade_pilot as stp

    client = _Recorder()
    monkeypatch.setattr(stt, "_client", client)
    with pytest.raises(tl.TradingLocked):
        stt.place(trade_id="t", confirmed=True)
    with pytest.raises(tl.TradingLocked):
        stt.cancel(account_id="a", brokerage_order_id="o")
    with pytest.raises(tl.TradingLocked):
        sttr.place_order("fidelity_rollover", {}, _intent("snaptrade"))
    with pytest.raises(tl.TradingLocked):
        spsp.route_after_2fa("fidelity_rollover", _intent("snaptrade"))
    assert stp.execute("iid")["mode"] == "trading_locked"
    assert stp.preflight(account_key="fidelity_x", symbol="SPY")["mode"] == "trading_locked"
    assert client.calls == []


def test_tastytrade_http_helpers_refuse_and_never_post(monkeypatch, audit, alerts):
    import requests
    from tastytrade_adapter import TastytradeAdapter

    post, delete = _Recorder(), _Recorder()
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "delete", delete)
    fake = types.SimpleNamespace(
        session_token="tok",
        base_url="https://api.example",
        _headers=lambda: {},
        enabled=True,
        account_number="0",
        dry_run=False,
    )
    with pytest.raises(tl.TradingLocked):
        TastytradeAdapter._api_post(fake, "/accounts/0/orders", {})
    with pytest.raises(tl.TradingLocked):
        TastytradeAdapter._api_delete(fake, "/accounts/0/orders/1")
    with pytest.raises(tl.TradingLocked):
        TastytradeAdapter.cancel_order(fake, "1")
    assert TastytradeAdapter.submit_entry(fake, "SPY", 1, 1, 1, 1, "s", None)["status"] == "trading_locked"
    assert post.calls == [] and delete.calls == []


def test_schwab_adapter_dead_paths_are_locked_too(audit, alerts):
    from schwab_adapter import SchwabAdapter

    fake = types.SimpleNamespace(account_label="schwab_taxable")
    with pytest.raises(tl.TradingLocked):
        SchwabAdapter._api_post(fake, "/trader/v1/accounts/h/orders", {})
    with pytest.raises(tl.TradingLocked):
        SchwabAdapter.cancel_order(fake, "1")
    assert SchwabAdapter.submit_entry(fake, "SPY", 1, 1, 1, 1, "s", None)["status"] == "trading_locked"


def test_moomoo_place_and_unlock_refuse(audit, alerts):
    from moomoo.client import MoomooClient

    with pytest.raises(tl.TradingLocked):
        MoomooClient.place_order(object())
    with pytest.raises(tl.TradingLocked):
        MoomooClient.unlock_trade(object())


# ── cron/daemon order steps ──────────────────────────────────────────────────────────────────────────
def test_synthetic_stop_breach_while_locked_alerts_and_requests_nothing(monkeypatch, audit, alerts):
    import synthetic_stop_monitor as ssm
    from brokers import protective_stop_pilot as psp

    class _C:
        def cursor(self):
            return self

        def execute(self, *a, **k):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(ssm, "ensure_table", lambda: None)
    monkeypatch.setattr(
        ssm,
        "list_stops",
        lambda status: [{"id": 1, "symbol": "SPCX", "account": "schwab_taxable", "stop_price": 150.0, "qty": 10}],
    )
    monkeypatch.setattr(ssm, "_live_price", lambda s, a: 149.0)
    monkeypatch.setattr(ssm, "_conn", lambda: _C())
    req = _Recorder({"ok": True})
    monkeypatch.setattr(psp, "request_2fa", req)
    saved = []
    fake_aew = types.ModuleType("alert_event_writer")
    fake_aew.save_alert_event = lambda **k: saved.append(k)
    monkeypatch.setitem(sys.modules, "alert_event_writer", fake_aew)
    out = ssm.check_and_trigger(dry_run=False)
    assert out[0]["status"] == "breach_trading_locked"
    assert req.calls == []
    assert saved and saved[0]["severity"] == "critical" and "TRADING LOCKED" in saved[0]["raw_text"]


def test_broker_trade_monitor_stop_modify_refuses(monkeypatch, audit, alerts):
    import schwab_broker_trade_monitor as m
    from brokers import protective_stop_pilot as psp

    req = _Recorder({"ok": True})
    monkeypatch.setattr(psp, "request_2fa", req)
    r = m._request_stop_modify("schwab_taxable", "SPCX", 10, 140.0, "1", 140.0, 150.0, 10)
    assert r["mode"] == "trading_locked" and req.calls == []


# ── C1 firing test: the refusal alert reaches the transport ─────────────────────────────────────────
def test_refusal_alert_reaches_the_transport(alarm_capture, monkeypatch, audit):
    """Inject the condition (no unlock → a Schwab place is refused) through the REAL house send path
    (telegram_alert.send_telegram, comms editor included); alarm_capture stubs only the wire."""
    monkeypatch.setattr(tl, "_ALERT_SENDER", None)
    monkeypatch.setattr(tl, "_under_test", lambda: False)
    with pytest.raises(tl.TradingLocked):
        tl.assert_trading_unlocked("place", broker="schwab", account="schwab_taxable", caller="c1-firing")
    alarm_capture.assert_fired(contains="TRADING LOCKED")
    assert "c1-firing" in alarm_capture.text()


# ── standalone CI harness hook ───────────────────────────────────────────────────────────────────────
def test_harness_hook_scratch_unlock_grants_then_restores(audit):
    prod_unlock, prod_panic = tl.UNLOCK_PATH, tl.PANIC_LOCK_PATH
    with tl.harness_scratch_lock(unlock_brokers=["schwab"]) as h:
        assert tl.UNLOCK_PATH.parent == h["dir"] and tl.UNLOCK_PATH != prod_unlock
        assert tl.assert_trading_unlocked("place", broker="schwab", caller="h")["locked"] is False
        with pytest.raises(tl.TradingLocked):
            tl.assert_trading_unlocked("place", broker="snaptrade", caller="h")
        scratch = h["dir"]
    assert (tl.UNLOCK_PATH, tl.PANIC_LOCK_PATH) == (prod_unlock, prod_panic)
    assert tl._AUDIT_PATH is None and not scratch.exists()


def test_harness_hook_without_unlock_is_locked_and_captures_alert(audit):
    with tl.harness_scratch_lock(unlock_brokers=None) as h:
        assert not tl.UNLOCK_PATH.exists()
        with pytest.raises(tl.TradingLocked):
            tl.assert_trading_unlocked("cancel", broker="schwab", caller="h-locked")
        assert h["alerts"] and h["alerts"][0].startswith("P0 URGENT TRADING LOCKED")
        assert (h["dir"] / "trading_lock_audit.jsonl").exists()
    assert not audit.exists()  # the harness audit went to its scratch dir, not the ambient ledger


def test_harness_hook_refused_outside_a_registered_harness(monkeypatch):
    monkeypatch.delitem(sys.modules, "pytest")
    fake_main = types.ModuleType("__main__")
    fake_main.__file__ = str(ROOT / "scripts" / "api_v2.py")
    monkeypatch.setitem(sys.modules, "__main__", fake_main)
    with pytest.raises(RuntimeError, match="not a registered test/CI harness"):
        with tl.harness_scratch_lock(unlock_brokers=["schwab"]):
            pass
    fake_main.__file__ = str(ROOT / "scripts" / "validate_schwab_write_policy.py")
    assert tl._registered_harness() == "scripts/validate_schwab_write_policy.py"
