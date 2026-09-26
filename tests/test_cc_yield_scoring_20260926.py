"""Covered-call edge scores premium yield on the configured scale (operator 2026-09-26).

SPCX: $4.10 for 27 days on a $148.57 stock is ~37% annualized, yet the old
``rr * 25`` term gave it under 2 of 20 points (edge 43). Operator: "fix the
covered call scoring". No network or DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import options_engine as oe  # noqa: E402

CFG = {"edge_roc_full_credit_ann_pct": 25.0}


def test_spcx_yield_is_about_37_pct_annualized():
    assert round(oe._cc_yield_ann_pct(4.10, 148.57, 27), 1) == 37.3


def test_rich_premium_now_earns_the_full_yield_points(monkeypatch):
    monkeypatch.setattr(oe, "_DESK_CFG", dict(CFG))
    kw = dict(pop=70.3, iv_rank=38.0, catalyst_boost=3.0, conviction=0.6)
    old = oe._edge_score(rr=0.373, **kw)
    new = oe._edge_score(rr=0.373, yield_ann_pct=oe._cc_yield_ann_pct(4.10, 148.57, 27), **kw)
    assert new - old > 17.0


def test_thin_premium_still_scores_low(monkeypatch):
    monkeypatch.setattr(oe, "_DESK_CFG", dict(CFG))
    kw = dict(pop=83.0, iv_rank=20.0, rr=0.0, catalyst_boost=3.0, conviction=0.6)
    thin = oe._edge_score(yield_ann_pct=oe._cc_yield_ann_pct(0.05, 53.0, 27), **kw)
    rich = oe._edge_score(yield_ann_pct=30.0, **kw)
    assert rich - thin > 15.0


def test_callers_without_yield_keep_the_old_term():
    assert oe._edge_score(70.0, 40.0, 0.5, conviction=0.5) == oe._edge_score(70.0, 40.0, 0.5, conviction=0.5, yield_ann_pct=None)


def test_both_covered_call_paths_pass_yield():
    src = (ROOT / "scripts" / "options_engine.py").read_text(encoding="utf-8")
    assert src.count("yield_ann_pct=_cc_yield_ann_pct(premium, und, dte)") == 2
    assert "chain_lookup=resolve_chain, price=price" in src
