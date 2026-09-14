"""The research heartbeat, 2026-09-14. Offline.

Measured failures of the CIO Hermes research queue, 7 to 14 September:
- 62% of requests failed and no monitor alarmed;
- refusals quoting "Strong Sell" were thrown away;
- breaker trips were never retried;
- the Health Agent's automatic fixes exited 127 on a doubled interpreter path, 36,365 times.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_hermes_queue_health as qh  # noqa: E402
from scripts.lib import cio_hermes_research as h  # noqa: E402
from scripts.lib.cio_research_fail_policy import classify_failure  # noqa: E402
from scripts.lib.hermes_research_backend import HermesBackendError, assert_no_execution_language  # noqa: E402

# COVERS is read by tests/test_alarm_coverage.py as "this test fires the file's send_telegram
# sites". These tests exercise research_lane_health.fix_hint, health_agent.collect_research_heartbeat
# and claude_escalation_handler.resolve_relative_venv, never their Telegram alarms, so those three
# files are deliberately not listed.
COVERS = [
    "scripts/lib/cio_hermes_queue_health.py",
    "scripts/lib/cio_hermes_research.py",
    "scripts/lib/hermes_research_backend.py",
    "scripts/lib/hermes_bridge_backend.py",
    "scripts/lib/cio_research_fail_policy.py",
    "scripts/lib/research_lane_health.py",
]
NOW = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)


# ── the guard: facts pass, advice still refuses ─────────────────────────────

@pytest.mark.parametrize("fact", [
    "The deterministic analyst_rating remains 'Strong Sell' with verified_producer false.",
    "Analyst rating: Buy · 20 analysts · mean target $67.43",
    "One institutional buy event in the last filing; sell-side estimates rose.",
    "SpaceX sought to buy an AI startup, per the report.",
    "The sell-off in semis dragged the name 4%.",
])
def test_third_party_labels_and_market_nouns_are_not_execution_language(fact):
    assert_no_execution_language(fact)


@pytest.mark.parametrize("advice", [
    "we should buy now the dip",
    "The advisory would change to a buy if the risk clears.",
    "a cautious buy near support",
    "place stop under 100",
    "sell the position into strength",
])
def test_advice_and_stance_still_refuse(advice):
    with pytest.raises(HermesBackendError):
        assert_no_execution_language(advice)


# ── the classifier: transient bridge failures are retryable ────────────────

@pytest.mark.parametrize("error", [
    'bridge HTTP 503: {"error": {"code": "CIRCUIT_OPEN", "message": "CIO bridge circuit breaker open"}}',
    "RemoteDisconnected:Remote end closed connection without response",
    "bridge unreachable: <urlopen error [Errno 111] Connection refused>",
])
def test_breaker_and_dropped_connections_are_retryable_provider_errors(error):
    info = classify_failure(error)
    assert info["class"] == "provider_error" and info["retryable"] is True


# ── the escalation handler: absolute interpreter paths are left alone ──────

def test_retry_command_venv_resolution_never_doubles_an_absolute_path():
    import claude_escalation_handler as esc
    dev = "/home/u/tree/.venv/bin/python"
    assert esc.resolve_relative_venv(".venv/bin/python scripts/x.py", dev) == f"{dev} scripts/x.py"
    absolute = "bash scripts/safe_flock.sh /tmp/l.lock /home/u/tree/.venv/bin/python scripts/y.py"
    assert esc.resolve_relative_venv(absolute, dev) == absolute
    assert esc.resolve_relative_venv("cd a && ./.venv/bin/python z.py", dev) == "cd a && ./.venv/bin/python z.py"


# ── the queue lane ──────────────────────────────────────────────────────────

def _ledger(tmp_path, rows):
    p = tmp_path / "requests.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _ts(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def test_queue_lane_fires_on_failure_rate_and_names_the_dominant_class(tmp_path):
    rows = []
    for i in range(6):
        rows.append({"research_id": f"r{i}", "status": "queued", "ts": _ts(5)})
        rows.append({"research_id": f"r{i}", "status": "failed", "ts": _ts(4),
                     "error": "execution language not allowed in research output: buy"})
    rows += [{"research_id": "ok1", "status": "completed", "ts": _ts(3)}]
    lane = qh.collect_cio_hermes_queue_health(now=NOW, path=_ledger(tmp_path, rows))
    assert lane["ok"] is False and "failure_rate_24h:6/7" in lane["firing"]
    assert lane["dominant_class"] == "execution_language"


def test_queue_lane_fires_on_a_stalled_request_and_is_quiet_when_healthy(tmp_path):
    stalled = qh.collect_cio_hermes_queue_health(
        now=NOW, path=_ledger(tmp_path, [{"research_id": "q", "status": "queued", "ts": _ts(5)}]))
    assert "queue_stalled:1" in stalled["firing"]
    healthy = qh.collect_cio_hermes_queue_health(now=NOW, path=_ledger(tmp_path, [
        {"research_id": f"c{i}", "status": "completed", "ts": _ts(2)} for i in range(6)]))
    assert healthy["ok"] is True and healthy["firing"] == []


def test_queue_lane_is_ok_without_a_ledger(tmp_path):
    lane = qh.collect_cio_hermes_queue_health(now=NOW, path=tmp_path / "absent.jsonl")
    assert lane["ok"] is True and lane["ledger_present"] is False


def test_lane_hint_names_the_cause(tmp_path):
    import research_lane_health as rlh
    hint = rlh.fix_hint({"lane": "cio-hermes-queue", "firing": ["failure_rate_24h:6/7"],
                         "dominant_class": "provider_error", "by_class": {"provider_error": 6}})
    assert "replays" in hint and "CAUSE NOT DIAGNOSED" not in hint


# ── replay: transient failures go back in the queue once ───────────────────

@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "PROJECTION_PATH", tmp_path / "projection.json")
    monkeypatch.setattr(h, "REQUEST_PATH", tmp_path / "requests.jsonl")
    return tmp_path


def _failed(rid, error, hours_ago, fp=None, replay_count=0):
    return {"research_id": rid, "status": "failed", "error": error, "fingerprint": fp or f"fp-{rid}",
            "plan_id": f"plan-{rid}", "updated_ts": _ts(hours_ago), "replay_count": replay_count}


def test_replay_requeues_transient_failures_once_and_leaves_refusals(store):
    proj = h._empty_projection()
    proj["by_research_id"] = {
        "t": _failed("t", "RemoteDisconnected:Remote end closed connection", 1),
        "x": _failed("x", "execution language not allowed in research output: buy", 1),
        "c": _failed("c", 'bridge HTTP 429: {"error": {"code": "COST_CAP_EXCEEDED"}}', 1),
        "fresh": _failed("fresh", "RemoteDisconnected", 0.05),
        "twice": _failed("twice", "RemoteDisconnected", 1, replay_count=1),
    }
    h._save_projection(proj)
    assert h.replay_retryable_failures(now=NOW) == ["t"]
    after = h._load_projection()["by_research_id"]
    assert after["t"]["status"] == "queued" and after["t"]["replay_count"] == 1
    assert {after[k]["status"] for k in ("x", "c", "fresh", "twice")} == {"failed"}
    assert "HERMES_RESEARCH_REPLAYED" in (store / "requests.jsonl").read_text()


def test_replay_skips_a_question_a_newer_request_already_owns(store):
    proj = h._empty_projection()
    proj["by_research_id"] = {"old": _failed("old", "RemoteDisconnected", 1, fp="same")}
    proj["by_fingerprint_open"] = {"same": {"research_id": "newer", "status": "queued"}}
    h._save_projection(proj)
    assert h.replay_retryable_failures(now=NOW) == []


# ── lost writes: locked, detected, restored ────────────────────────────────

def _requested(rid, fp, hours_ago):
    return {"event": "HERMES_RESEARCH_REQUESTED", "research_id": rid, "plan_id": f"plan-{rid}", "fingerprint": fp,
            "priority": "high", "status": "queued", "symbol": "DIVI", "authority": "READ_ONLY_ADVISORY",
            "created_ts": _ts(hours_ago), "updated_ts": _ts(hours_ago), "questions": [{"id": "q1", "text": "x"}]}


def test_restore_reprojects_a_request_the_projection_lost(store):
    h._save_projection(h._empty_projection())
    rows = [_requested("lost1", "fpL", 20), _requested("ancient", "fpA", 80)]
    (store / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert h.restore_lost_requests(now=NOW, apply=False) == ["lost1"]
    assert "lost1" not in h._load_projection()["by_research_id"]
    assert h.restore_lost_requests(now=NOW) == ["lost1"]
    proj = h._load_projection()
    assert proj["by_research_id"]["lost1"]["status"] == "queued"
    assert proj["by_fingerprint_open"]["fpL"]["research_id"] == "lost1"
    assert h.restore_lost_requests(now=NOW) == []
    assert "HERMES_RESEARCH_RESTORED" in (store / "requests.jsonl").read_text()


def test_restore_skips_a_question_answered_after_it_was_asked(store):
    proj = h._empty_projection()
    proj["by_fingerprint_completed"] = {"fpD": {"completed_ts": _ts(1)}}
    h._save_projection(proj)
    (store / "requests.jsonl").write_text(json.dumps(_requested("done", "fpD", 5)) + "\n", encoding="utf-8")
    assert h.restore_lost_requests(now=NOW) == []


def test_projection_transaction_is_reentrant_and_uses_a_lock_file(store):
    with h.projection_transaction():
        with h.projection_transaction():
            h._save_projection(h._empty_projection())
    assert (store / "projection.lock").exists()


def test_queue_lane_reports_requests_the_projection_lost(tmp_path):
    ledger = _ledger(tmp_path, [_requested("gone", "fpG", 2)])
    (tmp_path / "hermes_research_projection.json").write_text(json.dumps({"by_research_id": {}}), encoding="utf-8")
    lane = qh.collect_cio_hermes_queue_health(now=NOW, path=ledger)
    assert "requests_lost:1" in lane["firing"] and lane["lost"] == ["gone"]


# ── the health agent counts the research heartbeat ─────────────────────────

def test_health_agent_scores_a_firing_research_lane_as_critical(tmp_path, monkeypatch):
    import health_agent as ha
    status = tmp_path / "research_lane_health.json"
    status.write_text(json.dumps({"lanes": {"cio-hermes-queue": {"ok": False, "firing": ["failure_rate_24h:13/18"]},
                                            "drive-sync": {"ok": False, "firing": ["stale"]},
                                            "deepseek": {"ok": True}}}), encoding="utf-8")
    monkeypatch.setattr(ha, "RESEARCH_LANE_STATUS", status)
    findings = {f["type"]: f for f in ha.collect_research_heartbeat()}
    assert findings["research_lane_firing:cio-hermes-queue"]["severity"] == "critical"
    assert findings["research_lane_firing:drive-sync"]["severity"] == "warning"
    assert "research_lane_firing:deepseek" not in findings


def test_health_agent_flags_a_research_monitor_that_never_ran(tmp_path, monkeypatch):
    import health_agent as ha
    monkeypatch.setattr(ha, "RESEARCH_LANE_STATUS", tmp_path / "absent.json")
    assert ha.collect_research_heartbeat()[0]["type"] == "research_heartbeat_unmonitored"


# ── the bridge backend rewrites once, still guarded ────────────────────────

def _body(summary):
    return json.dumps({"as_of": NOW.isoformat(), "answers": [{"question_id": "q1", "status": "answered",
                       "summary": summary, "detail": "", "confidence": 0.6, "citations": []}], "findings": []})


def _request():
    return {"authority": "READ_ONLY_ADVISORY", "research_id": "r1", "symbol": "HPE",
            "questions": [{"id": "q1", "text": "What changed?", "intent": "other"}]}


def test_bridge_backend_rewrites_a_refused_draft_once(monkeypatch):
    from scripts.lib.hermes_bridge_backend import BridgeHermesResearchBackend
    replies = iter([_body("The advisory would change to a buy if margins hold."),
                    _body("The thesis strengthens if margins hold for two quarters.")])
    be = BridgeHermesResearchBackend()
    monkeypatch.setattr(be, "_chat_completions", lambda messages: next(replies))
    body = be.run(_request())
    assert "strengthens" in body["answers"][0]["summary"]
    assert any("rewritten once" in x for x in body.get("limitations") or [])


def test_bridge_backend_fails_when_the_rewrite_still_carries_advice(monkeypatch):
    from scripts.lib import hermes_bridge_backend as bb
    be = bb.BridgeHermesResearchBackend()
    monkeypatch.setattr(be, "_chat_completions", lambda messages: _body("a cautious buy near support"))
    # The backend imports `lib.hermes_research_backend` first, so catch the class it actually raises.
    with pytest.raises(bb.HermesBackendError):
        be.run(_request())
