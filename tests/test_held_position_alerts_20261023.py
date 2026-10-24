"""P1 2026-10-23 (NVDA): a moomoo account-opening reward paged "STOP HIT ... your plan stop".

Replay of the live page (Telegram 13:37 ET, operator_conversation_turns 1337):

    🚨 STOP HIT — NVDA (held, 0.133 sh)
    $211.70 · quote 6m · unusual news volume (5× normal) · stop $213.00
    ▶ Action: review exit — price is through your plan stop

Facts: holdings.json moomoo_taxable_live NVDA 0.133 sh, $28.15, cost_basis null, source
moomoo_live_read; the $213.00 was watchlist_entry_plans id 23236 (LLM entry planner, 2026-10-21), the
stop of a would-be BUY; no broker or operator stop exists for NVDA. Operator: "Momo gave me that for
free for opening my account ... we need to tag what account it came from."

Pinned here:
  * STOP HIT needs a real stop (broker-reported or operator-set); an entry-plan stop never pages a
    held name, and the digest names it "system entry-plan level ... (not a stop you set)";
  * the stop's owner is named: "your stop" only for an operator-set stop;
  * every held notice names each account by name (never digits) with its shares;
  * promo/reward and tiny positions get no stop/exit page unless opted in, and still show;
  * the comms editor tags the account on any held-position notice;
  * the Finviz chart URL changes every minute (Telegram's link-preview cache served a Dec chart);
  * "HIT" in "STOP HIT" is alert chrome, not the ticker HIT.

Hermetic: holdings, policy and stops are fixtures; no DB, network, broker or Telegram.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import notify_material_change as m  # noqa: E402
from scripts.lib import comms_editor as ce  # noqa: E402
from scripts.lib import held_position_alerts as hpa  # noqa: E402
from scripts.lib import telegram_rich as tr  # noqa: E402

NVDA_PROMO = {"symbol": "NVDA", "account": "moomoo_taxable_live", "shares": 0.133, "market_value": 28.15,
              "cost_basis": None, "source": "moomoo_live_read"}
HOLDINGS = {"holdings": [
    NVDA_PROMO,
    {"symbol": "CASH", "account": "moomoo_taxable_live", "shares": 500.0, "market_value": 500.0, "is_cash": True},
    {"symbol": "SPCX", "account": "schwab_taxable", "shares": 200.0, "market_value": 30000.0, "cost_basis": 25000.0},
    {"symbol": "SPCX", "account": "schwab_rollover_ira", "shares": 50.0, "market_value": 7500.0, "cost_basis": 7000.0},
    {"symbol": "JEPI", "account": "schwab_rollover_ira", "shares": 0.394, "market_value": 22.42, "cost_basis": 22.37},
    {"symbol": "628518102", "account": "schwab_rollover_ira", "shares": 125.0, "market_value": 0.0, "cost_basis": None},
]}
ENTRY_PLAN = {"entry": 218.5, "entry_high": 224.5, "stop": 213.0, "target": 265.0, "source": "entry_plan"}
NEWS = {"change_guid": "2a4dad7d-6a3c-5aab-83be-9ba2436a631c", "symbol": "NVDA", "kind": "news_burst",
        "magnitude": 4.97}


@pytest.fixture
def policy_file(tmp_path, monkeypatch):
    def write(**over):
        doc = json.loads((ROOT / "config" / "held_position_alerts.json").read_text(encoding="utf-8"))
        doc.update(over)
        p = tmp_path / "policy.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        monkeypatch.setenv("TRADEAI_HELD_POSITION_ALERTS", str(p))
        return p
    return write


def _info(symbol="NVDA", **over):
    info = {"price": 211.70, "quote_age_h": 0.1, "plan": dict(ENTRY_PLAN),
            "holding": m.holding_for(symbol, HOLDINGS), "entry_state": {"state": "NOT_YET"}}
    info.update(over)
    return info


# ── the incident ────────────────────────────────────────────────────────────


def test_promo_held_name_through_a_watchlist_entry_plan_stop_is_not_stop_hit():
    info = _info()
    r = m.classify(NEWS, info)
    assert r["state"] != "STOP_HIT" and r["route"] == m.ROUTE_DIGEST and r["state"] == "HELD_NEWS"
    assert r["system_level_hit"] and not r["real_stop_hit"]
    assert m.render([NEWS], {NEWS["change_guid"]: info}) == "", "no page at all"


def test_the_digest_names_the_account_the_promo_tag_and_the_system_level():
    info = _info()
    line = m.digest_line(dict(NEWS, guids=[]), info, m.classify(NEWS, info))
    assert "NVDA $211.70 · held · moomoo Taxable 0.133 sh (promo/reward)" in line
    assert "below system entry-plan level $213.00 (not a stop you set)" in line
    assert "your plan stop" not in line and "STOP HIT" not in line


def test_a_normal_held_name_through_an_entry_plan_stop_with_no_real_stop_does_not_page():
    info = _info("SPCX", price=140.0, plan=dict(ENTRY_PLAN, entry=150.0, stop=145.0, target=200.0))
    r = m.classify(NEWS, info)
    assert r["route"] == m.ROUTE_DIGEST and r["state"] == "HELD_NEWS"


def test_an_operator_stop_pages_as_your_stop_with_every_account_named():
    info = _info("SPCX", price=140.0, plan=dict(ENTRY_PLAN, entry=150.0, stop=145.0, target=200.0),
                 real_stop={"price": 142.0, "source": "operator", "broker": "schwab", "account": "schwab_taxable"})
    r = m.classify(NEWS, info)
    assert r["route"] == m.ROUTE_PAGE and r["state"] == "STOP_HIT"
    lines = m.page_lines(NEWS | {"symbol": "SPCX"}, info, r)
    assert lines[0] == "🚨 STOP HIT — SPCX (held · Schwab Individual 200 sh, Schwab Rollover IRA 50 sh)"
    assert "stop $142.00 (your stop)" in lines[1]
    assert lines[-1] == "▶ Action: review exit — price is through your stop"


def test_a_broker_stop_order_is_named_as_the_brokers_not_yours():
    info = _info("SPCX", price=140.0, plan=None,
                 real_stop={"price": 141.0, "source": "broker", "broker": "schwab", "account": "schwab_taxable"})
    r = m.classify(NEWS, info)
    lines = m.page_lines(NEWS | {"symbol": "SPCX"}, info, r)
    assert r["state"] == "STOP_HIT" and "stop $141.00 (Schwab stop order)" in lines[1]
    assert lines[-1] == "▶ Action: review exit — price is through the Schwab stop order"
    assert "your" not in lines[-1]


def test_a_target_hit_names_the_system_plan_not_yours():
    info = _info("SPCX", price=210.0, plan=dict(ENTRY_PLAN, entry=150.0, stop=145.0, target=200.0))
    r = m.classify(NEWS, info)
    lines = m.page_lines(NEWS | {"symbol": "SPCX"}, info, r)
    assert r["state"] == "TARGET_HIT"
    assert "target $200.00 (system entry-plan level)" in lines[1]
    assert "not a target you set" in lines[-1] and "your plan target" not in lines[-1]


def test_a_promo_position_with_a_real_stop_does_not_page_unless_opted_in(policy_file):
    stop = {"price": 212.5, "source": "operator", "broker": "moomoo", "account": "moomoo_taxable_live"}
    policy_file()
    r = m.classify(NEWS, _info(real_stop=stop))
    assert r["route"] == m.ROUTE_DIGEST and r["real_stop_hit"] and r["stop_exit_alerts"] is False
    policy_file(opt_in=["moomoo_taxable_live:NVDA"])
    r = m.classify(NEWS, _info(real_stop=stop))
    assert r["route"] == m.ROUTE_PAGE and r["state"] == "STOP_HIT"


def test_big_moves_on_tiny_positions_do_not_page_by_default(policy_file):
    policy_file()
    move = dict(NEWS, kind="price_excursion", magnitude=9.0, observed_value=-8.0)
    r = m.classify(move, _info("JEPI", price=50.0, plan=None))
    assert r["route"] == m.ROUTE_DIGEST
    policy_file(exclude_tiny_from_stop_exit_alerts=False)
    assert m.classify(move, _info("JEPI", price=50.0, plan=None))["state"] == "BIG_MOVE"


def test_a_watchlist_name_through_its_entry_plan_stop_is_still_plan_invalidated():
    info = _info(holding=None)
    r = m.classify(NEWS, info)
    assert r["route"] == m.ROUTE_DIGEST and r["state"] == "PLAN_INVALIDATED"


def test_no_held_page_says_your_plan_stop_any_more():
    assert not [v for v in m._ACTION.values() if "your" in v], "ownership is decided per page by action_text"
    assert "your plan" not in m.action_text({}, {"state": "STOP_HIT"})
    assert "your plan" not in m.action_text({"plan": ENTRY_PLAN}, {"state": "TARGET_HIT"})


# ── tags and names ──────────────────────────────────────────────────────────


def test_tags_promo_tiny_and_dead_lines():
    pol = hpa.load_policy(ROOT / "config" / "held_position_alerts.json")
    assert hpa.position_tag(NVDA_PROMO, pol) == hpa.TAG_PROMO
    assert hpa.position_tag(HOLDINGS["holdings"][4], pol) == hpa.TAG_TINY  # JEPI $22, has basis
    assert hpa.position_tag(HOLDINGS["holdings"][5], pol) == hpa.TAG_TINY  # $0, no basis: dead line, not promo
    assert hpa.position_tag(HOLDINGS["holdings"][2], pol) is None
    big_no_basis = dict(NVDA_PROMO, symbol="AAPL", market_value=5000.0)
    assert hpa.position_tag(big_no_basis, pol) is None


def test_the_operator_confirmed_reward_is_listed_in_the_policy():
    doc = json.loads((ROOT / "config" / "held_position_alerts.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "HeldPositionAlertPolicy@v1" and doc["de_minimis_usd"] == 100
    assert {"account": "moomoo_taxable_live", "symbol": "NVDA"}.items() <= doc["promo_positions"][0].items()


def test_tiny_and_promo_positions_still_show_with_their_account():
    pos = hpa.positions_for("NVDA", HOLDINGS)
    assert pos[0]["account_label"] == "moomoo Taxable" and pos[0]["tag"] == hpa.TAG_PROMO
    assert hpa.held_text({"positions": pos}) == "held · moomoo Taxable 0.133 sh (promo/reward)"


def test_account_names_never_carry_digits():
    for key in ("schwab_taxable", "moomoo_taxable_live", "12345678", "acct_...258"):
        assert not re.search(r"\d{3,}", hpa.account_label(key))
    row = {"symbol": "X", "account": "98765432", "shares": 1, "market_value": 500.0, "cost_basis": 400.0}
    assert hpa.held_text({"positions": hpa.positions_for("X", {"holdings": [row]})}) == "held · Unlabelled account 1 sh"


def test_the_regression_scan_lists_every_tagged_position():
    rows = hpa.scan(HOLDINGS)
    assert sorted((r["symbol"], r["tag"]) for r in rows) == [
        ("628518102", hpa.TAG_TINY), ("JEPI", hpa.TAG_TINY), ("NVDA", hpa.TAG_PROMO)]


# ── the central account tag (comms editor) ──────────────────────────────────


def _edit(tmp_path, monkeypatch, text, holdings=HOLDINGS):
    monkeypatch.setattr(hpa, "load_holdings", lambda path=None: holdings)
    return ce.edit(text, chat_id="fixture", now=datetime(2026, 10, 23, 17, 37, tzinfo=timezone.utc),
                   ledger=ce.DuplicateLedger(tmp_path / "ledger.json"),
                   resolve=lambda t: [{"symbol": "NVDA", "guid": "245a0597-2bf6-5d3a-a84a-737d39fb1648"}] if "NVDA" in t else [],
                   db_query=lambda *a, **k: [], editor_mode="live")


def test_every_held_position_notice_gets_the_account_tag(tmp_path, monkeypatch):
    out = _edit(tmp_path, monkeypatch, "⚠️ Trim review — NVDA position is up 40% since entry")
    assert "📁 Held in NVDA: moomoo Taxable 0.133 sh (promo/reward)" in out.text
    assert "held_account_tag" in out.changes


def test_no_tag_when_the_notice_already_names_the_account_or_is_not_about_a_position(tmp_path, monkeypatch):
    named = _edit(tmp_path, monkeypatch, "🚨 STOP HIT — NVDA (held · moomoo Taxable 0.133 sh (promo/reward))")
    assert "📁 Held in" not in named.text
    news = _edit(tmp_path, monkeypatch, "NVDA earnings on Nov 19")
    assert "📁 Held in" not in news.text
    unheld = _edit(tmp_path, monkeypatch, "NVDA position idea", holdings={"holdings": []})
    assert "📁 Held in" not in unheld.text


# ── chart and subject chrome ────────────────────────────────────────────────


def test_the_chart_url_is_unique_per_minute_so_telegram_cannot_serve_a_cached_chart():
    a = tr.chart_image_url("NVDA", now=datetime(2026, 10, 23, 17, 37, tzinfo=timezone.utc))
    b = tr.chart_image_url("NVDA", now=datetime(2026, 10, 23, 17, 38, tzinfo=timezone.utc))
    assert a != b and a.endswith("&v=202610231737") and "t=NVDA" in a and "tf=d" in a


def test_hit_in_an_alert_header_is_not_a_ticker():
    from scripts.lib import operator_subject_resolver as osr

    assert "HIT" in osr._STOP
