"""LQ-20261107-1819: Memory panel retrieval badge must read real retrieval use, not the comparator file."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
        {"consumed_at": ts(1), "consumer": "hermes_research_prompt", "memory_ids_supporting": ["m1", "m2"], "memory_ids_counter": ["m3"]},
        {"consumed_at": ts(2), "consumer": "intelligence_client", "memory_ids_supporting": ["m1"], "memory_ids_counter": []},
        {"consumed_at": ts(30), "consumer": "intelligence_client", "memory_ids_supporting": ["old"], "memory_ids_counter": []},
    ])
    _w(cio / "retrieval_receipts.jsonl", [
        {"created_at": ts(1), "decision": "HIT_PARTIAL", "evidence_stages": {"used_refs": []}},
        {"created_at": ts(3), "decision": "MISS", "evidence_stages": {"used_refs": ["x"]}},
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
    _w(cio / "memory_consumption_receipts.jsonl", [{"consumed_at": real, "consumer": "hermes_research_prompt",
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
    assert "shadow.real_retrievals" not in tsx
