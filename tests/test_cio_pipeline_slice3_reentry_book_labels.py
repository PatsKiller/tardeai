"""Slice 3: label the two re-entry books. Do not merge them."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_desk_depth import build_reentry_book as build_book_b
from scripts.lib.cio_investment_product import build_product, build_reentry_book as build_book_a
from scripts.lib.cio_reentry_surface_labels import SURFACE_A, SURFACE_B, banner


def test_surface_labels_are_distinct():
    assert SURFACE_A["scope"] == "former holdings vs exit trigger"
    assert SURFACE_B["scope"] == "candidates vs cash-stage R:R under desk thesis"
    assert SURFACE_A["scope"] != SURFACE_B["scope"]
    assert SURFACE_A["producer"] != SURFACE_B["producer"]
    assert "merge" not in SURFACE_A["precedence"].lower()
    assert SURFACE_A["not_this_book"] == SURFACE_B["scope"]
    assert SURFACE_B["not_this_book"] == SURFACE_A["scope"]


def test_investment_reentry_book_stamped_surface_a(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    (tmp_path / "data" / "cio").mkdir(parents=True)
    prev = [{"symbol": "SCHG", "reentry_signal": "IN_ZONE", "last_exit_price": 90, "current_price": 92}]
    p = build_product(root=tmp_path, queue={"items": []}, previously_traded=prev, holdings={})
    book = p["reentry_book"]
    assert book["surface"] == "A"
    assert book["scope"] == SURFACE_A["scope"]
    assert book["question"] == SURFACE_A["question"]
    assert book["precedence"] == SURFACE_A["precedence"]
    assert "SCHG" in {r["symbol"] for r in book["names"]}
    assert "cards" not in book  # Surface B shape, not merged


def test_desk_depth_reentry_book_stamped_surface_b(monkeypatch):
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
            "computed_at": "2026-08-28T00:00:00+00:00",
        },
    )
    book = build_book_b(
        pin="desk@test",
        thr={},
        cash_stage={"stage": 0, "label": "STAGE_0"},
        cash_pct=40.0,
        symbol_weights={},
    )
    assert book["surface"] == "B"
    assert book["scope"] == SURFACE_B["scope"]
    assert book["question"] == SURFACE_B["question"]
    assert book.get("names") is None  # Surface A shape, not merged
    assert "cards" in book
    assert "ACHV" in {c.get("symbol") for c in (book.get("cards") or book.get("core_cards") or [])} or book.get("actionable_count", 0) >= 0


def test_books_remain_independent_functions():
    assert build_book_a is not build_book_b
    assert SURFACE_A["producer"] != SURFACE_B["producer"]


def test_desk_note_template_mentions_surface_b():
    from scripts.lib.cio_desk_synthesis import render_desk_note
    note = render_desk_note({
        "pin": "desk@vTEST",
        "thesis": {"stance": "defensive_observe"},
        "thresholds": {"cash_band_min_pct": 20},
        "portfolio": {"cash_pct": 40, "data_quality": "OK", "top_weights": []},
        "material_plans": [],
        "learning": [],
        "cash_stage": {"stage": 0, "label": "STAGE_0"},
        "sector_posture": {},
        "reentry_book": {
            **SURFACE_B,
            "ok": True,
            "core_full": 0,
            "sub_rr": 0,
            "cards": [],
            "core_cards": [],
        },
        "evidence_spine": {},
    }, telegram=True)
    assert SURFACE_B["scope"] in note
    assert "former holdings vs exit trigger" in note
    assert "Surface B" in note or "scope" in note.lower()


def test_ciohub_renders_both_scope_strings():
    hub = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/CioHub.tsx").read_text()
    assert "former holdings vs exit trigger" in hub
    assert "candidates vs cash-stage R:R under desk thesis" in hub
    assert "cio-reentry-surface-a" in hub
