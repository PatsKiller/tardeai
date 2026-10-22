"""Watch page accuracy (2026-10-22 read-only Watch audit) — nine defects, one test each.

1. plan_ready_strong (and every entry rule) never matches a HELD name — held names belong in the manage lane.
2. A deterministic fail / block / avoid is never counted actionable for a non-held idea.
3. Held comes from ONE reader with an explicit freshness verdict; CUSIP rows resolve through the identity registry
   or are reported unresolved, so the Held count equals the held cards. positions_current is read only behind the
   operator-granted held.positions_store_reader switch, for the surfaces it names (on for "watch" since reader
   batch #1, operator 2026-10-22; AGENTS.md §7A/§17 — tests/test_positions_reader_batch1_20261022.py).
4. A decision packet past its TTL never sets ownership state; current holdings win.
5. "live" excludes expired held names; every count declares its scope (page | matched | live | all).
6. "Highest reward" excludes expired and needs-data cards.
7. The re-entry tile carries the re-entry desk's own READY + NEAR count.
8. POST /api/v2/pullback-macd/dismiss is registered once.
9. "SET CONDITION ALERT" is wired to the existing POST /api/v2/watch/alerts flow.

Fakes only: no database, no network, no broker, no production state.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import watch_decision as wd  # noqa: E402
from lib.data_broker import watch_domains as wdom  # noqa: E402
from lib.rockville import decision_projection as dp  # noqa: E402

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(hours=3)).isoformat()


def card(**k):
    base = {"symbol": "ABC", "last": 10.0, "trade_ai_state": "WAIT", "held": False, "proposal_allowed": False}
    base.update(k)
    return base


def strong_plan(at=FRESH):
    return {"urgency": "ready", "confidence": 0.65, "risk_reward": 5.9, "entry_zone_low": 9.5,
            "entry_zone_high": 10.5, "stop_price": 9.0, "created_at": at}


# ── 1 ── held names never get an entry rule ──────────────────────────────────

def test_held_name_with_strong_ready_plan_is_managed_not_entered():
    """RTX/NVDA/CSWC/LDOS/BAH: High conviction / Review entry while Trade AI said MANAGING."""
    held = wd.decide(card(symbol="RTX", held=True, trade_ai_state="MANAGING"), {"plan": strong_plan()}, now=NOW)
    assert held["rule_id"] != "plan_ready_strong"
    assert held["category"] == "held_position" and held["lane"] == "manage"
    assert not held["actionable"] and held["action_hint"] is None
    idea = wd.decide(card(), {"plan": strong_plan()}, now=NOW)
    assert idea["rule_id"] == "plan_ready_strong" and idea["actionable"] and idea["lane"] == "entry"


def test_every_entry_rule_in_the_standards_excludes_held():
    rules = {r["id"]: r for r in wd.load_config()["rules"]}
    for rid in ("proposal_ready", "plan_ready_strong", "plan_ready", "near_trigger", "plan_near"):
        assert rules[rid]["when"].get("held") is False, rid


# ── 2 ── a deterministic fail is never actionable ───────────────────────────

def test_deterministic_fail_near_reentry_is_not_actionable():
    """FATN/AXTI: actionable / Set a re-entry alert while Trade AI said DETERMINISTIC_FAIL / NO TRADE ACTION."""
    inp = {"reentry": {"state": "NEAR ENTRY", "price_as_of": FRESH, "distance_pct": 1.0}}
    d = wd.decide(card(symbol="FATN", trade_ai_state="DETERMINISTIC_FAIL"), inp, now=NOW)
    assert d["category"] == "re_entry" and d["status"] == "active"
    assert d["actionable"] is False and d["action_hint"] is None
    assert d["actionable_blocked_by"] == "DETERMINISTIC_FAIL"
    ok = wd.decide(card(symbol="OK"), inp, now=NOW)
    assert ok["actionable"] and ok["actionable_blocked_by"] is None
    c = card(symbol="FATN", trade_ai_state="DETERMINISTIC_FAIL")
    c["decision"] = d
    assert wd.board([c], now=NOW)["panels"]["attention"]["count"] == 0


def test_held_blocked_stays_an_actionable_risk_review():
    d = wd.decide(card(held=True, trade_ai_state="BLOCKED"), {"plan": strong_plan()}, now=NOW)
    assert d["rule_id"] == "held_blocked" and d["actionable"]


# ── 3 ── one held reader, freshness, CUSIP resolution ──────────────────────

def _holdings(tmp_path, *, updated_at, rows):
    p = tmp_path / "holdings.json"
    p.write_text(json.dumps({"updated_at": updated_at, "holdings": rows}))
    return p


HOLD_ROWS = [
    {"symbol": "RTX", "shares": 10, "market_value": 1900.0, "account": "schwab_taxable"},
    {"symbol": "12507E201", "shares": 7.0, "market_value": 0.0, "account": "schwab_taxable"},
    {"symbol": "543354104", "shares": 3000.0, "market_value": 0.0, "account": "schwab_rollover_ira"},
    {"symbol": "CASH", "shares": 0, "market_value": 5000.0, "is_cash": True},
    {"symbol": "OLD", "shares": 0, "market_value": 0.0},
]
REGISTRY = {"entities": {
    "g1": {"ticker_alias": "LPIH", "aliases": ["LPIH"], "identifiers": {"cusip": "543354104"}, "active": True},
    "g2": {"ticker_alias": "12507E201", "aliases": ["12507E201"], "identifiers": None, "active": True},
}}


def test_cusip_rows_resolve_or_are_reported_unresolved(tmp_path):
    p = _holdings(tmp_path, updated_at=FRESH, rows=HOLD_ROWS)
    h = wdom.held_positions(holdings_path=p, registry=REGISTRY, now=NOW, cfg={})
    assert h["symbols"] == {"RTX", "LPIH"}                    # no bare CUSIP is ever a held card
    assert h["resolved"] == {"543354104": "LPIH"} and h["unresolved"] == ["12507E201"]
    assert h["source"] == "holdings_accounts.holdings_json" and h["stale"] is False


def test_holdings_freshness_is_explicit(tmp_path):
    old = (NOW - timedelta(hours=30)).isoformat()
    h = wdom.held_positions(holdings_path=_holdings(tmp_path, updated_at=old, rows=HOLD_ROWS), registry={},
                            now=NOW, cfg={"holdings_stale_after_hours": 24})
    assert h["stale"] is True and h["age_s"] == 30 * 3600 and h["stale_after_s"] == 24 * 3600


SAT = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)      # market closed → 72 h contract
ON = {"positions_store_reader": True, "positions_store_reader_surfaces": ["watch"]}


def _store(finished_at):
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append(sql)
        return [{"symbol": "NVDA", "qty": 5, "is_cash": False, "as_of": finished_at, "finished_at": finished_at},
                {"symbol": "CASH", "qty": 100, "is_cash": True, "as_of": finished_at, "finished_at": finished_at}]
    return q, calls


def test_positions_store_reader_wins_when_granted_and_fresh(tmp_path):
    q, calls = _store(SAT - timedelta(hours=19))
    p = _holdings(tmp_path, updated_at=SAT.isoformat(), rows=HOLD_ROWS)
    h = wdom.held_positions(db_query=q, holdings_path=p, registry={}, now=SAT, cfg=ON, surface="watch")
    assert calls and h["source"] == "positions_store.positions_current" and h["symbols"] == {"NVDA"}
    assert h["stale"] is False


def test_stale_positions_store_falls_back_with_a_reason(tmp_path):
    q, _ = _store(SAT - timedelta(hours=100))
    p = _holdings(tmp_path, updated_at=SAT.isoformat(), rows=HOLD_ROWS)
    h = wdom.held_positions(db_query=q, holdings_path=p, registry={}, now=SAT, cfg=ON, surface="watch")
    assert h["source"] == "holdings_accounts.holdings_json" and h["fallback_reason"] == "positions_store_stale"


def test_positions_store_is_not_read_without_the_operator_grant(tmp_path):
    q, calls = _store(SAT)
    p = _holdings(tmp_path, updated_at=SAT.isoformat(), rows=HOLD_ROWS)
    wdom.held_positions(db_query=q, holdings_path=p, registry={}, now=SAT,
                        cfg={"positions_store_reader": False, "positions_store_reader_surfaces": ["watch"]},
                        surface="watch")
    assert calls == []                                        # switch off → never read (§7A/§17)
    wdom.held_positions(db_query=q, holdings_path=p, registry={}, now=SAT, cfg=ON)
    assert calls == []                                        # no surface → never read


def test_every_watch_layer_uses_the_one_held_reader():
    src = (ROOT / "scripts/lib/data_broker/watch_domains.py").read_text()
    fn = src[src.index("def membership_held("):]
    fn = fn[: fn.index("\ndef ", 10)] if "\ndef " in fn[10:] else fn
    assert "held_positions(surface=surface)" in fn and "get_portfolio_snapshot" not in fn
    wi = (ROOT / "scripts/lib/watchlist_intelligence.py").read_text()
    assert "membership_held(WATCH_SURFACE)" in wi[wi.index("def _held_set"):wi.index("def _enrichment_map")]
    lp = (ROOT / "scripts/lib/rockville/live_projection.py").read_text()
    body = lp[lp.index("def build_live_cards"):lp.index("def build_live_symbol")]
    assert "current_held_set()" in body and "holdings.json" not in body
    proj = (ROOT / "scripts/lib/data_broker/watch_intelligence.py").read_text()
    assert '"held_cards"' in proj and '"held_unresolved"' in proj


# ── 4 ── a stale packet never owns ownership state ──────────────────────────

def _packet(valid_until):
    return {"ownership": {"held": True}, "freshness": {"valid_until": valid_until},
            "ticket_review": {"reconciled": {"state": "WAIT"}}, "current_actionable_plan": None,
            "quality_admission": {"state": "PASS"}}


def test_current_holdings_win_over_a_stale_packet():
    """DT: held=false now, MANAGING from a 2026-10-11 packet."""
    old = _packet("2026-10-12T02:16:02+00:00")
    assert dp.packet_expired(old, now=NOW)
    assert dp.classify_primary_state(old, {}, current_held=False, now=NOW) != "MANAGING"
    assert dp.classify_primary_state(old, {}, current_held=None, now=NOW) != "MANAGING"   # past TTL: silent
    assert dp.classify_primary_state(old, {}, current_held=True, now=NOW) == "MANAGING"
    fresh = _packet((NOW + timedelta(hours=2)).isoformat())
    assert dp.classify_primary_state(fresh, {}, current_held=None, now=NOW) == "MANAGING"  # in TTL, unknown holdings
    assert dp.classify_primary_state(fresh, {}, current_held=False, now=NOW) != "MANAGING"
    dec = dp.project_watch_decision(old, {}, symbol="DT", current_held=False, now=NOW)
    assert dec["primary_state"] != "MANAGING" and dec["packet_freshness"]["expired"] is True
    assert dec["packet_freshness"]["ownership_from"] == "current_holdings"


def test_packet_ttl_falls_back_to_generated_at():
    p = {"ownership": {"held": True}}
    assert dp.packet_expired(p, generated_at="2026-10-11 10:16:01-04:00", now=NOW)
    assert not dp.packet_expired(p, generated_at=(NOW - timedelta(hours=1)).isoformat(), now=NOW)


def test_live_projection_passes_current_holdings_into_the_projection():
    lp = (ROOT / "scripts/lib/rockville/live_projection.py").read_text()
    assert "current_held=held" in lp and "packet_expired(" in lp


# ── 5 / 6 / 7 ── live, scopes, reward, re-entry desk ───────────────────────

def _decided(sym, c_kw, inp):
    c = card(symbol=sym, **c_kw)
    c["decision"] = wd.decide(c, inp, now=NOW)
    return c


def _universe():
    syn_old = (NOW - timedelta(days=9)).isoformat()
    return [
        _decided("HC", {}, {"plan": strong_plan()}),                                         # active, reward high
        _decided("ND", {"implied_upside_pct": 40}, {}),                                      # needs_data, reward 1.0
        _decided("HX", {"held": True}, {"synthesis": {"recommendation": "HOLD", "updated_at": syn_old}}),  # held expired
        _decided("EX", {}, {"plan": {**strong_plan(at=syn_old), "urgency": "ready"},
                            "synthesis": {"recommendation": "HOLD", "updated_at": syn_old}}),
        _decided("RE", {}, {"reentry": {"state": "NEAR ENTRY", "price_as_of": FRESH, "distance_pct": 1.0}}),
    ]


def test_expired_held_name_is_listed_but_not_live():
    rows = _universe()
    hx = rows[2]["decision"]
    assert hx["status"] == "expired" and wd.in_view(hx) and not wd.is_live(hx)
    assert wd.passes(hx, {})                                   # still listed in the active views
    b = wd.board(rows, now=NOW)
    assert b["live"] == sum(1 for c in rows if c["decision"]["status"] in ("active", "needs_data"))
    assert b["in_view"] == b["live"] + 1 and b["all"] == len(rows)


def test_every_board_count_declares_its_scope():
    b = wd.board(_universe(), now=NOW)
    assert set(wd.SCOPES) >= {"page", "matched", "live", "all"}
    for k, p in b["panels"].items():
        assert p.get("scope") in wd.SCOPES, k
    assert b["facets_scope"] == "all" and b["count_scopes"]["facets_live"] == "live"
    assert set(b["count_scopes"].values()) <= set(wd.SCOPES)
    src = (ROOT / "scripts/lib/data_broker/watch_intelligence.py").read_text()
    assert '"count_scopes": count_scopes' in src and 'counts["scopes"] = count_scopes' in src
    scopes = re.search(r"count_scopes = \{(.*?)\n    \}", src, re.S).group(1)
    assert set(re.findall(r'"\w+": "(\w+)"', scopes)) <= set(wd.SCOPES)


def test_highest_reward_excludes_expired_and_needs_data():
    rows = _universe()
    assert rows[1]["decision"]["status"] == "needs_data" and rows[1]["decision"]["reward_score"] >= 0.5
    reward = {i["symbol"] for i in wd.board(rows, now=NOW)["panels"]["reward"]["items"]}
    assert "HC" in reward and "ND" not in reward and "EX" not in reward and "HX" not in reward


def test_reentry_tile_carries_the_desk_count():
    desk_rows = {"A": {"state": "READY TO REVIEW"}, "B": {"state": "NEAR ENTRY"}, "C": {"state": "NEAR ENTRY"},
                 "D": {"state": "WAIT"}}
    desk = wd.reentry_desk_counts(desk_rows)
    assert (desk["ready"], desk["near"], desk["rows"]) == (1, 2, 4)
    p = wd.board(_universe(), now=NOW, desk=desk)["panels"]["reentry"]
    assert p["count"] == 1 and p["desk"]["near"] == 2 and "1 READY + 2 NEAR of 4" in p["note"]
    src = (ROOT / "scripts/lib/data_broker/watch_intelligence.py").read_text()
    assert "desk=_wd.reentry_desk_counts()" in src


# ── 8 ── one route registration ─────────────────────────────────────────────

def test_no_route_is_registered_twice_in_api_v2():
    src = (ROOT / "scripts/api_v2.py").read_text()
    lines = re.findall(r'if method == "(?:GET|POST|PUT|DELETE)" and base_path == "[^"]+":', src)
    dups = sorted({x for x in lines if lines.count(x) > 1})
    assert dups == [], dups
    assert lines.count('if method == "POST" and base_path == "/api/v2/pullback-macd/dismiss":') == 1


# ── 9 ── the instruction has a button ───────────────────────────────────────

def test_set_condition_alert_is_wired_to_the_watch_alerts_flow():
    ui = ROOT / "apps/command-center-v3/src"
    modal = (ui / "components/reentry/ReEntryAlertArmModal.tsx").read_text()
    assert "fetch('/api/v2/watch/alerts'" in modal and "noteTag" in modal
    for page in ("pages/WatchIntelligenceUnified.tsx", "pages/SymbolIntelligencePage.tsx"):
        src = (ui / page).read_text()
        assert "ReEntryAlertArmModal" in src and "data-set-condition-alert" in src and "SET CONDITION ALERT" in src, page
    parts = (ui / "components/watch/WatchDecisionParts.tsx").read_text()
    assert "actionable_blocked_by" in parts and "SCOPE_LABEL" in parts and "facets_live" in parts
