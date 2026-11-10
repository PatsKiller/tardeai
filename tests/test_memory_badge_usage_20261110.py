"""LQ-20261107-1819: Memory panel retrieval badge must read real retrieval use, not the comparator file."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CS = "MemoryConsumptionReceipt@v1"
RS = "RetrievalReceipt@v1"
NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)


def _w(p, rows):
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _fixture(cio: Path):
    cio.mkdir(parents=True)
    ts = lambda h: (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _w(cio / "aif_memory.jsonl", [{"memory_id": "m1", "status": "ADMITTED", "created_at": ts(1)}])
    _w(cio / "memory_shadow_runs.jsonl", [{"at": "2026-08-18T03:14:55+00:00",
        "retrieval": {"retrieval_status": "OK"}, "advisory_changes": 0}])  # the only comparator run, months old
    _w(cio / "memory_consumption_receipts.jsonl", [
        {"schema": CS, "consumed_at": ts(1), "consumer": "hermes_research_prompt", "memory_ids_supporting": ["m1", "m2"], "memory_ids_counter": ["m3"]},
        {"schema": CS, "consumed_at": ts(2), "consumer": "intelligence_client", "memory_ids_supporting": ["m1"], "memory_ids_counter": []},
        {"schema": CS, "consumed_at": ts(30), "consumer": "intelligence_client", "memory_ids_supporting": ["old"], "memory_ids_counter": []},
    ])
    _w(cio / "retrieval_receipts.jsonl", [
        {"schema": RS, "created_at": ts(1), "decision": "HIT_PARTIAL", "evidence_stages": {"used_refs": []}},
        {"schema": RS, "created_at": ts(3), "decision": "MISS", "evidence_stages": {"used_refs": ["x"]}},
    ])


def test_usage_window_counts_real_receipts(tmp_path):
    from scripts.lib.memory_usage_view import usage_window
    _fixture(tmp_path / "data" / "cio")
    u = usage_window(tmp_path / "data" / "cio", now=NOW)
    assert u["consumption_receipts"] == 2          # 30h-old receipt excluded
    assert u["by_consumer"] == {"hermes_research_prompt": 1, "intelligence_client": 1}
    assert u["distinct_memory_ids"] == 3
    assert u["ladder_receipts"] == 2 and u["ladder_decisions"] == {"HIT_PARTIAL": 1, "MISS": 1}
    assert u["ladder_used_refs"] == 1


def test_memory_view_badge_not_comparator_only(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.delenv("TRADEAI_CIO_DIR", raising=False)
    cio = tmp_path / "data" / "cio"
    _fixture(cio)
    # make receipts "now" relative: rewrite stamps to real now so the 24h window holds
    real = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _w(cio / "memory_consumption_receipts.jsonl", [{"schema": CS, "consumed_at": real, "consumer": "hermes_research_prompt",
        "memory_ids_supporting": ["m1"], "memory_ids_counter": []}])
    from scripts import api_v3_maturity as api
    api._MEMORY_VIEW_CACHE.clear()
    status, body = api.handle_get("memory", {"limit": ["40"]})
    assert status == 200
    assert body["shadow"]["real_retrievals"] == 1                      # comparator, kept but labelled
    assert body["shadow"]["last_run_at"].startswith("2026-08-18")
    assert "comparator" in body["shadow"]["source"]
    assert body["usage_24h"]["consumption_receipts"] == 1              # real use, distinct from comparator
    assert body["usage_24h"]["memory_behavior_influence"] == "0"
    api._MEMORY_VIEW_CACHE.clear()


def test_panel_badge_reads_usage_not_comparator():
    tsx = (ROOT / "apps/command-center-v3/src/pages/MaturityPanels.tsx").read_text(encoding="utf-8")
    assert "usage.consumption_receipts" in tsx
    assert "usage.error" in tsx and "memory-usage-unreadable" in tsx and "newest" in tsx and "age " in tsx
    assert "?? 24" not in tsx
    assert "shadow.real_retrievals" not in tsx


def test_missing_files_fail_closed(tmp_path):
    from scripts.lib.memory_usage_view import usage_window
    u = usage_window(tmp_path / "nope", now=NOW)
    assert u["consumption_receipts"] is None and u["ladder_receipts"] is None
    assert u["error"].startswith("cannot be read:") and "FileNotFoundError" in u["error"]
    assert u["consumption"]["status"] == "UNREADABLE"


def test_unreadable_file_fails_closed(tmp_path):
    import os, pytest
    from scripts.lib.memory_usage_view import usage_window
    cio = tmp_path / "data" / "cio"
    _fixture(cio)
    f = cio / "memory_consumption_receipts.jsonl"
    os.chmod(f, 0)
    try:
        if os.access(f, os.R_OK):
            pytest.skip("running as a user that ignores file modes")
        u = usage_window(cio, now=NOW)
        assert u["consumption_receipts"] is None and "PermissionError" in u["error"]
    finally:
        os.chmod(f, 0o644)


def test_corrupt_rows_skipped_and_counted(tmp_path):
    from scripts.lib.memory_usage_view import usage_window
    cio = tmp_path / "data" / "cio"
    _fixture(cio)
    t = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (cio / "memory_consumption_receipts.jsonl").open("a") as fh:
        fh.write('["list"]\nnot json\n{"schema": "Other@v1", "consumed_at": "%s"}\n' % t)
    with (cio / "retrieval_receipts.jsonl").open("a") as fh:
        fh.write(json.dumps({"schema": RS, "created_at": t, "decision": "MISS", "evidence_stages": "x"}) + "\n")
        fh.write(json.dumps({"schema": RS, "created_at": t, "decision": "MISS", "evidence_stages": {"used_refs": "abc"}}) + "\n")
    u = usage_window(cio, now=NOW)
    assert u["error"] is None and u["consumption_receipts"] == 2
    assert u["consumption"]["malformed"] == 3
    assert u["ladder_used_refs"] == 1            # string used_refs not len()-counted
    assert u["ladder"]["malformed"] == 2          # string evidence_stages + string used_refs row skipped from refs


def test_future_dated_excluded_and_counted(tmp_path):
    from scripts.lib.memory_usage_view import usage_window
    cio = tmp_path / "data" / "cio"
    _fixture(cio)
    with (cio / "memory_consumption_receipts.jsonl").open("a") as fh:
        fh.write(json.dumps({"schema": CS, "consumed_at": "2099-01-01T00:00:00Z", "consumer": "x",
                             "memory_ids_supporting": ["f"], "memory_ids_counter": []}) + "\n")
    u = usage_window(cio, now=NOW)
    assert u["consumption_receipts"] == 2 and u["consumption"]["future_dated"] == 1
    assert u["consumption"]["newest_receipt_at"].startswith("2026-11-10T17")   # not 2099


def test_as_of_age_source_and_empty_vs_missing(tmp_path):
    from scripts.lib.memory_usage_view import usage_window
    cio = tmp_path / "data" / "cio"
    _fixture(cio)
    u = usage_window(cio, now=NOW)
    c = u["consumption"]
    assert c["file"] == "memory_consumption_receipts.jsonl" and c["age_s"] == 3600 and c["mtime"]
    _w(cio / "memory_consumption_receipts.jsonl", [])
    u = usage_window(cio, now=NOW)
    assert u["consumption_receipts"] == 0 and u["error"] is None and u["consumption"]["newest_receipt_at"] is None


def test_truncated_flag_and_config(tmp_path):
    from scripts.lib.memory_usage_view import usage_window, load_config
    cio = tmp_path / "data" / "cio"
    _fixture(cio)
    with (cio / "memory_consumption_receipts.jsonl").open("a") as fh:   # two more in-window rows after the 30h one
        for h in (1, 2):
            fh.write(json.dumps({"schema": CS, "consumed_at": (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "consumer": "x", "memory_ids_supporting": [], "memory_ids_counter": []}) + "\n")
    u = usage_window(cio, now=NOW, env={"TRADEAI_MEMORY_USAGE_MAX_ROWS": "2"})
    assert u["max_rows"] == 2 and u["consumption"]["truncated"] is True
    assert load_config({})["window_hours"] == 24
    u = usage_window(cio, now=NOW, env={"TRADEAI_MEMORY_USAGE_HOURS": "48"})
    assert u["window_hours"] == 48 and u["consumption_receipts"] == 5
