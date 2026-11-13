"""LQ-20261107-2966: the validation-gate declaration producer, end to end against the sync, plus the refusal event."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts", ROOT / "tests"):
    sys.path.insert(0, str(p))

import validation_gate_declare as D  # noqa: E402
import validation_gates_sync as S  # noqa: E402
from lib import validation_gate_producer as P  # noqa: E402
from lib import validation_gates as VG  # noqa: E402
from vg_fixtures_20261112 import NOW, Conn  # noqa: E402

CATALOG = json.loads((ROOT / "config" / "validation_gate_declarations.json").read_text())
QUERIES = S.load_queries()
# sqlite stand-ins for the two Postgres-only named queries: same ids, so the real catalog resolves against them
SQLITE_Q = {**QUERIES, "lane_health_newest_measured": {"sql": "SELECT NULL AS value"},
            "amanx_quote_business_days_stale": {"sql": "SELECT 4 AS value"}}


def gdir(tmp_path, sub):
    return tmp_path / "data" / "coordination" / "validation_gates" / sub


def declare(tmp_path, monkeypatch, *args):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return D.main(list(args))


def declare_at_fixed_now(tmp_path):
    """Same producer code path as the CLI, with the clock pinned to the fixture's NOW (due_at = NOW + 24 h)."""
    decls = P.build_decls(CATALOG, queries=QUERIES, now=NOW)
    return P.write_pending(decls, P.plan(decls, root=tmp_path), root=tmp_path)


def receipt(tmp_path, lane, ok_at):
    d = tmp_path / "data" / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lane}_last.json").write_text(json.dumps({"ok_at": ok_at.isoformat()}))


def sync(conn, tmp_path, now=NOW, queries=SQLITE_Q):
    return S.run(conn, root=tmp_path, queries=queries, now=now, apply=True, run_id="t:2966", postgres=False)


def test_catalog_gates_read_only_real_evidence():
    decls = P.build_decls(CATALOG, queries=QUERIES, now=NOW)
    assert len(decls) == 5
    for d in decls:
        assert d["check_kind"] in ("lane_fresh", "db_max", "sql_threshold", "incident_absent")  # never manual
        assert "close" not in d and d["declared_by"] == P.DECLARED_BY
        assert d.get("blocks_trading") is None  # not declared is unknown, never claimed
        if d["check_kind"] == "lane_fresh":
            assert d["check_spec"]["max_age_h"] > 0
        else:
            assert d["check_spec"]["query_id"] in QUERIES
    assert {d["check_spec"].get("lane_id") for d in decls} >= {"stop_coverage_incidents", "lane-health-snapshot"}


def test_catalog_refuses_manual_pass_or_missing_evidence_or_unknown_query():
    def one(**kw):
        g = {**CATALOG["gates"][0], **kw}
        return {**CATALOG, "gates": [g]}
    with pytest.raises(P.CatalogError, match="manual_evidence"):
        P.build_decls(one(check_kind="manual_evidence", check_spec={}), queries=QUERIES, now=NOW)
    with pytest.raises(P.CatalogError, match="evidence"):
        P.build_decls(one(evidence=" "), queries=QUERIES, now=NOW)
    with pytest.raises(P.CatalogError, match="not in config"):
        P.build_decls(one(check_kind="db_max", check_spec={"query_id": "nope", "max_age_h": 1}), queries=QUERIES, now=NOW)
    with pytest.raises(P.CatalogError, match="unknown keys"):
        P.build_decls(one(close={"status": "PASSED"}), queries=QUERIES, now=NOW)


def test_dry_run_writes_nothing_apply_writes_five_rerun_is_noop(tmp_path, monkeypatch, capsys):
    assert declare(tmp_path, monkeypatch) == 0
    assert not gdir(tmp_path, "inbox").exists()
    assert declare(tmp_path, monkeypatch, "--apply") == 0
    assert len(list(gdir(tmp_path, "inbox").glob("*.json"))) == 5
    capsys.readouterr()
    assert declare(tmp_path, monkeypatch, "--apply") == 0
    assert all(r["action"] == "unchanged" for r in json.loads(capsys.readouterr().out)["gates"])


def test_producer_will_not_rewrite_a_declared_gate_with_a_looser_check(tmp_path, monkeypatch, capsys):
    declare(tmp_path, monkeypatch, "--apply")
    path = ROOT / "config" / "validation_gate_declarations.json"
    loose = json.loads(path.read_text())
    loose["gates"][0]["check_spec"]["max_age_h"] = 99
    monkeypatch.setattr(D, "HERE", ROOT / "scripts")
    decls = P.build_decls(loose, queries=QUERIES, now=NOW)
    rows = P.plan(decls, root=tmp_path)
    assert rows[0]["action"] == "drift" and all(r["action"] == "unchanged" for r in rows[1:])
    assert P.write_pending(decls, rows, root=tmp_path) == []
    on_disk = json.loads((gdir(tmp_path, "inbox") / f"{loose['gates'][0]['gate_id']}.json").read_text())
    assert on_disk["check_spec"]["max_age_h"] == 1.5


def test_producer_files_ingest_and_evaluate_real_evidence(tmp_path, monkeypatch):
    conn = Conn()
    declare_at_fixed_now(tmp_path)
    out = sync(conn, tmp_path)
    assert out["ingested"] == 5 and out["refused"] == 0
    rows = {r[0]: r for r in conn.q("SELECT gate_id, status, last_eval_result, source FROM validation_gates")}
    assert len(rows) == 5 and {r[3] for r in rows.values()} == {"declaration"}
    # no receipts, an empty lane_health_current and a 4-day-old AMANX quote: nothing passes, nothing is pre-passed
    assert {r[1] for r in rows.values()} == {"OPEN"}
    assert rows["VG-R3-STOP-COVERAGE-HEARTBEAT"][2] == "ERROR"
    assert rows["VG-R3-LANE-HEALTH-ROWS-FRESH"][2] == "ERROR"
    assert rows["VG-R3-AMANX-QUOTE-FRESH"][2] == "FAIL"
    # a fresh heartbeat receipt is real evidence: that one gate passes, the others do not
    receipt(tmp_path, "stop_coverage_incidents", NOW - timedelta(minutes=10))
    sync(conn, tmp_path, now=NOW + timedelta(minutes=5))
    rows = {r[0]: r[1] for r in conn.q("SELECT gate_id, status FROM validation_gates")}
    assert rows["VG-R3-STOP-COVERAGE-HEARTBEAT"] == "PASSED"
    assert [k for k, v in rows.items() if v == "PASSED"] == ["VG-R3-STOP-COVERAGE-HEARTBEAT"]
    label = conn.q("SELECT label, closed_by FROM validation_gates WHERE gate_id='VG-R3-STOP-COVERAGE-HEARTBEAT'")[0]
    assert label == ("FIXED_UNPROVEN", VG.SYSTEM_ACTOR)


def test_a_stale_receipt_does_not_pass_and_a_failing_gate_fails_after_due(tmp_path, monkeypatch):
    conn = Conn()
    declare_at_fixed_now(tmp_path)
    receipt(tmp_path, "stop_coverage_incidents", NOW - timedelta(hours=5))
    sync(conn, tmp_path)
    sync(conn, tmp_path, now=NOW + timedelta(hours=30))
    st = {r[0]: r[1] for r in conn.q("SELECT gate_id, status FROM validation_gates")}
    assert st["VG-R3-STOP-COVERAGE-HEARTBEAT"] == "FAILED"
    assert st["VG-R3-AMANX-QUOTE-FRESH"] == "FAILED"
    assert st["VG-R3-LANE-HEALTH-ROWS-FRESH"] == "OVERDUE"  # ERROR (no rows) after due is OVERDUE, never PASS
    assert conn.q("SELECT count(*) FROM validation_events WHERE transition='failed'")[0][0] == 2


LOOSENINGS = [
    ("check_spec", lambda d: d["check_spec"].update(max_age_h=99)),
    ("check_kind", lambda d: d.update(check_kind="db_max", check_spec={"query_id": "lane_health_newest_measured",
                                                                       "max_age_h": 99})),
    ("blocks_trading", lambda d: d.update(blocks_trading=False)),
    ("due_at", lambda d: d.update(due_at=(VG.parse_ts(d["due_at"]) + timedelta(days=30)).isoformat())),
]


@pytest.mark.parametrize("field,mutate", LOOSENINGS, ids=[x[0] for x in LOOSENINGS])
def test_a_gate_cannot_weaken_its_own_rule_refused_and_recorded(tmp_path, monkeypatch, field, mutate):
    conn = Conn()
    declare_at_fixed_now(tmp_path)
    sync(conn, tmp_path)
    gid = "VG-R3-STOP-COVERAGE-HEARTBEAT"
    before = conn.q("SELECT check_kind, check_spec, blocks_trading, due_at, decl_sha256 FROM validation_gates "
                    "WHERE gate_id=?", (gid,))[0]
    doc = json.loads((gdir(tmp_path, "ingested") / f"{gid}.json").read_text())
    mutate(doc)
    bad = gdir(tmp_path, "inbox") / f"{gid}.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(json.dumps(doc))
    out = sync(conn, tmp_path)
    assert out["refused"] == 1 and out["refusal_events"] == 1
    assert not bad.exists()
    refused = gdir(tmp_path, "refused")
    assert (refused / bad.name).is_file()
    assert field in (refused / (bad.name + ".reason.txt")).read_text() or "cannot change" in (
        refused / (bad.name + ".reason.txt")).read_text()
    after = conn.q("SELECT check_kind, check_spec, blocks_trading, due_at, decl_sha256 FROM validation_gates "
                   "WHERE gate_id=?", (gid,))[0]
    assert after == before  # the stored rule is untouched
    ev = conn.q("SELECT source_kind, source_id, transition, summary FROM validation_events WHERE transition='refused'")
    assert len(ev) == 1 and ev[0][:3] == ("declaration", gid, "refused") and "cannot change" in ev[0][3]
    # the same refused file offered again is the same refusal: still one event (deduped on the file's sha256)
    bad.write_text(json.dumps(doc))
    sync(conn, tmp_path, now=NOW + timedelta(minutes=5))
    assert conn.q("SELECT count(*) FROM validation_events WHERE transition='refused'")[0][0] == 1


def test_a_garbage_declaration_is_refused_and_recorded_under_its_file_name(tmp_path):
    conn = Conn()
    f = gdir(tmp_path, "inbox") / "junk.json"
    f.parent.mkdir(parents=True)
    f.write_text("{not json")
    out = sync(conn, tmp_path)
    assert out["refused"] == 1 and out["refusal_events"] == 1
    assert conn.q("SELECT source_id, transition FROM validation_events") == [("junk.json", "refused")]


def test_a_dry_run_records_no_refusal_event(tmp_path):
    conn = Conn()
    f = gdir(tmp_path, "inbox") / "junk.json"
    f.parent.mkdir(parents=True)
    f.write_text("{not json")
    S.run(conn, root=tmp_path, queries=SQLITE_Q, now=NOW, apply=False, run_id="t:dry", postgres=False)
    assert conn.q("SELECT count(*) FROM validation_events")[0][0] == 0 and f.exists()
