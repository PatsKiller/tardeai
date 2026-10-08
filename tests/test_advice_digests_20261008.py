"""Advice digests (operator 2026-10-08) — non-urgent advice at 10:00 / 15:00 / 17:00 ET as HTML digests.

Decisions: ALL CIO entry alerts + CIO advisory notes + thesis updates + watchlist BUY_READY material changes move to
the digest; scalp alerts, approvals and stop/protection alerts stay immediate; the 17:00 digest adds what moved today
(price incl. material changes, ratings, CIO conviction, new catalysts); old digests fold in.
Holds are switched ON here explicitly (tests/conftest.py defaults them off for producer tests). Fakes only.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import advice_digest as ad  # noqa: E402
import operator_alert_policy_v2 as policy  # noqa: E402

NOW = datetime(2026, 10, 8, 21, 0, tzinfo=timezone.utc)


@pytest.fixture
def holds_on(monkeypatch):
    monkeypatch.setattr(ad, "hold", lambda name: True)
    try:
        import lib.advice_digest as ad2
        monkeypatch.setattr(ad2, "hold", lambda name: True)
    except Exception:
        pass


def _route(text: str):
    ev = policy.classify_legacy_message(text)
    return ev.alert_type, policy.route_event(ev).route_mode


# ── what moves, what stays ──────────────────────────────────────────────────

def test_entry_alerts_and_thesis_updates_go_to_the_digest(holds_on):
    assert _route("🟡 HIGH CONVICTION ENTRY\n$SWMR\nSTATUS BUY READY") == ("cio_entry_state", policy.ROUTE_DIGEST)
    assert _route("🟡 CIO ENTRY ALERT — ALLE · New position\nBUY READY") == ("cio_entry_state", policy.ROUTE_DIGEST)


def test_without_the_hold_entry_alerts_page_as_before(monkeypatch):
    monkeypatch.setattr(ad, "hold", lambda name: False)
    assert _route("🟡 CIO ENTRY ALERT — ALLE · New position\nBUY READY")[1] == policy.ROUTE_IMMEDIATE


@pytest.mark.parametrize("text", [
    "🚨 STOP HEALTH — ORPHANED: *DT* (schwab_rollover_ira)\nstop with no matching holding",
    "🚨 CRITICAL STOP ALERT\n$DT\n🛑 STOP HEALTH — ORPHANED · schwab",
])
def test_stop_and_protection_stay_immediate(holds_on, text):
    assert _route(text)[1] == policy.ROUTE_IMMEDIATE


def test_config_names_every_hold_and_keeps_scalps_and_approvals_out():
    cfg = ad.load_config()
    assert set(cfg["holds"]) == {"cio_entry_state", "cio_entry_bot_copy", "cio_advisory_outbox", "thesis_update",
                                 "material_change_buy_ready"}
    entries = next(s for s in cfg["sections"] if s["id"] == "entries")
    assert "scalp_alert" in entries["exclude_rules"]
    assert set(cfg["slots"]) == {"10", "15", "17"} and cfg["slots"]["17"]["movers"]


def test_material_change_buy_ready_is_digested_but_held_moves_still_page(holds_on, monkeypatch):
    import notify_material_change as mc

    monkeypatch.setattr(mc, "quote_is_fresh", lambda info: True)
    monkeypatch.setattr(mc, "plan_levels", lambda plan, price: {"hit_stop": False, "hit_target": False})
    monkeypatch.setattr(mc, "cio_verdict", lambda info: {"state": "BUY_READY"})
    assert mc.classify({"kind": "price_excursion", "magnitude": 1}, {})["route"] == mc.ROUTE_DIGEST
    monkeypatch.setattr(mc, "plan_levels", lambda plan, price: {"hit_stop": True, "hit_target": False})
    assert mc.classify({"kind": "price_excursion"}, {"holding": {"shares": 1}})["route"] == mc.ROUTE_PAGE


def test_cio_bot_advisory_notes_wait_for_the_digest(holds_on):
    from scripts.lib.cio_notification_delivery import CIONotificationDeliveryWorker

    sent = []

    class Outbox:
        def list_notifications(self, status=None, **k):
            return [{"notification_id": "a", "message_class": "advisory"}, {"notification_id": "c", "message_class": "checkin"}]

        def get_notification(self, nid):
            return {}

        def claim(self, *a):
            return {}

        def confirm(self, *a):
            return {}

    class Adapter:
        is_live = True

        def send(self, n):
            sent.append(n["notification_id"])
            return {"delivered": True, "message_id": "1"}

    w = CIONotificationDeliveryWorker.__new__(CIONotificationDeliveryWorker)
    w.outbox, w.adapter, w.mode = Outbox(), Adapter(), "live"
    w.poll_and_deliver()
    assert sent == ["c"]                      # the advisory note stays PENDING for the digest


def test_entry_runner_holds_the_cio_bot_copy(holds_on, monkeypatch):
    import cio_entry_state_runner as r

    monkeypatch.setattr(r, "cio_card_payload", lambda res, ev: {"text": "x"})
    monkeypatch.setattr(r, "stamp_cio_stance", lambda t, s: t)
    monkeypatch.setattr(r, "operator_send", lambda p, primary_symbols=None: {"operator": True})
    import scripts.lib.cio_telegram_transport as tt
    monkeypatch.setattr(tt, "send_cio_message", lambda *a, **k: pytest.fail("CIO-bot copy must be held"))
    out = r.send_alerts({"symbol": "SWMR", "state": "BUY_READY"}, {})
    assert out["cio_desk"] is False and out["cio_desk_reason"] == "held_for_advice_digest"


# ── collection ──────────────────────────────────────────────────────────────

def test_held_notes_are_windowed_and_one_block_per_ticker(tmp_path):
    since = NOW - timedelta(hours=5)
    log = tmp_path / "outbox.jsonl"
    rows = []
    for nid, hours_ago, body in (("old", 9, "• RE_ENTER_IF AXTI — x"), ("n1", 2, "• RE_ENTER_IF AXTI — y"),
                                 ("n2", 1, "• RE_ENTER_IF TDG — z")):
        rows.append({"event_type": "NOTIFICATION_ENQUEUED", "payload": {
            "notification_id": nid, "message_class": "advisory", "body": body,
            "created_at": (NOW - timedelta(hours=hours_ago)).isoformat()}})
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    class Outbox:
        event_store_path = log

        def get_notification(self, nid):
            return {"current_status": "PENDING"}

    held = ad.collect_held_cio(Outbox(), since)
    assert sorted(h["notification_id"] for h in held) == ["n1", "n2"]          # the 9-hour-old note is outside
    assert {h["symbol"] for h in held} == {"AXTI", "TDG"}


# ── rendering ───────────────────────────────────────────────────────────────

FACTS = {
    "NFLX": {"quote": {"price": 71.12, "chg_pct": 2.0}, "analyst": {"recommendation_key": "buy", "analyst_count": 45,
                                                                     "target_mean": 93.66},
             "cio": {"conviction": 74, "rank": 165, "risk_reward": {"entry_zone": [68.88, 71.0], "invalidation_level": 66.7,
                                                                    "primary_target": 83.6, "rr": 4.1}},
             "news": {"title": "Is Netflix Stock Cheap Enough Yet?", "url": "https://x.example/n", "source": "finviz",
                      "published_at": (NOW - timedelta(hours=6)).isoformat()},
             "catalyst": {"headline": "Analysts offer insights"}, "profile": {"company": "Netflix Inc"}},
    "IPEX": {"quote": {"price": 3.28, "chg_pct": 0.0}},
    "GRML": {"quote": {"price": 5.63, "chg_pct": -2.9}, "analyst": {"recommendation_key": "none", "target_mean": 110},
             "cio": {"risk_reward": {"entry_zone": [3.2, 4.8]}}},
}


def test_item_block_has_everything_the_operator_asked_for():
    block = ad.item_block({"symbol": "NFLX", "event_id": "ev-1", "headline": "CIO ENTRY ALERT", "kind": "Entry setup"}, FACTS, NOW)
    plain = re.sub(r"<[^>]+>", "", block)
    for want in ("$NFLX", "Netflix Inc", "$71.12", "Rating BUY (45)", "Street target $93.66 (+32%)",
                 "Entry $68.88–$71.00", "Stop $66.70", "Target $83.60", "R:R 4.1", "Conviction 74 (#165)",
                 "Analysts offer insights", "Is Netflix Stock Cheap Enough Yet?"):
        assert want in plain, want
    assert "opp=NFLX" in block and "communications?event=ev-1" in block and 'href="https://x.example/n"' in block


def test_thin_items_are_one_line_and_bad_data_is_flagged():
    thin = ad.item_block({"symbol": "IPEX", "headline": "WATCH"}, FACTS, NOW)
    assert "\n" not in thin and "communications?q=IPEX" in thin
    grml = re.sub(r"<[^>]+>", "", ad.item_block({"symbol": "GRML"}, FACTS, NOW))
    assert "NONE" not in grml and "⚠ check" in grml


def test_render_sections_movers_and_safe_splitting(monkeypatch):
    sections = {"entries": [{"symbol": "NFLX", "event_id": "e"}] * 1, "reentry": [], "cio": []}
    movers = {"price": [{"symbol": "NFLX", "chg_pct": 5.2, "price": 71.1, "x_normal": 3.4}],
              "ratings": [{"symbol": "NFLX", "up": True, "from_key": "hold", "to_key": "buy", "key_change": True,
                          "from_target": 80, "to_target": 93.66}],
              "conviction": [{"symbol": "NFLX", "from": 62, "to": 74, "rank_from": 400, "rank_to": 165}],
              "catalysts": [{"symbol": "NFLX", "headline": "New deal"}]}
    msgs = ad.render("17", sections, [], FACTS, movers, {"rows": [(1, None, "stop_warning", "t", "b")]}, NOW)
    text = "\n".join(msgs)
    for want in ("CLOSE DIGEST", "ENTRY SETUPS", "MOVED TODAY", "3.4× its normal daily move", "HOLD → BUY",
                 "62 → <b>74</b>", "New catalysts", "OTHER UPDATES", "arrive immediately"):
        assert want in text, want
    monkeypatch.setitem(ad.load_config(), "max_message_chars", 600)
    many = ad.render("10", {"entries": [{"symbol": "NFLX"}] * 8, "reentry": [], "cio": []}, [], FACTS, None, {}, NOW)
    assert len(many) > 1 and all(m.count("<b>") == m.count("</b>") and m.count("<a ") == m.count("</a>") for m in many)


def test_digest_routes_scalps_out_of_the_entry_section():
    """A scalp alert is category reward but rule scalp_alert — it stays immediate and never enters the digest."""
    calls = []

    def db(sql, params=None, fetch="all"):
        calls.append(params)
        cats = params[2]
        if "reward" in cats:
            return [{"event_id": 1, "created_at": NOW, "category": "reward", "classified_by": "scalp_alert",
                     "symbols": ["ACB"], "sanitized_body": "ACTIVE TRADER · SCALP ALERT", "producer": "x"},
                    {"event_id": 2, "created_at": NOW, "category": "high_conviction_opportunity",
                     "classified_by": "high_conviction", "symbols": ["SWMR"], "sanitized_body": "CIO ENTRY ALERT", "producer": "x"}]
        return []
    out = ad.collect_comms(db, NOW - timedelta(hours=5), NOW)
    assert [i["symbol"] for i in out["entries"]] == ["SWMR"]


def test_wiring_and_schedule():
    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    lanes = {l["lane_id"]: l for l in reg["lanes"]}
    assert lanes["advice-digest"]["scheduler"]["expression"].startswith("0 10,15,17 * * 1-5")
    assert lanes["p1-digest-delivery"]["state"] == "RETIRED" and lanes["material-change-digest"]["state"] == "RETIRED"
    ui = (ROOT / "apps/command-center-v3/src/pages/CommunicationsHub.tsx").read_text()
    assert "sp.get('event')" in ui and "sp.get('q')" in ui
    send = (ROOT / "scripts/send_advice_digest.py").read_text()
    assert "bypass_router=True" in send and "mark_held_delivered" in send
