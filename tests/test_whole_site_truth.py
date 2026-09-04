#!/usr/bin/env python3
"""whole_site_truth — the server, not the page, decides what a surface is showing.

Structural + behavioural pins for ControlPlaneSurfaceAuthority@v1,
OperatorIdentityBoundary@v1, V3NextLineage@v1 and RouteDisposition@v1.

No network, broker, scheduler, Drive, order or production path is touched. The
control-plane probes run in-process against a temporary state root, never the
served one.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import whole_site_truth as wst  # noqa: E402

API_V2 = ROOT / "scripts" / "api_v2.py"


# ── the contracts are wired into the served route table ──────────────────────


@pytest.fixture(scope="module")
def api_tree() -> ast.Module:
    return ast.parse(API_V2.read_bytes())


@pytest.fixture(scope="module")
def api_src() -> str:
    return API_V2.read_text(errors="replace")


@pytest.mark.parametrize(
    "route",
    [
        "/api/v2/system/control-plane-surface-authority",
        "/api/v2/system/operator-identity-boundary",
        "/api/v2/system/v3-next-lineage",
        "/api/v2/system/route-disposition",
    ],
)
def test_contract_is_registered_in_the_route_table(api_src, route):
    """A contract that is defined but unrouted is a filing cabinet (AGENTS.md 13.5)."""
    assert f'"{route}"' in api_src


def test_route_handlers_exist(api_tree):
    names = {n.name for n in api_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for fn in (
        "_control_plane_surface_authority",
        "_operator_identity_boundary",
        "_v3_next_lineage",
        "_route_disposition",
        "_whole_site_truth_block",
    ):
        assert fn in names, f"{fn}() missing from api_v2.py"


def test_the_wrapper_fails_closed(api_tree):
    """An import error must surface as UNAVAILABLE with a reason, never as {}."""
    fn = next(n for n in api_tree.body if isinstance(n, ast.FunctionDef) and n.name == "_whole_site_truth_block")
    src = ast.dump(fn)
    assert "UNAVAILABLE" in src
    assert "reason" in src
    assert any(isinstance(h, ast.ExceptHandler) for h in ast.walk(fn))


# ── ControlPlaneSurfaceAuthority@v1 ──────────────────────────────────────────


def test_every_control_plane_route_is_declared():
    """A route the authority does not list would render with no server verdict."""
    declared = set(wst.CONTROL_PLANE_SURFACES)
    app_routes = {"/v3/" + r.lstrip("/") for r in wst.registered_routes(ROOT) if r.startswith("control-plane")}
    assert app_routes, "no control-plane routes found in App.tsx"
    assert app_routes <= declared, f"undeclared control-plane routes: {sorted(app_routes - declared)}"


def test_authority_is_decided_by_the_server(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rep = wst.control_plane_surface_authority(ROOT)
    assert rep["schema"] == "ControlPlaneSurfaceAuthority@v1"
    assert rep["decided_by"] == "server"
    assert rep["authority"] == "READ_ONLY_ADVISORY"
    assert rep["surface_count"] == len(wst.CONTROL_PLANE_SURFACES)


def test_an_empty_state_root_is_never_reported_live(monkeypatch, tmp_path):
    """The defect: a page label that says LIVE while nothing answered."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rep = wst.control_plane_surface_authority(ROOT)
    for s in rep["surfaces"]:
        assert s["data_mode"] != wst.LIVE_GOVERNED, f"{s['route']} claimed LIVE with an empty root"


def test_every_non_live_surface_requires_an_undismissable_banner(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rep = wst.control_plane_surface_authority(ROOT)
    for s in rep["surfaces"]:
        assert s["banner_dismissible"] is False
        assert s["fixture_may_be_rendered_as_live"] is False
        assert s["banner_required"] is (s["data_mode"] != wst.LIVE_GOVERNED)
        assert s["reason"], f"{s['route']} has no reason"


def test_a_populated_state_root_reports_live(monkeypatch, tmp_path):
    """The other direction: real data must not be mislabelled as a fixture."""
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "identity_registry.json").write_text(
        json.dumps([{"id": "e1", "kind": "entity"}, {"id": "e2", "kind": "entity"}])
    )
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rep = wst.control_plane_surface_authority(ROOT)
    identity = next(s for s in rep["surfaces"] if s["route"].endswith("/identity"))
    assert identity["data_mode"] == wst.LIVE_GOVERNED
    assert identity["banner_required"] is False
    assert identity["live"]["item_count"] == 2


def test_producer_and_served_roots_are_both_reported(monkeypatch, tmp_path):
    """Reporting only the checkout's answer would re-create the state-root fork."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rep = wst.control_plane_surface_authority(ROOT)
    backed = [s for s in rep["surfaces"] if s["live_domain"]]
    assert backed
    for s in backed:
        assert s["live"]["state_root"] == str(tmp_path)
        assert s["live"]["checkout"]["state_root"] == str(ROOT)
        assert "roots_disagree" in s["live"]


# ── OperatorIdentityBoundary@v1 ──────────────────────────────────────────────


def test_client_storage_is_never_the_security_boundary():
    rep = wst.operator_identity_boundary(ROOT, env={})
    assert rep["client_storage_is_security_boundary"] is False
    assert rep["operator_identity_verified"] is False
    assert rep["identity_display_source"] == "client_claim"


def test_declared_is_not_effective():
    """access_ok() returns True when ADMIN_WRITE_TOKEN is unset: an open door."""
    unset = wst.operator_identity_boundary(ROOT, env={})
    setted = wst.operator_identity_boundary(ROOT, env={"ADMIN_WRITE_TOKEN": "x"})
    assert unset["write_gate_declared"] is True
    assert unset["write_gate_effective"] is False
    assert setted["write_gate_effective"] is True
    assert setted["server_enforces_write_authorization"] is True


def test_the_open_when_unset_behaviour_is_reported():
    rep = wst.operator_identity_boundary(ROOT, env={})
    gate = next(f for f in rep["findings"] if f["id"] == "AUTHZ-03")
    assert gate["open_when_unset"] is True
    assert gate["declared_in"].endswith("access_ok")


def test_the_localstorage_keys_are_named():
    rep = wst.operator_identity_boundary(ROOT, env={})
    token = next(f for f in rep["findings"] if f["id"] == "AUTHZ-01")
    ident = next(f for f in rep["findings"] if f["id"] == "AUTHZ-02")
    assert token["scoped"] is False and token["expiring"] is False
    assert ident["verified_by_server"] is False
    assert any("adminWrite" in p for p in token["client_files"])


# ── V3NextLineage@v1 ─────────────────────────────────────────────────────────


def test_a_bundle_with_no_manifest_is_noncanonical(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    rep = wst.v3_next_lineage(tmp_path, ROOT)
    assert rep["lineage"] == "NONE"
    assert rep["canonical"] is False
    assert "NONCANONICAL" in rep["operator_label"]


def test_a_missing_bundle_is_absent_not_silent(tmp_path):
    rep = wst.v3_next_lineage(tmp_path / "nope", ROOT)
    assert rep["exists"] is False
    assert rep["lineage"] == "ABSENT"
    assert "NONCANONICAL" in rep["operator_label"]


def test_a_manifest_without_a_sha_is_not_proof(tmp_path):
    (tmp_path / "build-meta.json").write_text(json.dumps({"built_at": "2026-01-01"}))
    rep = wst.v3_next_lineage(tmp_path, ROOT)
    assert rep["lineage"] == "MANIFEST_WITHOUT_SHA"
    assert rep["canonical"] is False


def test_a_manifest_with_a_sha_outside_the_repo_is_still_not_canonical(tmp_path):
    (tmp_path / "build-meta.json").write_text(json.dumps({"git_sha": "a" * 40}))
    rep = wst.v3_next_lineage(tmp_path, ROOT)
    assert rep["lineage"] == "PROVEN"
    assert rep["canonical"] is False, "a bundle outside the repository is not canonical"


# ── RouteDisposition@v1 ──────────────────────────────────────────────────────


def test_every_registered_route_has_a_disposition():
    rep = wst.route_disposition(ROOT)
    assert rep["route_count"] == len(wst.registered_routes(ROOT))
    for row in rep["routes"]:
        assert row["disposition"] in {"KEEP", "ORPHAN_LABELLED", "PREVIEW_LABELLED"}
        assert row["reason"]


def test_control_plane_routes_are_preview_labelled():
    rep = wst.route_disposition(ROOT)
    cp = [r for r in rep["routes"] if r["route"].startswith("/control-plane")]
    assert len(cp) == 11
    assert all(r["disposition"] == "PREVIEW_LABELLED" for r in cp)


def test_the_disposition_counts_sum_to_the_route_count():
    rep = wst.route_disposition(ROOT)
    assert sum(rep["disposition_counts"].values()) == rep["route_count"]


# ── nothing here writes ──────────────────────────────────────────────────────


def test_the_module_declares_no_mutation_path():
    src = (ROOT / "scripts" / "lib" / "whole_site_truth.py").read_text()
    tree = ast.parse(src)
    banned = {"place_order", "submit_order", "cancel_order", "os.system", "rmtree", "unlink"}
    called = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert not (called & banned), f"mutation call in a read-only module: {called & banned}"
    assert "open(" not in src.replace('p.open("w"', "").replace("write_text", "")
    assert "write_text" not in src
    assert wst.AUTHORITY == "READ_ONLY_ADVISORY"
