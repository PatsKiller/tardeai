#!/usr/bin/env python3
"""operator_control_contract — every write the UI can issue, and what can be proven.

Static analysis only. This suite never issues a request, never imports an api_v2
handler, and never touches a broker, order, provider, scheduler or production path.

The pins that matter here are the ones that stop the ledger from manufacturing
findings: a control the dispatcher routes through a prefix match, or through a
sibling module, must not be reported as unrouted.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import operator_control_contract as occ  # noqa: E402


@pytest.fixture(scope="module")
def rep():
    return occ.contract()


# ── the ledger is real ───────────────────────────────────────────────────────


def test_the_ledger_finds_controls(rep):
    assert rep["schema"] == "OperatorControlContract@v1"
    assert rep["authority"] == "READ_ONLY_ADVISORY"
    assert rep["control_count"] > 100, "the Command Center has many write controls; found too few"
    assert rep["server_write_route_count"] > 100


def test_every_control_has_a_provability_class(rep):
    allowed = {occ.PROVABLE_HERMETIC, occ.UNPROVABLE_WITHOUT_PRODUCTION_WRITE, occ.OUT_OF_SCOPE_BROKER}
    for c in rep["controls"]:
        assert c["provability"] in allowed
        assert c["provability_reason"]
        assert c["method"] in occ.MUTATING


def test_broker_controls_are_marked_never_invoke(rep):
    broker = [c for c in rep["controls"] if c["provability"] == occ.OUT_OF_SCOPE_BROKER]
    assert broker, "broker-order controls exist in the UI and must be classified"
    for c in broker:
        assert c["must_never_be_invoked"] is True
        assert "AGENTS.md rule 2" in c["provability_reason"]


def test_guarded_controls_name_the_audit_obstruction(rep):
    guarded = [c for c in rep["controls"] if c["provability"] == occ.UNPROVABLE_WITHOUT_PRODUCTION_WRITE]
    assert guarded
    for c in guarded:
        assert "admin_audit_log" in c["provability_reason"]


def test_no_control_uses_a_method_the_server_does_not_route(rep):
    """A UI POST to a path the server only GETs fails as a silent no-op."""
    wrong = [c for c in rep["controls"] if c["route_registered"] and not c["method_correct"]]
    assert wrong == [], f"method mismatch: {[(c['method'], c['path']) for c in wrong]}"


def test_unresolved_controls_are_reported_as_extraction_limits_not_defects(rep):
    """An unmatched path may be a dynamic dispatch this analysis cannot see."""
    for c in rep["controls"]:
        if not c["route_registered"]:
            assert "EXTRACTION RESULT" in c["unregistered_note"]


# ── the extractors do not manufacture findings ───────────────────────────────


def _tmp_api(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "api_stub.py"
    p.write_text(textwrap.dedent(body))
    return p


def test_flat_method_and_path_dispatch_is_found(tmp_path):
    api = _tmp_api(
        tmp_path,
        """
        def handle(path, method="GET", body=None, query=None):
            base_path = path
            if method == "POST" and base_path == "/api/v2/thing/do":
                return 200, {}
            return 404, {}
    """,
    )
    assert occ.server_write_routes(api) == {"/api/v2/thing/do": {"POST"}}


def test_block_form_dispatch_is_found(tmp_path):
    """The shape a regex misses: `if method == "POST":` wrapping bare path tests."""
    api = _tmp_api(
        tmp_path,
        """
        def handle(path, method="GET", body=None, query=None):
            base_path = path
            if method == "POST":
                if base_path == "/api/v2/a/one":
                    return 200, {}
                if base_path == "/api/v2/a/two":
                    return 200, {}
            return 404, {}
    """,
    )
    assert occ.server_write_routes(api) == {
        "/api/v2/a/one": {"POST"},
        "/api/v2/a/two": {"POST"},
    }


def test_prefix_suffix_dispatch_is_found(tmp_path):
    api = _tmp_api(
        tmp_path,
        """
        def handle(path, method="GET", body=None, query=None):
            base_path = path
            if method == "POST":
                if base_path.startswith("/api/v2/watchlist/") and base_path.endswith("/plan"):
                    return 200, {}
            return 404, {}
    """,
    )
    pre = occ.server_write_prefix_routes(api)
    assert ("/api/v2/watchlist/", "/plan") in pre
    assert pre[("/api/v2/watchlist/", "/plan")] == {"POST"}


def test_a_get_only_route_is_not_a_write_route(tmp_path):
    api = _tmp_api(
        tmp_path,
        """
        def handle(path, method="GET", body=None, query=None):
            base_path = path
            if method == "GET" and base_path == "/api/v2/read/only":
                return 200, {}
            return 404, {}
    """,
    )
    assert occ.server_write_routes(api) == {}


def test_frontend_extractor_reads_method_and_body_keys(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Thing.tsx").write_text(
        "const r = await fetch('/api/v2/thing/do', {\n"
        "  method: 'POST', headers: { 'Content-Type': 'application/json' },\n"
        "  body: JSON.stringify({ symbol: s, operator: op, token: t, confirm: true }),\n"
        "})\n"
    )
    rows = occ.frontend_controls(src)
    assert len(rows) == 1
    row = rows[0]
    assert row["method"] == "POST"
    assert row["path"] == "/api/v2/thing/do"
    assert set(row["body_keys"]) >= {"symbol", "operator", "token", "confirm"}
    assert row["sends_operator"] is True
    assert row["sends_token"] is True
    assert row["two_step_confirm"] is True


def test_a_plain_get_is_not_a_control(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Read.tsx").write_text("await fetch('/api/v2/overview', { cache: 'no-store' })\n")
    assert occ.frontend_controls(src) == []


def test_test_files_are_not_scanned_as_controls(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.test.ts").write_text("await fetch('/api/v2/thing', { method: 'POST', body: JSON.stringify({ a: 1 }) })\n")
    assert occ.frontend_controls(src) == []


# ── the module itself writes nothing ─────────────────────────────────────────


def test_the_module_is_read_only():
    src = (ROOT / "scripts" / "lib" / "operator_control_contract.py").read_text()
    for banned in ("requests.post", "urlopen", "subprocess", "write_text", "os.system", "place_order"):
        assert banned not in src, f"read-only module contains {banned}"
    assert occ.AUTHORITY == "READ_ONLY_ADVISORY"
