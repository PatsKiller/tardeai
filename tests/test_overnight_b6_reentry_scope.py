"""Overnight B6 — each re-entry book states its question and population.

Wave contract (WAVE_12 E2 / overnight B6):
  The two re-entry books answer different questions and are both correct.
  Each states the question it answers and the population it scores.
  Do not merge them. Do not introduce a precedence winner.

Canonical definitions: ``scripts/lib/cio_reentry_surface_labels``.
Surface A stamped by ``cio_investment_product.build_reentry_book``.
Surface B stamped by ``cio_desk_depth.build_reentry_book``.

This file is on the hardening CI allowlist. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_desk_depth import build_reentry_book as build_book_b
from scripts.lib.cio_investment_product import build_product
from scripts.lib.cio_reentry_surface_labels import SURFACE_A, SURFACE_B, banner, stamp


def test_canonical_surfaces_state_question_and_population():
    for sfc in (SURFACE_A, SURFACE_B):
        assert sfc["question"].strip(), f"Surface {sfc['surface']} missing question"
        assert sfc["population"].strip(), f"Surface {sfc['surface']} missing population"
        assert "?" in sfc["question"]
    assert SURFACE_A["question"] != SURFACE_B["question"]
    assert SURFACE_A["population"] != SURFACE_B["population"]
    assert SURFACE_A["scope"] != SURFACE_B["scope"]
    assert SURFACE_A["producer"] != SURFACE_B["producer"]


def test_stamp_writes_question_and_population_without_merging_payloads():
    a = stamp({"names": [{"symbol": "SCHG"}], "count": 1}, SURFACE_A)
    b = stamp({"cards": [{"symbol": "ACHV"}], "ok": True}, SURFACE_B)
    assert a["question"] == SURFACE_A["question"]
    assert a["population"] == SURFACE_A["population"]
    assert b["question"] == SURFACE_B["question"]
    assert b["population"] == SURFACE_B["population"]
    # Shapes stay independent — no merge of names into cards or vice versa.
    assert "names" in a and "cards" not in a
    assert "cards" in b and "names" not in b
    assert a["surface"] == "A" and b["surface"] == "B"


def test_no_precedence_winner_rule():
    """``precedence`` disclaims authority; it must not crown a winner."""
    for sfc in (SURFACE_A, SURFACE_B):
        text = sfc["precedence"].lower()
        assert "winner" not in text
        assert "overrides" not in text
        assert "takes precedence over" not in text
        assert "only" in text  # authoritative only for its own question


def test_banner_names_population_and_disclaims_the_other_book():
    ba = banner(SURFACE_A)
    bb = banner(SURFACE_B)
    assert SURFACE_A["population"] in ba
    assert SURFACE_B["population"] in bb
    assert SURFACE_A["not_this_book"] in ba
    assert SURFACE_B["not_this_book"] in bb
    assert "Surface A" in ba and "Surface B" in bb


def test_surface_a_builder_stamps_question_and_population(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    (tmp_path / "data" / "cio").mkdir(parents=True)
    prev = [{"symbol": "SCHG", "reentry_signal": "IN_ZONE", "last_exit_price": 90, "current_price": 92}]
    book = build_product(root=tmp_path, queue={"items": []}, previously_traded=prev, holdings={})[
        "reentry_book"
    ]
    assert book["surface"] == "A"
    assert book["question"] == SURFACE_A["question"]
    assert book["population"] == SURFACE_A["population"]
    assert "SCHG" in {r["symbol"] for r in book["names"]}


def test_surface_b_builder_stamps_question_and_population(monkeypatch):
    monkeypatch.setattr(
        "scripts.lib.cio_desk_depth.fetch_reentry_rows",
        lambda: {
            "ok": True,
            "rows": [
                {
                    "symbol": "ACHV",
                    "price": 20,
                    "rr": 2.1,
                    "intel": {"state": "NEAR ENTRY", "distance_pct": 3},
                    "advisory": {"confirmations_complete": True},
                }
            ],
            "computed_at": "2026-08-31T00:00:00+00:00",
        },
    )
    book = build_book_b(
        pin="desk@b6",
        thr={},
        cash_stage={"stage": 0, "label": "STAGE_0"},
        cash_pct=40.0,
        symbol_weights={},
    )
    assert book["surface"] == "B"
    assert book["question"] == SURFACE_B["question"]
    assert book["population"] == SURFACE_B["population"]
    assert "cards" in book


def test_producers_remain_separate_in_source():
    """Guard against a future merge of the two build_reentry_book call sites."""
    root = Path(__file__).resolve().parents[1]
    a_src = (root / "scripts/lib/cio_investment_product.py").read_text(encoding="utf-8")
    b_src = (root / "scripts/lib/cio_desk_depth.py").read_text(encoding="utf-8")
    # Investment product stamps Surface A only; desk depth stamps Surface B only.
    assert "SURFACE_A" in a_src and "_stamp_scope" in a_src
    assert "SURFACE_B" not in a_src
    assert "SURFACE_B" in b_src and "_stamp_scope" in b_src
    assert "SURFACE_A" not in b_src
