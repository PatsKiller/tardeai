"""LQ-20261107-369: WP6 outcomes reads ``plan_stamp`` from market_event_candidates.plan, but WP3 computed the plan
at read time and never wrote it — so outcomes could only score the ``first_seen`` basis. This pins the persist:
a deterministic, idempotent snapshot written once per state change, keyed by account LABEL and carrying no account
number. Synthetic fixtures only (SYNTH_* symbols, a generic account label, invented cash).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scripts.lib import market_event_api as api
from scripts.lib import market_event_outcomes as outcomes
from scripts.lib import market_event_plan as mep
from scripts.lib import market_event_plan_stamp as stamp

ROOT = Path(__file__).resolve().parents[1]
POL = mep._merge(mep.DEFAULT_POLICY, {})
NOW = datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=30)
INTERNAL_KEY = "SYNTHKEY-123456789"  # the account key that must never reach the stored document


# ------------------------------------------------------------------ fixtures
def _bars(closes, vols=None, start=date(2026, 8, 1)):
    return [{"date": (start + timedelta(days=i)).isoformat(), "open": c, "high": c * 1.01, "low": c * 0.99,
             "close": c, "volume": vols[i] if vols else 1_000_000} for i, c in enumerate(closes)]


def _based():
    """A fall to a low, then five sessions without a new low, rising closes, rising volume (READY shape)."""
    closes = [100.0 - 1.5 * i for i in range(32)] + [54.0, 54.5, 55.5, 56.5, 58.0]
    return _bars(closes, [1_000_000] * 32 + [1_500_000] * 5)


def _snapshot():
    hist = [{"as_of": f"2026-11-0{6 + i}T15:00:00+00:00", "score": s, "tier": t}
            for i, (s, t) in enumerate(zip((70.0, 66.0, 62.0), ("RED", "RED", "ORANGE")))]
    cats = [{"category": k, "state": st} for k, st in zip(("options_flow", "breadth", "extended_hours"),
                                                          ("CALM", "WARN", "CALM"))]
    return {"schema": "MarketRiskSnapshot@v1", "as_of": "2026-11-08T14:00:00+00:00", "tier": "ORANGE", "score": 62.0,
            "mode": "live", "history": hist, "categories": cats}


class FakeDB:
    def __init__(self, tables):
        self.t = tables

    def __call__(self, sql, params=None):
        s = sql.lower()
        for name, rows in self.t.items():
            if f"from {name}" in s:
                return rows
        return []


HOLD = [{"account": INTERNAL_KEY, "is_cash": True, "market_value": 30_000.0},
        {"account": INTERNAL_KEY, "symbol": "SYNTH_H", "market_value": 170_000.0}]


def _active_db(closes_last=58.0):
    bars = [{"symbol": "SYNTH_B", "bar_time": b["date"],
             **{k: b[k] for k in ("open", "high", "low", "close", "volume")}} for b in _based()]
    shift = (NOW.date() - timedelta(days=1)) - date.fromisoformat(bars[-1]["bar_time"])
    for b in bars:
        b["bar_time"] = (date.fromisoformat(b["bar_time"]) + shift).isoformat()
    return FakeDB({
        "market_event_episodes": [{"episode_id": "E1", "state": "OPEN", "opened_at": "2026-11-05T14:00:00+00:00"}],
        "market_event_candidates": [{"episode_id": "E1", "symbol": "SYNTH_B", "rank": 1, "state": "WATCH",
                                     "last_price": closes_last, "quality_score": 0.7, "discount_score": 0.4,
                                     "reason_evidence": {"sector": "Technology"},
                                     "updated_at": "2026-11-08T13:00:00+00:00"}],
        "market_quotes": bars,
        "trade_transactions": [],
    })


def _active_doc(closes_last=58.0):
    return api.build_active(db_query=_active_db(closes_last), snapshot=_snapshot(), holdings_rows=HOLD,
                            label=lambda k: "Brokerage A", facts=lambda r: {"account_type": "taxable"},
                            taxable=lambda a: True, policy=POL, now=NOW)


def _candidate(state="READY", ready=2, price=58.0, label="Brokerage A", usd=1_000.0, invalidation=52.0):
    return {"symbol": "SYNTH_B", "state": state, "tranches_ready": ready, "last_price": price,
            "plan": {"tranche": ready or None, "invalidation": invalidation, "risk_usd": 120.0,
                     "risk_budget_usd": 500.0,
                     "tranches": [{"n": i, "pct": 30.0, "account_label": label, "shares": 10, "usd": usd * i,
                                   "entry_low": 57.0 - i, "entry_high": 59.0 + i, "condition": "gate",
                                   "status": "ready"} for i in range(1, (ready or 0) + 1)]}}


class FakeConn:
    """Records the UPDATEs. ``rowcounts`` is the sequence each execute() reports (default: 1)."""

    def __init__(self, rowcounts=None):
        self.rowcounts = list(rowcounts or [])
        self.calls = []
        self._i = 0

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.last_rowcount = self.rowcounts[self._i] if self._i < len(self.rowcounts) else 1
        self._i += 1

    @property
    def rowcount(self):
        return self.last_rowcount


# ------------------------------------------------------------------ the shape the consumers hand in
def test_the_active_view_feeds_the_stamp():
    """The stamp reads the same document /active renders — if the shapes drift, this fails before the lane does."""
    doc = _active_doc()
    c = doc["candidates"][0]
    assert c["state"] == "READY" and c["tranches_ready"] == 2
    s = stamp.build_stamp(c, NOW, previous=None, episode_id="E1")
    assert s is not None and s["ready"] == [1, 2] and s["tranche"] == 2
    assert s["symbol"] == "SYNTH_B" and s["episode_id"] == "E1"
    assert s["usd_by_account"] == {"Brokerage A": s["usd_by_account"]["Brokerage A"]}
    assert isinstance(s["invalidation"], float) and len([z for z in s["entry_zone"] if z is not None]) == 2
    legs = {t["tranche"]: t for t in s["tranches"]}
    assert legs[1]["ready_at"] == legs[2]["ready_at"] == NOW.isoformat()
    assert legs[1]["price"] == 58.0 and legs[1]["pct"] == 30.0


def test_no_account_number_reaches_the_document():
    doc = _active_doc()
    s = stamp.build_stamp(doc["candidates"][0], NOW, previous=None, episode_id="E1")
    text = json.dumps(s, sort_keys=True)
    assert INTERNAL_KEY not in text
    assert "SYNTHKEY" not in text
    assert "account_id" not in text and "account_key" not in text


# ------------------------------------------------------------------ determinism / idempotence
def test_a_candidate_that_was_never_ready_is_not_stamped():
    assert stamp.build_stamp(_candidate(state="WATCH", ready=0), NOW) is None
    assert stamp.build_stamp({"symbol": "", "state": "READY", "tranches_ready": 1}, NOW) is None


def test_the_same_state_and_ready_set_is_a_no_op_even_with_moving_prices():
    first = stamp.build_stamp(_candidate(), NOW, episode_id="E1")
    later = stamp.build_stamp(_candidate(price=61.5, usd=1_400.0), LATER, previous=first, episode_id="E1")
    assert later is None, "a second run inside the same state must not rewrite the snapshot"
    conn = FakeConn()
    assert stamp.write_plan_stamps(conn, [{"episode_id": "E1", "symbol": "SYNTH_B", "plan": first}]) == 1
    assert stamp.write_plan_stamps(conn, []) == 0


def test_the_document_is_byte_identical_when_rebuilt_from_its_own_inputs():
    a = stamp.build_stamp(_candidate(), NOW, episode_id="E1")
    b = stamp.build_stamp(_candidate(), NOW, episode_id="E1")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["state_since"] == a["stamp_at"] == NOW.isoformat()


def test_a_new_tranche_stamps_again_and_keeps_the_earlier_tranches_clock():
    t1 = stamp.build_stamp(_candidate(ready=1), NOW, episode_id="E1")
    assert [t["tranche"] for t in t1["tranches"]] == [1]
    t2 = stamp.build_stamp(_candidate(ready=2, price=60.0), LATER, previous=t1, episode_id="E1")
    assert t2 is not None and t2["ready"] == [1, 2] and t2["tranche"] == 2
    legs = {t["tranche"]: t for t in t2["tranches"]}
    assert legs[1]["ready_at"] == NOW.isoformat() and legs[1]["price"] == 58.0   # first tranche keeps its clock
    assert legs[2]["ready_at"] == LATER.isoformat() and legs[2]["price"] == 60.0  # new tranche starts now
    assert t2["state_since"] == NOW.isoformat(), "the state itself did not change"


def test_entering_does_not_reset_the_signal_clock():
    """READY -> ENTERED is the operator recording an entry, not a new signal: the tranche's ready_at must not move."""
    ready = stamp.build_stamp(_candidate(ready=2), NOW, episode_id="E1")
    entered = stamp.build_stamp(_candidate(state="ENTERED", ready=2, price=61.0), LATER, previous=ready,
                                episode_id="E1")
    assert entered is not None and entered["state"] == "ENTERED" and entered["state_since"] == LATER.isoformat()
    assert [t["ready_at"] for t in entered["tranches"]] == [NOW.isoformat(), NOW.isoformat()]
    assert stamp.build_stamp(_candidate(state="ENTERED", ready=2, price=61.0), LATER, previous=entered,
                             episode_id="E1") is None


def test_falling_back_to_watch_keeps_the_ready_leg_as_history():
    ready = stamp.build_stamp(_candidate(ready=2), NOW, episode_id="E1")
    watch = stamp.build_stamp(_candidate(state="WATCH", ready=0), LATER, previous=ready, episode_id="E1")
    assert watch is not None and watch["state"] == "WATCH" and watch["ready"] == []
    assert watch["tranche"] is None and watch["usd_by_account"] == {}
    legs = {t["tranche"]: t for t in watch["tranches"]}
    assert legs[1]["active"] is False and legs[1]["ready_at"] == NOW.isoformat()
    assert watch["invalidation"] == 52.0, "the invalidation the state machine reads back must survive"
    assert stamp.build_stamp(_candidate(state="WATCH", ready=0), LATER, previous=watch, episode_id="E1") is None


def test_an_unreadable_plan_block_does_not_erase_the_signal():
    """No holdings file means no dollars — but the READY tranche is still a signal WP6 can score."""
    c = {"symbol": "SYNTH_B", "state": "READY", "tranches_ready": 1, "last_price": 58.0, "plan": None}
    s = stamp.build_stamp(c, NOW, episode_id="E1")
    assert s is not None and s["ready"] == [1] and s["usd_by_account"] == {}
    assert s["tranches"][0]["ready_at"] == NOW.isoformat() and s["tranches"][0]["price"] == 58.0


# ------------------------------------------------------------------ the writer
def test_the_update_is_guarded_and_reports_changed_rows():
    conn = FakeConn(rowcounts=[1, 0])
    rows = [{"episode_id": "E1", "symbol": "syntH_b", "plan": {"schema": stamp.STAMP_SCHEMA}},
            {"episode_id": "E1", "symbol": "SYNTH_C", "plan": {"schema": stamp.STAMP_SCHEMA}}]
    assert stamp.write_plan_stamps(conn, rows) == 1
    sql, params = conn.calls[0]
    assert "IS DISTINCT FROM %s::jsonb" in sql and "updated_at = now()" in sql
    assert "SET plan = %s::jsonb" in sql and "UPDATE market_event_candidates" in sql
    assert params[1] == "E1" and params[2] == "SYNTH_B", "the symbol is normalised and keyed, never interpolated"
    assert params[0] == params[3] == json.dumps(rows[0]["plan"], sort_keys=True)
    assert "state" not in sql.split("WHERE")[0].replace("market_event_candidates", "")


# ------------------------------------------------------------------ the consumer this unblocks
def _signals(plan):
    episode = {"episode_id": "E1", "baseline_date": date(2026, 11, 5)}
    rows = [{"symbol": "SYNTH_B", "state": "READY", "plan": plan, "baseline_price": 60.0, "last_price": 58.0}]
    closes = {"SYNTH_B": {date(2026, 11, 5): 60.0, date(2026, 11, 6): 58.0, date(2026, 11, 9): 59.0,
                          date(2026, 11, 10): 61.0}}
    sessions = outcomes.weekday_calendar(date(2026, 11, 2), date(2026, 12, 4))
    return outcomes.build_signals(episode, rows, closes, sessions, NOW), closes, sessions


def test_outcomes_scores_the_persisted_stamp_as_the_plan_stamp_basis():
    s = stamp.build_stamp(_candidate(ready=2), NOW, episode_id="E1")
    (rows, skipped), closes, sessions = _signals(s)
    scored = outcomes.score_rows(rows, closes, sessions, NOW.date())
    ready = {r["signal"]: r for r in scored if r["signal"].startswith("READY")}
    assert set(ready) == {"READY_t1", "READY_t2"}
    assert all(r["signal_basis"] == "plan_stamp" for r in ready.values())
    assert ready["READY_t1"]["signal_at"] == NOW and ready["READY_t1"]["price"] == 58.0
    assert ready["READY_t1"]["price_source"] == "plan_price"
    assert ready["READY_t1"]["anchor_session"] == date(2026, 11, 6)   # Sunday 10:00 ET anchors to Friday's close
    assert ready["READY_t1"]["ret_5"] is None                        # horizon not reached, never a fabricated 0
    assert skipped == {}


def test_without_a_stamp_outcomes_still_falls_back_to_first_seen():
    (rows, _), _, _ = _signals(None)
    ready = {r["signal"]: r for r in rows if r["signal"].startswith("READY")}
    assert set(ready) == {"READY_t1"} and ready["READY_t1"]["signal_basis"] == "first_seen"


# ------------------------------------------------------------------ the lane step
def test_persist_dry_run_builds_every_stamp_and_writes_nothing(tmp_path):
    holds = tmp_path / "holdings.json"
    holds.write_text(json.dumps({"holdings": HOLD}))
    conn = FakeConn()
    s = stamp.persist_for_connection(conn=conn, db_query=_active_db(), snapshot=_snapshot(), holdings_path=holds,
                                     policy=POL, now=NOW, apply=False)
    assert s["error"] is None, s["error"]
    assert (s["candidates"], s["ready"], s["would_change"], s["changed"]) == (1, 1, 1, 0)
    assert conn.calls == [], "a dry run must not execute a single UPDATE"


def test_persist_apply_writes_one_guarded_update(tmp_path):
    holds = tmp_path / "holdings.json"
    holds.write_text(json.dumps({"holdings": HOLD}))
    conn = FakeConn(rowcounts=[1])
    s = stamp.persist_for_connection(conn=conn, db_query=_active_db(), snapshot=_snapshot(), holdings_path=holds,
                                     policy=POL, now=NOW, apply=True)
    assert s["error"] is None and s["changed"] == 1 and len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "IS DISTINCT FROM" in sql and params[1] == "E1" and params[2] == "SYNTH_B"
    stored = json.loads(params[0])
    assert stored["schema"] == stamp.STAMP_SCHEMA and stored["state"] == "READY"
    assert INTERNAL_KEY not in params[0] and "SYNTHKEY" not in params[0], "the account label is the only identifier"


def test_a_missing_holdings_file_degrades_to_no_dollars_not_an_error(tmp_path):
    conn = FakeConn()
    s = stamp.persist_for_connection(conn=conn, db_query=_active_db(), snapshot=_snapshot(),
                                     holdings_path=tmp_path / "absent.json", policy=POL, now=NOW, apply=False)
    assert s["error"] is None and s["ready"] == 1 and s["would_change"] == 1


# ------------------------------------------------------------------ wiring
def test_the_stamp_lane_is_the_writer():
    """A stamp function with no caller is a dead lane: the lane must call it, in both modes."""
    src = (ROOT / "scripts" / "market_event_plan_stamp.py").read_text()
    assert "persist_for_connection" in src
    assert 'mode.add_argument("--apply"' in src and 'default=True' in src, "dry run is the default mode"
    assert 'write_lane_receipt' in src, "an apply run must leave a receipt"


def test_the_stamp_lane_is_not_wired_into_another_authors_lane():
    """scripts/market_event_detect.py is held by cc-opus-3; the persist is its own lane, not a hook in theirs."""
    src = (ROOT / "scripts" / "market_event_detect.py").read_text()
    assert "market_event_plan_stamp" not in src
