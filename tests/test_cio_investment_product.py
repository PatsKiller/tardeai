"""Program 3.5 — CIO investment product (books + adjudication + worker wiring)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_investment_product import (
    adjudicate_reentry,
    apply_governed_verdicts,
    build_investment_product_synthesis_fn,
    build_product,
    persist_product,
)
from scripts.cio_wake_dispatch_entrypoint import main as entry_src


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "cio").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    monkeypatch.setenv("RATIFIED_LESSON_ADVISORY_INFLUENCE", "SHADOW")
    monkeypatch.setenv("FINANCIAL_SENSES_ADVISORY_INFLUENCE", "SHADOW")
    monkeypatch.setenv("GOVERNED_MEMORY_ADVISORY_INFLUENCE", "SHADOW")
    return tmp_path


def test_in_zone_is_not_reenter():
    rec = adjudicate_reentry(
        {"symbol": "SCHG", "reentry_signal": "IN_ZONE", "last_exit_price": 20, "current_price": 21},
        qitems=[],
        lessons={"lessons": []},
        fs_ok=False,
        infl={"lesson_enhanced": False},
    )
    assert rec["status"] in {"NEAR", "WAIT"}
    assert rec["governed_verdict"] is None


def test_explicit_queue_reenter_is_governed():
    rec = adjudicate_reentry(
        {"symbol": "CSCO", "reentry_signal": "IN_ZONE"},
        qitems=[{"source": "reentry", "verdict": "RE_ENTER", "symbol": "CSCO"}],
        lessons={"lessons": []},
        fs_ok=True,
        infl={"lesson_enhanced": True},
    )
    assert rec["status"] == "REENTER"
    assert rec["governed_verdict"] == "RE_ENTER"


def test_above_zone_avoid():
    rec = adjudicate_reentry(
        {"symbol": "ANET", "reentry_signal": "ABOVE_ZONE", "pct_above_exit": 40},
        qitems=[],
        lessons={"lessons": []},
        fs_ok=True,
        infl={"lesson_enhanced": True},
    )
    assert rec["status"] == "AVOID"
    assert rec["governed_verdict"] is None


def test_queue_reentry_names_enter_book_without_prev_table(root: Path):
    queue = {"items": [
        {"symbol": "ANET", "source": "reentry", "directive_label": "Re-entry NEAR ENTRY — ANET"},
        {"symbol": "CSCO", "source": "reentry", "directive_label": "Re-entry NEAR ENTRY — CSCO"},
        {"symbol": "SCHG", "source": "advisory", "verdict": "ADD", "directive_label": "watch SCHG"},
    ]}
    p = build_product(root=root, queue=queue, previously_traded=[], holdings={})
    names = {r["symbol"]: r for r in p["reentry_book"]["names"]}
    assert "ANET" in names and "CSCO" in names
    assert names["ANET"]["status"] in {"NEAR", "WAIT"}
    assert names["ANET"]["governed_verdict"] is None
    assert "SCHG" not in names  # advisory ADD alone is opportunity book, not former-holding book


def test_product_books(root: Path):
    prev = [
        {"symbol": "SCHG", "reentry_signal": "IN_ZONE", "last_exit_price": 90, "current_price": 92,
         "reentry_zone_low": 85, "reentry_zone_high": 95, "pct_above_exit": 2},
        {"symbol": "ANET", "reentry_signal": "ABOVE_ZONE", "pct_above_exit": 80},
    ]
    queue = {"items": [
        {"symbol": "XYZ", "source": "advisory", "verdict": "ADD", "directive_label": "research add"},
        {"symbol": "CSCO", "source": "reentry", "verdict": "RE_ENTER", "state": "READY TO REVIEW"},
    ], "top": [], "count": 2}
    prev.append({"symbol": "CSCO", "reentry_signal": "IN_ZONE", "last_exit_price": 40, "current_price": 41})
    p = build_product(root=root, queue=queue, previously_traded=prev, holdings={"cash": 25000})
    assert p["schema"] == "CIOInvestmentProduct@v1"
    assert p["financial_action"] is False
    assert p["memory_behavior_influence"] == "0"
    assert p["temperament"]["title"]
    names = {r["symbol"]: r for r in p["reentry_book"]["names"]}
    assert names["SCHG"]["governed_verdict"] is None
    assert names["CSCO"]["governed_verdict"] == "RE_ENTER"
    assert names["ANET"]["status"] == "AVOID"
    assert p["recommendations"]
    assert any(r.get("symbol") == "CSCO" for r in p["recommendations"])
    merged = apply_governed_verdicts(queue, p["governed_verdicts"])
    csco = [i for i in merged["items"] if i["symbol"] == "CSCO"][0]
    assert csco["verdict"] == "RE_ENTER"


def test_persist_and_synthesis(root: Path):
    p = persist_product(build_product(root=root, queue={"items": []}, previously_traded=[], holdings={}), root=root)
    assert (root / "data/cio/cio_investment_brief.json").is_file()
    fn = build_investment_product_synthesis_fn(root=root)
    out = fn({"run_id": "r1"}, {"snapshot_id": "s1"}, {"artifacts": []}, {})
    assert out["recommendations"] != []
    assert out["final_position"] == "HOLD"
    assert out["authority"] == "READ_ONLY_ADVISORY"


def test_entrypoint_wires_synthesis():
    text = Path(entry_src.__code__.co_filename).read_text()
    assert "build_investment_product_synthesis_fn" in text
    assert "CIOActionLedger" in text
    assert "NotificationOutbox" in text
    assert "CIORunWorker(run_store=run_store, mode=\"shadow\")" not in text


def test_cc_tab():
    hub = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/CioHub.tsx").read_text()
    assert "investment-books" in hub
    assert "cio-investment-books" in hub
    assert "INVESTMENT BOOKS" in hub


def test_no_broker():
    text = (Path(__file__).resolve().parent.parent / "scripts/lib/cio_investment_product.py").read_text()
    for needle in ("place_order", "cancel_order", "broker.submit"):
        assert needle not in text
