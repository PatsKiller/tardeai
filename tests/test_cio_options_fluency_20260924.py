#!/usr/bin/env python3
"""Stage 1C/1D — CIO options fluency + BUY_READY options alternative honesty.

    .venv/bin/python -m pytest tests/test_cio_options_fluency_20260924.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_options_fluency as flu  # noqa: E402
from scripts.lib import cio_entry_state as ces  # noqa: E402


def test_catalog_covers_desk_slots():
    ids = {c["strategy_id"] for c in flu.catalog_for_cio()}
    for required in ("covered_call", "cash_secured_put", "protective_put",
                     "credit_spread", "long_call", "debit_spread"):
        assert required in ids


def test_goal_lineage_absent_when_no_options_goals():
    goals = [
        {"goal_id": "goal_x", "status": "open", "title": "Cash concentration cost",
         "linked_symbols": ["V"], "description": "", "thesis_summary": ""},
    ]
    lin = flu.goal_lineage_for("V", "long_call", goals=goals)
    assert lin["status"] == "ABSENT"
    assert lin["goal_id"] is None


def test_goal_lineage_linked_when_options_language_and_symbol():
    goals = [
        {"goal_id": "goal_opt", "status": "open",
         "title": "Income sleeve covered calls on V",
         "linked_symbols": ["V"], "description": "covered call income",
         "thesis_summary": ""},
    ]
    lin = flu.goal_lineage_for("V", "covered_call", goals=goals)
    assert lin["status"] == "LINKED"
    assert lin["goal_id"] == "goal_opt"


def test_buy_ready_wrong_class_when_only_covered_call():
    desk = {
        "generated_at": "2026-09-24T15:00:00Z",
        "by_symbol": {
            "V": [{"strategy": "covered_call", "strike": 385, "edge_score": 64,
                   "premium_total": 120}],
        },
    }
    alt = flu.select_entry_options_alternative(
        "V", entry_low=364.5, entry_high=369, stop=357.5, target=410, desk=desk, goals=[],
    )
    assert alt["status"] == "OPTIONS_ALT_NONE"
    assert alt["reason"] == "WRONG_STRATEGY_CLASS"
    block = flu.format_entry_options_alternative_block(alt)
    assert "WRONG_STRATEGY_CLASS" in block
    assert "covered" in block.lower() or "income" in block.lower()


def test_buy_ready_ok_with_long_call():
    desk = {
        "by_symbol": {
            "V": [{"strategy": "long_call", "strike": 370, "edge_score": 70,
                   "premium_total": 850, "pop_pct": 55}],
        },
    }
    alt = flu.select_entry_options_alternative("V", desk=desk, goals=[])
    assert alt["status"] == "OPTIONS_ALT_OK"
    assert alt["strategy"] == "long_call"
    block = flu.format_entry_options_alternative_block(alt)
    assert "long_call" in block and "Path B" in block or "2FA" in block


def test_render_cio_includes_options_alt_or_honest_none(monkeypatch):
    desk = {
        "by_symbol": {
            "ACHV": [{"strategy": "covered_call", "strike": 8, "edge_score": 60}],
        },
    }
    import scripts.lib.cio_options_fluency as mod
    monkeypatch.setattr(mod, "load_options_desk_summary", lambda path=None: desk)

    result = {
        "symbol": "ACHV", "state": "BUY_READY", "price": 7.25,
        "entry_low": 7.0, "entry_high": 7.5, "stop": 6.5, "target": 10.0,
        "rr": 4.27, "plan_source": "reentry_desk", "distance_pct": 0.0,
        "catalyst": None, "cio_action": None, "held": False,
    }
    from lib.market_cap_label import cap_label
    ev = {"symbol": "ACHV", "market_cap_label": cap_label(744)}
    text = ces.render_cio(result, ev)
    assert "Entry state BUY_READY for ACHV" in text
    assert "Confirm or refute" in text
    assert "Options alternative" in text
    assert "WRONG_STRATEGY_CLASS" in text or "none suitable" in text.lower()


def test_looks_like_options_strategy_ask():
    assert flu.looks_like_options_strategy_ask("what covered call makes sense on V?")
    assert not flu.looks_like_options_strategy_ask("what's the analyst target for V?")
