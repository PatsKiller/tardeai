"""Wave 2 slice 06: earnings days_to_event + source as_of."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from scripts.lib.cio_investment_product import collect_earnings_events


def test_days_to_event_and_as_of(tmp_path, monkeypatch):
    root = tmp_path
    state = root / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "earnings_dates.json").write_text(json.dumps({
        "NOC": {"earnings_date": "2026-10-20", "fetched_at": "2026-08-24T08:34:39"},
    }))
    monkeypatch.setenv("TRADEAI_ROOT", str(root))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(root))
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    out = collect_earnings_events(
        root=root,
        holdings={"holdings": [{"symbol": "NOC", "shares": 10}]},
        now=now,
    )
    assert out["quality"] == "OK"
    assert out["as_of"]
    assert out["source"].endswith("earnings_dates.json")
    row = out["items"][0]
    assert row["symbol"] == "NOC"
    assert row["days_to_event"] == (date(2026, 10, 20) - date(2026, 8, 28)).days
    assert row["as_of"]
    assert row.get("source_as_of") == "2026-08-24T08:34:39"


def test_missing_file_empty_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    out = collect_earnings_events(root=tmp_path, holdings={"holdings": []})
    assert out["items"] == []
    assert out["quality"] == "DATA_UNAVAILABLE"
    assert out["as_of"]
