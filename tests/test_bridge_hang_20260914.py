"""The governed model bridge cannot be wedged by one held provider call, and a watchdog notices if it is.

2026-09-14, from 14:45 ET:
- DeepSeek held the bridge's non-streaming requests about 906 s each, trickling keep-alive bytes, so the
  90 s per-read timeout never fired.
- The single-threaded HTTPServer queued every caller behind each held call, for about 90 minutes: CIO
  research, desk answers, advisory opinions.
- /health did not exist (501), and nothing alarmed.

Offline: no provider, no Telegram, no systemd. Servers bind to an ephemeral loopback port.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.cio_governed_model_bridge as bridge  # noqa: E402
import cio_bridge_watchdog as wd  # noqa: E402

COVERS = ["scripts/cio_bridge_watchdog.py"]


class _Trickle:
    """A provider response that keeps sending keep-alive newlines and never finishes."""

    status_code = 200
    headers: dict = {}

    def __init__(self, pause: float = 0.0, body: bytes | None = None):
        self.pause = pause
        self.body = body
        self.closed = False

    def iter_content(self, chunk_size: int = 8192):
        if self.body is not None:
            yield self.body
            return
        while True:
            if self.pause:
                time.sleep(self.pause)
            yield b"\n"

    def close(self):
        self.closed = True


# ── the deadline ─────────────────────────────────────────────────────────────


def test_a_trickling_upstream_is_cut_off_at_the_wall_clock_deadline():
    # Re-checked 2026-10-15: the read now runs on a reader thread and the caller also reads the clock once
    # (before starting it), so both share `ticks`. The caller's first tick is 0 -> it joins for up to 25 real
    # seconds, while the reader's own ticks pass 25 within three chunks and it raises by itself, at once.
    ticks = iter(range(0, 10_000, 10))
    resp = _Trickle()
    t0 = time.time()
    with pytest.raises(bridge.UpstreamDeadlineExceeded):
        bridge.read_body_with_deadline(resp, 0.0, deadline_s=25, clock=lambda: next(ticks))
    assert resp.closed
    assert time.time() - t0 < 2


class _Silent:
    """A provider that holds the request and sends nothing: iter_content blocks without yielding."""

    status_code = 200
    headers: dict = {}

    def __init__(self, hold: float = 5.0):
        self.hold = hold
        self.closed = False
        self.released = threading.Event()

    def iter_content(self, chunk_size: int = 8192):
        self.released.wait(self.hold)
        yield b"\n"

    def close(self):
        self.closed = True
        self.released.set()


class _MidBodyReadTimeout:
    """iter_content raising what requests raises for a mid-body socket read timeout (models.py:827-828)."""

    status_code = 200
    headers: dict = {}

    def __init__(self):
        self.closed = False

    def iter_content(self, chunk_size: int = 8192):
        import requests
        from urllib3.exceptions import ReadTimeoutError

        yield b"{"
        raise requests.ConnectionError(ReadTimeoutError(None, "/v1/chat/completions", "Read timed out."))

    def close(self):
        self.closed = True


def test_a_silent_upstream_is_cut_off_at_the_deadline_without_a_single_byte():
    """2026-10-15: the deadline was checked only when a chunk arrived. Nothing arriving must not extend it."""
    resp = _Silent(hold=5.0)
    t0 = time.time()
    with pytest.raises(bridge.UpstreamDeadlineExceeded) as err:
        bridge.read_body_with_deadline(resp, t0, deadline_s=0.3)
    assert time.time() - t0 < 0.3 + 0.5
    assert "past 0.3s" in str(err.value)
    assert resp.closed  # closed at the deadline, which also releases the abandoned reader


def test_a_keepalive_trickle_cannot_stretch_the_deadline_in_real_time():
    """The 180 s overrun of a 150 s budget, scaled down: bytes keep arriving, the deadline still holds."""
    resp = _Trickle(pause=0.05)
    t0 = time.time()
    with pytest.raises(bridge.UpstreamDeadlineExceeded):
        bridge.read_body_with_deadline(resp, t0, deadline_s=0.3)
    assert time.time() - t0 < 0.3 + 0.5


def test_a_mid_body_read_timeout_is_a_timeout_not_a_network_error():
    import requests
    from urllib3.exceptions import ReadTimeoutError

    wrapped = requests.ConnectionError(ReadTimeoutError(None, "/x", "Read timed out."))
    assert bridge.is_upstream_timeout(wrapped)
    assert not bridge.is_upstream_timeout(requests.ConnectionError("connection reset by peer"))
    resp = _MidBodyReadTimeout()
    with pytest.raises(bridge.UpstreamReadTimeout):
        bridge.read_body_with_deadline(resp, time.time(), deadline_s=30)
    assert resp.closed


def _deepseek_generate(monkeypatch, response):
    import requests

    import lib.llm_model_registry as lmr

    costs = []
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(lmr, "get_deepseek_api_key", lambda: ("test-key", "deepseek_tradeai", False))
    monkeypatch.setattr(bridge, "_emit_bridge_cost", lambda **kw: costs.append(kw))
    with pytest.raises(RuntimeError) as err:
        bridge.RealProvider().generate([{"role": "user", "content": "x"}], "deepseek-flash")
    return err.value, costs, seen


def test_generate_records_a_mid_body_read_timeout_as_timeout(monkeypatch):
    err, costs, _seen = _deepseek_generate(monkeypatch, _MidBodyReadTimeout())
    assert "timeout" in str(err).lower()
    assert getattr(err, "possibly_billable", False) is True
    assert costs and costs[-1]["error_class"] == "TIMEOUT"


def test_generate_still_records_a_real_network_error_as_network_error(monkeypatch):
    import requests

    err, costs, _seen = _deepseek_generate(monkeypatch, requests.ConnectionError("connection reset by peer"))
    assert "network error" in str(err).lower()
    assert costs and costs[-1]["error_class"] == "NETWORK_ERROR"


def test_generate_caps_the_per_read_socket_timeout(monkeypatch):
    monkeypatch.setattr(bridge, "UPSTREAM_DEADLINE_S", 150.0)
    monkeypatch.setattr(bridge, "UPSTREAM_READ_TIMEOUT_S", 60.0)
    _err, _costs, seen = _deepseek_generate(monkeypatch, _MidBodyReadTimeout())
    assert seen["timeout"][1] == bridge.UPSTREAM_READ_TIMEOUT_CAP_S == 30.0


def test_generate_on_a_silent_upstream_returns_at_the_deadline(monkeypatch):
    monkeypatch.setattr(bridge, "UPSTREAM_DEADLINE_S", 0.3)
    t0 = time.time()
    err, costs, _seen = _deepseek_generate(monkeypatch, _Silent(hold=5.0))
    assert time.time() - t0 < 0.3 + 0.5
    assert "past 0.3s" in str(err) and costs[-1]["error_class"] == "TIMEOUT"


# ── the breaker on stalls (2026-10-15) ───────────────────────────────────────


def _single_lane_plan():
    return [
        {"lane": "primary", "provider": "deepseek", "policy_name": "FAST", "model_id": "deepseek-flash", "skip": None}
    ]


def _walk(use_circuits: bool = False, budget_s: float = 5.0):
    return bridge.walk_routes(
        _single_lane_plan(),
        [{"role": "user", "content": "x"}],
        policy_id=None,
        budget_s=budget_s,
        tools=None,
        tool_choice=None,
        response_format=None,
        max_tokens=64,
        thinking="disabled",
        reasoning_effort=None,
        request_id="t-stall",
        use_circuits=use_circuits,
    )


class _FailingDeepSeek:
    def __init__(self, exc_factory):
        self.exc_factory = exc_factory
        self.calls = 0

    def generate(self, messages, model_id=None, **kw):
        self.calls += 1
        raise self.exc_factory()


def _timeout_exc():
    err = RuntimeError("DeepSeek API timeout after 150s: upstream kept the request open past 150s (3 bytes)")
    err.request_sent = True
    err.possibly_billable = True
    return err


def _overloaded_exc():
    err = RuntimeError('DeepSeek API returned HTTP 503: {"error": "server overloaded"}')
    err.request_sent = True
    err.possibly_billable = True
    err.http_status = 503
    return err


def _network_exc():
    err = RuntimeError("DeepSeek API network error: ConnectionError")
    err.request_sent = True
    return err


@pytest.fixture
def breaker():
    bridge._reset_circuit()
    yield bridge.PROVIDER_CIRCUITS
    bridge.set_transport_override("deepseek", None)
    bridge._reset_circuit()


@pytest.mark.parametrize("exc_factory", [_timeout_exc, _overloaded_exc], ids=["timeout", "http_503"])
def test_single_lane_rows_open_the_provider_breaker_on_repeated_stalls(breaker, exc_factory):
    """A DeepSeek-only row (use_circuits=False) used to feed nothing, so every later call paid the full deadline."""
    fake = _FailingDeepSeek(exc_factory)
    bridge.set_transport_override("deepseek", fake)
    for _ in range(breaker.threshold):
        out = _walk()
        assert out["receipts"][-1]["attempted"] is True
    assert breaker.snapshot()["deepseek"]["open"] is True
    t0 = time.time()
    out = _walk()
    assert time.time() - t0 < 0.5  # skipped fast, not another deadline
    assert out["receipts"][-1]["outcome"] == "circuit_open" and out["response"] is None
    assert fake.calls == breaker.threshold


def test_a_non_stall_failure_on_a_single_lane_row_does_not_open_the_breaker(breaker):
    fake = _FailingDeepSeek(_network_exc)
    bridge.set_transport_override("deepseek", fake)
    for _ in range(breaker.threshold + 1):
        _walk()
    assert fake.calls == breaker.threshold + 1
    assert breaker.snapshot()["deepseek"]["open"] is False


def test_a_served_call_closes_the_stall_count(breaker):
    fake = _FailingDeepSeek(_timeout_exc)
    bridge.set_transport_override("deepseek", fake)
    for _ in range(breaker.threshold - 1):
        _walk()

    class _Ok:
        def generate(self, messages, model_id=None, **kw):
            return {"model": "deepseek-flash", "choices": [{"message": {"content": "ok"}}]}

    bridge.set_transport_override("deepseek", _Ok())
    assert _walk()["response"] is not None
    assert breaker.snapshot()["deepseek"]["errors"] == 0


def test_a_held_upstream_never_leaks_a_provider_slot(breaker):
    """The reader thread outlives the deadline briefly; the provider slot must already be back."""
    held = []

    class _HeldDeepSeek:
        def generate(self, messages, model_id=None, **kw):
            resp = _Silent(hold=5.0)
            held.append(resp)
            bridge.read_body_with_deadline(resp, time.time(), deadline_s=0.2)

    bridge.set_transport_override("deepseek", _HeldDeepSeek())
    sem = bridge.provider_semaphore("deepseek", None)
    limit = bridge.provider_slot_limit("deepseek", bridge.normalize_routing_policy_header(None))
    out = _walk()
    assert out["receipts"][-1]["outcome"] == "timeout" and held[0].closed
    taken = [sem.acquire(blocking=False) for _ in range(limit)]
    try:
        assert all(taken)
    finally:
        for ok in taken:
            if ok:
                sem.release()


def test_a_complete_body_inside_the_deadline_is_returned():
    resp = _Trickle(body=b'{"ok": true}')
    assert bridge.read_body_with_deadline(resp, time.time(), deadline_s=30) == b'{"ok": true}'
    assert resp.closed


def test_generate_reports_a_held_request_as_a_timeout(monkeypatch):
    import requests

    import lib.llm_model_registry as lmr

    seen = {}
    costs = []

    def fake_post(url, **kw):
        seen.update(kw)
        return _Trickle(pause=0.02)

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(lmr, "get_deepseek_api_key", lambda: ("test-key", "deepseek_tradeai", False))
    monkeypatch.setattr(bridge, "_emit_bridge_cost", lambda **kw: costs.append(kw))
    monkeypatch.setattr(bridge, "UPSTREAM_DEADLINE_S", 0.15)
    started = time.time()
    with pytest.raises(RuntimeError) as err:
        bridge.RealProvider().generate([{"role": "user", "content": "x"}], "deepseek-flash")
    assert time.time() - started < 5
    assert "timeout" in str(err.value).lower() and "past 0.15s" in str(err.value)
    assert getattr(err.value, "possibly_billable", False) is True
    assert seen["stream"] is True
    assert costs and costs[-1]["error_class"] == "TIMEOUT"


# ── the server ───────────────────────────────────────────────────────────────


@pytest.fixture
def served(monkeypatch):
    release = threading.Event()
    entered = threading.Event()

    def held_call(messages, **kw):
        entered.set()
        release.wait(10)
        return {"id": "x", "choices": [{"message": {"role": "assistant", "content": "done"}}]}

    monkeypatch.setattr(bridge, "execute_governed_call", held_call)
    monkeypatch.setattr(bridge, "resolve_caller", lambda caller, task_type=None: "alex_cio_synthesis")
    server = bridge.start_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, release, entered
    finally:
        release.set()
        server.shutdown()
        server.server_close()


def _post(base: str, timeout: float = 10.0):
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
        headers={bridge.AUTH_HEADER: "alex", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_health_answers_while_a_provider_call_is_held(served):
    base, release, entered = served
    worker = threading.Thread(target=_post, args=(base,), daemon=True)
    worker.start()
    assert entered.wait(5)
    t0 = time.time()
    with urllib.request.urlopen(f"{base}/health", timeout=3) as resp:
        body = json.loads(resp.read())
    assert time.time() - t0 < 2
    assert resp.status == 200 and body["inflight"] == 1 and body["oldest_inflight_s"] is not None
    assert body["upstream_deadline_s"] == bridge.UPSTREAM_DEADLINE_S
    release.set()
    worker.join(5)


def test_a_full_bridge_answers_503_at_once_instead_of_queueing(served, monkeypatch):
    base, release, entered = served
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(bridge, "_INFLIGHT_SLOTS", slots)
    t0 = time.time()
    status, body = _post(base, timeout=5)
    assert status == 503 and body["error"]["code"] == "BRIDGE_BUSY"
    assert time.time() - t0 < 2


# ── the watchdog ─────────────────────────────────────────────────────────────

NOW = datetime(2026, 9, 14, 20, 30, tzinfo=timezone.utc)


def test_classify():
    assert wd.classify({"answered": False}) == wd.WEDGED
    assert wd.classify({"answered": True, "body": {"circuit_open": True}}) == wd.CIRCUIT_OPEN
    assert (
        wd.classify({"answered": True, "body": {"oldest_inflight_s": 400, "upstream_deadline_s": 150}})
        == wd.BUSY_UPSTREAM
    )
    assert wd.classify({"answered": True, "body": {"oldest_inflight_s": 20, "upstream_deadline_s": 150}}) == wd.OK
    assert wd.classify({"answered": True, "http": 501, "body": {}}) == wd.OK


def test_one_missed_probe_does_not_restart_but_two_do():
    first = wd.decide(wd.WEDGED, {}, now=NOW, wedged_threshold=2, restart_cooldown_s=1800)
    assert not first["restart"] and first["alert"]
    second = wd.decide(
        wd.WEDGED,
        {"consecutive_wedged": 1, "last_status": wd.WEDGED},
        now=NOW,
        wedged_threshold=2,
        restart_cooldown_s=1800,
    )
    assert second["restart"] and not second["alert"]


def test_restarts_are_rate_limited():
    recent = (NOW - timedelta(minutes=5)).isoformat()
    d = wd.decide(
        wd.WEDGED,
        {"consecutive_wedged": 3, "last_status": wd.WEDGED, "last_restart_at": recent},
        now=NOW,
        wedged_threshold=2,
        restart_cooldown_s=1800,
    )
    assert not d["restart"] and d["restart_blocked_by_cooldown"]


def test_a_wedged_bridge_is_restarted_and_the_operator_is_told(tmp_path):
    state = tmp_path / "wd.json"
    state.write_text(json.dumps({"consecutive_wedged": 1, "last_status": wd.WEDGED}))
    probes = iter(
        [
            {"answered": False, "error": "TimeoutError: timed out"},
            {"answered": True, "http": 200, "body": {"inflight": 0}},
        ]
    )
    restarts, sent = [], []
    receipt = wd.run_once(
        apply=True,
        state_path=state,
        now=NOW,
        prober=lambda: next(probes),
        restarter=lambda: restarts.append(1) or {"rc": 0},
        sender=lambda text, **kw: sent.append((text, kw)) or True,
    )
    assert restarts == [1] and receipt["restarted"] == {"rc": 0}
    assert sent and sent[0][1]["message_class"] == "ops"
    assert "not answering" in sent[0][0] and "answering" in sent[0][0].split("after restart:")[1]
    assert json.loads(state.read_text())["last_restart_at"] == NOW.isoformat()


def test_a_provider_failure_is_alerted_but_never_restarted(tmp_path):
    restarts, sent = [], []
    receipt = wd.run_once(
        apply=True,
        state_path=tmp_path / "wd.json",
        now=NOW,
        prober=lambda: {
            "answered": True,
            "http": 200,
            "body": {"circuit_open": True, "last_error": "provider_failure:RuntimeError"},
        },
        restarter=lambda: restarts.append(1) or {"rc": 0},
        sender=lambda text, **kw: sent.append(text) or True,
    )
    assert receipt["status"] == wd.CIRCUIT_OPEN and not restarts
    assert sent and "circuit open" in sent[0]


def test_dry_run_changes_nothing(tmp_path):
    state = tmp_path / "wd.json"
    receipt = wd.run_once(
        apply=False,
        state_path=state,
        now=NOW,
        prober=lambda: {"answered": False},
        restarter=lambda: pytest.fail("dry run restarted"),
        sender=lambda *a, **k: pytest.fail("dry run sent"),
    )
    assert receipt["mode"] == "dry_run" and not state.exists()
