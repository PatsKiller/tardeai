"""Operator evidence: per-decision research, honest clocks, bounded reads, shared cache.

Regression for 2026-10-02 review of #1387-#1389:
  * lineage for ANY decision id showed the global research list (329 artifacts);
  * /api/v3/cio/operator-evidence parsed and SHA-256'd ~600 MB per call
    (~23 s, ~1.6 GB RSS) and was polled every 60 s;
  * last_produced_at compared mixed timestamp formats as strings (a future
    2026-12-29 date won).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.cio_operator_evidence as evidence  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _research_root(tmp_path: Path) -> Path:
    root = tmp_path / "cio"
    root.mkdir()
    _write(root / "hermes_research_results.jsonl", [
        {"result_id": "r-a", "decision_id": "dec-a", "symbol": "AAA", "created_at": "2026-10-01T10:00:00Z"},
        {"result_id": "r-b", "decision_id": "dec-b", "symbol": "AAA", "created_at": "2026-10-01T11:00:00Z"},
        {"result_id": "r-global", "symbol": "BBB", "created_at": "2026-10-01T12:00:00Z"},
    ])
    return root


def test_decision_research_never_returns_global_list(tmp_path):
    root = _research_root(tmp_path)
    everything = evidence._research_provenance(root)
    assert len(everything["artifacts"]) >= 3
    only_a = evidence._research_provenance(root, decision_id="dec-a")
    assert [a.get("decision_id") for a in only_a["artifacts"]] == ["dec-a"]
    assert only_a["decision_id"] == "dec-a"
    missing = evidence._research_provenance(root, decision_id="dec-does-not-exist")
    assert missing["artifacts"] == [] and sum(missing["counts"].values()) == 0


def test_same_symbol_decisions_get_distinct_research(tmp_path):
    root = _research_root(tmp_path)
    a = evidence._research_provenance(root, decision_id="dec-a")["artifacts"]
    b = evidence._research_provenance(root, decision_id="dec-b")["artifacts"]
    assert {x["artifact_id"] for x in a}.isdisjoint({x["artifact_id"] for x in b})


def test_future_and_mixed_format_clocks():
    rows = [
        {"created_at": "2026-12-29T00:00:00Z"},           # future: ignored
        {"created_at": "2026-10-01T09:00:00+00:00"},
        {"created_at": "2026-10-01 10:30:00"},             # different format, later instant
        {"created_at": "garbage"},
    ]
    ceiling = evidence._parse_ts("2026-10-02T00:00:00Z")
    assert evidence._latest_stamp(rows, not_after=ceiling) == "2026-10-01 10:30:00"


def test_source_meta_uses_cheap_version_not_content_hash(tmp_path):
    path = tmp_path / "s.jsonl"
    _write(path, [{"created_at": "2026-10-01T00:00:00Z"}])
    meta = evidence._source_meta(path, evidence._rows(path))
    assert meta["source_sha"] is None
    assert meta["source_version"].startswith("bytes=")
    assert meta["row_scope"] == "RECENT_WINDOW"
    assert evidence._source_meta(path, [], exact=True)["row_scope"] == "EXACT_DECISION_SCAN"


def test_composition_reads_a_bounded_recent_window(tmp_path, monkeypatch):
    path = tmp_path / "big.jsonl"
    _write(path, [{"n": i, "pad": "x" * 100} for i in range(5000)])
    monkeypatch.setattr(evidence, "_COMPOSITION_TAIL_BYTES", 4096)
    rows = evidence._rows(path)
    assert 0 < len(rows) < 100 and rows[-1]["n"] == 4999


def test_operator_evidence_is_shared_for_ttl(monkeypatch):
    import scripts.api_v3_cio as api

    calls = {"n": 0}

    def fake_build(**_kw):
        calls["n"] += 1
        return {"ok": True, "schema": "CIOOperatorEvidence@v1", "composition_as_of": f"t{calls['n']}"}

    monkeypatch.setattr(evidence, "build_operator_evidence", fake_build)
    monkeypatch.setitem(api._OPERATOR_EVIDENCE_CACHE, "payload", None)
    monkeypatch.setitem(api._OPERATOR_EVIDENCE_CACHE, "at", 0.0)
    first = api.get_operator_evidence_v1()
    second = api.get_operator_evidence_v1()
    assert calls["n"] == 1
    assert first["composition_as_of"] == second["composition_as_of"] == "t1"
    assert second["cache_age_seconds"] >= 0 and second["cache_ttl_seconds"] > 0
    monkeypatch.setitem(api._OPERATOR_EVIDENCE_CACHE, "at", 0.0)  # expire
    assert api.get_operator_evidence_v1()["composition_as_of"] == "t2"
