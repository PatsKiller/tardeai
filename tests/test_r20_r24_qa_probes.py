"""R20–R24 QA probes (contract / authority / secrets / routes).

Read-only against product code. Does not implement pages or change
scripts/control_plane_api.py behavior.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

import scripts.control_plane_api as api

BASELINE = json.loads(
    (ROOT / "docs" / "convergence" / "CONTROL_PLANE_API_V1_BASELINE.json").read_text()
)
SCHEMA = json.loads(
    (ROOT / "fixtures" / "control_plane" / "api_v1_baseline" / "SCHEMA.json").read_text()
)
INVENTORY = json.loads((ROOT / "docs" / "convergence" / "UI_ROUTE_INVENTORY.json").read_text())
REMAINING_MOCKS = json.loads(
    (ROOT / "docs" / "_evidence" / "r20-r24" / "REMAINING_MOCKS.json").read_text()
)
WORKER_REGISTRY = json.loads(
    (ROOT / "docs" / "_evidence" / "r20-r24" / "WORKER_REGISTRY.json").read_text()
)

ENVELOPE = tuple(BASELINE["envelope_required"])
COLLECTION = tuple(BASELINE["collection_data_required"])
PAGINATION = tuple(BASELINE["pagination_required"])
SUMMARY = tuple(BASELINE["summary_routes"])
ALLOWED_DISPOSITIONS = {"KEEP", "REPLACE", "MERGE", "SPLIT", "RETIRE", "REDIRECT", "DEFER"}

SECRET_RE = re.compile(
    r"(?ix)"
    r"(api[_-]?key|secret_key|private[_-]?key|passwd|password)"
    r"\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    r"|-----BEGIN[ A-Z]*PRIVATE KEY-----"
    r"|AKIA[0-9A-Z]{16}"
    r"|sk_live_[0-9A-Za-z]{16,}"
    r"|xox[baprs]-[0-9A-Za-z-]{20,}"
    r"|gh[pousr]_[0-9A-Za-z]{20,}"
)

WRITER_RE = re.compile(
    r"(?ix)"
    r"place_order|submit_order|create_order|cancel_order|"
    r"execute_trade|broker_client|\b2fa\b|two_factor|\btotp\b|"
    r"json\.dump|write_text|write_bytes|"
    r"subprocess\.|requests\.(post|put|patch|delete)|httpx\.(post|put|patch|delete)|"
    r"INSERT\s+INTO|DELETE\s+FROM"
)

ROUTE_PATH_RE = re.compile(r'<Route\s+(index|path="([^"]+)")')
NAVIGATE_RE = re.compile(
    r'<Route\s+path="([^"]+)"\s+element=\{<Navigate\s+to="([^"]+)"'
)
MATRIX_ROW_RE = re.compile(r"^\|\s*(`[^`]+`|—|[^|]+)\s*\|")


def _app_tsx() -> str:
    return (ROOT / "apps" / "command-center-v3" / "src" / "App.tsx").read_text()


def _app_route_paths() -> set[str]:
    paths: set[str] = set()
    for match in ROUTE_PATH_RE.finditer(_app_tsx()):
        if match.group(1) == "index":
            paths.add("/")
            continue
        raw = match.group(2)
        if raw in {"/*", "*"}:
            continue
        paths.add("/" + raw if not raw.startswith("/") else raw)
    return paths


def _matrix_dispositions() -> list[tuple[str, str]]:
    text = (ROOT / "docs" / "convergence" / "UI_REPLACEMENT_MATRIX.md").read_text()
    rows: list[tuple[str, str]] = []
    in_table = False
    disp_idx = 2
    for line in text.splitlines():
        if line.startswith("| Old route") or line.startswith("| New route"):
            in_table = True
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            disp_idx = header.index("Disposition") if "Disposition" in header else 2
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) > disp_idx and cells[0] not in {"Old route", "New route"}:
                route = cells[0].strip("` ")
                disp = cells[disp_idx].split("(")[0].strip()
                rows.append((route, disp))
            continue
        in_table = False
    return rows


def test_freeze_metadata_and_schema_align():
    assert BASELINE["freeze"] == "CONTROL_PLANE_API_V1_BASELINE"
    assert BASELINE["authority"] == "READ_ONLY_ADVISORY"
    assert BASELINE["memory_behavior_influence"] == 0
    assert BASELINE["methods"] == ["GET"]
    assert BASELINE["mutation_http_status"] == 405
    assert BASELINE["live_claim_from_api_existence"] is False
    assert tuple(SCHEMA["envelope_required"]) == ENVELOPE
    assert tuple(SCHEMA["collection_data_required"]) == COLLECTION
    assert tuple(SCHEMA["pagination_required"]) == PAGINATION
    assert tuple(SCHEMA["routes"]) == SUMMARY
    assert SCHEMA["methods"] == ["GET"]
    assert SCHEMA["mutation_status"] == 405


def test_summary_routes_and_envelope_keys():
    assert tuple(api.ROUTES) == SUMMARY
    for route in SUMMARY:
        status, body = api.handle(route, method="GET")
        assert status == 200
        for key in ENVELOPE:
            assert key in body
        assert "payload" not in body
        assert isinstance(body["ok"], bool)
        assert body["evidence_class"]
        assert body["freshness"]


def test_collection_shape_except_system():
    for route in SUMMARY:
        if route.endswith("/system"):
            continue
        _, body = api.handle(route, method="GET")
        for key in COLLECTION:
            assert key in body["data"]
        for key in PAGINATION:
            assert key in body["data"]["pagination"]


def test_system_is_advisory_not_live():
    _, body = api.handle("/api/v3/control-plane/system")
    data = body["data"]
    assert data["authority"] == "READ_ONLY_ADVISORY"
    assert data["memory_behavior_influence"] == 0
    assert data["runtime"]["state"] not in {"LIVE", "LIVE_EVENT_DRIVEN"}


def test_unavailable_fixture_matches_freeze():
    doc = json.loads(
        (ROOT / "fixtures" / "control_plane" / "api_v1_baseline" / "agents.unavailable.FIXTURE.json").read_text()
    )
    assert doc["label"] == "FIXTURE"
    assert doc["not_production_data"] is True
    body = doc["body"]
    assert set(ENVELOPE) <= set(body)
    assert body["ok"] is True
    assert body["data_quality"] == "UNAVAILABLE"
    assert "payload" not in body
    assert body["data"]["items"] == []
    assert body["data"]["pagination"]["total"] == 0


def test_summary_unavailable_snapshot_covers_all_summary_routes():
    snap = json.loads(
        (ROOT / "fixtures" / "control_plane" / "api_v1_baseline" / "SUMMARY_UNAVAILABLE_SNAPSHOT.json").read_text()
    )
    names = {route.rsplit("/", 1)[-1] for route in SUMMARY}
    assert set(snap) == names
    for name, row in snap.items():
        body = row["body"]
        assert set(ENVELOPE) <= set(body)
        assert "payload" not in body
        if name == "system":
            assert body["data_quality"] == "AVAILABLE"
            assert body["data"]["authority"] == "READ_ONLY_ADVISORY"
        else:
            assert body["data_quality"] == "UNAVAILABLE"
            assert set(COLLECTION) <= set(body["data"])


def test_v1_payload_fixtures_are_mock_only():
    fixture_dir = ROOT / "fixtures" / "control_plane" / "v1.0.0"
    files = sorted(fixture_dir.glob("*.json"))
    assert files
    for path in files:
        doc = json.loads(path.read_text())
        assert doc["schema"] == "ControlPlane@v1.0.0"
        assert "payload" in doc
        assert "ok" not in doc
        assert not isinstance(doc.get("data"), dict) or "items" not in (doc.get("data") or {})


def test_handle_mutations_are_405():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for route in SUMMARY:
            status, body = api.handle(route, method=method)
            assert status == 405
            assert body["data"]["error"] == "control-plane is read-only"


def test_portfolio_server_get_passes_real_method_and_post_intercepts():
    src = (ROOT / "scripts" / "portfolio_server.py").read_text()
    assert "if path.startswith(\"/api/v3/control-plane\")" in src
    assert "_control_plane_handle(path, method=self.command" in src
    assert "_control_plane_handle(path, method=\"POST\"" in src
    get_idx = src.find("def _do_GET_inner")
    post_idx = src.find("def _do_POST_inner")
    assert get_idx != -1 and post_idx != -1
    get_block = src[get_idx:post_idx]
    post_block = src[post_idx:post_idx + 4000]
    assert "method=self.command" in get_block
    assert "method=\"POST\"" in post_block
    assert 'path.startswith("/api/v3/control-plane")' in get_block
    assert 'path.startswith("/api/v3/control-plane")' in post_block


def test_control_plane_api_has_no_broker_order_stop_risk_2fa_writers():
    src = (ROOT / "scripts" / "control_plane_api.py").read_text()
    hits = [m.group(0) for m in WRITER_RE.finditer(src)]
    assert hits == []
    lowered = src.lower()
    for token in ("broker", "place_order", "2fa", "two_factor", "totp"):
        assert token not in lowered
    assert "mode=\"w\"" not in src
    assert "mode='w'" not in src


def test_missing_store_unavailable_ok_true(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/agents")
    assert status == 200
    assert body["ok"] is True
    assert body["data_quality"] == "UNAVAILABLE"
    assert body["data"]["items"] == []
    assert body["data"]["pagination"]["total"] == 0


def test_invalid_schema_ok_false(tmp_path, monkeypatch):
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "agent_registry.json").write_text("{not-json")
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/agents")
    assert status == 200
    assert body["ok"] is False
    assert body["data_quality"] == "INVALID_SCHEMA"
    assert body["data"]["items"] == []


def test_empty_valid_available_total_zero(tmp_path, monkeypatch):
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "agent_registry.json").write_text("[]")
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    status, body = api.handle("/api/v3/control-plane/agents")
    assert status == 200
    assert body["ok"] is True
    assert body["data_quality"] == "AVAILABLE"
    assert body["data"]["items"] == []
    assert body["data"]["pagination"]["total"] == 0
    assert body["data_quality"] != "UNAVAILABLE"


def test_secret_scan_control_plane_surfaces():
    targets = [
        ROOT / "scripts" / "control_plane_api.py",
        ROOT / "tests" / "test_control_plane_api.py",
        ROOT / "tests" / "test_control_plane_api_v1_baseline.py",
    ]
    targets.extend(sorted((ROOT / "fixtures" / "control_plane" / "api_v1_baseline").glob("*")))
    findings = []
    for path in targets:
        text = path.read_text(errors="ignore")
        for match in SECRET_RE.finditer(text):
            findings.append(f"{path}:{match.group(0)[:40]}")
    assert findings == []


def test_route_inventory_matches_app_tsx_and_cutover_false():
    assert INVENTORY["cutover"] is False
    assert INVENTORY["http_freeze"] == "CONTROL_PLANE_API_V1_BASELINE"
    app_paths = _app_route_paths()
    inventory_live = {row["old_route"] for row in INVENTORY["existing_live_routes"]}
    preview = {row["new_route"] for row in INVENTORY["new_preview_routes"]}
    assert inventory_live <= app_paths
    assert preview <= app_paths
    app = _app_tsx()
    assert 'path="agents"' in app
    assert 'Navigate to="/control-plane' not in app


def test_redirect_rows_match_navigate_elements():
    nav = {m.group(1): m.group(2) for m in NAVIGATE_RE.finditer(_app_tsx())}
    for row in INVENTORY["existing_live_routes"]:
        if row["disposition"] != "REDIRECT":
            continue
        path = row["old_route"].lstrip("/")
        assert path in nav, row["old_route"]
        assert nav[path] == row["new_route"]


def test_defer_rows_are_not_cut_over():
    app_paths = _app_route_paths()
    for row in INVENTORY["existing_live_routes"]:
        if row["disposition"] != "DEFER":
            continue
        assert row["old_route"] in app_paths
        # Still the live page, not a Navigate onto control-plane.
        path = row["old_route"].lstrip("/")
        block = _app_tsx()
        assert f'path="{path}"' in block
        assert f'path="{path}" element={{<Navigate to="/control-plane' not in block


def test_replacement_matrix_dispositions_and_no_live_cutover():
    matrix = (ROOT / "docs" / "convergence" / "UI_REPLACEMENT_MATRIX.md").read_text()
    assert "No live cutover" in matrix
    assert "No old route is retired" in matrix
    rows = _matrix_dispositions()
    assert rows
    bad = [(route, disp) for route, disp in rows if disp not in ALLOWED_DISPOSITIONS]
    assert bad == []
    retired = [route for route, disp in rows if disp == "RETIRE"]
    assert retired == []
    inventory_disp = {row["old_route"]: row["disposition"] for row in INVENTORY["existing_live_routes"]}
    preview_disp = {row["new_route"]: row["disposition"] for row in INVENTORY["new_preview_routes"]}
    for route, disp in rows:
        if route in inventory_disp:
            assert inventory_disp[route] == disp
        elif route in preview_disp:
            assert preview_disp[route] == disp


def test_remaining_mocks_exist_in_worker_trees_if_present_and_were_not_deleted():
    assert REMAINING_MOCKS["http_freeze"] == "CONTROL_PLANE_API_V1_BASELINE"
    assert REMAINING_MOCKS.get("runtime_mocks", 0) == 0
    for item in REMAINING_MOCKS["remaining"]:
        rel = item["path"].replace("*.json", "")
        target = ROOT / rel
        assert target.exists(), item["path"]
        files = list(target.glob("*.json")) if target.is_dir() else [target]
        assert files
        for path in files:
            doc = json.loads(path.read_text())
            assert "payload" in doc
            assert doc.get("schema") == "ControlPlane@v1.0.0"
        assert "ControlPlane@v1.0.0" in item["schema"]


def test_frontend_http_freeze_types_use_data_not_payload():
    src = (ROOT / "apps" / "command-center-v3" / "src" / "control-plane" / "apiV1Baseline.ts").read_text()
    assert "ok: boolean" in src
    assert "data: T" in src
    assert "items: T[]" in src
    assert "CONTROL_PLANE_API_V1_BASELINE" in src
    assert "084674c560abd7bb910726f62e41508703c07e40" in src
    for route in SUMMARY:
        assert route in src
