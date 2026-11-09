"""LQ-20261107-1688 — the cash sweep is a row, not a ticker.

Measured on the served API 2026-11-09 15:18 ET (page defect 192): ``/api/v2/rotation/summary``
published ``CASH`` as its top rotation candidate — $840,191.81 x 855,076.99 shares at $77.16,
trim 25, concentration 68.12%, and "CASH -> SPCX/NVDA" rotate ideas. ``positions_current`` holds
one synthetic row per account with ``symbol='CASH', is_cash=true`` (positions_sync.py:236-238 and
every broker reader); the symbol-card layer resolves the symbol CASH to Pathward Financial
(ticker CASH), so the sweep row was enriched, scored and paired like a holding.

The engine now drops cash rows with the repo's one predicate
(``lib.holdings_universe.is_cash_row``) before enrichment, scoring and idea pairing. The
denominator still comes from ``portfolio_totals.total_value``, which includes cash, so every real
holding keeps the weight it had.

Each test runs the real engine as a script on a synthetic holdings document: no database, no
network, synthetic tickers (ZQ*) and a synthetic card, so nothing here is live data.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "rotation_intelligence_engine.py"


def _run(tmp_path: Path, holdings: dict, cards: dict | None = None) -> dict:
    src = tmp_path / "holdings_ZQ.json"
    src.write_text(json.dumps(holdings), encoding="utf-8")
    argv = [sys.executable, str(SCRIPT), "--input", str(src)]
    if cards is not None:
        card_path = tmp_path / "cards_ZQ.json"
        card_path.write_text(json.dumps(cards), encoding="utf-8")
        argv += ["--cards", str(card_path)]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def _sweep_book() -> dict:
    """The incident's shape, scaled down: a $700 cash sweep against a $1,000 book, plus a money
    market fund and one real equity."""
    return {
        "portfolio_totals": {"total_value": 1000.0},
        "holdings": [
            {"symbol": "CASH", "market_value": 700.0, "account_key": "zq_rollover_ira",
             "is_cash": True, "asset_type": "CASH"},
            {"symbol": "SPAXX", "market_value": 50.0, "account_key": "zq_rollover_ira"},
            {"symbol": "ZQAAA", "market_value": 250.0, "account_key": "zq_taxable",
             "sector": "Industrials"},
        ],
    }


def test_the_cash_sweep_is_never_a_rotation_candidate(tmp_path):
    out = _run(tmp_path, _sweep_book())
    symbols = [c["symbol"] for c in out["top_candidates"]]

    assert symbols == ["ZQAAA"], f"cash entered the candidate list: {symbols}"
    assert out["data_quality"]["cash_rows_excluded"] == 2
    assert out["data_quality"]["holding_rows"] == 1
    for idea in out["top_rotation_ideas"]:
        assert idea["from_symbol"] not in {"CASH", "SPAXX", "ZQAAA"} or idea["to_symbol"] != "CASH"
        assert "CASH" not in (idea["from_symbol"], idea["to_symbol"])


def test_a_real_holding_keeps_its_weight_with_cash_still_in_the_denominator(tmp_path):
    out = _run(tmp_path, _sweep_book())
    zq = next(c for c in out["top_candidates"] if c["symbol"] == "ZQAAA")

    # 250 / 1000: the denominator still includes the excluded cash, so dropping the row does not
    # inflate the remaining holdings' concentration.
    assert zq["evidence"]["concentration_pct"] == 25.0
    assert "concentration_review" not in zq["evidence"] or zq["trim_score"] < 25.0


def test_a_sweep_row_without_the_flag_is_still_cash(tmp_path):
    """asset_type alone, and a known sweep symbol alone, are both cash (holdings_universe).

    A money-market symbol OUTSIDE ``CASH_SYMBOLS`` (FCASH, CORE, SWVXX) is only cash when its
    producer sets ``is_cash``/``asset_type``; that is the shared predicate's documented limit, not
    a gap this engine should paper over with a second list.
    """
    book = {
        "portfolio_totals": {"total_value": 1000.0},
        "holdings": [
            {"symbol": "ZQSWEEP", "market_value": 600.0, "account_key": "zq_ira",
             "asset_type": "CASH"},
            {"symbol": "VMFXX", "market_value": 100.0, "account_key": "zq_ira"},
            {"symbol": "ZQBBB", "market_value": 300.0, "account_key": "zq_ira"},
        ],
    }
    out = _run(tmp_path, book)
    assert [c["symbol"] for c in out["top_candidates"]] == ["ZQBBB"]
    assert out["data_quality"]["cash_rows_excluded"] == 2


def test_a_cash_row_is_never_symbol_card_enriched(tmp_path):
    """The Pathward resolution: a card for the symbol CASH must not reach any candidate."""
    cards = {"cards": [{"symbol": "CASH", "sector": "Financial Services",
                        "analyst_upside_pct": 42.0, "instrument_type": "Equity"}],
             "symbols": [{"symbol": "ZQAAA", "sector": "Industrials"}]}
    out = _run(tmp_path, _sweep_book(), cards=cards)

    assert [c["symbol"] for c in out["top_candidates"]] == ["ZQAAA"]
    zq = out["top_candidates"][0]
    assert zq["sector"] == "Industrials", "the cash card's sector leaked onto a real holding"
    assert out["summary"]["rotation_ideas"] == 0, "a cash row was paired into a rotation idea"


def test_the_fallback_denominator_still_includes_cash(tmp_path):
    """No `portfolio_totals`: the engine falls back to summing the document, cash included.

    cc-deepseek-7 review F1. The fallback used to sum every row; dropping cash from the rows it
    iterated would have made the same holding read 100% instead of 25% — a latent, silent change of
    meaning in the one path no live caller uses today (the live document always carries total_value).
    """
    book = _sweep_book()
    del book["portfolio_totals"]
    out = _run(tmp_path, book)

    assert [c["symbol"] for c in out["top_candidates"]] == ["ZQAAA"]
    assert out["data_quality"]["cash_rows_excluded"] == 2
    assert out["top_candidates"][0]["evidence"]["concentration_pct"] == 25.0


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
