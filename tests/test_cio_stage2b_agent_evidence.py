#!/usr/bin/env python3
"""Stage 2b (F2): structured agent evidence contract tests."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from process_watchlist_agent_jobs import (
    _format_evidence_for_synthesis,
    _normalize_data_i_doubt,
    _normalize_evidence,
    _parse_result,
    AGENT_JSON_CONTRACT_VERSION,
    SYNTHESIS_VERSION_NUM,
)


def test_synthesis_version_bumped():
    assert SYNTHESIS_VERSION_NUM == 7
    assert "structured_evidence" in AGENT_JSON_CONTRACT_VERSION


def test_normalize_evidence_tags():
    raw = [
        {"tag": "fact", "text": "0 shares held"},
        {"tag": "technical", "text": "RSI 44"},
        {"tag": "bogus", "text": "maps to fact"},
        "plain string claim",
    ]
    out = _normalize_evidence(raw)
    assert len(out) == 4
    assert out[0]["tag"] == "fact"
    assert out[2]["tag"] == "fact"  # bogus → fact
    assert out[3]["tag"] == "fact"


def test_parse_result_extracts_f2_fields():
    raw = json.dumps({
        "summary": "Test",
        "full_narrative": "Long form",
        "recommendation": "HOLD",
        "confidence": 0.72,
        "evidence": [
            {"tag": "risk", "text": "No stop on file"},
            {"tag": "fact", "text": "Yield 3.2%"},
        ],
        "data_i_doubt": "price may be 2d stale",
        "reason_codes": ["income_ok"],
        "next_action": "Monitor",
    })
    p = _parse_result(raw)
    assert p["recommendation"] == "HOLD"
    assert len(p["evidence"]) == 2
    assert p["evidence"][0]["tag"] == "risk"
    assert "stale" in p["data_i_doubt"]


def test_format_evidence_for_synthesis():
    block = _format_evidence_for_synthesis({
        "evidence": [{"tag": "technical", "text": "Below SMA50"}],
        "data_i_doubt": "news older than 14d",
    })
    assert "[technical]" in block
    assert "Data doubt:" in block


def test_normalize_data_i_doubt_list():
    assert _normalize_data_i_doubt(["stale RSI", "missing SEC"]) == "stale RSI; missing SEC"
    assert _normalize_data_i_doubt(None) == "none"


def main():
    test_synthesis_version_bumped()
    test_normalize_evidence_tags()
    test_parse_result_extracts_f2_fields()
    test_format_evidence_for_synthesis()
    test_normalize_data_i_doubt_list()
    print("test_cio_stage2b_agent_evidence: 5 passed")


if __name__ == "__main__":
    main()