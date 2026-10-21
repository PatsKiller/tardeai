"""Actual producer projection and actual rich/card renderer; only the packet/chrome are fake."""

import ast
import copy
import sys
import types
from pathlib import Path

import pytest

from scripts.lib import telegram_cards as cards
from scripts.lib import telegram_rich as rich

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("current", [0.8, None])
def test_canonical_packet_projects_to_real_distinct_basis_card(monkeypatch, tmp_path, current):
    runner = ROOT / "scripts/cio_entry_state_runner.py"
    tree = ast.parse(runner.read_text())
    names = {"cio_card_payload", "_card_option_reasons"}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(functions) == 2
    # Real presentation switch reads a byte-identical temporary copy of current reviewed config.
    config = tmp_path / "telegram_cards.yaml"
    config.write_bytes((ROOT / "config/telegram_cards.yaml").read_bytes())
    monkeypatch.setattr(cards, "CONFIG_PATH", config)
    assert cards.enabled("cio_entry") is True
    monkeypatch.setattr(cards, "ttl_text", lambda category: "4 days")
    for name in ("cc_symbol_url", "cc_trading_url", "trading_view_url", "opportunity_url", "chart_image_url"):
        monkeypatch.setattr(cards, name, lambda symbol: "https://example.invalid/" + symbol)

    result = {
        "symbol": "CANARY",
        "state": "ENTRY_NEAR",
        "rr": 1.8,
        "rr_at_current_price": None,
        "price": 20,
        "entry_low": 18,
        "entry_high": 19,
        "stop": 15,
        "target": 30,
    }
    evidence = {"fixture_only": True}
    packet = {"equity": {**result, "rr_at_ideal_entry": 1.8, "rr_at_current_price": current}}
    original = copy.deepcopy((result, evidence, packet))
    calls = []
    fake_math = types.ModuleType("lib.cio_options_fluency")

    def packet_only(actual_result, actual_evidence):
        assert actual_result is result
        calls.append(actual_evidence)
        return packet

    fake_math.build_buy_ready_packet = packet_only
    package = types.ModuleType("lib")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "lib", package)
    # This is the actual renderer module, including its actual enabled-card routing and render().
    monkeypatch.setitem(sys.modules, "lib.telegram_rich", rich)
    monkeypatch.setitem(sys.modules, "lib.cio_options_fluency", fake_math)
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(runner), "exec"), namespace)
    payload = namespace["cio_card_payload"](result, evidence)
    line = next(line for line in payload["text"].splitlines() if "R:R" in line)
    expected_current = "unavailable" if current is None else "0.80"
    assert f"R:R {expected_current} at current price" in line
    assert "ideal-zone 1.80" in line
    assert "2.00" not in line, "the supplied ratio must not be recomputed from price levels"
    assert "ENTRY APPROACHING" in payload["text"]
    assert payload["authority"] == "READ_ONLY_ADVISORY" and payload["parse_mode"] == "HTML"
    assert "nothing queued, nothing executed" in payload["text"]
    assert (result, evidence, packet) == original and len(calls) == 1
