"""LQ-20261107-1612: /api/v2/overview reads a precomputed projection, and falls back inline, never blank.

The projection is built out of process by ``scripts/build_overview_projection.py`` (lane overview-projection)
and read by ``scripts/lib/overview_projection.serve`` in front of ``_overview_with_today_move``. Every fixture
here is synthetic.
"""
from __future__ import annotations

import ast
import fcntl
import json
import math
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import overview_projection as op  # noqa: E402

IDENT = "sha:1111111111111111111111111111111111111111"
T0 = 1_800_000_000.0


def _body(value: float = 1000.5) -> dict:
    return {"portfolio_value": value, "position_count": 3, "today_move": {"status": "OK", "change": 1.25}}


def _build(path: Path, *, body=None, clock=lambda: T0, identity=IDENT, state_dir=None) -> dict:
    return op.build(lambda: body if body is not None else _body(), path=path, identity=identity,
                    clock=clock, state_dir=state_dir)


# ----------------------------------------------------------------------------- fail-before: the route

def _route_target_name() -> str:
    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "/api/v2/overview" and isinstance(v, ast.Lambda):
                    call = v.body
                    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    return call.func.id
    raise AssertionError("no /api/v2/overview route lambda in api_v2.py")


def test_overview_route_reads_the_projection_before_computing_inline():
    """FAIL-BEFORE: the route called _overview_with_today_move directly, every request, cold or warm."""
    name = _route_target_name()
    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    src = ast.unparse(fn)
    assert "overview_projection" in src and ".serve(" in src, f"{name} does not read the projection"
    assert "_overview_with_today_move" in src, "the inline fallback must stay the same code path"


def test_api_v2_registers_the_overview_write_invalidation():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert "register_write_invalidation(" in src


# ----------------------------------------------------------------------------- the reader matrix

def test_fresh_projection_is_served_with_its_age(tmp_path):
    p = tmp_path / "overview_projection.json"
    assert _build(p)["status"] == "ok"
    body, meta = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 30)
    assert meta == {"source": "projection", "built_at": meta["built_at"], "age_s": 30.0}
    assert body["portfolio_value"] == 1000.5 and body["_projection"]["source"] == "projection"


@pytest.mark.parametrize("now, reason", [(T0 + op.MAX_AGE_S + 0.5, "aged"), (T0 - 60, "clock_skew")])
def test_aged_or_future_projection_falls_back(tmp_path, now, reason):
    p = tmp_path / "overview_projection.json"
    _build(p)
    body, meta = op.read(p, identity=IDENT, invalidated_at=None, now=now)
    assert body is None and meta == {"source": "inline", "reason": reason}


def test_projection_from_another_release_falls_back(tmp_path):
    p = tmp_path / "overview_projection.json"
    _build(p, identity="sha:2222222222222222222222222222222222222222")
    body, meta = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 5)
    assert body is None and meta["reason"] == "code_mismatch"


def test_a_write_after_the_build_started_falls_back(tmp_path):
    """An operator write at T0+1 lands after a build that STARTED at T0: that body predates the write."""
    p = tmp_path / "overview_projection.json"
    _build(p)
    body, meta = op.read(p, identity=IDENT, invalidated_at=T0 + 1, now=T0 + 5)
    assert body is None and meta["reason"] == "invalidated"
    body, meta = op.read(p, identity=IDENT, invalidated_at=T0 - 1, now=T0 + 5)
    assert body is not None and meta["source"] == "projection"


@pytest.mark.parametrize("content, reason", [
    ("{not json", "corrupt"),
    (json.dumps({"schema": "Other@v9", "body": {}}), "corrupt"),
    (json.dumps({"schema": op.SCHEMA, "status": "ok", "body": []}), "corrupt"),
    (json.dumps({"schema": op.SCHEMA, "status": "failed", "body": {}}), "not_ok"),
])
def test_corrupt_projection_falls_back_with_the_reason(tmp_path, content, reason):
    p = tmp_path / "overview_projection.json"
    p.write_text(content, encoding="utf-8")
    body, meta = op.read(p, identity=IDENT, invalidated_at=None, now=T0)
    assert body is None and meta["reason"] == reason


def test_missing_projection_falls_back(tmp_path):
    body, meta = op.read(tmp_path / "nope.json", identity=IDENT, invalidated_at=None, now=T0)
    assert body is None and meta == {"source": "inline", "reason": "missing"}


def test_serve_never_blank_inline_body_names_the_reason(tmp_path):
    calls = []

    def compute():
        calls.append(1)
        return _body(7.0)

    out = op.serve(compute, path=tmp_path / "missing.json", identity=IDENT, invalidated_at_fn=lambda: None,
                   now=T0)
    assert calls == [1] and out["portfolio_value"] == 7.0
    assert out["_projection"] == {"source": "inline", "reason": "missing"}


def test_serve_prefers_a_fresh_projection_and_does_not_compute(tmp_path):
    p = tmp_path / "overview_projection.json"
    _build(p)
    out = op.serve(lambda: pytest.fail("computed inline under a fresh projection"), path=p, identity=IDENT,
                   invalidated_at_fn=lambda: None, now=T0 + 10)
    assert out["_projection"]["source"] == "projection" and out["portfolio_value"] == 1000.5


def test_unreadable_invalidation_record_is_inline_never_a_pre_write_body(tmp_path):
    p = tmp_path / "overview_projection.json"
    _build(p)

    def boom():
        raise OSError("swr dir unreadable")

    out = op.serve(lambda: _body(3.0), path=p, identity=IDENT, invalidated_at_fn=boom, now=T0 + 5)
    assert out["_projection"] == {"source": "inline", "reason": "invalidation_unreadable"}


def test_served_projection_is_a_fresh_top_level_dict_each_read(tmp_path):
    p = tmp_path / "overview_projection.json"
    _build(p)
    a, _ = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 1)
    a["portfolio_value"] = -1
    b, _ = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 2)
    assert b["portfolio_value"] == 1000.5 and b["_projection"] == {"source": "projection", "built_at": a["_projection"]["built_at"]}


def test_served_body_is_byte_identical_across_reads_so_etags_hold(tmp_path):
    p = tmp_path / "overview_projection.json"
    _build(p)
    a, ma = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 1)
    b, mb = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 100)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert (ma["age_s"], mb["age_s"]) == (1.0, 100.0)


# ----------------------------------------------------------------------------- the builder

def test_build_writes_the_envelope_atomically_0600(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "holdings.json").write_text("{}", encoding="utf-8")
    p = tmp_path / "runtime" / "overview_projection.json"
    ticks = iter([T0, T0 + 2.5])
    s = _build(p, clock=lambda: next(ticks), state_dir=state)
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert s["status"] == "ok" and doc["schema"] == op.SCHEMA and doc["status"] == "ok"
    assert doc["started_at_epoch"] == T0 and doc["built_at_epoch"] == T0 + 2.5 and doc["build_ms"] == 2500
    assert doc["code_identity"] == IDENT and doc["body"] == _body()
    assert set(doc["inputs"]) == set(op.INPUT_FILES) and doc["inputs"]["holdings.json"] is not None
    assert doc["inputs"]["trade_journal.json"] is None
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert [x.name for x in p.parent.iterdir() if x.name.endswith(".tmp")] == []


def test_a_failed_build_keeps_the_previous_projection(tmp_path):
    p = tmp_path / "overview_projection.json"
    _build(p)
    before = p.read_bytes()

    def broken():
        raise RuntimeError("db unreachable")

    s = op.build(broken, path=p, identity=IDENT, clock=lambda: T0 + 60)
    assert s["status"] == "failed" and "RuntimeError: db unreachable" in s["error"]
    assert p.read_bytes() == before


def test_an_overlapping_build_is_refused_not_queued(tmp_path):
    p = tmp_path / "overview_projection.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(op.lock_path(p), "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        s = op.build(lambda: pytest.fail("built under a held lock"), path=p, identity=IDENT, clock=lambda: T0)
    assert s == {"status": "refused", "reason": "build_in_flight"}
    assert not p.exists()


def test_parity_the_projection_body_is_the_inline_body_on_the_wire(tmp_path):
    """The served bytes equal what the server would serialize inline: default=str, NaN as null."""
    from datetime import date
    from decimal import Decimal

    inline = {"portfolio_value": Decimal("12.50"), "as_of": date(2026, 11, 9), "beta": math.nan,
              "rows": [{"v": math.inf}], "n": 3}
    p = tmp_path / "overview_projection.json"
    _build(p, body=inline)
    served, _ = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 1)
    served.pop("_projection")
    assert served == op.to_wire(inline)
    assert served == {"portfolio_value": "12.50", "as_of": "2026-11-09", "beta": None, "rows": [{"v": None}], "n": 3}


def test_a_body_that_is_not_a_dict_is_a_failed_build(tmp_path):
    p = tmp_path / "overview_projection.json"
    s = op.build(lambda: ["x"], path=p, identity=IDENT, clock=lambda: T0)
    assert s["status"] == "failed" and not p.exists()


# ----------------------------------------------------------------------------- identity, path, invalidation

def test_code_identity_reads_the_release_build_sha(tmp_path):
    (tmp_path / "BUILD_SHA").write_text("abc123\n", encoding="utf-8")
    assert op.code_identity(tmp_path) == "sha:abc123"
    other = tmp_path / "dev"
    other.mkdir()
    assert op.code_identity(other) == "path:" + str(other.resolve())


def test_projection_path_honours_the_override(tmp_path, monkeypatch):
    monkeypatch.setenv(op.PATH_ENV, str(tmp_path / "x.json"))
    assert op.projection_path() == tmp_path / "x.json"
    monkeypatch.delenv(op.PATH_ENV)
    assert op.projection_path(tmp_path) == tmp_path / "data" / "runtime" / "overview_projection.json"


def test_operator_writes_invalidate_the_overview(monkeypatch):
    from lib import stale_serve

    monkeypatch.setattr(stale_serve, "WRITE_INVALIDATES", dict(stale_serve.WRITE_INVALIDATES))
    op.register_write_invalidation(stale_serve)
    op.register_write_invalidation(stale_serve)  # idempotent

    class Srv:
        def __init__(self):
            self.paths = []

        def invalidate(self, path):
            self.paths.append(path)

    monkeypatch.setenv("TRADEAI_SWR", "1")
    for post in ("/api/v2/approvals/123/approve", "/api/v2/notifications/ack", "/api/v2/holdings/sync",
                 "/api/v2/trade-journal/entry", "/api/v2/pipeline/run"):
        srv = Srv()
        assert op.ROUTE in stale_serve.invalidate_for_write(post, server=srv), post
        assert op.ROUTE in srv.paths
    srv = Srv()
    assert op.ROUTE not in stale_serve.invalidate_for_write("/api/v2/watchlist/items/add", server=srv)


def test_write_tracking_off_means_inline(tmp_path, monkeypatch):
    """TRADEAI_SWR=0 turns off invalidate_for_write, so no write is tracked: never serve a projection."""
    monkeypatch.setenv("TRADEAI_SWR", "0")
    p = tmp_path / "overview_projection.json"
    _build(p)
    assert op.invalidation_reader()() is op.WRITE_TRACKING_OFF
    out = op.serve(lambda: _body(1.0), path=p, identity=IDENT, invalidated_at_fn=op.invalidation_reader(),
                   now=T0 + 1)
    assert out["_projection"] == {"source": "inline", "reason": "write_tracking_off"}


# ----------------------------------------------------------------------------- the lane script

def test_builder_dry_run_writes_only_where_told(tmp_path, monkeypatch):
    import build_overview_projection as b

    monkeypatch.setattr(b, "_compute", lambda: (_body(), {"identity": IDENT, "state_dir": None}))
    out = tmp_path / "scratch.json"
    monkeypatch.setattr(b, "_write_receipt", lambda *a, **k: pytest.fail("dry run wrote a receipt"))
    assert b.main(["--out", str(out), "--root", str(tmp_path / "root")]) == 0
    assert json.loads(out.read_text())["body"] == _body()
    assert not (tmp_path / "root" / "data" / "runtime" / "overview_projection.json").exists()


def test_builder_apply_failure_exits_nonzero_and_writes_a_failed_receipt(tmp_path, monkeypatch):
    import build_overview_projection as b

    def broken():
        raise RuntimeError("boom")

    seen = {}
    monkeypatch.setattr(b, "_compute", broken)
    monkeypatch.setattr(b, "_write_receipt", lambda summary: seen.update(summary))
    assert b.main(["--apply", "--root", str(tmp_path)]) == 1
    assert seen["status"] == "failed" and "boom" in seen["error"]


def test_builder_apply_refused_is_a_typed_empty_not_a_failure(tmp_path, monkeypatch):
    import build_overview_projection as b

    monkeypatch.setattr(b, "_compute", lambda: (_body(), {"identity": IDENT, "state_dir": None}))
    seen = {}
    monkeypatch.setattr(b, "_write_receipt", lambda summary: seen.update(summary))
    p = tmp_path / "data" / "runtime" / "overview_projection.json"
    p.parent.mkdir(parents=True)
    with open(op.lock_path(p), "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert b.main(["--apply", "--root", str(tmp_path)]) == 0
    assert seen["status"] == "refused" and seen["reason"] == "build_in_flight"


def test_builder_forces_a_read_only_db_session(monkeypatch):
    import build_overview_projection as b

    monkeypatch.delenv("PGOPTIONS", raising=False)
    b._force_read_only_db()
    assert "default_transaction_read_only=on" in os.environ["PGOPTIONS"]
    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=5000")
    b._force_read_only_db()
    assert os.environ["PGOPTIONS"] == "-c statement_timeout=5000 -c default_transaction_read_only=on"
