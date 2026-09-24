#!/usr/bin/env python3
"""Stage 1C/1D — CIO options fluency + institutional BUY_READY/ENTRY_NEAR packet.

Litmus: V BUY_READY (wrong-class CC honesty) + AXTI ENTRY_NEAR (vol-prefers-options).

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


def test_goal_lineage_linked_stamps_sector_industry_strategy():
    goals = [
        {"goal_id": "goal_opt", "status": "open",
         "title": "Income sleeve covered calls on V",
         "linked_symbols": ["V"], "description": "covered call income",
         "thesis_summary": "", "linked_sector": "Financials",
         "linked_industry": "Transaction Processing", "strategy_id": "covered_call"},
    ]
    lin = flu.goal_lineage_for("V", "covered_call", goals=goals)
    assert lin["status"] == "LINKED"
    assert lin["goal_id"] == "goal_opt"
    assert lin["linked_sector"] == "Financials"
    assert lin["linked_industry"] == "Transaction Processing"
    assert lin["strategy_id"] == "covered_call"


def test_buy_ready_wrong_class_when_only_covered_call():
    desk = {
        "generated_at": "2026-09-24T15:00:00Z",
        "by_symbol": {
            "V": [{"strategy": "covered_call", "strike": 385, "edge_score": 64,
                   "premium_total": 120, "iv_rank": 24.6}],
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
                   "premium_total": 850, "pop_pct": 55, "iv_rank": 30, "delta": 0.45}],
        },
    }
    alt = flu.select_entry_options_alternative("V", desk=desk, goals=[])
    assert alt["status"] == "OPTIONS_ALT_OK"
    assert alt["strategy"] == "long_call"
    block = flu.format_entry_options_alternative_block(alt)
    assert "long_call" in block and ("Path B" in block or "2FA" in block)


def test_v_buy_ready_institutional_packet():
    """Litmus V: equity + options alt or unsuitable + CIO verdict + compare when OK."""
    desk = {
        "by_symbol": {
            "V": [{"strategy": "covered_call", "strike": 385, "edge_score": 64,
                   "premium_total": 219, "iv_rank": 24.6, "pop_pct": 82}],
        },
    }
    result = {
        "symbol": "V", "state": "BUY_READY", "price": 367.53,
        "entry_low": 364.5, "entry_high": 369.0, "stop": 357.5, "target": 410.0,
        "rr": 3.57, "plan_source": "reentry_desk", "distance_pct": 0.0,
        "catalyst": None, "held": True,
    }
    ev = {"symbol": "V", "sector": "Financial", "pe": 31.03, "forward_pe": 24.07,
          "held": True, "plan_source": "reentry_desk", "atr": 4.0}
    packet = flu.build_buy_ready_packet(result, ev, desk=desk, goals=[], enrichment=ev)
    assert packet["equity"]["state"] == "BUY_READY"
    assert packet["options_alt"]["reason"] == "WRONG_STRATEGY_CLASS"
    assert packet["thesis_indicators"]["pe"] == 31.03
    assert packet["thesis_indicators"]["section"] == "thesis"
    assert packet["structure_indicators"]["section"] == "structure"
    assert packet["cio_verdict"]["verdict"]
    assert "APPROVE" in packet["cio_verdict"]["verdict"] or "MODIFY" in packet["cio_verdict"]["verdict"]
    lines = "\n".join(flu.format_buy_ready_packet_lines(packet))
    assert "Thesis:" in lines and "PE" in lines
    assert "CIO verdict:" in lines
    assert "Path B" in lines or "2FA" in lines


def test_axti_entry_near_vol_prefers_options():
    """Litmus AXTI ENTRY_NEAR: high ATR vs stop → prefer defined-risk options citation."""
    desk = {
        "by_symbol": {
            "AXTI": [{"strategy": "long_call", "strike": 75, "edge_score": 68,
                      "premium_total": 420, "pop_pct": 48, "iv_rank": 55, "delta": 0.40,
                      "dte": 35}],
        },
    }
    # price 72.93, stop 58.50 → dist_stop ≈ 14.43; ATR 8 → ratio ~0.55 elevated
    result = {
        "symbol": "AXTI", "state": "ENTRY_NEAR", "price": 72.93,
        "entry_low": 62.0, "entry_high": 66.0, "stop": 58.50, "target": 96.50,
        "rr": 4.07, "plan_source": "reentry_desk", "distance_pct": 10.5,
        "catalyst": None, "held": False,
    }
    ev = {
        "symbol": "AXTI", "plan_source": "reentry_desk", "held": False,
        "formerly_held": True, "reentry": True, "atr": 8.0, "pe": 22.0,
        "sector": "Technology",
    }
    packet = flu.build_buy_ready_packet(result, ev, desk=desk, goals=[], enrichment=ev)
    assert packet["equity"]["state"] == "ENTRY_NEAR"
    assert packet["options_alt"]["status"] == "OPTIONS_ALT_OK"
    assert packet["structure_indicators"]["volatility_elevated"] is True
    assert packet["options_alt"].get("volatility_prefers_options") is True
    assert packet["former_holding"]["formerly_held"] is True
    cmp_ = packet["comparative"]
    assert cmp_["equity"]["capital_at_risk"] is not None
    assert cmp_["options"]["max_loss"] is not None
    lines = "\n".join(flu.format_buy_ready_packet_lines(packet))
    assert "Compare" in lines or "capital" in lines.lower()
    assert "OPTIONS_PREFERRED" in packet["cio_verdict"]["verdict"] or "APPROVE" in packet["cio_verdict"]["verdict"]
    assert "formerly" in lines.lower() or "re-entry" in lines.lower() or "Book context" in lines


def test_p8_pe_never_picks_strike():
    """A1D.P8.4 — PE lives in thesis section; structure builders do not read PE for strike."""
    import ast
    import inspect
    src = inspect.getsource(flu.build_structure_indicators)
    tree = ast.parse(src)
    # No attribute/name access whose id is exactly 'pe' / 'forward_pe' / 'peg'
    forbidden = {"pe", "forward_pe", "peg", "pe_ratio"}
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden:
            hits.append(node.id)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in forbidden:
            hits.append(node.value)
    assert not hits, f"structure builder must not reference PE fields: {hits}"
    struct = flu.build_structure_indicators(
        {"strike": 100, "iv_rank": 40, "delta": 0.5},
        price=95, stop=90, target=120, atr=3.0,
        enrichment={"pe": 99.0, "atr": 3.0},
    )
    assert "pe" not in struct
    assert struct["section"] == "structure"
    thesis = flu.build_thesis_indicators("X", ev={"pe": 18.5}, enrichment={})
    assert thesis["section"] == "thesis"
    assert thesis["pe"] == 18.5
    # Strike on proposal is never derived from thesis PE in packet builder
    packet = flu.build_buy_ready_packet(
        {"symbol": "X", "state": "BUY_READY", "price": 95, "entry_low": 90,
         "entry_high": 100, "stop": 85, "target": 120, "rr": 3.0,
         "plan_source": "test"},
        {"pe": 99.0, "atr": 2.0},
        desk={"by_symbol": {"X": [{"strategy": "long_call", "strike": 100,
                                   "premium_total": 200, "edge_score": 70}]}},
        goals=[],
        enrichment={"pe": 99.0},
    )
    assert packet["options_alt"]["proposal"]["strike"] == 100
    assert packet["thesis_indicators"]["pe"] == 99.0
    # Coupling check: changing PE must not change strike in maps_to_plan
    packet2 = flu.build_buy_ready_packet(
        {"symbol": "X", "state": "BUY_READY", "price": 95, "entry_low": 90,
         "entry_high": 100, "stop": 85, "target": 120, "rr": 3.0,
         "plan_source": "test"},
        {"pe": 5.0, "atr": 2.0},
        desk={"by_symbol": {"X": [{"strategy": "long_call", "strike": 100,
                                   "premium_total": 200, "edge_score": 70}]}},
        goals=[],
        enrichment={"pe": 5.0},
    )
    assert packet2["options_alt"]["maps_to_plan"]["strike"] == packet["options_alt"]["maps_to_plan"]["strike"]


def test_render_cio_includes_packet_or_honest_none(monkeypatch):
    desk = {
        "by_symbol": {
            "ACHV": [{"strategy": "covered_call", "strike": 8, "edge_score": 60, "iv_rank": 15}],
        },
    }
    import scripts.lib.cio_options_fluency as mod
    monkeypatch.setattr(mod, "load_options_desk_summary", lambda path=None: desk)
    monkeypatch.setattr(mod, "load_enrichment_row", lambda symbol: {"pe": 12.0, "atr": 0.4})

    result = {
        "symbol": "ACHV", "state": "BUY_READY", "price": 7.25,
        "entry_low": 7.0, "entry_high": 7.5, "stop": 6.5, "target": 10.0,
        "rr": 4.27, "plan_source": "reentry_desk", "distance_pct": 0.0,
        "catalyst": None, "cio_action": None, "held": False,
    }
    from lib.market_cap_label import cap_label
    ev = {"symbol": "ACHV", "market_cap_label": cap_label(744), "pe": 12.0, "atr": 0.4}
    text = ces.render_cio(result, ev)
    assert "Entry state BUY_READY for ACHV" in text
    assert "Confirm or refute" in text or "CIO verdict" in text
    assert "WRONG_STRATEGY_CLASS" in text or "none suitable" in text.lower() or "Options alt" in text
    assert "Thesis:" in text or "PE" in text


def test_render_operator_entry_near_gets_packet(monkeypatch):
    desk = {"by_symbol": {"AXTI": []}}
    import scripts.lib.cio_options_fluency as mod
    monkeypatch.setattr(mod, "load_options_desk_summary", lambda path=None: desk)
    monkeypatch.setattr(mod, "load_enrichment_row", lambda symbol: {"atr": 8.0, "pe": 20.0})
    result = {
        "symbol": "AXTI", "state": "ENTRY_NEAR", "price": 72.93,
        "entry_low": 62.0, "entry_high": 66.0, "stop": 58.5, "target": 96.5,
        "rr": 4.07, "plan_source": "reentry_desk", "distance_pct": 10.5,
        "catalyst": None, "cio_action": None, "held": False,
    }
    from lib.market_cap_label import cap_label
    ev = {"symbol": "AXTI", "market_cap_label": cap_label(2000), "atr": 8.0,
          "formerly_held": True, "plan_source": "reentry_desk", "pe": 20.0}
    text = ces.render_operator(result, ev)
    assert "getting close" in text.lower() or "ENTRY" in text or "CIO entry" in text
    assert "Options alt" in text or "none suitable" in text.lower()
    assert "CIO verdict" in text
    assert "MAA" not in text  # chrome bleed must not invent secondary tickers in body


def test_looks_like_options_strategy_ask():
    assert flu.looks_like_options_strategy_ask("what covered call makes sense on V?")
    assert not flu.looks_like_options_strategy_ask("what's the analyst target for V?")
