"""Actual delivery aggregate owner with a fake read-only DB; no SQL reaches a server."""

from datetime import datetime, timedelta, timezone
import ast
from pathlib import Path

import pytest
from scripts import communications_portal as C

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def valid():
    return dict(
        unsettled=17,
        failed=9,
        total=1234,
        oldest_unsettled_at=NOW - timedelta(minutes=10),
        as_of=NOW,
        window_start=NOW - timedelta(days=3),
        invalid_clocks=0,
    )


class Connection:
    def __init__(self, row, *, failure=False):
        self.row, self.failure = row, failure
        self.statements, self.rollbacks = [], 0
        self.description = [(k,) for k in (row or valid())]

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql):
        self.statements.append(sql)
        if self.failure:
            raise RuntimeError("sentinel private database detail")

    def fetchone(self):
        return self.row

    def rollback(self):
        self.rollbacks += 1


def invoke(monkeypatch, row, **kw):
    conn = Connection(row, **kw)
    monkeypatch.setattr(C, "_deliveries_db_conn", lambda: conn)
    return C.delivery_summary(), conn


def test_real_aggregate_has_full_retained_coverage_and_ends_read_transaction(monkeypatch):
    result, conn = invoke(monkeypatch, valid())
    assert result["ok"] is True and result["total"] == 1234 and result["unsettled"] == 17
    assert result["oldest_unsettled_age_s"] == 600
    assert result["coverage"] == dict(
        scope="all_retained_rows",
        complete=True,
        window_start=(NOW - timedelta(days=3)).isoformat(),
        window_end=NOW.isoformat(),
    )
    assert len(conn.statements) == 1 and "LIMIT" not in conn.statements[0].upper()
    assert conn.statements[0].startswith("SELECT") and conn.rollbacks == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("total", None),
        ("total", True),
        ("total", -1),
        ("total", 1.5),
        ("unsettled", 1235),
        ("failed", -1),
        ("invalid_clocks", 1),
        ("as_of", None),
        ("as_of", NOW.replace(tzinfo=None)),
        ("window_start", None),
        ("window_start", NOW + timedelta(seconds=1)),
        ("oldest_unsettled_at", None),
        ("oldest_unsettled_at", NOW + timedelta(seconds=1)),
    ],
)
def test_malformed_or_incomplete_aggregate_is_unavailable_not_zero(monkeypatch, field, value):
    row = valid()
    row[field] = value
    result, _ = invoke(monkeypatch, row)
    assert result["status"] == "UNAVAILABLE" and result["ok"] is False
    assert all(result[k] is None for k in ("total", "failed", "unsettled", "as_of"))
    assert result["coverage"]["complete"] is False


@pytest.mark.parametrize("row", [None, {}])
def test_absent_query_row_cannot_become_empty_success(monkeypatch, row):
    result, _ = invoke(monkeypatch, row)
    assert result["ok"] is False and result["total"] is None


def test_explicit_empty_complete_query_is_valid_no_work(monkeypatch):
    row = valid()
    row.update(total=0, unsettled=0, failed=0, window_start=None, oldest_unsettled_at=None)
    result, _ = invoke(monkeypatch, row)
    assert result["ok"] and result["total"] == 0 and result["coverage"]["complete"]


def test_unavailable_db_and_query_error_never_leak_or_fabricate_counts(monkeypatch):
    monkeypatch.setattr(C, "_deliveries_db_conn", lambda: None)
    assert C.delivery_summary()["total"] is None
    result, conn = invoke(monkeypatch, valid(), failure=True)
    assert result["total"] is None and conn.rollbacks == 1
    assert "sentinel" not in str(result)


def test_actual_api_route_delegates_to_same_owner(monkeypatch):
    import sys
    import types

    source = Path(__file__).resolve().parents[1] / "scripts/api_v2.py"
    tree = ast.parse(source.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_communications_delivery_summary")
    marker = {"status": "UNAVAILABLE"}
    fake = types.ModuleType("communications_portal")
    fake.delivery_summary = lambda: marker
    monkeypatch.setitem(sys.modules, "communications_portal", fake)
    ns = {"PROJECT_ROOT": source.parent.parent}
    before = list(sys.path)
    try:
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), "exec"), ns)
        assert ns[fn.name]({}) is marker
    finally:
        sys.path[:] = before
    route = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ROUTES" for t in n.targets)
    )
    entries = {
        k.value: v.id
        for k, v in zip(route.value.keys, route.value.values)
        if isinstance(k, ast.Constant) and isinstance(v, ast.Name)
    }
    assert entries["/api/v2/communications/deliveries/summary"] == fn.name


def test_real_typescript_summary_projection():
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node, "registered CI dependency setup must provide Node 22"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--experimental-strip-types", str(root / "apps/command-center-v3/src/lib/commsDeliveryHealth.test.ts")],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "NODE_OPTIONS": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "19 passed, 0 failed" in result.stdout
