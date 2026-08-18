"""CC v3 page-load repair: build-meta merge + maturity bound."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib.cc_v3_build_meta import merge_build_meta, write_merged_build_meta  # noqa: E402


def test_merge_keeps_vite_ui_version():
    existing = {"ui_version": "3.14+msypemkd", "base_version": "3.14", "release_notes": "x"}
    out = merge_build_meta(existing, sha="da4550e980d3e70d4a723147de90843c4449a0a3", label="main-exact-phase2")
    assert out["ui_version"] == "3.14+msypemkd"
    assert out["source_commit"].startswith("da4550e9")
    assert out["build_sha"] == "da4550e980d3"
    assert out["release_label"] == "main-exact-phase2"


def test_merge_synthesizes_ui_version_when_clobbered():
    out = merge_build_meta({}, sha="deadbeefcafebabe", label="x")
    assert out["ui_version"].startswith("3.14+deadbeef")


def test_write_prefers_vite_file(tmp_path: Path):
    vite = tmp_path / "dist" / "build-meta.json"
    dest = tmp_path / "build-meta.json"
    vite.parent.mkdir()
    vite.write_text(json.dumps({"ui_version": "3.14+abc", "built_at": "2026-08-18T00:00:00Z"}))
    meta = write_merged_build_meta([vite, dest], sha="aa" * 20, label="lab")
    assert meta["ui_version"] == "3.14+abc"
    assert json.loads(dest.read_text())["ui_version"] == "3.14+abc"


def test_deploy_script_calls_merge_helper():
    src = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text()
    assert "write_merged_build_meta" in src
    assert "ui_version" in src


def test_host_wraps_maturity_connect_in_3s():
    src = (ROOT / "scripts/portfolio_server.py").read_text()
    assert "agent-maturity exceeded 3s connect/read bound" in src


def test_maturity_bound_times_out(monkeypatch):
    from agent_runtime import read_http as rh

    def hang(*_a, **_k):
        import time
        time.sleep(5)
        return 200, {"ok": True}

    monkeypatch.setattr(rh, "_dispatch_maturity", hang)
    status, body = rh._dispatch_maturity_bounded("GET", "/api/v3/agent-maturity", None, timeout_s=0.2)
    assert status == 503
    assert "timeout" in json.dumps(body).lower() or (body.get("kind") == "timeout")


def test_trading_hub_defers_sibling_polls():
    src = (ROOT / "apps/command-center-v3/src/pages/TradingHub.tsx").read_text()
    assert "scannerSettled" in src
    assert "Loading latest scanner run" in src
    assert "No scanner data yet." not in src


def test_use_api_does_not_settle_cancelled():
    src = (ROOT / "apps/command-center-v3/src/hooks/useApi.ts").read_text()
    assert "if (!cancelled)" in src
    assert "Abandoned effects must not settle loading=false" in src
