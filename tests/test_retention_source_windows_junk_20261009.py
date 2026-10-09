"""Operator decision 2026-10-09: enforce content_embeddings source_windows (30 d fused_signal/social_post)
as ARCHIVE_THEN_DELETE, and a one-time, dry-run-by-default purge of the blank-template fused_signal
embeddings. Every batch is archived, re-read (row count + sha256 + key set) and only then deleted.

Hermetic: an in-memory table stands in for Postgres; archives go to tmp_path.
"""
from __future__ import annotations

import copy
import gzip
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.check_retention_policy import validate  # noqa: E402
from lib import retention_archive as ra  # noqa: E402


class _Table:
    """id -> row; DELETEs are staged until COMMIT so a rollback really undoes them."""

    def __init__(self, rows, match):
        self.rows = {r["id"]: r for r in rows}
        self.match = match            # (row, params) -> bool, standing in for the WHERE clause
        self.staged: set = set()
        self.deletes_executed = 0
        self.commits = 0
        self.rollbacks = 0

    def live(self):
        return [r for k, r in sorted(self.rows.items()) if k not in self.staged]


class _Cur:
    def __init__(self, t: _Table, archive_drop: int = 0):
        self.t, self.archive_drop = t, archive_drop
        self.rowcount = 0
        self._all, self._one, self._iter = [], None, []
        self.itersize = 0

    def execute(self, sql, params=()):
        t = self.t
        params = tuple(params or ())
        if "FOR UPDATE" in sql:
            *pred, limit = params
            self._all = [(r["id"],) for r in t.live() if t.match(r, pred)][:limit]
        elif sql.startswith("SELECT row_to_json(t)") and "ANY(%s)" in sql:
            keys = set(params[0])
            rows = [r for r in t.live() if r["id"] in keys]
            self._iter = [(copy.deepcopy(r),) for r in rows[: len(rows) - self.archive_drop]]
        elif sql.startswith("SELECT row_to_json(t)"):
            *pred, limit = params
            self._all = [(copy.deepcopy(r),) for r in t.live() if t.match(r, pred)][:limit]
        elif sql.startswith("SELECT count(*), COALESCE(sum(pg_column_size"):
            rows = [r for r in t.live() if t.match(r, params)]
            self._one = (len(rows), 7000 * len(rows))
        elif sql.startswith("SELECT count(*) FROM"):
            self._one = (len([r for r in t.live() if t.match(r, params)]),)
        elif sql.startswith("DELETE"):
            keys = set(params[0])
            hit = [k for k in keys if k in t.rows and k not in t.staged]
            t.staged.update(hit)
            t.deletes_executed += 1
            self.rowcount = len(hit)
        elif "pg_constraint" in sql:
            self._all = []
        else:  # pragma: no cover
            raise AssertionError(sql[:80])

    def fetchall(self):
        return self._all

    def fetchone(self):
        return self._one

    def __iter__(self):
        return iter(self._iter)

    def close(self):
        pass


class _Conn:
    def __init__(self, t, archive_drop=0):
        self.t, self.archive_drop = t, archive_drop

    def cursor(self, name=None):
        return _Cur(self.t, self.archive_drop)

    def commit(self):
        for k in self.t.staged:
            del self.t.rows[k]
        self.t.staged.clear()
        self.t.commits += 1

    def rollback(self):
        self.t.staged.clear()
        self.t.rollbacks += 1

    def close(self):
        pass


JUNK_RE = r"^\S+ signal: *$"


def _embeddings(n_junk=45, n_real=5, n_news=3):
    rows, i = [], 0
    for k in range(n_junk):
        i += 1
        rows.append({"id": i, "source_type": "fused_signal", "title": f"S{k} signal: ", "embedding": [0.1] * 8})
    for k in range(n_real):
        i += 1
        rows.append({"id": i, "source_type": "fused_signal", "title": f"R{k} signal: low fused 0.34 (news) 2026-10-09 16:00Z",
                     "embedding": [0.2] * 8})
    for k in range(n_news):
        i += 1
        rows.append({"id": i, "source_type": "news", "title": f"S{k} signal: ", "embedding": [0.3] * 8})
    return rows


def _junk_match(row, params):
    return row["source_type"] == "fused_signal" and re.match(params[0], row["title"] or "") is not None


# ── archive_then_delete_batches ─────────────────────────────────────────────
def test_batches_archive_verify_then_delete_with_cap(tmp_path):
    t = _Table(_embeddings(), _junk_match)
    res = ra.archive_then_delete_batches(_Conn(t), table="content_embeddings", where_sql="x", params=(JUNK_RE,),
                                         label="junk_fused_signal", archive_dir=tmp_path, batch_rows=20, max_rows=30,
                                         stamp="20261009T000000Z")
    assert res["status"] == "ok" and res["rows_deleted"] == 30 and res["cap_reached"] is True
    assert [b["rows"] for b in res["batches"]] == [20, 10]
    remaining = {r["id"] for r in t.rows.values()}
    assert len([i for i in remaining if i <= 45]) == 15        # junk left for the next run
    assert all(i in remaining for i in range(46, 54))          # real fused + news untouched
    archived = []
    for b in res["batches"]:
        p = Path(b["path"])
        man = json.loads(ra.manifest_path(p).read_text())
        assert man["schema"] == ra.MANIFEST_SCHEMA and man["rows"] == b["rows"] and man["sha256"] == b["sha256"]
        with gzip.open(p, "rt") as fh:
            archived += [json.loads(line)["id"] for line in fh]
    assert sorted(archived) == list(range(1, 31))


def test_short_archive_refuses_the_delete_and_rolls_back(tmp_path):
    t = _Table(_embeddings(), _junk_match)
    with pytest.raises(ra.ArchiveVerifyError):
        ra.archive_then_delete_batches(_Conn(t, archive_drop=1), table="content_embeddings", where_sql="x",
                                       params=(JUNK_RE,), label="junk", archive_dir=tmp_path, batch_rows=20, max_rows=40)
    assert t.deletes_executed == 0 and len(t.rows) == 53 and t.rollbacks >= 1


def test_tampered_archive_fails_verification(tmp_path, monkeypatch):
    t = _Table(_embeddings(), _junk_match)
    real_write = ra.write_jsonl_gz

    def write_then_tamper(rows, path):
        n, sha, b = real_write(rows, path)
        path.write_bytes(path.read_bytes() + b"x")          # corrupt after the checksum is taken
        return n, sha, b

    monkeypatch.setattr(ra, "write_jsonl_gz", write_then_tamper)
    with pytest.raises(ra.ArchiveVerifyError, match="sha256 mismatch"):
        ra.archive_then_delete_batches(_Conn(t), table="content_embeddings", where_sql="x", params=(JUNK_RE,),
                                       label="junk", archive_dir=tmp_path, batch_rows=20, max_rows=40)
    assert t.deletes_executed == 0 and len(t.rows) == 53


def test_estimate_is_read_only(tmp_path):
    t = _Table(_embeddings(), _junk_match)
    est = ra.estimate(_Conn(t), table="content_embeddings", where_sql="x", params=(JUNK_RE,), sample_rows=10)
    assert est["rows"] == 45 and est["stored_bytes"] == 45 * 7000 and est["est_archive_bytes"] > 0
    assert t.deletes_executed == 0 and len(t.rows) == 53


# ── the one-time junk mode in db_retention ──────────────────────────────────
def _dr(monkeypatch, tmp_path, table):
    import db_retention as dr
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(dr, "_connect", lambda: _Conn(table))
    monkeypatch.setattr(dr, "_disk_too_low_for_retention", lambda: None)
    return dr


def test_junk_mode_defaults_to_dry_run_and_touches_nothing(monkeypatch, tmp_path, capsys):
    t = _Table(_embeddings(), _junk_match)
    dr = _dr(monkeypatch, tmp_path, t)
    assert dr.JUNK_FUSED_TITLE_RE == JUNK_RE
    assert dr.purge_junk_fused_embeddings() == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "45 rows" in out and '"status": "dry_run"' in out
    assert t.deletes_executed == 0 and len(t.rows) == 53
    assert not (tmp_path / "archive").exists()


def test_junk_mode_apply_archives_verifies_deletes_and_writes_receipt(monkeypatch, tmp_path):
    t = _Table(_embeddings(), _junk_match)
    dr = _dr(monkeypatch, tmp_path, t)
    assert dr.purge_junk_fused_embeddings(apply=True, batch_rows=20, max_rows=1000) == 0
    assert {r["id"] for r in t.rows.values()} == set(range(46, 54))
    rdir = tmp_path / "archive" / "db_retention" / "content_embeddings" / "receipts"
    (rec_path,) = list(rdir.glob("*-junk_fused_signal.json"))
    rec = json.loads(rec_path.read_text())
    assert rec["status"] == "ok" and rec["result"]["rows_deleted"] == 45 and rec["remaining"] == 0
    assert rec["before"]["rows"] == 45
    assert len(list((tmp_path / "archive" / "db_retention" / "content_embeddings").glob("*.jsonl.gz"))) == 3


def test_junk_mode_apply_refuses_on_low_disk(monkeypatch, tmp_path):
    t = _Table(_embeddings(), _junk_match)
    dr = _dr(monkeypatch, tmp_path, t)
    monkeypatch.setattr(dr, "_disk_too_low_for_retention", lambda: "3% free")
    assert dr.purge_junk_fused_embeddings(apply=True) == 2
    assert t.deletes_executed == 0


# ── source_windows are enforced, archive-first ──────────────────────────────
def test_committed_registry_declares_enforced_archive_first_source_windows():
    import db_retention as dr
    doc = json.loads((ROOT / "config" / "data_retention_policy.json").read_text())
    assert validate(doc) == []
    ws = dr.enforced_source_windows(doc)
    got = {(w["table"], w["source"], w["days"]) for w in ws}
    assert got == {("content_embeddings", "fused_signal", 30), ("content_embeddings", "social_post", 30)}
    assert all(w["source_column"] == "source_type" and w["batch_rows"] > 0 and w["max_rows"] > 0 for w in ws)


@pytest.mark.parametrize("mut,needle", [
    (lambda r: r.pop("source_column"), "requires source_column"),
    (lambda r: r.update(source_windows_class="DELETE"), "must be ARCHIVE_THEN_DELETE"),
    (lambda r: r["source_windows"].update(fused_signal=3), "must be an int >= 7"),
    (lambda r: r["source_windows"].update(fused_signal=90), "not shorter than window_days"),
    (lambda r: r.update(source_windows_max_rows_per_run=0), "must be a positive int"),
])
def test_registry_gate_rejects_bad_source_windows(mut, needle):
    doc = json.loads((ROOT / "config" / "data_retention_policy.json").read_text())
    row = next(r for r in doc["policies"] if r["table"] == "content_embeddings")
    mut(row)
    assert any(needle in e for e in validate(doc))


def _window_match(row, params):
    return row["source_type"] == params[0] and row["age_days"] > params[1]


def test_run_source_windows_dry_run_and_apply(monkeypatch, tmp_path, capsys):
    import db_retention as dr
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rows = [{"id": i, "source_type": st, "age_days": age}
            for i, (st, age) in enumerate([("fused_signal", 40)] * 5 + [("fused_signal", 10)] * 2
                                          + [("social_post", 31)] * 3 + [("news", 60)] * 4, start=1)]
    t = _Table(rows, _window_match)
    conn = _Conn(t)
    ws = [{"table": "content_embeddings", "ts_column": "created_at", "source_column": "source_type", "source": s,
           "days": 30, "batch_rows": 2, "max_rows": 4} for s in ("fused_signal", "social_post")]
    total, failed = dr.run_source_windows(conn.cursor(), conn, ws, dry_run=True)
    assert (total, failed) == (4 + 3, []) and t.deletes_executed == 0
    assert "source window, archive-first" in capsys.readouterr().out
    total, failed = dr.run_source_windows(conn.cursor(), conn, ws, dry_run=False)
    assert failed == [] and total == 4 + 3
    left = sorted((r["source_type"], r["age_days"]) for r in t.rows.values())
    assert left == [("fused_signal", 10)] * 2 + [("fused_signal", 40)] + [("news", 60)] * 4
    gz = list((tmp_path / "archive" / "db_retention" / "content_embeddings").glob("*.jsonl.gz"))
    assert len(gz) == 4 and all(ra.manifest_path(p).exists() for p in gz)
    pred, params = dr.source_window_predicate(ws[0])
    assert "make_interval(days => %s)" in pred and params == ("fused_signal", 30)


def test_existing_archive_rows_now_writes_a_checksum_manifest(tmp_path, monkeypatch):
    import db_retention as dr
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))

    class _C:
        def execute(self, sql, params=None):
            pass

        def __iter__(self):
            return iter([({"id": 1},), ({"id": 2},)])

    n, path = dr.archive_rows(_C(), "hermes_external_research", "created_at", 90, "")
    man = json.loads(ra.manifest_path(Path(path)).read_text())
    assert n == 2 and man["rows"] == 2 and len(man["sha256"]) == 64
    ok, why = ra.verify_archive(Path(path), expected_rows=2, expected_sha256=man["sha256"], key="id",
                                expected_keys=[1, 2])
    assert ok, why
