"""Learning loop PR1 (operator 2026-10-21): stable recommendation ids, trade linkage, R-multiple attribution.

Operator, verbatim: "Approve learning-loop plan and begin PR1 immediately. Stable recommendation IDs, trade linkage,
and R-multiple attribution provide the highest long-term value and should be implemented before calibration."

  1. rec_id determinism — every source; a CIO opportunity keeps its rec_id across versions while its plan is
     unchanged, gets a new one when a level moves or the plan comes back, and the backfill (from_jsonl) and the
     curator hook compute the same id.
  2. registry writer — SAVEPOINT-guarded upsert, never raises into the caller (table absent before the migration),
     kill switch; the curator hook runs on --apply only and never fails curation.
  3. linker matching — exact / zone / window_only / none (operator_initiated, explicit), active window + grace,
     direction, tie-breaks.
  4. R math — longs, shorts, missing stop (journal fallback, then null with a reason), wrong-side stop, planned R:R,
     target/stop hit.
  5. API shape — /api/v2/journal attaches rec_id, source, confidence, plan entry/stop/target, R achieved, planned R:R;
     'unavailable' (never a guess) before the migration.
  6. dry run is a READ ONLY session and writes nothing; --apply refuses without the migration.
  7. the migration is additive (no DROP / DELETE / TRUNCATE; the down file archives by rename).

Hermetic: fake cursors and connections, temp files. No database, no network, no broker.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import recommendation_registry as reg  # noqa: E402
from scripts.lib import trade_recommendation_linkage as lk  # noqa: E402

@pytest.fixture(autouse=True)
def _stub_psycopg2(monkeypatch):
    """CI has no psycopg2. The writers import psycopg2.extras lazily (RealDictCursor, execute_values) and every
    test hands them a fake connection, so a stub module keeps these tests hermetic on any runner."""
    import types

    pg = types.ModuleType("psycopg2")
    pg.extras = types.ModuleType("psycopg2.extras")
    pg.extras.RealDictCursor = object
    pg.extras.execute_values = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", pg.extras)


T0 = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)


def _version(sym, v, at, run_id, zone=(89.1, 92.0), stop=86.0, target=100.0, conviction=60.0, rank=10):
    rr = {"entry_ref": 90.8 if zone else None, "entry_zone": list(zone) if zone else None, "invalidation_level": stop,
          "primary_target": target, "targets": [{"px": target, "primary": True}]}
    return {"schema": "OpportunityAssessmentVersion@v1", "symbol": sym, "version": v, "written_at": at.isoformat(),
            "assessment": {"symbol": sym, "conviction": conviction, "rank": rank, "stance": "WATCH",
                           "risk_reward": rr}, "change_reasons": ["x"],
            "provenance": {"writer": "cio_opportunity_curator", "run_id": run_id}}


# ── 1. rec_id determinism ─────────────────────────────────────────────────────────────────────────────────────────
def test_rec_id_is_deterministic_and_source_scoped():
    a = reg.rec_id_for("paper_trade_proposal", "123")
    assert a == reg.rec_id_for("paper_trade_proposal", "123")
    assert a.startswith("rec_") and len(a) == 24
    assert a != reg.rec_id_for("scalp_alert", "123")
    with pytest.raises(ValueError):
        reg.rec_id_for("made_up", "1")


def test_opportunity_rec_id_is_stable_while_the_plan_is_unchanged():
    lin = reg.OpportunityLineage()
    r1 = lin.feed(_version("XMTR", 1, T0, "opp-A"))
    r2 = lin.feed(_version("XMTR", 2, T0 + timedelta(hours=3), "opp-B", conviction=70, rank=5))   # rank/conv only
    assert r1 == r2
    rec = lin.recs[r1]
    assert rec["first_seen_run_id"] == "opp-A" and rec["conviction_at_issue"] == 60.0       # conviction AT ISSUE
    assert rec["last_seen_at"] == T0 + timedelta(hours=3)
    assert rec["expires_at"] == rec["last_seen_at"] + reg.TTL["cio_opportunity"]
    # 90.8 vs 90.80 must not split a plan
    assert reg.plan_key("X", {"entry_low": 90.8, "entry_high": 92, "plan_stop": 86, "plan_target": 100}) == \
        reg.plan_key("x", {"entry_low": 90.80, "entry_high": 92.0, "plan_stop": 86.0, "plan_target": 100.0})


def test_opportunity_level_move_supersedes_and_a_returning_plan_is_a_new_rec():
    lin = reg.OpportunityLineage()
    r1 = lin.feed(_version("XMTR", 1, T0, "opp-A"))
    t_move = T0 + timedelta(days=2)
    r2 = lin.feed(_version("XMTR", 2, t_move, "opp-B", stop=84.0))
    assert r2 != r1
    assert lin.recs[r1]["superseded_at"] == t_move and lin.recs[r1]["expires_at"] == t_move
    r3 = lin.feed(_version("XMTR", 3, T0 + timedelta(days=3), "opp-C"))       # the old plan comes back
    assert r3 not in (r1, r2)
    assert lin.feed(_version("XMTR", 4, T0 + timedelta(days=4), "opp-D", zone=None)) is None   # no plan → no rec
    assert lin.recs[r3]["superseded_at"] == T0 + timedelta(days=4)


def test_backfill_and_hook_compute_the_same_ids(tmp_path):
    lines = [_version("AAA", 1, T0, "opp-1"), _version("BBB", 1, T0, "opp-1", zone=(10, 11), stop=9, target=14),
             _version("AAA", 2, T0 + timedelta(hours=1), "opp-2", rank=99)]
    p = tmp_path / "hist.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    from_file = reg.OpportunityLineage.from_jsonl(p)
    live = reg.OpportunityLineage()
    for x in lines:
        live.feed(x)
    assert sorted(from_file.recs) == sorted(live.recs) and len(from_file.recs) == 2
    assert reg.opportunity_rec_id("AAA", reg.opportunity_plan(lines[0]["assessment"]), "opp-1") in from_file.recs


def test_db_source_mappers():
    p = reg.proposal_rec({"id": 77, "symbol": "mcd", "side": "short", "created_at": T0, "proposed_entry": 255.09,
                          "proposed_stop": 262.0, "proposed_target1": 240.0, "final_entry": None,
                          "max_expires_at": T0 + timedelta(days=3), "confidence_score": 0.7, "status": "EXPIRED"})
    assert p["rec_id"] == reg.rec_id_for("paper_trade_proposal", "77") and p["direction"] == "short"
    assert p["symbol"] == "MCD" and p["entry_low"] == p["entry_high"] == 255.09 and p["plan_stop"] == 262.0
    assert p["expires_at"] == T0 + timedelta(days=3) and p["conviction_at_issue"] == 0.7
    p2 = reg.proposal_rec({"id": 78, "symbol": "X", "created_at": T0, "proposed_entry": 10, "final_entry": 10.5})
    assert p2["entry_low"] == 10.5 and p2["direction"] == "long" and p2["expires_at"] == T0 + reg.TTL["paper_trade_proposal"]
    s = reg.scalp_rec({"id": 5, "symbol": "PL", "scanned_at": T0, "price": 17.6, "score": 41, "decision": "GO"},
                      "trade_ai_scans")
    assert s["source_id"] == "trade_ai_scans:5" and s["plan_stop"] is None and s["expires_at"] == T0 + timedelta(days=1)
    assert reg.scalp_rec({"id": 6, "symbol": "PL", "scanned_at": T0, "price": None}, "trade_ai_scans") is None
    a = reg.alert_rec({"alert_uid": "u1", "alert_type": "entry_alert", "symbol": "AAA", "price": 10, "stop_price": 9,
                       "created_at": T0, "parsed_payload": json.dumps({"target": 13})})
    assert a["rec_id"] == reg.rec_id_for("entry_alert", "u1") and a["plan_target"] == 13.0
    assert reg.alert_rec({"alert_uid": "u2", "alert_type": "data_staleness", "symbol": "AAA", "price": 10,
                          "created_at": T0}) is None


# ── 2. registry writer ────────────────────────────────────────────────────────────────────────────────────────────
class FakeCur:
    def __init__(self, fail_on=None):
        self.sql: list[str] = []
        self.fail_on = fail_on
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError('relation "recommendation_registry" does not exist')

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_execute_values(monkeypatch):
    import psycopg2.extras

    calls = []

    def ev(cur, sql, rows, page_size=100):
        calls.append((sql, list(rows)))
        cur.execute(sql)
        cur.rowcount = len(rows)
    monkeypatch.setattr(psycopg2.extras, "execute_values", ev)
    return calls


def test_upsert_is_savepoint_guarded_and_never_raises(fake_execute_values):
    lin = reg.OpportunityLineage()
    lin.feed(_version("AAA", 1, T0, "r1"))
    lin.feed(_version("AAA", 2, T0 + timedelta(days=1), "r2", stop=80))
    recs = lin.rows()
    cur = FakeCur()
    res = reg.upsert_recs(cur, recs)
    assert res["status"] == "ok" and res["offered"] == 2
    assert cur.sql[0] == "SAVEPOINT rec_registry_upsert" and cur.sql[-1] == "RELEASE SAVEPOINT rec_registry_upsert"
    assert any(s.startswith("UPDATE recommendation_registry SET expires_at") for s in cur.sql)   # the superseded one
    sql, rows = fake_execute_values[0]
    assert "ON CONFLICT (rec_id) DO UPDATE" in sql and "conviction_at_issue =" not in sql.split("DO UPDATE")[1]
    assert len(rows[0]) == len(reg.COLUMNS)
    bad = FakeCur(fail_on="INSERT INTO recommendation_registry")
    res = reg.upsert_recs(bad, recs)
    assert res["status"] == "skipped" and "does not exist" in res["error"]
    assert "ROLLBACK TO SAVEPOINT rec_registry_upsert" in bad.sql


def test_kill_switch(monkeypatch, fake_execute_values):
    monkeypatch.setenv(reg.KILL_SWITCH_ENV, "0")
    cur = FakeCur()
    assert reg.upsert_recs(cur, [{"rec_id": "x"}])["status"] == "disabled" and cur.sql == []


class FakeConn:
    def __init__(self, cur=None):
        self.cur = cur or FakeCur()
        self.commits = 0
        self.rollbacks = 0
        self.readonly = None

    def cursor(self, cursor_factory=None):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def set_session(self, readonly=None):
        self.readonly = readonly


def test_curator_hook_registers_changed_and_confirmed_plans(tmp_path, fake_execute_values):
    p = tmp_path / "hist.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        _version("AAA", 1, T0, "r1"), _version("BBB", 1, T0, "r1", zone=(5, 6), stop=4, target=9),
        _version("CCC", 1, T0, "r1", zone=(1, 2), stop=0.5, target=3)]) + "\n", encoding="utf-8")
    conn = FakeConn()
    now = T0 + timedelta(days=1)
    res = reg.register_opportunities_after_curation(conn, p, current_symbols=["AAA", "BBB"], changed_symbols=["CCC"],
                                                    at=now)
    assert res["status"] == "ok" and res["confirmed"] == 2 and conn.commits == 1
    rows = fake_execute_values[0][1]
    syms = sorted(r[reg.COLUMNS.index("symbol")] for r in rows)
    assert syms == ["AAA", "BBB", "CCC"]
    aaa = next(r for r in rows if r[reg.COLUMNS.index("symbol")] == "AAA")
    assert aaa[reg.COLUMNS.index("expires_at")] == now + reg.TTL["cio_opportunity"]


def test_curator_calls_the_hook_on_apply_only_and_it_never_fails_curation(monkeypatch):
    import cio_opportunity_curator as cur

    src = (ROOT / "scripts/cio_opportunity_curator.py").read_text(encoding="utf-8")
    body = src.split("def run(", 1)[1]
    assert "register_recommendations(" not in body.split("    if apply:", 1)[0]
    assert "register_recommendations(store, assessments, lines)" in body.split("    if apply:", 1)[1]

    class S:
        event_path = Path("/nonexistent/hist.jsonl")
    import scripts.lib.recommendation_registry as r

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(r, "register_opportunities_after_curation", boom)
    import db_adapter

    monkeypatch.setattr(db_adapter, "_get_conn", lambda: FakeConn())   # tests never touch the live DB (§24.6)
    out = cur.register_recommendations(S(), [{"symbol": "A"}], [])
    assert out["status"] == "error" and "db down" in out["error"]


# ── 3. linker matching ────────────────────────────────────────────────────────────────────────────────────────────
def _rec(rid, lo, hi, created=T0, days=5, sym="AAA", direction="long", stop=None, target=None, source="paper_trade_proposal"):
    return {"rec_id": rid, "source": source, "symbol": sym, "direction": direction, "entry_low": lo, "entry_high": hi,
            "plan_stop": stop, "plan_target": target, "created_at": created, "expires_at": created + timedelta(days=days)}


def _trade(px, at=T0 + timedelta(days=1), sym="AAA", exit_px=None, journal_stop=None):
    return {"round_trip_key": f"acct|{sym}|{at.isoformat()}", "round_trip_id": 1, "symbol": sym, "account": "acct",
            "entry_time": at, "exit_time": at + timedelta(days=2), "entry_price": px,
            "exit_price": exit_px if exit_px is not None else px, "qty": 10, "journal_stop": journal_stop}


@pytest.mark.parametrize("px,expected", [
    (100.0, "exact"),            # inside the zone
    (99.0, "exact"),             # zone edge
    (97.5, "zone"),              # 1.5% below the low edge
    (106.0, "window_only"),      # 4.95% above the high edge
    (115.0, None),               # 13.9% away: not plausible
])
def test_confidence_tiers(px, expected):
    m = lk.match_trade(_trade(px), [_rec("r1", 99.0, 101.0)])
    assert (m["confidence"] if m else None) == expected


def test_single_price_zone_is_widened_for_exact():
    assert lk.match_trade(_trade(10.04), [_rec("r", 10.0, 10.0)])["confidence"] == "exact"    # within 0.5%
    assert lk.match_trade(_trade(10.15), [_rec("r", 10.0, 10.0)])["confidence"] == "zone"


def test_window_grace_symbol_and_direction():
    rec = _rec("r1", 99, 101, days=2)
    assert lk.match_trade(_trade(100, at=T0 - timedelta(minutes=1)), [rec]) is None            # before issue
    assert lk.match_trade(_trade(100, at=T0 + timedelta(days=2, hours=20)), [rec])["confidence"] == "exact"   # grace
    assert lk.match_trade(_trade(100, at=T0 + timedelta(days=3, hours=1)), [rec]) is None       # past grace
    assert lk.match_trade(_trade(100, sym="BBB"), [rec]) is None
    assert lk.match_trade(_trade(100), [_rec("s", 99, 101, direction="short")]) is None          # a short call ≠ a buy


def test_best_match_prefers_confidence_then_distance_then_recency():
    far = _rec("far", 90, 91)
    near = _rec("near", 99, 100.5, created=T0)
    newer = _rec("newer", 99, 100.5, created=T0 + timedelta(hours=1))
    m = lk.match_trade(_trade(100), [far, near, newer])
    assert m["rec"]["rec_id"] == "newer" and m["candidates"] == 3 and m["confidence"] == "exact"


def test_unmatched_trade_is_operator_initiated_explicitly():
    row = lk.attribute(_trade(50), None)
    assert row["origin"] == "operator_initiated" and row["link_confidence"] == "none" and row["rec_id"] is None
    assert row["r_multiple"] is None and row["r_null_reason"] == "operator_initiated_no_journal_stop"
    assert row["stop_source"] == "none" and row["link_method"] == lk.LINK_METHOD
    rows = lk.link_all([_trade(100), _trade(50, sym="ZZZ")], [_rec("r1", 99, 101, stop=95, target=110)])
    assert [r["origin"] for r in rows] == ["recommendation", "operator_initiated"]


# ── 4. R math ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_r_multiple_long_short_and_missing_stop():
    assert lk.r_multiple(100, 110, 95) == (2.0, None)
    assert lk.r_multiple(100, 97.5, 95) == (-0.5, None)
    assert lk.r_multiple(100, 90, 105, "short") == (2.0, None)
    assert lk.r_multiple(100, 102.5, 105, "short") == (-0.5, None)
    assert lk.r_multiple(100, 110, None) == (None, "no_stop")
    assert lk.r_multiple(100, 110, 101) == (None, "stop_on_wrong_side_of_entry")
    assert lk.r_multiple(100, 90, 99, "short") == (None, "stop_on_wrong_side_of_entry")


def test_planned_rr_and_hits():
    assert lk.planned_rr(99, 101, 95, 115) == 3.0
    assert lk.planned_rr(100, 100, 105, 85, "short") == 3.0
    assert lk.planned_rr(100, 100, None, 110) is None
    assert lk.hits(115, 95, 115) == (True, False)
    assert lk.hits(94, 95, 115) == (False, True)
    assert lk.hits(84, 105, 85, "short") == (True, False)
    assert lk.hits(100, None, None) == (None, None)


def test_attribution_uses_linked_stop_then_journal_stop():
    rec = _rec("r1", 99, 101, stop=95, target=115)
    t = _trade(100, exit_px=110, journal_stop=90)
    row = lk.attribute(t, lk.match_trade(t, [rec]))
    assert row["r_multiple"] == 2.0 and row["stop_source"] == "recommendation" and row["planned_rr"] == 3.0
    assert row["target_hit"] is False and row["stop_hit"] is False and row["hit_basis"] == "exit_price"
    no_stop = _rec("r2", 99, 101)
    row = lk.attribute(t, lk.match_trade(t, [no_stop]))
    assert row["r_multiple"] == 1.0 and row["stop_source"] == "journal"
    t2 = _trade(100, exit_px=110)
    row = lk.attribute(t2, lk.match_trade(t2, [no_stop]))
    assert row["r_multiple"] is None and row["r_null_reason"] == "no_linked_or_journal_stop"
    own = lk.attribute(t, None)
    assert own["origin"] == "operator_initiated" and own["r_multiple"] == 1.0 and own["stop_source"] == "journal"


# ── 5. API shape ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_attach_recommendation_links_shape():
    trades = [{"symbol": "AAA", "dedupe_key": "srt:1"}, {"symbol": "BBB", "dedupe_key": "srt:2"},
              {"symbol": "CCC", "dedupe_key": None}]
    seen = {}

    def q(sql, params=None, fetch="all"):
        seen["sql"], seen["params"] = sql, params
        return [{"trade_dedupe_key": "srt:1", "rec_id": "rec_x", "rec_source": "cio_opportunity",
                 "link_confidence": "exact", "origin": "recommendation", "plan_entry_low": 1, "plan_entry_high": 2,
                 "plan_stop": 0.5, "plan_target": 3, "r_multiple": 1.5, "r_null_reason": None, "planned_rr": 2.0,
                 "target_hit": False, "stop_hit": False, "stop_source": "recommendation", "linked_at": "2026-10-21",
                 "conviction_at_issue": 61.0, "rec_issued_at": "2026-10-08"}]
    assert lk.attach_recommendation_links(trades, q) == "ok"
    assert seen["params"] == (["srt:1", "srt:2"],)
    blk = trades[0]["recommendation"]
    for k in ("rec_id", "rec_source", "link_confidence", "origin", "plan_entry_low", "plan_entry_high", "plan_stop",
              "plan_target", "r_achieved", "planned_rr"):
        assert k in blk, k
    assert blk["r_achieved"] == 1.5 and "r_multiple" not in blk and isinstance(blk["plan_stop"], float)
    assert trades[1]["recommendation"] is None and trades[2]["recommendation"] is None


def test_attach_is_unavailable_never_a_guess():
    trades = [{"dedupe_key": "srt:1"}]

    def boom(*a, **k):
        raise RuntimeError('relation "trade_recommendation_links" does not exist')
    assert lk.attach_recommendation_links(trades, boom) == "unavailable" and trades[0]["recommendation"] is None
    assert lk.attach_recommendation_links(trades, lambda *a, **k: None) == "unavailable"


def test_journal_endpoint_wires_the_link():
    src = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    body = src.split("\ndef journal():", 1)[1].split("\ndef ", 1)[0]
    assert "tc.dedupe_key" in body
    assert "attach_recommendation_links(trades, _db_query)" in body
    assert '"recommendation_link_status": rec_link_status' in body


# ── 6. dry run writes nothing; apply refuses without the migration ───────────────────────────────────────────────
class DictCur(FakeCur):
    def __init__(self, tables_exist=False):
        super().__init__()
        self.tables_exist = tables_exist
        self._last = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if "to_regclass" in sql:
            self._last = [{"ok": self.tables_exist}]
        elif "FROM schwab_round_trips" in sql:
            self._last = [{"round_trip_id": 1, "round_trip_key": "k1", "account": "a", "symbol": "AAA",
                           "entry_time": T0 + timedelta(days=1), "exit_time": T0 + timedelta(days=2),
                           "entry_price": 100, "exit_price": 110, "qty": 1, "journal_stop": None}]
        elif "FROM recommendation_registry" in sql:
            self._last = [_rec("rec_1", 99, 101, stop=95, target=115)]
        else:
            self._last = []

    def fetchall(self):
        return self._last


def test_linker_dry_run_is_read_only(monkeypatch):
    import db_adapter
    import trade_recommendation_linker as L

    conn = FakeConn(DictCur(tables_exist=True))
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    rep = L.run(days=90, apply=False, from_sources=False)
    assert conn.readonly is True and conn.commits == 0
    assert not any(re.match(r"\s*(INSERT|UPDATE|DELETE)", s) for s in conn.cur.sql)
    assert rep["mode"] == "DRY-RUN" and rep["linked"] == 1 and rep["by_confidence"] == {"exact": 1}
    assert rep["sample"][0]["r_multiple"] == 2.0


def test_linker_apply_refuses_without_the_migration(monkeypatch):
    import db_adapter
    import trade_recommendation_linker as L

    conn = FakeConn(DictCur(tables_exist=False))
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    rep = L.run(days=90, apply=True, from_sources=False)
    assert "refused" in rep and conn.commits == 0
    assert not any("INSERT" in s for s in conn.cur.sql)
    rep = L.run(days=90, apply=True, from_sources=True)
    assert "refused" in rep


def test_linker_upsert_is_idempotent_sql():
    import trade_recommendation_linker as L

    assert "ON CONFLICT (round_trip_key) DO UPDATE" in L.UPSERT_SQL
    assert "IS DISTINCT FROM EXCLUDED.rec_id" in L.UPSERT_SQL           # only rewrites a changed row
    assert L.LINK_COLS[0] == "round_trip_key"


def test_registry_sync_dry_run_is_read_only(monkeypatch, tmp_path):
    import db_adapter
    import recommendation_registry_sync as S

    conn = FakeConn(DictCur())
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    hist = tmp_path / "h.jsonl"
    hist.write_text(json.dumps(_version("AAA", 1, datetime.now(timezone.utc), "r1")) + "\n", encoding="utf-8")
    rep = S.run(days=90, apply=False, event_path=hist, projection_path=tmp_path / "none.json")
    assert conn.readonly is True and conn.commits == 0 and rep["by_source"] == {"cio_opportunity": 1}
    assert not any(re.match(r"\s*(INSERT|UPDATE|DELETE)", s) for s in conn.cur.sql)


# ── 7. migration ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_migration_is_additive_and_down_archives():
    up = (ROOT / "migrations/2026_10_21_learning_loop_pr1.sql").read_text(encoding="utf-8")
    code = "\n".join(ln.split("--", 1)[0] for ln in up.splitlines())
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE)\b", code, re.I)
    assert not re.search(r"\bALTER\s+TABLE\b", code, re.I)                 # nothing existing is altered
    assert "CREATE TABLE IF NOT EXISTS recommendation_registry" in code
    assert "CREATE TABLE IF NOT EXISTS trade_recommendation_links" in code
    assert "'operator_initiated'" in code and "rec_id IS NULL AND link_confidence = 'none'" in code
    for col in ("rec_id", "source", "symbol", "direction", "entry_low", "entry_high", "plan_stop", "plan_target",
                "created_at", "expires_at", "conviction_at_issue"):
        assert re.search(rf"^\s+{col}\s", code.split("CREATE TABLE IF NOT EXISTS trade_recommendation_links")[0], re.M), col
    down = (ROOT / "migrations/2026_10_21_learning_loop_pr1.down.sql").read_text(encoding="utf-8")
    dcode = "\n".join(ln.split("--", 1)[0] for ln in down.splitlines())
    assert "RENAME TO" in dcode and not re.search(r"\bDROP\b", dcode, re.I)


def test_no_behaviour_keys_in_registry_rows():
    """MBI_BEHAVIOR = 0: the registry stores plan levels for attribution under plan_* names, never 'stop'."""
    from scripts.lib.cio_instrument_record import BEHAVIOR_FIELDS

    assert not set(reg.COLUMNS) & set(BEHAVIOR_FIELDS)
    lin = reg.OpportunityLineage()
    lin.feed(_version("AAA", 1, T0, "r1"))
    assert not set(lin.rows()[0]) & set(BEHAVIOR_FIELDS)
