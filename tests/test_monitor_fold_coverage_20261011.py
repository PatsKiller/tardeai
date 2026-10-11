"""W1-9 monitor fold coverage (2026-10-11) — freshness contracts and input starvation in the breach detector.

MONITOR_FOLD_COVERAGE.md gaps 1, 3 and 6: the registry's ``freshness_contracts`` carry the DB/file freshness
checks of job_coverage_monitor (12 DB checks), pipeline_freshness_monitor (8 targets no registry signal named)
and system_freshness_monitor (8 'fresh' tables); supervisor_breach_detector raises STALE_OUTPUT from them and
INPUT_STARVATION from pipeline_liveness (the checks of pipeline_liveness_report). Both kinds are detect + record
only: they never reach L1-L5 or L3. Hermetic: tmp registry and state root, no DB, no heartbeat write; the
committed-registry tests read only repo files.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import lane_registry as lr  # noqa: E402
import supervisor_breach_detector as sbd  # noqa: E402

COVERS = ["scripts/supervisor_breach_detector.py", "scripts/lib/lane_registry.py", "config/lane_registry.json"]

UTC = dt.timezone.utc
ET = sbd.SCHEDULE_TZ


def _contract(**kw):
    c = {"key": "t.store", "signal": {"kind": "db_max", "table": "news_articles", "column": "created_at"},
         "max_age_hours": 24, "basis": "wall_clock", "severity": "P2", "source": "scripts/x.py:1", "replaces": ["tick:x"]}
    c.update(kw)
    return c


# ── validation ────────────────────────────────────────────────────────────────────────────────────────

def test_a_valid_contract_and_an_absent_list_validate():
    assert lr.validate_freshness_contracts(None) == []
    assert lr.validate_freshness_contracts([_contract()]) == []
    assert lr.validate_freshness_contracts([_contract(lane_id="a", basis="lane_due")], ["a"]) == []


@pytest.mark.parametrize("bad, needle", [
    ({"source": ""}, "source is required"),
    ({"replaces": []}, "replaces must name"),
    ({"severity": "P0"}, "severity must be"),
    ({"basis": "lane_due"}, "lane_due needs lane_id"),
    ({"lane_id": "nope"}, "is not a registry lane"),
    ({"max_age_hours": 0}, "max_age_hours"),
    ({"signal": {"kind": "db_max", "table": "t; drop", "column": "c"}}, "safe table"),
    ({"signal": {"kind": "db_max", "table": "t", "column": "c", "where": "a=1; delete"}}, "unsafe where"),
    ({"signal": {"kind": "file_mtime"}}, "needs a path"),
    ({"signal": {"kind": "systemd_result", "unit": "x"}}, "signal.kind"),
    ({"key": "Bad Key"}, "key must match"),
])
def test_invalid_contracts_are_rejected(bad, needle):
    errs = lr.validate_freshness_contracts([_contract(**bad)], ["a"])
    assert any(needle in e for e in errs), errs


def test_duplicate_keys_are_rejected_and_validate_registry_includes_contracts():
    reg = {"lanes": [], "freshness_contracts": [_contract(), _contract()]}
    assert any("duplicate key" in e for e in lr.validate_registry(reg))


# ── the committed registry ────────────────────────────────────────────────────────────────────────────

REG = lr.load_registry(ROOT / "config" / "lane_registry.json")
CONTRACTS = {c["key"]: c for c in REG.get("freshness_contracts") or []}
LANES = {l["lane_id"]: l for l in REG["lanes"]}


def test_committed_registry_validates_and_carries_28_contracts():
    assert lr.validate_registry(REG) == []
    assert len(CONTRACTS) == 28
    assert sum(k.startswith("jcm.") for k in CONTRACTS) == 12
    assert sum(k.startswith("pfm.") for k in CONTRACTS) == 8
    assert sum(k.startswith("sfm.") for k in CONTRACTS) == 8


def _source_line(contract) -> str:
    path, _, rest = contract["source"].partition(":")
    first = int(rest.split()[0].split("-")[0])
    return (ROOT / path).read_text(encoding="utf-8").splitlines()[first - 1]


def test_every_contract_source_points_at_its_check():
    for key, c in CONTRACTS.items():
        line = _source_line(c)
        name = key.split(".", 1)[1]
        assert name in line, (key, line)


def test_job_coverage_db_checks_all_carried_with_their_cadence_on_an_active_producer_lane():
    import job_coverage_monitor as jcm

    db_jobs = {j["name"]: j for j in jcm.REGISTRY if j["signal"][0] == "db"}
    assert len(db_jobs) == 12
    for name, job in db_jobs.items():
        c = CONTRACTS[f"jcm.{name}"]
        assert c["max_age_hours"] == job["cadence_h"] and c["basis"] == "lane_due"
        assert LANES[c["lane_id"]]["state"] == "ACTIVE"
        sig = c["signal"]
        sql = job["signal"][1]
        assert f"MAX({sig['column']}) FROM {sig['table']}" in sql, (name, sql)
        if "where" in sig and " OR " not in sig["where"]:
            assert sig["where"] in sql
        producer = c["lane_id"]
        if c.get("producer_before_c1"):
            # C1 premarket flip (2026-10-11): the producer row is RETIRED into the stage lane that now runs its cron
            # line verbatim; the contract follows the stage lane (a RETIRED lane_id is never judged).
            producer = c["producer_before_c1"]
            assert LANES[producer]["state"] == "RETIRED" and LANES[producer]["superseded_by"] == c["lane_id"], name
        sched = json.dumps(LANES[producer].get("scheduler")) + json.dumps(LANES[producer].get("exec_start") or "")
        assert job["schedule_match"] in sched, (name, producer)


def test_candidate_discovery_or_clause_is_the_same_set_as_the_in_list():
    import job_coverage_monitor as jcm

    sql = next(j["signal"][1] for j in jcm.REGISTRY if j["name"] == "candidate_discovery_orchestrator")
    in_keys = set(sql.split("IN (")[1].rstrip(")").replace("'", "").split(","))
    or_keys = {p.split("=")[1].strip("'") for p in CONTRACTS["jcm.candidate_discovery_orchestrator"]["signal"]["where"].split(" OR ")}
    assert in_keys == or_keys


def test_pipeline_freshness_targets_carried_with_threshold_days():
    import pipeline_freshness_monitor as pfm

    for name, kind, spec, days, _ in pfm.REGISTRY:
        c = CONTRACTS.get(f"pfm.{name}")
        if c is None:
            assert name in ("hermes_canonical", "rotation_summary")  # already named by a registry output_signal
            continue
        assert c["max_age_hours"] == days * 24 and c["basis"] == "trading_days"
        if kind == "table":
            table, col, where = spec
            assert (c["signal"]["table"], c["signal"]["column"], c["signal"].get("where")) == (table, col, where)
        else:
            assert c["signal"] == {"kind": "file_mtime", "path": spec}


def test_system_freshness_fresh_checks_carried_with_severity_and_weekday_rule():
    import system_freshness_monitor as sfm

    for e in sfm.REGISTRY:
        if e["kind"] != "fresh":
            continue
        c = CONTRACTS.get(f"sfm.{e['key']}")
        if e.get("agg") == "min":
            assert c is None  # topic_monitor oldest-item check: not a db_max, a ruling
            continue
        assert c["signal"]["table"] == e["table"] and c["signal"]["column"] == e.get("ts_col", "created_at")
        assert c["max_age_hours"] == e["max_age_h"] and c["severity"] == e["sev"]
        assert c["basis"] == ("trading_days" if e.get("weekday_only") else "wall_clock")


# ── detection ─────────────────────────────────────────────────────────────────────────────────────────

def _obs(ts):
    return lambda sig: {"last_output_at": ts, "readable": True, "detail": "fake"}


NOW = dt.datetime(2026, 10, 14, 15, 0, tzinfo=UTC)  # Wednesday


def test_stale_store_raises_record_only_stale_output_and_fresh_does_not():
    c = _contract()
    rows = sbd.detect_freshness(contracts=[c], lanes=[], sla_by_lane={}, observe=_obs(NOW - dt.timedelta(hours=30)), now=NOW)
    assert [r["kind"] for r in rows] == ["STALE_OUTPUT"] and rows[0]["lane_id"] == "freshness:t.store"
    assert rows[0]["evidence"]["severity"] == "P2" and rows[0]["evidence"]["source"] == "scripts/x.py:1"
    assert "STALE_OUTPUT" in sbd.RECORD_ONLY_KINDS and "STALE_OUTPUT" in sbd.KINDS
    assert sbd.detect_freshness(contracts=[c], lanes=[], sla_by_lane={}, observe=_obs(NOW - dt.timedelta(hours=2)), now=NOW) == []


def test_unreadable_and_never_produced_are_reported():
    c = _contract()
    unread = sbd.detect_freshness(contracts=[c], lanes=[], sla_by_lane={},
                                  observe=lambda s: {"last_output_at": None, "readable": False}, now=NOW)
    never = sbd.detect_freshness(contracts=[c], lanes=[], sla_by_lane={}, observe=_obs(None), now=NOW)
    assert "UNVERIFIABLE" in unread[0]["evidence"]["note"] and never[0]["evidence"]["note"] == "never produced"


def test_a_contract_on_a_retired_lane_is_not_judged_and_breach_ids_are_per_contract():
    lane = {"lane_id": "a", "state": "RETIRED", "scheduler": {"kind": "none"}}
    stale = _obs(NOW - dt.timedelta(days=9))
    assert sbd.detect_freshness(contracts=[_contract(lane_id="a")], lanes=[lane], sla_by_lane={}, observe=stale, now=NOW) == []
    lane["state"] = "ACTIVE"
    rows = sbd.detect_freshness(contracts=[_contract(lane_id="a", key="k.one"), _contract(lane_id="a", key="k.two")],
                                lanes=[lane], sla_by_lane={}, observe=stale, now=NOW)
    assert len({r["breach_id"] for r in rows}) == 2 and {r["lane_id"] for r in rows} == {"a"}


def test_trading_day_limit_extends_over_the_weekend_only(monkeypatch):
    monkeypatch.setattr(sbd, "_is_trading_day", lambda d: d.weekday() < 5)
    monday_6 = dt.datetime(2026, 10, 12, 6, 0, tzinfo=ET)
    assert sbd._trading_day_limit_h(26, monday_6) == 74  # reaches Sun, then Sat, stops at Fri
    assert sbd._trading_day_limit_h(26, dt.datetime(2026, 10, 14, 12, 0, tzinfo=ET)) == 26  # Wednesday
    # Friday 15:55 prices are fine on Monday morning, stale by Tuesday noon
    c = _contract(basis="trading_days", max_age_hours=26)
    fri = dt.datetime(2026, 10, 9, 15, 55, tzinfo=ET)
    assert sbd.detect_freshness(contracts=[c], lanes=[], sla_by_lane={}, observe=_obs(fri), now=monday_6.astimezone(UTC)) == []
    tue = dt.datetime(2026, 10, 13, 12, 0, tzinfo=ET).astimezone(UTC)
    assert len(sbd.detect_freshness(contracts=[c], lanes=[], sla_by_lane={}, observe=_obs(fri), now=tue)) == 1


def test_lane_due_follows_job_coverage_semantics_for_a_cron_lane():
    # job_coverage: allowed = max(cadence, idle + min(cadence, 1h)). A 3 h job whose cron window ended 20:45 ET
    # is not stale at 23:00 ET with output from 20:00 ET, and is stale with output from 19:00 ET.
    lane = {"lane_id": "w", "state": "ACTIVE", "expected_cadence_hours": 3,
            "scheduler": {"kind": "cron", "expression": "*/15 10-20 * * *"}}
    now = dt.datetime(2026, 10, 14, 23, 0, tzinfo=ET).astimezone(UTC)
    c = _contract(lane_id="w", basis="lane_due", max_age_hours=3)
    sla = {"w": {"max_run_s": 60}}
    ok = sbd.detect_freshness(contracts=[c], lanes=[lane], sla_by_lane=sla,
                              observe=_obs(dt.datetime(2026, 10, 14, 20, 0, tzinfo=ET)), now=now)
    late = sbd.detect_freshness(contracts=[c], lanes=[lane], sla_by_lane=sla,
                                observe=_obs(dt.datetime(2026, 10, 14, 19, 30, tzinfo=ET)), now=now)
    assert ok == [] and len(late) == 1 and late[0]["evidence"]["basis"].startswith("lane_due:cron")
    # next morning 09:00 ET (outside the window): output from 20:00 ET last night is still fine
    morning = dt.datetime(2026, 10, 15, 9, 0, tzinfo=ET).astimezone(UTC)
    assert sbd.detect_freshness(contracts=[c], lanes=[lane], sla_by_lane=sla,
                                observe=_obs(dt.datetime(2026, 10, 14, 20, 0, tzinfo=ET)), now=morning) == []


def test_lane_due_on_a_systemd_lane_falls_back_to_max_age():
    lane = {"lane_id": "s", "state": "ACTIVE", "expected_cadence_hours": 20,
            "scheduler": {"kind": "systemd", "expression": "s.timer"}}
    c = _contract(lane_id="s", basis="lane_due", max_age_hours=30)
    assert sbd.detect_freshness(contracts=[c], lanes=[lane], sla_by_lane={}, observe=_obs(NOW - dt.timedelta(hours=29)), now=NOW) == []
    rows = sbd.detect_freshness(contracts=[c], lanes=[lane], sla_by_lane={}, observe=_obs(NOW - dt.timedelta(hours=31)), now=NOW)
    assert rows and rows[0]["evidence"]["basis"] == "wall_clock:30h"


def test_input_starvation_maps_liveness_findings_only():
    doc = {"lanes": [
        {"lane": "cio_runs", "status": "STARVED", "produced": 0, "attempted": 55, "window_hours": 24},
        {"lane": "mem", "status": "NO_ELIGIBLE_INPUT", "produced": 0, "attempted": 4, "eligible": 0},
        {"lane": "lin", "status": "UNKNOWN", "detail": "probe failed: OSError"},
        {"lane": "ok", "status": "LIVE", "produced": 3, "attempted": 3},
        {"lane": "q", "status": "QUIET", "produced": 0, "attempted": 0},
    ]}
    rows = sbd.detect_input_starvation(liveness=doc, now=NOW)
    assert [(r["lane_id"], r["evidence"]["status"]) for r in rows] == [
        ("liveness:cio_runs", "STARVED"), ("liveness:mem", "NO_ELIGIBLE_INPUT"), ("liveness:lin", "UNKNOWN")]
    assert {r["kind"] for r in rows} == {"INPUT_STARVATION"} and rows[0]["level"] == 2 and rows[1]["level"] == 1
    assert "INPUT_STARVATION" in sbd.RECORD_ONLY_KINDS


# ── main(): throttle, record-only, dry run ────────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    code = tmp_path / "code"
    (code / "config").mkdir(parents=True)
    state = tmp_path / "state"
    rt = state / "data" / "runtime"
    rt.mkdir(parents=True)
    reg = {"lanes": [], "freshness_contracts": [
        _contract(key="t.file", signal={"kind": "file_mtime", "path": "data/runtime/never.json"})]}
    (code / "config" / "lane_registry.json").write_text(json.dumps(reg))
    (rt / "supervisor_sla_seed.json").write_text(json.dumps({"rows": []}))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_HEARTBEAT_DIR", str(tmp_path / "hb"))
    monkeypatch.setattr(sbd, "_read_only_db_query", lambda: None)
    fake_db = type(sys)("db_adapter")
    fake_db._get_conn = lambda: (_ for _ in ()).throw(RuntimeError("no db in tests"))
    monkeypatch.setitem(sys.modules, "db_adapter", fake_db)
    import supervisor_heartbeat as hbmod

    monkeypatch.setattr(hbmod, "beat", lambda *a, **k: {"pg": "skipped"})
    calls = []
    monkeypatch.setattr(sbd, "_evaluate_liveness", lambda root: calls.append(root) or {
        "lanes": [{"lane": "cio_runs", "status": "STARVED", "produced": 0, "attempted": 9}]})
    ladder = []
    monkeypatch.setattr(sbd, "_ladder_l4_l5", lambda rows, *a, **k: ladder.append(list(rows)) or {})
    monkeypatch.setattr(sbd, "_self_heal_l1_l2", lambda rows, *a, **k: ladder.append(list(rows)) or {})
    return {"code": code, "state": state, "rt": rt, "calls": calls, "ladder": ladder, "tmp": tmp_path}


def _main(monkeypatch, env, *argv):
    monkeypatch.setattr(sys, "argv", ["supervisor_breach_detector.py", "--root", str(env["code"]),
                                      "--state-root", str(env["state"]), *argv])
    return sbd.main()


def _snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def test_dry_run_evaluates_slow_checks_and_writes_nothing(env, monkeypatch, capsys):
    before = _snapshot(env["tmp"])
    assert _main(monkeypatch, env, "--dry-run", "--slow-checks", "always") == 0
    out = capsys.readouterr().out
    assert '"STALE_OUTPUT": 1' in out and '"INPUT_STARVATION": 1' in out
    assert _snapshot(env["tmp"]) == before and env["ladder"] == []


def test_write_records_both_kinds_but_never_hands_them_to_the_ladder(env, monkeypatch):
    assert _main(monkeypatch, env, "--write") == 0
    led = [json.loads(x) for x in (env["rt"] / "supervisor_breaches.jsonl").read_text().splitlines()]
    assert sorted(r["kind"] for r in led) == ["INPUT_STARVATION", "STALE_OUTPUT"]
    assert env["ladder"] and all(rows == [] for rows in env["ladder"])
    state = json.loads((env["rt"] / sbd.SLOW_CHECKS_STATE).read_text())
    assert set(state) == {"freshness_contracts", "input_starvation"}
    assert env["calls"] == [env["state"]]


def test_auto_mode_throttles_the_slow_checks(env, monkeypatch, capsys):
    assert _main(monkeypatch, env, "--write") == 0
    capsys.readouterr()
    assert _main(monkeypatch, env, "--write") == 0  # same half hour: not due
    out = capsys.readouterr().out
    assert len(env["calls"]) == 1 and '"breaches": 0' in out and '"last_evaluated_at"' in out
    assert _main(monkeypatch, env, "--write", "--slow-checks", "always") == 0
    assert len(env["calls"]) == 2


def test_never_skips_and_a_failing_slow_check_does_not_stop_the_run(env, monkeypatch, capsys):
    assert _main(monkeypatch, env, "--dry-run", "--slow-checks", "never") == 0
    assert '"breaches": 0' in capsys.readouterr().out and env["calls"] == []

    def boom(root):
        raise OSError("unreadable")

    monkeypatch.setattr(sbd, "_evaluate_liveness", boom)
    assert _main(monkeypatch, env, "--dry-run", "--slow-checks", "always") == 0
    out = capsys.readouterr().out
    assert "OSError: unreadable" in out and '"STALE_OUTPUT": 1' in out
