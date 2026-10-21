"""Preserve upstream CIO review display while projecting the registered packet.

Only actual pure projection functions execute. Packet and renderer leaves are
contained fakes; no runner import, store, provider or notification is needed.
"""

import ast
from copy import deepcopy
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "review,evidence_review,status,decision_id",
    [
        (None, None, "ON_RECORD", "recorded-decision"),
        ({"status": "OK", "decision_id": "fresh"}, None, "OK", "fresh"),
        (None, {"status": "PENDING", "decision_id": "queued"}, "PENDING", "queued"),
        ({}, None, "ON_RECORD", "recorded-decision"),
        (None, {}, None, None),
        ("unusable", None, "ON_RECORD", "recorded-decision"),
    ],
)
def test_projection_keeps_main_review_precedence(monkeypatch, review, evidence_review, status, decision_id):
    runner = ROOT / "scripts/cio_entry_state_runner.py"
    functions = [
        node
        for node in ast.parse(runner.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name in {"cio_card_payload", "_card_option_reasons"}
    ]
    assert len(functions) == 2
    package = types.ModuleType("lib")
    package.__path__ = []
    rich = types.ModuleType("lib.telegram_rich")
    producer = types.ModuleType("lib.cio_options_fluency")

    class Capture:
        def __init__(self, item):
            self.item = item

        def render(self):
            return self.item

    rich.cio_entry_alert = Capture
    producer.build_buy_ready_packet = lambda *_args: {"equity": {"rr_at_ideal_entry": 1.8, "rr_at_current_price": 0.8}}
    for name, module in [("lib", package), ("lib.telegram_rich", rich), ("lib.cio_options_fluency", producer)]:
        monkeypatch.setitem(sys.modules, name, module)
    result = {"symbol": "CANARY", "rr": 1.2, "next_action": "Existing review action"}
    evidence = {"cio_review_status": "ON_RECORD", "cio_review_id": "recorded-decision"}
    if evidence_review is not None:
        evidence["cio_review"] = evidence_review
    original = deepcopy((result, evidence, review))
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(runner), "exec"), namespace)
    item = namespace["cio_card_payload"](result, evidence, review=review)
    assert item["cio_review_status"] == status
    assert item["cio_review_id"] == decision_id
    assert item["rr_at_ideal_entry"] == 1.8 and item["rr_at_current_price"] == 0.8
    assert item["next_action"] == ("CIO review follow-up received" if review else "Existing review action")
    assert (result, evidence, review) == original
