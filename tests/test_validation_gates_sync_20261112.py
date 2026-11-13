"""VALIDATION_GATES_SYNC_20261112 - declarations, DB CHECKs, evaluation and transitions (LQ-20261107-2141/2143)."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import validation_gates_sync as S  # noqa: E402
from lib import validation_gates as VG  # noqa: E402
from vg_fixtures_20261112 import NOW, Conn, decl  # noqa: E402

QUERIES = {"q_zero": {"sql": "SELECT 0 AS value"}, "q_five": {"sql": "SELECT 5 AS value"}}


def inbox(tmp_path, *docs):
    d = tmp_path / "data" / "coordination" / "validation_gates" / "inbox"
    d.mkdir(parents=True)
    for i, doc in enumerate(docs):
        (d / f"{i:02d}.json").write_text(json.dumps(doc))
    return d


def run(conn, tmp_path, *, apply=True, now=NOW, queries=QUERIES):
    return S.run(conn, root=tmp_path, queries=queries, now=now, apply=apply, run_id="t:1", postgres=False)


def test_declaration_cannot_carry_free_sql():
    with pytest.raises(VG.DeclError, match="free SQL"):
        VG.parse_decl(decl(check_kind="sql_threshold", check_spec={"query_id": "q_zero", "op": "<=", "value": 0,
                                                                  "sql": "DROP TABLE x"}), queries=QUERIES)
    with pytest.raises(VG.DeclError, match="not in config"):
        VG.parse_decl(decl(check_kind="incident_absent", check_spec={"query_id": "nope"}), queries=QUERIES)
    with pytest.raises(VG.DeclError, match="unknown keys"):
        VG.parse_decl(decl(sql="select 1"), queries=QUERIES)


def test_committed_query_registry_is_what_declarations_resolve_against():
    q = S.load_queries()
    assert q and all(set(v) >= {"sql", "returns"} for v in q.values())
    assert all(v["sql"].lstrip().upper().startswith("SELECT") for v in q.values())


def test_same_declaration_twice_upserts_once(tmp_path):
    c = Conn()
    inbox(tmp_path, decl())
    first = run(c, tmp_path)
    assert first["ingested"] == 1
    (tmp_path / "data/coordination/validation_gates/inbox").mkdir(exist_ok=True)
    again = tmp_path / "data/coordination/validation_gates/inbox/again.json"
    again.write_text(json.dumps(decl()))
    second = run(c, tmp_path)
    assert second["unchanged"] == 1 and second["ingested"] == 0
    assert c.q("SELECT count(*) FROM validation_gates")[0][0] == 1
    assert c.q("SELECT count(*) FROM validation_events WHERE transition='opened'")[0][0] == 1


def test_open_becomes_overdue_at_due_at_with_one_event(tmp_path):
    c = Conn()
    inbox(tmp_path, decl(due_at="2026-11-12T09:00:00+00:00"))
    out = run(c, tmp_path)
    assert out["transitions"] == 1
    assert c.q("SELECT status FROM validation_gates")[0][0] == "OVERDUE"
    assert c.q("SELECT count(*) FROM validation_events WHERE transition='overdue'")[0][0] == 1
    run(c, tmp_path, now=NOW + timedelta(minutes=5))  # already OVERDUE: no new transition
    assert c.q("SELECT count(*) FROM validation_events WHERE transition='overdue'")[0][0] == 1
    # same slot replayed: the dedupe key refuses the duplicate event
    cur = c.cursor()
    assert VG.record_event(cur, {"gate_id": "VG-T-1", "category": "x", "owner": "r", "check_spec": {}}, "overdue",
                           occurred_at=NOW, run_id="t:1", summary="again") is False


def test_not_yet_due_stays_open(tmp_path):
    c = Conn()
    inbox(tmp_path, decl())
    assert run(c, tmp_path)["transitions"] == 0
    assert c.q("SELECT status, last_eval_result FROM validation_gates")[0] == ("OPEN", "NOT_EVALUABLE")


def test_self_certified_manual_close_is_refused_by_code_and_by_db(tmp_path):
    c = Conn()
    inbox(tmp_path, decl())
    run(c, tmp_path)
    with pytest.raises(VG.DeclError, match="self-certification"):
        VG.check_close(decl(), {"status": "PASSED", "closed_by": "lead", "evidence": [{"path": "p"}]})
    # the database says no on its own, even if the code were bypassed
    with pytest.raises(sqlite3.IntegrityError):
        c.raw.execute("UPDATE validation_gates SET status='PASSED', closed_at='2026-11-12T10:00:00+00:00', "
                      "closed_by='lead'")
    # a different closer with evidence is accepted
    d = decl(close={"status": "PASSED", "closed_by": "cc-opus-1", "evidence": [{"path": "p", "sha256": "0" * 64}]})
    inbox_dir = tmp_path / "data/coordination/validation_gates/inbox"
    (inbox_dir / "close.json").write_text(json.dumps(d))
    out = run(c, tmp_path)
    assert out["ingested"] == 1 and c.q("SELECT status, closed_by FROM validation_gates")[0] == ("PASSED", "cc-opus-1")


def test_self_close_file_is_refused_and_moved_aside_with_a_reason(tmp_path):
    c = Conn()
    inbox(tmp_path, decl())
    run(c, tmp_path)
    bad = tmp_path / "data/coordination/validation_gates/inbox/bad.json"
    bad.write_text(json.dumps(decl(close={"status": "PASSED", "closed_by": "lead", "evidence": [{"path": "p"}]})))
    out = run(c, tmp_path)
    assert out["refused"] == 1 and not bad.exists()
    refused = tmp_path / "data/coordination/validation_gates/refused"
    assert (refused / "bad.json").exists() and (refused / "bad.json.reason.txt").read_text().strip()
    assert c.q("SELECT status FROM validation_gates")[0][0] == "OPEN"
    assert run(c, tmp_path)["refused"] == 0  # not re-counted on the next run


def test_dry_run_leaves_a_refused_file_in_the_inbox(tmp_path):
    c = Conn()
    d = inbox(tmp_path, {"schema": "nope"})
    out = run(c, tmp_path, apply=False)
    assert out["refused"] == 1 and list(d.glob("*.json"))
    assert not (tmp_path / "data/coordination/validation_gates/refused").exists()


def test_waived_only_by_operator(tmp_path):
    with pytest.raises(VG.DeclError, match="operator-only"):
        VG.check_close(decl(), {"status": "WAIVED", "closed_by": "cc-opus-1"})
    VG.check_close(decl(), {"status": "WAIVED", "closed_by": "operator"})
    c = Conn()
    inbox(tmp_path, decl())
    run(c, tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        c.raw.execute("UPDATE validation_gates SET status='WAIVED', closed_at='2026-11-12T10:00:00+00:00', "
                      "closed_by='someone'")


def test_machine_check_cannot_be_closed_by_hand():
    with pytest.raises(VG.DeclError, match="evaluated PASS"):
        VG.check_close(decl(check_kind="lane_fresh"), {"status": "PASSED", "closed_by": "cc-opus-1"})


def test_lane_fresh_pass_closes_and_labels_fixed_unproven(tmp_path):
    c = Conn()
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    (rt / "x-lane_last.json").write_text(json.dumps({"ok_at": (NOW - timedelta(minutes=10)).isoformat()}))
    inbox(tmp_path, decl(check_kind="lane_fresh", check_spec={"lane_id": "x-lane", "max_age_h": 1}))
    out = run(c, tmp_path)
    assert out["transitions"] == 1
    assert c.q("SELECT status, closed_by FROM validation_gates")[0] == ("PASSED", VG.SYSTEM_ACTOR)
    label, pw = c.q("SELECT label, proof_window_end FROM validation_events WHERE transition='passed'")[0]
    assert label == "FIXED_UNPROVEN" and pw.startswith("2026-11-13T10:00")


def test_lane_fresh_fail_after_due_becomes_failed_and_missing_receipt_is_error(tmp_path):
    c = Conn()
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    (rt / "x-lane_last.json").write_text(json.dumps({"ok_at": (NOW - timedelta(hours=3)).isoformat()}))
    inbox(tmp_path,
          decl("VG-A", check_kind="lane_fresh", check_spec={"lane_id": "x-lane", "max_age_h": 1}, due_at="2026-11-12T09:00:00+00:00"),
          decl("VG-B", check_kind="lane_fresh", check_spec={"lane_id": "gone", "max_age_h": 1}))
    out = run(c, tmp_path)
    assert dict(c.q("SELECT gate_id, status FROM validation_gates")) == {"VG-A": "FAILED", "VG-B": "OPEN"}
    assert dict(c.q("SELECT gate_id, last_eval_result FROM validation_gates"))["VG-B"] == "ERROR"
    assert out["errors"] == 1  # an unreadable check is an error, never a pass


def test_named_query_threshold(tmp_path):
    c = Conn()
    inbox(tmp_path, decl("VG-Z", check_kind="sql_threshold", check_spec={"query_id": "q_zero", "op": "<=", "value": 0}),
          decl("VG-F", check_kind="sql_threshold", check_spec={"query_id": "q_five", "op": "<=", "value": 0}))
    run(c, tmp_path)
    assert dict(c.q("SELECT gate_id, status FROM validation_gates")) == {"VG-Z": "PASSED", "VG-F": "OPEN"}


def test_dry_run_writes_nothing_and_moves_nothing(tmp_path):
    c = Conn()
    d = inbox(tmp_path, decl())
    out = run(c, tmp_path, apply=False)
    assert out["ingested"] == 1  # computed
    assert c.q("SELECT count(*) FROM validation_gates")[0][0] == 0
    assert c.q("SELECT count(*) FROM validation_events")[0][0] == 0
    assert list(d.glob("*.json")) and not (tmp_path / "data/coordination/validation_gates/ingested").exists()


def test_apply_moves_ingested_files_after_commit(tmp_path):
    c = Conn()
    d = inbox(tmp_path, decl())
    run(c, tmp_path)
    assert not list(d.glob("*.json"))
    assert len(list((tmp_path / "data/coordination/validation_gates/ingested").glob("*.json"))) == 1


def test_script_is_wrapped_by_run_main():
    src = (ROOT / "scripts" / "validation_gates_sync.py").read_text()
    assert "run_main(LANE, main, script=" in src and "LANE_OUTPUT" in src


def test_manual_evidence_never_passes_on_an_evaluator_result():
    g = {"status": "OPEN", "check_kind": "manual_evidence", "due_at": None}
    assert VG.next_state(g, "PASS", now=NOW) is None


def test_redeclaring_cannot_loosen_a_gate(tmp_path):
    """REVIEW C1 probe: max_age_h 1 + blocks_trading -> 999999 + not blocking must be refused and must not pass."""
    c = Conn()
    spec = {"lane_id": "lane-x", "max_age_h": 1}
    inbox(tmp_path, decl(check_kind="lane_fresh", check_spec=spec, blocks_trading=True))
    run(c, tmp_path)
    before = c.q("SELECT check_spec, blocks_trading, due_at FROM validation_gates")
    d = tmp_path / "data/coordination/validation_gates/inbox"
    (d / "loose.json").write_text(json.dumps(decl(check_kind="lane_fresh",
                                                  check_spec={"lane_id": "lane-x", "max_age_h": 999999},
                                                  blocks_trading=False, title="looser")))
    out = run(c, tmp_path)
    assert out["refused"] == 1
    assert c.q("SELECT check_spec, blocks_trading, due_at FROM validation_gates") == before
    assert "cannot change" in (tmp_path / "data/coordination/validation_gates/refused/loose.json.reason.txt").read_text()


def test_redeclaring_cannot_move_the_due_date_or_the_kind():
    c = Conn()
    cur = c.cursor()
    d0 = VG.parse_decl(decl(), queries=QUERIES)
    VG.apply_decl(cur, d0, now=NOW)
    for change in ({"due_at": "2099-01-01T00:00:00+00:00"}, {"check_kind": "incident_absent",
                                                              "check_spec": {"query_id": "q_zero"}}):
        d1 = VG.parse_decl(decl(**change), queries=QUERIES)
        with pytest.raises(VG.DeclError, match="cannot change"):
            VG.apply_decl(cur, d1, now=NOW)


def test_redeclaring_a_title_still_updates_and_same_file_is_noop():
    c = Conn()
    cur = c.cursor()
    VG.apply_decl(cur, VG.parse_decl(decl(), queries=QUERIES), now=NOW)
    res = VG.apply_decl(cur, VG.parse_decl(decl(title="renamed"), queries=QUERIES), now=NOW)
    assert res["action"] == "updated"
    assert c.q("SELECT title FROM validation_gates")[0][0] == "renamed"


@pytest.mark.parametrize("kind,spec", [("db_max", {"query_id": "q", "max_age_h": 1}),
                                       ("incident_absent", {"query_id": "q"}),
                                       ("sql_threshold", {"query_id": "q", "op": "<=", "value": 1})])
def test_a_query_with_no_value_is_error_and_never_closes(kind, spec):
    """REVIEW C2: a NULL query result must never read as PASS."""
    g = {"gate_id": "g", "status": "OPEN", "check_kind": kind, "check_spec": spec, "due_at": None}
    result, _ = VG.evaluate(g, now=NOW, lane_ok_at=lambda _l: None, run_query=lambda _q: None)
    assert result == "ERROR"
    assert VG.next_state(g, result, now=NOW) is None


def test_a_future_db_max_timestamp_is_error_not_fresh():
    g = {"gate_id": "g", "status": "OPEN", "check_kind": "db_max", "check_spec": {"query_id": "q", "max_age_h": 24},
         "due_at": None}
    result, detail = VG.evaluate(g, now=NOW, lane_ok_at=lambda _l: None,
                                 run_query=lambda _q: NOW + timedelta(days=30))
    assert result == "ERROR" and "future" in detail["reason"]


def test_redeclaring_only_the_check_spec_is_refused():
    c = Conn()
    cur = c.cursor()
    base = dict(check_kind="lane_fresh", check_spec={"lane_id": "lane-x", "max_age_h": 1})
    VG.apply_decl(cur, VG.parse_decl(decl(**base), queries=QUERIES), now=NOW)
    loose = dict(base, check_spec={"lane_id": "lane-x", "max_age_h": 999999})
    with pytest.raises(VG.DeclError, match="check_spec"):
        VG.apply_decl(cur, VG.parse_decl(decl(**loose), queries=QUERIES), now=NOW)


def test_a_future_lane_receipt_is_error_not_fresh():
    """REVIEW-2653 F1: lane_fresh gets the same future guard as db_max."""
    g = {"gate_id": "g", "status": "OPEN", "check_kind": "lane_fresh", "check_spec": {"lane_id": "l", "max_age_h": 1},
         "due_at": None}
    result, detail = VG.evaluate(g, now=NOW, lane_ok_at=lambda _l: NOW + timedelta(days=30), run_query=lambda _q: None)
    assert result == "ERROR" and "future" in detail["reason"]
    assert VG.next_state(g, result, now=NOW) is None
    ok, _ = VG.evaluate(g, now=NOW, lane_ok_at=lambda _l: NOW - timedelta(minutes=5), run_query=lambda _q: None)
    assert ok == "PASS"


def test_lane_future_tolerance_is_six_minutes_not_more():
    """REVIEW-2680 N-A1: the lane guard tolerates at most 0.1 h (6 min) of clock skew.

    The +0.2 h case sits between the tolerance and the existing far-future fixture, which is what
    makes a widened tolerance observable: with the guard relaxed (e.g. -0.1 -> -100 h) a receipt
    12 min ahead reads PASS/"fresh" and this test fails. The +0.05 h case pins the other edge, so a
    tolerance tighter than the design skew is also caught.
    """
    g = {"gate_id": "g", "status": "OPEN", "check_kind": "lane_fresh", "check_spec": {"lane_id": "l", "max_age_h": 1},
         "due_at": None}
    # 0.2 h (12 min) ahead: outside the 0.1 h tolerance -> a clock fault, never freshness.
    result, detail = VG.evaluate(g, now=NOW, lane_ok_at=lambda _l: NOW + timedelta(hours=0.2),
                                 run_query=lambda _q: None)
    assert result == "ERROR" and "future" in detail["reason"]
    assert VG.next_state(g, result, now=NOW) is None
    # 0.05 h (3 min) ahead: inside the design tolerance -> reads normally (PASS on a fresh lane).
    inside, _ = VG.evaluate(g, now=NOW, lane_ok_at=lambda _l: NOW + timedelta(hours=0.05),
                            run_query=lambda _q: None)
    assert inside == "PASS"


@pytest.mark.parametrize("field,value", [("blocks_trading", False), ("check_kind", "db_max")])
def test_redeclaring_a_frozen_field_is_refused(field, value):
    """REVIEW-2653 F2: blocks_trading and check_kind freeze like check_spec/due_at."""
    c = Conn()
    cur = c.cursor()
    base = dict(check_kind="lane_fresh", check_spec={"lane_id": "lane-x", "max_age_h": 1}, blocks_trading=True)
    VG.apply_decl(cur, VG.parse_decl(decl(**base), queries=QUERIES), now=NOW)
    changed = dict(base, **{field: value})
    if field == "check_kind":
        changed["check_spec"] = {"query_id": "q_zero", "max_age_h": 1}
    with pytest.raises(VG.DeclError, match=field):
        VG.apply_decl(cur, VG.parse_decl(decl(**changed), queries=QUERIES), now=NOW)


def test_a_future_snapshot_reads_unknown_not_fresh():
    """REVIEW-2653 F3: computed_at in the future is a clock fault -> UNKNOWN."""
    m = VG.read_model([], {"n": 1, "computed_at": NOW + timedelta(days=3)}, now=NOW)
    assert m["state"] == "UNKNOWN" and "future" in m["reason"] and m["counts"] is None
    m2 = VG.read_model([], {"n": 1, "computed_at": NOW - timedelta(seconds=5)}, now=NOW)
    assert m2["state"] == "OK"
