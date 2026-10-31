"""Market Risk Engine: phone cards, delivery intents, the Red/Orange escalation ledger, opening shock and the
extended_hours category (DSN-20261031-market-risk-engine P3-T7, P2-T11; plan §4A, §5.8, §5.10, §5.14).

Fixture shapes follow the 2026-10-29 18:15 ET case of the RCA (synthetic numbers, no portfolio data): NQ proxy
-1.6% after hours, INTC -22%, AMZN -6%; a RED card with five contributors that must repeat at +15/+30/+60 and then
hourly until acknowledged. Hermetic: no network, no DB, no Telegram (the send is patched).
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib.market_risk import alerts, escalation as esc, opening_shock as osk  # noqa: E402
from lib.market_risk.categories import extended_hours as xh  # noqa: E402
from lib.market_risk.contract import EvalContext  # noqa: E402
from lib.market_risk.policy import load_policy  # noqa: E402

COVERS = ["scripts/lib/market_risk/alerts.py"]

POLICY = load_policy()
T0 = datetime(2026, 10, 29, 22, 15, tzinfo=timezone.utc)  # 18:15 ET

RED = {
    "as_of": T0.isoformat(),
    "tier": "RED",
    "market_tier": "ORANGE",
    "score": 83,
    "market_score": 76,
    "confirming": 6,
    "uplift": {"vulnerability": 78, "reason": "growth ETF over budget"},
    "contributors": [
        {
            "category": "extended_hours",
            "points": 18,
            "headline": "QQQ -1.6% extended · INTC -22%",
            "as_of": T0.isoformat(),
        },
        {"category": "event", "points": 17, "headline": "25% of index cap reported in 48h", "as_of": T0.isoformat()},
        {
            "category": "options_flow",
            "points": 15,
            "headline": "QQQ P/C vol 3.31 (2.9x median)",
            "as_of": T0.isoformat(),
        },
        {"category": "breadth", "points": 14, "headline": "230 new lows · RSP-SPY WEAKENING", "as_of": T0.isoformat()},
        {"category": "technical", "points": 11, "headline": "SMH -2.4% · SOX -15% MTD", "as_of": T0.isoformat()},
        {"category": "volatility", "points": 3, "headline": "sixth contributor must not print", "as_of": None},
    ],
    "portfolio": {
        "vulnerability": 78,
        "budget_breaches": [{"budget": "growth style", "actual": 85, "limit": 50}],
        "drivers": [{"symbol": "ETF-A", "stop_distance_pct": 4.1, "reason": "top holdings report"}],
    },
    "observations": [{"category": "breadth", "state": "STRESS"}, {"category": "macro_credit", "state": "UNKNOWN"}],
    "deescalates_if": "NQ proxy > -0.75% pre-market and P/C vol < 2.0 at 09:45",
}


# ── render ──────────────────────────────────────────────────────────────────────────────────────


def test_red_card_has_tier_uplift_five_contributors_book_and_advisory():
    card = alerts.render(RED)
    assert "MARKET RISK RED 83/100" in card and "6 of 9 categories confirm" in card
    assert "Market 76 (ORANGE) → RED because portfolio vulnerability 78" in card
    assert card.count("\n") >= 8 and "sixth contributor" not in card
    assert "extended_hours +18" in card and "10-29 18:15 ET" in card
    # budget NAMES only, never the actual/limit numbers (review of #2362, M3)
    assert "Your book: over budget: growth style · ETF-A stop 4.1% below (top holdings report)" in card
    assert "Not measured: macro_credit" in card and "De-escalates if:" in card
    assert "ACK RED" in card and card.rstrip().endswith(alerts.ADVISORY)


def test_card_refuses_behaviour_fields():
    bad = dict(RED, portfolio={"drivers": [{"symbol": "ETF-A", "stop_price": 34.0}]})
    with pytest.raises(ValueError):
        alerts.render(bad)


def test_repeat_card_carries_the_acknowledgment_banner():
    card = alerts.render(RED, repeat={"repeat_number": 3, "elapsed_min": 60})
    assert card.startswith("🔴 RED ALERT ACTIVE — acknowledgment required (repeat 3, 60 min")


# ── intents ─────────────────────────────────────────────────────────────────────────────────────


def test_intents_are_transitions_only():
    assert alerts.intent_for(RED, {"tier": "RED"}, POLICY) is None
    i = alerts.intent_for(RED, {"tier": "ORANGE"}, POLICY)
    assert i["priority"] == "P1" and i["dedupe_minutes"] == 0
    assert i["dedupe_key"] == "market_risk:RED:2026-10-29:up_from_orange"
    down = alerts.intent_for(dict(RED, tier="YELLOW"), {"tier": "ORANGE"}, POLICY)
    assert down["priority"] == "P2" and down["transition"] == "down_from_orange"
    assert alerts.intent_for(dict(RED, tier="BLUE"), {"tier": "YELLOW"}, POLICY) is None
    assert alerts.intent_for(dict(RED, tier="GREEN"), {"tier": "NONE"}, POLICY)["tier"] == "GREEN"
    assert alerts.intent_for(dict(RED, tier="YELLOW"), None, POLICY)["priority"] == "P2"


def _fake_transport(monkeypatch, ok=True):
    calls = []
    mod = types.ModuleType("telegram_alert")

    def send_telegram(message, **kw):
        calls.append((message, kw))
        return ok

    mod.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    return calls


def test_deliver_reaches_the_chokepoint_with_market_risk_class(monkeypatch, tmp_path):
    calls = _fake_transport(monkeypatch)
    intent = alerts.intent_for(RED, {"tier": "ORANGE"}, POLICY)
    out = alerts.deliver(alerts.render(RED), intent, POLICY, dry_run=False, ledger=tmp_path / "keys.json")
    assert out["sent"] is True and len(calls) == 1
    kw = calls[0][1]
    assert kw == {
        "priority": "P1",
        "dedupe_minutes": 0,
        "producer": "market_risk_engine",
        "message_class": "market_risk",
    }


def test_deliver_dry_run_sends_nothing_and_a_refused_send_is_reported(monkeypatch, tmp_path):
    calls = _fake_transport(monkeypatch, ok=False)
    intent = alerts.intent_for(RED, {"tier": "ORANGE"}, POLICY)
    assert alerts.deliver("x", intent, POLICY)["sent"] is False and calls == []
    out = alerts.deliver("x", intent, POLICY, dry_run=False, ledger=tmp_path / "keys.json")
    assert out["sent"] is False and "returned False" in out["error"] and len(calls) == 1


# ── escalation ledger ───────────────────────────────────────────────────────────────────────────


def _red(stress=("breadth",)):
    return {"tier": "RED", "score": 83, "observations": [{"category": c, "state": "STRESS"} for c in stress]}


def _drain(store, start, minutes):
    """Run the evaluator's repeat step every minute for ``minutes``; return the minutes at which a repeat went out."""
    sent = []
    for m in range(minutes + 1):
        now = start + timedelta(minutes=m)
        for r in esc.due_repeats(now=now, policy=POLICY, path=store):
            esc.record_send(r["episode_id"], now=now, kind=r["kind"], ok=True, path=store)
            sent.append(m)
    return sent


def test_red_repeats_at_15_30_60_then_hourly_and_caps_at_12(tmp_path):
    store = tmp_path / "e.json"
    ep = esc.observe(_red(), now=T0, policy=POLICY, path=store)
    assert ep["event"] == "opened" and ep["episode"]["status"] == "OPEN"
    esc.record_send(ep["episode"]["id"], now=T0, kind="initial", ok=True, path=store)
    sent = _drain(store, T0, 14 * 60)
    assert sent[:5] == [15, 30, 60, 120, 180]
    assert len(sent) == 12  # cap


def test_ack_silences_and_upgrade_or_new_stress_reopens(tmp_path):
    store = tmp_path / "e.json"
    orange = {"tier": "ORANGE", "score": 63, "observations": [{"category": "event", "state": "STRESS"}]}
    ep = esc.observe(orange, now=T0, policy=POLICY, path=store)["episode"]
    code, body = esc.acknowledge(ep["id"], actor="tailnet:op", channel="test", now=T0, path=store)
    assert code == 200 and body["episode"]["status"] == "ACKED"
    assert _drain(store, T0, 120) == []
    again = esc.observe(
        dict(orange, observations=orange["observations"] + [{"category": "breadth", "state": "STRESS"}]),
        now=T0 + timedelta(hours=2),
        policy=POLICY,
        path=store,
    )
    assert again["event"] == "reopened" and again["episode"]["status"] == "OPEN"
    esc.acknowledge(None, actor="tailnet:op", channel="test", now=T0 + timedelta(hours=2), path=store)
    up = esc.observe(_red(("event", "breadth")), now=T0 + timedelta(hours=3), policy=POLICY, path=store)
    assert up["event"] == "upgraded" and up["episode"]["tier"] == "RED" and up["episode"]["status"] == "OPEN"


def test_no_two_sends_inside_a_minute(tmp_path):
    store = tmp_path / "e.json"
    ep = esc.observe(_red(), now=T0, policy=POLICY, path=store)["episode"]
    t = T0 + timedelta(minutes=15)
    [r] = esc.due_repeats(now=t, policy=POLICY, path=store)
    esc.record_send(r["episode_id"], now=t, kind=r["kind"], ok=True, path=store)
    # the +30 slot is not due, and even a forced re-check 30 s later yields nothing
    assert esc.due_repeats(now=t + timedelta(seconds=30), policy=POLICY, path=store) == []
    assert ep["id"] == r["episode_id"]


def test_orange_repeats_once_at_60_then_at_session_boundaries(tmp_path):
    store = tmp_path / "e.json"
    t0 = datetime(2026, 10, 28, 20, 30, tzinfo=timezone.utc)  # 16:30 ET
    esc.observe({"tier": "ORANGE", "score": 63, "observations": []}, now=t0, policy=POLICY, path=store)
    sent = _drain(store, t0, 18 * 60)
    # +60 (17:30 ET), then 05:00 ET next day (= +750 min), then 09:45 ET (= +1035 min)
    assert sent[:3] == [60, 750, 1035]


def test_resolves_after_three_sessions_below_yellow(tmp_path):
    store = tmp_path / "e.json"
    esc.observe(_red(), now=T0, policy=POLICY, path=store)
    calm = {"tier": "BLUE", "score": 20, "observations": []}
    # T0 is Thu 10-29 18:15 ET; Fri 10-30 is a session, the weekend is not, Mon 11-02 and Tue 11-03 are (sessions.py)
    days = (1, 1, 2, 3, 4, 5)
    events = [esc.observe(calm, now=T0 + timedelta(days=d), policy=POLICY, path=store)["event"] for d in days]
    assert events == ["unchanged", "unchanged", "unchanged", "unchanged", "unchanged", "resolved"]
    assert esc.open_episode(esc.load(store)) is None


def test_stalled_escalation_is_reported_after_75_minutes(tmp_path):
    store = tmp_path / "e.json"
    ep = esc.observe(_red(), now=T0, policy=POLICY, path=store)["episode"]
    esc.record_send(ep["id"], now=T0, kind="initial", ok=True, path=store)
    assert esc.stalled(now=T0 + timedelta(minutes=74), policy=POLICY, path=store) is None
    f = esc.stalled(now=T0 + timedelta(minutes=76), policy=POLICY, path=store)
    assert f["episode_id"] == ep["id"] and f["minutes_since_last_send"] == 76


def test_ack_needs_a_principal_and_the_open_episode(tmp_path):
    store = tmp_path / "e.json"
    assert esc.acknowledge(None, actor="op", channel="t", now=T0, path=store)[0] == 409
    ep = esc.observe(_red(), now=T0, policy=POLICY, path=store)["episode"]
    assert esc.acknowledge(ep["id"], actor="", channel="t", now=T0, path=store)[0] == 403
    assert esc.acknowledge("mre-other", actor="op", channel="t", now=T0, path=store)[0] == 409


# ── opening shock ───────────────────────────────────────────────────────────────────────────────

CFG = POLICY["opening_shock"]


def test_panic_open_with_internals():
    s = {"symbol": "QQQ", "prior_close": 700, "atr": 10, "open_print": 682, "range": [680, 678], "vix_change_pct": 14}
    r = osk.classify(s, {"advancers_pct": 12, "trin": 2.6}, CFG)
    assert r["class"] == "panic_open" and r["shock"] is True and r["evidence"]["internals"] == "measured"
    calm_internals = osk.classify(s, {"advancers_pct": 45, "trin": 1.1}, CFG)
    assert calm_internals["class"] != "panic_open"
    quiet_vix = osk.classify(dict(s, vix_change_pct=3), {"advancers_pct": 12, "trin": 2.6}, CFG)
    assert quiet_vix["class"] != "panic_open"  # all four panic conditions are required


def test_panic_without_internals_needs_a_deeper_gap():
    s = {"symbol": "QQQ", "prior_close": 700, "atr": 10, "open_print": 682, "range": [681], "vix_change_pct": 14}
    assert osk.classify(s, None, CFG)["class"] != "panic_open"  # -1.8 ATR is not enough blind
    deeper = dict(s, open_print=675, range=[674])
    r = osk.classify(deeper, None, CFG)
    assert r["class"] == "panic_open" and r["evidence"]["internals"] == "UNKNOWN"


def test_gap_fade_gap_and_go_normal_unknown():
    base = {"symbol": "SPY", "prior_close": 600, "atr": 8, "vix_change_pct": 0}
    assert osk.classify(dict(base, open_print=608, range=[611]), None, CFG)["class"] == "gap_and_go"
    assert osk.classify(dict(base, open_print=608, range=[603]), None, CFG)["class"] == "gap_fade"
    assert osk.classify(dict(base, open_print=601, range=[602]), None, CFG)["class"] == "normal"
    assert osk.classify(dict(base, open_print=None), None, CFG)["class"] == "unknown"
    assert (
        osk.classify_all([dict(base, open_print=601), dict(base, open_print=608, range=[611])], None, CFG)["class"]
        == "gap_and_go"
    )


# ── extended_hours category ─────────────────────────────────────────────────────────────────────


class Reader:
    def __init__(self, rows):
        self.rows = rows

    def quotes(self, symbols, *, start, end):
        want = set(symbols)
        return [r for r in self.rows if r["symbol"] in want]


def _q(sym, price, prev, session="afterhours", at=T0):
    return {"symbol": sym, "price": price, "prev_close": prev, "session": session, "as_of": at.isoformat()}


def test_extended_hours_stress_names_heavyweights():
    rows = [
        _q("QQQ", 625.6, 635.8),
        _q("SPY", 676.0, 680.0),
        _q("INTC", 31.2, 40.0),
        _q("AMZN", 230.0, 244.7),
        _q("QQQ", 640.0, 635.8, session="regular"),
    ]
    o = xh.evaluate(EvalContext(now=T0, reader=Reader(rows), policy=POLICY, session="afterhours"))
    assert o.state == "STRESS" and o.score >= 75 and o.headline.startswith("QQQ -1.6% extended")
    assert "INTC -22%" in o.headline and "AMZN" not in o.headline  # -6% is evidence-worthy only at the cut
    labels = [e.label for e in o.evidence]
    assert any(lbl.startswith("INTC") for lbl in labels)


def test_extended_hours_warn_calm_unknown_and_shock():
    warn = xh.evaluate(EvalContext(now=T0, reader=Reader([_q("QQQ", 629.0, 635.8)]), policy=POLICY))
    assert warn.state == "WARN" and 40 <= warn.score < 75
    calm = xh.evaluate(EvalContext(now=T0, reader=Reader([_q("QQQ", 636.0, 635.8)]), policy=POLICY))
    assert calm.state == "CALM"
    none = xh.evaluate(EvalContext(now=T0, reader=Reader([]), policy=POLICY))
    assert none.state == "UNKNOWN" and none.score is None and none.reason_unknown
    shock = xh.evaluate(
        EvalContext(
            now=T0, reader=Reader([]), policy=POLICY, extras={"opening_shock": {"class": "panic_open", "shock": True}}
        )
    )
    assert shock.state == "STRESS" and any(isinstance(e.value, dict) and e.value.get("shock") for e in shock.evidence)
