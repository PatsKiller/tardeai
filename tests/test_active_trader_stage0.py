"""Active Trader Stage 0: flags off, write:false, packet ack required."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.flags import FlagsError, load_flags  # noqa: E402
from active_trader.read_api import ReadOnlyActiveTraderAPI  # noqa: E402
from active_trader.read_http import dispatch, is_active_trader_path  # noqa: E402
import active_trader_read_boot as boot  # noqa: E402

EXAMPLE = ROOT / "config" / "active_trader.stage0.example.yaml"
PACKET = ROOT / "scripts" / "operator_packets" / "packet_g_active_trader_stage0.py"


def _load_packet():
    spec = importlib.util.spec_from_file_location("packet_g", PACKET)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pf = _load_packet()


def test_flags_default_off():
    flags = load_flags(EXAMPLE)
    assert flags.stage == 0
    assert flags.write is False
    assert flags.canary is False
    assert flags.flags.get("live_canary") is False
    assert flags.flags.get("order_routes") is False
    assert flags.flags.get("session_authorize") is False
    assert all(v is False for v in flags.flags.values())


def test_flags_reject_live_canary(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "schema_version: active-trader-stage0-v1\n"
        "stage: 0\n"
        "authority:\n  write: false\n  canary: false\n"
        "feature_flags:\n  live_canary: true\n  order_routes: false\n"
        "read_api:\n  contract: active-trader-stage0-read-api-v1\n"
        "registry:\n  path: /tmp/x.json\n",
        encoding="utf-8",
    )
    with pytest.raises(FlagsError, match="live_canary"):
        load_flags(p)


def test_health_write_false():
    api = ReadOnlyActiveTraderAPI(load_flags(EXAMPLE))
    st, body = dispatch(api, "GET", "/api/v3/active-trader/health")
    assert st == 200
    assert body["stage"] == 0
    assert body["write"] is False
    assert body["canary"] is False
    assert body["read_only"] is True
    venues = body.get("venues") or {}
    for name in ("schwab", "moomoo", "alpaca"):
        assert name in venues
        assert venues[name]["data"] is False
        assert venues[name]["execution"] is False
        assert venues[name]["read_only_inventory"] is True
        assert venues[name]["order_path"] is False
    assert body.get("product_intent", {}).get("unattended_discover_and_fire") is False
    assert body.get("product_intent", {}).get("operator_opt_in_required") is True


def test_status_and_sessions():
    api = ReadOnlyActiveTraderAPI(load_flags(EXAMPLE))
    st, status = dispatch(api, "GET", "/api/v3/active-trader/status")
    assert st == 200
    assert status["write"] is False
    assert status["feature_flags"]["live_canary"] is False
    st2, sessions = dispatch(api, "GET", "/api/v3/active-trader/sessions")
    assert st2 == 200
    assert sessions["sessions"] == []


def test_non_get_is_405():
    api = ReadOnlyActiveTraderAPI(load_flags(EXAMPLE))
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        st, body = dispatch(api, method, "/api/v3/active-trader/health")
        assert st == 405
        assert body["write"] is False


def test_boot_handle():
    boot.reset_for_test()
    out = boot.handle("GET", "/api/v3/active-trader/health", {})
    assert out is not None
    st, body = out
    assert st == 200
    assert body["write"] is False
    assert body["canary"] is False
    assert boot.handle("GET", "/api/v2/other", {}) is None
    assert is_active_trader_path("/api/v3/active-trader/status")


def test_packet_default_disabled():
    assert pf.main([]) == 3


def test_packet_refuses_without_ack():
    assert pf.main(["--preflight"]) == 2
    assert pf.main(["--preflight", "--ack", "WRONG"]) == 2


def test_packet_self_check():
    assert pf.main(["--self-check"]) == 0


def test_packet_preflight_and_execute(tmp_path):
    rc = pf.main([
        "--preflight",
        "--ack", pf.ACK_TOKEN,
        "--config", str(EXAMPLE),
    ])
    assert rc == 0
    reg = tmp_path / "reg.json"
    rc2 = pf.main([
        "--execute",
        "--ack", pf.ACK_TOKEN,
        "--config", str(EXAMPLE),
        "--registry-path", str(reg),
    ])
    assert rc2 == 0
    body = json.loads(reg.read_text(encoding="utf-8"))
    assert body["live_canary"] is False
    assert body["order_routes"] is False
    assert body["write"] is False
    assert body["agents_marked_operational"] == 0
    assert body.get("docs_checksums")


def test_shell_wrapper_default_disabled():
    import subprocess
    sh = ROOT / "scripts" / "operator_packets" / "packet_g_active_trader_stage0.sh"
    proc = subprocess.run(
        ["bash", str(sh)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 2
    assert "PREPARE-ONLY" in (proc.stdout + proc.stderr)


def test_docs_exist():
    for rel in (
        "docs/implementation/ACTIVE_TRADER_STAGE0_BASELINE.md",
        "docs/implementation/ACTIVE_TRADER_ROUTE_API_DB_MAP.md",
        "docs/implementation/ACTIVE_TRADER_CURRENT_GUARDRAILS.md",
    ):
        assert (ROOT / rel).is_file()
