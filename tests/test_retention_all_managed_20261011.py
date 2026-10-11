"""retention-all-managed (2026-10-11): every delete/purge registered, archive-first, observable.

Operator 2026-10-11: "Add, enable, and manage all deletes and purges." Covers:
  * registry: archive_first on every DELETE row except the declared holds; archive cap; file_prune rows;
    purge_paths + the unregistered-deleter scan (check_retention_policy rules 8-9);
  * lib.retention_archive.managed_purge (dry run counts only; apply archives + verifies + deletes;
    archive=False is the explicit hard-DELETE lever), archive_files_then_unlink, archive_usage and
    ARCHIVE_GROWTH;
  * db_retention: read-only dry-run session, per-row action column, delete-rowcount check, registry
    file prunes (archive-then-unlink), --archive-projection;
  * the converted owners: hermes librarian, siem purge, protection-proposal prune, research critique,
    hermes self-tune, governed-universe history (files) and the librarian receipt.
No database, no network: fake connections and tmp dirs only.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import retention_archive as ra  # noqa: E402
from lib import retention_tripwire as rt  # noqa: E402
from scripts import check_retention_policy as crp  # noqa: E402

REG = json.loads((ROOT / "config" / "data_retention_policy.json").read_text(encoding="utf-8"))
HOLDS = {"market_quotes", "schwab_stream_book", "schwab_stream_quotes"}


# ── fake DB: rows carry "old" (the WHERE clause stand-in); DELETEs stage until COMMIT ──────────
class _Table:
    def __init__(self, n_old=5, n_new=3):
        self.rows = {i: {"id": i, "old": i <= n_old, "payload": "x" * 20} for i in range(1, n_old + n_new + 1)}
        self.staged: set = set()
        self.sql: list[str] = []
        self.commits = self.rollbacks = 0

    def live(self):
        return [r for k, r in sorted(self.rows.items()) if k not in self.staged]

    def old(self):
        return [r for r in self.live() if r["old"]]


class _Cur:
    def __init__(self, t: _Table, conn):
        self.t, self.connection = t, conn
        self.rowcount, self._all, self._one, self._iter, self.itersize = 0, [], None, [], 0

    def execute(self, sql, params=()):
        t = self.t
        t.sql.append(sql)
        params = tuple(params or ())
        s = " ".join(sql.split())
        if "FOR UPDATE" in s:
            self._all = [(r["id"],) for r in t.old()][: params[-1]]
        elif s.startswith("SELECT row_to_json(t)") and "ANY(%s)" in s:
            keys = set(params[0])
            self._iter = [(copy.deepcopy(r),) for r in t.live() if r["id"] in keys]
        elif s.startswith("SELECT count(*) FROM"):
            self._one = (len(t.old()),)
        elif s.startswith("DELETE") and "ANY(%s)" in s:
            hit = [k for k in params[0] if k in t.rows and k not in t.staged]
            t.staged.update(hit)
            self.rowcount = len(hit)
        elif s.startswith("DELETE"):
            hit = [r["id"] for r in t.old()]
            t.staged.update(hit)
            self.rowcount = len(hit)
        elif s.startswith("UPDATE"):
            self.rowcount = 0
        elif s.startswith("SELECT to_regclass"):
            self._one = ("x",)
        else:  # pragma: no cover
            raise AssertionError(s[:100])

    def fetchall(self):
        return self._all

    def fetchone(self):
        return self._one

    def __iter__(self):
        return iter(self._iter)

    def close(self):
        pass


class _Conn:
    def __init__(self, t: _Table):
        self.t = t
        self.session = {}

    def cursor(self, name=None):
        return _Cur(self.t, self)

    def commit(self):
        for k in self.t.staged:
            del self.t.rows[k]
        self.t.staged.clear()
        self.t.commits += 1

    def rollback(self):
        self.t.staged.clear()
        self.t.rollbacks += 1

    def set_session(self, **kw):
        self.session.update(kw)

    def close(self):
        pass


def _deletes(t: _Table) -> int:
    return sum(1 for s in t.sql if s.lstrip().upper().startswith("DELETE"))


# ── registry ─────────────────────────────────────────────────────────────────────────────────
def test_every_delete_row_archives_first_except_the_declared_holds():
    rows = [r for r in REG["policies"] if r["class"] == "DELETE"]
    assert len(rows) == 96
    off = {r["table"] for r in rows if r.get("archive_first") is not True}
    assert off == HOLDS
    for r in rows:
        if r["table"] in HOLDS:
            assert r["archive_first"] is False and len(r["archive_first_hold"]) >= 20


def test_enforced_policies_route_rows_through_archive_first():
    import db_retention as dr
    enforced = dr.enforced_policies(REG)
    assert len(enforced) == 125
    assert sum(1 for *_x, af in enforced if af) == 122  # 93 DELETE + 29 ARCHIVE_THEN_DELETE
    assert {t for t, _c, _d, af in enforced if not af} == HOLDS


def test_archive_cap_and_file_prune_rows_are_declared():
    assert REG["archive_growth_cap_gb_month"] == 2.0
    assert REG["archive_total_budget_gb"] > 0
    fp = {r["id"]: r for r in REG["file_prune"]}
    assert set(fp) == {"raw_snapshots", "ticker_snapshot_history", "ingestion_summaries", "catalyst_cache"}
    assert all(r["archive"] is True for r in fp.values())


def test_committed_registry_passes_the_gate_and_registers_every_deleter():
    assert crp.validate(REG) == []
    assert crp.unregistered_deleters(REG) == []


def test_gate_rejects_archive_first_false_without_a_hold():
    doc = copy.deepcopy(REG)
    row = next(r for r in doc["policies"] if r["table"] == "market_quotes")
    row.pop("archive_first_hold")
    assert any("archive_first_hold" in e for e in crp.validate(doc))


@pytest.mark.parametrize("mut,needle", [
    (lambda d: d["file_prune"][0].update(days="7"), "days must be an int"),
    (lambda d: d["file_prune"][0].update(archive="yes"), "archive must be true or false"),
    (lambda d: d["file_prune"].append(dict(d["file_prune"][0])), "duplicate id"),
    (lambda d: d.update(archive_growth_cap_gb_month=0), "archive_growth_cap_gb_month"),
    (lambda d: d["purge_paths"][0].update(state="WHATEVER"), "state"),
    (lambda d: d["purge_paths"][0].update(scripts=["scripts/nope_does_not_exist.py"]), "does not exist"),
])
def test_gate_rejects_bad_managed_fields(mut, needle):
    doc = copy.deepcopy(REG)
    mut(doc)
    assert any(needle in e for e in crp.validate(doc)), crp.validate(doc)


def test_gate_fails_a_new_unregistered_deleter(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "sneaky_purge.py").write_text('cur.execute("DELETE FROM foo WHERE x")\n')
    (tmp_path / "scripts" / "uses_helper.py").write_text("managed_purge(conn, table='t')\n")
    (tmp_path / "scripts" / "comment_only.py").write_text("# we truncate the label for display\n")
    (tmp_path / "scripts" / "test_fixture.py").write_text('cur.execute("DELETE FROM foo")\n')
    doc = {"purge_paths": [{"scripts": ["scripts/uses_helper.py"]}]}
    out = crp.unregistered_deleters(doc, root=tmp_path)
    assert len(out) == 1 and out[0].startswith("scripts/sneaky_purge.py")


# ── managed_purge ────────────────────────────────────────────────────────────────────────────
def test_managed_purge_dry_run_only_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    t = _Table()
    r = ra.managed_purge(_Conn(t), table="foo", where_sql="t.old", label="x", writer="w", apply=False)
    assert r["eligible"] == 5 and r["deleted"] == 0 and r["mode"] == "dry_run"
    assert _deletes(t) == 0 and len(t.rows) == 8
    assert not (tmp_path / "archive").exists()


def test_managed_purge_apply_archives_verifies_then_deletes(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    t = _Table()
    r = ra.managed_purge(_Conn(t), table="foo", where_sql="t.old", label="lbl", writer="siem_retention_purge",
                         apply=True, batch_rows=2)
    assert r["deleted"] == r["archived"] == 5 and r["batches"] == 3
    assert sorted(t.rows) == [6, 7, 8]
    adir = tmp_path / "archive" / "db_retention" / "foo"
    recs = [json.loads(x) for x in (adir / "TRIPWIRE.jsonl").read_text().splitlines()]
    assert len(recs) == 3 and {x["writer"] for x in recs} == {"siem_retention_purge"}
    archived_ids = []
    for f in sorted(adir.glob("*.jsonl.gz")):
        import gzip
        archived_ids += [json.loads(line)["id"] for line in gzip.open(f, "rt")]
    assert sorted(archived_ids) == [1, 2, 3, 4, 5]


def test_managed_purge_archive_false_is_the_explicit_hard_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    t = _Table()
    r = ra.managed_purge(_Conn(t), table="foo", where_sql="t.old", label="x", writer="w", apply=True, archive=False)
    assert r["deleted"] == 5 and r["archived"] == 0 and r["archive"] is False
    assert not (tmp_path / "archive").exists()


# ── file archives ────────────────────────────────────────────────────────────────────────────
def _files(d: Path, n=3, age_days=30):
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(n):
        f = d / f"snap_{i}.json"
        f.write_text(json.dumps({"i": i, "pad": "y" * 50}))
        old = f.stat().st_mtime - age_days * 86400
        os.utime(f, (old, old))
        out.append(f)
    return out


def test_archive_files_then_unlink_verifies_every_member(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    src = tmp_path / "src"
    files = _files(src)
    res = ra.archive_files_then_unlink(files, base_dir=src, archive_dir=ra.file_archive_root() / "lbl", label="lbl")
    assert res["unlinked"] == 3 and not any(f.exists() for f in files)
    tar = Path(res["archive"])
    with tarfile.open(tar) as tf:
        assert sorted(tf.getnames()) == ["snap_0.json", "snap_1.json", "snap_2.json"]
    man = json.loads(ra.manifest_path(tar).read_text())
    assert man["kind"] == "files" and len(man["members"]) == 3 and man["sha256"] == res["sha256"]
    rec = json.loads((tar.parent / "TRIPWIRE.jsonl").read_text().splitlines()[0])
    assert rec["kind"] == "files" and rec["archive"] == str(tar)


def test_archive_files_failed_verify_unlinks_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    src = tmp_path / "src"
    files = _files(src)
    monkeypatch.setattr(ra, "verify_file_archive", lambda *a, **k: (False, "forced"))
    with pytest.raises(ra.ArchiveVerifyError):
        ra.archive_files_then_unlink(files, base_dir=src, archive_dir=tmp_path / "a", label="lbl")
    assert all(f.exists() for f in files)


def test_tripwire_reader_covers_file_prune_archives(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    src = tmp_path / "src"
    res = ra.archive_files_then_unlink(_files(src), base_dir=src, archive_dir=ra.file_archive_root() / "x", label="x")
    units = tmp_path / "u"
    units.mkdir()
    assert rt.findings(state, tmp_path / "norepo", crontab_text="", unit_dir=units) == []
    Path(res["archive"]).unlink()  # simulate loss of the archive
    codes = [f["code"] for f in rt.findings(state, tmp_path / "norepo", crontab_text="", unit_dir=units)]
    assert "ARCHIVE_MISSING" in codes
    hits = rt.scan_references(tmp_path / "norepo", crontab_text="cat ~/x/archive/file_prune/x/a.tar.gz", unit_dir=units)
    assert hits and hits[0]["needle"] == "archive/file_prune"


def test_archive_usage_and_growth_findings(tmp_path):
    root = tmp_path / "archive"
    (root / "db_retention" / "t1").mkdir(parents=True)
    (root / "db_retention" / "t1" / "a.jsonl.gz").write_bytes(b"x" * 1000)
    (root / "file_prune" / "f1").mkdir(parents=True)
    old = root / "file_prune" / "f1" / "b.tar.gz"
    old.write_bytes(b"y" * 500)
    t = old.stat().st_mtime - 90 * 86400
    os.utime(old, (t, t))
    u = ra.archive_usage(root)
    assert u["total_bytes"] == 1500 and u["recent_bytes"] == 1000
    assert set(u["stores"]) == {"db_retention/t1", "file_prune/f1"}
    assert ra.archive_growth_findings(u, cap_gb_month=2.0, total_budget_gb=25) == []
    f = ra.archive_growth_findings(u, cap_gb_month=1e-9, total_budget_gb=1e-9, disk_free_bytes=1)
    assert [x["item"] for x in f] == ["archive", "archive_total", "disk_free"]
    assert all(x["code"] == "ARCHIVE_GROWTH" and x["severity"] == "P2" for x in f)


def test_hygiene_report_carries_archive_growth(tmp_path, monkeypatch):
    import report_db_hygiene as h
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    (tmp_path / "archive" / "db_retention" / "t").mkdir(parents=True)
    (tmp_path / "archive" / "db_retention" / "t" / "a.jsonl.gz").write_bytes(b"x" * 10)
    f, usage = h.archive_findings({"archive_growth_cap_gb_month": 1e-12})
    assert usage["total_bytes"] == 10 and f and f[0]["code"] == "ARCHIVE_GROWTH"


# ── db_retention ─────────────────────────────────────────────────────────────────────────────
class _RetCur:
    """Fake for db_retention.run: one table 'foo' with 4 matching rows."""

    def __init__(self, conn):
        self.conn, self.rowcount, self._one, self._all, self.itersize = conn, 0, None, [], 0

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self.conn.sql.append(s)
        if "information_schema" in s:
            self._one = (1,)
        elif "pg_constraint" in s:
            self._all = []
        elif s.startswith("SELECT count(*)"):
            self._one = (4,)
        elif s.startswith("SELECT row_to_json"):
            self._all = [({"id": i},) for i in range(4)]
        elif s.startswith("DELETE"):
            if self.conn.readonly:
                raise RuntimeError("cannot execute DELETE in a read-only transaction")
            self.rowcount = self.conn.delete_rowcount
        else:  # pragma: no cover
            raise AssertionError(s[:80])

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def __iter__(self):
        return iter(self._all)

    def close(self):
        pass


class _RetConn:
    def __init__(self, delete_rowcount=4):
        self.sql, self.readonly, self.delete_rowcount, self.commits, self.rollbacks = [], False, delete_rowcount, 0, 0

    def set_session(self, readonly=False, **_):
        self.readonly = readonly

    def cursor(self, name=None):
        return _RetCur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _ret_setup(monkeypatch, tmp_path, conn, archive_first=True, file_prune=None):
    import db_retention as dr
    doc = {"schema": "DataRetentionPolicy@v1", "policies": [
        {"table": "foo", "ts_column": "created_at", "class": "DELETE", "window_days": 30, "archive_first": archive_first}],
        "file_prune": file_prune or []}
    monkeypatch.setattr(dr, "load_registry", lambda path=None: doc)
    monkeypatch.setattr(dr, "_connect", lambda: conn)
    monkeypatch.setattr(dr, "_disk_too_low_for_retention", lambda: None)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path / "proj"))
    return dr


def test_dry_run_is_a_read_only_session_and_reports_the_plan(monkeypatch, tmp_path, capsys):
    proj = tmp_path / "proj"
    _files(proj / "snaps", n=2, age_days=30)
    conn = _RetConn()
    dr = _ret_setup(monkeypatch, tmp_path, conn, file_prune=[
        {"id": "snaps", "dir": "snaps", "pattern": "*.json", "days": 14, "archive": True}])
    assert dr.run(dry_run=True) == 0
    out = capsys.readouterr().out
    assert conn.readonly is True
    assert not any(s.startswith("DELETE") for s in conn.sql)
    assert "ARCHIVE+DELETE" in out and "archived first: 0" in out and "would archive first: 4" in out
    assert "ARCHIVE+UNLINK" in out and "Total would prune: 2 files" in out
    assert len(list((proj / "snaps").glob("*.json"))) == 2
    assert not (tmp_path / "state").exists()


def test_apply_archives_then_deletes_and_prunes_files_through_an_archive(monkeypatch, tmp_path, capsys):
    proj = tmp_path / "proj"
    _files(proj / "snaps", n=2, age_days=30)
    conn = _RetConn()
    dr = _ret_setup(monkeypatch, tmp_path, conn, file_prune=[
        {"id": "snaps", "dir": "snaps", "pattern": "*.json", "days": 14, "archive": True}])
    assert dr.run(dry_run=False) == 0
    out = capsys.readouterr().out
    assert "Total deleted: 4 rows; archived first: 4" in out
    assert len(list((tmp_path / "state" / "archive" / "db_retention" / "foo").glob("*.jsonl.gz"))) == 1
    assert list((proj / "snaps").glob("*.json")) == []
    assert len(list((tmp_path / "state" / "archive" / "file_prune" / "snaps").glob("*.tar.gz"))) == 1


def test_delete_rowcount_different_from_archive_rolls_back(monkeypatch, tmp_path, capsys):
    conn = _RetConn(delete_rowcount=5)  # a fifth row matched between the archive and the DELETE
    dr = _ret_setup(monkeypatch, tmp_path, conn)
    assert dr.run(dry_run=False) == 1
    out = capsys.readouterr().out
    assert "deleted 5 != archived 4" in out and conn.commits == 0 and conn.rollbacks == 1


def test_archive_first_false_keeps_the_hard_delete(monkeypatch, tmp_path, capsys):
    conn = _RetConn()
    dr = _ret_setup(monkeypatch, tmp_path, conn, archive_first=False)
    assert dr.run(dry_run=False) == 0
    assert "DELETE (no archive)" in capsys.readouterr().out
    assert not (tmp_path / "state" / "archive").exists()


def test_file_prune_archive_failure_unlinks_nothing_and_fails_the_run(monkeypatch, tmp_path, capsys):
    proj = tmp_path / "proj"
    files = _files(proj / "snaps", n=2, age_days=30)
    conn = _RetConn()
    dr = _ret_setup(monkeypatch, tmp_path, conn, file_prune=[
        {"id": "snaps", "dir": "snaps", "pattern": "*.json", "days": 14, "archive": True}])
    monkeypatch.setattr(ra, "verify_file_archive", lambda *a, **k: (False, "forced"))
    assert dr.run(dry_run=False) == 1
    assert all(f.exists() for f in files)
    assert "file_prune:snaps" in capsys.readouterr().out


def test_legacy_file_prune_without_registry_rows_stays_unarchived():
    import db_retention as dr
    rows = dr.file_prune_policies({"policies": []})
    assert len(rows) == 4 and all(r["archive"] is False for r in rows)
    assert {r["id"] for r in dr.file_prune_policies(REG)} == {r["id"] for r in rows}


class _ProjCur:
    def __init__(self, counts, sample):
        self.counts, self.sample, self._one, self._all = list(counts), sample, None, []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "information_schema" in s:
            self._one = (1,)
        elif "pg_constraint" in s:
            self._all = []
        elif s.startswith("SELECT count(*)"):
            self._one = (self.counts.pop(0),)
        elif s.startswith("SELECT row_to_json"):
            self._all = self.sample
        else:  # pragma: no cover
            raise AssertionError(s)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


def test_project_row_math():
    import db_retention as dr
    sample = [({"id": i, "v": "z" * 100},) for i in range(50)]
    r = dr.project_row(_ProjCur([10, 700, 1400], sample), "foo", "created_at", 30, True)
    bpr = ra.gz_bytes_per_row(sample)
    assert r["tonight_rows"] == 10 and r["boundary_rows_per_day"] == 100 and r["inflow_rows_per_day"] == 200
    assert r["rows_per_day"] == 200 and r["gb_per_month"] == round(200 * 30 * bpr / 1e9, 4)


def test_archive_projection_flags_rows_over_the_cap(monkeypatch):
    import db_retention as dr
    doc = {"schema": "DataRetentionPolicy@v1", "archive_growth_cap_gb_month": 1e-9, "policies": [
        {"table": "foo", "ts_column": "c", "class": "DELETE", "window_days": 30, "archive_first": True}]}
    monkeypatch.setattr(dr, "project_row", lambda cur, t, c, d, af, n: {
        "table": t, "status": "ok", "archive_first": af, "gb_per_month": 0.5})

    class _C:
        def cursor(self):
            return self

        def close(self):
            pass

    rep = dr.archive_projection(_C(), doc)
    assert rep["within_cap"] is False and rep["over_cap_rows"] == ["foo"] and rep["archive_first_gb_month"] == 0.5


# ── converted owners ─────────────────────────────────────────────────────────────────────────
def test_siem_purge_is_archive_first(monkeypatch, tmp_path):
    import siem_retention_purge as sp
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    t = _Table()
    out = sp.purge(_Conn(t), 14, apply=False)
    assert [r["eligible"] for r in out] == [5, 5] and _deletes(t) == 0
    out = sp.purge(_Conn(t), 14, apply=True)
    assert out[0]["archived"] == 5 and out[0]["writer"] == "siem_retention_purge"
    assert (tmp_path / "archive" / "db_retention" / "system_health_events" / "TRIPWIRE.jsonl").is_file()


def test_protection_prune_is_archive_first(monkeypatch, tmp_path):
    import prune_protection_proposals_retention as pp
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    t = _Table()
    assert pp.prune(_Conn(t), dry_run=True)["eligible"] == 5 and _deletes(t) == 0
    r = pp.prune(_Conn(t), dry_run=False)
    assert r["deleted"] == r["archived"] == 5
    assert list((tmp_path / "archive" / "db_retention" / "paper_protection_adjustment_proposals").glob("*.jsonl.gz"))


def test_research_critique_dry_run_no_longer_executes_deletes(monkeypatch, tmp_path):
    import research_critique_pipeline as rcp
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    t = _Table()
    r = rcp.retention_purge(_Conn(t), apply=False)
    assert _deletes(t) == 0 and r["purged"]["directives"] == 5
    r = rcp.retention_purge(_Conn(t), apply=True)
    assert r["purged"]["directives"] == 5
    assert (tmp_path / "archive" / "db_retention" / "watch_directives" / "TRIPWIRE.jsonl").is_file()


def test_self_tune_purges_are_archive_first(monkeypatch, tmp_path):
    import hermes_autonomous_self_tune as st
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    t = _Table()
    conn = _Conn(t)
    assert st._archived_purge(conn.cursor(), "x", "hermes_score_history", "t.old", (), apply=False) == 5
    assert _deletes(t) == 0
    assert st._archived_purge(conn.cursor(), "x", "hermes_score_history", "t.old", (), apply=True) == 5
    assert (tmp_path / "archive" / "db_retention" / "hermes_score_history" / "TRIPWIRE.jsonl").is_file()


def test_librarian_purges_route_through_managed_purge(monkeypatch):
    from lib.hermes_librarian import retention as lr
    calls = []

    def fake(conn, **kw):
        calls.append(kw)
        return {"eligible": 2, "deleted": 0 if not kw["apply"] else 2, "archived": 2 if kw["archive"] else 0,
                "archive": kw["archive"]}

    monkeypatch.setattr(lr, "_managed_purge", lambda: fake)

    class _C:
        def cursor(self):
            return self

        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return (0,)

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(lr, "load_policy", lambda: {"content_embeddings": {"max_age_owner": "db_retention"}})
    out = lr.apply_retention(_C(), dry_run=True)
    assert [c["label"] for c in calls] == ["librarian_archived_180d", "librarian_failed_14d",
                                           "librarian_orphan_news", "librarian_orphan_hermes_research"]
    assert all(c["writer"] == "hermes_librarian" and c["archive"] is True and c["apply"] is False for c in calls)
    assert {a["action"]: a.get("archive_first") for a in out["actions"]}["purge_news_orphans"] is True
    calls.clear()
    monkeypatch.setattr(lr, "load_policy", lambda: {"archive_first": False})
    lr.apply_retention(_C(), dry_run=False)
    assert all(c["archive"] is False and c["apply"] is True for c in calls)


def test_committed_librarian_policy_turns_archive_first_on():
    import yaml
    doc = yaml.safe_load((ROOT / "config" / "hermes_librarian_policy.yaml").read_text())
    assert doc["archive_first"] is True and doc["content_embeddings"]["max_age_owner"] == "db_retention"


def test_librarian_runner_writes_a_receipt(monkeypatch, tmp_path):
    import run_hermes_librarian_retention as rr
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    p = rr.write_receipt({"ok": True, "dry_run": False, "actions": []})
    doc = json.loads(p.read_text())
    assert doc["schema"] == "HermesLibrarianRetentionReceipt@v1" and p.parent == tmp_path / "data" / "runtime"


def _universe(hist: Path, days_old: list[int]):
    from datetime import datetime, timedelta, timezone
    hist.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    for i, d in enumerate(days_old):
        day = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        (hist / f"universe_{day}T{1000 + i:04d}_sg_{i:04x}.json").write_text(json.dumps({"d": d, "pad": "u" * 200}))


def test_universe_history_archives_before_unlinking(monkeypatch, tmp_path):
    import hermes_universe_history_retention as uh
    hist = tmp_path / "hist"
    _universe(hist, [1, 2, 120, 121, 122])
    monkeypatch.setattr(uh, "_history_dir", lambda: hist)
    monkeypatch.setattr(uh, "PROJECT_ROOT", tmp_path / "proj")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    dry = uh.run(min_keep=1, apply=False)
    assert dry["files_deletable"] == 3 and len(list(hist.iterdir())) == 5
    res = uh.run(min_keep=1, apply=True)
    assert res["ok"] and res["files_deleted"] == 3 and len(list(hist.iterdir())) == 2
    tar = Path(res["archive"])
    assert tar.parent == tmp_path / "state" / "archive" / "file_prune" / "hermes_governed_universe_history"
    with tarfile.open(tar) as tf:
        assert len(tf.getnames()) == 3


def test_universe_history_failed_archive_unlinks_nothing(monkeypatch, tmp_path):
    import hermes_universe_history_retention as uh
    hist = tmp_path / "hist"
    _universe(hist, [1, 120, 121])
    monkeypatch.setattr(uh, "_history_dir", lambda: hist)
    monkeypatch.setattr(uh, "PROJECT_ROOT", tmp_path / "proj")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(ra, "verify_file_archive", lambda *a, **k: (False, "forced"))
    res = uh.run(min_keep=1, apply=True)
    assert not res["ok"] and res["files_deleted"] == 0 and len(list(hist.iterdir())) == 3
