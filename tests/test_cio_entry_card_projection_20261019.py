"""Actual producer projection, extracted without importing runner effects or financial math."""

import ast
import copy
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def project(monkeypatch, *, equity=None, result=None, failure=False):
    """Execute the real reader/helper with a fake existing-schema packet and capture-only renderer."""
    runner = ROOT / "scripts/cio_entry_state_runner.py"
    tree = ast.parse(runner.read_text())
    names = {"cio_card_payload", "_card_option_reasons"}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(functions) == 2
    owner = ast.parse((ROOT / "scripts/lib/cio_options_fluency.py").read_text())
    builder = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == "build_buy_ready_packet")
    packet_equity = next(
        n
        for n in ast.walk(builder)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "equity" for t in n.targets)
    )
    keys = {k.value for k in packet_equity.value.keys if isinstance(k, ast.Constant)}
    assert {"rr_at_ideal_entry", "rr_at_current_price"} <= keys
    assert not {"reward_risk_at_quote", "reward_risk_worst_in_zone"} & keys

    inputs = {"symbol": "CANARY", "rr": 1.8, **(result or {})}
    evidence = {"fixture_only": True}
    packet = {"equity": equity}
    originals = copy.deepcopy((inputs, evidence, packet))
    calls = []
    package = types.ModuleType("lib")
    package.__path__ = []
    render = types.ModuleType("lib.telegram_rich")
    math_owner = types.ModuleType("lib.cio_options_fluency")

    class Capture:
        def __init__(self, item):
            self.item = item

        def render(self):
            return self.item

    def fake_packet(actual_result, actual_evidence):
        calls.append((actual_result, actual_evidence))
        assert actual_result is inputs
        if failure:
            raise RuntimeError("fixture packet unavailable")
        return packet

    render.cio_entry_alert = Capture
    math_owner.build_buy_ready_packet = fake_packet
    for name, module in [("lib", package), ("lib.telegram_rich", render), ("lib.cio_options_fluency", math_owner)]:
        monkeypatch.setitem(sys.modules, name, module)
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(runner), "exec"), namespace)
    value = namespace["cio_card_payload"](inputs, evidence)
    assert (inputs, evidence, packet) == originals
    assert len(calls) == 1
    return value


@pytest.mark.parametrize(
    "equity,result,ideal,current",
    [
        ({"rr_at_ideal_entry": 1.8, "rr_at_current_price": 0.8}, {"rr_at_current_price": None}, 1.8, 0.8),
        ({"rr_at_ideal_entry": 2.2, "rr_at_current_price": 0.8}, {"rr": 1.2, "rr_at_current_price": 0.9}, 2.2, 0.8),
        ({"rr_at_ideal_entry": 0, "rr_at_current_price": 0}, {"rr_at_current_price": 0.8}, 0, 0),
        ({"rr_at_ideal_entry": None, "rr_at_current_price": None}, {"rr_at_current_price": 0.8}, None, None),
        ({}, {"rr_at_ideal_entry": 2.0, "rr_at_current_price": 0.8}, 2.0, 0.8),
        ({}, {"rr_at_current_price": None}, 1.8, None),
        ({"reward_risk_at_quote": 9, "reward_risk_worst_in_zone": 9}, {"rr_at_current_price": None}, 1.8, None),
        ({"rr_at_ideal_entry": 1.8, "rr_at_current_price": None}, {}, 1.8, None),
        ({"rr_at_current_price": 0}, {"rr_at_ideal_entry": 2.0}, 2.0, 0),
        (None, {"rr_at_current_price": 0.8}, 1.8, 0.8),
        ({"rr_at_ideal_entry": None}, {"rr_at_current_price": 0}, None, 0),
    ],
)
def test_existing_packet_ratios_keep_their_own_price_basis(monkeypatch, equity, result, ideal, current):
    item = project(monkeypatch, equity=equity, result=result)
    assert item["rr_at_ideal_entry"] == ideal
    assert item["rr_at_current_price"] == current
    assert item["symbol"] == "CANARY"


def test_unavailable_packet_preserves_existing_result_fallback(monkeypatch):
    item = project(
        monkeypatch,
        failure=True,
        result={"rr_at_ideal_entry": 1.8, "rr_at_current_price": 0, "options_status": "unavailable"},
    )
    assert item["rr_at_ideal_entry"] == 1.8 and item["rr_at_current_price"] == 0
    assert item["options_status"] == "unavailable"
