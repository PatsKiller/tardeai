"""Slice 7: NEW_POSITION_IF carries thesis fields or UNAVAILABLE, never a fake thesis."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_investment_product import build_product


def test_not_former_with_fields_shows_them(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    (tmp_path / "data" / "cio").mkdir(parents=True)

    def fake_thesis(sym, **k):
        if str(sym).upper() == "NKE":
            return {
                "has_current_symbol_thesis": True,
                "thesis_state": "CURRENT",
                "thesis_summary": "Quality consumer franchise.",
                "why_owned_or_watched": "Quality consumer franchise.",
            }
        return {
            "has_current_symbol_thesis": False,
            "thesis_state": "INSUFFICIENT_DATA",
            "thesis_unavailable_reason": "no living symbol thesis",
        }

    monkeypatch.setattr(
        "scripts.lib.symbol_thesis_attach.thesis_fields_for_symbol", fake_thesis,
    )
    queue = {"items": [
        {"symbol": "NKE", "source": "defense", "state": "WATCH"},
        {"symbol": "SH", "source": "defense", "state": "WATCH"},
    ]}
    p = build_product(root=tmp_path, queue=queue, previously_traded=[], holdings={})
    rows = {r["symbol"]: r for r in p["action_book"]["NEW_POSITION_IF"]}
    assert rows["NKE"]["thesis_status"] == "CURRENT"
    assert "franchise" in (rows["NKE"].get("why_owned_or_watched") or "")
    assert rows["SH"]["thesis_status"] == "UNAVAILABLE"
    assert rows["SH"]["thesis_status_reason"]
    assert not rows["SH"].get("why_owned_or_watched")
