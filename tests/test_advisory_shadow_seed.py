"""Daily shadow-receipt producer — Financial Senses + memory heartbeats.

READ_ONLY_ADVISORY. The producer must (1) write an FS tool-trace heartbeat that
the desk's SENSES join recognizes as CURRENT, (2) admit a governed memory
heartbeat that moves the MEMORY clock, and (3) hold influence at 0 while never
touching broker / order / stop authority.
"""
from __future__ import annotations

import json
import os

import pytest

import scripts.advisory_shadow_seed as seed
from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider


def _write_state(tmp_path) -> None:
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "holdings.json").write_text(json.dumps({
        "holdings": [{"symbol": "SCHD"}, {"symbol": "V"}, {"symbol": "CASH"}],
    }))
    (state / "watchlist.json").write_text(json.dumps({
        "state": "AVAILABLE",
        "items": {"AXTI": {"thesis": "x"}, "ADBE": {"thesis": "y"}},
    }))
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "reentry_decision_desk_latest.json").write_text(json.dumps({
        "rows": [{"symbol": "NVDA"}, {"symbol": "AMD"}],
    }))


def _provider(tmp_path) -> DurableJsonlMemoryProvider:
    return DurableJsonlMemoryProvider(path=tmp_path / "aif_memory.jsonl")


def test_collect_symbols_merges_holdings_watch_reentry(tmp_path):
    _write_state(tmp_path)
    syms = seed.collect_symbols(tmp_path)
    assert set(syms) >= {"SCHD", "V", "AXTI", "ADBE", "NVDA", "AMD"}
    assert "CASH" not in syms


def test_run_writes_fs_and_memory_receipts(tmp_path):
    _write_state(tmp_path)
    out = seed.run(root=tmp_path, cio_dir=tmp_path, provider=_provider(tmp_path))
    assert out["ok"] is True
    assert out["influence"] == 0
    assert out["authority"] == "READ_ONLY_ADVISORY"
    assert out["memory"]["admitted"] is True
    assert out["memory"]["memory_id"]

    recs = [json.loads(l) for l in (tmp_path / "agent_tool_traces.jsonl").read_text().splitlines() if l.strip()]
    fs = next(r for r in recs if r.get("tool_name") == "financial_senses")
    assert fs["fs_provider"] == "shadow_seed"
    assert fs["ended_at"]
    assert set(fs["symbols"]) >= {"SCHD", "V", "AXTI", "ADBE", "NVDA", "AMD"}
    assert fs["influence"] == 0
    assert fs["behavior_influence"] is False

    adm = [json.loads(l) for l in (tmp_path / "aif_memory_admissions.jsonl").read_text().splitlines() if l.strip()]
    assert adm[-1]["accepted"] is True
    stored = _provider(tmp_path).get(adm[-1]["memory_id"])
    assert stored is not None
    assert stored["producer"] == "advisory_shadow_seed"
    assert stored["status"] in ("CANDIDATE", "ACTIVE")


def test_run_enforces_zero_influence(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "1")
    _write_state(tmp_path)
    seed.run(root=tmp_path, cio_dir=tmp_path, provider=_provider(tmp_path))
    assert os.environ["MEMORY_BEHAVIOR_INFLUENCE"] == "0"


def test_fs_receipt_satisfies_join_financial_senses(tmp_path, monkeypatch):
    from scripts.lib import advisory_desk_operator as op

    _write_state(tmp_path)
    seed.run(root=tmp_path, cio_dir=tmp_path, provider=_provider(tmp_path))
    monkeypatch.setattr(op, "_CIO", tmp_path)

    j = op.join_financial_senses(["SCHD", "V", "AXTI", "NVDA"])
    assert j["producer"] == "advisory_shadow_seed"
    assert j["receipts_available"] >= 1
    assert j["freshness"] == "CURRENT"
    assert j["as_of"]


def test_memory_clock_reads_admission_receipt(tmp_path, monkeypatch):
    from scripts.lib import advisory_desk_operator as op
    from scripts.lib import agent_durable_memory as adm

    _write_state(tmp_path)
    prov = _provider(tmp_path)
    seed.run(root=tmp_path, cio_dir=tmp_path, provider=prov)
    monkeypatch.setattr(adm, "get_durable_provider", lambda: prov)

    j = op.join_durable_memory(["SCHD", "V"])
    assert j["producer"] == "advisory_shadow_seed"
    assert j["as_of"]


if __name__ == "__main__":
    pytest.main([__file__])
