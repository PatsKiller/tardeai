"""Hermetic Flash CIO soak observer — no live DB."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.observe_flash_cio_soak import observe_flash_cio_soak, main

_NOW = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)

FIXTURE = {
    "held_symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "META"],
    "rows": [
        {
            "symbol": "AAPL",
            "updated_at": "2026-09-09T12:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "VOTED",
                "participating_lanes": ["grok", "chatgpt", "deepseek-flash"],
            },
        },
        {
            "symbol": "MSFT",
            "updated_at": "2026-09-09T13:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "VOTED",
                "participating_lanes": ["grok", "deepseek-flash"],
            },
        },
        {
            "symbol": "NVDA",
            "updated_at": "2026-09-09T14:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "VOTED",
                "participating_lanes": ["chatgpt", "deepseek-flash"],
            },
        },
        {
            "symbol": "AMZN",
            "updated_at": "2026-09-09T15:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "VOTED",
                "participating_lanes": ["deepseek-flash"],
            },
        },
        {
            "symbol": "META",
            "updated_at": "2026-09-09T16:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "VOTED",
                "participating_lanes": ["grok", "chatgpt", "deepseek-flash"],
            },
        },
        {
            "symbol": "TSLA",
            "updated_at": "2026-09-09T17:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "VOTED",
                "participating_lanes": ["grok", "chatgpt", "deepseek-flash"],
            },
            "held": False,
        },
        {
            "symbol": "OLD",
            "updated_at": "2026-01-01T00:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "VOTED",
                "participating_lanes": ["deepseek-flash"],
            },
        },
        {
            "symbol": "SKIP",
            "updated_at": "2026-09-09T18:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "SKIPPED_PEAK",
                "participating_lanes": ["grok", "chatgpt"],
            },
        },
        {
            "symbol": "FALLBACK",
            "updated_at": "2026-09-09T19:00:00Z",
            "dual_consensus_json": {
                "deepseek_status": "FALLBACK_SYNTH",
                "participating_lanes": ["deepseek-flash"],
            },
        },
    ],
}


def test_observe_flash_voted_claim_observed():
    report = observe_flash_cio_soak(
        FIXTURE["rows"],
        window_days=14,
        min_n=5,
        held_only=False,
        now=_NOW,
    )
    assert report["flash_voted_n"] == 6  # five held + TSLA; OLD out of window; SKIP/FALLBACK out
    assert report["claim"] == "OBSERVED"
    assert "AAPL" in report["symbols"]
    assert "OLD" not in report["symbols"]
    assert "SKIP" not in report["symbols"]
    assert "FALLBACK" not in report["symbols"]
    assert report["not_counted"] == ["on_demand_challengers"]
    assert report["mbi_behavior"] == 0


def test_observe_held_only_and_pending():
    report = observe_flash_cio_soak(
        FIXTURE["rows"],
        window_days=14,
        min_n=5,
        held_only=True,
        held_symbols=set(FIXTURE["held_symbols"]),
        now=_NOW,
    )
    assert report["flash_voted_n"] == 5
    assert "TSLA" not in report["symbols"]
    assert report["claim"] == "OBSERVED"


def test_observe_pending_below_min_n():
    report = observe_flash_cio_soak(
        FIXTURE["rows"][:2],
        window_days=14,
        min_n=5,
        held_only=False,
        now=_NOW,
    )
    assert report["flash_voted_n"] == 2
    assert report["claim"] == "PENDING"


def test_cli_json_in(tmp_path: Path):
    path = tmp_path / "flash_soak_fixture.json"
    path.write_text(json.dumps(FIXTURE), encoding="utf-8")
    out = tmp_path / "out.json"
    rc = main(
        [
            "--json-in",
            str(path),
            "--window-days",
            "14",
            "--min-n",
            "5",
            "--held-only",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["flash_voted_n"] == 5
    assert body["claim"] == "OBSERVED"
    assert body["mbi_behavior"] == 0
    assert body["not_counted"] == ["on_demand_challengers"]
