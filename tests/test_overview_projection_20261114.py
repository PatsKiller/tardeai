"""ANCHOR: OVERVIEW_PROJECTION_20261114 — the overview projection lane, its builder and its reader's contract.

R7 blocker (LEAD 2026-11-14T18:46Z). This file is the successor to
``tests/test_overview_projection_20261109.py``, which was archive-moved with its gate to
``archive/s2_overview_20261109_retired_20261114/`` (see the COVERAGE-MAP.md there for the
test-by-test map). That file pinned the pre-S2 meta contract — ``(None, {"source": "inline",
"reason": ...})`` with an inline compute on every miss — which ACC-CACHE r4 replaced by design:
the reader is now LAST-KNOWN-GOOD-or-named-UNKNOWN and ``serve()`` never computes (S2 item 2,
operator 2026-11-14; gate S2_READ_MODEL_20261114).

Of its 26 tests, the 16 that describe behaviour that did not change (builder, identity, path,
parity, invalidation registration, serve-never-computes, ETag byte-identity) are ported here
verbatim; 5 are covered only by ``tests/test_s2_overview_never_inline_20261114.py`` because their
subject changed under the new contract; and 5 are new, restating a behaviour whose shape changed
(the route binding, per-read dict isolation, the no-body cases for a missing file and a future
stamp, the write-tracking-off sentinel, and a write older than the build). No assertion was
weakened: each coverage-map row names the assertion that carries the behaviour.

Every fixture here is synthetic.
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

ANCHOR = "OVERVIEW_PROJECTION_20261114"
IDENT = "sha:1111111111111111111111111111111111111111"
T0 = 1_800_000_000.0



def _body(value: float = 1000.5) -> dict:
    return {"portfolio_value": value, "position_count": 3, "today_move": {"status": "OK", "change": 1.25}}


def _build(path: Path, *, body=None, clock=lambda: T0, identity=IDENT, state_dir=None) -> dict:
    return op.build(lambda: body if body is not None else _body(), path=path, identity=identity,
                    clock=clock, state_dir=state_dir)


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


# ----------------------------------------------------------------------------- the route


def test_the_overview_route_is_bound_to_the_projection_reader():
    """The route table entry resolves to the reader; the inline compute is reachable only on an import failure.

    The retired test asserted the route "reads the projection before computing inline". That is no longer the
    contract (serve() never computes), so the assertion is restated: the target of /api/v2/overview calls
    ``.serve(``, and the only occurrence of the inline compute sits inside the ``_overview_projection is None``
    guard — the import-failure branch. Together with
    ``test_s2_overview_never_inline_20261114.test_the_overview_route_never_computes`` (which runs the target),
    this pins both halves: what the route is bound to, and that running it never computes."""
    name = _route_target_name()
    assert name != "_overview_with_today_move", "the route must not be the inline compute"
    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    src = ast.unparse(fn)
    assert ".serve(" in src, f"{name} does not call the projection reader"
    assert src.count("_overview_with_today_move") == 1, "exactly one inline-compute path may exist"
    before, _, _after = src.partition("_overview_with_today_move")
    assert "_overview_projection is None" in before, "the only inline-compute path must be the import-failure guard"


# ----------------------------------------------------------------------------- the reader matrix


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


def test_read_refuses_a_missing_file_and_a_future_stamp_with_a_named_reason(tmp_path):
    """read() returns no body — and names why — for the two cases the retired file pinned directly.

    Both are still ``(None, reason)`` under the S2 contract; what changed is the label on
    ``meta.source`` (``none``, never ``inline``: nothing is computed here). The missing file's meta is
    compared whole; a clock-skewed read additionally carries the stamps it read."""
    body, meta = op.read(tmp_path / "nope.json", identity=IDENT, invalidated_at=None, now=T0)
    assert body is None and meta == {"source": "none", "reason": "missing"}
    p = tmp_path / "overview_projection.json"
    _build(p)
    body, meta = op.read(p, identity=IDENT, invalidated_at=None, now=T0 - 60)
    assert body is None and meta["source"] == "none" and meta["reason"] == "clock_skew"


# ----------------------------------------------------------------------------- serve()


def test_serve_prefers_a_fresh_projection_and_does_not_compute(tmp_path):
    p = tmp_path / "overview_projection.json"
    _build(p)
    out = op.serve(lambda: pytest.fail("computed inline under a fresh projection"), path=p, identity=IDENT,
                   invalidated_at_fn=lambda: None, now=T0 + 10)
    assert out["_projection"]["source"] == "projection" and out["portfolio_value"] == 1000.5


# ----------------------------------------------------------------------------- per-read isolation and ETags


def test_a_served_projection_is_a_fresh_top_level_dict_each_read(tmp_path):
    """A caller cannot poison the next read by mutating the body it was served (the parsed document is cached)."""
    p = tmp_path / "overview_projection.json"
    _build(p)
    a, _ = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 1)
    built_at = a["_projection"]["built_at"]
    a["portfolio_value"] = -1
    a["_projection"]["stale"] = True
    b, _ = op.read(p, identity=IDENT, invalidated_at=None, now=T0 + 2)
    assert b["portfolio_value"] == 1000.5
    assert b["_projection"] == {"source": "projection", "built_at": built_at, "stale": False, "reason": None}


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


def test_api_v2_registers_the_overview_write_invalidation():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert "register_write_invalidation(" in src


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


def test_write_tracking_off_is_the_sentinel_and_serves_last_good(tmp_path, monkeypatch):
    """TRADEAI_SWR=0 records no write, so the reader says WRITE_TRACKING_OFF and a body is never served as current."""
    monkeypatch.setenv("TRADEAI_SWR", "0")
    p = tmp_path / "overview_projection.json"
    _build(p)
    reader = op.invalidation_reader()
    assert reader() is op.WRITE_TRACKING_OFF
    body, meta = op.read(p, identity=IDENT, invalidated_at=reader(), now=T0 + 1)
    assert body is not None and body["portfolio_value"] == 1000.5
    assert meta["stale"] is True and meta["reason"] == "write_tracking_off"


def test_a_write_older_than_the_build_does_not_downgrade_it(tmp_path):
    """The invalidation cut is compared with the build's START: a write that predates it leaves the body current.

    The retired file asserted this half too (``invalidated_at=T0 - 1`` beside ``= T0 + 1``). Only the
    "a write landed after the build started" half moved to S2, so the other half is restated here — a
    reader that downgraded on ANY recorded write would still pass every S2 test, which pass None or a
    post-build stamp."""
    p = tmp_path / "overview_projection.json"
    _build(p)
    body, meta = op.read(p, identity=IDENT, invalidated_at=T0 - 1, now=T0 + 5)
    assert body is not None and body["portfolio_value"] == 1000.5
    assert meta["stale"] is False and meta["reason"] is None


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
