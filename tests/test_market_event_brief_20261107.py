"""WP4 market-event-brief: slots, idempotence, text rules, dry run writes nothing. Synthetic data only."""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import market_event_brief as meb  # noqa: E402
from lib import critical_texts as ct  # noqa: E402

FIX = json.loads((ROOT / "tests/fixtures/market_event_brief_sample.json").read_text())
POL = meb.load_policy()


def _run(payload, state, send=True, texts=None):
    sent = {"email": [], "tg": [], "txt": []}
    def txt(ev):
        sent["txt"].append(ev); return {"sent": True}
    res = meb.run(payload, slot="2026-11-08T20:00", state=state, policy=POL, send=send,
                  email=lambda s, b: sent["email"].append((s, b)) or True,
                  telegram=lambda t: sent["tg"].append(t) or True, text=txt)
    return res, sent


def test_slots_follow_spec():
    et = lambda y, m, d, h, mi: datetime(y, m, d, h, mi, tzinfo=meb.ZoneInfo("America/New_York")).astimezone(timezone.utc)
    assert meb.slot_for(et(2026, 11, 8, 20, 5), POL) == "2026-11-08T20:00"      # Sunday 20:00
    assert meb.slot_for(et(2026, 11, 9, 10, 20), POL) == "2026-11-09T10:15"     # Monday 10:15
    assert meb.slot_for(et(2026, 11, 9, 11, 30), POL) is None
    assert meb.slot_for(et(2026, 11, 8, 7, 0), POL) is None                     # no Sunday morning slot
    assert meb.slot_for(et(2026, 11, 7, 12, 30), POL) is None                   # Saturday: none


def test_dry_run_sends_nothing_and_writes_no_state():
    state = meb.load_state(Path("/nonexistent/x.json"))
    res, sent = _run(copy.deepcopy(FIX), state, send=False)
    assert not sent["email"] and not sent["tg"] and not sent["txt"]
    assert state["slots"] == {} and state["texts"] == {}
    assert "AAAA" in res["email_body"] and "Advisory only" in res["email_body"]


def test_send_is_idempotent_per_slot_and_text_per_event():
    state = meb.load_state(Path("/nonexistent/x.json"))
    _, sent = _run(copy.deepcopy(FIX), state)
    ids = [e["event_id"] for e in sent["txt"]]
    assert ids == ["market_event:ME-SYNTH-001:open", "market_event:ME-SYNTH-001:AAAA:T1"]   # open + one READY; CCCC is not READY
    assert len(sent["email"]) == 1 and len(sent["tg"]) == 1
    res2, sent2 = _run(copy.deepcopy(FIX), state)
    assert res2["skipped"] == "slot_already_delivered" and not sent2["email"] and not sent2["txt"]


def test_ready_name_text_dedup_across_slots_and_new_tranche_texts_again():
    state = meb.load_state(Path("/nonexistent/x.json"))
    _run(copy.deepcopy(FIX), state)
    later = copy.deepcopy(FIX)
    res = meb.run(later, slot="2026-11-09T07:00", state=state, policy=POL, send=True, email=lambda s, b: True, telegram=lambda t: True,
                  text=lambda ev: {"sent": True})
    assert not any(t["sent"] for t in res["texts"])             # same name+tranche: no second text
    later["candidates"][0]["plan"]["tranche"] = 2
    sent = []
    meb.run(later, slot="2026-11-09T09:00", state=state, policy=POL, send=True, email=lambda s, b: True, telegram=lambda t: True,
            text=lambda ev: sent.append(ev["event_id"]) or {"sent": True})
    assert sent == ["market_event:ME-SYNTH-001:AAAA:T2"]


def test_fell_for_reason_never_texts_ready():
    p = copy.deepcopy(FIX)
    p["candidates"][0]["fell_for_reason"] = True
    ids = [e["event_id"] for e in meb.text_events(p, {"last": {"episode_id": "ME-SYNTH-001"}})]
    assert ids == []


def test_close_text_once_and_no_brief_after():
    state = meb.load_state(Path("/nonexistent/x.json"))
    _run(copy.deepcopy(FIX), state)
    closed = copy.deepcopy(FIX); closed["episode"]["state"] = "CLOSED"
    sent = []
    r = meb.run(closed, slot="2026-11-09T07:00", state=state, policy=POL, send=True, email=lambda s, b: True, telegram=lambda t: True,
                text=lambda ev: sent.append(ev["event_id"]) or {"sent": True})
    assert sent == ["market_event:ME-SYNTH-001:close"]
    r2 = meb.run(closed, slot="2026-11-09T09:00", state=state, policy=POL, send=True, email=lambda s, b: True, telegram=lambda t: True)
    assert r2["skipped"] == "episode_not_active"


def test_texts_are_short_advisory_and_have_no_link():
    for ev in meb.text_events(copy.deepcopy(FIX), {"last": {}}):
        t = ct.format_text(ev)
        assert len(t) <= 160 and t.startswith("MARKET EVENT") and "http" not in t and "ACT NOW" not in t


def test_class_is_enabled_in_allowlist():
    assert ct.class_enabled(ct.load_policy(), "market_event")


def test_failed_channels_leave_the_slot_open():
    state = meb.load_state(Path("/nonexistent/x.json"))
    meb.run(copy.deepcopy(FIX), slot="s1", state=state, policy=POL, send=True, email=lambda s, b: False, telegram=lambda t: False,
            text=lambda ev: {"sent": False, "reason": "x"})
    assert "s1" not in state["slots"]


def test_what_changed_and_no_account_ids():
    prev = meb.snapshot(FIX)
    p = copy.deepcopy(FIX); p["candidates"][1]["state"] = "READY"; p["market_gate"]["tier"] = "ORANGE"
    ch = meb.changes_since(prev, meb.snapshot(p))
    assert "Market tier RED -> ORANGE." in ch and "BBBB STABILIZING -> READY." in ch
    assert meb.next_tranche_by_account(FIX) == {"Acct One": 3000.0, "Acct Two": 1500.0}
