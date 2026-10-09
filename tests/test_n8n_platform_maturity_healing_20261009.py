"""N8nPlatformMaturity@v1 dimensions 6 (self-healing proven) and 9 (recovery): hermetic, deterministic.

Every test uses tmp_path for the state root, repo and home, a fake command runner and a fixed ``now``.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))

from n8n_maturity import core  # noqa: E402
from n8n_maturity import dims_healing as h  # noqa: E402

NOW = dt.datetime(2026, 10, 9, 20, 0, tzinfo=dt.timezone.utc)
REQUIRED_CATEGORIES = {"retry", "dead_letter", "watchdog", "health_agent", "health_tick_step", "escalation",
                       "approval", "queue_recovery", "token_refresh", "incident_routing", "governance",
                       "systemd_restart"}


def _iso(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


class FakeRunner:
    def __init__(self, table: dict | None = None):
        self.table = table or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        for key, val in self.table.items():
            if key in " ".join(argv):
                return val
        return (1, "", "no fake")


REAL_CONFIG = json.loads((PROJ / "config" / "n8n_platform_maturity.json").read_text())


def _config(**dim_overrides) -> dict:
    """The real config file, with per-dimension overrides ({dim: {key: value}}) — never a hand-built stub."""
    cfg = copy.deepcopy(REAL_CONFIG)
    for dim, upd in dim_overrides.items():
        cfg["dimensions"][dim].update(upd)
    return cfg


def _probe(tmp_path, *, runner=None, config=None, env=None):
    for d in ("state", "proj/config", "home", "dev"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    e = {"HOME": str(tmp_path / "home"), "TRADEAI_DEV_TREE": str(tmp_path / "dev")}
    e.update(env or {})
    return core.Probe(root=tmp_path / "state", proj=tmp_path / "proj", now=NOW, env=e,
                      config=config if config is not None else _config(),
                      runner=runner or FakeRunner())


def _write(p: Path, text: str, *, mtime_hours_ago: float | None = None) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if mtime_hours_ago is not None:
        t = (NOW - dt.timedelta(hours=mtime_hours_ago)).timestamp()
        os.utime(p, (t, t))
    return p


def _mech(mid, ev, pred, category="watchdog", code="scripts/x.py"):
    return {"id": mid, "name": mid, "category": category, "code": code, "evidence_source": ev,
            "success_predicate": {"description": "test", **pred}, "expected": "test"}


def _inventory(probe, mechs):
    (probe.proj / "scripts").mkdir(parents=True, exist_ok=True)
    (probe.proj / "scripts" / "x.py").write_text("# stub\n")
    doc = {"schema": h.INVENTORY_SCHEMA, "bases": {"devtree": "~/dev"}, "mechanisms": mechs}
    _write(probe.proj / h.INVENTORY_REL, json.dumps(doc))
    return doc


def _eval(probe, mech, window=336.0, tail=0):
    return h.evaluate_mechanism(probe, {"bases": {}}, mech, default_window_h=window, default_tail=tail)


# --------------------------------------------------------------------------- the real inventory

def test_real_inventory_self_check():
    doc = json.loads((PROJ / h.INVENTORY_REL).read_text())
    assert doc["schema"] == "SelfHealingMechanisms@v1"
    mechs = doc["mechanisms"]
    assert len(mechs) >= 35
    ids = [m["id"] for m in mechs]
    assert len(ids) == len(set(ids)), "mechanism ids must be unique"
    for m in mechs:
        assert m.get("evidence_source", {}).get("kind") in h.KINDS, m["id"]
        assert m.get("success_predicate", {}).get("description"), m["id"]
        if not m.get("code_external"):
            assert (PROJ / m["code"]).exists(), f"{m['id']}: {m['code']} not in repo"
    assert h.inventory_problems(doc, PROJ) == []
    assert REQUIRED_CATEGORIES <= {m["category"] for m in mechs}
    # not-built mechanisms are honest: absent evidence
    kinds = {m["id"]: m["evidence_source"]["kind"] for m in mechs}
    assert kinds["n8n_run_retry_wrapper"] == "absent" and kinds["n8n_run_dead_letter_queue"] == "absent"
    assert "/home/" not in (PROJ / h.INVENTORY_REL).read_text()


def test_inventory_problems_flags_bad_rows(tmp_path):
    p = _probe(tmp_path)
    good = _mech("a", {"kind": "absent"}, {"field": "x", "equals": 1})
    doc = {"schema": h.INVENTORY_SCHEMA, "mechanisms": [
        good, dict(good),  # duplicate id
        _mech("b", {"kind": "nope"}, {"field": "x", "equals": 1}),
        _mech("c", {"kind": "jsonl", "path": "/abs/x.jsonl"}, {"field": "x", "equals": 1}),
        _mech("d", {"kind": "journal"}, {"regex": "x"}),
        _mech("e", {"kind": "absent"}, {}, code="scripts/missing.py"),
    ]}
    probs = "\n".join(h.inventory_problems(doc, p.proj))
    for frag in ("a: duplicate id", "unknown evidence kind", "must be relative", "needs unit",
                 "no machine condition", "code path not in repo"):
        assert frag in probs


def test_load_inventory_rejects_wrong_schema(tmp_path):
    p = _probe(tmp_path)
    assert h.load_inventory(p)[0] is None
    _write(p.proj / h.INVENTORY_REL, json.dumps({"schema": "Other@v1", "mechanisms": [1]}))
    doc, err = h.load_inventory(p)
    assert doc is None and "schema" in err


# --------------------------------------------------------------------------- predicates

def test_cond_match_operators():
    rec = {"a": {"b": 3}, "s": "OK", "flag": True, "one": 1, "l": [1], "e": []}
    assert h.cond_match(rec, {"field": "a.b", "gte": 3})
    assert not h.cond_match(rec, {"field": "a.b", "gte": 4})
    assert h.cond_match(rec, {"field": "s", "in": ["OK", "WARN"]})
    assert h.cond_match(rec, {"field": "s", "not_in": ["NO_ACTION", None]})
    assert h.cond_match(rec, {"field": "flag", "equals": True})
    assert not h.cond_match(rec, {"field": "one", "equals": True}), "True must not match 1"
    assert h.cond_match(rec, {"field": "one", "equals": 1})
    assert h.cond_match(rec, {"field": "l", "nonempty": True}) and not h.cond_match(rec, {"field": "e", "nonempty": True})
    assert h.cond_match(rec, {"field": "a", "regex": r'"b": 3'})
    assert h.cond_match(rec, {"all": [{"field": "s", "equals": "OK"}, {"field": "flag", "truthy": True}]})
    assert h.cond_match(rec, {"any": [{"field": "s", "equals": "X"}, {"field": "one", "equals": 1}]})
    assert not h.cond_match(rec, {"field": "missing", "truthy": True})


# --------------------------------------------------------------------------- evaluators per kind

def test_jsonl_states_and_window(tmp_path):
    p = _probe(tmp_path)
    rows = [{"at": _iso(1), "type": "q", "outcome": "CLEARED"},
            {"at": _iso(2), "type": "q", "outcome": "INEFFECTIVE"},
            {"at": _iso(1000), "type": "s", "outcome": "CLEARED"},
            {"at": _iso(3), "type": "s", "outcome": "INEFFECTIVE"}]
    _write(p.root / "logs/rem.jsonl", "\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    ev = {"kind": "jsonl", "path": "logs/rem.jsonl", "ts_key": "at"}
    pred = {"field": "outcome", "equals": "CLEARED"}
    r = _eval(p, _mech("all", ev, pred))
    assert r["state"] == h.PROVEN and r["successes"] == 2 and r["successes_window"] == 1
    assert r["last_success_ts"] == _iso(1)
    r = _eval(p, _mech("s", dict(ev, filter={"field": "type", "equals": "s"}), pred))
    assert r["state"] == h.RAN_NOT_HEALED, "the only success is outside the window"
    assert r["records"] == 2 and r["successes_window"] == 0
    r = _eval(p, _mech("min", ev, dict(pred, min_count=2)))
    assert r["state"] == h.RAN_NOT_HEALED
    r = _eval(p, _mech("missing", dict(ev, path="logs/none.jsonl"), pred))
    assert r["state"] == h.NO_EVIDENCE and r["note"] == "evidence file absent"


def test_json_document(tmp_path):
    p = _probe(tmp_path)
    _write(p.root / "data/runtime/fanin.json", json.dumps({"as_of": _iso(0.1), "recovered": [], "open": 3}))
    ev = {"kind": "json", "path": "data/runtime/fanin.json", "ts_key": "as_of"}
    assert _eval(p, _mech("f", ev, {"field": "recovered", "nonempty": True}))["state"] == h.RAN_NOT_HEALED
    _write(p.root / "data/runtime/fanin.json", json.dumps({"as_of": _iso(0.1), "recovered": [{"id": 1}]}))
    assert _eval(p, _mech("f", ev, {"field": "recovered", "nonempty": True}))["state"] == h.PROVEN


def test_jsonstream_dated_and_undated_tail(tmp_path):
    p = _probe(tmp_path)
    blocks = [{"checked_at": _iso(5), "restarted": None}, {"checked_at": _iso(4), "restarted": {"rc": 0}}]
    _write(p.root / "logs/wd.log", "[telegram] noise\n" + "\n".join(json.dumps(b, indent=2) for b in blocks) + "\n{broken\n")
    ev = {"kind": "jsonstream", "path": "logs/wd.log", "ts_key": "checked_at"}
    r = _eval(p, _mech("wd", ev, {"field": "restarted", "truthy": True}))
    assert r["state"] == h.PROVEN and r["records"] == 2 and not r["undated"]
    # undated stream: only the last N records count, dated with the file mtime
    undated = [{"local": {"deleted": ["x"]}}] + [{"local": {"deleted": []}}] * 3
    _write(p.root / "logs/be.log", "\n".join(json.dumps(b, indent=2) for b in undated), mtime_hours_ago=1)
    ev2 = {"kind": "jsonstream", "path": "logs/be.log", "undated_tail_lines": 2}
    pred2 = {"field": "local.deleted", "nonempty": True}
    r = _eval(p, _mech("be", ev2, pred2))
    assert r["state"] == h.RAN_NOT_HEALED and r["undated"] and r["records"] == 2
    r = _eval(p, _mech("be", dict(ev2, undated_tail_lines=4), pred2))
    assert r["state"] == h.PROVEN
    _write(p.root / "logs/be.log", "\n".join(json.dumps(b) for b in undated), mtime_hours_ago=1000)
    assert _eval(p, _mech("be", dict(ev2, undated_tail_lines=4), pred2))["state"] == h.RAN_NOT_HEALED


def test_log_ts_regex_timezone_and_bases(tmp_path):
    p = _probe(tmp_path)
    # local ET timestamps: 2026-10-09 15:30 EDT = 19:30Z (inside a 1 h window); 09-01 is outside
    text = ("2026-09-01 10:00:00,1 [x] verified clear (abc)\n"
            "2026-10-09 15:30:00,5 [x] Tier 1\n"
            "   verified clear (no_verify)\n"
            "2026-10-09 15:31:00,5 [x] verified clear (jobs_0)\n")
    _write(tmp_path / "dev/logs/esc.log", text)
    ev = {"kind": "log", "base": "devtree", "path": "logs/esc.log", "ts_regex": r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)",
          "tz": "America/New_York", "line_regex": "verified clear"}
    pred = {"regex": r"verified clear \((?!no_verify)", "window_hours": 1}
    r = _eval(p, _mech("esc", ev, pred))
    assert r["state"] == h.PROVEN and r["successes"] == 2 and r["successes_window"] == 1
    assert r["last_success_ts"].startswith("2026-10-09T15:31:00-04:00")
    assert r["records"] == 3, "the continuation line inherits the previous timestamp"
    # home base + UTC + undated tail
    _write(tmp_path / "home/logs/w.log", "[2026-10-09 19:00:00 UTC] UNRESPONSIVE after 3 probes — killing pid 1\n")
    ev2 = {"kind": "log", "base": "home", "path": "logs/w.log", "ts_regex": r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC\]", "tz": "UTC"}
    assert _eval(p, _mech("w", ev2, {"regex": "killing pid"}))["state"] == h.PROVEN
    _write(p.root / "logs/reaper.log", "x · 1 proc(s) reaped\n" + "x · 0 proc(s) reaped\n" * 5, mtime_hours_ago=0.5)
    ev3 = {"kind": "log", "path": "logs/reaper.log", "undated_tail_lines": 3}
    r = _eval(p, _mech("r", ev3, {"regex": r"[1-9]\d* proc\(s\) reaped"}))
    assert r["state"] == h.RAN_NOT_HEALED and r["undated"]
    assert _eval(p, _mech("r", dict(ev3, undated_tail_lines=6), {"regex": r"[1-9]\d* proc\(s\) reaped"}))["state"] == h.PROVEN


def test_sqlite_read_only(tmp_path):
    p = _probe(tmp_path)
    db = p.root / "data/governance/ledger.sqlite"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE events (k TEXT, dead_letter INTEGER, updated_at TEXT)")
    con.execute("INSERT INTO events VALUES ('a', 0, ?)", (_iso(1),))
    con.commit()
    ev = {"kind": "sqlite", "path": "data/governance/ledger.sqlite", "table": "events", "ts_key": "updated_at"}
    pred = {"field": "dead_letter", "equals": 1}
    assert _eval(p, _mech("dlq", ev, pred))["state"] == h.RAN_NOT_HEALED
    con.execute("INSERT INTO events VALUES ('b', 1, ?)", (_iso(2),))
    con.commit()
    con.close()
    assert _eval(p, _mech("dlq", ev, pred))["state"] == h.PROVEN
    assert _eval(p, _mech("bad", dict(ev, table="events; DROP"), pred))["state"] == h.NO_EVIDENCE
    con = sqlite3.connect(db)
    con.execute("DELETE FROM events")
    con.commit()
    con.close()
    assert _eval(p, _mech("empty", ev, pred))["state"] == h.NO_EVIDENCE


def test_journal_via_fake_runner(tmp_path):
    out = ("2026-10-09T15:00:00-04:00 host systemd[1]: portfolio-server.service: Scheduled restart job, restart counter is at 1.\n"
           "-- Boot abc --\n"
           "2026-10-09T15:00:05-04:00 host systemd[1]: Started portfolio-server.service.\n")
    runner = FakeRunner({"-u portfolio-server.service": (0, out, ""), "-u dead.service": (1, "", "boom")})
    p = _probe(tmp_path, runner=runner)
    ev = {"kind": "journal", "unit": "portfolio-server.service", "window_hours": 168}
    r = _eval(p, _mech("ps", ev, {"regex": "Scheduled restart job"}))
    assert r["state"] == h.PROVEN and r["records"] == 2
    assert r["last_success_ts"] == "2026-10-09T15:00:00-04:00"
    argv = runner.calls[0]
    assert argv[:4] == ["journalctl", "--user", "-u", "portfolio-server.service"]
    assert argv[argv.index("--since") + 1] == "2026-10-02 20:00:00 UTC"
    assert _eval(p, _mech("ps", ev, {"regex": "nope"}))["state"] == h.RAN_NOT_HEALED
    r = _eval(p, _mech("d", {"kind": "journal", "unit": "dead.service"}, {"regex": "x"}))
    assert r["state"] == h.NO_EVIDENCE and "rc=1" in r["note"]


def test_systemd_show(tmp_path):
    runner = FakeRunner({"show a.service": (0, "NRestarts=1\nActiveState=active\nLoadState=loaded\nRestart=always\n", ""),
                         "show b.service": (0, "NRestarts=0\nActiveState=active\nLoadState=loaded\n", ""),
                         "show c.service": (0, "LoadState=not-found\n", "")})
    p = _probe(tmp_path, runner=runner)
    pred = {"all": [{"field": "NRestarts", "gte": 1}, {"field": "ActiveState", "equals": "active"}]}
    assert _eval(p, _mech("a", {"kind": "systemd", "unit": "a.service"}, pred))["state"] == h.PROVEN
    assert _eval(p, _mech("b", {"kind": "systemd", "unit": "b.service"}, pred))["state"] == h.RAN_NOT_HEALED
    assert _eval(p, _mech("c", {"kind": "systemd", "unit": "c.service"}, pred))["state"] == h.NO_EVIDENCE


PSQL_EV = {"kind": "psql", "database": "trade_ai", "user": "trade_ai", "host": "localhost",
           "table": "broker_oauth_token_audit", "ts_key": "created_at", "columns": ["event", "status", "created_at"]}
PSQL_PRED = {"all": [{"field": "event", "equals": "refresh_rotation"}, {"field": "status", "equals": "ok"}],
             "window_hours": 24}


def test_psql_proven_via_fake_runner(tmp_path):
    rows = [{"event": "refresh_rotation", "status": "ok", "created_at": _iso(2)},
            {"event": "refresh_rotation", "status": "error", "created_at": _iso(3)}]
    runner = FakeRunner({"broker_oauth_token_audit": (0, "\n".join(json.dumps(r) for r in rows) + "\n", "")})
    p = _probe(tmp_path, runner=runner)
    r = _eval(p, _mech("s", PSQL_EV, PSQL_PRED))
    assert r["state"] == h.PROVEN and r["successes_window"] == 1 and r["records"] == 2
    argv = runner.calls[0]
    assert core.is_read_only(argv)
    assert argv[:9] == ["psql", "-X", "-At", "-h", "localhost", "-U", "trade_ai", "-d", "trade_ai"]
    sql = argv[-1]
    assert core.is_safe_sql(sql)
    assert "SELECT event, status, created_at FROM broker_oauth_token_audit" in sql
    assert "*" not in sql and "fingerprint" not in sql and "PASSWORD" not in " ".join(argv).upper()
    assert argv == h.psql_source_argv(PSQL_EV, p.since(24))
    # only failed rotations in the window -> RAN_NOT_HEALED
    runner.table = {"broker_oauth_token_audit": (0, json.dumps(rows[1]) + "\n", "")}
    assert _eval(p, _mech("s", PSQL_EV, PSQL_PRED))["state"] == h.RAN_NOT_HEALED


def test_psql_auth_failure_is_no_evidence(tmp_path):
    runner = FakeRunner({"broker_oauth_token_audit": (2, "", "password authentication failed")})
    p = _probe(tmp_path, runner=runner)
    r = _eval(p, _mech("s", PSQL_EV, PSQL_PRED))
    assert r["state"] == h.NO_EVIDENCE and r["note"] == "psql auth/connect failed rc=2"


@pytest.mark.parametrize("bad", [{"columns": []}, {"columns": ["*"]}, {"table": "t; DROP"}, {"user": ""},
                                 {"columns": ["event", "pg_sleep(1)"]}])
def test_psql_invalid_spec_never_runs(tmp_path, bad):
    runner = FakeRunner()
    p = _probe(tmp_path, runner=runner)
    r = _eval(p, _mech("s", dict(PSQL_EV, **bad), PSQL_PRED))
    assert r["state"] == h.NO_EVIDENCE and runner.calls == []


def test_absent_kind(tmp_path):
    p = _probe(tmp_path)
    r = _eval(p, _mech("x", {"kind": "absent", "reason": "not built yet"}, {"field": "x", "equals": 1}))
    assert r["state"] == h.NO_EVIDENCE and r["note"] == "not built yet"


def test_undated_tail_default_from_config(tmp_path):
    p = _probe(tmp_path)
    _write(p.root / "logs/reaper.log", "x · 1 proc(s) reaped\n", mtime_hours_ago=0.5)
    m = _mech("r", {"kind": "log", "path": "logs/reaper.log"}, {"regex": r"[1-9]\d* proc\(s\) reaped"})
    assert _eval(p, m, tail=0)["state"] == h.NO_EVIDENCE, "no tail configured -> undated lines are not trusted"
    assert _eval(p, m, tail=5)["state"] == h.PROVEN


def test_every_real_inventory_command_is_read_only(tmp_path):
    """Run the real inventory against a recording runner: every argv issued passes core.is_read_only and
    none is refused by the probe."""
    runner = FakeRunner()
    p = _probe(tmp_path, runner=runner)
    doc = json.loads((PROJ / h.INVENTORY_REL).read_text())
    results = h.evaluate_inventory(p, doc, 336.0, 0)
    kinds = [m["evidence_source"]["kind"] for m in doc["mechanisms"]]
    assert len(runner.calls) == sum(k in ("journal", "systemd", "psql") for k in kinds)
    assert "psql" in kinds
    for argv in runner.calls:
        assert core.is_read_only(argv), argv[:4]
    assert not any("refuses" in (r["note"] or "") for r in results)


# --------------------------------------------------------------------------- dimension 6

def _tick(p, *, ok_runs: int, total: int, last_ok: bool = True, last_age_min: float = 3):
    rows = [{"as_of": _iso(i * 0.08), "mode": "apply", "ok": i >= total - ok_runs} for i in range(total)]
    _write(p.root / "data/runtime/health_tick_history.jsonl", "\n".join(json.dumps(r) for r in rows))
    _write(p.root / "data/runtime/health_tick_last.json",
           json.dumps({"as_of": _iso(last_age_min / 60), "ok": last_ok, "mode": "apply", "failed": [] if last_ok else ["x"]}))


def _heal_inventory(p, proven: int, total: int):
    rows = [{"at": _iso(1), "id": i, "outcome": "CLEARED" if i < proven else "INEFFECTIVE"} for i in range(total)]
    _write(p.root / "logs/rem.jsonl", "\n".join(json.dumps(r) for r in rows))
    mechs = [_mech(f"m{i}", {"kind": "jsonl", "path": "logs/rem.jsonl", "ts_key": "at", "filter": {"field": "id", "equals": i}},
                   {"field": "outcome", "equals": "CLEARED"}) for i in range(total)]
    _inventory(p, mechs)


def test_self_healing_unverified_without_evidence(tmp_path):
    r = h.collect_self_healing(_probe(tmp_path))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0 and not r["gate"]["pass"]


@pytest.mark.parametrize("proven,ok_runs,last_ok,age,passes", [
    (4, 99, True, 3, True),     # exactly 80% proven and 99% tick ok -> gate
    (5, 100, True, 3, True),    # 100% / 100% -> 10
    (3, 100, True, 3, False),   # 60% proven
    (4, 98, True, 3, False),    # tick ok rate 98% < 99%
    (4, 100, False, 3, False),  # latest tick exited 1
    (4, 100, True, 60, False),  # latest tick receipt stale
])
def test_self_healing_gate_boundaries(tmp_path, proven, ok_runs, last_ok, age, passes):
    p = _probe(tmp_path)
    _heal_inventory(p, proven, 5)
    _tick(p, ok_runs=ok_runs, total=100, last_ok=last_ok, last_age_min=age)
    r = h.collect_self_healing(p)
    assert r["gate"]["pass"] is passes
    assert r["metrics"]["proven"] == proven and r["metrics"]["mechanisms_total"] == 5
    if passes:
        assert r["score"] >= 8.0
        if proven == 5 and ok_runs == 100:
            assert r["score"] == 10.0
    else:
        assert r["score"] <= 7.9


def test_self_healing_partial_without_tick(tmp_path):
    p = _probe(tmp_path)
    _heal_inventory(p, 5, 5)
    r = h.collect_self_healing(p)
    assert r["status"] == core.PARTIAL and r["score"] == 5.0 and not r["gate"]["pass"]
    assert any("health_tick_exit0" in n for n in r["notes"])


def test_self_healing_thresholds_from_config(tmp_path):
    cfg = _config(self_healing={"proven_ratio_gate": 0.6, "health_tick_ok_rate_gate": 0.9})
    p = _probe(tmp_path, config=cfg)
    _heal_inventory(p, 3, 5)
    _tick(p, ok_runs=95, total=100)
    r = h.collect_self_healing(p)
    assert r["gate"]["pass"] and r["score"] >= 8.0


def test_self_healing_empty_inventory_is_not_full_marks(tmp_path):
    p = _probe(tmp_path)
    _write(p.proj / h.INVENTORY_REL, json.dumps({"schema": h.INVENTORY_SCHEMA, "mechanisms": []}))
    _tick(p, ok_runs=100, total=100)
    r = h.collect_self_healing(p)
    assert r["metrics"]["proven_ratio"] is None and r["metrics"]["s_proven"] is None
    assert r["status"] == core.PARTIAL and r["score"] == 5.0 and not r["gate"]["pass"]
    # an inventory whose rows are all non-objects is empty too
    _write(p.proj / h.INVENTORY_REL, json.dumps({"schema": h.INVENTORY_SCHEMA, "mechanisms": [1, "x"]}))
    r = h.collect_self_healing(p)
    assert r["metrics"]["proven_ratio"] is None and not r["gate"]["pass"]


def test_health_tick_zero_receipts_in_window_is_unverified(tmp_path):
    p = _probe(tmp_path)
    _heal_inventory(p, 5, 5)
    rows = [{"as_of": _iso(30 + i), "mode": "apply", "ok": True} for i in range(10)]  # all outside 24 h
    _write(p.root / "data/runtime/health_tick_history.jsonl", "\n".join(json.dumps(r) for r in rows))
    t = h.health_tick_status(p)
    assert t["runs"] == 0 and t["ok_rate"] is None
    r = h.collect_self_healing(p)
    assert r["metrics"]["s_health_tick"] is None and r["status"] == core.PARTIAL and not r["gate"]["pass"]


def test_health_tick_single_stale_receipt_not_green(tmp_path):
    p = _probe(tmp_path)
    _heal_inventory(p, 5, 5)
    _write(p.root / "data/runtime/health_tick_last.json", json.dumps({"as_of": _iso(2), "ok": True, "mode": "apply"}))
    t = h.health_tick_status(p)
    assert t["last_fresh"] is False and t["ok_rate"] is None, "a stale receipt is not a sample"
    r = h.collect_self_healing(p)
    assert r["metrics"]["s_health_tick"] is None and not r["gate"]["pass"] and r["score"] <= 7.9
    # the same receipt, fresh and alone, is one sample (ok_rate 1/1) and the gate can pass
    _write(p.root / "data/runtime/health_tick_last.json", json.dumps({"as_of": _iso(0.05), "ok": True, "mode": "apply"}))
    t = h.health_tick_status(p)
    assert t["ok_rate"] == 1.0 and t["runs"] == 1 and t["ok_rate_basis"] == "latest_receipt"


def test_history_rows_without_timestamp_do_not_count(tmp_path):
    p = _probe(tmp_path)
    _write(p.root / "data/runtime/health_tick_history.jsonl", json.dumps({"mode": "apply", "ok": True}))
    assert h.health_tick_status(p)["runs"] == 0


@pytest.mark.parametrize("dim,key", [("self_healing", "proven_ratio_gate"), ("self_healing", "undated_tail_lines"),
                                     ("self_healing", "health_tick_window_hours"), ("self_healing", "proof_window_hours"),
                                     ("recovery", "backup_ok_score"), ("recovery", "n8n_lab_restore_drill_credit")])
def test_missing_config_key_is_unverified(tmp_path, dim, key):
    cfg = _config()
    del cfg["dimensions"][dim][key]
    p = _probe(tmp_path, config=cfg)
    with pytest.raises(core.ConfigError):
        p.need(dim, key)
    _heal_inventory(p, 5, 5)
    _tick(p, ok_runs=100, total=100)
    _bv(p)
    _rd(p)
    r = h.COLLECTORS[dim](p)
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0 and key in r["notes"][0]


@pytest.mark.parametrize("key", ["gate_score", "gate_cap"])
def test_missing_top_level_gate_key_is_unverified(tmp_path, key):
    cfg = _config()
    del cfg[key]
    p = _probe(tmp_path, config=cfg)
    with pytest.raises(core.ConfigError):
        core.need_top(cfg, key)
    assert h.collect_self_healing(p)["status"] == core.UNVERIFIED
    assert h.collect_recovery(p)["status"] == core.UNVERIFIED


def test_gate_cap_from_config(tmp_path):
    cfg = _config()
    cfg["gate_cap"] = 6.5
    p = _probe(tmp_path, config=cfg)
    cfg["dimensions"]["recovery"]["restore_drill_fail_score"] = 9.0  # mean 9.5 would pass 8.0; the cap holds it
    _bv(p)
    _rd(p, outcome="FAIL")
    r = h.collect_recovery(p)
    assert not r["gate"]["pass"] and r["score"] == 6.5


def test_recovery_scores_from_config(tmp_path):
    p = _probe(tmp_path, config=_config(recovery={"backup_warn_score": 7.0, "backup_ok_score": 9.0}))
    _bv(p, "WARN")
    _rd(p)
    assert h.collect_recovery(p)["metrics"]["s_backup"] == 7.0


# --------------------------------------------------------------------------- dimension 9

def _bv(p, verdict="OK", age_h=2):
    _write(p.root / "data/runtime/backup_verify_last.json", json.dumps({"schema": "BackupVerifyReceipt@v1", "as_of": _iso(age_h), "verdict": verdict}))


def _rd(p, outcome="PASS", age_h=24):
    _write(p.root / "data/runtime/trade_ai_restore_drill_last.json", json.dumps({"schema": "TradeAiRestoreDrill@v1", "as_of": _iso(age_h), "outcome": outcome}))


def _lab(p, ok=True, age_h=50):
    _write(p.root / "backups/n8n/n8n_lab_restore_drill_last.json", json.dumps({"finished": _iso(age_h), "ok": ok}))


def test_recovery_unverified_when_never_run(tmp_path):
    r = h.collect_recovery(_probe(tmp_path))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0 and not r["gate"]["pass"]


def test_recovery_gate_pass(tmp_path):
    p = _probe(tmp_path)
    _bv(p)
    _rd(p)
    r = h.collect_recovery(p)
    assert r["gate"]["pass"] and r["score"] == 10.0 and r["status"] == core.VERIFIED


@pytest.mark.parametrize("bv,rd,expect_score", [
    (("OK", 27), ("PASS", 24), 5.0),        # backup receipt 1 h past the 26 h freshness limit
    (("WARN", 2), ("PASS", 24), 7.5),       # WARN = 5 -> mean 7.5, capped below the gate
    (("OK", 2), ("FAIL", 24), 5.0),         # drill failed
    (("OK", 2), ("PASS", 36 * 24), 5.0),    # drill older than 35 days
])
def test_recovery_gate_failures(tmp_path, bv, rd, expect_score):
    p = _probe(tmp_path)
    _bv(p, *bv)
    _rd(p, *rd)
    r = h.collect_recovery(p)
    assert not r["gate"]["pass"] and r["score"] == expect_score


def test_recovery_lab_drill_partial_credit(tmp_path):
    p = _probe(tmp_path)
    _lab(p)
    r = h.collect_recovery(p)
    assert r["status"] == core.PARTIAL and r["score"] == 2.0 and not r["gate"]["pass"]
    assert r["metrics"]["s_drill"] == 4.0 and r["metrics"]["s_backup"] is None
    _lab(p, ok=False)
    assert h.collect_recovery(p)["score"] == 0.0


def test_collectors_registered():
    assert set(h.COLLECTORS) == {"self_healing", "recovery"}
