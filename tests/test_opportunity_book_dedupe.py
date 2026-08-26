"""P1.6 — Opportunity book symbol dedupe + zone/pct rounding."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_opportunity_book_dedupes_auud_keeping_best_status(monkeypatch, tmp_path):
    from scripts.lib import cio_investment_product as ip

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_attach.thesis_fields_for_symbol",
        lambda sym, **k: {
            "thesis_state": "RESEARCH_REQUIRED",
            "portfolio_role": "UNKNOWN",
            "research_gap_count": 1,
            "research_gaps": ["living thesis"],
            "symbol_thesis_version": None,
        },
    )
    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_attach.opportunity_actionability",
        lambda row: "RESEARCH_REQUIRED",
    )

    queue = {
        "items": [
            {"symbol": "AUUD", "source": "watch", "state": "WAIT", "verdict": None},
            {"symbol": "AUUD", "source": "reentry", "state": "NEAR", "verdict": None},
            {"symbol": "SCHG", "source": "advisory", "verdict": "ADD", "state": "WATCH"},
            {"symbol": "HEALTH", "source": "watch", "state": "WAIT"},  # non-ticker dropped
        ],
    }
    reentry = {
        "names": [
            {
                "symbol": "AUUD",
                "status": "NEAR",
                "thesis": {
                    "thesis_state": "RESEARCH_REQUIRED",
                    "portfolio_role": "UNKNOWN",
                    "research_gap_count": 1,
                    "research_gaps": ["living thesis"],
                },
                "setup": "Zone 1.35–1.6; desk NEAR",
                "pct_above_exit": 12.3456,
            },
        ],
    }
    book = ip.build_opportunity_book(queue, reentry, root=tmp_path)
    symbols = [r["symbol"] for r in book["top"]]
    assert symbols.count("AUUD") == 1
    assert "HEALTH" not in symbols
    auud = next(r for r in book["top"] if r["symbol"] == "AUUD")
    assert auud["status"] == "NEAR"
    assert auud["rank"] == 1
    assert book["deduped_from"] >= 3


def test_fmt_num_and_zone_rounding():
    from scripts.lib.cio_investment_product import _fmt_num, _round_pct, adjudicate_reentry

    assert _fmt_num(1.3469600000000002) == "1.35"
    assert _fmt_num(85.0) == "85"
    assert _round_pct(12.3456) == 12.35

    rec = adjudicate_reentry(
        {
            "symbol": "AUUD",
            "reentry_signal": "WATCH",
            "reentry_zone_low": 1.3469600000000002,
            "reentry_zone_high": 1.5995149999999998,
            "pct_above_exit": 12.3456,
        },
        qitems=[],
        lessons={"lessons": []},
        fs_ok=False,
        infl={"lesson_enhanced": False},
    )
    assert "1.35" in rec["setup"]
    assert "1.6" in rec["setup"] or "1.60" in rec["setup"]
    assert "1.3469600000000002" not in rec["setup"]
