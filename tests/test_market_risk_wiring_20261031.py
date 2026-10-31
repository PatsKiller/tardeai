"""Market Risk Engine wiring (DSN-20261031-market-risk-engine P3-T7): Telegram ACK RED, the stalled-escalation
health-tick page, and the CommsHub market_risk colour. Hermetic: temp episode store, patched transport, no network.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib import market_risk_ack_telegram as mra  # noqa: E402
from scripts.lib.market_risk import escalation  # noqa: E402

COVERS = ["scripts/check_market_risk_escalation.py"]

T0 = datetime(2026, 10, 29, 22, 15, tzinfo=timezone.utc)  # 18:15 ET
CHAT = "1111"


def _seed(path: Path, *, tier: str = "RED", status: str = "OPEN", last_send_min_ago: int | None = 80) -> str:
    sends = []
    if last_send_min_ago is not None:
        sends.append({"at": (T0 - timedelta(minutes=last_send_min_ago)).isoformat(), "kind": "initial", "ok": True})
    ep = {
        "id": "ep-test-1",
        "tier": tier,
        "status": status,
        "anchor_at": (T0 - timedelta(minutes=120)).isoformat(),
        "opened_at": (T0 - timedelta(minutes=120)).isoformat(),
        "sends": sends,
        "repeats": 0,
    }
    path.write_text(json.dumps({"schema": "MarketRiskEpisodeStore@v1", "episodes": [ep]}), encoding="utf-8")
    return ep["id"]


# ── ACK RED ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["ACK RED", "ack red", "ACK", "Ack.", " ack red "])
def test_ack_text_forms_are_recognised(text):
    assert mra.is_ack_text(text)


@pytest.mark.parametrize("text", ["acknowledge", "ACK RED please trim", "hold #12", "", None, "back"])
def test_other_text_is_not_an_ack(text):
    assert not mra.is_ack_text(text)
    assert mra.handle_ack_text(text or "", chat_id=CHAT, allowed_chats=[CHAT]) is None


def test_ack_red_acknowledges_the_open_episode(tmp_path):
    store = tmp_path / "episodes.json"
    _seed(store)
    reply = mra.handle_ack_text("ACK RED", chat_id=CHAT, from_id=42, allowed_chats=[CHAT], now=T0, path=store)
    assert reply.startswith("Acknowledged market risk RED")
    ep = escalation.open_episode(escalation.load(store))
    assert ep["status"] == "ACKED" and ep["acknowledged_by"] == "telegram:42"
    assert ep["acks"][0]["channel"] == "telegram"


def test_non_allowlisted_chat_is_refused(tmp_path):
    store = tmp_path / "episodes.json"
    _seed(store)
    reply = mra.handle_ack_text("ACK RED", chat_id="9999", allowed_chats=[CHAT], now=T0, path=store)
    assert reply.startswith("Not acknowledged: this chat is not an operator chat")
    assert escalation.open_episode(escalation.load(store))["status"] == "OPEN"


def test_nothing_open(tmp_path):
    store = tmp_path / "episodes.json"
    reply = mra.handle_ack_text("ACK", chat_id=CHAT, allowed_chats=[CHAT], now=T0, path=store)
    assert reply.startswith("Nothing open")


def test_wrong_tier_word_is_refused(tmp_path):
    store = tmp_path / "episodes.json"
    _seed(store, tier="ORANGE")
    reply = mra.handle_ack_text("ACK RED", chat_id=CHAT, allowed_chats=[CHAT], now=T0, path=store)
    assert "the open episode is ORANGE" in reply
    assert escalation.open_episode(escalation.load(store))["status"] == "OPEN"


def test_poller_routes_ack_before_free_text():
    src = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")
    assert "elif _is_market_risk_ack(text):" in src
    assert src.index("_is_market_risk_ack(text)") < src.index("_is_digest_hold_text(lower)")


# ── stalled-escalation page ───────────────────────────────────────────────────


def _run(tmp_path, monkeypatch, *, now, dry=False, sends=None):
    import check_market_risk_escalation as chk

    calls = sends if sends is not None else []

    def fake_send(message, **kw):
        calls.append((message, kw))
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", fake_send)
    argv = ["--now", now.isoformat(), "--state-root", str(tmp_path), "--episodes", str(tmp_path / "episodes.json")]
    if dry:
        argv.append("--dry-run")
    return chk.main(argv), calls


def test_stalled_red_pages_p1_once_per_hour(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / "episodes.json", last_send_min_ago=80)
    rc, calls = _run(tmp_path, monkeypatch, now=T0)
    assert rc == 3 and len(calls) == 1
    msg, kw = calls[0]
    assert "ESCALATION STALLED" in msg and "80 min" in msg
    assert kw["priority"] == "P1" and kw["message_class"] == "market_risk" and kw["dedupe_minutes"] == 0
    rc, calls = _run(tmp_path, monkeypatch, now=T0 + timedelta(minutes=30), sends=calls)
    assert rc == 3 and len(calls) == 1  # inside the hour: no second page
    rc, calls = _run(tmp_path, monkeypatch, now=T0 + timedelta(minutes=61), sends=calls)
    assert rc == 3 and len(calls) == 2


def test_recent_send_is_not_stalled(tmp_path, monkeypatch):
    _seed(tmp_path / "episodes.json", last_send_min_ago=20)
    rc, calls = _run(tmp_path, monkeypatch, now=T0)
    assert rc == 0 and calls == []


def test_acked_or_orange_is_silent(tmp_path, monkeypatch):
    _seed(tmp_path / "episodes.json", status="ACKED", last_send_min_ago=200)
    assert _run(tmp_path, monkeypatch, now=T0) == (0, [])
    _seed(tmp_path / "episodes.json", tier="ORANGE", last_send_min_ago=200)
    assert _run(tmp_path, monkeypatch, now=T0) == (0, [])


def test_dry_run_sends_nothing_and_writes_no_state(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / "episodes.json", last_send_min_ago=80)
    rc, calls = _run(tmp_path, monkeypatch, now=T0, dry=True)
    assert rc == 3 and calls == []
    assert "ESCALATION STALLED" in capsys.readouterr().out
    assert not (tmp_path / "data/runtime/market_risk/escalation_stall_state.json").exists()


def test_delivery_failure_is_loud(tmp_path, monkeypatch):
    import check_market_risk_escalation as chk
    import telegram_alert

    _seed(tmp_path / "episodes.json", last_send_min_ago=80)
    monkeypatch.setattr(telegram_alert, "send_telegram", lambda *a, **k: False)
    rc = chk.main(
        ["--now", T0.isoformat(), "--state-root", str(tmp_path), "--episodes", str(tmp_path / "episodes.json")]
    )
    assert rc == 1
    assert not (tmp_path / "data/runtime/market_risk/escalation_stall_state.json").exists()


def test_health_tick_row_present_and_watchdog_last():
    steps = json.loads((ROOT / "config" / "health_tick_steps.json").read_text(encoding="utf-8"))
    steps = steps["steps"] if isinstance(steps, dict) else steps
    ids = [s["step_id"] for s in steps]
    assert "market-risk-escalation-stall" in ids and ids[-1] == "pipeline-watchdog"
    row = next(s for s in steps if s["step_id"] == "market-risk-escalation-stall")
    assert row["command"] == ["$PY", "scripts/check_market_risk_escalation.py"] and row["finding_rc"] == [3]


# ── CommsHub colour ───────────────────────────────────────────────────────────


def test_commshub_has_market_risk_colour_from_tokens():
    src = (ROOT / "apps/command-center-v3/src/components/comms/CommsHubParts.tsx").read_text(encoding="utf-8")
    assert "market_risk: TOKENS.danger" in src
