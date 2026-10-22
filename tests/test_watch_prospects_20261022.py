"""Watch redesign (operator directive 2026-10-22: build the Gate 3 Watch mockup) — the prospect lanes adapter.

lib/data_broker/watch_prospects.py builds one row per security in exactly one lane (Actionable now · Setup forming ·
Re-entry near · Manage (held) · Expired) with conviction + components, stance, conflicts (shown, never resolved —
AGENTS.md §26.5), next trigger and ONE next step. It reads the cio_prospect projection when that exists; until then
an interim adapter over today's sources, labelled "interim — CIO prospect store not live".

Fakes only: no database, no network, no broker, no production state (AGENTS.md §24.6).
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import watch_decision as wd  # noqa: E402
from lib.data_broker import watch_prospects as wp  # noqa: E402
from lib.cio_instrument_record import BEHAVIOR_FIELDS  # noqa: E402

NOW = datetime(2026, 10, 22, 15, 30, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(hours=3)).isoformat()
LATER = (NOW + timedelta(hours=40)).isoformat()
PAST = (NOW - timedelta(hours=2)).isoformat()


def card(sym="ABC", *, held=False, rule="candidate", status="active", actionable=False, trade="WAIT",
         synthesis=None, review=None, expires=LATER, levels=None, category="watchlist_candidate", **k):
    c = {"symbol": sym, "company": f"{sym} Inc", "last": 10.0, "rsi": 50.0, "held": held, "trade_ai_state": trade,
         "support": 9.0, "resistance": 11.0, "price_as_of": FRESH,
         "decision": {"rule_id": rule, "status": status, "actionable": actionable, "category": category,
                      "priority_score": 50.0, "evidence_at": FRESH, "expires_at": expires,
                      "action_hint": "Review entry" if actionable else None,
                      "inputs": {"synthesis": synthesis, "synthesis_at": FRESH if synthesis else None,
                                 "plan_levels": levels}}}
    if review:
        c["cio_review"] = {"verdict": review, "completed_at": "2026-09-02T20:21:21+00:00"}
    c.update(k)
    return c


def opp(sym="ABC", conv=70.0, stance="WATCH", position="not_owned", rank=5):
    return {"symbol": sym, "conviction": conv, "stance": stance, "position_status": position, "rank": rank,
            "as_of": FRESH, "coverage": 0.9, "factors_missing": ["fundamental"],
            "stance_rationale": f"{stance} rationale",
            "factors": {"technical": {"score": 80.0, "label": "Technical", "weight": 0.22, "source": "hermes"},
                        "analyst": {"score": 60.0, "label": "Analyst", "weight": 0.18, "source": "yahoo"}},
            "risk_reward": {"entry_zone": [9.5, 10.5], "entry_ref": 10.0, "invalidation_level": 9.0,
                            "primary_target": 14.0}}


def build(cards, opps=None, desk=None, held=None, **k):
    held = held if held is not None else {c["symbol"] for c in cards if c.get("held")}
    return wp.build_watch_prospects(cards=cards, opportunities=opps or {}, reentry=desk or {}, held=held,
                                    held_source="positions_store.positions_current", now=NOW, **k)


def rows(payload):
    return {r["symbol"]: r for lane in payload["lanes"] for r in lane["items"]}


def lane_of(payload, sym):
    return rows(payload)[sym]["lane"]


# ── lanes and one membership ──────────────────────────────────────────────────

def test_held_is_always_manage_and_never_proposed():
    p = build([card("RTX", held=True, rule="held_watch", actionable=False, category="held_position")],
              {"RTX": opp("RTX", stance="HOLD", position="owned")})
    r = rows(p)["RTX"]
    assert r["lane"] == "manage" and r["stage"] == "held"
    assert r["next_action"]["kind"] != "propose"


def test_held_name_with_expired_signal_stays_in_manage():
    p = build([card("XAR", held=True, rule="held_watch", status="expired", expires=PAST)])
    assert lane_of(p, "XAR") == "manage"


def test_non_held_expired_or_invalidated_goes_to_expired_with_no_step():
    p = build([card("OLD", status="expired", expires=PAST), card("BAD", status="invalidated", trade="AVOID")])
    assert lane_of(p, "OLD") == "expired" and lane_of(p, "BAD") == "expired"
    assert rows(p)["OLD"]["next_action"]["kind"] == "none"
    assert rows(p)["OLD"]["stale"] is True


def test_actionable_rule_is_actionable_with_propose_seeded_from_plan_refs():
    lv = {"entry_low_ref": 9.6, "entry_high_ref": 10.2, "limit_ref": 10.1, "stop_ref": 9.1, "target_ref": 13.0}
    p = build([card("GO", rule="plan_ready_strong", actionable=True, levels=lv)], {"GO": opp("GO")})
    r = rows(p)["GO"]
    assert r["lane"] == "actionable"
    assert r["next_action"]["kind"] == "propose" and r["next_action"]["label"] == "Propose"
    assert r["next_action"]["seed"] == {"entry_ref": 10.1, "stop_ref": 9.1, "target_ref": 13.0}
    assert r["next_trigger"]["inside"] is True


def test_deterministic_fail_is_never_actionable():
    p = build([card("FAIL", rule="plan_ready", actionable=True, trade="DETERMINISTIC_FAIL")])
    assert lane_of(p, "FAIL") == "forming"


def test_reentry_desk_names_outside_the_watch_universe_still_get_a_lane():
    desk = {"ALXO": {"state": "NEAR ENTRY", "price": 5.0, "rsi": 48.0, "entry_low_ref": 4.8, "entry_high_ref": 5.1,
                     "price_as_of": FRESH, "reason": "Hard gates pass", "held": False},
            "CACI": {"state": "READY TO REVIEW", "price": 624.7, "entry_low_ref": 620.0, "entry_high_ref": 628.0,
                     "stop_ref": 604.0, "target_ref": 690.0, "price_as_of": FRESH, "held": False},
            "WAITX": {"state": "WAIT", "price_as_of": FRESH, "held": False},
            "HELDX": {"state": "NEAR ENTRY", "price_as_of": FRESH, "held": True}}
    p = build([], {}, desk)
    r = rows(p)
    assert r["ALXO"]["lane"] == "reentry" and r["ALXO"]["next_action"]["kind"] == "set_alert"
    assert r["ALXO"]["next_action"]["seed"]["entry_low_ref"] == 4.8
    assert r["CACI"]["lane"] == "actionable" and r["CACI"]["next_action"]["seed"]["stop_ref"] == 604.0
    assert "WAITX" not in r and "HELDX" not in r


def test_one_membership_even_when_a_symbol_repeats():
    p = build([card("DUP", held=True, rule="held_watch"), card("DUP", rule="plan_ready", actionable=True)])
    assert sum(1 for lane in p["lanes"] for r in lane["items"] if r["symbol"] == "DUP") == 1
    assert p["counts"]["total"] == 1


def test_lane_cap_names_the_overflow():
    cs = [card(f"S{i:02d}") for i in range(6)]
    p = build(cs, {f"S{i:02d}": opp(f"S{i:02d}", conv=50 + i) for i in range(6)}, caps={"forming": 4})
    forming = next(lane for lane in p["lanes"] if lane["id"] == "forming")
    assert forming["count"] == 6 and len(forming["items"]) == 4
    assert forming["overflow"] == ["S01", "S00"]  # lowest conviction left out, by name


def test_order_is_conviction_high_first_and_missing_conviction_last():
    p = build([card("LOW"), card("HIGH"), card("NONE")], {"LOW": opp("LOW", 40), "HIGH": opp("HIGH", 90)})
    forming = next(lane for lane in p["lanes"] if lane["id"] == "forming")
    assert [r["symbol"] for r in forming["items"]] == ["HIGH", "LOW", "NONE"]
    assert "No CIO conviction yet" in " ".join(rows(p)["NONE"]["whats_missing"])


# ── conviction components ─────────────────────────────────────────────────────

def test_conviction_carries_named_components_and_missing_factors():
    p = build([card("C")], {"C": opp("C", 72.4)})
    r = rows(p)["C"]
    assert r["conviction"] == 72.4 and r["conviction_source"] == "cio_opportunity_projection"
    assert [c["key"] for c in r["conviction_components"]] == ["technical", "analyst"]
    assert r["conviction_missing"] == ["fundamental"]


# ── conflicts: shown, never resolved (§26.5) ──────────────────────────────────

def test_stance_vs_review_conflict_keeps_both_values_sources_and_times():
    p = build([card("SPCX", held=True, rule="held_watch", review="HOLD")],
              {"SPCX": opp("SPCX", 80.3, "ADD", "owned")})
    r = rows(p)["SPCX"]
    c = next(x for x in r["conflicts"] if x["kind"] == "stance_vs_review")
    assert c["a"] == {"value": "ADD", "source": "cio_opportunity_projection", "at": FRESH}
    assert c["b"]["value"] == "HOLD" and c["b"]["source"] == "watchlist CIO review" and c["b"]["at"]
    assert r["stance"] == "ADD"  # nothing picked a winner
    assert r["next_action"]["kind"] == "resolve_conflict"


def test_held_at_risk_protect_first_comes_before_resolving_a_conflict():
    p = build([card("NAVN", held=True, rule="held_negative", synthesis="SELL", category="risk")],
              {"NAVN": opp("NAVN", 87.7, "HOLD", "owned")})
    r = rows(p)["NAVN"]
    assert any(x["kind"] == "stance_vs_synthesis" for x in r["conflicts"])
    assert r["next_action"]["kind"] == "protect" and r["next_action"]["label"] == "Protect first"
    assert r["next_action"]["href"] == "/v3/trading?tab=Open+Trades&symbol=NAVN"


def test_ownership_disagreement_is_a_conflict():
    p = build([card("NVDA", held=True, rule="held_watch")], {"NVDA": opp("NVDA", 78.5, "WATCH", "not_owned")})
    kinds = [x["kind"] for x in rows(p)["NVDA"]["conflicts"]]
    assert kinds == ["ownership"]


def test_trade_ai_block_against_a_reentry_go_is_a_conflict():
    desk = {"FATN": {"state": "NEAR ENTRY", "price_as_of": FRESH, "held": False}}
    p = build([card("FATN", trade="DETERMINISTIC_FAIL", rule="reentry_near", category="re_entry")],
              {"FATN": opp("FATN", 62, "RE_ENTER", "recently_sold")}, desk)
    r = rows(p)["FATN"]
    assert r["lane"] == "reentry"
    assert any(x["kind"] == "trade_ai_block" for x in r["conflicts"])


def test_same_family_is_not_a_conflict():
    p = build([card("OK", review="WATCH")], {"OK": opp("OK", 60, "HOLD")})
    assert rows(p)["OK"]["conflicts"] == []


# ── labels, surfaces, rails ───────────────────────────────────────────────────

def test_interim_payload_is_labelled_and_surfaces_say_not_joined():
    p = build([card("A")], {"A": opp("A")})
    assert p["interim"] is True and p["source_label"] == "interim — CIO prospect store not live"
    surf = {s["surface"]: s for s in rows(p)["A"]["surfaces"]}
    assert set(wp.SURFACES) <= set(surf)
    assert surf["Home"]["value"] == wp.NOT_JOINED and surf["Home"]["joined"] is False
    assert surf["Open Trades"]["value"] == "not held"
    assert surf["Opportunities (CIO curator)"]["value"] == "#5 · 70 · WATCH"


def _keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


def test_no_key_anywhere_is_a_behavior_field():
    lv = {"entry_low_ref": 9.6, "entry_high_ref": 10.2, "limit_ref": 10.1, "stop_ref": 9.1, "target_ref": 13.0}
    desk = {"Q": {"state": "NEAR ENTRY", "price_as_of": FRESH, "entry_low_ref": 1.0, "entry_high_ref": 2.0}}
    p = build([card("GO", rule="plan_ready", actionable=True, levels=lv), card("H", held=True)],
              {"GO": opp("GO")}, desk)
    assert not (set(_keys(p)) & set(BEHAVIOR_FIELDS))
    assert p["mbi_behavior"] == 0


def test_watch_decision_plan_levels_use_ref_keys_and_only_when_fresh():
    plan = {"urgency": "ready", "confidence": 0.7, "risk_reward": 3.0, "entry_zone_low": 9.5,
            "entry_zone_high": 10.5, "limit_price": 10.0, "stop_price": 9.0, "target_price": 13.0,
            "created_at": FRESH}
    d = wd.decide({"symbol": "Z", "last": 10.0, "held": False, "trade_ai_state": "WAIT"}, {"plan": plan}, now=NOW)
    lv = d["inputs"]["plan_levels"]
    assert lv["stop_ref"] == 9.0 and lv["target_ref"] == 13.0 and lv["limit_ref"] == 10.0
    assert not (set(lv) & set(BEHAVIOR_FIELDS))
    old = dict(plan, created_at=(NOW - timedelta(days=30)).isoformat())
    d2 = wd.decide({"symbol": "Z", "last": 10.0, "held": False, "trade_ai_state": "WAIT"}, {"plan": old}, now=NOW)
    assert d2["inputs"]["plan_levels"] is None


# ── the cio_prospect projection, when live ────────────────────────────────────

# Record shapes as cio_prospect_builder.assemble writes them (branch feat/cio-prospect-p0-p1-20261022).
def _rec(sym, stage, conv, expires, **k):
    r = {"symbol": sym, "stage": stage, "conviction": conv, "expires_at": expires, "evidence_at": FRESH,
         "stance": "WATCH", "security_guid": f"guid-{sym}", "issuer_guid": f"iss-{sym}",
         "conviction_components": {"opportunity_score": {"value": conv, "weight": 0.5, "source": "cio_opportunity_projection",
                                                         "evidence_at": FRESH},
                                   "unified_edge": {"value": 70.0, "weight": 0.3, "source": "opportunity+reentry inputs",
                                                    "evidence_at": FRESH}},
         "next_trigger": {"kind": "reference_level", "entry_zone": [9.5, 10.5], "entry_ref": 10.0,
                          "invalidation_level": 9.0, "observed_by": "cio-entry-state"},
         "next_action": {"who": "lane", "what": "wait for the next trigger"}, "conflicts": []}
    r.update(k)
    return r


def test_from_cio_prospect_maps_stage_to_lane_expiry_conflicts_and_one_step():
    conflict = {"field": "stance", "resolved": False,
                "values": [{"value": "ADD", "source": "cio_opportunity_projection", "at": FRESH},
                           {"value": "watch", "source": "cio_theses v8", "at": "2026-10-05T00:00:00+00:00"}]}
    recs = [
        _rec("AAA", "actionable", 81, LATER, stance="BUY_SETUP"),
        _rec("BBB", "held", 60, PAST, stance="TRIM_REVIEW"),
        _rec("CCC", "setup_forming", 50, PAST),
        _rec("DDD", "re_entry", 55, LATER),
        _rec("EEE", "held", 78.5, LATER, stance="ADD", conflicts=[conflict]),
    ]
    p = wp.from_cio_prospect(recs, now=NOW)
    r = rows(p)
    assert p["interim"] is False and p["source"] == "cio_prospect"
    assert [r[s]["lane"] for s in ("AAA", "BBB", "CCC", "DDD", "EEE")] == \
        ["actionable", "manage", "expired", "reentry", "manage"]
    assert r["AAA"]["next_action"]["kind"] == "propose"
    assert r["AAA"]["next_action"]["seed"] == {"entry_ref": 10.0, "stop_ref": 9.0, "target_ref": None}
    assert r["BBB"]["next_action"]["kind"] == "protect"
    assert r["DDD"]["next_action"]["kind"] == "set_alert" and r["DDD"]["next_trigger"]["label"] == "zone $9.50–$10.50"
    c = r["EEE"]["conflicts"][0]
    assert c["kind"] == "stance" and c["a"]["value"] == "ADD" and c["b"]["value"] == "watch"
    assert c["b"]["source"] == "cio_theses v8" and r["EEE"]["next_action"]["kind"] == "resolve_conflict"
    assert [x["key"] for x in r["AAA"]["conviction_components"]] == ["opportunity_score", "unified_edge"]
    assert all(s["value"] == "same record" for s in r["AAA"]["surfaces"])
    assert not (set(_keys(p)) & set(BEHAVIOR_FIELDS))


def _fake_cp(monkeypatch, out):
    mod = types.ModuleType("lib.data_broker.cio_prospect")
    mod.get_prospects = lambda db_query=None, **k: out
    monkeypatch.setitem(sys.modules, "lib.data_broker.cio_prospect", mod)
    import lib.data_broker as pkg
    monkeypatch.setattr(pkg, "cio_prospect", mod, raising=False)
    monkeypatch.setattr(wp, "_db_query", lambda: None)


def test_list_reads_the_cio_prospect_store_when_it_is_live(monkeypatch):
    _fake_cp(monkeypatch, {"prospects": [_rec("AAA", "held", 60, LATER)], "source": {"kind": "store"},
                           "store_status": {"live": True}})
    wp._CACHE.update(at=0.0, val=None)
    out = wp.list_watch_prospects({"fresh": "1"})
    wp._CACHE.update(at=0.0, val=None)
    assert out["source"] == "cio_prospect" and out["interim"] is False and out["cio_prospect_status"] == "store"


def test_a_shadow_build_is_not_read_as_the_record(monkeypatch):
    _fake_cp(monkeypatch, {"prospects": [_rec("AAA", "held", 60, LATER)], "source": {"kind": "shadow"},
                           "store_status": {"live": False}})
    assert wp._cio_prospect_records() == (None, "shadow")


def test_list_falls_back_to_the_labelled_interim_adapter(monkeypatch):
    monkeypatch.setattr(wp, "_cio_prospect_records", lambda: (None, "absent"))
    from lib.data_broker import watch_intelligence as wi

    monkeypatch.setattr(wi, "compose_universe", lambda **k: {
        "items": [{"card": card("GO", rule="plan_ready", actionable=True)}], "held": set(),
        "held_source": "positions_store.positions_current", "held_detail": {"as_of": FRESH, "stale": False}})
    monkeypatch.setattr(wd, "reentry_rows", lambda: {})
    monkeypatch.setattr(wp, "_identities", lambda syms: {})

    class FakeStore:
        def read_projection(self):
            return {"as_of": FRESH, "items": {"GO": opp("GO")}}

    import lib.cio_opportunity_store as cos
    monkeypatch.setattr(cos, "CIOOpportunityStore", FakeStore)
    try:
        import scripts.lib.cio_opportunity_store as scos
        monkeypatch.setattr(scos, "CIOOpportunityStore", FakeStore)
    except ImportError:
        pass
    wp._CACHE.update(at=0.0, val=None)
    out = wp.list_watch_prospects({"fresh": "1"})
    wp._CACHE.update(at=0.0, val=None)
    assert out["interim"] is True and out["source_label"] == wp.INTERIM_LABEL
    assert rows(out)["GO"]["lane"] == "actionable" and rows(out)["GO"]["conviction"] == 70.0


# ── wiring ────────────────────────────────────────────────────────────────────

def test_route_is_registered_once_and_the_catalog_advertises_it():
    src = (ROOT / "scripts/api_v2.py").read_text()
    assert src.count('if p == "watch-prospects":') == 1
    from lib.data_broker.catalog import PROJECTIONS
    entry = next(x for x in PROJECTIONS if x["id"] == "watch_prospects")
    assert entry["module"] == "lib.data_broker.watch_prospects" and entry["read_only"] is True
    assert "GET /api/v3/data-broker/watch-prospects" in entry["http"]


def test_list_watch_intelligence_and_the_adapter_share_one_composition():
    src = (ROOT / "scripts/lib/data_broker/watch_intelligence.py").read_text()
    assert "def compose_universe(" in src
    body = src.split("def list_watch_intelligence(")[1].split("\ndef ")[0]
    assert "compose_universe(" in body and "list_intelligence(" not in body


@pytest.mark.parametrize("stance,fam", [("ADD", "positive"), ("RE_ENTER", "positive"), ("HOLD", "neutral"),
                                        ("WATCH", "neutral"), ("SELL", "negative"), ("TRIM_REVIEW", "negative"),
                                        ("", None), ("WHATEVER", None)])
def test_stance_families(stance, fam):
    assert wp.family(stance) == fam
