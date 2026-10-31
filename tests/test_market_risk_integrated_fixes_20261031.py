"""Integrated precision + rotation branch: the review findings, each pinned (ANCHOR MARKET_RISK_INTEGRATED_FIXES_20261031).

Synthetic symbols and amounts only (public repo). No database, network, LLM or send: the book, the stops, the quotes,
the bars and the trade ledger are injected fakes; state goes to tmp_path.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.lib.market_risk import book_precision as bp
from scripts.lib.market_risk import cio_memory_fanout as F
from scripts.lib.market_risk import position_stances as ps
from scripts.lib.market_risk import policy as P
from scripts.lib.market_risk import rotation_advice as ra

POLICY = P.load_policy()
UTC = timezone.utc


# --------------------------------------------------------------------------- fakes


class FakeAssessment:
    def __init__(self, tier: str, groups: dict[str, str], as_of: str):
        self.tier = tier
        self.as_of = as_of
        self.sectors = {
            "groups": [{"key": k, "label": k.title(), "kind": "sector", "state": st} for k, st in groups.items()],
            "stressed": [k.title() for k, st in groups.items() if st == "STRESS"],
            "weak": [k.title() for k, st in groups.items() if st == "WEAK"],
        }
        self.positions: dict = {}
        self.heatmap: list = []
        self.reentry_watch: dict = {}
        self.session_history: list = []

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "market_tier": self.tier,
            "as_of": self.as_of,
            "sectors": self.sectors,
            "shock_type": {"class": "SECTOR", "headline": ""},
            "observations": [],
            "session_history": self.session_history,
        }


def _bars(sym: str, end: date, n: int, px: float = 100.0) -> list[dict]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append({"symbol": sym, "date": d.isoformat(), "close": px})
        d -= timedelta(days=1)
    return list(reversed(out))


class FakeReader:
    def __init__(self, quotes: list[dict] | None = None, bar_px: dict[str, float] | None = None):
        self._quotes = quotes or []
        self._px = bar_px or {}
        self.quote_calls: list = []

    def daily_bars(self, symbols, *, sessions, end):
        out = []
        for s in symbols:
            if s in self._px:
                last = end.astimezone(bp_et()).date()
                if (end.astimezone(bp_et()).hour, end.astimezone(bp_et()).minute) < (16, 0):
                    last -= timedelta(days=1)
                out += _bars(s, last, min(int(sessions), 80), self._px[s])
        return out

    def quotes(self, symbols, *, start, end):
        self.quote_calls.append((list(symbols), start, end))
        return [q for q in self._quotes if q["symbol"] in set(symbols)]


def bp_et():
    from scripts.lib.market_risk.sessions import ET

    return ET


def _book(data_as_of: str, **h) -> dict:
    row = {"symbol": "ZZTECH", "account": "Synthetic Individual", "shares": 50, "market_value": 5000.0, "price": 100.0}
    row.update(h)
    return {"data_as_of": data_as_of, "aggregate_published_at": data_as_of + "T21:00:00+00:00", "holdings": [row]}


def _loaders(book: dict, stop: float | None = 98.0, earnings: dict | None = None) -> dict:
    return {
        "store_loader": lambda: book,
        "stops_loader": lambda now: [{"symbol": "ZZTECH", "level": stop}] if stop else [],
        "profiles_loader": lambda syms: ({"ZZTECH": {"sector": "Technology"}}, None),
        "book_doc": book,
        "earnings_loader": lambda syms: earnings or {},
    }


def _attach(a, now, reader, prior=None, **kw):
    return bp.attach(a, now=now, reader=reader, policy=POLICY, prior=prior, loaders=_loaders(**kw), conn_factory=None)


# --------------------------------------------------------------------------- B2 evening exit review, live path


def test_evening_exit_review_is_live_from_after_hours_quotes_knowable_at_now():
    now = datetime(2026, 10, 29, 22, 0, tzinfo=UTC)  # 18:00 ET, after hours
    quotes = [
        {"symbol": "ZZTECH", "price": 99.0, "session": "afterhours", "as_of": "2026-10-29T21:30:00+00:00"},
        # printed AFTER now: never knowable at now, must be ignored (it would leave 7 points of room)
        {"symbol": "ZZTECH", "price": 105.0, "session": "afterhours", "as_of": "2026-10-29T23:30:00+00:00"},
        # a regular-session print is not an after-hours move
        {"symbol": "ZZTECH", "price": 90.0, "session": "regular", "as_of": "2026-10-29T19:00:00+00:00"},
    ]
    a = FakeAssessment("YELLOW", {"tech": "NEUTRAL"}, now.isoformat())
    out = _attach(a, now, FakeReader(quotes, {"ZZTECH": 100.0}), book=_book("2026-10-29"))
    rec = a.positions["ZZTECH"]
    assert out["evening"] == ["ZZTECH"]
    assert rec["stance"] == "EXIT", rec
    assert rec["reasons"][0].startswith("after hours: implied open -1.00%")
    assert "left before the broker stop" in rec["reasons"][0]


def test_no_evening_review_without_after_hours_prints_or_during_the_session():
    now = datetime(2026, 10, 29, 22, 0, tzinfo=UTC)
    a = FakeAssessment("YELLOW", {"tech": "NEUTRAL"}, now.isoformat())
    _attach(a, now, FakeReader([], {"ZZTECH": 100.0}), book=_book("2026-10-29"))
    assert a.positions["ZZTECH"]["stance"] == "HOLD"
    regular = datetime(2026, 10, 29, 17, 0, tzinfo=UTC)  # 13:00 ET
    r = FakeReader([{"symbol": "ZZTECH", "price": 90.0, "session": "afterhours", "as_of": "2026-10-28T21:00:00+00:00"}])
    assert bp.after_hours_moves(r, ["ZZTECH"], regular) == {} and r.quote_calls == []


# --------------------------------------------------------------------------- B3 per-session history


def test_session_history_upserts_one_entry_per_session_and_skips_closed_days():
    h = None
    for t, tier, st in [
        ("2026-10-28T15:00:00+00:00", "ORANGE", "STRESS"),
        ("2026-10-28T20:30:00+00:00", "ORANGE", "WEAK"),  # same session: replaces the earlier entry
        ("2026-10-31T15:00:00+00:00", "GREEN", "NEUTRAL"),  # Saturday: adds nothing
        ("2026-10-29T20:30:00+00:00", "YELLOW", "NEUTRAL"),
    ]:
        blk = {"groups": [{"key": "tech", "label": "Technology", "state": st, "r5": -1.0}]}
        h = bp.session_history({"session_history": h}, now=datetime.fromisoformat(t), tier=tier, sectors_block=blk)
    assert [(x["session"], x["tier"], x["sectors"]["groups"][0]["state"]) for x in h] == [
        ("2026-10-28", "ORANGE", "WEAK"),
        ("2026-10-29", "YELLOW", "NEUTRAL"),
    ]
    assert set(h[0]["sectors"]["groups"][0]) == {"key", "label", "state"}


def test_group_recovered_becomes_true_across_live_cycles():
    reader = FakeReader([], {"ZZTECH": 100.0})
    prior = None
    met = []
    for day, tier, st in [
        ("2026-10-27", "ORANGE", "STRESS"),
        ("2026-10-28", "YELLOW", "NEUTRAL"),
        ("2026-10-29", "YELLOW", "NEUTRAL"),
    ]:
        now = datetime.fromisoformat(day + "T20:30:00+00:00")
        a = FakeAssessment(tier, {"tech": st}, now.isoformat())
        _attach(a, now, reader, prior=prior, book=_book(day))
        rec = a.positions["ZZTECH"]
        met.append((rec["stance"], [c["met"] for c in rec["re_enter_if"] if c["key"] == "group_recovered"]))
        prior = json.loads(json.dumps({**a.to_dict(), "positions": a.positions, "session_history": a.session_history}))
    assert met[0][0] == "TRIM"
    assert met[1] == ("RE_ENTER_IF", [False])  # one recovered session of two
    assert met[2] == ("RE_ENTER_IF", [True])  # two recovered sessions: the condition fires


# --------------------------------------------------------------------------- B4 wash sale + M4 read-only + re-entry


class FakeConn:
    def __init__(self, rows, earn=None):
        self.rows, self.earn, self.readonly, self.executed = rows, earn or [], False, []

    def set_session(self, readonly=False):
        self.readonly = readonly

    def cursor(self):
        conn = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                assert conn.readonly, "query before the session was made read-only"
                conn.executed.append(sql)
                self._r = conn.rows if "trade_closed" in sql else conn.earn

            def fetchall(self):
                return list(self._r)

        return Cur()

    def close(self):
        pass


def _watch_block(rows, now, prior=None, tier="YELLOW", st="NEUTRAL"):
    a = FakeAssessment(tier, {"tech": st}, now.isoformat())
    conn = FakeConn(rows, earn=[(s, None, None, "Technology") for s in ("ZZEX", "ZZEY")])
    reader = FakeReader([], {s: 100.0 for s in ("ZZEX", "ZZEY")})
    cards = bp.reentry_watch_block(a, now=now, reader=reader, policy=POLICY, prior=prior, conn_factory=lambda: conn)
    return cards, conn, a


def test_wash_sale_note_only_from_the_latest_taxable_loss():
    now = datetime(2026, 10, 29, 20, 30, tzinfo=UTC)
    rows = [
        ("ZZEX", "Synthetic Roth IRA", date(2026, 10, 20), True),  # IRA loss: no wash sale
        ("ZZEX", "Synthetic Individual", date(2026, 10, 25), False),  # taxable GAIN: no wash sale
        ("ZZEY", "Synthetic Individual", date(2026, 10, 10), True),  # taxable loss 19 days ago
        ("ZZEY", "Synthetic Rollover IRA", date(2026, 10, 26), False),
    ]
    cards, conn, _ = _watch_block(rows, now)
    assert conn.readonly and conn.executed
    assert cards["ZZEX"]["wash_sale_note"] is None
    assert "19 days ago" in cards["ZZEY"]["wash_sale_note"]
    assert cards["ZZEY"]["exit_date"] == "2026-10-26"


def test_reentry_watch_group_recovered_across_cycles():
    rows = [("ZZEX", "Synthetic Roth IRA", date(2026, 10, 20), True)]
    prior, met = None, []
    for day, st in [("2026-10-27", "STRESS"), ("2026-10-28", "NEUTRAL"), ("2026-10-29", "NEUTRAL")]:
        now = datetime.fromisoformat(day + "T20:30:00+00:00")
        cards, _, a = _watch_block(rows, now, prior=prior, st=st)
        met.append([c["met"] for c in cards["ZZEX"]["conditions"] if c["key"] == "group_recovered"][0])
        prior = {"session_history": a.session_history}
    assert met == [False, False, True]


def test_unknown_group_states_never_count_as_recovered():
    from scripts.lib.market_risk import reentry_watch as rw

    rec = rw.card(
        symbol="ZZEX",
        exit_date="2026-10-20",
        breakdown_close=None,
        closes=[],
        last_date=None,
        group_label="Technology",
        group_history=["UNKNOWN", "UNKNOWN"],
        earnings_next=None,
        earnings_last=None,
        sessions_since_earnings=None,
        sessions_to_earnings=None,
        market_tier="YELLOW",
        options_flow_state="CALM",
        taxable_loss_days_ago=None,
        policy=POLICY,
    )
    assert [c["met"] for c in rec["conditions"] if c["key"] == "group_recovered"] == [False]


def test_reentry_watch_unknown_group_is_never_recovered():
    rows = [("ZZEX", "Synthetic Roth IRA", date(2026, 10, 20), True)]
    now = datetime(2026, 10, 29, 20, 30, tzinfo=UTC)
    a = FakeAssessment("YELLOW", {"tech": "NEUTRAL"}, now.isoformat())
    a.session_history = [
        {"session": d, "tier": "YELLOW", "sectors": {"groups": []}} for d in ("2026-10-28", "2026-10-29")
    ]
    conn = FakeConn(rows, earn=[])  # no profile: the group is unknown
    cards = bp.reentry_watch_block(
        a, now=now, reader=FakeReader([], {"ZZEX": 100.0}), policy=POLICY, prior=None, conn_factory=lambda: conn
    )
    gr = [c for c in cards["ZZEX"]["conditions"] if c["key"] == "group_recovered"][0]
    assert gr["met"] is False and gr["text"] == "group not measured: exposure unknown"


def test_read_only_refuses_a_connection_that_cannot_be_made_read_only():
    class Bare:
        def close(self):
            pass

    with pytest.raises(RuntimeError, match="read-only"):
        bp.read_only(lambda: Bare())


# --------------------------------------------------------------------------- M1 / R3 marks and staleness


def test_mark_is_canonical_or_price_never_current_price():
    b = bp.current_book(POLICY, doc=_book("2026-10-29", price=100.0, current_price=500.0))
    assert b["material"][0]["mark"] == 100.0
    b = bp.current_book(POLICY, doc=_book("2026-10-29", price=100.0, canonical_mark=101.0, current_price=500.0))
    assert b["material"][0]["mark"] == 101.0


def test_rotation_holdings_never_fall_back_to_current_price(tmp_path):
    import scripts.market_risk_rotation as rot

    p = tmp_path / "h.json"
    p.write_text(json.dumps({"holdings": [{"symbol": "ZZTECH", "shares": 10, "current_price": 500.0}]}))
    assert rot.load_holdings(p)[0]["market_value"] == 0.0


@pytest.mark.parametrize(
    "as_of,why",
    [("2026-10-26", "holdings stale: data as of 2026-10-26, 3 sessions behind"), (None, "holdings data_as_of missing")],
)
def test_stale_book_reads_unknown_with_a_reason(as_of, why):
    now = datetime(2026, 10, 29, 20, 30, tzinfo=UTC)
    a = FakeAssessment("ORANGE", {"tech": "STRESS"}, now.isoformat())
    book = _book(as_of or "2026-10-29")
    if as_of is None:
        book.pop("data_as_of")
    out = _attach(a, now, FakeReader([], {"ZZTECH": 100.0}), book=book)
    assert out["available"] is False and out["stale"].startswith(why)
    assert a.positions["ZZTECH"]["stance"] == "UNKNOWN" and a.positions["ZZTECH"]["reasons"][0].startswith(why)


def test_previous_session_book_is_fresh_in_the_evening_and_on_the_weekend():
    for t in ("2026-10-30T20:30:00+00:00", "2026-10-31T15:00:00+00:00", "2026-11-02T13:00:00+00:00"):
        assert bp.book_staleness({"data_as_of": "2026-10-29"}, datetime.fromisoformat(t), POLICY) is None, t
    assert bp.book_staleness({"data_as_of": "2026-10-29"}, datetime.fromisoformat("2026-11-02T22:00:00+00:00"), POLICY)


# --------------------------------------------------------------------------- M2 earnings shape


def test_reporting_soon_reads_the_dict_shapes():
    now = datetime(2026, 10, 30, 15, 0, tzinfo=UTC)
    earn = {
        "ZZA": "2026-11-03",
        "ZZB": {"next_earnings_date": date(2026, 11, 4), "last_earnings_date": date(2026, 10, 1)},
        "ZZC": {"next_earnings_date": date(2026, 12, 1)},
        "ZZD": {"next_earnings_date": None},
    }
    assert bp.reporting_soon(earn, now, 5) == {"ZZA", "ZZB"}
    assert bp.reporting_soon([{"symbol": "ZZA"}], now, 5) == set()


def test_attach_flags_reporting_from_the_profile_dates():
    now = datetime(2026, 10, 29, 20, 30, tzinfo=UTC)
    a = FakeAssessment("YELLOW", {"tech": "NEUTRAL"}, now.isoformat())
    _attach(
        a,
        now,
        FakeReader([], {"ZZTECH": 100.0}),
        book=_book("2026-10-29"),
        earnings={"ZZTECH": {"next_earnings_date": date(2026, 11, 2), "last_earnings_date": None}},
    )
    assert a.positions["ZZTECH"]["look_through"]["reporting"] == ["ZZTECH"]


# --------------------------------------------------------------------------- M3 unmeasured group


def test_unmeasured_group_reads_exposure_unknown():
    out = ps.stances(
        positions=["ZZOIL"],
        exposures={"ZZOIL": {"groups": {"energy": 1.0}}},
        tier="YELLOW",
        shock={"class": "SECTOR"},
        sectors_block={
            "groups": [{"key": "tech", "label": "Technology", "state": "STRESS"}],
            "stressed": ["Technology"],
        },
        prior=None,
        reentry=[],
        stop_distance_pct=None,
        policy=POLICY,
        as_of="2026-10-29",
    )
    assert out["ZZOIL"]["stance"] == "HOLD"
    assert out["ZZOIL"]["reasons"] == ["energy not measured: exposure unknown"]


def test_unmeasured_defensive_group_is_not_holding_up():
    out = ps.stances(
        positions=["ZZSTAP"],
        exposures={"ZZSTAP": {"groups": {"staples": 1.0}}},
        tier="GREEN",
        shock={},
        sectors_block={"groups": []},
        prior=None,
        reentry=[],
        stop_distance_pct=None,
        policy=POLICY,
        as_of="2026-10-29",
    )
    assert out["ZZSTAP"]["reasons"] == ["staples not measured: exposure unknown"]


# --------------------------------------------------------------------------- R1 / R7 track record + caveat

TR = json.loads(open("docs/audits/ROTATION_LEADERSHIP_BACKTEST_20261031.json").read())["summary"]


def test_track_record_summary_includes_the_2026_holdout():
    assert (TR["holdout_confirmed_hit_60"], TR["holdout_baseline_hit_60"]) == (0.35, 0.542)
    assert (TR["holdout_strategic_hits_60"], TR["holdout_strategic_n_60"]) == (0, 6)
    assert TR["holdout_false_confirmation_rate"] == 0.65


def test_card_line_and_cio_facts_carry_the_holdout():
    line = ra.track_record_holdout_line(TR)
    assert line == (
        "2026 holdout: confirmed leaders 0.35 vs 0.542 for plain momentum (n=20); strategic calls 0 of 6; "
        "65% false confirmations."
    )
    assert line in ra.render_card({"track_record": TR})
    from scripts.lib.market_risk import cio_context

    facts = cio_context._leadership_facts({"state": "evaluated", "as_of": "2026-10-30", "groups": {}})
    assert facts["track_record"]["holdout_confirmed_hit_60"] == 0.35
    assert "No demonstrated edge" in facts["caveat"] and "0.35 vs 0.542" in facts["caveat"]


def _plan(groups=None, exits=None):
    trigs = F.triggers(
        {"leadership": {"energy": "NEUTRAL"}, "tier": "YELLOW", "shock_type": None},
        {
            "leadership": {"energy": "LEADERSHIP_CONFIRMED"},
            "tier": "ORANGE",
            "shock_type": "SECTOR",
            "as_of": "2026-10-30",
        },
    )
    groups = groups or {
        "energy": {
            "label": "Energy",
            "class": "LEADERSHIP_CONFIRMED",
            "symbols": ["XLE"],
            "evidence": ["relative strength rising", "RS +4.2% over 60 sessions"],
        }
    }
    return F.plan_memory(
        trigs,
        groups=groups,
        cur={"as_of": "2026-10-30", "shock_type": "SECTOR"},
        exits=exits or [],
        tiers_by_group={},
        snapshot_ref="snap.json",
        policy=POLICY,
    )


def test_leadership_memories_carry_the_no_edge_caveat():
    plans = _plan()
    sec = next(p for p in plans if p["target"] == "sector_record")
    assert F.LEADERSHIP_CAVEAT in sec["next_research_question"] and sec["lesson"]["caveat"] == F.LEADERSHIP_CAVEAT
    assert sec["lesson"]["evidence"] == ["relative strength rising"]  # the numbered evidence line is not remembered
    aif = [p for p in plans if p["target"] == "aif_memory"]
    assert aif and all(F.LEADERSHIP_CAVEAT in p["record"]["content"] for p in aif)
    assert not any(p.get("refused") for p in plans)


# --------------------------------------------------------------------------- R5 text guard + idempotence


def test_price_text_is_refused_on_every_memory_path(monkeypatch, tmp_path):
    bad = "ZZEX closed at $134.20 after the stop at 137"
    assert F.text_refusal(bad)
    assert F.text_refusal("stop at 137") and F.text_refusal("down 4%") and F.text_refusal("buy 100 shares")
    assert F.text_refusal("ZZEX exited on 2026-10-30 during a SECTOR selloff; 3 of 5 conditions") is None
    calls = []
    spine = types.ModuleType("scripts.lib.cross_asset.security_research_spine")
    spine.upsert_research_memory = lambda *a, **k: calls.append(a) or {"ok": True}
    monkeypatch.setitem(sys.modules, "scripts.lib.cross_asset.security_research_spine", spine)
    plans = [
        {
            "target": "spine",
            "trigger_id": "mrt_a",
            "symbol": "ZZEX",
            "kind": "k",
            "tags": [],
            "summary": bad,
            "next_research_question": "q",
        },
        {
            "target": "sector_record",
            "trigger_id": "mrt_b",
            "sector": "Energy",
            "next_research_question": bad,
            "lesson": {"event": "x"},
        },
        {"target": "aif_memory", "trigger_id": "mrt_c", "record": {"content": bad, "subject": "market regime episode"}},
    ]
    receipts = F.apply_memory(plans, root=tmp_path)
    assert [bool(r.get("refused")) for r in receipts] == [True, True, True] and calls == []
    assert not (tmp_path / "data").exists()


def test_planned_exit_text_with_a_price_is_marked_refused():
    plans = _plan(exits=[{"symbol": "ZZEX", "date": "2026-10-30 at $134.20", "stressed_groups": []}])
    sp = next(p for p in plans if p["target"] == "spine")
    assert sp["refused"].startswith("price or number")


def test_memory_apply_is_idempotent_by_trigger_id(monkeypatch, tmp_path):
    calls = []
    spine = types.ModuleType("scripts.lib.cross_asset.security_research_spine")
    spine.upsert_research_memory = lambda *a, **k: calls.append(a) or {"ok": True}
    monkeypatch.setitem(sys.modules, "scripts.lib.cross_asset.security_research_spine", spine)
    plans = _plan(exits=[{"symbol": "ZZEX", "date": "2026-10-30", "stressed_groups": ["Technology"]}])
    again = _plan(exits=[{"symbol": "ZZEX", "date": "2026-10-30", "stressed_groups": ["Technology"]}])
    assert [p["trigger_id"] for p in plans] == [p["trigger_id"] for p in again]  # stable across runs
    done = {F.applied_key(p) for p in plans}
    receipts = F.apply_memory(again, root=tmp_path, done=done)
    assert all(r.get("skipped") == "already applied" for r in receipts) and calls == []


# --------------------------------------------------------------------------- R6 ledger before apply + daily cap


def _fan_plan(tmp_path, prev=None):
    import scripts.market_risk_rotation as rot

    now = datetime(2026, 10, 30, 20, 0, tzinfo=UTC)
    trigs = [{"kind": "reentry_flip", "key": "ZZEX", "from": "RE_ENTER_IF", "to": "RE_ENTER", "id": "mrt_r1"}]
    research = F.plan_research(
        trigs,
        groups={},
        tiers_by_group={},
        policy=POLICY,
        brave_status={"daily_limit": 100, "daily_used": 0},
        used_today=((prev or {}).get("days") or {}).get(rot.ledger_day(now)),
    )
    return (
        rot,
        now,
        {
            "triggers": trigs,
            "research": research,
            "memory": [],
            "state": {"tier": "ORANGE"},
            "state_file": str(tmp_path / "rotation_fanout_state.json"),
            "prev": prev or {},
            "day": rot.ledger_day(now),
        },
    )


def test_ledger_is_written_before_any_apply(monkeypatch, tmp_path):
    rot, now, plan = _fan_plan(tmp_path)
    seen = {}

    def fake_mem(plans, root=None, done=None):
        seen["at_memory"] = json.loads((tmp_path / "rotation_fanout_state.json").read_text())
        return []

    def fake_res(plan_, conn_factory, policy):
        raise RuntimeError("crash mid-apply")

    monkeypatch.setattr(F, "apply_memory", fake_mem)
    monkeypatch.setattr(F, "apply_research", fake_res)
    with pytest.raises(RuntimeError):
        rot.apply_fanout(plan, POLICY, now, conn_factory=lambda: None)
    led = json.loads((tmp_path / "rotation_fanout_state.json").read_text())
    assert seen["at_memory"]["status"] == "claimed" and "mrt_r1" in led["trigger_ids"]
    assert led["days"]["2026-10-30"]["hermes"] == 1 and led["days"]["2026-10-30"]["brave"] == 1


def test_hermes_daily_cap_is_per_day_across_runs(tmp_path):
    cap = int(POLICY["leadership"]["fanout"]["hermes"]["daily_cap"])
    rot, now, plan = _fan_plan(tmp_path, prev={"days": {"2026-10-30": {"hermes": cap, "brave": 0}}})
    assert plan["research"]["hermes"] == [] and plan["research"]["hermes_cap_applied"] == 0
    rot, now, plan = _fan_plan(tmp_path, prev={"days": {"2026-10-29": {"hermes": cap, "brave": 0}}})
    assert len(plan["research"]["hermes"]) == 1  # yesterday's count never spends today's cap
