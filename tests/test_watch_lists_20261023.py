"""Watch IA (operator 2026-10-23): My Watchlist, System Suggests, Full universe on Watch, position facts and filters.

Operator, verbatim: "I don't see stuff that I had starred that I was watching ... where is my traditional watch list,
the stuff that I was watching, and where is the automated watch list, the stuff that the system is proposing for me?";
"NAVN is saying add. When I actually sold that yesterday, it should be tracked that formerly held ... if I made money
with it or not"; "we should be able to filter on this information."

Fakes only: no database, no network, no broker, no production state (AGENTS.md §24.6).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.cio_instrument_record import BEHAVIOR_FIELDS  # noqa: E402
from lib.data_broker import opportunity as op  # noqa: E402
from lib.data_broker import watch_curation as wc  # noqa: E402
from lib.data_broker import watch_domains as wdom  # noqa: E402
from lib.data_broker import watch_position_facts as wpf  # noqa: E402
from lib.data_broker import watch_prospects as wp  # noqa: E402
from lib.data_broker import watch_universe as wu  # noqa: E402

NOW = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(hours=1)).isoformat()
PREV = (NOW - timedelta(minutes=30)).isoformat()
LATER = (NOW + timedelta(hours=40)).isoformat()
PAST = (NOW - timedelta(hours=2)).isoformat()


def card(sym, *, status="active", expires=LATER, held=False):
    return {
        "symbol": sym,
        "company": f"{sym} Inc",
        "last": 10.0,
        "rsi": 50.0,
        "held": held,
        "trade_ai_state": "WAIT",
        "support": 9.0,
        "resistance": 11.0,
        "price_as_of": FRESH,
        "decision": {
            "rule_id": "candidate",
            "status": status,
            "actionable": False,
            "category": "watchlist",
            "priority_score": 50.0,
            "evidence_at": FRESH,
            "expires_at": expires,
            "inputs": {},
        },
    }


def opp(sym, rank, conv, *, stance="WATCH", typ="new_position", status="not_owned", hist=None):
    return {
        "symbol": sym,
        "rank": rank,
        "conviction": conv,
        "stance": stance,
        "type": typ,
        "position_status": status,
        "as_of": FRESH,
        "coverage": 0.9,
        "rankable": True,
        "factors": {"technical": {"score": 80.0, "weight": 0.22, "label": "Technical", "detail": "RSI 55"}},
        "risk_reward": {
            "entry_zone": [9.5, 10.5],
            "rr": 3.0,
            "risk_pct": 4.0,
            "reward_pct": 12.0,
            "current_price": 10.0,
        },
        **({"rank_history": hist} if hist else {}),
    }


def mine(*syms, starred=(), at="2026-07-01T00:00:00+00:00"):
    out = {}
    for s in syms:
        out[s] = {
            "symbol": s,
            "starred": s in starred,
            "starred_at": at if s in starred else None,
            "reasons": [{"kind": "starred" if s in starred else "directive", "label": "x", "at": at, "ref": None}],
        }
    return out


# ── 1. where the operator's names live, and why they were missing ─────────────


def test_membership_operator_reads_all_four_sources_with_reasons():
    rows = {
        "operator_starred_symbols": [{"s": "ANET", "at": "2026-07-02", "ref": None, "label": None}],
        "personal_watchlist": [
            {"s": "PLTR", "at": "2026-06-01", "ref": None, "label": None},
            {"s": "ANET", "at": "2026-06-01", "ref": None, "label": None},
        ],
        "watch_directives": [{"s": "IBM", "at": "2026-06-23", "ref": 211, "label": "White House Quantum Computing"}],
        "origin_system = 'operator'": [
            {"s": "NOC", "at": "2026-08-01", "ref": None, "label": "paper_proposal"},
            {"s": "543354104", "at": None, "ref": None, "label": "portfolio"},
        ],
    }

    def q(sql, params=None):
        for k, v in rows.items():
            if k in sql and (k != "personal_watchlist" or "source = 'personal_watchlist'" in sql):
                return v
        return []

    out = wdom.membership_operator(db_query=q)
    names = out["names"]
    assert set(names) == {"ANET", "PLTR", "IBM", "NOC"}, "CUSIPs are not names"
    assert names["ANET"]["starred"] and {r["kind"] for r in names["ANET"]["reasons"]} == {
        "starred",
        "personal_watchlist",
    }
    assert "White House Quantum Computing" in names["IBM"]["reasons"][0]["label"]
    assert all(v["status"] == "ok" for v in out["sources"].values())


def test_one_failing_source_is_reported_not_silently_empty():
    def q(sql, params=None):
        if "watch_directives" in sql:
            raise RuntimeError("boom")
        return [{"s": "ANET", "at": None, "ref": None, "label": None}] if "operator_starred" in sql else []

    out = wdom.membership_operator(db_query=q)
    assert out["sources"]["directive"]["status"] == "error" and "ANET" in out["names"]


def test_universe_no_longer_takes_the_first_120_names_alphabetically():
    src = (ROOT / "scripts/lib/data_broker/watch_intelligence.py").read_text()
    body = src.split("def _universe_symbols(")[1].split("\ndef ")[0]
    assert "_operator_names()" in body, "the operator's names are always in the Watch universe"
    assert "ORDER BY is_active DESC, updated_at DESC" in body


# ── 2. Prospects: every operator name, never capped, never expired ────────────


def test_operator_names_are_never_capped_or_expired_on_prospects():
    cards = [card(f"S{i:02d}") for i in range(10)] + [card("MINE1"), card("OLD", status="expired")]
    opps = {f"S{i:02d}": opp(f"S{i:02d}", i + 1, 90 - i) for i in range(10)}
    opps["MINE1"] = opp("MINE1", 50, 10.0)
    p = wp.build_watch_prospects(
        cards=cards,
        opportunities=opps,
        reentry={},
        held=set(),
        held_source="positions_store.positions_current",
        now=NOW,
        caps={"forming": 3},
        operator=mine("MINE1", "OLD", "NOCARD"),
    )
    forming = next(lane for lane in p["lanes"] if lane["id"] == "forming")
    shown = [r["symbol"] for r in forming["items"]]
    assert "MINE1" in shown, "lowest conviction, but yours: never pushed to overflow"
    assert "OLD" in shown and "NOCARD" in shown
    assert len([s for s in shown if s.startswith("S")]) == 3 and len(forming["overflow"]) == 7
    old = next(r for r in forming["items"] if r["symbol"] == "OLD")
    assert old["expiry_suggestion"] and old["mine"] is True
    nocard = next(r for r in forming["items"] if r["symbol"] == "NOCARD")
    assert any("No Watch card yet" in m for m in nocard["whats_missing"])
    assert p["counts"]["mine"] == 3


# ── 3. one ranking: Suggests = top of the Full universe list, minus held / yours / dismissed ──


def test_suggests_is_the_top_of_the_same_ranking_with_each_skip_named():
    opps = {s: opp(s, i + 1, 90 - i) for i, s in enumerate(["AAA", "HLD", "MIN", "DIS", "BBB", "CCC"])}
    out = wc.suggest(opps, n=2, held={"HLD"}, mine=mine("MIN"), dismissed={"DIS": {"at": PAST}})
    assert [m["symbol"] for m in out["members"]] == ["AAA", "BBB"]
    assert [m["universe_rank"] for m in out["members"]] == [1, 5]
    assert {k: [x["symbol"] for x in v] for k, v in out["skipped"].items()} == {
        "held": ["HLD"],
        "mine": ["MIN"],
        "dismissed": ["DIS"],
    }
    assert out["rotation"]["available"] is False and out["rotation"]["unavailable_reason"]


def test_n_defaults_to_20_and_never_exceeds_30():
    assert wc.clamp_n(None) == 20 and wc.clamp_n("99") == 30 and wc.clamp_n(0) == 1


def test_rotation_hysteresis_keeps_a_member_inside_the_exit_band():
    # n=4 → exit band 6, displace margin 2. D was a member (prev #4), now #6: kept as "holding".
    rot = wc.rotate(["A", "B", "C", "E", "F", "D", "G"], ["A", "B", "C", "D"], 4)
    assert rot["members"] == ["A", "B", "C", "D"]
    # Now D drops to #8 (outside the band of 6): E enters.
    rot = wc.rotate(["A", "B", "C", "E", "F", "G", "H", "D"], ["A", "B", "C", "D"], 4)
    assert rot["members"] == ["A", "B", "C", "E"]
    assert len(wc.rotate([str(i) for i in range(50)], None, 30)["members"]) == 30


def test_entered_and_left_carry_reasons_from_rank_history():
    opps = {
        "AAA": opp("AAA", 1, 90, hist=[[PREV, 1, 89], [FRESH, 1, 90]]),
        "NEW": opp("NEW", 2, 88, hist=[[PREV, 40, 70], [FRESH, 2, 88]]),
        "OUT": opp("OUT", 30, 60, hist=[[PREV, 2, 85], [FRESH, 30, 60]]),
        "ADD": opp("ADD", 3, 87, hist=[[PREV, 3, 87], [FRESH, 3, 87]]),
        **{
            f"F{i}": opp(f"F{i}", 3 + i, 86 - i, hist=[[PREV, 10 + i, 80], [FRESH, 3 + i, 86 - i]]) for i in range(1, 4)
        },
    }
    # ADD was added to the operator's list after the previous run → "left: added to your watchlist".
    m = {"ADD": {"symbol": "ADD", "starred": False, "reasons": [{"kind": "directive", "at": FRESH}]}}
    out = wc.suggest(opps, n=2, held=set(), mine=m, dismissed={})
    assert out["rotation"]["available"] is True
    st = {x["symbol"]: x for x in out["members"]}
    assert set(st) == {"AAA", "NEW"} and st["NEW"]["status"] == "entered" and "was #40" in st["NEW"]["reason"]
    left = {x["symbol"]: x["reason"] for x in out["left"]}
    assert left["OUT"].startswith("left: fell to #30") and "85 → 60" in left["OUT"]


def test_curation_rows_are_the_prospect_rows_so_conviction_and_stage_match():
    cards = [card("AAA"), card("MIN")]
    opps = {"AAA": opp("AAA", 1, 80.0), "MIN": opp("MIN", 2, 70.0), "ZZZ": opp("ZZZ", 3, 60.0)}
    operator = mine("MIN", starred=("MIN",))
    p = wp.build_watch_prospects(
        cards=cards,
        opportunities=opps,
        reentry={},
        held=set(),
        held_source="positions_store.positions_current",
        now=NOW,
        operator=operator,
    )
    rows = {r["symbol"]: r for lane in p["lanes"] for r in lane["items"]}

    def row_for(s):
        return rows.get(s) or wp.build_row(
            s,
            card=None,
            opp=opps.get(s),
            held=False,
            held_source="x",
            reentry=None,
            identity=None,
            now=NOW,
            mine=operator.get(s),
        )

    g = {
        "operator": operator,
        "opps": opps,
        "held": set(),
        "row_for": row_for,
        "payload": p,
        "now": NOW,
        "proj_meta": {"as_of": FRESH},
        "held_source": "positions_store.positions_current",
        "held_detail": {"stale": False},
    }
    c = wc.build_curation(g, n=5)
    my = c["my_watchlist"]["rows"]
    assert [r["symbol"] for r in my] == ["MIN"] and my[0]["starred"]
    assert my[0]["conviction"] == rows["MIN"]["conviction"] and my[0]["lane"] == rows["MIN"]["lane"]
    sug = {r["symbol"]: r for r in c["suggests"]["rows"]}
    assert set(sug) == {"AAA", "ZZZ"} and sug["AAA"]["conviction"] == rows["AAA"]["conviction"]
    assert c["suggests"]["actions"]["add"]["path"] == "/api/v2/watch/directives"
    assert [h["id"] for h in c["how"]] == ["my_watchlist", "suggests", "prospects", "full_universe", "proposals"]
    _no_behavior(c)


# ── 4. NAVN: held status from the broker-synced reader, formerly held, round trip, re-entry ──


NAVN_LIFE = {
    "status": "closed",
    "round_trip_key": "srt:607228",
    "entry_fill": {"at": "2026-10-19T15:01:04+00:00", "price": 25.64},
    "exit_fill": {"at": "2026-10-22T19:59:21+00:00", "price": 26.02},
    "exit_cause": {
        "class": "trailing_ratchet",
        "evidence": "exit 26.02 = observed stop 26.02 (FILLED)",
        "in_profit": True,
    },
    "pnl": {"net_pnl_usd": 189.73, "pnl_pct": 1.48, "r_multiple": None, "r_on_initial_observed_stop": 0.36},
    "observed_stops": {"ratchets_up": 5, "initial": 24.59, "last": 26.02},
    "hold_days": 3,
}
NAVN_ADVICE = {
    "state": "WAIT",
    "distance_pct": 3.67,
    "levels": {"entry_zone": [24.8, 25.1], "reclaim": 26.02},
    "alert_levels": [
        {"reference": "near_entry", "level": 25.853, "means": "near"},
        {"reference": "in_zone", "level": 25.1, "means": "zone top"},
        {"reference": "reclaim", "level": 26.02, "means": "close above exit"},
    ],
    "conditions": [{"id": "thesis_valid", "text": "thesis", "met": None}],
}


def navn_facts(**kw):
    return wpf.facts_for(
        "NAVN",
        held=kw.get("held", set()),
        last_sell={"NAVN": "2026-10-22T19:59:21+00:00"},
        lifecycle={
            "NAVN": {"life": NAVN_LIFE, "review": {"noise_vs_trend": {"verdict": "noise"}}, "advice": NAVN_ADVICE}
        },
        now=NOW,
    )


def test_navn_is_formerly_held_with_its_round_trip_and_reentry_levels():
    f = navn_facts()
    assert f["position_state"] == "formerly_held" and f["last_sell_at"].startswith("2026-10-22")
    rt = f["last_round_trip"]
    assert (rt["entry_price"], rt["exit_price"], rt["pnl_usd"], rt["pnl_pct"], rt["result"]) == (
        25.64,
        26.02,
        189.73,
        1.48,
        "won",
    )
    assert (rt["exit_cause"], rt["r"], rt["r_basis"], rt["noise_vs_trend"]) == (
        "trailing",
        0.36,
        "initial observed stop",
        "noise",
    )
    a = f["reentry"]
    assert a["readiness"] == "waiting" and a["entry_zone"] == [24.8, 25.1] and a["reclaim"] == 26.02
    assert [x["level"] for x in a["alert_levels"]] == [25.853, 25.1, 26.02]
    assert navn_facts(held={"NAVN"})["position_state"] == "held"


def test_universe_overlay_never_shows_a_sold_name_as_add_on():
    a = opp("NAVN", 8, 83.7, stance="ADD", typ="add_on", status="owned")
    row = wu.overlay(a, navn_facts())
    assert (row["type"], row["position_status"], row["stance"]) == ("re_entry", "formerly_held", "WATCH")
    assert (row["curator_type"], row["curator_stance"]) == ("add_on", "ADD") and "Sold 2026-10-22" in row[
        "ownership_note"
    ]


def test_curator_held_basis_follows_the_broker_synced_reader_only_when_approved_and_fresh():
    fresh = {
        "source": "positions_store.positions_current",
        "stale": False,
        "symbols": {"RTX"},
        "as_of": FRESH,
        "positions_store_reader": True,
    }
    b = op.held_basis(fresh)
    pc = op.apply_held_basis({"owned": True, "shares": 500}, "NAVN", b)
    assert pc["owned"] is False and pc["owned_per_holdings_file"] is True
    off = op.held_basis(
        {
            "source": "holdings_accounts.holdings_json",
            "stale": False,
            "symbols": {"NAVN"},
            "positions_store_reader": False,
        }
    )
    assert off["symbols"] is None and off["reason"].startswith("reader_batch_4_not_approved")
    pc = op.apply_held_basis({"owned": True}, "NAVN", off)
    assert pc["owned"] is True and pc["held_basis"]["reason"].startswith("reader_batch_4")
    stale = op.held_basis({**fresh, "stale": True, "fallback_reason": "positions_store_stale"})
    assert stale["symbols"] is None and stale["reason"] == "positions_store_stale"


def test_opportunity_surface_is_approved_reader_batch_4():
    import json

    import yaml

    cfg = yaml.safe_load((ROOT / "config/watch_decision_standards.yaml").read_text())["held"]
    assert wdom.OPPORTUNITY_SURFACE in cfg["positions_store_reader_surfaces"]
    reg = json.loads((ROOT / "config/data_source_authority.json").read_text())
    ps = next(d for d in reg["domains"] if d["domain"] == "positions_store")
    b4 = next(e for e in ps["approved_readers"] if e["batch"] == 4)
    assert b4["surfaces"] == ["opportunity"] and b4["approval"]["approved_by"] == "operator"
    assert "Yes, I approve" in b4["approval"]["reference"] and b4["approval"]["approved_on"] == "2026-10-23"
    assert "proposed_readers" not in ps


def test_rank_history_is_carried_by_the_projection_writer(tmp_path):
    from lib.cio_opportunity_store import CIOOpportunityStore

    st = CIOOpportunityStore(event_path=tmp_path / "e.jsonl", projection_path=tmp_path / "p.json")
    for i, at in enumerate(["t1", "t2", "t3"]):
        st.write_projection([{"symbol": "AAA", "rank": i + 1, "conviction": 80.0 + i}], {"as_of": at})
    h = st.read_projection()["items"]["AAA"]["rank_history"]
    assert h == [["t1", 1, 80.0], ["t2", 2, 81.0], ["t3", 3, 82.0]]
    assert wc.prev_point(st.read_projection()["items"]["AAA"]) == (2, 81.0, "t2")


# ── filters ──────────────────────────────────────────────────────────────────


def test_position_filters_and_facets():
    f = navn_facts()
    never = {"position_state": "never_held", "last_round_trip": None, "reentry": None, "last_sell_at": None}
    ok = lambda q: wpf.passes(f, q, now=NOW)  # noqa: E731
    assert ok({"position": "formerly_held"}) and not ok({"position": "held,never_held"})
    assert ok({"result": "won"}) and not ok({"result": "lost"})
    assert ok({"pnl_usd_min": "100", "pnl_usd_max": "200"}) and not ok({"pnl_pct_min": "2"})
    assert ok({"exit_cause": "trailing"}) and not ok({"exit_cause": "stop,target"})
    assert ok({"exited_within": "1d"}) and not ok({"exited_within": "older"})
    assert ok({"reentry": "waiting"}) and not ok({"reentry": "ready"})
    assert ok({"reentry_dist_max": "4"}) and not ok({"reentry_dist_max": "3"})
    assert ok({"r_min": "0.3"}) and not ok({"r_min": "0.5"})
    assert not wpf.passes(never, {"result": "won"}, now=NOW)
    fc = wpf.facet_counts([f, never], now=NOW)
    assert fc["position"] == {"formerly_held": 1, "never_held": 1} and fc["exited_within"]["1d"] == 1
    assert set(wpf.FILTERS) >= {
        "position",
        "result",
        "pnl_usd_min",
        "exit_cause",
        "exited_within",
        "reentry",
        "reentry_dist_min",
        "r_min",
    }
    assert all(spec["server"] for spec in wpf.FILTERS.values()), "every tooltip states the server rule"


def test_universe_filters_sorts_and_reentry_preset(monkeypatch):
    monkeypatch.setattr(op, "load_config", lambda: {"presets": {}})
    items = {
        "NAVN": opp("NAVN", 8, 83.7, stance="ADD", typ="add_on", status="owned"),
        "BRCC": opp("BRCC", 1, 88.0),
        "RTX": opp("RTX", 2, 87.0, typ="existing", status="owned"),
    }
    facts = {"NAVN": navn_facts(), "BRCC": {"position_state": "never_held"}, "RTX": {"position_state": "held"}}
    u = wu.build_universe(items, facts_for=lambda s: facts[s], q={"position": "formerly_held"}, now=NOW)
    assert [i["symbol"] for i in u["items"]] == ["NAVN"] and u["position_facets"]["position"]["held"] == 1
    r = wu.build_universe(items, facts_for=lambda s: facts[s], q={"preset": "reentry"}, now=NOW)
    assert [i["symbol"] for i in r["items"]][0] == "NAVN" and r["sort"] == "formerly_held_first"
    s = wu.build_universe(items, facts_for=lambda s: facts[s], q={"sort": "conviction"}, now=NOW)
    assert [i["symbol"] for i in s["items"]] == ["BRCC", "RTX", "NAVN"]
    assert all("rank_history" not in i for i in s["items"])
    _no_behavior(s)


def test_prospects_filter_payload_recounts_lanes():
    cards = [card("AAA"), card("BBB")]
    p = wp.build_watch_prospects(cards=cards, opportunities={}, reentry={}, held=set(), held_source="x", now=NOW)
    for lane in p["lanes"]:
        for r in lane["items"]:
            r.update(navn_facts() if r["symbol"] == "AAA" else {"position_state": "never_held"})
    out = wp.filter_payload(p, {"position": "formerly_held"})
    assert out["counts"]["total"] == 1 and out["filters"] == {"position": "formerly_held"}
    assert wp.filter_payload(p, {})["lanes"] == p["lanes"]


# ── writes ───────────────────────────────────────────────────────────────────


def test_dismiss_is_an_audited_watchlist_event_with_the_principal(monkeypatch):
    import api_v3_watch_commands as cmd

    seen = []
    monkeypatch.setattr(cmd, "_principal", lambda: "tailnet:john@example")
    out = cmd.post_suggest_decision(
        "dismiss",
        {"symbol": "brcc", "reason": "not my style", "universe_rank": 1, "by": "spoofed"},
        db_execute=lambda sql, p: seen.append((sql, p)),
    )
    assert out["ok"] and out["event_type"] == "watch_suggest_dismissed" and out["by"] == "tailnet:john@example"
    assert out["broker_write"] is False
    sql, params = seen[0]
    assert (
        sql.startswith("INSERT INTO watchlist_events")
        and params[0] == "watch_suggest_dismissed"
        and params[1] == "BRCC"
    )
    assert '"by": "tailnet:john@example"' in params[3] and "spoofed" not in params[3]
    assert cmd.post_suggest_decision("dismiss", {"symbol": ""}, db_execute=lambda *a: None)["ok"] is False
    assert cmd.post_suggest_decision("nuke", {"symbol": "X"}, db_execute=lambda *a: None)["ok"] is False


def test_read_dismissed_latest_event_wins():
    rows = [
        {
            "s": "BRCC",
            "event_type": wc.EVENT_DISMISSED,
            "created_at": NOW - timedelta(days=1),
            "payload": {"by": "tailnet:x", "reason": "no"},
        },
        {"s": "XRPN", "event_type": wc.EVENT_RESTORED, "created_at": NOW, "payload": {}},
    ]
    d, status = wc.read_dismissed(lambda sql, params=None: rows, now=NOW)
    assert status == "ok" and list(d) == ["BRCC"] and d["BRCC"]["reason"] == "no"


def test_routes_and_catalog():
    src = (ROOT / "scripts/api_v2.py").read_text()
    assert src.count('if p == "watch-curation":') == 1 and src.count('if p == "watch-universe":') == 1
    assert 'cmd in ("suggest-dismiss", "suggest-restore")' in src
    from lib.data_broker.catalog import PROJECTIONS

    ids = {x["id"] for x in PROJECTIONS}
    assert {"watch_curation", "watch_universe"} <= ids


def test_ownership_conflicts_only_against_a_fresh_broker_synced_answer():
    opps = {"NAVN": opp("NAVN", 8, 83.7, stance="ADD", typ="add_on", status="owned")}
    c = wc.ownership_conflicts(
        opps, held=set(), held_source="positions_store.positions_current", held_detail={"stale": False, "as_of": FRESH}
    )
    assert c and c[0]["a"]["value"] == "owned" and c[0]["b"]["value"] == "not held"
    assert wc.ownership_conflicts(opps, held=set(), held_source="holdings_accounts.holdings_json", held_detail={}) == []


def _no_behavior(obj, path=""):
    blocked = {str(x).lower() for x in BEHAVIOR_FIELDS}
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert str(k).lower() not in blocked, f"behaviour key {k} at {path}"
            _no_behavior(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_behavior(v, f"{path}[{i}]")


# ── choose what to watch: add / remove / search (operator 2026-10-23) ─────────


def test_mine_add_and_remove_are_logged_with_the_principal_and_never_trade(monkeypatch):
    import api_v3_watch_commands as cmd

    monkeypatch.setattr(cmd, "_principal", lambda: "tailnet:john@example")
    ex, archived = [], []
    import lib.writers.watch_directives_writer as wdw

    monkeypatch.setattr(
        wdw, "set_watch_directive_status", lambda q, did, st, source: archived.append((did, st, source))
    )
    q = lambda sql, params=None, fetch="all": [{"id": 1352}] if "watch_directives" in sql else []  # noqa: E731
    out = cmd.post_mine_decision(
        {"symbol": "nvda", "action": "add", "note": "AI capex", "by": "spoofed"},
        db_execute=lambda sql, p=None: ex.append((sql, p)),
        db_query=q,
    )
    assert out["ok"] and out["event_type"] == "watch_mine_added" and out["by"] == "tailnet:john@example"
    assert out["broker_write"] is False
    assert ex[0][0].startswith("INSERT INTO operator_starred_symbols") and ex[0][1] == ("NVDA", "tailnet:john@example")
    assert ex[1][0].startswith("INSERT INTO watchlist_events") and '"note": "AI capex"' in ex[1][1][3]
    ex.clear()
    out = cmd.post_mine_decision(
        {"symbol": "SKYD", "action": "remove", "reason": "done"},
        db_execute=lambda sql, p=None: ex.append((sql, p)),
        db_query=q,
    )
    assert (
        out["ok"]
        and out["archived_directives"] == [1352]
        and archived == [(1352, "archived", "watch_my_watchlist_remove")]
    )
    assert ex[0][0].startswith("DELETE FROM operator_starred_symbols") and ex[-1][1][0] == "watch_mine_removed"
    assert (
        cmd.post_mine_decision({"symbol": "X", "action": "buy"}, db_execute=lambda *a: None, db_query=q)["ok"] is False
    )
    src = (ROOT / "scripts/api_v2.py").read_text()
    assert 'if cmd == "mine":' in src


def test_a_removed_name_leaves_my_watchlist_until_added_again():
    def q(sql, params=None):
        if "operator_starred" in sql:
            return []
        if "personal_watchlist" in sql and "source = 'personal_watchlist'" in sql:
            return [
                {"s": "PLTR", "at": "2026-06-01T00:00:00+00:00", "ref": None, "label": None},
                {"s": "MSFT", "at": "2026-06-01T00:00:00+00:00", "ref": None, "label": None},
            ]
        if "watch_mine_added" in sql:
            return [
                {"s": "PLTR", "event_type": "watch_mine_removed", "created_at": "2026-10-23T14:00:00+00:00"},
                {"s": "MSFT", "event_type": "watch_mine_added", "created_at": "2026-10-23T14:05:00+00:00"},
            ]
        return []

    out = wdom.membership_operator(db_query=q)
    assert "PLTR" not in out["names"] and "MSFT" in out["names"] and out["removed"] == ["PLTR"]


def test_symbol_search_ranks_ticker_then_name_and_skips_cusips():
    by_symbol = {"NVDA": "g1", "NVDQ": "g2", "NAVN": "g3", "543354104": "g4"}
    ents = {"g1": {"identity_status": "CONFIRMED", "security_guid": "s1"}}
    names = {"NVDA": "NVIDIA CORP", "NVDQ": "T REX 2X INVERSE NVIDIA DAILY ETF", "NAVN": "NAVAN INC A"}
    r = wc.search_symbols("nvda", by_symbol=by_symbol, entities=ents, names=names, mine={"NVDA"})
    assert r[0]["symbol"] == "NVDA" and r[0]["on_my_list"] and r[0]["identity_status"] == "CONFIRMED"
    assert [
        x["symbol"] for x in wc.search_symbols("nvidia", by_symbol=by_symbol, entities=ents, names=names, mine=set())
    ] == ["NVDA", "NVDQ"]
    assert wc.search_symbols("5433", by_symbol=by_symbol, entities=ents, names=names, mine=set()) == []
    assert wc.search_symbols("", by_symbol=by_symbol, entities=ents, names=names, mine=set()) == []
