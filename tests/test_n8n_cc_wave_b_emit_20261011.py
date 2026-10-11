"""Wave B CC orchestrate: research-intake + watch-refresh emit helpers (hermetic)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import n8n_cc_wave_b_emit as E
from scripts.lib import n8n_research_intake as ri
from scripts.lib import n8n_watch_refresh_events as wr
from scripts.lib import n8n_coordination_projection as P

NOW = datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc)
SHA = "a" * 40


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("TRADEAI_SERVED_SHA", SHA)
    monkeypatch.setenv(E.EMIT_MODE_ENV, "dry_run")
    return root


def test_emit_mode_aliases():
    assert E.emit_mode({E.EMIT_MODE_ENV: "off"}) == "off"
    assert E.emit_mode({E.EMIT_MODE_ENV: "0"}) == "off"
    assert E.emit_mode({E.EMIT_MODE_ENV: "dry_run"}) == "dry_run"
    assert E.emit_mode({E.EMIT_MODE_ENV: "1"}) == "apply"
    assert E.emit_mode({}) == "dry_run"


def test_research_intake_dry_run_writes_sidecar_and_spotlight(env):
    out = E.emit_research_intake(
        subject="TOPIC-A", request_type="topic", requested_by="operator",
        reason="unit", now=NOW, root=env, mode="dry_run",
    )
    assert out["ok"] and out["mode"] == "dry_run"
    assert out["gateway"]["state"] == "DRY_RUN"
    side = Path(out["sidecar_path"])
    assert side.is_file() and json.loads(side.read_text())["subject"] == "TOPIC-A"
    spot = json.loads((env / E.SPOTLIGHT_REL).read_text())
    assert spot["lanes"]["research-intake"]["subject"] == "TOPIC-A"


def test_watch_refresh_started_and_terminal(env):
    start = E.emit_watch_refresh(run_id=42, phase="started", symbols=["AAPL"], now=NOW, root=env)
    assert start["ok"] and start["phase"] == "started" and start["idempotency_key"].startswith("wr-")
    term = E.emit_watch_refresh(
        run_id=42, phase="terminal", terminal_state="COMPLETE", now=NOW, root=env,
    )
    assert term["ok"] and term["terminal_state"] == "COMPLETE"
    assert term["idempotency_key"] != start["idempotency_key"]
    spot = json.loads((env / E.SPOTLIGHT_REL).read_text())
    assert spot["lanes"]["watch-refresh"]["run_id"] == 42


def test_apply_posts_via_injected_client(env):
    seen: list[dict] = []

    class _C:
        def accept_event(self, event):
            seen.append(dict(event))
            return {"state": "ACCEPTED", "durable": True, "duplicate": False}

    out = E.emit_research_intake(
        subject="TOPIC-B", request_type="topic", requested_by="cio-wake",
        reason="apply path", now=NOW, root=env, mode="apply", client=_C(),
    )
    assert out["gateway"]["state"] == "ACCEPTED" and out["gateway"]["durable"] is True
    assert seen and seen[0]["lane_id"] == ri.LANE


def test_off_is_noop(env):
    out = E.emit_watch_refresh(run_id=1, phase="started", mode="off", root=env)
    assert out.get("skipped") is True
    assert not (env / "data" / "runtime" / wr.SIDECAR_REL).exists()


def test_projection_spotlights_and_idempotency(env, tmp_path):
    E.emit_research_intake(subject="TOPIC-A", request_type="topic", requested_by="operator",
                           reason="x", now=NOW, root=env)
    (env / "data" / "runtime" / "n8n_research_intake_last.json").write_text(
        json.dumps({"ok": True, "ok_at": NOW.isoformat(), "listed": 1, "enqueued_today": 1})
    )
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerReceiptStore

    path = tmp_path / "l.sqlite"
    ledger = CoordinationLedger(path)
    store = LedgerReceiptStore(ledger)
    rec = {
        "schema": "N8nCoordinationReceipt@v1", "state": "ACCEPTED", "reason": None,
        "event_id": "evt-1", "source_project": "trade-ai", "lane_id": "research-intake",
        "idempotency_key": "rq-test", "origin_sha": SHA, "recorded_at": NOW.isoformat(),
        "artifact_ref": {"store": "data/runtime", "ref": "x.json"}, "durable": True,
    }
    store["trade-ai:rq-test"] = {"payload_hash": "h", "receipt": rec}
    ledger.close()
    out = P.project(path)
    assert out["status"] == "OK"
    assert out["items"][0]["idempotency_key"] == "rq-test"
    assert out["items"][0]["artifact_ref"]["ref"] == "x.json"
    assert out["items"][0]["wave_b"] is True
    lanes = {s["lane_id"] for s in out["spotlights"]}
    assert "research-intake" in lanes and "n8n-research-intake-consumer" in lanes


def test_watch_refresh_contract_validates():
    ev, side = wr.build_event(run_id=7, phase="started", origin_sha=SHA, now=NOW)
    assert ev["lane_id"] == wr.LANE and side["run_id"] == 7
    with pytest.raises(wr.WatchRefreshEventError):
        wr.build_event(run_id=7, phase="terminal", origin_sha=SHA, terminal_state="RUNNING")
