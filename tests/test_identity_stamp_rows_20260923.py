"""Every research and gap row a subject join reads must carry subject_guid.

Measured 2026-09-23 on the live stores: only HERMES_RESEARCH_REQUESTED rows were
stamped (since 16:07 UTC), and 0 of 1,617 ENQUEUE rows carried a GUID. In the
operator gap log, only hermes_operator_forced rows were stamped; every
gaps-shaped row (the desk's data gaps) carried the symbol alone. A join by
subject_guid found the question but never its outcome.

Resolution must never block a write: a failed lookup stamps nothing and the row
is still appended.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

GUIDS = {"SCHD": ("s-schd", "i-schd"), "S": ("s-s", "i-s")}


def _fake_resolve(_doc, symbol):
    sym = str(symbol or "").upper()
    if sym not in GUIDS:
        return None
    sg, ig = GUIDS[sym]
    return {"symbol": sym, "subject_guid": sg, "issuer_guid": ig,
            "identity_status": "CONFIRMED"}


def _patch_identity(monkeypatch, resolve=_fake_resolve):
    import importlib

    for name in ("scripts.lib.research_identity", "lib.research_identity"):
        try:
            mod = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        monkeypatch.setattr(mod, "load_registry", lambda *a, **k: {})
        monkeypatch.setattr(mod, "resolve", resolve)


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


@pytest.fixture
def hermes_tmp(tmp_path, monkeypatch):
    import lib.cio_hermes_research as hr

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    monkeypatch.setattr(hr, "REQUEST_PATH", Path("data/cio/hermes_research_requests.jsonl"))
    monkeypatch.setattr(hr, "RESULT_PATH", Path("data/cio/hermes_research_results.jsonl"))
    monkeypatch.setattr(hr, "PROJECTION_PATH", Path("data/cio/hermes_research_projection.json"))
    return hr


def _plan(**kw):
    base = {"plan_id": "plan_stamp_1", "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
            "symbols": ["SCHD"], "thesis_version": "desk@v5", "fire_reasons": ["t"]}
    base.update(kw)
    return base


def test_every_hermes_lifecycle_row_carries_subject_guid(hermes_tmp, monkeypatch):
    hr = hermes_tmp
    _patch_identity(monkeypatch)
    from lib.hermes_worker import HermesWorker, StubResearchBackend

    enq = hr.enqueue_research_request(_plan(), priority="high")
    assert enq["created"]
    hr.enqueue_research_request(_plan(), priority="high")        # duplicate path
    HermesWorker(store=hr, backend=StubResearchBackend(), worker_id="w").run_once(limit=1)

    reqs = _rows(hr.REQUEST_PATH)
    events = {r["event"] for r in reqs}
    assert {"HERMES_RESEARCH_REQUESTED", "HERMES_RESEARCH_ENQUEUE",
            "HERMES_RESEARCH_CLAIMED", "HERMES_RESEARCH_COMPLETED"} <= events
    for r in reqs:
        if r["event"] in ("HERMES_RESEARCH_REQUESTED", "HERMES_RESEARCH_ENQUEUE",
                          "HERMES_RESEARCH_CLAIMED", "HERMES_RESEARCH_COMPLETED"):
            assert r.get("subject_guid") == "s-schd", r["event"]
    results = _rows(hr.RESULT_PATH)
    assert results and all(r.get("subject_guid") == "s-schd" for r in results)


def test_hermes_rows_still_write_when_identity_resolution_fails(hermes_tmp, monkeypatch):
    hr = hermes_tmp

    def _boom(*_a, **_k):
        raise RuntimeError("registry down")

    _patch_identity(monkeypatch, resolve=_boom)
    enq = hr.enqueue_research_request(_plan(plan_id="plan_stamp_2"), priority="high")
    assert enq["ok"] and enq["created"]
    reqs = _rows(hr.REQUEST_PATH)
    assert any(r["event"] == "HERMES_RESEARCH_ENQUEUE" for r in reqs)
    assert all(not r.get("subject_guid") for r in reqs)


def test_gaps_shaped_operator_rows_carry_subject_guid(tmp_path, monkeypatch):
    from lib import cio_operator_desk_loop as desk

    _patch_identity(monkeypatch)
    monkeypatch.setattr(desk, "PROJECT_ROOT", tmp_path)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    # No resolver action for these gaps: nothing touches the database.
    monkeypatch.setattr(desk, "_registry_gap_type", lambda _g: None)

    gaps = [{"symbol": "S", "domain": "quote", "field": "price"},
            {"symbol": "ZZZZ", "domain": "quote", "field": "price"}]
    desk._register_gaps(gaps, chat_id="c1", pending_id="opr_test")

    row = _rows(tmp_path / "data" / "cio" / "cio_operator_gap_requests.jsonl")[-1]
    assert row["subject_guid"] == "s-s"
    assert row["gaps"][0]["subject_guid"] == "s-s"
    assert "subject_guid" not in row["gaps"][1]           # unresolved: stamped nothing
    assert "subject_guid" not in gaps[0]                   # caller's list not mutated
