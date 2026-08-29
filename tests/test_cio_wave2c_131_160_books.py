"""Wave 2C items 131–136 / 158 — both re-entry books name themselves.

The canonical definitions live in `cio_reentry_surface_labels` and each producer
stamps its own book. Neither book reaches /v3/cio/home, so a reader there saw
two re-entry counts with no way to tell which question each answers — which is
how two books get merged in someone's head while the code keeps them apart.

Labelling is not merging. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from scripts.lib.cio_command_center import build_office_home, build_reentry_book_labels
from scripts.lib.cio_reentry_surface_labels import SURFACE_A, SURFACE_B


def test_both_surfaces_are_named_with_their_question():
    b = build_reentry_book_labels()
    assert b["a"]["surface"] == "A"
    assert b["b"]["surface"] == "B"
    assert "former holdings" in b["a"]["question"]
    assert "risk-reward" in b["b"]["question"]


def test_labels_come_from_the_canonical_module_not_a_second_copy():
    """A second copy of the label text is a second definition waiting to drift."""
    b = build_reentry_book_labels()
    assert b["a"]["question"] == SURFACE_A["question"]
    assert b["b"]["question"] == SURFACE_B["question"]
    assert b["a"]["scope"] == SURFACE_A["scope"]
    assert b["b"]["scope"] == SURFACE_B["scope"]


def test_the_two_books_have_different_producers():
    b = build_reentry_book_labels()
    assert b["a"]["producer"] != b["b"]["producer"]
    assert b["a"]["producer"].endswith("cio_investment_product.build_reentry_book")
    assert b["b"]["producer"].endswith("cio_desk_depth.build_reentry_book")


def test_merged_is_false_and_each_book_disclaims_the_other():
    b = build_reentry_book_labels()
    assert b["merged"] is False
    assert b["a"]["not_this_book"] == SURFACE_A["not_this_book"]
    assert b["b"]["not_this_book"] == SURFACE_B["not_this_book"]


def test_home_carries_the_labels():
    home = build_office_home(operator_product={})
    rb = home["reentry_books"]
    assert rb["a"]["surface"] == "A" and rb["b"]["surface"] == "B"
    assert rb["merged"] is False
    assert home["telegram_sent"] is False


def test_labels_fail_soft_without_blanking_home(monkeypatch):
    import builtins

    real = builtins.__import__

    def _no_labels(name, *a, **k):
        if name == "scripts.lib.cio_reentry_surface_labels":
            raise ImportError("simulated")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_labels)
    b = build_reentry_book_labels()
    assert b["available"] is False
    assert b["merged"] is False          # the invariant survives the failure


def test_dual_pipes_still_report_separate_totals():
    """Overlay must not collapse the queue pipe into the Surface A pipe."""
    from scripts.lib.cio_command_center import overlay_surface_a_reentry_on_opportunities

    opp = overlay_surface_a_reentry_on_opportunities(
        {"reentry": [1, 2, 3], "reentry_total": 3},
        {"count": 70, "counts": {"NEAR": 25, "REENTER": 0}},
    )
    assert opp["queue_reentry_total"] == 3
    assert opp["surface_a_reentry_count"] == 70
    assert opp["surface_a_reentry_near"] == 25
    assert opp["reentry_pipes"]["merged"] is False


def test_cc_names_surface_b_alongside_surface_a():
    """Item 160: the CC named only Surface A; a reader saw one book, not two."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "apps/command-center-v3/src/pages/CioHub.tsx"
    ).read_text(encoding="utf-8")
    assert "cio-home-reentry-surface-a" in src
    assert "books?.b" in src                        # Surface B rendered
    assert "Not merged with Surface A." in src
    assert "ReentryBookLabels" in src               # typed, not any
