"""S2 item 2 (operator 2026-11-14): /api/v2/overview never computes on a GET.

Measured live 2026-11-14 16:22Z: the route answered in 1.43 s with ``_projection: {"source": "inline", "reason":
"code_mismatch"}`` — the file on disk was built by the previous release, so every GET ran the inline compute. The
reader now answers three ways and never a fourth:

* current — same release, inside MAX_AGE_S, no later operator write;
* LAST-KNOWN-GOOD with its age and a named reason (``aged`` / ``invalidated`` / ``code_mismatch`` /
  ``write_tracking_off``);
* NAMED UNKNOWN when nothing may be served at all (missing / corrupt / not_ok / clock skew / past LAST_GOOD_MAX_S):
  ``status: UNKNOWN``, every number null, ``gap.owner`` + ``gap.next_action``.

There is no compute path: ``serve(compute)`` accepts a callable for call-site compatibility and never calls it.

Anchor: S2_READ_MODEL (config/ci_gates/S2_READ_MODEL_20261114.json).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

ANCHOR = "S2_READ_MODEL"
NOW = 10_000.0
IDENT = "sha:test-release"


@pytest.fixture(autouse=True)
def _clear():
    from lib import overview_projection as op

    op._PARSED.clear()
    yield
    op._PARSED.clear()


def _build(tmp_path, *, built_at=NOW - 10.0, identity=IDENT, body=None):
    from lib import overview_projection as op

    path = tmp_path / "overview_projection.json"
    out = op.build(lambda: body if body is not None else {"portfolio_value": 1.0, "as_of": "2026-11-14T16:00:00Z"},
                   path=path, identity=identity, clock=lambda: built_at, state_dir=None)
    assert out["status"] == "ok", out
    return path


def _read(path, *, now=NOW, invalidated_at=None, identity=IDENT):
    from lib import overview_projection as op

    return op.read(path, identity=identity, invalidated_at=invalidated_at, now=now)


def test_a_current_projection_carries_fresh_and_no_reason(tmp_path):
    path = _build(tmp_path, built_at=NOW - 10)
    body, meta = _read(path)
    assert body["portfolio_value"] == 1.0
    assert body["_projection"] == {"source": "projection", "built_at": meta["built_at"], "stale": False, "reason": None}
    assert meta["stale"] is False and meta["age_s"] == 10.0


def test_an_aged_projection_is_served_stale_with_its_age(tmp_path):
    from lib import overview_projection as op

    path = _build(tmp_path, built_at=NOW - (op.MAX_AGE_S + 100))
    body, meta = _read(path)
    assert body is not None, "past MAX_AGE_S the body is last-known-good, not a compute"
    assert meta["stale"] is True and meta["reason"] == "aged"
    assert meta["age_s"] == op.MAX_AGE_S + 100


def test_a_write_after_the_build_is_served_stale_not_recomputed(tmp_path):
    path = _build(tmp_path, built_at=NOW - 10)
    body, meta = _read(path, invalidated_at=NOW - 5)
    assert body is not None and meta["stale"] is True and meta["reason"] == "invalidated"


def test_a_body_from_another_release_is_last_good_and_says_so(tmp_path):
    path = _build(tmp_path, identity="sha:previous-release")
    body, meta = _read(path, identity=IDENT)
    assert body is not None and meta["stale"] is True and meta["reason"] == "code_mismatch"


def test_write_tracking_off_serves_last_good_labelled(tmp_path):
    from lib import overview_projection as op

    path = _build(tmp_path, built_at=NOW - 10)
    body, meta = _read(path, invalidated_at=op.WRITE_TRACKING_OFF)
    assert body is not None and meta["stale"] is True and meta["reason"] == "write_tracking_off"


def test_past_the_last_good_window_nothing_is_served(tmp_path):
    from lib import overview_projection as op

    path = _build(tmp_path, built_at=NOW - (op.LAST_GOOD_MAX_S + 1))
    body, meta = _read(path)
    assert body is None and meta["source"] == "none" and meta["reason"] == "expired"


def test_missing_corrupt_and_foreign_files_are_named(tmp_path):
    from lib import overview_projection as op

    missing = tmp_path / "nope.json"
    assert op.read(missing, identity=IDENT, invalidated_at=None, now=NOW)[1]["reason"] == "missing"

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{nope")
    op._PARSED.clear()
    assert op.read(corrupt, identity=IDENT, invalidated_at=None, now=NOW)[1]["reason"] == "corrupt"

    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"schema": "Other@v1", "status": "ok", "body": {}, "started_at_epoch": 1,
                                   "built_at_epoch": 1}))
    op._PARSED.clear()
    assert op.read(foreign, identity=IDENT, invalidated_at=None, now=NOW)[1]["reason"] == "corrupt"


def test_a_future_stamp_is_a_clock_problem(tmp_path):
    path = _build(tmp_path, built_at=NOW + 60)
    assert _read(path)[1]["reason"] == "clock_skew"


# ── serve(): never computes, and answers the named UNKNOWN when it must ────────────────────────────────────

def test_serve_never_calls_the_compute_callable_it_is_handed(tmp_path):
    from lib import overview_projection as op

    path = _build(tmp_path, built_at=NOW - 10)
    called = {"n": 0}

    def compute():
        called["n"] += 1
        return {"portfolio_value": 999.0}

    body = op.serve(compute, path=path, identity=IDENT, invalidated_at_fn=lambda: None, now=NOW)
    assert called["n"] == 0, "serve must never compute, even when handed the old inline callable"
    assert body["portfolio_value"] == 1.0


def test_serve_answers_the_named_unknown_instead_of_computing(tmp_path):
    from lib import overview_projection as op

    called = {"n": 0}

    def compute():
        called["n"] += 1
        return {"portfolio_value": 999.0}

    body = op.serve(compute, path=tmp_path / "missing.json", identity=IDENT,
                    invalidated_at_fn=lambda: None, now=NOW)
    assert called["n"] == 0
    assert body["status"] == "UNKNOWN" and body["unavailable"] is True
    assert body["portfolio_value"] is None and body["total_cash"] is None, "no fabricated figures"
    assert body["gap"]["reason"] == "missing"
    assert "overview-projection" in body["gap"]["owner"]
    assert "overview-projection" in body["gap"]["next_action"]
    assert body["_projection"] == {"source": "unknown", "reason": "missing", "age_s": None, "built_at": None}


def test_an_unreadable_invalidation_record_never_shows_a_current_body(tmp_path):
    from lib import overview_projection as op

    path = _build(tmp_path, built_at=NOW - 10)

    def boom():
        raise RuntimeError("stale_serve unavailable")

    body = op.serve(None, path=path, identity=IDENT, invalidated_at_fn=boom, now=NOW)
    assert body["_projection"]["stale"] is True, "a write may have landed; the body is last-good, not current"


def test_is_servable_covers_the_last_good_window_not_only_the_fresh_one(tmp_path):
    from lib import overview_projection as op

    fresh = _build(tmp_path / "a", built_at=NOW - 10)
    aged = _build(tmp_path / "b", built_at=NOW - (op.MAX_AGE_S + 100))
    gone = _build(tmp_path / "c", built_at=NOW - (op.LAST_GOOD_MAX_S + 1))
    assert op.is_servable(fresh, now=NOW) and op.is_fresh(fresh, now=NOW)
    assert op.is_servable(aged, now=NOW), "an aged body is still a file read: the semaphore exemption must follow it"
    assert not op.is_fresh(aged, now=NOW)
    assert not op.is_servable(gone, now=NOW)


# ── the route ───────────────────────────────────────────────────────────────────────────────────────────────

def test_the_overview_route_never_computes(tmp_path, monkeypatch):
    import time

    import api_v2
    from lib import overview_projection as op

    # the route reads with the real clock (no `now` argument), so the fixture is stamped against real time here
    path = _build(tmp_path, built_at=time.time() - 10)
    monkeypatch.setattr(op, "projection_path", lambda root=None: path)
    monkeypatch.setattr(api_v2, "_OVERVIEW_CODE_IDENTITY", [IDENT])

    called = {"n": 0}

    def compute():
        called["n"] += 1
        return {"portfolio_value": 999.0}

    monkeypatch.setattr(api_v2, "_overview_with_today_move", compute)
    out = api_v2._overview_served()
    assert called["n"] == 0
    assert out["portfolio_value"] == 1.0 and out["_projection"]["stale"] is False

    # and with nothing on disk: the named UNKNOWN, still no compute
    monkeypatch.setattr(op, "projection_path", lambda root=None: tmp_path / "absent.json")
    out = api_v2._overview_served()
    assert called["n"] == 0
    assert out["status"] == "UNKNOWN" and out["portfolio_value"] is None


# ── a build that is older than what is on disk never replaces it (ACC-CACHE item 3) ─────────────────────────────

def test_an_older_build_never_overwrites_a_newer_projection(tmp_path):
    from lib import overview_projection as op

    path = _build(tmp_path, built_at=NOW)
    newer = path.read_bytes()
    out = op.build(lambda: {"portfolio_value": 999.0}, path=path, identity=IDENT, clock=lambda: NOW - 30)
    assert out["status"] == "refused" and out["reason"] == "newer_build_present", out
    assert path.read_bytes() == newer
    body, meta = _read(path)
    assert body["portfolio_value"] == 1.0, "the newer body survives an out-of-order build"


def test_a_newer_build_replaces_an_older_projection(tmp_path):
    from lib import overview_projection as op

    path = _build(tmp_path, built_at=NOW - 30)
    out = op.build(lambda: {"portfolio_value": 2.0, "as_of": "2026-11-14T16:01:00Z"}, path=path,
                   identity=IDENT, clock=lambda: NOW)
    assert out["status"] == "ok"
    body, _ = _read(path)
    assert body["portfolio_value"] == 2.0
