"""Live Schwab Options Desk — Stage A/B/C/E regressions (2026-09-25).

Advisory only. Never enables live, never widens max_spread_pct, never broker writes.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_enterprise_enrich_source_never_reads_paper_validation():
    """Regression: live_eligible must not consult paper n/30 / validation_status."""
    src = (ROOT / "scripts" / "options_desk_enterprise.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                forbidden_imports.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            forbidden_imports.add(mod)
            for a in node.names:
                if a.name in ("validation_status", "compute_gate_metrics", "n_closed"):
                    pytest.fail(f"enterprise imports validation symbol {a.name}")
    assert "validation" not in forbidden_imports
    # Function body must not mention paper ledger fields as live gates.
    fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "enterprise_enrich_proposal":
            fn = node
            break
    assert fn is not None
    body = ast.get_source_segment(src, fn) or ""
    for bad in ("n_closed", "validation_status", "min_closed_paper", "gate_met"):
        assert bad not in body, f"enterprise_enrich_proposal references {bad}"


def test_pick_chain_prefers_two_sided_liquid_quote_near_target():
    oe = _load("options_engine_stage_b", "scripts/options_engine.py")
    chain = {
        "status": "ok",
        "expirations": [
            {
                "exp": "2026-10-17",
                "dte": 30,
                "strikes": [
                    # Nearest strike but zero bid / absurd spread
                    {"side": "call", "strike": 350.0, "bid": 0.0, "ask": 2.0, "last": 1.0,
                     "iv": 25, "delta": 0.3, "oi": 10, "volume": 0},
                    # Slightly farther, two-sided, tight spread, higher OI
                    {"side": "call", "strike": 352.5, "bid": 1.80, "ask": 1.95, "last": 1.87,
                     "iv": 24, "delta": 0.28, "oi": 500, "volume": 40},
                ],
            }
        ],
    }
    picked = oe._pick_chain_contract(chain, "call", 350.0, 30)
    assert picked is not None
    assert picked["strike"] == 352.5
    assert picked["bid"] == 1.80
    assert picked.get("bid_ask_spread_pct") is not None
    assert picked["bid_ask_spread_pct"] < 20


def test_need_100_carries_shares_short_and_alternate_hint():
    oe = _load("options_engine_stage_c", "scripts/options_engine.py")
    row = oe.evaluate_covered_call_status(
        {"symbol": "SCHG", "shares": 11.2, "price": 30.0, "market_value": 336.0, "account": "ira"},
        tech_map={},
        intent_cfg={},
        resolve_chain=False,
    )
    assert row["status"] == "NEED_100_SHARES"
    assert row["shares_short"] == pytest.approx(88.8, abs=0.01)
    assert "buy_to_lot" in row["alternate_hint"]
    assert "never" in row["alternate_hint"]
    assert "fake" in row["detail"].lower() or "refused" in row["detail"].lower()


def test_alpaca_submit_refuses_desk_path_b_strategy(monkeypatch):
    ap = _load("alpaca_paper_stage_e", "scripts/lib/options_pipeline/alpaca_paper.py")

    class FakeEx:
        def __call__(self, *a, **k):
            return None

    row = {
        "proposal_id": "p1",
        "status": ap.STATE_READY,
        "strategy": "covered_call",
        "proposal_json": {
            "strategy": "covered_call",
            "educational_paper_model": False,
            "paper_only": False,
            "symbol": "V",
        },
    }
    monkeypatch.setattr(ap, "get_queue_row", lambda *a, **k: row)
    monkeypatch.setattr(ap, "build_order_payload", lambda *a, **k: {"symbol": "X", "limit_price": 1.0, "time_in_force": "day"})
    with pytest.raises(ap.OperatorActionRequiredError) as ei:
        ap.submit_ready_proposal("p1", confirm=True, dry_run=False, executor=FakeEx())
    assert "Path B" in str(ei.value) or "Schwab" in str(ei.value)

def test_options_engine_excludes_alpaca_holdings_from_desk_book():
    oe = _load("options_engine_schwab_only", "scripts/options_engine.py")
    alp = oe._execution_profile("alpaca_paper")
    assert alp.get("options_desk_excluded") is True
    assert alp.get("auto_eligible") is False
    schwab = oe._execution_profile("schwab_taxable")
    assert schwab.get("broker") == "schwab"
    assert schwab.get("options_desk_excluded") is not True


def test_options_alpaca_mark_ready_refuses_schwab_only_desk():
    """API handlers return 403 options_desk_schwab_only (Alpaca lane retired)."""
    import importlib.util
    # Load only the refuse helpers by evaluating source snippets is brittle;
    # assert the refuse reason string is present on every alpaca-paper handler.
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    for name in (
        "_options_alpaca_mark_ready",
        "_options_alpaca_submit",
        "_options_alpaca_reconcile",
        "_options_alpaca_record_outcome",
        "_options_alpaca_promote_live_review",
    ):
        assert name in src
    assert src.count("options_desk_schwab_only") >= 5


def test_stamp_cio_hub_strip_defined_and_stamps_entry_state():
    """Regression 2026-09-25: call site shipped without the helper → NameError blanked Ideas."""
    oe = _load("options_engine_cio_strip", "scripts/options_engine.py")
    assert callable(getattr(oe, "_stamp_cio_hub_strip", None))
    props = [{"symbol": "V", "strategy": "covered_call"}, {"symbol": "ZZZ", "strategy": "long_call"}]
    out = oe._stamp_cio_hub_strip(
        props,
        [
            {
                "symbol": "V",
                "source": "entry_state",
                "entry_state": "BUY_READY",
                "bias": "bullish",
                "confidence": 0.62,
                "summary": "BUY_READY entry",
                "volatility_elevated": False,
            }
        ],
    )
    assert out[0]["cio"]["entry_state"] == "BUY_READY"
    assert out[0]["cio"]["bias"] == "bullish"
    assert "cio" not in out[1]

