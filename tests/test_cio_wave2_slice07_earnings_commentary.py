"""Wave 2 slice 07: earnings commentary 1-line or UNAVAILABLE. Cap 10."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.lib.cio_investment_product import collect_earnings_events


def test_commentary_unavailable_without_transcript(tmp_path, monkeypatch):
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "earnings_dates.json").write_text(json.dumps({
        "NOC": {"earnings_date": "2026-10-20", "fetched_at": "2026-08-24T08:34:39"},
    }))
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    out = collect_earnings_events(
        root=tmp_path,
        holdings={"holdings": [{"symbol": "NOC", "shares": 10}]},
        now=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    row = out["items"][0]
    assert row["commentary"] == "UNAVAILABLE"
    assert row["commentary_reason"] == "no_earnings_transcript_row"
    assert "4150" not in json.dumps(row)
