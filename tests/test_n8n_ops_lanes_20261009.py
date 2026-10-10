"""n8n ops lanes (2026-10-09): storage-watch, backup-verify, trade-ai-restore-drill.

Hermetic: every filesystem input lives under tmp_path, every subprocess goes through a fake runner, every
database connection is a fake that records SQL. No live host path is spelled out (check_test_host_paths).
The restore-drill tests pin the one destructive statement the lanes may issue: DROP DATABASE of the
throwaway database this run created, guarded by name regex + created-name + run-id marker.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import ops_lanes as ol  # noqa: E402
from scripts import storage_watch as sw  # noqa: E402
from scripts import backup_verify as bv  # noqa: E402
from scripts import trade_ai_restore_drill as rd  # noqa: E402
from scripts import n8n_workflow_templates as gen  # noqa: E402

CFG = ol.load_config()
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]}
REG = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]}
NEW_LANES = {
    "storage-watch": "data/runtime/storage_watch_last.json",
    "backup-verify": "data/runtime/backup_verify_last.json",
    "trade-ai-restore-drill": "data/runtime/trade_ai_restore_drill_last.json",
}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, query, params=None):
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.conn.log.append((self.conn.dbname, text, params))
        self._rows = self.conn.responder(text, params)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, log, responder, dbname):
        self.log, self.responder, self.dbname = log, responder, dbname

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        pass


def fake_connect_factory(responder):
    log: list = []

    def connect(params, dbname=None, read_only=True, timeout_ms=120000):
        return FakeConn(log, responder, dbname or params["dbname"])

    return connect, log


@pytest.fixture(autouse=True)
def _as_string(monkeypatch):
    """psycopg2.sql objects need a connection for as_string; render identifiers plainly for the fake.

    GitHub CI installs no Postgres driver: the fixture is then a no-op, and only the end-to-end drill
    tests (which build psycopg2.sql) skip; every guard test is pure and still runs.
    """
    try:
        from psycopg2 import sql
    except ImportError:
        return

    def render(obj, _ctx=None):
        if isinstance(obj, sql.Composed):
            return "".join(render(p) for p in obj.seq)
        if isinstance(obj, sql.Identifier):
            return ".".join('"' + s + '"' for s in obj.strings)
        if isinstance(obj, sql.Literal):
            return "'" + str(obj.wrapped) + "'"
        if isinstance(obj, sql.SQL):
            return obj.string
        return str(obj)

    monkeypatch.setattr(sql.Composable, "as_string", render, raising=False)
    for cls in (sql.Composed, sql.Identifier, sql.Literal, sql.SQL):
        monkeypatch.setattr(cls, "as_string", render, raising=False)


# ============================================================================ config + wiring
def test_config_thresholds_are_data_and_paths_are_home_relative():
    sw_cfg = CFG["storage_watch"]
    assert (sw_cfg["disk_warn_used_pct"], sw_cfg["disk_crit_used_pct"]) == (80, 90)
    assert CFG["backup_verify"]["max_age_hours"] == 26 and CFG["backup_verify"]["size_tolerance_pct"] == 30
    assert CFG["restore_drill"]["db_name_regex"] == r"^restore_drill_\d{8}$"
    raw = (ROOT / "config" / "ops_lanes.json").read_text(encoding="utf-8")
    assert "/home/" not in raw
    for root in sw_cfg["heavy_roots"]:
        assert root.startswith("~/") or root.startswith("/usr/") or root.startswith("/var/"), root


def test_allowlist_registry_and_generated_workflows_agree_for_the_new_lanes():
    index = json.loads((gen.DEFAULT_OUT / "INDEX.json").read_text(encoding="utf-8"))
    rows = {r["lane_id"]: r for r in index["lanes"]}
    for lane, signal in NEW_LANES.items():
        e = ALLOW[lane]
        assert e["dry_run_arg"][0] == "--dry-run" and e["live_arg"][0] == "--write"
        assert e["lock"].startswith("/tmp/") and e["timeout_s"] > 0 and e["market_gate"] is False
        assert e["output_signal"] == signal
        r = REG[lane]
        assert r["state"] == "NEVER_SCHEDULED" and r["scheduler"]["kind"] == "none" and r["owner"]
        assert r["output_signal"]["path"] == signal and r["expected_cadence_hours"] > 0
        assert rows[lane]["tranche"] == "N7" and rows[lane]["committed"] is True
        for f in (rows[lane]["shadow_file"], rows[lane]["live_file"]):
            wf = json.loads((gen.DEFAULT_OUT / f).read_text(encoding="utf-8"))
            assert wf["active"] is False
    assert "n8n-workflow-drift-check" in rows and ALLOW["n8n-workflow-drift-check"]["live_arg"] == ["--write"]
    # backup-verify shares the monthly maintenance step's lock so the two cannot overlap
    assert ALLOW["backup-verify"]["lock"] == "/tmp/backup_verify.lock"


def test_p16_is_registered_but_blocked_from_the_allowlist_by_the_forbidden_token():
    from scripts.lib import n8n_coordination_gateway as G

    assert "grant" in G.FORBIDDEN_ROUTE_TOKENS
    assert "n8n-activation-grants" not in ALLOW
    # registry-ops-crons 2026-10-09: host cron */30, PAUSED until Agent A installs the line (then ACTIVE)
    assert REG["n8n-activation-grants"]["state"] in {"PAUSED", "ACTIVE"}
    assert REG["n8n-activation-grants"]["scheduler"]["kind"] == "cron"
    doc = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    assert "grant" in doc["blocked_reasons"]["n8n-activation-grants"]
    assert "system-rollup-snapshot" not in ALLOW  # sender; the fix PR owns its code
    assert "n8n-activation-grants" not in {lane["lane_id"] for lane in gen.LANES}


def test_restore_drill_cron_is_weekly_sunday_with_a_first_week_gate():
    lane = next(lane for lane in gen.LANES if lane["lane_id"] == "trade-ai-restore-drill")
    assert lane["cron"] == ["30 3 * * 0"]
    assert ALLOW["trade-ai-restore-drill"]["live_arg"] == ["--write", "--first-week-only"]
    assert rd.first_week(datetime(2026, 11, 1)) and not rd.first_week(datetime(2026, 11, 8))


def test_no_lane_script_sends():
    for path in ("scripts/storage_watch.py", "scripts/trade_ai_restore_drill.py", "scripts/lib/ops_lanes.py"):
        src = (ROOT / path).read_text(encoding="utf-8").lower()
        for token in ("send_telegram", "telegram_alert", "dispatch_alert", "smtp" + "lib"):
            assert token not in src, (path, token)


# ============================================================================ storage-watch
def _fs(pct, path="/"):
    return {"path": path, "total_bytes": 100 << 30, "used_bytes": int(pct) << 30, "avail_bytes": (100 - int(pct)) << 30,
            "used_pct": float(pct), "free_pct": 100.0 - pct, "inodes_total": 100, "inodes_used": 10, "inodes_used_pct": 10.0}


@pytest.mark.parametrize("pct, expect", [(79.9, None), (80, "P2"), (87, "P2"), (90, "P1"), (95.5, "P1")])
def test_storage_thresholds_come_from_config(pct, expect):
    cfg = CFG["storage_watch"]
    found = [f for f in sw.evaluate({"filesystems": [_fs(pct)]}, cfg) if f["item"].startswith("disk:")]
    assert (found[0]["severity"] if found else None) == expect
    if found:
        assert set(found[0]) == {"source", "item", "severity", "detail", "artifact_rel", "store", "detected_at"}


def test_storage_thresholds_follow_a_config_change():
    cfg = dict(CFG["storage_watch"], disk_warn_used_pct=50, disk_crit_used_pct=60)
    assert [f["severity"] for f in sw.evaluate({"filesystems": [_fs(61)]}, cfg)] == ["P1"]


def test_growers_diff_the_previous_snapshot_and_rank():
    prev = {"a": {"bytes": 100}, "b": {"bytes": 100}, "c": {"error": "timeout>1s"}}
    cur = {"a": {"bytes": 150}, "b": {"bytes": 400}, "c": {"bytes": 5}, "d": {"bytes": 9}}
    g = sw.growers(cur, prev, 10)
    assert [r["root"] for r in g] == ["b", "a"] and g[0]["delta_bytes"] == 300
    assert sw.growers(cur, None, 10) == []


def test_du_is_niced_depth_limited_and_parses(tmp_path):
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=f"12345\t{argv[-1]}\n", stderr="")

    out = sw.du_bytes(tmp_path, timeout=5, nice=19, runner=runner)
    assert out == {"bytes": 12345}
    argv = calls[0]
    assert "nice" in argv and argv[argv.index("du"):argv.index("du") + 4] == ["du", "-x", "-s", "-B1"]
    assert sw.du_bytes(tmp_path / "missing", timeout=5, nice=19, runner=runner) == {"error": "missing"}


def test_m2_count_is_one_read_only_catalog_select():
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="m2_shadow_test_a\nm2_shadow_test_b\n", stderr="")

    out = sw.m2_test_dbs("ctr", "m2", "^m2_shadow_test_", runner=runner)
    assert out["count"] == 2
    argv = seen[0]
    assert argv[:2] == ["docker", "exec"] and "PGOPTIONS=-c default_transaction_read_only=on" in argv
    assert argv[-1].startswith("SELECT datname FROM pg_database")


def test_storage_main_dry_run_writes_nothing_and_write_writes_receipt(tmp_path, monkeypatch):
    receipt = tmp_path / "storage_watch_last.json"
    fake = {"as_of": "2026-10-09T10:10:00+00:00", "filesystems": [_fs(91)], "du_snapshot": {"~/x": {"bytes": 1}}, "growers": [],
            "database": {"database": "trade_ai", "size_bytes": 1 << 30, "top_relations": []},
            "m2_test_databases": {"count": 3}, "pg_log_dir": {"bytes": 1}, "worktrees": {"excluding_main": 2}}
    monkeypatch.setattr(sw, "measure", lambda cfg, previous: dict(fake))
    assert sw.main(["--dry-run", "--receipt", str(receipt)]) == 0
    assert not receipt.exists()
    assert sw.main(["--write", "--receipt", str(receipt)]) == 0
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    assert doc["schema"] == "StorageWatchReceipt@v1" and doc["verdict"] == "CRIT" and doc["fanin_wired"] is False
    assert any(f["severity"] == "P1" for f in doc["fanin_findings"])


def test_storage_db_report_uses_catalog_queries_only():
    def responder(text, params):
        if "pg_database_size" in text:
            return [(5 << 30,)]
        return [("public", "big", "r", 3 << 30, 10)]

    connect, log = fake_connect_factory(responder)
    out = sw.db_report({"dbname": "trade_ai"}, 10, connect=connect)
    assert out["size_bytes"] == 5 << 30 and out["top_relations"][0]["relation"] == "big"
    for _db, text, _p in log:
        assert text.lstrip().upper().startswith("SELECT")


# ============================================================================ backup-verify
LOG = """[Wed Oct  7 02:30:00 AM EDT 2026] Starting backup of trade_ai@localhost:5432...
[Wed Oct  7 02:50:00 AM EDT 2026] Backup complete: /x/trade_ai_20261007_023000.sql.gz (2.7G)
{
  "local": {
    "total_bytes": 2900000000,
    "max_count": 1
  }
}
[Thu Oct  8 02:50:42 AM EDT 2026] Backup complete: /x/trade_ai_20261008_023000.sql.gz (2.7G)
    "total_bytes": 2904602468,
[Thu Oct  8 03:00:00 AM EDT 2026] SKIP: last full dump is 10m old (< 1200m)
[Fri Oct  9 02:51:24 AM EDT 2026] Backup complete: /x/trade_ai_20261009_023000.sql.gz (2.8G)
    "total_bytes": 2914763010,
"""


def test_size_history_is_parsed_from_the_backup_log(tmp_path):
    log = tmp_path / "backup.log"
    log.write_text(LOG, encoding="utf-8")
    hist = bv.size_history_from_log(log)
    assert [h["date"] for h in hist] == ["2026-10-07", "2026-10-08", "2026-10-09"]
    assert hist[-1]["bytes"] == 2914763010
    base = bv.size_baseline(hist, exclude="trade_ai_20261009_023000.sql.gz", now=datetime(2026, 10, 9), days=7, min_samples=2)
    assert base == {"median_bytes": (2900000000 + 2904602468) // 2, "samples": 2}
    assert bv.size_baseline(hist, exclude="x", now=datetime(2026, 10, 9), days=7, min_samples=5)["median_bytes"] is None


def _write_plain_dump(path: Path, tables: int, trailer: bool = True):
    body = "".join(f"CREATE TABLE public.t{i} (id int);\nCOPY public.t{i} (id) FROM stdin;\n1\n\\.\n" for i in range(tables))
    if trailer:
        body += "--\n-- PostgreSQL database dump complete\n--\n"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(body)


def test_plain_gz_scan_reads_end_to_end_and_counts(tmp_path):
    good = tmp_path / "trade_ai_20261009_023000.sql.gz"
    _write_plain_dump(good, 7)
    out = bv.scan_plain_gz(good, timeout=60)
    assert out["ok"] and out["tables"] == 7 and out["table_data"] == 7 and out["trailer"]
    no_trailer = tmp_path / "trade_ai_20261009_000000.sql.gz"
    _write_plain_dump(no_trailer, 3, trailer=False)
    assert bv.scan_plain_gz(no_trailer, timeout=60)["ok"] is False
    truncated = tmp_path / "trade_ai_20261009_000001.sql.gz"
    truncated.write_bytes(good.read_bytes()[:-20])
    assert bv.scan_plain_gz(truncated, timeout=60)["ok"] is False


def _bv_cfg(tmp_path, **over):
    cfg = dict(CFG["backup_verify"], dump_dir=str(tmp_path / "dumps"), table_count_floor=5, size_median_min_samples=2)
    cfg.update(over)
    return cfg


def test_dump_dir_is_config_driven_not_relative_to_the_code_root(tmp_path, monkeypatch):
    cfg = CFG["backup_verify"]
    assert bv.dump_dir(cfg, env={}) == Path(os.path.expanduser("~/db_backups"))
    assert bv.dump_dir(cfg, env={"TRADEAI_DB_BACKUP_DIR": str(tmp_path)}) == tmp_path
    assert "backups/db" not in (ROOT / "scripts" / "backup_verify.py").read_text(encoding="utf-8").split('"""', 2)[2]
    # the legacy monthly step uses the same locator
    d = tmp_path / "dumps"
    d.mkdir()
    (d / "trade_ai_20261009_023000.sql.gz").write_bytes(b"x" * 2000)
    monkeypatch.setenv("TRADEAI_DB_BACKUP_DIR", str(d))
    legacy = bv.verify_db_backup()
    assert legacy[0]["check"] == "backup_exists" and legacy[0]["status"] == "OK"


def test_trade_ai_checks_fresh_good_dump_is_clean(tmp_path):
    d = tmp_path / "dumps"
    d.mkdir()
    (d / "backup.log").write_text(LOG.replace("2914763010", "2"), encoding="utf-8")
    dump = d / "trade_ai_20261009_023000.sql.gz"
    _write_plain_dump(dump, 6)
    now = datetime.fromtimestamp(dump.stat().st_mtime, timezone.utc) + timedelta(hours=1)
    cfg = _bv_cfg(tmp_path, size_median_min_samples=99)
    section, findings = bv.check_trade_ai(cfg, now=now, previous=None)
    assert findings == [], findings
    assert section["latest"] == dump.name and section["scan"]["tables"] == 6


@pytest.mark.parametrize("case", ["missing", "stale", "floor", "unreadable", "size"])
def test_trade_ai_failures_are_typed_findings(tmp_path, case):
    d = tmp_path / "dumps"
    d.mkdir()
    cfg = _bv_cfg(tmp_path)
    if case == "missing":
        _, f = bv.check_trade_ai(cfg, now=datetime.now(timezone.utc), previous=None)
        assert [x["item"] for x in f] == ["trade_ai:no_dump"] and f[0]["severity"] == "P1"
        return
    dump = d / "trade_ai_20261009_023000.sql.gz"
    _write_plain_dump(dump, 2 if case == "floor" else 6)
    if case == "unreadable":
        dump.write_bytes(dump.read_bytes()[:-30])
    mtime = datetime.fromtimestamp(dump.stat().st_mtime, timezone.utc)
    now = mtime + timedelta(hours=30 if case == "stale" else 1)
    prev = None
    if case == "size":
        prev = {"trade_ai": {"size_history": [
            {"date": (mtime - timedelta(days=k)).strftime("%Y-%m-%d"), "bytes": dump.stat().st_size * 3, "name": f"trade_ai_2026100{k}_023000.sql.gz"}
            for k in (1, 2, 3)]}}
    _, f = bv.check_trade_ai(cfg, now=now, previous=prev)
    items = {x["item"]: x["severity"] for x in f}
    expected = {"stale": ("trade_ai:stale", "P1"), "floor": ("trade_ai:table_floor", "P1"),
                "unreadable": ("trade_ai:unreadable", "P1"), "size": ("trade_ai:size_out_of_band", "P2")}[case]
    assert items.get(expected[0]) == expected[1], items


def test_n8n_and_drive_family_checks(tmp_path):
    root = tmp_path / "state"
    (root / "backups" / "n8n").mkdir(parents=True)
    (root / "data" / "runtime").mkdir(parents=True)
    dump = root / "backups" / "n8n" / "n8n-lab-x.dump"
    dump.write_bytes(b"d" * 100)
    now = datetime.now(timezone.utc)
    receipt = {"as_of": (now - timedelta(hours=2)).isoformat(), "dump": str(dump), "bytes": 100, "live_public_tables": 3, "ok": True}
    (root / "backups" / "n8n" / "n8n_lab_backup_last.json").write_text(json.dumps(receipt), encoding="utf-8")
    toc = "\n".join(f"{i}; 0 0 TABLE DATA public t{i} n8n" for i in range(3))

    def runner(argv, **kw):
        assert "pg_restore" in argv and "--list" in argv
        return subprocess.CompletedProcess(argv, 0, stdout=toc, stderr="")

    cfg = CFG["backup_verify"]
    section, f = bv.check_n8n(cfg, now=now, root=root, runner=runner)
    assert f == [] and section["scan"]["table_data"] == 3
    dump.unlink()
    _, f = bv.check_n8n(cfg, now=now, root=root, runner=runner)
    assert [x["item"] for x in f] == ["n8n_lab:dump_missing"] and f[0]["severity"] == "P1"

    for rel in cfg["drive_family_stamps_rel"][:2]:
        (root / rel).touch()
    old = root / cfg["drive_family_stamps_rel"][1]
    os.utime(old, (now.timestamp() - 10 * 86400, now.timestamp() - 10 * 86400))
    _, f = bv.check_drive_family(cfg, now=now, root=root)
    sev = {x["item"]: x["severity"] for x in f}
    assert sev == {"drive_family:last_db_offsite_backup:stale": "P2", "drive_family:last_apps_backup:missing": "P1"}


def test_backup_verify_lane_modes_never_send_and_write_only_with_write(tmp_path, monkeypatch):
    receipt = tmp_path / "backup_verify_last.json"
    sent = []
    monkeypatch.setitem(sys.modules, "alert_dispatcher", type(sys)("alert_dispatcher"))
    sys.modules["alert_dispatcher"].dispatch_alert = lambda **kw: sent.append(kw)
    monkeypatch.setattr(bv, "build_receipt", lambda cfg, **kw: {"schema": bv.SCHEMA, "verdict": "OK", "mode": kw["mode"], "as_of": "t",
                                                                 "trade_ai": {}, "n8n_lab": {}, "drive_family": {"stamps": []}, "fanin_findings": []})
    assert bv.main(["--dry-run", "--receipt", str(receipt)]) == 0 and not receipt.exists()
    assert bv.main(["--write", "--receipt", str(receipt)]) == 0
    assert json.loads(receipt.read_text(encoding="utf-8"))["mode"] == "write"
    assert sent == []


# ============================================================================ restore drill
REGEX = CFG["restore_drill"]["db_name_regex"]


def test_drill_name_is_dated_and_regex_guarded():
    assert rd.drill_db_name(datetime(2026, 11, 1), CFG["restore_drill"]) == "restore_drill_20261101"
    with pytest.raises(rd.DrillRefused):
        rd.drill_db_name(datetime(2026, 11, 1), dict(CFG["restore_drill"], db_name_prefix="trade_ai_"))


@pytest.mark.parametrize(
    "name, created, comment",
    [
        ("trade_ai", "trade_ai", "tradeai-restore-drill run r1"),
        ("postgres", "postgres", "tradeai-restore-drill run r1"),
        ("restore_drill_2026110", "restore_drill_2026110", "tradeai-restore-drill run r1"),
        ("restore_drill_20261101x", "restore_drill_20261101x", "tradeai-restore-drill run r1"),
        ("restore_drill_20261101; DROP DATABASE trade_ai", "restore_drill_20261101; DROP DATABASE trade_ai", "tradeai-restore-drill run r1"),
        ("restore_drill_20261101", None, "tradeai-restore-drill run r1"),
        ("restore_drill_20261101", "restore_drill_20261102", "tradeai-restore-drill run r1"),
        ("restore_drill_20261101", "restore_drill_20261101", None),
        ("restore_drill_20261101", "restore_drill_20261101", "tradeai-restore-drill run OTHER"),
    ],
)
def test_drop_guard_refuses_everything_but_this_runs_throwaway(name, created, comment):
    with pytest.raises(rd.DrillRefused):
        rd.assert_droppable(name, created_name=created, comment=comment, run_id="r1", regex=REGEX)


def test_drop_guard_accepts_this_runs_throwaway():
    rd.assert_droppable("restore_drill_20261101", created_name="restore_drill_20261101", comment=rd.COMMENT_PREFIX + "r1", run_id="r1", regex=REGEX)


def test_disk_floor_guard_is_two_times_estimate_plus_headroom():
    cfg = CFG["restore_drill"]
    g = rd.disk_guard(10 << 30, 24 << 30, cfg)
    assert g["required_free_bytes"] == int((10 << 30) * 2.0 * 1.15) and g["ok"] is True
    assert rd.disk_guard(10 << 30, 23 << 30, cfg)["ok"] is False


def test_row_comparison_tolerance():
    cfg = CFG["restore_drill"]
    rows = rd.compare_counts(
        [{"schema": "s", "table": "a", "live_estimate": 100000, "restored_rows": 90000},
         {"schema": "s", "table": "b", "live_estimate": 100000, "restored_rows": 50000},
         {"schema": "s", "table": "c", "live_estimate": 10, "restored_rows": 900},
         {"schema": "s", "table": "d", "live_estimate": 10, "restored_rows": None}],
        cfg,
    )
    assert [r["ok"] for r in rows] == [True, False, True, False]


def _plan(name="restore_drill_20261101"):
    return {"db_name": name, "dump_dir": "/nonexistent", "dump": "trade_ai_20261101_023000.sql.gz",
            "tables_to_compare": [{"schema": "public", "table": "a", "bytes": 1, "live_estimate": 5}],
            "would_run": True, "preconditions": {"dump_present": True}}


def _drill_responder(comment_holder):
    def responder(text, params):
        if text.startswith("COMMENT ON DATABASE"):
            comment_holder["c"] = re.search(r"'(.*)'", text).group(1)
            return []
        if "shobj_description" in text:
            return [(comment_holder.get("c"),)]
        return []
    return responder


def test_run_drill_creates_restores_compares_then_drops_only_its_database():
    pytest.importorskip("psycopg2")
    holder: dict = {}
    connect, log = fake_connect_factory(_drill_responder(holder))
    restored = []
    result = rd.run_drill(
        CFG["restore_drill"], _plan(), {"user": "drill", "dbname": "trade_ai"}, run_id="r1", connect=connect,
        restore_fn=lambda dump, name, params, timeout: restored.append(name) or {"rc": 0, "timed_out": False, "error_lines": 0, "first_errors": []},
        count_fn=lambda params, name, tables: [{**t, "restored_rows": 5} for t in tables],
    )
    ddl = [t for _db, t, _p in log if t.startswith(("CREATE", "DROP"))]
    assert ddl == ['CREATE DATABASE "restore_drill_20261101" TEMPLATE "restore_drill_template"', 'DROP DATABASE "restore_drill_20261101"']
    assert all(db == "postgres" for db, t, _p in log if t.startswith(("CREATE", "DROP")))
    assert restored == ["restore_drill_20261101"] and result["dropped"] is True
    assert rd.findings_for(_plan(), result) == []


def test_run_drill_drops_even_when_the_restore_blows_up():
    pytest.importorskip("psycopg2")
    holder: dict = {}
    connect, log = fake_connect_factory(_drill_responder(holder))

    def boom(*a, **k):
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        rd.run_drill(CFG["restore_drill"], _plan(), {"user": "drill", "dbname": "trade_ai"}, run_id="r1", connect=connect, restore_fn=boom)
    assert [t for _db, t, _p in log if t.startswith("DROP")] == ['DROP DATABASE "restore_drill_20261101"']


def test_run_drill_never_drops_when_the_marker_is_not_its_own():
    pytest.importorskip("psycopg2")
    connect, log = fake_connect_factory(lambda text, params: [("someone else",)] if "shobj_description" in text else [])
    result = rd.run_drill(
        CFG["restore_drill"], _plan(), {"user": "drill", "dbname": "trade_ai"}, run_id="r1", connect=connect,
        restore_fn=lambda *a, **k: {"rc": 0, "timed_out": False, "error_lines": 0, "first_errors": []},
        count_fn=lambda params, name, tables: [{**t, "restored_rows": 5} for t in tables],
    )
    assert not [t for _db, t, _p in log if t.startswith("DROP")]
    assert result["dropped"] is False
    assert {f["item"] for f in rd.findings_for(_plan(), result)} == {"throwaway:left_behind"}


def test_refused_preconditions_are_findings_and_create_nothing():
    p = dict(_plan(), would_run=False, preconditions={"dump_present": True, "disk_guard": False, "role_createdb": False})
    f = rd.findings_for(p, None)
    assert f[0]["item"] == "refused:disk_guard,role_createdb" and f[0]["severity"] == "P2"


def test_dry_run_prints_the_plan_and_never_creates(tmp_path, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(rd, "run_drill", lambda *a, **k: called.append(1))
    plan = dict(_plan(), dump_bytes=1, live_size_bytes=1 << 30, excluded_schemas_bytes=0, existing_drill_databases=[],
                disk_guard=rd.disk_guard(1 << 30, 100 << 30, CFG["restore_drill"]),
                drill_role=rd.role_verdict("x", None, live_user="trade_ai"), template_db={"name": "restore_drill_template", "present": False},
                tables_to_compare=[dict(t, key=True) for t in _plan()["tables_to_compare"]])
    monkeypatch.setattr(rd, "plan", lambda *a, **k: plan)
    receipt = tmp_path / "r.json"
    assert rd.main(["--dry-run", "--receipt", str(receipt)]) == 0
    assert called == [] and not receipt.exists()
    assert "PLAN" in capsys.readouterr().out


def test_first_week_only_is_a_no_op_after_day_seven(monkeypatch, tmp_path):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 8, 3, 30)

    monkeypatch.setattr(rd, "datetime", Fixed)
    monkeypatch.setattr(rd, "plan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("plan must not run")))
    assert rd.main(["--write", "--first-week-only", "--receipt", str(tmp_path / "r.json")]) == 0
    assert not (tmp_path / "r.json").exists()
