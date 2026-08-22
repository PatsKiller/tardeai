"""P1 write-path: parser slices, living-thesis schema, always-on raw_response INSERT."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from cio_agent_contract import (  # noqa: E402
    build_external_research_json_schema,
    parse_external_research_result,
)


def test_parse_keeps_600_char_recommendation():
    rec = "A" * 600
    raw = json.dumps({"recommendation": rec, "confidence": 0.55})
    p = parse_external_research_result(raw)
    assert p is not None
    assert p["recommendation"] == rec
    assert len(p["recommendation"]) == 600


def test_parse_cuts_5000_char_recommendation_at_4000():
    rec = "B" * 5000
    raw = json.dumps({"recommendation": rec, "confidence": 0.55})
    p = parse_external_research_result(raw)
    assert p is not None
    assert len(p["recommendation"]) == 4000
    assert p["recommendation"] == rec[:4000]


def test_parse_dissent_and_sidecar_slices():
    dissent_ok = "D" * 600
    dissent_long = "E" * 5000
    learn_ok = "L" * 400
    learn_long = "M" * 1000
    op_ok = "O" * 400
    op_long = "P" * 1000

    kept = parse_external_research_result(json.dumps({
        "recommendation": "x",
        "dissent": dissent_ok,
        "learning_candidate": learn_ok,
        "operator_action": op_ok,
    }))
    assert kept["dissent"] == dissent_ok
    assert kept["learning_candidate"] == learn_ok
    assert kept["operator_action"] == op_ok

    cut = parse_external_research_result(json.dumps({
        "recommendation": "x",
        "dissent": dissent_long,
        "learning_candidate": learn_long,
        "operator_action": op_long,
    }))
    assert len(cut["dissent"]) == 4000
    assert cut["dissent"] == dissent_long[:4000]
    assert len(cut["learning_candidate"]) == 800
    assert cut["learning_candidate"] == learn_long[:800]
    assert len(cut["operator_action"]) == 800
    assert cut["operator_action"] == op_long[:800]


def test_schema_describes_recommendation_as_living_thesis():
    schema = build_external_research_json_schema()
    low = schema.lower()
    assert "living thesis" in low
    assert "ticker" in low
    assert "invalidation" in low
    assert "8 sentences" in low
    assert "do not hide the thesis in evidence" in low
    assert "Return ONLY valid JSON" in schema


def test_researcher_insert_sql_mentions_raw_response():
    src = (ROOT / "scripts" / "hermes_external_researcher.py").read_text(encoding="utf-8")
    assert "raw_response" in src
    assert "str(raw)[:16000]" in src
    assert 'parsed["recommendation"] = str(raw).strip()[:4000]' in src
    # Always-on store is on the parsed INSERT, not only the empty-rec fallback.
    assert "lane_used, raw_response)" in src
    # Capability-cache path may leave raw_response NULL (column omitted).
    cache_insert = src.split("if cache_blocks_lane", 1)[1].split("return", 1)[0]
    assert "INSERT INTO hermes_external_research" in cache_insert
    assert "raw_response" not in cache_insert
    # Prompt: recommendation IS the thesis; JSON contract still required.
    assert "recommendation field IS the living thesis" in src
    assert "JSON contract still required" in src


def test_researcher_requests_process_ceiling():
    src = (ROOT / "scripts" / "hermes_external_researcher.py").read_text(encoding="utf-8")
    assert "max_tokens=max_out or 4096" in src
    assert '--max-output-tokens", type=int, default=None' in src


def test_hermes_external_research_caps_unchanged_except_output_tokens():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    proc = next(p for p in reg["processes"] if p["id"] == "hermes_external_research")
    assert proc["max_output_tokens"] == 4096
    assert proc["daily_soft_cap"] == 600
    assert float(proc["daily_cost_cap_usd"]) == 0.30
    notes = proc.get("notes") or ""
    assert "dollar caps unchanged $0.30 / $0.50" in notes
    assert "daily_soft_cap stays 600" in notes


def test_raw_response_migration_exists():
    path = ROOT / "migrations" / "2026-08-22_hermes_external_research_raw_response.sql"
    sql = path.read_text(encoding="utf-8")
    assert "ALTER TABLE hermes_external_research" in sql
    assert "ADD COLUMN IF NOT EXISTS raw_response TEXT" in sql
    assert "always-on raw store" in sql
    assert "parser slices no longer the only copy" in sql
