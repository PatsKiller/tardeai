"""IntelligenceLineage@v1 — drain, observe, rebuild, GET API.

Never deletes challenge history. Never invents POSITIVE/NEGATIVE P&L.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib import intelligence_lineage as L
from lib.cio_hermes_challenge_queue import HermesChallengeQueue
from lib.cio_production_case import (
    open_case_from_decision,
    materialize_cases,
)
from scripts import api_v3_intelligence as api


@pytest.fixture
def cio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "cio"
    d.mkdir()
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(d))
    return d


def _enqueue(path: Path, *, symbols: list[str], when: datetime, stream: str, extra_meta: dict | None = None):
    q = HermesChallengeQueue(event_store_path=path)
    ev = q.enqueue(
        challenge_type="research_gap",
        description=f"probe {symbols}",
        source="test",
        priority="low",
        metadata={"symbols": symbols, **(extra_meta or {})},
    )
    # rewrite occurred_at for age tests by appending a copy is not allowed;
    # mutate the last line in-place for the test fixture only (still one row).
    rows = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(rows[-1])
    rec["occurred_at"] = when.isoformat()
    rec["stream_id"] = stream
    rec["payload"]["symbols"] = symbols
    rec["metadata"] = {"symbols": symbols, **(extra_meta or {})}
    rows[-1] = json.dumps(rec, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return ev


def test_drain_never_deletes_and_dead_letters_test_symbols(cio: Path):
    path = cio / "hermes_challenge_queue.jsonl"
    now = datetime.now(timezone.utc)
    _enqueue(path, symbols=["SCHD"], when=now - timedelta(days=1), stream="hermes-challenge-keep")
    _enqueue(path, symbols=["SCHD"], when=now - timedelta(days=2), stream="hermes-challenge-dup")
    _enqueue(path, symbols=["SPACEX_TEST"], when=now - timedelta(hours=3), stream="hermes-challenge-test")
    _enqueue(path, symbols=["MU"], when=now - timedelta(days=9), stream="hermes-challenge-stale")
    before = path.read_text(encoding="utf-8")
    dry = L.drain_hermes_challenges(apply=False, max_age_days=7)
    assert dry["expired_dup"] == 1
    assert dry["expired_test"] == 1
    assert dry["expired_stale"] == 1
    assert dry["left_pending"] == 1
    assert path.read_text(encoding="utf-8") == before
    applied = L.drain_hermes_challenges(apply=True, max_age_days=7)
    after = path.read_text(encoding="utf-8")
    assert after.startswith(before.rstrip()[:40]) or before.splitlines()[0] in after
    assert len(after.splitlines()) > len(before.splitlines())
    assert "SPACEX_TEST" in after
    assert applied["deleted"] == 0
    rows = [json.loads(x) for x in after.splitlines() if x.strip()]
    latest = L.challenge_latest(rows)
    pending = L.challenge_pending(latest)
    assert len(pending) == 1
    assert pending[0]["stream_id"] == "hermes-challenge-keep"


def _backdate_case(path: Path, decision_id: str, when: datetime) -> None:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("decision_id") == decision_id:
            rec["occurred_at"] = when.isoformat()
            pl = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
            facts = pl.setdefault("decision_time_facts", {})
            if isinstance(facts, dict):
                facts["as_of"] = when.isoformat()
        rows.append(json.dumps(rec, sort_keys=True))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_observe_expires_only_old_cases_and_never_invents_pnl(cio: Path, monkeypatch: pytest.MonkeyPatch):
    from lib import cio_production_case as cs
    monkeypatch.setattr(cs, "DEFAULT_PATH", cio / "cio_production_cases.jsonl")
    cases_file = cio / "cio_production_cases.jsonl"
    old = {
        "decision_id": "dec_old",
        "symbol": "SCHD",
        "action": "TRIM",
        "decision_input_digest": "in_old",
        "decision_evidence_digest": "ev_old",
    }
    young = {
        "decision_id": "dec_young",
        "symbol": "JEPI",
        "action": "HOLD",
        "decision_input_digest": "in_y",
        "decision_evidence_digest": "ev_y",
    }
    open_case_from_decision(old)
    open_case_from_decision(young)
    _backdate_case(cases_file, "dec_old", datetime.now(timezone.utc) - timedelta(days=10))
    dry = L.observe_overdue_cases(apply=False, horizon_days=7)
    assert dry["observed_expired"] == 1
    assert dry["invented_pnl"] == 0
    raw = (cio / "cio_production_cases.jsonl").read_text(encoding="utf-8")
    assert "EXPIRED" not in raw
    applied = L.observe_overdue_cases(apply=True, horizon_days=7)
    assert applied["observed_expired"] == 1
    assert applied["scored"] >= 1
    folded = materialize_cases(path=cio / "cio_production_cases.jsonl")
    by = {c["decision_id"]: c for c in folded}
    assert (by["dec_old"].get("outcome") or {}).get("outcome_status") == "EXPIRED"
    assert by["dec_old"]["status"] in {"MATURED", "SCORED"}
    assert by["dec_young"]["status"] == "OPEN"
    assert "POSITIVE" not in json.dumps(by["dec_old"].get("outcome"))
    assert "NEGATIVE" not in json.dumps(by["dec_old"].get("outcome"))


def test_rebuild_uses_real_ids_only(cio: Path, monkeypatch: pytest.MonkeyPatch):
    from lib import cio_production_case as cs
    monkeypatch.setattr(cs, "DEFAULT_PATH", cio / "cio_production_cases.jsonl")
    path = cio / "hermes_challenge_queue.jsonl"
    _enqueue(path, symbols=["SCHD"], when=datetime.now(timezone.utc), stream="hermes-challenge-schd",
             extra_meta={"research_id": "res_abc123"})
    open_case_from_decision({
        "decision_id": "dec_schd",
        "symbol": "SCHD",
        "action": "HOLD",
        "decision_input_digest": "in_s",
        "decision_evidence_digest": "ev_s",
        "decision_time_facts": {"as_of": datetime.now(timezone.utc).isoformat()},
    })
    (cio / "aif_memory.jsonl").write_text(json.dumps({
        "memory_id": "mem_schd_1",
        "status": "ACTIVE",
        "symbols": ["SCHD"],
        "content": "operator preference",
        "admission_reason": "test",
    }) + "\n", encoding="utf-8")
    snap = L.rebuild_lineages()
    assert snap["count"] >= 1
    schd = next(r for r in snap["lineages"] if r["symbol"] == "SCHD")
    assert schd["lineage_id"].startswith("lin_")
    assert "hermes-challenge-schd" in schd["research_request_ids"]
    assert "mem_schd_1" in schd["memory_ids"]
    assert schd["cio_case_id"]
    assert L.get_lineage(schd["lineage_id"])["symbol"] == "SCHD"


def test_api_get_lineage_and_404(cio: Path):
    snap = L.rebuild_lineages()
    code, body = api.handle_get("")
    assert code == 200
    assert body["authority"] == "READ_ONLY_ADVISORY"
    assert body["financial_action"] is False
    code, body = api.handle_get("lineage")
    assert code == 200
    assert "lineages" in body
    if snap.get("count"):
        lid = snap["lineages"][0]["lineage_id"]
        code, one = api.handle_get(f"lineage/{lid}")
        assert code == 200
        assert one["lineage"]["lineage_id"] == lid
    code, missing = api.handle_get("lineage/lin_does_not_exist")
    assert code == 404


def test_api_v2_mounts_intelligence_route():
    src = Path(__file__).resolve().parents[1].joinpath("scripts/api_v2.py").read_text()
    assert 'base_path.startswith("/api/v3/intelligence")' in src
    assert "api_v3_intelligence" in src


def test_cc_closed_loop_tab_exists():
    hub = Path(__file__).resolve().parents[1].joinpath(
        "apps/command-center-v3/src/pages/IntelligenceHub.tsx"
    ).read_text()
    assert "Closed Loop" in hub
    assert "ClosedLoopPanel" in hub
    app = Path(__file__).resolve().parents[1].joinpath(
        "apps/command-center-v3/src/App.tsx"
    ).read_text()
    assert "closed-loop" in app


def test_delegation_counts_latest_per_stream(cio: Path, monkeypatch: pytest.MonkeyPatch):
    path = cio / "hermes_challenge_queue.jsonl"
    now = datetime.now(timezone.utc)
    _enqueue(path, symbols=["SCHD"], when=now, stream="hermes-challenge-a")
    q = HermesChallengeQueue(event_store_path=path)
    q.expire("hermes-challenge-a", actor_id="test", reason="done")
    # two ENQUEUED events exist historically, latest is EXPIRED
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    latest = L.challenge_latest(rows)
    pending = L.challenge_pending(latest)
    assert pending == []
    enqueued_events = sum(1 for r in rows if r.get("event_type") == "HERMES_CHALLENGE_ENQUEUED")
    assert enqueued_events >= 1
    assert len(pending) != enqueued_events or enqueued_events == 0
