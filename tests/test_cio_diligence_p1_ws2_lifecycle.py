"""P1-WS2 event lifecycle census — help + dry run on tmp fixtures."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cio_event_lifecycle_census.py"
BASELINE = ROOT / "docs" / "audits" / "diligence" / "P1_WS2_EVENT_LIFECYCLE_BASELINE_2026-08-30.md"
OPS = ROOT / "docs" / "ops" / "CIO_DILIGENCE_P1_WS2_2026-08-30.md"
SCOREBOARD = ROOT / "docs" / "ops" / "CIO_DILIGENCE_SCOREBOARD.json"
GAPS = ROOT / "docs" / "audits" / "CIO_DILIGENCE_GAP_REGISTER.md"


def test_census_help():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "lifecycle" in proc.stdout.lower() or "census" in proc.stdout.lower()
    assert "--json" in proc.stdout


def test_census_dry_run_tmp_fixtures(tmp_path: Path):
    """Fail-soft census on an empty-ish tree; must exit 0 and emit schema."""
    data = tmp_path / "data"
    (data / "cio").mkdir(parents=True)
    (data / "portfolios" / "state").mkdir(parents=True)
    (data / "runtime").mkdir(parents=True)
    (data / "hermes" / "momentum_catalysts").mkdir(parents=True)

    # Minimal holdings + empty-ish peers
    holdings = {
        "as_of": "2026-08-30T00:00:00+00:00",
        "holdings": [
            {"symbol": "AAA", "quantity": 1, "is_cash": False},
            {"symbol": "CASH", "quantity": 100, "is_cash": True},
        ],
        "resolved_sectors": [{"sector": "Technology"}],
    }
    (data / "portfolios" / "state" / "holdings.json").write_text(
        json.dumps(holdings), encoding="utf-8"
    )
    (data / "runtime" / "sector_momentum_latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-08-30T00:00:00+00:00",
                "rows": [
                    {"etf": "XLK", "sector": "Technology", "state": "LEADING", "book_pct": 1.0}
                ],
                "not_decomposed": {"positions": []},
            }
        ),
        encoding="utf-8",
    )
    (data / "runtime" / "industry_momentum_latest.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-08-30T00:00:00+00:00",
                "industries": [{"industry": "Semiconductors", "state": "IMPROVING"}],
                "counts": {"n": 1},
            }
        ),
        encoding="utf-8",
    )
    (data / "cio" / "catalyst_graph_latest.json").write_text(
        json.dumps(
            {
                "schema": "CatalystGraph@v1",
                "nodes": [],
                "traces": [],
                "skipped": {"symbol_not_registered": 3},
            }
        ),
        encoding="utf-8",
    )
    (data / "portfolios" / "state" / "earnings_dates.json").write_text(
        json.dumps({"AAA": {"earnings_date": "2026-10-01", "fetched_at": "2026-08-30"}}),
        encoding="utf-8",
    )
    (data / "hermes" / "momentum_catalysts" / "2026-08-30_catalysts.jsonl").write_text(
        json.dumps(
            {
                "symbol": "AAA",
                "research_timestamp": "2026-08-30T00:00:00",
                "catalyst_type": "earnings",
                "catalyst_summary": "fixture",
                "sources": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (data / "cio" / "cio_instrument_records.jsonl").write_text(
        json.dumps(
            {
                "subject_key": "HELD:AAA",
                "schema": "InstrumentRecord@v1",
                "authority": "READ_ONLY_ADVISORY",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["schema"] == "CIOEventLifecycleCensus@v1"
    assert report["authority"] == "READ_ONLY_ADVISORY"
    assert report["memory_behavior_influence"] == 0
    assert report["headline"]["claim_99_99"] is False
    assert "security_holdings_exit_reentry" in report["families"]
    assert "sector_industry" in report["families"]
    assert "catalyst_earnings" in report["families"]
    # Fixture should accept at least the AAA holding / catalyst skip aggregate
    assert report["headline"]["accepted_total"] >= 1


def test_baseline_docs_and_scoreboard_mark():
    assert BASELINE.is_file()
    text = BASELINE.read_text(encoding="utf-8")
    assert "READ_ONLY_ADVISORY" in text
    assert "Do not claim 99.99%" in text or "Do **not** claim 99.99%" in text
    assert OPS.is_file()
    data = json.loads(SCOREBOARD.read_text(encoding="utf-8"))
    assert data["packages"]["P1-WS2"]["status"] == "DONE"
    gaps = GAPS.read_text(encoding="utf-8")
    assert "P1-WS2" in gaps
    assert "G-LOOP-01" in gaps
    assert "G-PRICE-01" in gaps
