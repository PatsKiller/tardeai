"""LQ-20261113-3051 (review 3034b C1 + A1 + A4): a 503 build_deferred from StaleServe reaches the route intact.

The 503 UNKNOWN ``build_deferred`` is the normal first read after a night (6 h ``MAX_STALE_S``). Two in-process
callers return bodies, not ``(status, body)``:
  * C1a  api_v3_trade_journey._serve dropped the status, so the route answered HTTP 200 ``ok: false``;
  * C1b  api_v3_data_broker_watch.get_curation raised ValueError, so the route answered HTTP 500.
Both now raise ``stale_serve.Deferred`` carrying the 503 and its body; the route returns ``served_response``.
A1: the retry hint is ``retry_after_sec``, the name useApi.ts:271 and every other 503 read.
A4: ``last_good_age_s`` is measured from ``computed_at`` (R4) and a follower of a refused leader keeps the
``past_max_stale`` claim (F4). Synthetic fixtures only; no DB, no HTTP.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import api_v3_data_broker_watch as dbw  # noqa: E402
import api_v3_trade_journey as tj  # noqa: E402
from lib import stale_serve as ss  # noqa: E402

T0 = 1_800_000_000.0


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _full_admission():
    """An admission whose only slot is held: every inline compute is refused REFUSED_CAP."""
    a = ss.Admission(cap=1, memory_refusal=lambda: None, host_slots=False)
    held, _, _ = a.acquire("someone else's key")
    assert held is not None
    return a


def _refusing_server(tmp_path):
    return ss.StaleServe(tmp_path, clock=Clock(), spawn=lambda fn: None, admission=_full_admission())


def _never(*_a, **_k):
    raise AssertionError("a refused read must not compute")


def _assert_deferred_503(exc: BaseException) -> None:
    assert isinstance(exc, ss.Deferred), type(exc)
    status, body = exc.served_response
    assert status == 503 and exc.status == 503
    assert body["ok"] is False and body["status"] == "UNKNOWN" and body["error"] == "build_deferred"
    assert body["reason"] == ss.REFUSED_CAP
    assert body["retry_after_sec"] > 0 and "retry_after_s" not in body


# ── C1a: trade journeys ──────────────────────────────────────────────────────────────────────────────────────
def test_trade_journey_list_passes_a_503_through_never_a_200_body(tmp_path, monkeypatch):
    srv = _refusing_server(tmp_path)
    monkeypatch.setattr(tj, "_swr", lambda: ss)
    monkeypatch.setattr(tj, "_server", lambda kind: srv)
    monkeypatch.setattr(ss, "enabled", lambda: True)
    with pytest.raises(Exception) as ei:
        tj._serve("list", "list|days=30", _never, {"days": "30"})
    _assert_deferred_503(ei.value)


def test_trade_journey_detail_passes_a_503_through(tmp_path, monkeypatch):
    srv = _refusing_server(tmp_path)
    monkeypatch.setattr(tj, "_swr", lambda: ss)
    monkeypatch.setattr(tj, "_server", lambda kind: srv)
    monkeypatch.setattr(ss, "enabled", lambda: True)
    with pytest.raises(Exception) as ei:
        tj._serve("detail", "detail|T-1|", _never, {})
    _assert_deferred_503(ei.value)


def test_trade_journey_good_read_is_still_the_body(tmp_path, monkeypatch):
    srv = ss.StaleServe(tmp_path, clock=Clock(), spawn=lambda fn: None,
                        admission=ss.Admission(cap=1, memory_refusal=lambda: None, host_slots=False))
    monkeypatch.setattr(tj, "_swr", lambda: ss)
    monkeypatch.setattr(tj, "_server", lambda kind: srv)
    monkeypatch.setattr(ss, "enabled", lambda: True)
    body = tj._serve("list", "list|", lambda: {"ok": True, "rows": [1]}, {})
    assert body["ok"] is True and body["rows"] == [1]


# ── C1b: watch curation ──────────────────────────────────────────────────────────────────────────────────────
def test_watch_curation_passes_a_503_through_never_a_500(tmp_path, monkeypatch):
    srv = _refusing_server(tmp_path)
    monkeypatch.setattr(dbw, "_swr_context", lambda: (ss, "p1", None))
    monkeypatch.setattr(ss, "default", lambda: srv)
    monkeypatch.setattr(dbw, "_read_curation", _never)
    with pytest.raises(Exception) as ei:
        dbw.get_curation({})
    assert not isinstance(ei.value, ValueError)
    _assert_deferred_503(ei.value)


def test_watch_curation_good_read_is_still_the_body(tmp_path, monkeypatch):
    srv = ss.StaleServe(tmp_path, clock=Clock(), spawn=lambda fn: None,
                        admission=ss.Admission(cap=1, memory_refusal=lambda: None, host_slots=False))
    monkeypatch.setattr(dbw, "_swr_context", lambda: (ss, "p1", None))
    monkeypatch.setattr(ss, "default", lambda: srv)
    monkeypatch.setattr(dbw, "_read_curation", lambda q: {"ok": True, "watchlist": ["AAPL"]})
    assert dbw.get_curation({})["watchlist"] == ["AAPL"]


# ── A1: the retry field's name ───────────────────────────────────────────────────────────────────────────────
def test_503_retry_hint_is_retry_after_sec_the_name_useapi_reads(tmp_path):
    status, body = _refusing_server(tmp_path).get(ss.request_key("/api/v2/watchlist/items", {}, "p"), _never)
    assert status == 503
    assert body["retry_after_sec"] == ss.RETRY_AFTER_S and "retry_after_s" not in body


def test_useapi_reads_retry_after_sec():
    src = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/hooks/useApi.ts").read_text()
    assert "retry_after_sec" in src


# ── A4: R4 and F4 ─────────────────────────────────────────────────────────────────────────────────────────────
def test_last_good_age_is_measured_from_computed_at_not_started_at(tmp_path):
    """R4: a compute that takes 30 s; the age of its body runs from when it finished."""
    clock = Clock()
    a = ss.Admission(cap=1, memory_refusal=lambda: None, host_slots=False)
    srv = ss.StaleServe(tmp_path, clock=clock, spawn=lambda fn: None, admission=a)
    k = ss.request_key("/api/v2/watchlist/items", {"sort": "hermes"}, "p")

    def slow():
        clock.t += 30                       # the compute itself takes 30 s
        return 200, {"ok": True, "n": 1}

    assert srv.get(k, slow)[0] == 200
    clock.t += 4000                         # 4000 s after it finished, 4030 s after it began
    held, _, _ = a.acquire("another key")
    status, body = srv.get(k, _never)
    assert status == 503 and body["_swr"]["past_max_stale"] is True
    assert body["_swr"]["last_good_age_s"] == pytest.approx(4000, abs=1)
    assert "4000 s old" in body["detail"]
    a.release(held)


def test_a_follower_of_a_refused_leader_keeps_the_past_max_stale_claim(tmp_path):
    """F4: the follower joins while the leader waits on admission; the leader is refused; both 503s name the
    old body and its age."""
    clock = Clock()
    gate, asked = threading.Event(), threading.Event()

    def memory_refusal():
        asked.set()
        assert gate.wait(5)
        return "memory.current=9 >= 85% of memory.high=10"

    a = ss.Admission(cap=2, memory_refusal=memory_refusal, host_slots=False)
    srv = ss.StaleServe(tmp_path, clock=clock, spawn=lambda fn: None, admission=a, inline_wait_s=5)
    k = ss.request_key("/api/v2/watchlist/items", {"sort": "hermes"}, "p")
    # seed a last-good body without going through admission (the guard would block it)
    srv._remember(k, (200, {"ok": True, "n": 1}), clock.t)
    clock.t += 4000
    out: dict = {}
    leader = threading.Thread(target=lambda: out.__setitem__("leader", srv.get(k, _never)))
    leader.start()
    assert asked.wait(5)
    follower = threading.Thread(target=lambda: out.__setitem__("follower", srv.get(k, _never)))
    follower.start()
    deadline = threading.Event()
    for _ in range(100):                    # until the follower has joined the leader's flight
        if srv.stats.get("joined", 0) >= 1:
            break
        deadline.wait(0.02)
    assert srv.stats.get("joined", 0) == 1
    gate.set()
    leader.join(5)
    follower.join(5)
    for who in ("leader", "follower"):
        status, body = out[who]
        assert status == 503 and body["reason"] == ss.REFUSED_MEMORY, who
        assert body["_swr"]["past_max_stale"] is True, who
        assert body["_swr"]["last_good_age_s"] == pytest.approx(4000, abs=1), who
        assert "n" not in body, who
