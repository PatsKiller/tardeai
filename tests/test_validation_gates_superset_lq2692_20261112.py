"""LQ-20261107-2692 (2141 rev4): the 2141 writer/reader speak the LQ-2413 / 2665 superset validation_gates shape.

The superset DDL (2665 files 05/06) adds source, fix_ref, label, proof_window_end, proven_at and makes blocks_trading
tri-state (NULL = not declared = unknown, never false). rev3 code wrote none of them: a PASS left label NULL, a gate
with no blocks_trading was stored as a declared "no", and a board gate would have been evaluated as a declaration.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from lib import validation_gates as VG  # noqa: E402
from vg_fixtures_20261112 import NOW, Conn, decl  # noqa: E402

QUERIES = {"q_zero": {"sql": "SELECT 0 AS value"}}
SUPERSET_SHA = {"2026_11_12_validation_gates.sql": "a870ce5e", "2026_11_12_validation_events.sql": "5a23f9d4"}


def _apply(c, d, now=NOW):
    return VG.apply_decl(c.cursor(), VG.parse_decl(d, queries=QUERIES), now=now, decl_path="x.json")


def _row(c, gid="VG-T-1", cols="source, blocks_trading, fix_ref, label, proof_window_end, proven_at, status"):
    return c.q(f"SELECT {cols} FROM validation_gates WHERE gate_id=?", (gid,))[0]


def _eval(c, now=NOW, ok_at=None):
    return VG.evaluate_open(c.cursor(), now=now, run_id="t:1", lane_ok_at=lambda _l: ok_at or now,
                            run_query=lambda _q: 0)


def test_migrations_are_the_2665_superset_files_not_a_second_ddl():
    for name, prefix in SUPERSET_SHA.items():
        assert hashlib.sha256((ROOT / "migrations" / name).read_bytes()).hexdigest().startswith(prefix), name


def test_undeclared_blocks_trading_is_stored_unknown_not_false():
    c = Conn()
    d = decl()
    del d["blocks_trading"]
    _apply(c, d)
    assert _row(c, cols="blocks_trading")[0] is None  # was 0: "not declared" stored as a declared "no"
    _apply(c, decl("VG-T-2", blocks_trading=False))
    assert _row(c, "VG-T-2", "blocks_trading")[0] == 0
    with pytest.raises(VG.DeclError, match="blocks_trading"):
        VG.parse_decl(decl(blocks_trading="yes"), queries=QUERIES)
    assert VG.parse_decl(decl(blocks_trading=None), queries=QUERIES)["blocks_trading"] is None


def test_insert_writes_source_declaration_and_monitoring_when_a_fix_is_named():
    c = Conn()
    _apply(c, decl(fix_ref="commit 9aacfc25a"))
    _apply(c, decl("VG-T-2"))
    assert _row(c, cols="source, fix_ref, label") == ("declaration", "commit 9aacfc25a", "MONITORING")
    assert _row(c, "VG-T-2", "source, fix_ref, label") == ("declaration", None, None)
    with pytest.raises(VG.DeclError, match="fix_ref"):
        VG.parse_decl(decl(fix_ref="  "), queries=QUERIES)


def test_proof_window_must_be_positive():
    with pytest.raises(VG.DeclError, match="proof_window_h"):
        VG.parse_decl(decl(check_kind="incident_absent", check_spec={"query_id": "q_zero", "proof_window_h": 0}),
                      queries=QUERIES)


def test_naming_a_fix_later_marks_an_open_gate_monitoring():
    c = Conn()
    _apply(c, decl())
    out = _apply(c, decl(fix_ref="PATCH-X"))
    assert out["action"] == "updated" and _row(c, cols="fix_ref, label") == ("PATCH-X", "MONITORING")


def test_evaluated_pass_is_fixed_unproven_with_a_proof_window_on_the_gate_and_the_event():
    c = Conn()
    _apply(c, decl(check_kind="incident_absent", check_spec={"query_id": "q_zero", "proof_window_h": 48},
                   fix_ref="PATCH-X"))
    _eval(c)
    src, bt, fix, label, end, proven, status = _row(c)
    assert (status, label, proven) == ("PASSED", "FIXED_UNPROVEN", None)  # never FIXED without a proof window
    assert VG.parse_ts(end) == NOW + timedelta(hours=48)
    ev = c.q("SELECT label, proof_window_end FROM validation_events WHERE transition='passed'")
    assert ev == [("FIXED_UNPROVEN", end)]  # the gate and its event say the same thing


def test_manual_close_passed_is_fixed_unproven_and_waived_has_no_label():
    c = Conn()
    _apply(c, decl(fix_ref="PATCH-X"))
    _apply(c, decl(fix_ref="PATCH-X", close={"status": "PASSED", "closed_by": "cc-opus-1",
                                             "evidence": [{"path": "p", "sha256": "0" * 64}]}))
    assert _row(c, cols="status, label")[0:2] == ("PASSED", "FIXED_UNPROVEN")
    assert VG.parse_ts(_row(c, cols="proof_window_end")[0]) == NOW + timedelta(hours=VG.DEFAULT_PROOF_WINDOW_H)
    _apply(c, decl("VG-T-2", fix_ref="PATCH-Y"))
    _apply(c, decl("VG-T-2", fix_ref="PATCH-Y", close={"status": "WAIVED", "closed_by": "operator"}))
    assert _row(c, "VG-T-2", "status, label, proof_window_end") == ("WAIVED", None, None)


def test_a_board_gate_is_neither_evaluated_nor_rewritten_by_a_declaration():
    c = Conn()
    c.raw.execute("INSERT INTO validation_gates (gate_id, title, category, source, status, blocks, opened_at, owner, "
                  "declared_by, check_kind, check_spec, decl_sha256) VALUES ('VG-B-1','b','c','board','OPEN','x',"
                  "'2026-11-12T08:00:00+00:00','o','board','board_probe','{}','s')")
    out = _eval(c)
    assert out["evaluated"] == 0 and _row(c, "VG-B-1", "last_eval_result")[0] is None
    with pytest.raises(VG.DeclError, match="board"):
        _apply(c, decl("VG-B-1"))


def test_reader_keeps_blocks_trading_tri_state_and_carries_the_superset_fields():
    c = Conn()
    d = decl("VG-T-U")
    del d["blocks_trading"]
    _apply(c, d)
    _apply(c, decl("VG-T-Y", fix_ref="PATCH-X"))
    _apply(c, decl("VG-T-N", blocks_trading=False))
    _eval(c)
    cur = c.cursor()
    cur.execute(VG.READ_GATES_SQL)
    names = [x.strip() for x in VG.READ_GATES_SQL.split("SELECT", 1)[1].split("FROM", 1)[0].split(",")]
    rows = [dict(zip(names, r)) for r in cur.fetchall()]
    cur.execute(VG.READ_FRESH_SQL)
    fresh = dict(zip(("computed_at", "n"), cur.fetchone()))
    m = VG.read_model(rows, fresh, now=NOW)
    by = {i["gate_id"]: i for i in m["items"]}
    assert [i["gate_id"] for i in m["items"]] == ["VG-T-Y", "VG-T-U", "VG-T-N"]  # unknown ranks above a declared no
    assert by["VG-T-U"]["blocks_trading"] is None and by["VG-T-N"]["blocks_trading"] is False
    assert by["VG-T-Y"]["label"] == "MONITORING" and by["VG-T-Y"]["fix_ref"] == "PATCH-X"
    assert by["VG-T-Y"]["source"] == "declaration" and by["VG-T-Y"]["label_text"] == "MONITORING"
    assert {"proof_window_end", "proven_at"} <= set(by["VG-T-U"])
    assert m["counts"] == {"open": 3, "blocks_trading": 1, "blocks_trading_unknown": 1, "overdue": 0}


def test_an_unknown_blocks_trading_cannot_be_redeclared_as_no():
    c = Conn()
    d = decl()
    del d["blocks_trading"]
    _apply(c, d)
    with pytest.raises(VG.DeclError, match="blocks_trading cannot change"):
        _apply(c, decl(blocks_trading=False, title="quietly loosened"))  # unknown -> "no" is a change, not a fill-in
    assert _row(c, cols="blocks_trading")[0] is None


def test_manual_close_and_monitoring_write_their_events(tmp_path):
    import json

    import validation_gates_sync as S
    c = Conn()
    ib = tmp_path / "data/coordination/validation_gates/inbox"
    ib.mkdir(parents=True)

    def run(name, d, minutes):
        (ib / name).write_text(json.dumps(d))
        S.run(c, root=tmp_path, queries=QUERIES, now=NOW + timedelta(minutes=minutes), apply=True, run_id="t:1",
              postgres=False)

    run("a.json", decl(), 0)
    run("b.json", decl(fix_ref="PATCH-X"), 1)
    run("c.json", decl(fix_ref="PATCH-X", close={"status": "PASSED", "closed_by": "cc-opus-1",
                                                 "evidence": [{"path": "p", "sha256": "0" * 64}]}), 2)
    run("d.json", decl("VG-T-2"), 3)
    run("e.json", decl("VG-T-2", close={"status": "WAIVED", "closed_by": "operator"}), 4)
    ev = c.q("SELECT source_id, transition, label, proof_window_end FROM validation_events ORDER BY occurred_at")
    assert [e[:3] for e in ev] == [("VG-T-1", "opened", None), ("VG-T-1", "monitoring", None),
                                   ("VG-T-1", "passed", "FIXED_UNPROVEN"), ("VG-T-2", "opened", None),
                                   ("VG-T-2", "waived", None)]
    assert ev[2][3] == _row(c, cols="proof_window_end")[0]  # the event and the gate agree on the window end
