"""GET /api/v3/maturity/scorecard — UNMEASURED when stale/missing; no mutations."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import api_v3_maturity as api  # noqa: E402
from scripts.lib.maturity_scorecard import (  # noqa: E402
    FRESHNESS_TTL_DAYS,
    SCHEMA,
    STATUS_MEASURED,
    STATUS_UNMEASURED,
    compute_scorecard,
)

NOW = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
FILE_DIMS = (
    "research_skip",
    "holdings_universe",
    "held_thesis_coverage",
    "decision_payload",
)


def _cio(root: Path) -> Path:
    p = root / "data" / "cio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_missing_files_unmeasured(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    card = compute_scorecard(root=tmp_path, now=NOW)
    assert card["ok"] is True
    assert card["authority"] == "READ_ONLY_ADVISORY"
    assert card["financial_action"] is False
    assert card["schema"] == SCHEMA
    assert card["ttl_days"] == FRESHNESS_TTL_DAYS
    for name in FILE_DIMS:
        dim = card["dimensions"][name]
        assert dim["status"] == STATUS_UNMEASURED, name
        assert dim["score"] is None, name
    mem = card["dimensions"]["memory_influence"]
    assert mem["status"] == STATUS_MEASURED
    assert mem["score"] == 0
    assert mem["inputs"]["MEMORY_BEHAVIOR_INFLUENCE"] == 0


def test_skip_ledger_measured_rates(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    cio = _cio(tmp_path)
    lines = [
        {"at": "2026-08-21T12:00:00+00:00", "code": "SKIP_UNCHANGED", "symbol": "SCHD", "lane": "deepseek", "metered": True, "material": False},
        {"at": "2026-08-21T12:01:00+00:00", "code": "SKIP_UNCHANGED", "symbol": "JEPI", "lane": "local-gemma", "metered": False},
        {"at": "2026-08-21T12:02:00+00:00", "code": "RESEARCH_EXECUTED", "symbol": "V", "lane": "deepseek", "metered": True, "material": True},
        {"at": "2026-08-21T12:03:00+00:00", "code": "SKIP_FRESH", "symbol": "RTX", "lane": "deepseek"},
    ]
    (cio / "research_skip_ledger.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8"
    )
    card = compute_scorecard(root=tmp_path, now=NOW)
    dim = card["dimensions"]["research_skip"]
    assert dim["status"] == STATUS_MEASURED
    assert dim["score"] == 0.5
    inp = dim["inputs"]
    assert inp["skip_unchanged_rate"] == 0.5
    assert inp["research_executed_rate"] == 0.25
    assert inp["n"] == 4
    assert inp["metered_calls_per_material_change"] == 1.0
    assert dim["last_measured_at"] is not None


def test_stale_skip_ledger_unmeasured_null_score(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    cio = _cio(tmp_path)
    (cio / "research_skip_ledger.jsonl").write_text(
        json.dumps({"at": "2026-01-01T00:00:00+00:00", "code": "SKIP_UNCHANGED"}) + "\n",
        encoding="utf-8",
    )
    card = compute_scorecard(root=tmp_path, now=NOW)
    dim = card["dimensions"]["research_skip"]
    assert dim["status"] == STATUS_UNMEASURED
    assert dim["score"] is None
    assert "skip_unchanged_rate" not in dim["inputs"]


def test_holdings_and_coverage_and_payloads(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    cio = _cio(tmp_path)
    (cio / "holdings_universe_latest.json").write_text(json.dumps({
        "schema": "HoldingsUniverse@v1",
        "as_of": "2026-08-21T15:00:00+00:00",
        "held_equity_ticker_n": 22,
    }), encoding="utf-8")
    (cio / "held_thesis_coverage_latest.json").write_text(json.dumps({
        "schema": "HeldBookThesisCoverage@v1",
        "as_of": "2026-08-21T15:20:00+00:00",
        "held_current_pct": 13.64,
        "held_count": 22,
        "current_count": 3,
    }), encoding="utf-8")
    traces = [
        {
            "trace_version": "1.0",
            "started_at": "2026-08-21T10:00:00+00:00",
            "decision": {"schema": "DecisionPayload@v1", "decision_id": "d1"},
        },
        {
            "trace_version": "1.0",
            "started_at": "2026-08-21T11:00:00+00:00",
            "decision": {"action": "HOLD"},
        },
    ]
    (cio / "agent_run_traces.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in traces), encoding="utf-8"
    )
    card = compute_scorecard(root=tmp_path, now=NOW)
    hu = card["dimensions"]["holdings_universe"]
    assert hu["status"] == STATUS_MEASURED
    assert hu["score"] == 22
    assert hu["inputs"]["held_equity_ticker_n"] == 22
    cov = card["dimensions"]["held_thesis_coverage"]
    assert cov["status"] == STATUS_MEASURED
    assert cov["inputs"]["coverage_pct"] == 13.64
    assert cov["inputs"]["fresh_pct"] is None
    dp = card["dimensions"]["decision_payload"]
    assert dp["status"] == STATUS_MEASURED
    assert dp["score"] == 1
    assert dp["inputs"]["decision_payload_n"] == 1


def test_handle_get_scorecard_200(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    code, body = api.handle_get("scorecard")
    assert code == 200
    assert body["ok"] is True
    assert body["financial_action"] is False
    assert body["authority"] == "READ_ONLY_ADVISORY"
    assert body["schema"] == SCHEMA
    assert "research_skip" in body["dimensions"]


def test_handle_get_scorecard_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()}
    code, _ = api.handle_get("scorecard")
    assert code == 200
    after = {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_memory_influence_not_set(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.delenv("MEMORY_BEHAVIOR_INFLUENCE", raising=False)
    card = compute_scorecard(root=tmp_path, now=NOW)
    assert "MEMORY_BEHAVIOR_INFLUENCE" not in os.environ
    assert card["dimensions"]["memory_influence"]["score"] == 0
