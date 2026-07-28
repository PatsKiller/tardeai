from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ast
NEW_FILES = [
    "scripts/moomoo/gateway_ipc.py",
    "scripts/moomoo/gateway_journal.py",
    "scripts/moomoo/futu_normalizer.py",
    "scripts/moomoo/futu_streaming_transport.py",
    "scripts/moomoo/gateway_service.py",
    "scripts/active_trader/current_marks_api.py",
    "scripts/active_trader/fire_replay.py",
    "scripts/active_trader/l2_runtime.py",
    "scripts/active_trader/l2_status_api.py",
]


def test_new_gateway_modules_have_no_trade_or_credential_authority():
    banned_calls = {
        "place_order", "submit_order", "unlock_trade", "modify_order", "cancel_order",
        "open_sectrade_context", "open_ustrade_context", "get_totp", "request_2fa",
    }
    banned_import_fragments = ("alpaca_trade", "order_adapter", "broker_write", "trade_unlock")
    for relative in NEW_FILES:
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                assert name.lower() not in banned_calls, f"{relative} calls forbidden authority {name}"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                else:
                    names.append(node.module or "")
                assert not any(fragment in name.lower() for fragment in banned_import_fragments for name in names)


def test_only_gateway_service_constructs_real_gateway_transport():
    for relative in NEW_FILES:
        source = (ROOT / relative).read_text(encoding="utf-8")
        occurrences = source.count("RealGatewayTransport()")
        if relative.endswith("gateway_service.py"):
            assert occurrences == 1
        else:
            assert occurrences == 0


def test_http_and_probe_never_construct_opend_context():
    for relative in ("scripts/active_trader/l2_runtime.py", "scripts/active_trader/current_marks_api.py", "scripts/moomoo_l2_gateway_probe.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "OpenQuoteContext" not in source
        assert "FutuTransport(" not in source
        assert "RealGatewayTransport(" not in source


def test_service_unit_and_example_are_inert_by_default():
    config = (ROOT / "config/moomoo_l2_gateway.example.yaml").read_text()
    unit = (ROOT / "config/systemd/tradeai-moomoo-l2-gateway.service").read_text()
    assert "enabled: false" in config
    assert "ConditionPathExists=/etc/tradeai/ENABLE_MOOMOO_L2_GATEWAY" in unit
    assert "ConditionPathExists=/etc/tradeai/moomoo_l2_gateway.env" in unit
    assert "Restart=on-failure" in unit
    assert "ReadWritePaths=/home/johnclaw/.tradeai/runtime" in unit


def test_service_unit_runs_exact_ref_candidate_not_mutable_main_tree():
    config = (ROOT / "config/moomoo_l2_gateway.example.yaml").read_text()
    unit = (ROOT / "config/systemd/tradeai-moomoo-l2-gateway.service").read_text()
    candidate_root = "/opt/trade-ai/runtime/moomoo-l2-gateway/current"
    assert f"WorkingDirectory={candidate_root}" in unit
    assert f"{candidate_root}/scripts/moomoo/gateway_service.py" in unit
    assert "EnvironmentFile=/etc/tradeai/moomoo_l2_gateway.env" in unit
    assert "Environment=TRADEAI_REPO_ROOT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild" in unit
    assert "WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild" not in unit
    assert '"${TRADEAI_REPO_ROOT}/data/scalp/moomoo_armed_state.json"' in config


def test_git_hygiene_guard_is_nounset_safe():
    source = (ROOT / "scripts/git_hygiene_guard.sh").read_text()
    assert '${ALLOW_MAINTREE_GIT:-}' in source
    assert '[ -n "$ALLOW_MAINTREE_GIT" ]' not in source


def test_operator_probe_is_snapshot_read_only():
    source = (ROOT / "scripts/moomoo_l2_gateway_probe.py").read_text()
    for token in ("atomic_write", "open(\"w", "subscribe(", "unsubscribe(", "systemctl", "get_connection"):
        assert token not in source
