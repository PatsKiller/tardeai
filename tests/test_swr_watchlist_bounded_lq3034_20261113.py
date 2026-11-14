"""ANCHOR: SWR_WATCHLIST_BOUNDED_LQ3034_20261113 -- /v3/manual-execution request-time compute.

RCA (2026-11-13 walk): /api/v2/watchlist/items took 17.4 s and the server grew ~0.5 GB because
(a) a key not read for > PATH_MAX_STALE_S (1 h) recomputed inline on the request path,
(b) ``symbols=`` lists in different orders were different cache keys (many disk bodies of the same set, 1.4 MB each),
(c) inline computes of distinct keys were unbounded (5-7 at once in the slow log, ~50-175 MB each).

Fix under test (scripts/lib/stale_serve.py, scripts/lib/request_coalesce.py):
- the ``symbols`` list of the watchlist route is canonical in both cache keys;
- every StaleServe compute (inline and background) needs an admission: a per-process/host cap and a memory guard;
- a refused background refresh keeps last-good and names the cause;
- a refused inline compute is 503 UNKNOWN; a last-good body past the route cap is never served (3034b, D1), the 503
  names it with its age; within the cap last-good is still served STALE;
- the host-wide slot pool (shared_get_swr) is used, released, and fails open (T1 of review 3040r);
- an invalidated body is never served, refused or not; slots are always released.

Synthetic only: injected clock, injected spawn, no DB, no network, no server.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import request_coalesce as rc  # noqa: E402
from lib import stale_serve as ss  # noqa: E402

WL = "/api/v2/watchlist/items"
T0 = 1_800_000_000.0


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Spawned:
    def __init__(self) -> None:
        self.fns: list = []

    def __call__(self, fn) -> None:
        self.fns.append(fn)

    def run(self) -> None:
        fns, self.fns = self.fns, []
        for fn in fns:
            fn()


def adm(cap: int = 1, memory: str | None = None) -> "ss.Admission":
    return ss.Admission(cap=cap, memory_refusal=lambda: memory, host_slots=False)


def server(tmp_path, clock, spawned, admission):
    return ss.StaleServe(tmp_path, clock=clock, spawn=spawned, admission=admission)


def good(n: int = 1):
    return 200, {"ok": True, "n": n}


class Counter:
    def __init__(self, result=None, exc: BaseException | None = None) -> None:
        self.calls = 0
        self.result = result if result is not None else good()
        self.exc = exc

    def __call__(self):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


def key(q: dict, principal: str = "p") -> str:
    return ss.request_key(WL, q, principal)


# ── (b) canonical keys ────────────────────────────────────────────────────────────────────────────────────────
def test_permuted_symbols_share_one_stale_serve_key():
    a = key({"symbols": "MSFT,AAPL,NVDA", "full": "1"})
    assert a == key({"full": "1", "symbols": "nvda, aapl ,MSFT"})
    assert a == key({"symbols": "AAPL,MSFT,NVDA,AAPL", "full": "1"})          # a duplicate does not change the set
    assert a != key({"symbols": "AAPL,MSFT", "full": "1"})                     # a different set never shares
    assert "symbols=AAPL,MSFT,NVDA" in a                                        # the canonical form is sorted
    assert rc.canonical_query_value(WL, "symbols", "zz,b,AA") == "AA,B,ZZ"


def test_permuted_symbols_share_one_coalesce_key():
    a = rc.request_key(WL, {"symbols": "MSFT,AAPL"}, "p")
    assert a is not None and a == rc.request_key(WL, {"symbols": "aapl,msft", "_": "123"}, "p")
    assert a != rc.request_key(WL, {"symbols": "AAPL"}, "p")


def test_symbols_canonical_form_only_for_a_single_string_value():
    # the route reads only the FIRST value of a repeated param; two repeated forms are different reads
    assert key({"symbols": ["B", "A"]}) != key({"symbols": ["A", "B"]})
    assert rc.request_key(WL, {"symbols": ["B", "A"]}, "p") != rc.request_key(WL, {"symbols": ["A", "B"]}, "p")
    # an empty list ("symbols=,") is not the unfiltered list ("symbols=" is falsy and reads every row)
    assert key({"symbols": ","}) != key({"symbols": ""})


def test_symbols_are_not_canonical_on_other_routes():
    other = "/api/v2/desks/agents"
    assert ss.request_key(other, {"symbols": "B,A"}, "p") != ss.request_key(other, {"symbols": "A,B"}, "p")


# ── (c) bounded inline compute ───────────────────────────────────────────────────────────────────────────────
def test_inline_compute_over_the_cap_is_refused_unknown_503_without_computing(tmp_path):
    a = adm(cap=1)
    held, _, _ = a.acquire("another key")
    assert held is not None
    srv, compute = server(tmp_path, Clock(), Spawned(), a), Counter()
    status, body = srv.get(key({"sort": "hermes"}), compute)
    assert compute.calls == 0
    assert status == 503 and body["ok"] is False
    assert body["status"] == "UNKNOWN" and body["error"] == "build_deferred"
    assert body["reason"] == "REFUSED_CAP" and body["retry_after_sec"] > 0
    a.release(held)
    assert srv.get(key({"sort": "hermes"}), compute)[0] == 200 and compute.calls == 1


def test_memory_guard_refuses_an_inline_compute(tmp_path):
    srv, compute = server(tmp_path, Clock(), Spawned(), adm(cap=4, memory="memory.current=9 >= 85% of memory.high=10")), Counter()
    status, body = srv.get(key({}), compute)
    assert compute.calls == 0 and status == 503
    assert body["reason"] == "REFUSED_MEMORY" and "memory.current" in body["detail"]


def test_refused_inline_past_max_stale_is_503_unknown_never_the_old_body(tmp_path):
    """3034b (lead decision D1): the page does not render `state`/`_swr`, so a body past the 1 h cap would read
    as current prices. Refused past the cap: 503 UNKNOWN that names the old body and its age, never the body."""
    clock, spawned, a = Clock(), Spawned(), adm(cap=1)
    srv, k = server(tmp_path, clock, spawned, a), key({"sort": "hermes", "full": "1"})
    assert srv.get(k, Counter(good(7)))[1]["n"] == 7
    spawned.run()
    clock.t += 4000                                         # past the 1 h watchlist cap
    held, _, _ = a.acquire("another key")
    compute = Counter(good(8))
    status, body = srv.get(k, compute)
    assert compute.calls == 0
    assert status == 503 and body["ok"] is False and "n" not in body
    assert body["status"] == "UNKNOWN" and body["state"] == "UNKNOWN" and body["error"] == "build_deferred"
    assert body["reason"] == "REFUSED_CAP" and body["retry_after_sec"] > 0
    assert "4000 s old" in body["detail"] and "not served" in body["detail"]
    assert body["_swr"]["past_max_stale"] is True and body["_swr"]["source"] == "none"
    assert body["_swr"]["last_good_age_s"] == pytest.approx(4000, abs=1) and body["_swr"]["age_s"] is None
    assert srv.stats["refused_past_max_stale"] == 1 and srv.stats["deferred"] == 1
    a.release(held)
    assert srv.get(k, compute)[1]["n"] == 8               # admitted again: computes inline, as before


def test_refused_with_no_body_is_503_without_a_past_max_stale_claim(tmp_path):
    a = adm(cap=1)
    held, _, _ = a.acquire("another key")
    srv = server(tmp_path, Clock(), Spawned(), a)
    status, body = srv.get(key({"sort": "score"}), Counter())
    assert status == 503 and body["_swr"]["past_max_stale"] is False and body["_swr"]["last_good_age_s"] is None
    assert srv.stats["refused_past_max_stale"] == 0
    a.release(held)


def test_within_the_cap_a_refused_refresh_still_serves_last_good_stale(tmp_path):
    """Unchanged by 3034b: inside the route cap the last good body is served STALE with its age."""
    clock, spawned, a = Clock(), Spawned(), adm(cap=1)
    srv, k = server(tmp_path, clock, spawned, a), key({"sort": "hermes"})
    srv.get(k, Counter(good(7)))
    spawned.run()
    clock.t += 3000                                         # stale, inside the 1 h cap
    held, _, _ = a.acquire("another key")
    compute = Counter(good(8))
    status, body = srv.get(k, compute)
    assert status == 200 and body["n"] == 7 and body["state"] == "STALE"
    assert body["_swr"]["stale"] is True and body["_swr"]["past_max_stale"] is False
    spawned.run()                                           # the background refresh is refused, not run
    assert compute.calls == 0
    status, body = srv.get(k, compute)
    assert status == 200 and body["n"] == 7 and "REFUSED_CAP" in (body["_swr"]["last_refresh_error"] or "")
    a.release(held)


def test_invalidated_body_is_never_served_even_when_the_compute_is_refused(tmp_path):
    clock, spawned, a = Clock(), Spawned(), adm(cap=1)
    srv, k = server(tmp_path, clock, spawned, a), key({})
    srv.get(k, Counter(good(1)))
    spawned.run()
    clock.t += 5
    srv.invalidate(WL)
    held, _, _ = a.acquire("another key")
    status, body = srv.get(k, Counter(good(2)))
    assert status == 503 and body["status"] == "UNKNOWN" and body.get("n") is None
    a.release(held)


def test_a_slot_is_released_when_the_inline_compute_raises(tmp_path):
    a = adm(cap=1)
    srv = server(tmp_path, Clock(), Spawned(), a)
    with pytest.raises(RuntimeError):
        srv.get(key({}), Counter(exc=RuntimeError("db")))
    assert a.in_use == 0
    assert srv.get(key({}), Counter())[0] == 200


def test_a_slot_is_released_after_a_good_inline_compute(tmp_path):
    a = adm(cap=1)
    srv = server(tmp_path, Clock(), Spawned(), a)
    srv.get(key({}), Counter())
    assert a.in_use == 0


# ── background refresh ───────────────────────────────────────────────────────────────────────────────────────
def test_memory_guard_refuses_a_background_refresh_and_keeps_last_good(tmp_path):
    clock, spawned = Clock(), Spawned()
    state = {"mem": None}
    a = ss.Admission(cap=2, memory_refusal=lambda: state["mem"], host_slots=False)
    srv, k = server(tmp_path, clock, spawned, a), key({})
    srv.get(k, Counter(good(1)))
    spawned.run()
    clock.t += 120                                          # stale, inside the window
    state["mem"] = "memory.current=9 >= 85% of memory.high=10"
    refresh = Counter(good(2))
    first = srv.get(k, refresh, refresh)
    assert first[1]["n"] == 1 and first[1]["state"] == "STALE"
    spawned.run()                                           # the refresh is refused
    assert refresh.calls == 0 and a.in_use == 0
    status, body = srv.get(k, refresh, refresh)
    assert status == 200 and body["n"] == 1
    assert "REFUSED_MEMORY" in body["stale_cause"] and "REFUSED_MEMORY" in body["_swr"]["last_refresh_error"]
    state["mem"] = None
    spawned.run()                                           # a refused refresh does not block the next one
    assert refresh.calls == 1 and srv.get(k, refresh, refresh)[1]["n"] == 2


def test_a_slot_is_released_when_a_background_refresh_raises(tmp_path):
    clock, spawned, a = Clock(), Spawned(), adm(cap=1)
    srv, k = server(tmp_path, clock, spawned, a), key({})
    srv.get(k, Counter())
    spawned.run()
    clock.t += 120
    boom = Counter(exc=RuntimeError("db"))
    srv.get(k, boom, boom)
    spawned.run()
    assert boom.calls == 1 and a.in_use == 0


# ── per-key inline single-flight: followers wait, they do not take slots ────────────────────────────────────
def test_concurrent_inline_reads_of_one_key_compute_once_and_take_one_slot(tmp_path):
    a = adm(cap=1)
    srv, k = server(tmp_path, Clock(), Spawned(), a), key({"sort": "hermes"})
    gate, entered = threading.Event(), threading.Event()
    calls = []

    def slow():
        calls.append(1)
        entered.set()
        assert gate.wait(5)
        return good(3)

    out: list = []
    t1 = threading.Thread(target=lambda: out.append(srv.get(k, slow)))
    t1.start()
    assert entered.wait(5)
    t2 = threading.Thread(target=lambda: out.append(srv.get(k, slow)))
    t2.start()
    t2.join(0.3)
    assert t2.is_alive(), "the follower waits for the leader instead of being refused or computing"
    gate.set()
    t1.join(5)
    t2.join(5)
    assert len(calls) == 1
    assert [r[0] for r in out] == [200, 200] and all(r[1]["n"] == 3 for r in out)
    assert out[0][1] is not out[1][1], "each caller gets its own body dict"
    assert a.in_use == 0


def test_a_read_after_a_write_does_not_join_an_inline_compute_that_began_before_it(tmp_path):
    clock = Clock()
    a = adm(cap=2)
    srv, k = server(tmp_path, clock, Spawned(), a), key({})
    gate, entered = threading.Event(), threading.Event()

    def pre_write():
        entered.set()
        assert gate.wait(5)
        return good(1)

    out: list = []
    t1 = threading.Thread(target=lambda: out.append(srv.get(k, pre_write)))
    t1.start()
    assert entered.wait(5)
    clock.t += 1
    srv.invalidate(WL)
    clock.t += 1
    post = srv.get(k, Counter(good(2)))                     # must not wait for or reuse the pre-write compute
    assert post[1]["n"] == 2
    gate.set()
    t1.join(5)
    assert a.in_use == 0


def test_a_write_while_a_follower_waits_is_never_answered_with_the_pre_write_body(tmp_path):
    clock, spawned, a = Clock(), Spawned(), adm(cap=2)
    srv = ss.StaleServe(tmp_path, clock=clock, spawn=spawned, admission=a, inline_wait_s=0.3)
    k = key({"sort": "hermes"})
    srv.get(k, Counter(good(1)))
    spawned.run()
    clock.t += 4000                                         # past the cap: the next reads compute inline
    gate, entered = threading.Event(), threading.Event()

    def slow():
        entered.set()
        assert gate.wait(5)
        return good(2)

    out: list = []
    t1 = threading.Thread(target=lambda: srv.get(k, slow))
    t1.start()
    assert entered.wait(5)
    t2 = threading.Thread(target=lambda: out.append(srv.get(k, slow)))
    t2.start()
    t2.join(0.1)                                            # the follower has joined and holds the old body
    srv.invalidate(WL)
    t2.join(5)                                              # its wait times out after the write
    gate.set()
    t1.join(5)
    status, body = out[0]
    assert status == 503 and body["status"] == "UNKNOWN" and body.get("n") is None
    assert body["reason"] == ss.BUILD_IN_PROGRESS
    # the old body was invalidated during the wait: the 503 must not even claim a servable body exists (3034b)
    assert body["_swr"]["past_max_stale"] is False and body["_swr"]["last_good_age_s"] is None


def test_a_follower_that_times_out_past_the_cap_gets_503_never_the_old_body(tmp_path):
    clock, spawned, a = Clock(), Spawned(), adm(cap=2)
    srv = ss.StaleServe(tmp_path, clock=clock, spawn=spawned, admission=a, inline_wait_s=0.2)
    k = key({"sort": "hermes"})
    srv.get(k, Counter(good(1)))
    spawned.run()
    clock.t += 4000
    gate, entered = threading.Event(), threading.Event()

    def slow():
        entered.set()
        assert gate.wait(5)
        return good(2)

    out: list = []
    t1 = threading.Thread(target=lambda: srv.get(k, slow))
    t1.start()
    assert entered.wait(5)
    t2 = threading.Thread(target=lambda: out.append(srv.get(k, slow)))
    t2.start()
    t2.join(5)
    gate.set()
    t1.join(5)
    status, body = out[0]
    assert status == 503 and body["state"] == "UNKNOWN" and body.get("n") is None
    assert body["reason"] == ss.BUILD_IN_PROGRESS and body["_swr"]["past_max_stale"] is True
    assert body["_swr"]["last_good_age_s"] == pytest.approx(4000, abs=1)


# ── default admission ────────────────────────────────────────────────────────────────────────────────────────
def test_default_admission_cap_comes_from_the_shared_env(monkeypatch):
    monkeypatch.setenv("SWR_MAX_CONCURRENT_BUILDS", "3")
    assert ss.Admission().cap == 3


def test_local_memory_guard_fails_open_when_the_cgroup_is_unreadable(monkeypatch):
    monkeypatch.setattr(ss, "_cgroup_memory", lambda: (None, None))
    assert ss.local_memory_refusal() is None
    monkeypatch.setattr(ss, "_cgroup_memory", lambda: (90, 100))
    assert "memory.current=90" in (ss.local_memory_refusal() or "")
    monkeypatch.setattr(ss, "_cgroup_memory", lambda: (80, 100))
    assert ss.local_memory_refusal() is None


# ── T1 (review 3040r): the host-wide slot pool from shared_get_swr ─────────────────────────────────────────────
class FakePool:
    """Stands in for shared_get_swr: acquire_host_slots answers from `answer`, release_slots is recorded."""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.acquired: list = []
        self.released: list = []

    def max_concurrent_builds(self) -> int:
        return 2

    def _memory_refusal(self):
        return None

    def acquire_host_slots(self, key: str, cap: int):
        self.acquired.append((key, cap))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    def release_slots(self, fds) -> None:
        self.released.append(list(fds))


def pooled(monkeypatch, answer) -> tuple:
    pool = FakePool(answer)
    monkeypatch.setattr(ss, "_shared", lambda: pool)
    return ss.Admission(), pool                             # every default: cap, guard and pool from the module


def test_host_pool_is_used_by_default_and_its_slots_are_released_once(monkeypatch):
    a, pool = pooled(monkeypatch, ([11, 12], None))
    token, outcome, _ = a.acquire("p|/api/v2/watchlist/items?sort=hermes")
    assert outcome is None and token is not None and a.cap == 2 and a.in_use == 1
    assert pool.acquired == [("stale_serve:p|/api/v2/watchlist/items?sort=hermes", 2)]
    a.release(token)
    a.release(token)                                        # idempotent: one release, never two
    assert pool.released == [[11, 12]] and a.in_use == 0


def test_host_pool_refusal_does_not_leak_the_process_slot(monkeypatch):
    a, pool = pooled(monkeypatch, (None, ss.REFUSED_DUPLICATE))
    for _ in range(3):                                      # more refusals than the cap: no slot may leak
        token, outcome, detail = a.acquire("k")
        assert token is None and outcome == ss.REFUSED_DUPLICATE and "another process" in detail
    assert a.in_use == 0 and pool.released == []
    pool.answer = ([5, 6], None)
    token, outcome, _ = a.acquire("k")                      # still admits once the pool frees up
    assert token is not None and outcome is None
    a.release(token)


def test_host_pool_refusal_without_an_outcome_is_refused_cap(monkeypatch):
    a, _ = pooled(monkeypatch, (None, None))
    token, outcome, detail = a.acquire("k")
    assert token is None and outcome == ss.REFUSED_CAP and "host-wide" in detail and a.in_use == 0


def test_host_pool_error_fails_open_to_the_process_cap(monkeypatch):
    a, pool = pooled(monkeypatch, OSError("slot dir unwritable"))
    t1, o1, _ = a.acquire("k1")
    t2, o2, _ = a.acquire("k2")
    t3, o3, _ = a.acquire("k3")
    assert t1 is not None and t2 is not None and o1 is None and o2 is None
    assert t3 is None and o3 == ss.REFUSED_CAP             # the per-process cap (2) still holds
    a.release(t1)
    a.release(t2)
    assert pool.released == [] and a.in_use == 0            # nothing was granted, nothing is released


def test_host_slots_false_never_touches_the_pool(monkeypatch):
    pool = FakePool(([1, 2], None))
    monkeypatch.setattr(ss, "_shared", lambda: pool)
    a = ss.Admission(cap=1, memory_refusal=lambda: None, host_slots=False)
    a.release(a.acquire("k")[0])
    assert pool.acquired == [] and pool.released == []


def test_real_host_pool_refuses_a_duplicate_and_a_full_pool_across_admissions(monkeypatch, tmp_path):
    """The real shared_get_swr pool where the tree has it (wt/mem-contain-lead, 93728de3f and later)."""
    mod = ss._shared()
    if mod is None or not callable(getattr(mod, "acquire_host_slots", None)):
        pytest.skip("this tree's shared_get_swr has no host slot pool")
    monkeypatch.setenv("SWR_SLOT_DIR", str(tmp_path / "slots"))
    one = ss.Admission(cap=1, memory_refusal=lambda: None)
    two = ss.Admission(cap=1, memory_refusal=lambda: None)
    t1, o1, _ = one.acquire("p|/api/v2/watchlist/items?sort=hermes")
    assert t1 is not None and o1 is None and len(t1.fds) == 2
    assert two.acquire("p|/api/v2/watchlist/items?sort=hermes")[1] == ss.REFUSED_DUPLICATE
    assert two.acquire("p|/api/v2/watchlist/items?sort=score")[1] == ss.REFUSED_CAP
    assert two.in_use == 0
    one.release(t1)
    t2, o2, _ = two.acquire("p|/api/v2/watchlist/items?sort=score")
    assert t2 is not None and o2 is None
    two.release(t2)
