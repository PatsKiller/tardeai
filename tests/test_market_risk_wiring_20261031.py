"""Market Risk Engine wiring (DSN-20261031-market-risk-engine P3-T7) after the #2354 review: Telegram ACK RED with the
tier checked under the ledger lock, reply binding and the from.id allowlist; the stalled-escalation page judged from
the evaluator's schedule and run receipt (capped at 3 pages per episode); the evaluator run receipt; the CommsHub
colour. Hermetic: temp episode store and state root, patched transport, no network, no DB.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib import market_risk_ack_telegram as mra  # noqa: E402
from scripts.lib.market_risk import escalation  # noqa: E402

COVERS = ["scripts/check_market_risk_escalation.py"]

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 29, 18, 15, tzinfo=ET)  # Thu 18:15 ET (inside the evaluator schedule)
CHAT = "1111"  # private chat: chat id == operator user id


@pytest.fixture(autouse=True)
def _no_from_ids_env(monkeypatch):
    monkeypatch.delenv("TRADEAI_OPERATOR_FROM_IDS", raising=False)


def _seed(path: Path, *, tier: str = "RED", status: str = "OPEN", anchor: datetime | None = None, repeats: int = 0):
    anchor = anchor or (T0 - timedelta(minutes=120))
    ep = {
        "id": "ep-test-1",
        "tier": tier,
        "current_tier": tier,
        "status": status,
        "opened_at": anchor.isoformat(),
        "anchor_at": anchor.isoformat(),
        "sends": [{"at": anchor.isoformat(), "kind": "initial", "ok": True}],
        "repeats": repeats,
        "acks": [],
    }
    path.write_text(json.dumps({"schema": "MarketRiskEpisodeStore@v1", "episodes": [ep]}), encoding="utf-8")
    return ep["id"]


def _status(store: Path) -> str:
    return escalation.open_episode(escalation.load(store))["status"]


# ── ACK: recognition ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["ACK RED", "ack red", "ACK", "Ack.", " ack orange "])
def test_ack_text_forms_are_recognised(text):
    assert mra.is_ack_text(text)


@pytest.mark.parametrize("text", ["acknowledge", "ACK RED please trim", "hold #12", "", None, "back"])
def test_other_text_is_not_an_ack(text):
    assert not mra.is_ack_text(text)
    assert mra.handle_ack_text(text or "", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT]) is None


def test_card_tier_parsing():
    assert mra.card_tier("🔴 MARKET RISK RED 83/100 · 5 of 9 categories confirm") == "RED"
    assert (
        mra.card_tier("🟠 ORANGE ALERT ACTIVE — acknowledgment required (repeat 1, 60 min since it opened)") == "ORANGE"
    )
    assert mra.card_tier("PR merge digest") is None


# ── ACK: who may acknowledge ──────────────────────────────────────────────────


def test_ack_red_acknowledges_the_open_red(tmp_path):
    store = tmp_path / "e.json"
    _seed(store)
    reply = mra.handle_ack_text("ACK RED", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], now=T0, path=store)
    assert reply.startswith("Acknowledged market risk RED")
    ep = escalation.open_episode(escalation.load(store))
    assert ep["status"] == "ACKED" and ep["acknowledged_by"] == f"telegram:{CHAT}"


def test_non_allowlisted_chat_is_refused(tmp_path):
    store = tmp_path / "e.json"
    _seed(store)
    reply = mra.handle_ack_text("ACK RED", chat_id="9999", from_id="9999", allowed_chats=[CHAT], now=T0, path=store)
    assert reply.startswith("Not acknowledged: this chat is not an operator chat") and _status(store) == "OPEN"


def test_other_member_of_an_allowlisted_group_is_refused(tmp_path, monkeypatch):
    store = tmp_path / "e.json"
    _seed(store)
    group = "-100777"
    monkeypatch.setenv("TRADEAI_OPERATOR_FROM_IDS", CHAT)
    reply = mra.handle_ack_text("ACK RED", chat_id=group, from_id="5555", allowed_chats=[group], now=T0, path=store)
    assert reply.startswith("Not acknowledged: only the operator") and _status(store) == "OPEN"
    reply = mra.handle_ack_text("ACK RED", chat_id=group, from_id=CHAT, allowed_chats=[group], now=T0, path=store)
    assert reply.startswith("Acknowledged")


def test_missing_from_id_is_refused(tmp_path):
    store = tmp_path / "e.json"
    _seed(store)
    reply = mra.handle_ack_text("ACK RED", chat_id=CHAT, from_id=None, allowed_chats=[CHAT], now=T0, path=store)
    assert reply.startswith("Not acknowledged: only the operator") and _status(store) == "OPEN"


def test_nothing_open(tmp_path):
    reply = mra.handle_ack_text(
        "ACK RED", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], now=T0, path=tmp_path / "e.json"
    )
    assert reply.startswith("Nothing open")


# ── ACK: tier binding ─────────────────────────────────────────────────────────


def test_ack_orange_on_a_red_is_refused(tmp_path):
    store = tmp_path / "e.json"
    _seed(store, tier="RED")
    reply = mra.handle_ack_text("ACK ORANGE", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], now=T0, path=store)
    assert "the open episode is RED, not ORANGE" in reply and _status(store) == "OPEN"


def test_upgrade_between_read_and_ack_is_refused_under_the_lock(tmp_path, monkeypatch):
    """The handler reads ORANGE, then the evaluator upgrades the same episode to RED before the ACK is written: the
    tier check runs under the ledger lock, so "ACK ORANGE" must not silence the RED (review of #2354)."""
    store = tmp_path / "e.json"
    _seed(store, tier="ORANGE")
    import importlib

    real = {}
    for name in ("lib.market_risk.escalation", "scripts.lib.market_risk.escalation"):
        mod = importlib.import_module(name)
        real[name] = mod.open_episode

        def stale_then_upgrade(data, _mod=mod, _real=mod.open_episode):
            ep = _real(data)
            snap = dict(ep)  # what the handler sees: ORANGE
            raw = json.loads(store.read_text())
            raw["episodes"][0].update(tier="RED", current_tier="RED")  # the upgrade lands now
            store.write_text(json.dumps(raw))
            _mod.open_episode = _real
            return snap

        monkeypatch.setattr(mod, "open_episode", stale_then_upgrade)
    reply = mra.handle_ack_text("ACK ORANGE", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], now=T0, path=store)
    assert "the open episode is RED, not ORANGE" in reply
    raw = json.loads(store.read_text())["episodes"][0]
    assert raw["status"] == "OPEN" and raw["tier"] == "RED" and not raw.get("acks")


def test_bare_ack_needs_a_reply_to_a_card(tmp_path):
    store = tmp_path / "e.json"
    _seed(store, tier="ORANGE")
    reply = mra.handle_ack_text("ACK", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], now=T0, path=store)
    assert "A bare ACK must answer a market-risk card" in reply and _status(store) == "OPEN"


def test_bare_ack_never_acknowledges_red(tmp_path):
    store = tmp_path / "e.json"
    _seed(store, tier="RED")
    card = {"text": "🔴 MARKET RISK RED 83/100", "date": int(T0.timestamp())}
    reply = mra.handle_ack_text(
        "ACK", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], reply_to=card, now=T0, path=store
    )
    assert "a RED needs the words ACK RED" in reply and _status(store) == "OPEN"


def test_bare_ack_replying_to_the_current_orange_card_acknowledges(tmp_path):
    store = tmp_path / "e.json"
    _seed(store, tier="ORANGE")
    card = {"text": "🟠 MARKET RISK ORANGE 63/100", "date": int((T0 - timedelta(minutes=30)).timestamp())}
    reply = mra.handle_ack_text(
        "ACK", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], reply_to=card, now=T0, path=store
    )
    assert reply.startswith("Acknowledged market risk ORANGE") and _status(store) == "ACKED"


def test_bare_ack_replying_to_an_older_card_is_refused(tmp_path):
    store = tmp_path / "e.json"
    _seed(store, tier="ORANGE", anchor=T0 - timedelta(minutes=10))
    card = {"text": "🟠 MARKET RISK ORANGE 63/100", "date": int((T0 - timedelta(hours=3)).timestamp())}
    reply = mra.handle_ack_text(
        "ACK", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], reply_to=card, now=T0, path=store
    )
    assert "older than the open ORANGE episode" in reply and _status(store) == "OPEN"


def test_bare_ack_to_an_orange_card_after_upgrade_to_red_is_refused(tmp_path):
    store = tmp_path / "e.json"
    _seed(store, tier="RED")
    card = {"text": "🟠 MARKET RISK ORANGE 63/100", "date": int(T0.timestamp())}
    reply = mra.handle_ack_text(
        "ACK", chat_id=CHAT, from_id=CHAT, allowed_chats=[CHAT], reply_to=card, now=T0, path=store
    )
    assert "the open episode is RED, not ORANGE" in reply and _status(store) == "OPEN"


def test_escalation_acknowledge_expected_tier(tmp_path):
    store = tmp_path / "e.json"
    _seed(store, tier="RED")
    code, body = escalation.acknowledge(None, actor="x", channel="t", now=T0, path=store, expected_tier="ORANGE")
    assert code == 409 and body["episode_tier"] == "RED"
    code, _ = escalation.acknowledge(None, actor="x", channel="t", now=T0, path=store, expected_tier="red")
    assert code == 200


def test_api_ack_binds_to_the_shown_episode_tier(tmp_path):
    from scripts.lib import market_risk_projection as mrp

    store = tmp_path / "e.json"
    _seed(store, tier="RED")
    shown = {"episode": {"id": "ep-test-1", "tier": "ORANGE"}}
    code, body = mrp.ack_outcome(shown, {}, actor="tailnet:op", now=T0, path=store)
    assert code == 409 and _status(store) == "OPEN"
    code, _ = mrp.ack_outcome(
        {"episode": {"id": "ep-test-1", "tier": "RED"}}, {}, actor="tailnet:op", now=T0, path=store
    )
    assert code == 200


def test_poller_routes_ack_before_free_text_and_passes_the_reply():
    src = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")
    assert "elif _is_market_risk_ack(text):" in src
    assert src.index("_is_market_risk_ack(text)") < src.index("_is_digest_hold_text(lower)")
    assert 'reply_to=msg.get("reply_to_message")' in src


# ── stalled-escalation page ───────────────────────────────────────────────────


def _receipt(root: Path, at: datetime):
    p = root / "data/runtime/market_risk/run_last.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "MarketRiskRunReceipt@v1", "finished_at": at.isoformat()}))


def _tick(tmp_path, monkeypatch, now, calls):
    import check_market_risk_escalation as chk
    import telegram_alert

    def fake_send(message, **kw):
        calls.append((now, message, kw))
        return True

    monkeypatch.setattr(telegram_alert, "send_telegram", fake_send)
    return chk.main(
        ["--now", now.isoformat(), "--state-root", str(tmp_path), "--episodes", str(tmp_path / "e.json"), "--json"]
    )


def test_evaluator_alive_means_no_stall(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / "e.json")
    _receipt(tmp_path, T0 - timedelta(minutes=5))
    calls: list = []
    assert _tick(tmp_path, monkeypatch, T0, calls) == 0 and calls == []


def test_missed_run_pages_p1_at_most_3_times_hourly(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / "e.json")
    _receipt(tmp_path, datetime(2026, 10, 29, 10, 0, tzinfo=ET))  # evaluator died after its 10:00 run
    calls: list = []
    t = datetime(2026, 10, 29, 10, 5, tzinfo=ET)
    while t <= datetime(2026, 10, 29, 20, 50, tzinfo=ET):
        _tick(tmp_path, monkeypatch, t, calls)
        t += timedelta(minutes=15)
    assert len(calls) == 3
    first = calls[0]
    assert first[0] == datetime(2026, 10, 29, 10, 50, tzinfo=ET)  # 10:15 slot is 35 min overdue at 10:50
    assert first[2]["priority"] == "P1" and first[2]["message_class"] == "market_risk"
    assert "missed its 10:15 ET run" in first[1] and "page 1 of 3" in first[1]
    assert [c[0] - calls[0][0] for c in calls] == [timedelta(0), timedelta(hours=1), timedelta(hours=2)]


def test_weekend_with_the_evaluator_unscheduled_is_silent(tmp_path, monkeypatch, capsys):
    """The review probe's shape: RED opened Fri 18:00, evaluator ran through Fri 20:00, then is not scheduled until
    Sun 18:30. The old send-age rule paged 46 times; now nothing (and nothing on Sunday when it runs)."""
    _seed(tmp_path / "e.json", anchor=datetime(2026, 10, 30, 18, 0, tzinfo=ET))
    _receipt(tmp_path, datetime(2026, 10, 30, 20, 0, 30, tzinfo=ET))
    calls: list = []
    t = datetime(2026, 10, 30, 20, 5, tzinfo=ET)
    while t < datetime(2026, 11, 1, 18, 30, tzinfo=ET):
        _tick(tmp_path, monkeypatch, t, calls)
        t += timedelta(minutes=15)
    _receipt(tmp_path, datetime(2026, 11, 1, 18, 30, 40, tzinfo=ET))
    while t < datetime(2026, 11, 2, 3, 0, tzinfo=ET):
        _tick(tmp_path, monkeypatch, t, calls)
        t += timedelta(minutes=15)
    assert calls == []


def test_weeknight_after_the_last_slot_is_silent(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / "e.json")
    _receipt(tmp_path, datetime(2026, 10, 29, 20, 0, 20, tzinfo=ET))
    calls: list = []
    t = datetime(2026, 10, 29, 20, 5, tzinfo=ET)
    while t < datetime(2026, 10, 30, 4, 30, tzinfo=ET):
        _tick(tmp_path, monkeypatch, t, calls)
        t += timedelta(minutes=15)
    assert calls == []


def test_outside_the_schedule_a_dead_evaluator_does_not_page(tmp_path, monkeypatch, capsys):
    """The evaluator died mid-afternoon. Inside the schedule that pages (capped); outside it (night, before the
    04:00 window is 35 min old) the step is silent even though the receipt is hours stale."""
    _seed(tmp_path / "e.json")
    _receipt(tmp_path, datetime(2026, 10, 29, 15, 0, tzinfo=ET))
    calls: list = []
    for t in (
        datetime(2026, 10, 29, 23, 0, tzinfo=ET),
        datetime(2026, 10, 30, 2, 0, tzinfo=ET),
        datetime(2026, 10, 30, 4, 20, tzinfo=ET),
    ):
        assert _tick(tmp_path, monkeypatch, t, calls) == 0
    assert calls == []
    assert _tick(tmp_path, monkeypatch, datetime(2026, 10, 30, 4, 35, tzinfo=ET), calls) == 3 and len(calls) == 1


def test_holiday_weekday_is_silent(tmp_path, monkeypatch, capsys):
    _seed(tmp_path / "e.json", anchor=datetime(2026, 11, 25, 18, 0, tzinfo=ET))
    _receipt(tmp_path, datetime(2026, 11, 25, 20, 0, tzinfo=ET))  # Thanksgiving 2026-11-26: gated off
    calls: list = []
    assert _tick(tmp_path, monkeypatch, datetime(2026, 11, 26, 12, 0, tzinfo=ET), calls) == 0 and calls == []


def test_acked_capped_or_orange_is_silent(tmp_path, monkeypatch, capsys):
    calls: list = []
    for kw in ({"status": "ACKED"}, {"status": "CAPPED"}, {"tier": "ORANGE"}, {"repeats": 12}):
        _seed(tmp_path / "e.json", **kw)
        assert _tick(tmp_path, monkeypatch, datetime(2026, 10, 29, 12, 0, tzinfo=ET), calls) == 0
    assert calls == []


def test_dry_run_sends_nothing_and_writes_no_state(tmp_path, monkeypatch, capsys):
    import check_market_risk_escalation as chk

    _seed(tmp_path / "e.json")
    rc = chk.main(
        ["--now", T0.isoformat(), "--state-root", str(tmp_path), "--episodes", str(tmp_path / "e.json"), "--dry-run"]
    )
    assert rc == 3 and "ESCALATION STALLED" in capsys.readouterr().out
    assert not (tmp_path / "data/runtime/market_risk/escalation_stall_state.json").exists()


def test_delivery_failure_is_loud(tmp_path, monkeypatch):
    import check_market_risk_escalation as chk
    import telegram_alert

    _seed(tmp_path / "e.json")
    monkeypatch.setattr(telegram_alert, "send_telegram", lambda *a, **k: False)
    rc = chk.main(["--now", T0.isoformat(), "--state-root", str(tmp_path), "--episodes", str(tmp_path / "e.json")])
    assert rc == 1 and not (tmp_path / "data/runtime/market_risk/escalation_stall_state.json").exists()


def test_health_tick_row_present_and_watchdog_last():
    steps = json.loads((ROOT / "config" / "health_tick_steps.json").read_text(encoding="utf-8"))["steps"]
    ids = [s["step_id"] for s in steps]
    assert "market-risk-escalation-stall" in ids and ids[-1] == "pipeline-watchdog"
    row = next(s for s in steps if s["step_id"] == "market-risk-escalation-stall")
    assert row["command"] == ["$PY", "scripts/check_market_risk_escalation.py"] and row["finding_rc"] == [3]


# ── evaluator run receipt ─────────────────────────────────────────────────────


def test_every_scheduled_run_writes_a_receipt_and_a_replay_does_not(tmp_path, monkeypatch, capsys):
    import market_risk_evaluate as ev
    from scripts.lib.market_risk.fixture_reader import FixtureReader

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("MARKET_RISK_EPISODES_PATH", str(tmp_path / "e.json"))
    monkeypatch.setattr(ev, "production_reader", lambda: FixtureReader())
    rp = tmp_path / "data/runtime/market_risk/run_last.json"
    assert ev.main(["--as-of", "2026-10-28T20:30:00+00:00", "--no-portfolio", "--json"]) == 0
    assert not rp.exists()  # a replay leaves no run receipt
    assert ev.main(["--dry-run", "--no-portfolio", "--json"]) == 0
    rec = json.loads(rp.read_text())
    assert (
        rec["schema"] == "MarketRiskRunReceipt@v1"
        and rec["mode"] == "dry_run"
        and rec["lane_id"] == "market-risk-evaluate"
    )
    assert not (tmp_path / "data/runtime/market_risk/latest.json").exists()  # dry run writes only the receipt


# ── CommsHub colour ───────────────────────────────────────────────────────────


def test_commshub_has_market_risk_colour_from_tokens():
    src = (ROOT / "apps/command-center-v3/src/components/comms/CommsHubParts.tsx").read_text(encoding="utf-8")
    assert "market_risk: TOKENS.danger" in src
