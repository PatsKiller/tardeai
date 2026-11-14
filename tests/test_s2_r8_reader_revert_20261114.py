"""ANCHOR: S2_R8_READER_REVERT_20261114 — R8 restores the R6 inline fallback for /api/v2/overview and /api/v2/home/do-now.

INC-OVW-20261114 (Sat 2026-11-14): R7's stored-only overview reader (ACC-CACHE r4, 0eb740a8b + 979ffb34f) served
only a projection inside a 1800 s last-good window and otherwise answered UNKNOWN with every number null. The lane
that writes the projection runs weekdays 04:00-20:59 ET, so on Saturday the header went blank: the projection on
disk was 63,686 s old. LEAD-RULING-R8-base-after-R7-rollback-20261114T1951Z: R8 reverts the reader behaviour
and keeps only the producer-side guards that do not depend on the reader. The stored-only reader returns only
with the INC-OVW permanent fix (24/7 n8n schedule plus admission test).

Pinned here:
* an aged projection (just past MAX_AGE_S, and the incident's 63,686 s) and a missing one are answered by the
  inline compute, with ``_projection.reason`` naming why: never null, never UNKNOWN;
* the route hands ``serve`` the real compute (``_overview_with_today_move``), not ``None``, and running it on an
  aged synthetic projection returns the computed body;
* the producer guard R8 keeps: a build never moves the projection file backwards;
* /api/v2/home/do-now is the R6 stale-while-revalidate route again: no snapshot reader, a first read builds, a
  stale read is served with its age while one background refresh is kicked.

Every fixture is synthetic: a scratch projection path, stubbed compute and build functions. No DB, no network.
"""
from __future__ import annotations

import ast
import inspect
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import overview_projection as op  # noqa: E402

ANCHOR = "S2_R8_READER_REVERT_20261114"
IDENT = "sha:r8-revert-test"
T0 = 1_800_000_000.0
INCIDENT_AGE_S = 63_686.0  # the age of the projection the R7 reader refused on Sat 2026-11-14 14:40 ET


@pytest.fixture(autouse=True)
def _clear_parse_cache():
    op._PARSED.clear()
    yield
    op._PARSED.clear()


def _build(path: Path, *, built_at: float = T0, value: float = 1.0) -> Path:
    out = op.build(lambda: {"portfolio_value": value, "as_of": "2026-11-13T20:59:00Z"}, path=path, identity=IDENT,
                   clock=lambda: built_at, state_dir=None)
    assert out["status"] == "ok", out
    return path


def _computed():
    calls: list[int] = []

    def compute():
        calls.append(1)
        return {"portfolio_value": 42.0, "status": "OK"}

    return compute, calls


# ── the reader: aged or missing -> inline, named ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("age_s", [op.MAX_AGE_S + 0.5, INCIDENT_AGE_S])
def test_an_aged_projection_is_answered_inline_with_the_reason(tmp_path, age_s):
    path = _build(tmp_path / "overview_projection.json")
    compute, calls = _computed()
    out = op.serve(compute, path=path, identity=IDENT, invalidated_at_fn=lambda: None, now=T0 + age_s)
    assert calls == [1], "an aged projection must fall back to the inline compute"
    assert out["portfolio_value"] == 42.0 and out.get("status") != "UNKNOWN"
    assert out["_projection"] == {"source": "inline", "reason": "aged"}


def test_a_missing_projection_is_answered_inline_with_the_reason(tmp_path):
    compute, calls = _computed()
    out = op.serve(compute, path=tmp_path / "absent.json", identity=IDENT, invalidated_at_fn=lambda: None, now=T0)
    assert calls == [1]
    assert out["portfolio_value"] == 42.0
    assert out["_projection"] == {"source": "inline", "reason": "missing"}


def test_a_fresh_projection_is_served_without_computing(tmp_path):
    path = _build(tmp_path / "overview_projection.json")
    out = op.serve(lambda: pytest.fail("computed inline under a fresh projection"), path=path, identity=IDENT,
                   invalidated_at_fn=lambda: None, now=T0 + 10)
    assert out["portfolio_value"] == 1.0 and out["_projection"]["source"] == "projection"


def test_the_reader_has_no_stored_only_window():
    """The R7 names that made the reader stored-only are gone from the module R8 serves."""
    assert not hasattr(op, "LAST_GOOD_MAX_S")
    assert not hasattr(op, "unknown_body")
    assert "last_good_max_s" not in inspect.signature(op.serve).parameters


# ── the route ───────────────────────────────────────────────────────────────────────────────────────────────────

def _overview_served_serve_call() -> ast.Call:
    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_overview_served")
    return next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "serve")


def test_the_route_hands_serve_the_inline_compute_not_none():
    call = _overview_served_serve_call()
    assert call.args, "serve() must receive the compute positionally, as R6 did"
    first = call.args[0]
    assert isinstance(first, ast.Name) and first.id == "_overview_with_today_move", ast.unparse(first)


def test_the_route_computes_inline_over_an_aged_projection(tmp_path, monkeypatch):
    import api_v2

    if api_v2._overview_projection is None:  # pragma: no cover -- the module ships with the route
        pytest.fail("lib.overview_projection did not import beside api_v2")
    path = _build(tmp_path / "overview_projection.json", built_at=time.time() - INCIDENT_AGE_S)
    monkeypatch.setenv(op.PATH_ENV, str(path))
    monkeypatch.setattr(api_v2, "_OVERVIEW_CODE_IDENTITY", [IDENT])
    monkeypatch.setattr(api_v2._overview_projection, "invalidation_reader", lambda *_a, **_k: (lambda: None))
    monkeypatch.setattr(api_v2, "_overview_with_today_move", lambda: {"portfolio_value": 7.0, "status": "OK"})
    out = api_v2._overview_served()
    assert out["portfolio_value"] == 7.0 and out.get("status") != "UNKNOWN"
    assert out["_projection"] == {"source": "inline", "reason": "aged"}


# ── the producer guard R8 keeps (reader-independent) ────────────────────────────────────────────────────────────

def test_an_older_build_never_overwrites_a_newer_projection(tmp_path):
    path = _build(tmp_path / "overview_projection.json", built_at=T0)
    newer = path.read_bytes()
    out = op.build(lambda: {"portfolio_value": 999.0}, path=path, identity=IDENT, clock=lambda: T0 - 30,
                   state_dir=None)
    assert out["status"] == "refused" and out["reason"] == "newer_build_present", out
    assert path.read_bytes() == newer


def test_a_newer_build_replaces_an_older_projection(tmp_path):
    path = _build(tmp_path / "overview_projection.json", built_at=T0 - 30)
    out = op.build(lambda: {"portfolio_value": 2.0}, path=path, identity=IDENT, clock=lambda: T0, state_dir=None)
    assert out["status"] == "ok", out
    body, _ = op.read(path, identity=IDENT, invalidated_at=None, now=T0 + 1)
    assert body["portfolio_value"] == 2.0


# ── /api/v2/home/do-now: the R6 stale-while-revalidate route ────────────────────────────────────────────────────

def test_do_now_route_has_no_snapshot_reader():
    import api_v2

    src = inspect.getsource(api_v2._home_do_now)
    assert "_snap.serve(" not in src and "home_do_now_snapshot" not in src
    assert not hasattr(api_v2, "_HOME_DO_NOW_SERVE_CACHE")


def test_do_now_first_read_builds(monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "_HOME_DO_NOW_CACHE", {})
    monkeypatch.setattr(api_v2, "_home_do_now_build", lambda: {"status": "OK", "counts": {"total": 1}})
    out = api_v2._home_do_now()
    assert out == {"status": "OK", "counts": {"total": 1}}


def test_do_now_stale_read_is_served_with_its_age_and_kicks_one_refresh(monkeypatch):
    import api_v2

    kicked: list[int] = []
    monkeypatch.setattr(api_v2, "_HOME_DO_NOW_CACHE", {"v": (time.monotonic() - 120, {"status": "OK"})})
    monkeypatch.setattr(api_v2, "_home_do_now_refresh_in_background", lambda: kicked.append(1))
    monkeypatch.setattr(api_v2, "_home_do_now_build", lambda: pytest.fail("a stale read must not build inline"))
    out = api_v2._home_do_now()
    assert kicked == [1]
    assert out["status"] == "OK" and out["served"]["stale"] is True and out["served"]["age_s"] >= 120
