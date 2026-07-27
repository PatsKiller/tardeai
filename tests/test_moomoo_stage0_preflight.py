"""Moomoo Stage 0: preflight fail-closed, no network required in CI."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from moomoo.client import (  # noqa: E402
    MoomooAuthorityError,
    MoomooClient,
    MoomooUnavailable,
    StubTransport,
)
from moomoo.config import ConfigError, load_stage0_config  # noqa: E402
from moomoo.preflight import run_preflight  # noqa: E402

PACKET_MOD = ROOT / "scripts" / "operator_packets" / "packet_f_moomoo_stage0.py"


def _load_packet():
    spec = importlib.util.spec_from_file_location("packet_f", PACKET_MOD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pf = _load_packet()

EXAMPLE = ROOT / "config" / "moomoo.stage0.example.yaml"


def test_example_config_loads_read_only():
    cfg = load_stage0_config(EXAMPLE)
    assert cfg.stage == 0
    assert cfg.read_only is True
    assert cfg.order_routing is False
    assert cfg.trade_unlock is False


def test_config_rejects_order_routing(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "schema_version: moomoo-stage0-v1\n"
        "stage: 0\n"
        "mode: read_only_data_plane\n"
        "authority:\n"
        "  order_routing: true\n"
        "  trade_unlock: false\n"
        "opend:\n"
        "  host: 127.0.0.1\n"
        "  port: 11111\n"
        "secrets:\n"
        "  required_names: []\n"
        "preflight:\n"
        "  allow_missing_secrets: true\n"
        "  allow_missing_opend: true\n"
        "health_registry:\n"
        "  path: /tmp/x.json\n"
        "client:\n"
        "  fail_closed: true\n"
        "  adapter: stub\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="order_routing"):
        load_stage0_config(p)


def test_preflight_passes_without_network():
    report = run_preflight(config_path=EXAMPLE, probe_opend=False)
    assert report["ok"] is True
    assert report["order_routing"] is False
    assert report["agents_marked_operational"] == 0
    assert report["opend"]["probed"] is False
    names = {g["gate"] for g in report["gates"]}
    assert "client_fail_closed" in names
    assert "order_path_refused" in names


def test_client_fail_closed_when_opend_down():
    cfg = load_stage0_config(EXAMPLE)
    client = MoomooClient(cfg, transport=StubTransport(force_up=False))
    assert client.opend_up is False
    with pytest.raises(MoomooUnavailable):
        client.get_quote("AAPL")


def test_client_quote_when_up():
    cfg = load_stage0_config(EXAMPLE)
    client = MoomooClient(cfg, transport=StubTransport(force_up=True))
    q = client.get_quote("AAPL")
    assert q.symbol == "AAPL"
    assert q.source == "stub"


def test_place_order_refused():
    cfg = load_stage0_config(EXAMPLE)
    client = MoomooClient(cfg, transport=StubTransport(force_up=True))
    with pytest.raises(MoomooAuthorityError, match="Stage 0"):
        client.place_order(symbol="AAPL", qty=1)
    with pytest.raises(MoomooAuthorityError):
        client.unlock_trade()


def test_packet_default_disabled():
    assert pf.main([]) == 3


def test_packet_missing_ack_refuses():
    assert pf.main(["--preflight"]) == 2
    assert pf.main(["--preflight", "--ack", "WRONG"]) == 2


def test_packet_self_check():
    assert pf.main(["--self-check"]) == 0


def test_packet_preflight_ok():
    rc = pf.main([
        "--preflight",
        "--ack", pf.ACK_TOKEN,
        "--config", str(EXAMPLE),
    ])
    assert rc == 0


def test_packet_execute_health_only(tmp_path):
    health = tmp_path / "health.json"
    rc = pf.main([
        "--execute",
        "--ack", pf.ACK_TOKEN,
        "--config", str(EXAMPLE),
        "--health-path", str(health),
    ])
    assert rc == 0
    assert health.is_file()
    body = json.loads(health.read_text(encoding="utf-8"))
    assert body["read_path_only"] is True
    assert body["order_routing"] is False
    assert body["trade_unlock"] is False
    assert body["agents_marked_operational"] == 0
    assert body["schedule_enabled"] is False


def test_shell_wrapper_default_disabled():
    import subprocess
    sh = ROOT / "scripts" / "operator_packets" / "packet_f_moomoo_stage0.sh"
    proc = subprocess.run(
        ["bash", str(sh)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 2
    combined = proc.stdout + proc.stderr
    assert "PREPARE-ONLY" in combined
    assert "read-plane" in combined.lower() or "Stage 0" in combined


def test_preflight_cli_module():
    from moomoo import preflight as pre_mod
    rc = pre_mod.main(["--config", str(EXAMPLE)])
    assert rc == 0
