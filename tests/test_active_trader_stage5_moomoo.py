"""Stage 5 tests — pure (governors, features, queues, envelope, AST guard,
credential wrapper allowlist, replay round-trip). No live broker, no trade API.
"""
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from active_trader.moomoo import ast_guard, features as F, secret_render  # noqa: E402
from active_trader.moomoo.governor import (  # noqa: E402
    Budget, Governor, GovernorSet, MODIFY_CANCEL, PLACE, RateRefused, SNAPSHOT,
)
from active_trader.moomoo.envelope import (  # noqa: E402
    BoundedStreamQueue, EventEnvelope, QueuePolicy, StreamType,
)
from active_trader.moomoo.gateway import (  # noqa: E402
    Priority, SubState, SubscriptionOwner,
)
from active_trader.moomoo.secret_render import CredentialGateError


# ---------------- AST trade-API prohibition
def test_no_trade_context_or_method_reachable():
    findings = ast_guard.scan_directory()
    assert findings == [], f"trade-API references found: {findings}"


def test_ast_guard_catches_injected_trade_call():
    bad = "from moomoo import OpenSecTradeContext\nctx=OpenSecTradeContext()\nctx.place_order()\n"
    hits = ast_guard.scan_source(bad, "bad.py")
    tokens = {h["token"] for h in hits}
    assert "OpenSecTradeContext" in tokens and "place_order" in tokens
    assert ast_guard.scan_source("x = TrdEnv.REAL", "b.py")[0]["token"] == "TrdEnv.REAL"


# ---------------- rate governors
def test_governor_budget_values():
    assert (PLACE.ceiling, PLACE.ordinary, PLACE.reserve) == (15, 12, 3)
    assert (MODIFY_CANCEL.ceiling, MODIFY_CANCEL.ordinary, MODIFY_CANCEL.reserve) == (20, 16, 4)
    assert (SNAPSHOT.ceiling, SNAPSHOT.ordinary, SNAPSHOT.reserve) == (60, 48, 12)
    with pytest.raises(ValueError):
        Budget("X", 15, 13, 3)          # ordinary+reserve != ceiling


def test_governor_ordinary_cannot_borrow_reserve():
    clk = [1000.0]
    g = Governor(PLACE, "moomoo/acct", clock=lambda: clk[0], conservative_start=False)
    for _ in range(12):
        g.acquire()
    with pytest.raises(RateRefused, match="reserve is protection-only"):
        g.acquire()
    for _ in range(3):
        g.acquire(reserve=True)         # protection may use reserve
    with pytest.raises(RateRefused, match="ceiling"):
        g.acquire(reserve=True)         # ceiling absolute


def test_governor_sliding_window_release():
    clk = [1000.0]
    g = Governor(PLACE, "a", clock=lambda: clk[0], conservative_start=False)
    for _ in range(15):
        g.acquire(reserve=True)
    with pytest.raises(RateRefused):
        g.acquire(reserve=True)
    clk[0] += 31                        # window ages out
    g.acquire()
    assert g.state()["used_total"] == 1


def test_governor_conservative_restart_assumes_full_ordinary():
    g = Governor(PLACE, "a", clock=lambda: 5.0)     # conservative_start default True
    assert g.state()["used_ordinary"] == 12
    with pytest.raises(RateRefused):
        g.acquire()                     # ordinary already "full" on restart


def test_snapshot_batching_not_polling():
    gs = GovernorSet("a", conservative_start=False)
    batches = gs.snapshot_batch([f"US.S{i}" for i in range(250)], batch_size=100)
    assert [len(b) for b in batches] == [100, 100, 50]


def test_governor_thread_safety():
    import threading
    g = Governor(SNAPSHOT, "a", conservative_start=False)
    ok = []
    def worker():
        try:
            g.acquire(); ok.append(1)
        except RateRefused:
            pass
    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sum(ok) == 48                # ordinary budget (48) admits; reserve is protection-only


# ---------------- features
def test_feature_formulas_and_nulls():
    assert F.midprice(10.0, 10.10) == pytest.approx(10.05)
    assert F.spread_cents(10.0, 10.10) == pytest.approx(10.0)
    assert F.spread_bps(10.0, 10.10) == pytest.approx(99.5, abs=0.5)  # 0.10/10.05*1e4
    assert F.microprice(10.0, 10.10, 100, 300) == pytest.approx(10.025)
    assert F.top_imbalance(300, 100) == pytest.approx(0.5)
    assert F.midprice(None, 10.0) is None
    assert F.spread_bps(0, 0) is None
    assert F.microprice(10, 10.1, 0, 0) is None


def test_feature_snapshot_deterministic_replay_equality():
    kw = dict(symbol="US.AAPL", as_of_ns=123456789, last=200.0, bid=199.9, ask=200.1,
              bid_size=500, ask_size=300, vwap=199.95, session_high=201.0, session_low=198.0,
              last_event_ns=123000000)
    a = F.compute_snapshot(**kw).as_dict()
    b = F.compute_snapshot(**kw).as_dict()
    assert a == b and a["feature_version"] == F.FEATURE_VERSION
    assert a["data_age_ms"] == pytest.approx(0.457, abs=0.001)


def test_no_lookahead_null_when_absent():
    s = F.compute_snapshot(symbol="X", as_of_ns=1, gap_state="STALE").as_dict()
    assert s["microprice"] is None and s["spread_bps"] is None and s["gap_state"] == "STALE"


# ---------------- queues
def test_quote_coalescing():
    q = BoundedStreamQueue(QueuePolicy.COALESCE)
    for i in range(5):
        q.put(_env("US.AAPL", StreamType.QUOTE, {"last": i}))
    out = q.drain()
    assert len(out) == 1 and out[0].payload["last"] == 4 and q.metrics.coalesced == 4


def test_order_book_ring_gap_marker():
    q = BoundedStreamQueue(QueuePolicy.RING_GAP, capacity=3)
    for i in range(5):
        q.put(_env("US.AAPL", StreamType.ORDER_BOOK, {"i": i}))
    out = q.drain()
    assert any(isinstance(x, dict) and x.get("marker") == "SEQUENCE_GAP" for x in out)
    assert q.metrics.gap_markers >= 1 and q.metrics.dropped >= 1


def test_ticker_overflow_marker_and_control_never_drops():
    q = BoundedStreamQueue(QueuePolicy.APPEND_OVERFLOW, capacity=2)
    for i in range(4):
        q.put(_env("US.AAPL", StreamType.TICKER, {"i": i}))
    assert q.metrics.overflow_markers >= 1
    c = BoundedStreamQueue(QueuePolicy.CONTROL, capacity=1)
    for i in range(10):
        c.put(_env("US.AAPL", StreamType.CONTROL, {"i": i}))
    assert c.metrics.dropped == 0 and c.depth() == 10


# ---------------- subscription owner
class FakeCtx:
    def __init__(self, fail_right_for=()):
        self.subscribed = []
        self.fail_right_for = set(fail_right_for)
        # only market-data methods exist — no trade method to call
    def subscribe(self, syms, streams):
        if any(s in self.fail_right_for for s in syms):
            return False, "the quote right is occupied by another terminal"
        self.subscribed.append((tuple(syms), tuple(streams)))
        return True, "ok"
    def unsubscribe(self, syms, streams):
        return True, "ok"


def test_single_owner_subscribe_order_and_states():
    owner = SubscriptionOwner(quote_ctx=FakeCtx())
    owner.record_quota(total=100, used=0)
    for st in (StreamType.QUOTE, StreamType.K_1M, StreamType.ORDER_BOOK, StreamType.TICKER):
        sub = owner.subscribe("US.AAPL", st, Priority.P0)
        assert sub.state is SubState.ACTIVE
    assert owner.quota["used"] == 4


def test_missing_entitlement_preserves_lower_tiers():
    owner = SubscriptionOwner(quote_ctx=FakeCtx())
    owner.record_quota(100, 0)
    q = owner.subscribe("US.AAPL", StreamType.QUOTE, Priority.P0, entitled=True)
    ob = owner.subscribe("US.AAPL", StreamType.ORDER_BOOK, Priority.P0, entitled=False)
    assert q.state is SubState.ACTIVE and ob.state is SubState.ENTITLEMENT_MISSING


def test_quote_right_conflict_never_auto_grabs():
    owner = SubscriptionOwner(quote_ctx=FakeCtx(fail_right_for={"US.AAPL"}))
    owner.record_quota(100, 0)
    sub = owner.subscribe("US.AAPL", StreamType.QUOTE, Priority.P0)
    assert sub.state is SubState.QUOTE_RIGHT_CONFLICT and "auto-grab" in sub.reason


def test_quota_deferred_when_exhausted():
    owner = SubscriptionOwner(quote_ctx=FakeCtx())
    owner.record_quota(total=1, used=1)
    sub = owner.subscribe("US.AAPL", StreamType.QUOTE, Priority.P0)
    assert sub.state is SubState.QUOTA_DEFERRED


def test_first_push_not_fresh_and_reconnect_epoch():
    owner = SubscriptionOwner(quote_ctx=FakeCtx())
    e1 = owner.on_push("US.AAPL", StreamType.QUOTE, {"last": 1})
    assert e1.is_first_push and e1.is_cached and owner.fresh_signal_eligible(e1) is False
    e2 = owner.on_push("US.AAPL", StreamType.QUOTE, {"last": 2}, is_cached=False)
    assert not e2.is_first_push and owner.fresh_signal_eligible(e2) is True
    owner.reconnect()
    assert owner.status()["reconnect_epoch"] == 1
    e3 = owner.on_push("US.AAPL", StreamType.QUOTE, {"last": 3})
    assert e3.is_first_push and e3.reconnect_epoch == 1


def test_provider_sequence_null_not_invented():
    owner = SubscriptionOwner(quote_ctx=FakeCtx())
    e = owner.on_push("US.AAPL", StreamType.TICKER, {"x": 1}, provider_seq=None)
    assert e.provider_sequence is None


# ---------------- credential wrapper allowlist (mocked bws — no network)
PID = "aaaaaaaa-bbbb-cccc-dddd-00000000375f2c"      # ends with pinned suffix 00375f2c


def _bws_factory(projects, secrets):
    import json
    def call(args):
        if args[:2] == ["project", "list"]:
            return json.dumps(projects)
        if args[0] == "secret" and args[1] == "list":
            return json.dumps(secrets)
        raise AssertionError(f"unexpected bws call {args}")
    return call


def _tokenfile(tmp_path):
    f = tmp_path / "tok"
    f.write_text("fake-token")
    f.chmod(0o600)
    return f


def test_wrapper_happy_path(tmp_path):
    projects = [{"name": "trade-ai-lab", "id": "lab-id"},
                {"name": "trade-ai-moomoo-data", "id": PID}]
    secrets = [{"key": "MOOMOO_DATA_LOGIN_ACCOUNT", "value": "acct", "projectId": PID},
               {"key": "MOOMOO_DATA_LOGIN_PASSWORD", "value": "pw", "projectId": PID},
               {"key": "MOOMOO_DATA_TEST_SYMBOLS", "value": "US.AAPL", "projectId": PID}]
    out = secret_render.load_data_secrets(_tokenfile(tmp_path),
                                          bws_call=_bws_factory(projects, secrets))
    assert set(out) == set(secret_render.ALLOWED_SECRETS)


def test_wrapper_rejects_non_allowlisted_and_other_project(tmp_path):
    projects = [{"name": "trade-ai-lab", "id": "lab-id"},
                {"name": "trade-ai-moomoo-data", "id": PID}]
    base = [{"key": k, "value": "v", "projectId": PID} for k in secret_render.ALLOWED_SECRETS]
    extra = base + [{"key": "MOOMOO_TRADE_UNLOCK_PASSWORD", "value": "x", "projectId": PID}]
    with pytest.raises(CredentialGateError, match="non-allowlisted"):
        secret_render.load_data_secrets(_tokenfile(tmp_path), bws_call=_bws_factory(projects, extra))
    wrong = [{"key": "MOOMOO_DATA_LOGIN_ACCOUNT", "value": "v", "projectId": "lab-id"}]
    with pytest.raises(CredentialGateError, match="non-pinned project"):
        secret_render.load_data_secrets(_tokenfile(tmp_path), bws_call=_bws_factory(projects, wrong))


def test_wrapper_rejects_prod_exposure_sentinel_and_bad_mode(tmp_path):
    proj_prod = [{"name": "trade-ai-prod", "id": "p"}, {"name": "trade-ai-moomoo-data", "id": PID}]
    ok_secrets = [{"key": k, "value": "v", "projectId": PID} for k in secret_render.ALLOWED_SECRETS]
    with pytest.raises(CredentialGateError, match="trade-ai-prod"):
        secret_render.load_data_secrets(_tokenfile(tmp_path),
                                        bws_call=_bws_factory(proj_prod, ok_secrets))
    projects = [{"name": "trade-ai-moomoo-data", "id": PID}]
    sent = [{"key": "MOOMOO_DATA_LOGIN_ACCOUNT", "value": "UNSET__OPERATOR_REQUIRED", "projectId": PID},
            {"key": "MOOMOO_DATA_LOGIN_PASSWORD", "value": "v", "projectId": PID},
            {"key": "MOOMOO_DATA_TEST_SYMBOLS", "value": "US.AAPL", "projectId": PID}]
    with pytest.raises(CredentialGateError, match="sentinel"):
        secret_render.load_data_secrets(_tokenfile(tmp_path), bws_call=_bws_factory(projects, sent))
    bad = tmp_path / "badmode"; bad.write_text("t"); bad.chmod(0o644)
    with pytest.raises(CredentialGateError, match="mode"):
        secret_render.load_data_secrets(bad, bws_call=_bws_factory(projects, ok_secrets))


def test_wrapper_rejects_wrong_project_id_suffix(tmp_path):
    projects = [{"name": "trade-ai-moomoo-data", "id": "aaaa-0000-9999abcd"}]  # wrong suffix
    secrets = [{"key": k, "value": "v", "projectId": "aaaa-0000-9999abcd"}
               for k in secret_render.ALLOWED_SECRETS]
    with pytest.raises(CredentialGateError, match="pinned bootstrap suffix"):
        secret_render.load_data_secrets(_tokenfile(tmp_path), bws_call=_bws_factory(projects, secrets))


def test_render_config_refuses_non_loopback_and_no_password_in_xml(tmp_path):
    secrets = {"MOOMOO_DATA_LOGIN_ACCOUNT": "acct123", "MOOMOO_DATA_LOGIN_PASSWORD": "SECRETPW",
               "MOOMOO_DATA_TEST_SYMBOLS": "US.AAPL"}
    with pytest.raises(CredentialGateError, match="non-loopback"):
        secret_render.render_opend_config(secrets, ip="0.0.0.0", runtime_dir=tmp_path)
    cfg = secret_render.render_opend_config(secrets, runtime_dir=tmp_path)
    text = cfg.read_text()
    import hashlib
    assert "SECRETPW" not in text                # plaintext password never in XML
    assert hashlib.md5(b"SECRETPW").hexdigest() in text    # only the MD5 is present
    assert "<auto_hold_quote_right>0</auto_hold_quote_right>" in text   # auto-grab OFF
    assert "<console>0</console>" in text
    assert "<api_port>11112</api_port>" in text
    import stat, os
    assert stat.S_IMODE(os.stat(cfg).st_mode) == 0o600
    secret_render.cleanup(runtime_dir=tmp_path)
    assert not cfg.exists()


def test_symbols_capped_at_two():
    s = {"MOOMOO_DATA_TEST_SYMBOLS": "US.AAPL,US.MSFT,US.TSLA",
         "MOOMOO_DATA_LOGIN_ACCOUNT": "a", "MOOMOO_DATA_LOGIN_PASSWORD": "b"}
    assert secret_render.test_symbols(s) == ["US.AAPL", "US.MSFT"]


def _env(symbol, st, payload):
    return EventEnvelope(
        event_id="e", stream_type=st.value, symbol=symbol, provider_timestamp=None,
        provider_receive_timestamp=None, gateway_receive_timestamp="t",
        gateway_receive_monotonic_ns=time.monotonic_ns(), reconnect_epoch=0,
        connection_sequence=1, provider_sequence=None, is_first_push=False,
        is_cached=False, session="RTH", payload=payload)
