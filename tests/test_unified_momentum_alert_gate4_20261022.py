"""Gate 4 — one threaded momentum alert per symbol/event/day + Level 2 book signals (operator design 2026-10-22).

Covers:
- l2_book_signals: spread_bps and bid/ask imbalance computed from a book; priors in config equal the defaults;
  missing / one-sided / crossed books fail closed (never a lit signal from absent data).
- unified_momentum_alert: render carries catalyst, grade, verdict + confidence ("—" when absent), float, volume,
  RVOL, sources agreeing, lit L2 signals and the ADVISORY ONLY line; mode resolution (off / shadow / live, unknown
  -> shadow, never live); transition-only dedupe; replay idempotency; live threading: the first DELIVERED message
  is the root and every later state change replies to the root's id in its own chat.
- telegram_alert: reply_to_message_ids reaches the transport on the first chunk only, per chat, and the
  per-chat message ids are readable after the send.
- social_scalp_scanner.send_scalp_alert: flag off = exactly today's send and no ledger; shadow = today's send +
  one logged unified row; live = the unified message instead, legacy only when the unified send is not accepted.
- the Active Trader journal adapter and the shadow replay CLI (dry run writes nothing; re-run adds nothing).

Hermetic: tmp ledgers, injected lookups, fake transports. No live store, network, Telegram or broker.
"""

from __future__ import annotations

import ast
import json
import logging
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import l2_book_signals as L2  # noqa: E402
from lib import unified_momentum_alert as U  # noqa: E402

# Firing test (tests/test_alarm_coverage.py): test_live_alert_fires_through_the_real_gateway_to_the_transport drives
# the real send_telegram -> intent route -> raw transport and captures the message at send_message (never sent).
COVERS = ["scripts/lib/unified_momentum_alert.py"]

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 22, 8, 41, tzinfo=ET).timestamp()


def _ev(state="WATCH", ts=T0, **over):
    base = dict(symbol="BKYI", state=state, ts_epoch=ts, origin="social",
                catalyst_title="BIO-key secures another Middle East government contract", grade="A+",
                verdict="AI: contract (2 src)", confidence=0.65, float_m=1.91, volume=1_250_000, rvol=40.0,
                sources={"scan": True, "social": True, "l2": None},
                source_detail={"scan": "GO 44/55", "social": "3x reddit"},
                l2=L2.compute(2.70, 2.71, 2800, 1000, levels=5))
    base.update(over)
    return U.UnifiedAlertEvent(**base)


# ── L2 book signals ────────────────────────────────────────────────────────────────────────────────────────────

def test_spread_and_imbalance_are_computed_and_lit_against_the_priors():
    r = L2.compute(2.70, 2.71, 2800, 1000, levels=5)
    assert r["status"] == "OK" and r["spread_bps"] == pytest.approx(37.0, abs=0.05)
    assert r["imbalance"] == 2.8
    assert r["signals"]["tight_spread"]["on"] is True
    assert r["signals"]["bid_ask_imbalance"]["on"] is True
    assert r["signals"]["ask_heavy"]["on"] is False
    wide = L2.compute(2.60, 2.71, 500, 1000, levels=5)
    assert wide["signals"]["tight_spread"]["on"] is False and wide["signals"]["ask_heavy"]["on"] is True


@pytest.mark.parametrize("bid,ask", [(None, 2.7), (0, 2.7), (2.8, 2.7)])
def test_missing_one_sided_or_crossed_book_fails_closed(bid, ask):
    r = L2.compute(bid, ask, 100, 100, levels=5)
    assert r["status"] == "NO_BOOK"
    assert all(s["on"] is None for s in r["signals"].values())


def test_snapshot_and_at_l2_adapters():
    snap = {"t": 1.0, "b": [[2.64, 300], [2.62, 500]], "a": [[2.66, 100], [2.69, 100]], "bs": "opend_server"}
    r = L2.from_snapshot(snap)
    assert r["levels"] == 2 and r["imbalance"] == 4.0 and r["source"] == "store:opend_server"
    assert L2.from_snapshot({"b": [], "a": [[1, 1]]})["status"] == "NO_BOOK"
    at = {"ok": True, "best_bid": 2.85, "best_ask": 2.86, "bid_depth": 20165.0, "ask_depth": 54906.0, "levels": 10}
    r2 = L2.from_at_l2(at)
    assert r2["imbalance"] == 0.37 and r2["signals"]["ask_heavy"]["on"] is True
    assert L2.from_at_l2({"ok": False})["status"] == "NO_BOOK"


def test_config_priors_equal_the_shipped_defaults():
    assert L2.load_config() == L2.L2BookSignalConfig()
    assert L2.load_config(Path("/nonexistent.yaml")) == L2.L2BookSignalConfig()


# ── rendering and mode ─────────────────────────────────────────────────────────────────────────────────────────

def test_render_carries_every_field_and_the_advisory_line():
    text = U.render(_ev())
    assert text.splitlines()[0] == "👀 WATCH · BKYI · 08:41 ET"
    for needle in ("BIO-key secures", "Grade A+", "AI: contract (2 src)", "confidence 0.65", "Float 1.91M",
                   "Vol 1.2M", "RVOL 40.0x", "scan ✓ GO 44/55", "social ✓ 3x reddit", "L2 —",
                   "● Spread 37 bps", "● Bid/ask 2.8:1", U.ADVISORY_LINE):
        assert needle in text, needle
    assert text.endswith(U.ADVISORY_LINE)


def test_render_absent_values_are_dashes_never_invented():
    text = U.render(U.UnifiedAlertEvent(symbol="xyz", state="STAND_DOWN", ts_epoch=T0, origin="active_trader"))
    assert "STAND DOWN · XYZ" in text and "Catalyst: —" in text and "confidence —" in text
    assert "Float — · Vol — · RVOL —" in text and "L2: not computed" in text and U.ADVISORY_LINE in text


def test_markdown_metacharacters_are_stripped_from_free_text():
    text = U.render(_ev(catalyst_title="*Big* [news] `x` under_score"))
    assert "Big news x under score" in text


def test_mode_resolution(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("unified_momentum_alert:\n  mode: live\n")
    assert U.resolve_mode(cfg, env={}) == "live"
    assert U.resolve_mode(cfg, env={"UNIFIED_MOMENTUM_ALERT_MODE": "off"}) == "off"
    assert U.resolve_mode(cfg, env={"UNIFIED_MOMENTUM_ALERT_MODE": "LOUD"}) == "shadow"
    assert U.resolve_mode(tmp_path / "missing.yaml", env={}) == "shadow"
    assert U.resolve_mode(env={}) == "shadow", "the committed default is shadow"


# ── emit: off / shadow / dedupe ────────────────────────────────────────────────────────────────────────────────

def _send_must_not_run(*a, **k):
    raise AssertionError("no send outside live mode")


def test_off_builds_nothing_and_writes_nothing(tmp_path):
    led = U.Ledger(tmp_path / "l.jsonl")
    assert U.emit(_ev(), mode="off", ledger=led, send=_send_must_not_run)["action"] == "OFF"
    assert not (tmp_path / "l.jsonl").exists()


def test_shadow_logs_threads_and_dedupes_transitions(tmp_path):
    led = U.Ledger(tmp_path / "l.jsonl")
    a = U.emit(_ev("WATCH", origin_ref="s1"), mode="shadow", ledger=led, send=_send_must_not_run,
               legacy_alert="social_scalp_scanner.send_scalp_alert")
    assert a["action"] == "SHADOW_LOGGED" and a["is_root"] and a["would_reply_to"] is None
    assert a["legacy_alert"] == "social_scalp_scanner.send_scalp_alert"
    same = U.emit(_ev("WATCH", ts=T0 + 60, origin_ref="s2"), mode="shadow", ledger=led, send=_send_must_not_run)
    assert same["action"] == "DEDUPED_SAME_STATE"
    b = U.emit(_ev("ARMED", ts=T0 + 4260, origin_ref="a1"), mode="shadow", ledger=led, send=_send_must_not_run)
    assert b["action"] == "SHADOW_LOGGED" and b["would_reply_to"] == a["row_id"] and b["prev_state"] == "WATCH"
    assert "↳ update to WATCH · BKYI 08:41" in b["text"]
    again = U.emit(_ev("ARMED", ts=T0 + 4260, origin_ref="a1"), mode="shadow", ledger=led)
    assert again["action"] == "DUPLICATE_ORIGIN"
    rows = led.rows()
    assert [r["state"] for r in rows] == ["WATCH", "ARMED"]
    assert all(r["authority"] == {"read_only": True, "order": False, "broker_write": False} for r in rows)


def test_a_new_day_or_symbol_starts_a_new_thread(tmp_path):
    led = U.Ledger(tmp_path / "l.jsonl")
    U.emit(_ev("WATCH"), mode="shadow", ledger=led)
    nxt = U.emit(_ev("WATCH", ts=T0 + 86400), mode="shadow", ledger=led)
    other = U.emit(_ev("WATCH", symbol="ABCD"), mode="shadow", ledger=led)
    assert nxt["is_root"] and other["is_root"]


def test_unknown_state_is_rejected(tmp_path):
    assert U.emit(_ev("MOON"), mode="shadow", ledger=U.Ledger(tmp_path / "l.jsonl"))["action"] == "REJECTED_STATE"


# ── emit: live threading ───────────────────────────────────────────────────────────────────────────────────────

class FakeGateway:
    """Stands in for send_telegram: records priority / reply ids and mints per-chat message ids."""

    def __init__(self, outcomes=None):
        self.calls = []
        self.outcomes = list(outcomes or [])
        self.next_id = 100

    def __call__(self, text, *, priority, dedupe_minutes, reply_to, symbol):
        self.calls.append({"text": text, "priority": priority, "dedupe_minutes": dedupe_minutes,
                           "reply_to": reply_to, "symbol": symbol})
        outcome = self.outcomes.pop(0) if self.outcomes else "deliver"
        if outcome == "fail":
            return {"accepted": False, "message_ids_by_chat": {}}
        if outcome == "held":
            return {"accepted": True, "message_ids_by_chat": {}, "route_decision": "HELD_QUIET_HOURS"}
        self.next_id += 1
        return {"accepted": True, "message_ids_by_chat": {"chatA": str(self.next_id), "chatB": str(self.next_id + 50)},
                "route_decision": "DELIVER"}


def test_live_first_message_is_root_and_state_changes_reply_to_it_per_chat(tmp_path):
    led, gw = U.Ledger(tmp_path / "l.jsonl"), FakeGateway()
    w = U.emit(_ev("WATCH"), mode="live", ledger=led, send=gw)
    assert w["action"] == "SENT" and w["is_root"] and gw.calls[0]["reply_to"] is None
    assert gw.calls[0]["priority"] == "P2" and gw.calls[0]["dedupe_minutes"] == 30
    a = U.emit(_ev("ARMED", ts=T0 + 4260), mode="live", ledger=led, send=gw)
    t = U.emit(_ev("TRIGGERED", ts=T0 + 4620), mode="live", ledger=led, send=gw)
    s = U.emit(_ev("STAND_DOWN", ts=T0 + 6000), mode="live", ledger=led, send=gw)
    root_ids = {"chatA": "101", "chatB": "151"}
    assert [c["reply_to"] for c in gw.calls[1:]] == [root_ids] * 3
    assert [c["priority"] for c in gw.calls] == ["P2", "P1", "P1", "P2"]
    assert a["reply_to"] == t["reply_to"] == s["reply_to"] == root_ids
    assert not a["is_root"] and a["message_ids_by_chat"] == {"chatA": "102", "chatB": "152"}
    assert all(U.ADVISORY_LINE in c["text"] for c in gw.calls)
    dup = U.emit(_ev("STAND_DOWN", ts=T0 + 6100), mode="live", ledger=led, send=gw)
    assert dup["action"] == "DEDUPED_SAME_STATE" and len(gw.calls) == 4


def test_live_held_first_message_is_not_a_root_and_failed_sends_may_retry(tmp_path):
    led, gw = U.Ledger(tmp_path / "l.jsonl"), FakeGateway(["held", "fail", "deliver", "deliver"])
    held = U.emit(_ev("WATCH"), mode="live", ledger=led, send=gw)
    assert held["action"] == "ACCEPTED_NOT_DELIVERED" and not held["is_root"]
    failed = U.emit(_ev("APPROACHING", ts=T0 + 60), mode="live", ledger=led, send=gw)
    assert failed["action"] == "SEND_FAILED"
    retry = U.emit(_ev("APPROACHING", ts=T0 + 70), mode="live", ledger=led, send=gw)
    assert retry["action"] == "SENT" and retry["is_root"] and gw.calls[2]["reply_to"] is None
    nxt = U.emit(_ev("ARMED", ts=T0 + 120), mode="live", ledger=led, send=gw)
    assert gw.calls[3]["reply_to"] == retry["message_ids_by_chat"]
    assert nxt["action"] == "SENT"


def test_live_send_exception_is_recorded_not_raised(tmp_path):
    def boom(*a, **k):
        raise RuntimeError("transport down")

    r = U.emit(_ev("WATCH"), mode="live", ledger=U.Ledger(tmp_path / "l.jsonl"), send=boom)
    assert r["action"] == "SEND_FAILED" and "transport down" in r["error"]


def test_shadow_and_live_threads_are_separate(tmp_path):
    led, gw = U.Ledger(tmp_path / "l.jsonl"), FakeGateway()
    U.emit(_ev("WATCH"), mode="shadow", ledger=led)
    live = U.emit(_ev("WATCH", ts=T0 + 5), mode="live", ledger=led, send=gw)
    assert live["action"] == "SENT" and live["is_root"]


# ── transport threading (telegram_alert) ───────────────────────────────────────────────────────────────────────

def test_raw_send_replies_on_the_first_chunk_only_and_reports_ids_per_chat(monkeypatch):
    import telegram_alert as ta

    sent = []

    def fake_send_message(**kw):
        sent.append(kw)
        return {"ok": True, "message_id": 500 + len(sent)}

    monkeypatch.setattr(ta, "send_message", fake_send_message)
    monkeypatch.setattr(ta, "_token", lambda: "fixture-token")
    monkeypatch.setattr(ta, "_smart_split", lambda m, n: ["part1", "part2"])
    monkeypatch.setitem(sys.modules, "report_capture", types.SimpleNamespace(capture=lambda *a, **k: None))
    res = ta._raw_send_telegram_result("body", ["chatA", "chatB"], reply_to_message_ids={"chatA": "77"})
    assert res["ok"]
    assert [kw.get("reply_to_message_id") for kw in sent] == ["77", None, None, None]
    assert ta.last_message_ids_by_chat() == {"chatA": "501", "chatB": "503"}
    sent.clear()
    ta._raw_send_telegram_result("body", ["chatA"])
    assert all("reply_to_message_id" not in kw for kw in sent), "no reply kwarg when none is asked for"


def test_send_telegram_routes_a_reply_through_the_legacy_intent_branch(monkeypatch):
    import telegram_alert as ta

    seen = {}

    def fake_legacy(message, bypass_router, **kw):
        seen.update(kw, message=message, bypass_router=bypass_router)
        return True

    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(ta, "_legacy_send", fake_legacy)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", lambda *a, **k: None)
    assert ta.send_telegram("x", priority="P1", dedupe_minutes=30, producer=U.PRODUCER,
                            reply_to_message_ids={"chatA": "9"}) is True
    assert seen["reply_to_message_ids"] == {"chatA": "9"} and seen["priority"] == "P1"
    assert seen["producer"] == U.PRODUCER and seen["bypass_router"] is False


def test_live_alert_fires_through_the_real_gateway_to_the_transport(monkeypatch, tmp_path):
    """Inject a state change, capture the message at the transport (captured, never sent): root, then a reply."""
    import telegram_alert as ta

    wire = []

    def fake_send_message(**kw):
        wire.append(kw)
        return {"ok": True, "message_id": 900 + len(wire)}

    class Router:
        receipts = []

        @staticmethod
        def route_intent(message, priority, dedupe_minutes=None, producer=None):
            return {"decision": "DELIVER", "deliver": True, "priority": priority, "producer": producer,
                    "window_minutes": dedupe_minutes}

        @staticmethod
        def mark_intent_sent(route):
            return None

        @classmethod
        def record_intent_receipt(cls, route, **kw):
            cls.receipts.append((route, kw))

    stub = types.SimpleNamespace(enrich=lambda m, **k: m, wrap_send_hook=lambda *a, **k: None,
                                 capture=lambda *a, **k: None)
    for name in ("scripts.lib.opportunity_alert", "lib.opportunity_alert", "lib.advisory.notification_broker",
                 "report_capture"):
        monkeypatch.setitem(sys.modules, name, stub)
    monkeypatch.setattr(ta, "send_message", fake_send_message)
    monkeypatch.setattr(ta, "_enabled", lambda: True)
    monkeypatch.setattr(ta, "_token", lambda: "fixture-token")
    monkeypatch.setattr(ta, "_chat_ids", lambda: ["chatA"])
    monkeypatch.setattr(ta, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(ta, "_intent_router", lambda: Router)
    monkeypatch.setattr(ta, "_best_effort_comms_publish", lambda *a, **k: None)
    led = U.Ledger(tmp_path / "l.jsonl")
    root = U.emit(_ev("WATCH"), mode="live", ledger=led)
    nxt = U.emit(_ev("TRIGGERED", ts=T0 + 4620), mode="live", ledger=led)
    assert root["action"] == nxt["action"] == "SENT"
    assert root["message_ids_by_chat"] == {"chatA": "901"} and nxt["reply_to"] == {"chatA": "901"}
    assert "reply_to_message_id" not in wire[0] and wire[1]["reply_to_message_id"] == "901"
    assert wire[1]["text"].startswith("🟢 TRIGGERED · BKYI") and U.ADVISORY_LINE in wire[1]["text"]
    assert [r[0]["priority"] for r in Router.receipts] == ["P2", "P1"]
    assert all(r[0]["producer"] == U.PRODUCER for r in Router.receipts)


# ── the scanner hook ───────────────────────────────────────────────────────────────────────────────────────────

def _scanner_ns(monkeypatch):
    src = ROOT / "scripts" / "social_scalp_scanner.py"
    tree = ast.parse(src.read_text())
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_send_symbol_alert",
                                                                                  "send_scalp_alert"}]
    ns = {"logger": logging.getLogger("unified-gate4-fixture")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=keep, type_ignores=[])), str(src), "exec"), ns)
    gate = types.ModuleType("lib.cio_telegram_stance_gate")
    gate.check_investment_send = lambda **k: types.SimpleNamespace(allow=True, held_reason=None, cio_action=None)
    gate.apply_stance_rewrite = lambda msg, sym, g: msg
    editor = types.ModuleType("lib.comms_editor")
    editor.default_db_query = None
    editor.set_primary_symbols = lambda s: "tok"
    editor.reset_primary_symbols = lambda t: None
    comms = types.ModuleType("lib.comms")
    comms.CommunicationEvent = lambda **k: k
    comms.publish_communication = lambda e: None
    fmt = types.ModuleType("lib.scalp_alert_format")
    fmt.format_scalp_meta_line = lambda **k: "Social · US"
    for name, mod in {"lib.cio_telegram_stance_gate": gate, "lib.comms_editor": editor, "lib.comms": comms,
                      "lib.scalp_alert_format": fmt}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(U, "catalyst_from_hermes", lambda s, d, lookup=None: {"verdict": "AI: earnings (2 src)",
                                                                            "confidence": 0.7, "title": "Q3 beat"})
    monkeypatch.setattr(U, "latest_at_l2", lambda s, d, path=None: None)
    sent = []
    ns["send_telegram"] = lambda text, **kw: sent.append((text, kw)) or True
    return ns, sent


def _fire(ns):
    ns["send_scalp_alert"]("WFF", 44, "A+", "GO", {"price": 12.0, "rvol": 6.2, "float_m": 4.1, "volume": 900000},
                           3, ["reddit"], 1, 0)


def test_flag_off_is_exactly_todays_alert_and_writes_nothing(monkeypatch, tmp_path):
    ledger = tmp_path / "u.jsonl"
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_LEDGER", str(ledger))
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_MODE", "off")
    ns, sent = _scanner_ns(monkeypatch)
    _fire(ns)
    assert len(sent) == 1
    text, kw = sent[0]
    assert kw == {"priority": "P1", "producer": "social_scalp_scanner"}
    assert text.startswith("\U0001f525 A+ *WFF* — Social Scalp Setup") and U.ADVISORY_LINE not in text
    assert not ledger.exists()


def test_shadow_sends_todays_alert_and_logs_the_unified_one_beside_it(monkeypatch, tmp_path):
    ledger = tmp_path / "u.jsonl"
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_LEDGER", str(ledger))
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_MODE", "shadow")
    ns, sent = _scanner_ns(monkeypatch)
    _fire(ns)
    assert len(sent) == 1 and "Social Scalp Setup" in sent[0][0]
    rows = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["action"] == "SHADOW_LOGGED" and rows[0]["state"] == "WATCH"
    assert rows[0]["legacy_alert"] == "social_scalp_scanner.send_scalp_alert"
    for needle in ("Q3 beat", "Grade A+", "AI: earnings (2 src)", "confidence 0.70", "RVOL 6.2x", "Float 4.10M",
                   "scan ✓ GO 44/55", "social ✓ 3x reddit", "L2 — not armed", U.ADVISORY_LINE):
        assert needle in rows[0]["text"], needle


def test_live_sends_the_unified_alert_instead(monkeypatch, tmp_path):
    ledger = tmp_path / "u.jsonl"
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_LEDGER", str(ledger))
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_MODE", "live")
    ns, sent = _scanner_ns(monkeypatch)
    gw = FakeGateway()
    monkeypatch.setattr(U, "gateway_send", gw)
    _fire(ns)
    assert sent == [], "the legacy scalp alert is not sent when the unified one is"
    assert len(gw.calls) == 1 and gw.calls[0]["text"].startswith("👀 WATCH · WFF")
    _fire(ns)  # the scanner re-fires the same GO 30 minutes later: same state, no second message
    assert len(gw.calls) == 1 and sent == []


def test_live_falls_back_to_todays_alert_when_the_unified_send_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_LEDGER", str(tmp_path / "u.jsonl"))
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_MODE", "live")
    ns, sent = _scanner_ns(monkeypatch)
    monkeypatch.setattr(U, "gateway_send", FakeGateway(["fail"]))
    _fire(ns)
    assert len(sent) == 1 and "Social Scalp Setup" in sent[0][0]


# ── Active Trader journal adapter + shadow replay ──────────────────────────────────────────────────────────────

def _at_row(kind, ts, *, sent=True, sym="GIXI"):
    return {"contract": "active-trader-momentum-alert-v1", "kind": kind, "sent": sent, "ts_epoch": ts,
            "run_id": f"2026-10-22:{int(ts)}", "verdict": "ALERT" if sent else "VETO",
            "candidate": {"symbol": sym, "session_date": "2026-10-22", "float_mm": 3.2, "rvol": 7.5, "last": 4.0,
                          "break_level": 3.98, "entry_ref": 4.07, "stop_ref": 3.96,
                          "trade_ai": {"decision": "GO", "day_catalyst": {"text": "Quantum milestone",
                                                                          "source": "premarket_social"},
                                       "setup_evidence": {"passed_count": 4, "required_count": 5}}},
            "l2": {"ok": True, "best_bid": 3.99, "best_ask": 4.0, "bid_depth": 30000.0, "ask_depth": 10000.0,
                   "levels": 10, "source": "moomoo"},
            "signals": {"supply_thinning": True, "volume_acceleration": False, "status": "OK"},
            "message": {"title": f"ACTIVE TRADER · SCALP ALERT\n{kind} · {sym}"}}


def test_at_row_adapter_maps_the_engine_states_and_fields():
    ev = U.event_from_at_row(_at_row("PREMARKET_WATCH", T0))
    assert ev.state == "WATCH" and ev.symbol == "GIXI" and ev.origin == "active_trader"
    assert ev.sources == {"scan": True, "social": True, "l2": True}
    assert ev.source_detail["scan"] == "GO 4/5" and ev.levels["r"] == pytest.approx(0.11)
    text = U.render(ev)
    assert "● supply thinning" in text and "● Bid/ask 3.0:1" in text and "Quantum milestone" in text
    assert U.event_from_at_row(_at_row("SOMETHING_NEW", T0)) is None


def test_shadow_replay_dry_run_writes_nothing_and_rerun_is_idempotent(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import unified_momentum_alert_shadow as R

    monkeypatch.setattr(U, "catalyst_from_hermes", lambda s, d, lookup=None: {})
    journal = tmp_path / "momentum_alerts.jsonl"
    rows = [_at_row("APPROACHING", T0 + 3600), _at_row("ARMED", T0 + 3700), _at_row("ARMED", T0 + 3710),
            _at_row("TRIGGERED", T0 + 3800, sent=False), _at_row("TRIGGERED", T0 + 3900)]
    journal.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    ledger = tmp_path / "u.jsonl"
    assert R.main(["--day", "2026-10-22", "--journal", str(journal), "--ledger", str(ledger), "--dry-run"]) == 0
    assert not ledger.exists()
    out = R.replay("2026-10-22", journal=journal, ledger=U.Ledger(ledger))
    assert out["replayed"] == 4 and out["actions"] == {"DEDUPED_SAME_STATE": 1, "SHADOW_LOGGED": 3}
    assert out["threads"] == 1
    again = R.replay("2026-10-22", journal=journal, ledger=U.Ledger(ledger))
    assert again["actions"] == {"DUPLICATE_ORIGIN": 3, "DEDUPED_SAME_STATE": 1}
    states = [json.loads(x)["state"] for x in ledger.read_text().splitlines()]
    assert states == ["APPROACHING", "ARMED", "TRIGGERED"]


# ── boundaries ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", ["scripts/lib/unified_momentum_alert.py", "scripts/lib/l2_book_signals.py",
                                 "scripts/unified_momentum_alert_shadow.py"])
def test_no_broker_order_or_execution_reach(rel):
    tree = ast.parse((ROOT / rel).read_text())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    banned = ("active_trader", "brokers", "moomoo", "schwab", "alpaca", "requests", "place_order")
    assert not [m for m in mods if any(b in m for b in banned)], mods


def test_committed_config_ships_shadow():
    import yaml

    doc = yaml.safe_load((ROOT / "config/scalp_signal_engine.yaml").read_text())
    assert doc["unified_momentum_alert"]["mode"] == "shadow"
    assert doc["l2_book_signals"] == {"spread_bps_max": 50.0, "imbalance_min": 1.5, "ask_heavy_max": 0.67,
                                      "levels": 5}


def test_ci_gate_registered():
    from scripts.lib import ci_gates

    doc = json.loads((ROOT / "config/ci_gates/unified_momentum_alert_gate4_20261022.json").read_text())
    assert ci_gates.validate(doc, stem="unified_momentum_alert_gate4_20261022")
    assert doc["files"] == ["tests/test_unified_momentum_alert_gate4_20261022.py"]
    assert doc["anchor"] == "UNIFIED_MOMENTUM_ALERT_GATE4_20261022"
