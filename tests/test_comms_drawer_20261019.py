"""Communications drawer (operator 2026-10-19): "show more before we click it open", "broken HTML", "I don't see any
analyst ratings", "it should be larger", "what do the buttons do? I tried clicking them — nothing".

Pins: Street consensus on every ticker item (Yahoo targets store, stale-marked, never invented); the drawer renders
the Telegram HTML through an allowlist (no innerHTML); every lifecycle action carries a plain-English effect; a
missing operator token is asked for in the confirm dialog instead of failing silently (the 10:22 ET click was a 403).
Hermetic: the DB read is injected; UI checks are source-level."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import communications_portal as cp  # noqa: E402

UI = ROOT / "apps/command-center-v3/src"
NOW = datetime.now(timezone.utc)


def _rows(**over):
    base = {
        "NAVN": {"symbol": "NAVN", "target_mean_price": Decimal("30.80"), "target_high_price": Decimal("38"),
                 "target_low_price": Decimal("26"), "recommendation_key": "strong_buy",
                 "number_of_analyst_opinions": 15, "created_at": NOW - timedelta(days=6)},
        "KBR": {"symbol": "KBR", "target_mean_price": Decimal("45.86"), "target_high_price": Decimal("60"),
                "target_low_price": Decimal("36"), "recommendation_key": "buy",
                "number_of_analyst_opinions": 7, "created_at": NOW - timedelta(days=85)},
        "AGM": {"symbol": "AGM", "target_mean_price": Decimal("257"), "target_high_price": None,
                "target_low_price": None, "recommendation_key": "none",
                "number_of_analyst_opinions": 3, "created_at": NOW - timedelta(days=5)},
    }
    base.update(over)
    return base


def _fake_db(rows):
    def q(sql, params=None, fetch="all"):
        wanted = set(params[0])
        return [r for s, r in rows.items() if s in wanted]
    return q


def test_consensus_is_labelled_counted_and_stale_marked():
    out = cp.analyst_consensus(["NAVN", "KBR", "AGM", "NOPE"], db_query=_fake_db(_rows()))
    assert out["NAVN"]["rating"] == "Strong Buy" and out["NAVN"]["analyst_count"] == 15
    assert out["NAVN"]["target_mean"] == 30.8 and out["NAVN"]["target_low"] == 26.0
    assert out["NAVN"]["stale"] is False
    assert out["KBR"]["stale"] is True and out["KBR"]["age_days"] > cp.ANALYST_STALE_DAYS   # old row is not "current"
    assert out["AGM"]["rating"] is None                     # "none" is no consensus, never a made-up rating
    assert "NOPE" not in out                                # no coverage stays absent


def test_consensus_fails_closed_when_the_store_is_unreadable():
    def boom(*a, **k):
        raise RuntimeError("db down")
    assert cp.analyst_consensus(["NAVN"], db_query=boom) == {}
    assert cp.analyst_consensus([], db_query=boom) == {}


def test_feed_items_carry_analyst_and_upside_vs_the_live_quote(monkeypatch):
    from lib.data_broker import market_quote

    monkeypatch.setattr(market_quote, "get_price_batch", lambda q, syms, skip_live=True:
                        {"NAVN": {"price": 25.53, "chg_pct": 0.6, "as_of": "t", "source": "x"}})
    monkeypatch.setattr(cp, "_opportunity_items", lambda: {})
    real = cp.analyst_consensus
    monkeypatch.setattr(cp, "analyst_consensus", lambda syms: real(syms, db_query=_fake_db(_rows())))
    out = cp.attach_market([{"symbols": ["NAVN"]}, {"symbols": ["KBR"]}, {"symbols": ["NOPE"]}, {"symbols": []}])
    assert out[0]["analyst"]["rating"] == "Strong Buy"
    assert out[0]["analyst"]["upside_pct"] == round((30.8 / 25.53 - 1) * 100, 1)
    assert "upside_pct" not in out[1]["analyst"]            # no live quote → no invented upside
    assert "analyst" not in out[2] and "analyst" not in out[3]


def test_deep_linked_event_gets_the_same_enrichment(monkeypatch):
    seen = []
    monkeypatch.setattr(cp, "_db_get_event", lambda eid: {"event_id": eid, "symbols": ["NAVN"]})
    monkeypatch.setattr(cp, "attach_market", lambda evs: seen.extend(evs) or evs)
    r = cp.get_event("abc")
    assert r["ok"] and seen and seen[0]["event_id"] == "abc"


def test_drawer_renders_telegram_html_through_an_allowlist():
    md = (UI / "components/comms/MessageDrawer.tsx").read_text()
    assert "dangerouslySetInnerHTML" not in md and ".innerHTML" not in md
    assert "DOMParser" in md and "safeHref" in md and "u.protocol === 'https:'" in md
    assert "<TelegramHtml body=" in md
    assert "min(920px, 96vw)" in md                          # was a 520px panel
    hub = (UI / "pages/CommunicationsHub.tsx").read_text()
    assert "<MessageDrawer" in hub and "<pre" not in hub.split("<MessageDrawer")[0].split("hubMode && selectedId")[-1]


def test_every_action_says_what_it_does_and_none_touches_trading():
    md = (UI / "components/comms/MessageDrawer.tsx").read_text()
    for label in ("Acknowledge", "Keep 7 more days", "Keep until I release", "Dismiss now"):
        assert f"label: '{label}', help: '" in md
    assert "None of them places, sizes, stops or cancels an order" in md
    # the labels map to the server's real actions (communications_portal.HUB_ACTIONS)
    for a in ("acknowledge", "retain", "expire", "release"):
        assert a in cp.HUB_ACTIONS and f"action: '{a}'" in md


def test_a_missing_operator_token_is_asked_for_not_swallowed():
    m = (UI / "components/AdminConfirmModal.tsx").read_text()
    assert "/access denied/i.test(err)" in m and "setToken(tok.trim())" in m and "Save &amp; retry" in m
    assert "action.explain" in m


def test_feed_card_shows_the_decision_facts_before_opening():
    fc = (UI / "components/decision/FeedCards.tsx").read_text()
    assert "<LevelsLine l={e.levels} />" in fc and "<AnalystLine a={e.analyst} />" in fc
    assert "Stop ${usd(l.invalidation_level)}" in fc and "catalystOf(e.sanitized_body)" in fc
