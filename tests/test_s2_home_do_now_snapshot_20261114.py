"""S2 item 2 (operator 2026-11-14): Home "Do now" is a producer-written snapshot, and a GET only reads it.

The defect this pins: GET /api/v2/home/do-now built its body on the request thread whenever its in-process cache was
empty — the first Home open after a restart, a cache miss, or a second reader during a build. The build is a ~5 s
fan-out (measured 5.0 s for needs_action alone on the 2026-11-14 16:17Z capture). Cold restart, cache miss and
dependency failure each cost a request that computation.

The fix: the lane `home-do-now-snapshot` builds it out of process and writes HomeDoNowSnapshot@v1; the route reads
the file. These tests pin, in order:

* the store/reader contract (fresh / last-good-with-age / expired / missing / corrupt / not_ok / clock skew /
  another release),
* that the module has NO compute path (so no future edit can quietly reintroduce a build-on-GET),
* the producer's single-flight and "a failed build leaves the previous body",
* the per-request authorization recheck (a principal-gated item is dropped for a caller that may not see it),
* the NAMED UNKNOWN (counts null, owner + next action present), and
* the route itself: with `_home_do_now_build` instrumented to raise, every one of cold restart / cache miss /
  aged / expired / dependency failure still answers — proving no heavy computation runs on the GET.

Anchor: S2_READ_MODEL (config/ci_gates/S2_READ_MODEL_20261114.json).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ANCHOR = "S2_READ_MODEL"


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    """A clean module state and a scratch snapshot path for every test."""
    from lib import home_do_now_snapshot as hdn

    hdn._PARSED.clear()
    path = tmp_path / "home_do_now_snapshot.json"
    monkeypatch.setenv(hdn.PATH_ENV, str(path))
    return path


def _body(items=None, sources=None, as_of="2026-11-14T16:17:25+00:00"):
    return {
        "schema": "HomeDoNow@v1",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": as_of,
        "status": "OK",
        "all_sources_answered": True,
        "any_source_stale": False,
        "sort": "money at risk",
        "top_n": 7,
        "counts": {"all": len(items or []), "protect": 0, "decide": 0, "fix": 0},
        "severity_counts": {"P1": len(items or [])},
        "items": items or [],
        "rolled_up": {"raw_items": len(items or [])},
        "numbers": {"status": "OK"},
        "sources": sources or {},
        "timeout_s": 60,
    }


def _write(path: Path, *, age_s: float, identity: str = "sha:test", body: dict | None = None, **over):
    from lib import home_do_now_snapshot as hdn

    built = 1000.0
    doc = {
        "schema": hdn.SCHEMA, "status": "ok", "started_at": hdn._iso(built - 0.2),
        "built_at": hdn._iso(built), "started_at_epoch": built - 0.2, "built_at_epoch": built,
        "build_ms": 200, "code_identity": identity, "as_of": (body or _body()).get("as_of"),
        "inputs": {}, "body": body or _body(),
    }
    doc.update(over)
    path.write_text(json.dumps(doc), encoding="utf-8")
    hdn._PARSED.clear()
    return 1000.0 + age_s  # the `now` at which age_s is exact


# ── the store/reader contract ──────────────────────────────────────────────────────────────────────────────────

def test_a_fresh_snapshot_is_served_as_current(paths):
    from lib import home_do_now_snapshot as hdn

    now = _write(paths, age_s=5)
    body, meta = hdn.serve(identity="sha:test", now=now)
    assert body is not None and body["as_of"] == "2026-11-14T16:17:25+00:00"
    assert meta == {"source": "snapshot", "reason": None, "stale": False, "as_of": body["as_of"],
                    "built_at": hdn._iso(1000.0), "age_s": 5.0, "code_identity": "sha:test"}


def test_an_aged_snapshot_is_served_as_last_good_with_its_age(paths):
    from lib import home_do_now_snapshot as hdn

    now = _write(paths, age_s=900)
    body, meta = hdn.serve(identity="sha:test", now=now)
    assert body is not None, "a body inside the last-good window must still be served"
    assert meta["stale"] is True and meta["age_s"] == 900.0
    assert meta["reason"] is None, "aged is not a reason here: stale + age_s is the whole story"


def test_an_expired_snapshot_is_not_served_at_all(paths):
    from lib import home_do_now_snapshot as hdn

    now = _write(paths, age_s=hdn.LAST_GOOD_MAX_S + 1)
    body, meta = hdn.serve(identity="sha:test", now=now)
    assert body is None
    assert meta["source"] == "none" and meta["reason"] == "expired"
    assert meta["age_s"] > hdn.LAST_GOOD_MAX_S


def test_a_body_from_another_release_is_last_good_and_says_so(paths):
    from lib import home_do_now_snapshot as hdn

    now = _write(paths, age_s=30, identity="sha:old-release")
    body, meta = hdn.serve(identity="sha:new-release", now=now)
    assert body is not None, "a deploy must not blank the queue for the minute before the lane's next tick"
    assert meta["stale"] is True and meta["reason"] == "code_mismatch"


def test_a_future_stamp_is_a_clock_problem_not_a_fresh_read(paths):
    from lib import home_do_now_snapshot as hdn

    now = _write(paths, age_s=-60)
    body, meta = hdn.serve(identity="sha:test", now=now)
    assert body is None and meta["reason"] == "clock_skew"


def test_missing_unreadable_corrupt_and_not_ok_are_named(paths):
    from lib import home_do_now_snapshot as hdn

    assert hdn.serve(identity="sha:test", now=1000.0) == (None, {"source": "none", "reason": "missing"})

    paths.write_text("{not json", encoding="utf-8")
    hdn._PARSED.clear()
    assert hdn.read(paths, identity="sha:test", now=1000.0)[1]["reason"] == "corrupt"

    now = _write(paths, age_s=0, status="failed")
    assert hdn.read(paths, identity="sha:test", now=now)[1]["reason"] == "not_ok"

    now = _write(paths, age_s=0, schema="SomethingElse@v1")
    assert hdn.read(paths, identity="sha:test", now=now)[1]["reason"] == "corrupt"

    os.chmod(paths, 0o000)
    try:
        hdn._PARSED.clear()
        reason = hdn.read(paths, identity="sha:test", now=now)[1]["reason"]
        assert reason in ("unreadable", "corrupt"), reason  # root can still read it; either way it is NAMED
    finally:
        os.chmod(paths, 0o600)


# ── there is no compute path in the reader ────────────────────────────────────────────────────────────────────

def test_the_reader_has_no_compute_callable_to_fall_back_to(paths):
    """The property, not a promise: serving cannot build, because there is nothing to call.

    This is the test a future edit cannot pass while reintroducing a build-on-GET: `serve`/`read` take no callable,
    and a missing snapshot returns a reason rather than a body."""
    import inspect

    from lib import home_do_now_snapshot as hdn

    for fn in (hdn.serve, hdn.read):
        params = set(inspect.signature(fn).parameters)
        assert not (params & {"compute", "build", "builder", "fallback", "probe"}), (fn.__name__, params)
    body, meta = hdn.serve(identity="sha:test", now=1000.0)
    assert body is None and meta["reason"] == "missing"


# ── the producer ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_failed_build_leaves_the_previous_snapshot_in_place(paths):
    from lib import home_do_now_snapshot as hdn

    first = hdn.build(lambda: _body(), path=paths, identity="sha:test", clock=lambda: 1000.0)
    assert first["status"] == "ok" and first["bytes"] > 0
    before = paths.read_bytes()

    def boom():
        raise RuntimeError("synthetic producer failure")

    out = hdn.build(boom, path=paths, identity="sha:test", clock=lambda: 2000.0)
    assert out["status"] == "failed" and "synthetic producer failure" in out["error"]
    assert paths.read_bytes() == before, "a failed build must not disturb the body still being served"


def test_a_second_build_while_one_is_in_flight_is_refused(paths):
    from lib import home_do_now_snapshot as hdn

    with open(hdn.lock_path(paths), "a+") as held:
        import fcntl

        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = hdn.build(lambda: _body(), path=paths, identity="sha:test", clock=lambda: 1000.0)
    assert out == {"status": "refused", "reason": "build_in_flight"}
    assert not paths.exists(), "a refused build writes nothing"


def test_the_written_document_carries_the_clocks_the_body_and_its_inputs(paths):
    from lib import home_do_now_snapshot as hdn

    out = hdn.build(lambda: _body(), path=paths, identity="sha:test", clock=lambda: 1000.0,
                    state_dir=None)
    doc = json.loads(paths.read_text())
    assert doc["schema"] == hdn.SCHEMA and doc["status"] == "ok"
    assert doc["code_identity"] == "sha:test" and doc["as_of"] == "2026-11-14T16:17:25+00:00"
    assert doc["built_at_epoch"] == 1000.0 and doc["started_at_epoch"] <= doc["built_at_epoch"]
    assert isinstance(doc["body"], dict) and doc["body"]["schema"] == "HomeDoNow@v1"
    assert out["as_of"] == doc["as_of"]


# ── authorization recheck ────────────────────────────────────────────────────────────────────────────────────

GATED = {"id": "proposals:pending", "category": "decide", "severity": "P1", "sources": ["proposals", "inbox"],
         "title": "2 paper proposals waiting", "action": {"label": "Review", "where": "/v3/proposals"}}
OPEN = {"id": "stops:unprotected", "category": "protect", "severity": "P1", "sources": ["risk"],
        "title": "3 positions with no stop", "action": {"label": "Open risk", "where": "/v3/risk"}}


def test_an_anonymous_reader_never_receives_a_principal_gated_item():
    from lib import home_do_now_snapshot as hdn

    body = _body(items=[OPEN, GATED], sources={"proposals": {"status": "OK"}, "risk": {"status": "OK"}})
    out = hdn.reauthorize(body, authorized=False)
    assert [i["id"] for i in out["items"]] == ["stops:unprotected"]
    assert out["counts"]["all"] == 1, "the counts must describe what the caller actually received"
    assert out["sources"]["proposals"] == {"status": "UNAUTHORIZED", "scope_excluded": True}
    assert out["sources"]["risk"] == {"status": "OK"}
    assert out["authorization"]["scope"] == "not_operator"
    assert "proposals" in out["authorization"]["excluded_sources"]
    assert body["items"] == [OPEN, GATED], "the parsed snapshot is shared and must never be mutated"


def test_the_operator_and_the_service_token_receive_the_whole_queue():
    from lib import home_do_now_snapshot as hdn

    body = _body(items=[OPEN, GATED], sources={"proposals": {"status": "OK"}})
    out = hdn.reauthorize(body, authorized=True)
    assert [i["id"] for i in out["items"]] == ["stops:unprotected", "proposals:pending"]
    assert "authorization" not in out


def test_an_unreadable_auth_state_is_not_authorization(monkeypatch):
    """`_home_do_now_can_read_gated` must fail CLOSED: an auth module that cannot be read is 'no', not 'yes'."""
    import api_v2

    monkeypatch.setitem(sys.modules, "lib.home_approvals_api", None)  # `from lib import …` then raises
    assert api_v2._home_do_now_can_read_gated() is False


# ── the named UNKNOWN ───────────────────────────────────────────────────────────────────────────────────────

def test_the_unknown_names_its_owner_and_next_action_and_counts_nothing():
    from lib import home_do_now_snapshot as hdn

    out = hdn.unknown_data({"reason": "expired", "age_s": 4000.0, "built_at": "x", "as_of": "y"})
    assert out["status"] == "UNKNOWN" and out["schema"] == "HomeDoNow@v1"
    assert out["counts"] is None and out["severity_counts"] is None, "an unknown queue is not an empty queue"
    assert out["items"] == [] and out["all_sources_answered"] is False
    assert out["unknown"]["reason"] == "expired"
    assert "home-do-now-snapshot" in out["unknown"]["owner"]
    assert "home-do-now-snapshot" in out["unknown"]["next_action"]
    assert out["unknown"]["snapshot"]["age_s"] == 4000.0


# ── the route: no heavy computation on any GET ──────────────────────────────────────────────────────────────

@pytest.fixture()
def route(paths, monkeypatch):
    """api_v2 with the build instrumented: any call is a failure, and the serve cache is empty."""
    import api_v2

    calls = {"build": 0}

    def _no_build():
        calls["build"] += 1
        raise AssertionError("GET /api/v2/home/do-now RAN THE BUILD — this is the defect the snapshot removes")

    monkeypatch.setattr(api_v2, "_home_do_now_build", _no_build)
    monkeypatch.setattr(api_v2, "_home_do_now_can_read_gated", lambda: False)
    api_v2._HOME_DO_NOW_SERVE_CACHE.clear()
    return api_v2, calls


def test_cold_start_with_no_snapshot_answers_unknown_and_does_not_build(route, paths):
    api_v2, calls = route
    out = api_v2._home_do_now()
    assert calls["build"] == 0
    assert out["status"] == "UNKNOWN" and out["unknown"]["reason"] == "missing"
    assert out["counts"] is None


def test_a_fresh_snapshot_is_served_without_a_build(route, paths):
    from lib import home_do_now_snapshot as hdn

    hdn.build(lambda: _body(items=[OPEN]), path=paths,
              identity=hdn.code_identity(route[0].PROJECT_ROOT))
    out = route[0]._home_do_now()
    assert route[1]["build"] == 0
    assert [i["id"] for i in out["items"]] == ["stops:unprotected"]
    assert out["served"]["source"] == "snapshot" and out["served"]["stale"] is False
    assert out["served"]["as_of"] == "2026-11-14T16:17:25+00:00"


def test_a_cache_miss_that_hits_an_aged_snapshot_serves_last_good_and_does_not_build(route, paths):
    from lib import home_do_now_snapshot as hdn

    doc = {"schema": hdn.SCHEMA, "status": "ok", "started_at_epoch": time.time() - 901,
           "built_at_epoch": time.time() - 900, "built_at": hdn._iso(time.time() - 900),
           "started_at": hdn._iso(time.time() - 901), "build_ms": 1,
           "code_identity": hdn.code_identity(route[0].PROJECT_ROOT), "as_of": _body()["as_of"],
           "inputs": {}, "body": _body(items=[OPEN])}
    paths.write_text(json.dumps(doc))
    hdn._PARSED.clear()
    out = route[0]._home_do_now()
    assert route[1]["build"] == 0
    assert out["served"]["stale"] is True and 895 <= out["served"]["age_s"] <= 905


def test_an_expired_snapshot_answers_unknown_and_does_not_build(route, paths):
    from lib import home_do_now_snapshot as hdn

    doc = {"schema": hdn.SCHEMA, "status": "ok", "started_at_epoch": time.time() - 4001,
           "built_at_epoch": time.time() - 4000, "built_at": hdn._iso(time.time() - 4000),
           "started_at": hdn._iso(time.time() - 4001), "build_ms": 1, "code_identity": "sha:x",
           "as_of": None, "inputs": {}, "body": _body()}
    paths.write_text(json.dumps(doc))
    hdn._PARSED.clear()
    out = route[0]._home_do_now()
    assert route[1]["build"] == 0
    assert out["status"] == "UNKNOWN" and out["unknown"]["reason"] == "expired"


def test_a_corrupt_snapshot_is_a_dependency_failure_answered_without_a_build(route, paths):
    paths.write_text("{ halfwritten")
    out = route[0]._home_do_now()
    assert route[1]["build"] == 0
    assert out["status"] == "UNKNOWN" and out["unknown"]["reason"] == "corrupt"


def test_repeated_polls_are_served_from_the_projected_cache_and_still_do_not_build(route, paths):
    from lib import home_do_now_snapshot as hdn

    hdn.build(lambda: _body(items=[OPEN]), path=paths, identity=hdn.code_identity(route[0].PROJECT_ROOT))
    first = route[0]._home_do_now()
    second = route[0]._home_do_now()
    assert route[1]["build"] == 0
    assert first == second, "the 2 s projected cache must return the same body"
    assert len(route[0]._HOME_DO_NOW_SERVE_CACHE) == 1, "the cache is keyed per principal scope and bounded"


def test_the_producer_build_executes_end_to_end(monkeypatch):
    """Execute api_v2._home_do_now_build() — the call the lane makes — with only the world stubbed.

    Every route test above REPLACES this function (to prove the route never builds), which is also why no test ever
    *ran* it. REVIEW-S2-ACC-CACHE F1: r3's dead write to the removed ``_HOME_DO_NOW_CACHE`` at the end of this
    function was a NameError that killed the lane while the gate stayed green. Stub only ``home_do_now.build``: the
    rest of the function body (imports, the eight-entry probe table) executes for real, so any NameError/AttributeError
    in it is red here. Anchor: S2_READ_MODEL. Mutation that must fail this test: add
    ``_HOME_DO_NOW_CACHE["v"] = 1`` as the last line of ``_home_do_now_build``.
    """
    from lib.data_broker import home_do_now as hdn

    import api_v2

    seen = {}

    def fake_build(probes):
        seen["probes"] = sorted(probes)
        return {"items": [], "sources": {name: {"status": "OK"} for name in probes}}

    monkeypatch.setattr(hdn, "build", fake_build, raising=True)
    body = api_v2._home_do_now_build()
    assert body["items"] == []
    assert seen["probes"] == ["cio", "deploy", "desk_truth", "held", "inbox", "needs_action", "proposals", "risk"]
    assert sorted(body["sources"]) == seen["probes"], "the producer must call build() with its own probe table"


# ── a build that is older than what is on disk never replaces it (ACC-CACHE item 3) ────────────────────────────

def test_an_older_build_never_overwrites_a_newer_valid_snapshot(paths):
    from lib import home_do_now_snapshot as hdn

    hdn.build(lambda: _body(), path=paths, identity="sha:test", clock=lambda: 2000.0)
    newer = paths.read_bytes()
    out = hdn.build(lambda: _body(items=[OPEN]), path=paths, identity="sha:test", clock=lambda: 1000.0)
    assert out["status"] == "refused" and out["reason"] == "newer_build_present", out
    assert paths.read_bytes() == newer, "a build that started earlier must not clobber the newer body"
    body, meta = hdn.serve(identity="sha:test", now=2001.0)
    assert body is not None and meta["age_s"] == 1.0


def test_a_build_clocked_equal_to_the_file_is_refused_not_rewritten(paths):
    from lib import home_do_now_snapshot as hdn

    hdn.build(lambda: _body(), path=paths, identity="sha:test", clock=lambda: 2000.0)
    before = paths.read_bytes()
    out = hdn.build(lambda: _body(), path=paths, identity="sha:test", clock=lambda: 2000.0)
    assert out["status"] == "refused" and out["reason"] == "newer_build_present"
    assert paths.read_bytes() == before


def test_the_guard_reads_a_document_older_than_itself_as_replaceable(paths):
    from lib import home_do_now_snapshot as hdn

    hdn.build(lambda: _body(), path=paths, identity="sha:test", clock=lambda: 1000.0)
    out = hdn.build(lambda: _body(items=[OPEN]), path=paths, identity="sha:test", clock=lambda: 2000.0)
    assert out["status"] == "ok", out
    body, _ = hdn.serve(identity="sha:test", now=2001.0)
    assert [i["id"] for i in body["items"]] == ["stops:unprotected"]


def test_a_corrupt_file_does_not_block_a_good_build(paths):
    from lib import home_do_now_snapshot as hdn

    paths.write_text("{ halfwritten")
    out = hdn.build(lambda: _body(), path=paths, identity="sha:test", clock=lambda: 1000.0)
    assert out["status"] == "ok"


# ── ACC-CACHE item 3: no dependency in the read path, no invented clock, bounded scope and state ─────────────

def test_the_reader_module_imports_no_database_or_cache_client():
    """A DB or Valkey outage cannot cost the read, because the reader has no client to fail.

    Static, not behavioural: the module's own import list is the proof. (The producer may use both; the GET may not.)"""
    import ast

    from lib import home_do_now_snapshot as hdn

    tree = ast.parse(Path(hdn.__file__).read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    forbidden = {"psycopg2", "psycopg", "redis", "valkey", "sqlite3", "requests", "urllib", "http", "socket"}
    assert not (mods & forbidden), (mods & forbidden)
    assert mods <= {"__future__", "fcntl", "json", "os", "time", "datetime", "pathlib", "typing", "lib", "scripts"}, mods


def test_a_read_invents_no_timestamp(paths):
    """The served clock is the producer's. A read that has nothing to serve says so; it does not stamp `now`."""
    from lib import home_do_now_snapshot as hdn

    now = _write(paths, age_s=7, body=_body(as_of="2026-11-14T16:17:25+00:00"))
    body, meta = hdn.serve(identity="sha:test", now=now)
    assert body["as_of"] == "2026-11-14T16:17:25+00:00" and meta["as_of"] == body["as_of"]
    assert meta["built_at"] == hdn._iso(1000.0), "meta.built_at is the producer's, not the reader's clock"

    unknown = hdn.unknown_data({"reason": "missing"})
    assert unknown["as_of"] is None, "an unknown queue carries no clock at all"
    assert unknown["sources"] == {} and unknown["numbers"] == {"status": "UNAVAILABLE"}


def test_a_half_written_temp_file_is_never_read(paths):
    """The producer writes .name.pid.tmp then renames: an interrupted refresh leaves a tmp file, not a broken body."""
    from lib import home_do_now_snapshot as hdn

    now = _write(paths, age_s=5)
    tmp = paths.with_name(f".{paths.name}.99999.tmp")
    tmp.write_text("{ interrupted")
    body, meta = hdn.serve(identity="sha:test", now=now)
    assert body is not None and meta["reason"] is None, "the reader reads the final path only"
    tmp.unlink()


def test_the_serve_cache_cannot_leak_an_operator_body_to_an_anonymous_reader(route, paths):
    from lib import home_do_now_snapshot as hdn

    hdn.build(lambda: _body(items=[OPEN, GATED], sources={"proposals": {"status": "OK"}}), path=paths,
              identity=hdn.code_identity(route[0].PROJECT_ROOT))
    api_v2 = route[0]
    seen = []
    for authorized in (True, False, True, False):
        route[0]._home_do_now_can_read_gated = lambda a=authorized: a
        out = api_v2._home_do_now()
        seen.append((authorized, tuple(i["id"] for i in out["items"])))
    assert seen[0] == (True, ("stops:unprotected", "proposals:pending"))
    assert seen[1] == (False, ("stops:unprotected",)), "an anonymous reader must never be served the operator body"
    assert seen[2][1] == seen[0][1] and seen[3][1] == seen[1][1]
    assert len(api_v2._HOME_DO_NOW_SERVE_CACHE) <= 2, "one entry per principal scope, nothing unbounded"


def test_the_serve_cache_never_outlives_its_window(paths):
    """Two seconds, not the lane's minute: a rebuilt snapshot is visible on the next poll after that."""
    import api_v2

    assert 0 < api_v2._HOME_DO_NOW_SERVE_CACHE_S <= 5
