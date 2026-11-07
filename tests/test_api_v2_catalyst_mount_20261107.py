"""LQ-20261107-135 wiring: api_v2.handle dispatches /api/v3/catalyst to api_v3_catalyst.handle_get (GET only).

The block is cut out of scripts/api_v2.py and run against a stub module, so the test exercises the real
lines without importing the 60k-line router or touching a database.
"""

from __future__ import annotations

import sys
import textwrap
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1].joinpath("scripts/api_v2.py").read_text()
MARK = "# ── /v3/catalyst"


def _block() -> str:
    start = SRC.rindex("\n", 0, SRC.index(MARK)) + 1  # from the start of the line, so dedent sees one indent
    end = SRC.index("\n\n    # ──", start)  # the next section; the block itself holds a blank line
    return textwrap.dedent(SRC[start:end])


def _dispatch(base_path: str, method: str, query):
    ns: dict = {}
    body = textwrap.indent(_block(), "    ")
    exec(f"def _f(base_path, method, query):\n{body}\n    return None\n", ns)  # noqa: S102 -- runs the router's own lines from the repo, no outside input
    return ns["_f"](base_path, method, query)


@pytest.fixture
def stub(monkeypatch):
    calls = []
    mod = types.ModuleType("api_v3_catalyst")

    def handle_get(path, query=None):
        calls.append((path, query))
        return 200, {"ok": True, "path": path}

    mod.handle_get = handle_get
    monkeypatch.setitem(sys.modules, "api_v3_catalyst", mod)
    return calls


def test_the_route_is_mounted_once_before_cio():
    assert SRC.count('base_path.startswith("/api/v3/catalyst")') == 1
    assert SRC.index(MARK) < SRC.index('if base_path.startswith("/api/v3/cio")')


def test_get_reaches_the_reader_with_the_subpath_and_query(stub):
    assert _dispatch("/api/v3/catalyst/impact/", "GET", {"symbol": "ANET"}) == (200, {"ok": True, "path": "impact"})
    assert stub == [("impact", {"symbol": "ANET"})]


def test_a_non_dict_query_becomes_none(stub):
    _dispatch("/api/v3/catalyst", "GET", "symbol=ANET")
    assert stub == [("", None)]


def test_writes_are_refused_without_reaching_the_reader(stub):
    code, body = _dispatch("/api/v3/catalyst/impact", "POST", {})
    assert code == 405 and body["error"] == "method_not_allowed" and stub == []


def test_a_missing_module_is_a_500_never_an_empty_200(monkeypatch):
    monkeypatch.setitem(sys.modules, "api_v3_catalyst", None)  # import now raises ImportError
    code, body = _dispatch("/api/v3/catalyst/impact", "GET", {})
    assert code == 500 and body["ok"] is False


def test_other_paths_fall_through(stub):
    assert _dispatch("/api/v3/cio/plans", "GET", {}) is None and stub == []
