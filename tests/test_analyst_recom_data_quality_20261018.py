"""Exact-source read-model boundaries; AST loading avoids import-time credentials.

Only synthetic cache bytes, fake DB effects, and fake market-quote results.
DQ_SOURCE_ROOT selects a frozen source snapshot or isolated candidate checkout.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(os.environ.get("DQ_SOURCE_ROOT", Path(__file__).resolve().parents[1]))


def functions(path, names, scope):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / path), "exec"), scope)
    return scope


@pytest.fixture(autouse=True)
def helper_modules(monkeypatch):
    lib = types.ModuleType("lib")
    lib.__path__ = []
    monkeypatch.setitem(sys.modules, "lib", lib)
    for name in ("analyst_recom_guard", "analyst_vote_distribution"):
        path = ROOT / "scripts/lib" / f"{name}.py"
        if path.exists():
            module = types.ModuleType(f"lib.{name}")
            exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
            monkeypatch.setitem(sys.modules, module.__name__, module)
            setattr(lib, name, module)
    market = types.ModuleType("lib.data_broker.market_quote")
    market.get_price_batch = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, market.__name__, market)


def cache_reader():
    return functions(
        "scripts/finviz_enrichment.py",
        {"_classify_recom", "_cache_path", "load_cache", "_recom_guard", "sanitize_cache_recoms"},
        {"json": json, "Path": Path, "Dict": Dict, "Any": Any, "CACHE_FILE": "data/state/ticker_enrichment_cache.json"},
    )


def test_source_parser_already_refuses_percent_recom():
    assert cache_reader()["_classify_recom"]("3.81%") == (None, None, "percent_sign_not_a_1_5_rating")


def test_source_parser_valid_control():
    assert cache_reader()["_classify_recom"]("2.0") == (2.0, "Buy", None)


def test_loaded_historical_cache_does_not_publish_percent_as_a_rating(tmp_path):
    p = tmp_path / "data/state/ticker_enrichment_cache.json"
    p.parent.mkdir(parents=True)
    before = json.dumps({"AAA": {"recom": "3.81%", "recom_score": 3.81, "analyst_rating": "Sell"}})
    p.write_text(before)
    value = cache_reader()["load_cache"](tmp_path)["AAA"]
    assert value["recom_score"] is None and value["analyst_rating"] is None
    assert value["recom"] == "3.81%" and p.read_text() == before


def test_writer_cannot_replay_percent_rating_even_when_target_exists(monkeypatch):
    rows = []
    extras = types.ModuleType("psycopg2.extras")
    extras.execute_values = lambda cursor, sql, values: rows.extend(values)
    driver = types.ModuleType("psycopg2")
    driver.extras = extras
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    connection = types.SimpleNamespace(cursor=Cursor, commit=lambda: None, rollback=lambda: None)
    namespace = functions(
        "scripts/db_adapter.py",
        {"_recom_guard", "build_analyst_consensus_rows", "save_analyst_consensus_history"},
        {"json": json, "USE_DB": True, "_get_conn": lambda: connection},
    )
    namespace["save_analyst_consensus_history"](
        "2026-10-18",
        {"AAA": {"recom": "3.81%", "recom_score": 3.81, "analyst_rating": "Sell"}},
        {"AAA": {"target": 10.0}},
    )
    assert len(rows) == 1
    assert rows[0][2:6] == (None, None, None, 10.0)


@pytest.mark.parametrize(
    "raw,score",
    [
        ("-95.44%", -95.44),
        ("3.81%", 3.81),
        ("938.86", 938.86),
        ("nan", None),
        (float("nan"), None),
        (None, float("inf")),
        (True, 1.0),
        ("2.0", True),
        ("unknown", 2.0),
        ("2.0", 4.0),
    ],
)
def test_all_cache_replay_refusals_share_the_classifier(raw, score):
    guard = sys.modules["lib.analyst_recom_guard"]
    record = {"recom": raw, "recom_score": score, "analyst_rating": "Buy", "source": "fixture"}
    reason = guard.recom_reject_reason(raw, score)
    assert reason is not None
    assert guard.sanitize_enrichment_record(record) == reason
    assert record["recom_score"] is None and record["analyst_rating"] is None
    assert record["source"] == "fixture"


@pytest.mark.parametrize("raw,score", [("2.0", 2.0), (None, 2.0), ("buy", 2.0)])
def test_supported_legacy_records_keep_their_existing_nullable_shape(raw, score):
    guard = sys.modules["lib.analyst_recom_guard"]
    record = {"recom": raw, "recom_score": score, "analyst_rating": "Buy", "extension": {"old": True}}
    before = dict(record)
    assert guard.sanitize_enrichment_record(record) is None
    assert record == before
    assert guard.is_valid_recom(raw, score)


def test_missing_numeric_evidence_never_creates_a_rating_or_zero():
    guard = sys.modules["lib.analyst_recom_guard"]
    missing = {"recom": None, "recom_score": None, "analyst_rating": None}
    assert guard.sanitize_enrichment_record(missing) is None
    assert not guard.is_valid_recom(None, None)
    label_only = {"recom": None, "recom_score": None, "analyst_rating": "Buy"}
    assert guard.sanitize_enrichment_record(label_only) == "missing_numeric_evidence"
    assert label_only["recom_score"] is None and label_only["analyst_rating"] is None


@pytest.mark.parametrize(
    "raw,score,rating",
    [
        ("Strong Buy", 4.8, "Strong Buy"),
        ("Strong Buy", 4.8, "Strong Sell"),
        ("4.8", 4.8, "Strong Buy"),
        ("4.8", None, "Strong Buy"),
        (None, 4.8, "Strong Buy"),
        ("4.8", 4.8, ["Strong Sell"]),
        ("4.8", 4.8, []),
        ("4.8", 4.8, False),
    ],
)
def test_contradictory_labels_are_withheld_without_remapping(raw, score, rating):
    guard = sys.modules["lib.analyst_recom_guard"]
    record = {"recom": raw, "recom_score": score, "analyst_rating": rating, "cached_at": "fixture-time"}
    assert guard.sanitize_enrichment_record(record) is not None
    assert record["recom_score"] is None and record["analyst_rating"] is None
    assert record["recom"] == raw and record["cached_at"] == "fixture-time"


@pytest.mark.parametrize(
    "score,rating", [(1.0, "Strong Buy"), (2.0, "Buy"), (3.0, "Hold"), (4.0, "Sell"), (4.8, "Strong Sell")]
)
def test_supported_labels_match_only_the_unchanged_classifier(score, rating):
    guard = sys.modules["lib.analyst_recom_guard"]
    record = {"recom": rating.lower(), "recom_score": score, "analyst_rating": rating}
    before = dict(record)
    assert guard.sanitize_enrichment_record(record) is None
    assert record == before


def test_cache_keeps_old_reader_keys_raw_bytes_metadata_and_valid_zero(tmp_path):
    p = tmp_path / "data/state/ticker_enrichment_cache.json"
    p.parent.mkdir(parents=True)
    before = json.dumps(
        {
            "_meta": {"schema": "legacy"},
            "AAA": {
                "recom": "-95.44%",
                "recom_score": -95.44,
                "analyst_rating": "Strong Buy",
                "cached_at": "2026-09-01T00:00:00Z",
                "extension": {"reader": 1},
                "perf_ytd_pct": 0,
            },
            "BBB": {"recom": "2.0", "recom_score": 2.0, "analyst_rating": "Buy"},
        }
    )
    p.write_text(before)
    result = cache_reader()["load_cache"](tmp_path)
    assert result["_meta"] == {"schema": "legacy"}
    assert result["AAA"]["cached_at"] == "2026-09-01T00:00:00Z"
    assert result["AAA"]["extension"] == {"reader": 1}
    assert result["AAA"]["perf_ytd_pct"] == 0  # measured zero is not missing
    # An old open-dict reader still receives known keys and nullable values.
    assert {k: result["AAA"].get(k) for k in ("recom", "recom_score", "analyst_rating")} == {
        "recom": "-95.44%",
        "recom_score": None,
        "analyst_rating": None,
    }
    assert result["BBB"]["recom_score"] == 2.0
    assert p.read_text() == before


def row_namespace(connection=None):
    return functions(
        "scripts/db_adapter.py",
        {"_recom_guard", "build_analyst_consensus_rows", "save_analyst_consensus_history"},
        {"json": json, "USE_DB": True, "_get_conn": lambda: connection},
    )


def test_pure_row_builder_preserves_refused_provenance_and_input():
    source = {
        "AAA": {"recom": "3.81%", "recom_score": 3.81, "analyst_rating": "Sell", "cached_at": "2026-09-01T00:00:00Z"}
    }
    before = json.dumps(source)
    rows, receipt = row_namespace()["build_analyst_consensus_rows"]("2026-10-18", source, {"AAA": {"target": 10.0}})
    assert len(rows) == 1 and len(rows[0]) == 8  # unchanged existing SQL column contract
    assert rows[0][2:6] == (None, None, None, 10.0)
    evidence = json.loads(rows[0][7])["recom_rejected_evidence"]
    assert evidence == {"raw": "'3.81%'", "score": "3.81", "rating": "'Sell'", "cached_at": "2026-09-01T00:00:00Z"}
    assert receipt["rows_prepared"] == 1 and receipt["recom_refused"] == 1
    assert "written" not in receipt and "rows_committed" not in receipt
    assert receipt["refused_records"][0]["raw"] == "'3.81%'"
    assert json.dumps(source) == before


def test_refused_only_row_is_not_an_empty_observation_or_a_write():
    rows, receipt = row_namespace()["build_analyst_consensus_rows"](
        "2026-10-18", {"AAA": {"recom": "3.81%", "recom_score": 3.81, "analyst_rating": "Sell"}}
    )
    assert rows == [] and receipt["rows_prepared"] == 0
    assert receipt["recom_refused"] == 1


def test_writer_unavailable_database_does_not_report_prepared_rows_as_written():
    receipt = row_namespace()["save_analyst_consensus_history"](
        "2026-10-18", {"AAA": {"recom": "2.0", "recom_score": 2.0, "analyst_rating": "Buy"}}
    )
    assert receipt["rows_prepared"] == 1
    assert receipt["rows_committed"] is None and receipt["storage_status"] == "unavailable"


@pytest.mark.parametrize("failure", [None, "execute", "commit"])
def test_writer_commit_evidence_is_separate_from_preparation(monkeypatch, failure):
    calls = []
    extras = types.ModuleType("psycopg2.extras")

    def execute_values(cursor, sql, rows):
        calls.append((sql, rows))
        if failure == "execute":
            raise RuntimeError("fixture execute failed")

    extras.execute_values = execute_values
    driver = types.ModuleType("psycopg2")
    driver.extras = extras
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def commit():
        if failure == "commit":
            raise RuntimeError("fixture commit outcome unknown")

    conn = types.SimpleNamespace(cursor=Cursor, commit=commit, rollback=lambda: None)
    receipt = row_namespace(conn)["save_analyst_consensus_history"](
        "2026-10-18", {"AAA": {"recom": "2.0", "recom_score": 2.0, "analyst_rating": "Buy"}}
    )
    assert len(calls) == 1 and "INSERT INTO analyst_consensus_history" in calls[0][0]
    assert receipt["rows_prepared"] == 1
    if failure:
        assert receipt["rows_committed"] is None and receipt["storage_status"] == "unknown"
    else:
        assert receipt["rows_committed"] == 1 and receipt["storage_status"] == "committed"
