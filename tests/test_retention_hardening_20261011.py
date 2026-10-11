"""DB retention hardening (2026-10-11, overnight report "DB retention" findings 1, 4 and 6).

1. Row-archive tripwire: every db_retention archive file gets a RetentionArchiveTripwire@v1 record
   (written before the DELETE), and a reader (lib/retention_tripwire.py, run nightly by
   report_db_hygiene.py) turns any live reference to an archived path into a P1 finding that the
   incident fan-in opens.
2. db_retention --junk-fused-signal-embeddings --apply refuses without a db-write grant id that
   matches the ACTIVE guard-ledger grant, and records the verdict in the receipt. Dry run needs none.
3. One owner for the 90 d content_embeddings age rail: db_retention. The hermes librarian defers
   (no-op + pointer line); the registry row carries archive_first, default OFF.

Hermetic: tmp_path state roots and guard ledgers, fake cursors. No live DB, no host ledger,
no crontab, no systemd (§24.6).
"""
from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.check_retention_policy import validate  # noqa: E402
from scripts.lib import retention_tripwire as rt  # noqa: E402
from lib import retention_archive as ra  # noqa: E402
from lib import db_write_grant as dwg  # noqa: E402


def _registry() -> dict:
    return json.loads((ROOT / "config" / "data_retention_policy.json").read_text(encoding="utf-8"))


class _RowsCur:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        pass

    def __iter__(self):
        return iter([(r,) for r in self.rows])


# ── 1. tripwire: writer ─────────────────────────────────────────────────────
def test_archive_rows_writes_a_tripwire_record_next_to_the_archive(tmp_path, monkeypatch):
    import db_retention as dr
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    n, path = dr.archive_rows(_RowsCur([{"id": 1}, {"id": 2}, {"id": 3}]), "content_embeddings", "created_at", 90, "")
    tw = tmp_path / "archive" / "db_retention" / "content_embeddings" / "TRIPWIRE.jsonl"
    (rec,) = [json.loads(line) for line in tw.read_text().splitlines()]
    man = json.loads(ra.manifest_path(Path(path)).read_text())
    assert n == 3 and rec["schema"] == "RetentionArchiveTripwire@v1" and rec["kind"] == "rows"
    assert rec["archive"] == path and rec["table"] == "content_embeddings" and rec["rows"] == 3
    assert rec["sha256"] == man["sha256"] and rec["manifest"] == str(ra.manifest_path(Path(path)))
    # the tripwire file is not an archive: the *.jsonl.gz globs the purge receipts rely on are unchanged
    assert [p.name for p in tw.parent.glob("*.jsonl.gz")] == [Path(path).name]


def test_empty_archive_writes_no_tripwire(tmp_path, monkeypatch):
    import db_retention as dr
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert dr.archive_rows(_RowsCur([]), "scope_governor_audit", "created_at", 30, "")[0] == 0
    assert not (tmp_path / "archive" / "db_retention" / "scope_governor_audit" / "TRIPWIRE.jsonl").exists()


def test_tripwire_write_failure_refuses_the_delete(tmp_path, monkeypatch):
    """The record is written before the DELETE; if it cannot be written, nothing is deleted."""
    from tests.test_retention_source_windows_junk_20261009 import JUNK_RE, _Conn, _Table, _embeddings, _junk_match
    t = _Table(_embeddings(), _junk_match)

    def boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(ra, "write_tripwire_record", boom)
    with pytest.raises(OSError):
        ra.archive_then_delete_batches(_Conn(t), table="content_embeddings", where_sql="x", params=(JUNK_RE,),
                                       label="junk", archive_dir=tmp_path / "content_embeddings", batch_rows=20,
                                       max_rows=40)
    assert t.deletes_executed == 0 and len(t.rows) == 53


def test_verified_batches_record_one_tripwire_line_per_batch(tmp_path):
    from tests.test_retention_source_windows_junk_20261009 import JUNK_RE, _Conn, _Table, _embeddings, _junk_match
    t = _Table(_embeddings(), _junk_match)
    adir = tmp_path / "content_embeddings"
    res = ra.archive_then_delete_batches(_Conn(t), table="content_embeddings", where_sql="x", params=(JUNK_RE,),
                                         label="junk_fused_signal", archive_dir=adir, batch_rows=20, max_rows=1000)
    recs = [json.loads(line) for line in (adir / "TRIPWIRE.jsonl").read_text().splitlines()]
    assert [r["archive"] for r in recs] == [b["path"] for b in res["batches"]]
    assert [r["rows"] for r in recs] == [20, 20, 5] and all(r["label"] == "junk_fused_signal" for r in recs)


# ── 1. tripwire: reader ─────────────────────────────────────────────────────
def _repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts" / "lib").mkdir(parents=True)
    (repo / "config").mkdir()
    (repo / "scripts" / "db_retention.py").write_text("# writes persistent-state/archive/db_retention/<table>/\n")
    (repo / "config" / "data_retention_policy.json").write_text('{"note": "archive/db_retention/<table>/"}')
    (repo / "scripts" / "fine.py").write_text("print('nothing archived here')\n")
    return repo


def test_reader_is_quiet_when_only_the_writers_name_the_archive(tmp_path):
    units = tmp_path / "units"; units.mkdir()
    (units / "x.service").write_text("ExecStart=/bin/true\n")
    cron = "# 0 1 * * * cat ~/state/archive/db_retention/content_embeddings/x.jsonl.gz  (comment, not a reader)\n"
    assert rt.scan_references(_repo(tmp_path), crontab_text=cron, unit_dir=units) == []


def test_reader_trips_on_repo_crontab_and_systemd_references(tmp_path):
    repo = _repo(tmp_path)
    (repo / "scripts" / "restore_embeddings.py").write_text(
        "SRC = STATE / 'archive/db_retention/content_embeddings'\n")
    (repo / "config" / "loader.yaml").write_text("path: persistent-state/archive/db_trim/20261007T170000Z\n")
    units = tmp_path / "units"; units.mkdir()
    (units / "replay.service").write_text("ExecStart=zcat /s/archive/db_retention/x/a.jsonl.gz\n")
    cron = "15 2 * * * zcat ~/s/archive/db_retention/content_embeddings/*.gz | wc -l\n"
    hits = rt.scan_references(repo, crontab_text=cron, unit_dir=units)
    got = {(h["where"], h["ref"]) for h in hits}
    assert got == {("repo", "scripts/restore_embeddings.py"), ("repo", "config/loader.yaml"),
                   ("crontab", "line 1"), ("systemd", "replay.service")}


def test_findings_shape_missing_archive_and_unreadable_line(tmp_path):
    state = tmp_path / "state"
    tdir = state / "archive" / "db_retention" / "content_embeddings"
    tdir.mkdir(parents=True)
    kept = tdir / "20261011T000000Z.jsonl.gz"
    kept.write_bytes(gzip.compress(b'{"id": 1}\n'))
    ra.write_tripwire_record(kept, table="content_embeddings", rows=1, sha256="x")
    gone = tdir / "20261010T000000Z.jsonl.gz"
    ra.write_tripwire_record(gone, table="content_embeddings", rows=7, sha256="y")
    with open(tdir / "TRIPWIRE.jsonl", "a") as fh:
        fh.write("{not json\n")
    trim = state / "archive" / "db_trim"; trim.mkdir(parents=True)
    (trim / "TRIPWIRE.jsonl").write_text(json.dumps({"kind": "table", "name": "bak_x", "dump": str(trim / "nope.sql.gz")})
                                         + "\n")
    repo = _repo(tmp_path)
    (repo / "scripts" / "reader.py").write_text("open('archive/db_retention/content_embeddings/a.jsonl.gz')\n")
    units = tmp_path / "units"; units.mkdir()
    fs = rt.findings(state, repo, crontab_text="", unit_dir=units)
    by = {(f["code"], f["item"]): f for f in fs}
    assert by[("ARCHIVE_TRIPWIRE", "repo:scripts/reader.py")]["severity"] == "P1"
    assert by[("ARCHIVE_MISSING", str(gone))]["severity"] == "P2"
    assert ("ARCHIVE_MISSING", str(trim / "nope.sql.gz")) in by           # db_trim's TRIPWIRE.jsonl is read too
    assert ("ARCHIVE_MISSING", str(kept)) not in by
    assert any(c == "TRIPWIRE_UNREADABLE" for c, _ in by)
    assert all(set(f) == {"code", "item", "severity", "detail"} for f in fs)


def test_committed_tree_has_no_live_reader_of_an_archive(tmp_path):
    """The repo's own scripts/config must not name an archive outside the writer allowlist."""
    units = tmp_path / "units"; units.mkdir()
    assert rt.scan_references(ROOT, crontab_text="", unit_dir=units) == []
    for rel in rt.ALLOWLIST_REL:
        assert (ROOT / rel).is_file(), f"stale allowlist entry {rel}"


def test_hygiene_report_appends_tripwire_findings_and_never_crashes(monkeypatch):
    import scripts.report_db_hygiene as h
    monkeypatch.setattr(rt, "findings", lambda *a, **k: [
        {"code": "ARCHIVE_TRIPWIRE", "item": "crontab:line 9", "severity": "P1", "detail": "names archive/db_retention"}])
    assert h.tripwire_findings()[0]["code"] == "ARCHIVE_TRIPWIRE"

    def broken(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(rt, "findings", broken)
    (f,) = h.tripwire_findings()
    assert f["code"] == "TRIPWIRE_UNREADABLE" and f["severity"] == "P2" and "disk gone" in f["detail"]


def test_tripwire_finding_becomes_a_p1_incident(tmp_path):
    from scripts.n8n_incident_fanin import collect
    root = tmp_path / "state"; (root / "data" / "runtime").mkdir(parents=True); (root / "backups" / "n8n").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    (root / "data" / "runtime" / "db_hygiene_last.json").write_text(json.dumps({
        "schema": "DbHygieneReport@v1", "as_of": now.isoformat(), "findings": [
            {"code": "ARCHIVE_TRIPWIRE", "item": "repo:scripts/reader.py", "severity": "P1",
             "detail": "names archive/db_retention"}]}))
    items = {(f["source"], f["item"], f["severity"]) for f in collect(root, now)}
    assert ("db_hygiene", "ARCHIVE_TRIPWIRE:repo:scripts/reader.py", "P1") in items


# ── 2. grant id for --apply ─────────────────────────────────────────────────
def _ledger(tmp_path, *, expires_in=3600, uses=5, tier="db-write"):
    gl = dwg._guard_ledger()
    adir = tmp_path / "approvals"
    gl.ledger_create_grant(tier, expires=int(time.time()) + expires_in, uses=uses, reason="junk purge c45f", adir=adir)
    _, doc = gl.ledger_read(adir)
    return adir, doc[tier]["grant_id"]


def test_grant_verified_against_the_active_ledger_record(tmp_path):
    adir, gid = _ledger(tmp_path)
    assert len(gid) == 32
    full = dwg.verify(gid, adir=adir)
    short = dwg.verify(gid[:16].upper(), adir=adir)          # operators quote 16 chars
    assert full["ok"] and short["ok"] and short["grant_id"] == gid and short["grant_reason"] == "junk purge c45f"


@pytest.mark.parametrize("supplied,why", [
    ("", "is not set"), ("not-a-grant", "is not a grant id"), ("abc123", "is not a grant id"),
    ("0123456789abcdef", "does not match"),
])
def test_grant_refusals(tmp_path, supplied, why):
    adir, _ = _ledger(tmp_path)
    v = dwg.verify(supplied, adir=adir)
    assert v["ok"] is False and why in v["reason"]


def test_grant_refused_when_expired_wrong_tier_or_no_ledger(tmp_path):
    adir, gid = _ledger(tmp_path / "a", expires_in=-5)
    assert "no active db-write grant" in dwg.verify(gid, adir=adir)["reason"]
    adir, gid = _ledger(tmp_path / "b", tier="cron")
    assert "no active db-write grant" in dwg.verify(gid, adir=adir)["reason"]
    v = dwg.verify("ab" * 8, adir=tmp_path / "empty")
    assert v["ok"] is False and "MISSING" in v["reason"]


def test_db_retention_reads_the_grant_from_env(tmp_path, monkeypatch):
    import db_retention as dr
    adir, gid = _ledger(tmp_path)
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(adir))
    monkeypatch.setenv("TRADEAI_DB_WRITE_GRANT", gid[:16])
    assert dr._verify_db_write_grant()["ok"] is True
    monkeypatch.delenv("TRADEAI_DB_WRITE_GRANT")
    assert dr._verify_db_write_grant()["ok"] is False


def _dr_no_grant(monkeypatch, tmp_path, grant):
    import db_retention as dr
    from tests.test_retention_source_windows_junk_20261009 import _Conn, _Table, _embeddings, _junk_match
    t = _Table(_embeddings(), _junk_match)
    connects = []
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(dr, "_connect", lambda: connects.append(1) or _Conn(t))
    monkeypatch.setattr(dr, "_disk_too_low_for_retention", lambda: None)
    monkeypatch.setattr(dr, "_verify_db_write_grant", lambda: copy.deepcopy(grant))
    return dr, t, connects


def test_apply_without_a_valid_grant_refuses_before_connecting(monkeypatch, tmp_path, capsys):
    dr, t, connects = _dr_no_grant(monkeypatch, tmp_path, {"ok": False, "reason": "TRADEAI_DB_WRITE_GRANT is not set"})
    assert dr.purge_junk_fused_embeddings(apply=True) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "refused" and "db-write grant" in out["reason"] and out["grant"]["ok"] is False
    assert connects == [] and t.deletes_executed == 0 and not (tmp_path / "archive").exists()


def test_dry_run_needs_no_grant(monkeypatch, tmp_path, capsys):
    dr, t, _ = _dr_no_grant(monkeypatch, tmp_path, {"ok": False, "reason": "unset"})
    assert dr.purge_junk_fused_embeddings() == 0
    assert "DRY RUN" in capsys.readouterr().out and t.deletes_executed == 0


def test_apply_receipt_records_the_grant(monkeypatch, tmp_path):
    grant = {"schema": "DbWriteGrantCheck@v1", "ok": True, "grant_id": "c45f5cc126cd1d7c" + "0" * 16,
             "grant_id_supplied": "c45f5cc126cd1d7c"}
    dr, t, _ = _dr_no_grant(monkeypatch, tmp_path, grant)
    assert dr.purge_junk_fused_embeddings(apply=True, batch_rows=20, max_rows=1000) == 0
    (rec_path,) = (tmp_path / "archive" / "db_retention" / "content_embeddings" / "receipts").glob("*.json")
    rec = json.loads(rec_path.read_text())
    assert rec["status"] == "ok" and rec["grant"] == grant
    assert (tmp_path / "archive" / "db_retention" / "content_embeddings" / "TRIPWIRE.jsonl").is_file()


# ── 3. one owner for the content_embeddings 90 d rail ───────────────────────
def test_registry_names_db_retention_owner_and_archive_first_is_on():
    # Operator 2026-10-11: archive the 90 d content_embeddings rows, then delete them (archive_first true).
    import db_retention as dr
    doc = _registry()
    assert validate(doc) == []
    row = next(r for r in doc["policies"] if r["table"] == "content_embeddings")
    assert row["class"] == "DELETE" and row["window_days"] == 90 and row["archive_first"] is True
    assert "SOLE owner" in row["reason"]
    enforced = {t: (d, a) for t, _c, d, a in dr.enforced_policies(doc)}
    assert enforced["content_embeddings"] == (90, True)
    row["archive_first"] = False
    assert {t: a for t, _c, _d, a in dr.enforced_policies(doc)}["content_embeddings"] is False


@pytest.mark.parametrize("table,value,needle", [
    ("content_embeddings", "yes", "must be true or false"),
    ("hermes_external_research", False, "DELETE rows only"),
])
def test_registry_gate_checks_archive_first(table, value, needle):
    doc = _registry()
    next(r for r in doc["policies"] if r["table"] == table)["archive_first"] = value
    assert any(needle in e for e in validate(doc))


def _librarian():
    path = ROOT / "scripts" / "lib" / "hermes_librarian" / "retention.py"
    spec = importlib.util.spec_from_file_location("hermes_librarian_retention_20261011", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _LibCur:
    def __init__(self, log):
        self.log = log
        self._one = (0,)

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.log.append(s)
        aged = "FROM content_embeddings WHERE created_at <" in s
        self._one = (4,) if (s.startswith("SELECT COUNT(*)") and aged) else (0,)

    def fetchone(self):
        return self._one

    def close(self):
        pass


class _LibConn:
    def __init__(self):
        self.log: list[str] = []

    def cursor(self):
        return _LibCur(self.log)

    def commit(self):
        pass


def test_librarian_defers_the_age_rail_to_db_retention(capsys):
    mod = _librarian()
    pol = mod.load_policy()
    assert pol["content_embeddings"]["max_age_owner"] == "db_retention"
    conn = _LibConn()
    res = mod.apply_retention(conn, dry_run=False)
    age = [a for a in res["actions"] if a["action"] == "purge_by_age"]
    assert age == [{"table": "content_embeddings", "action": "purge_by_age", "count": 0, "threshold_days": 90,
                    "deferred_to": "db_retention", "pointer": mod.AGE_RAIL_POINTER}]
    assert not any("FROM content_embeddings WHERE created_at" in s for s in conn.log)
    assert "DEFERRED to db_retention" in capsys.readouterr().err
    # the orphan purges (not the 90 d rail) stay with the librarian
    assert {a["action"] for a in res["actions"]} >= {"purge_news_orphans", "purge_hermes_research_orphans"}


def test_librarian_owner_override_restores_the_old_purge(monkeypatch):
    mod = _librarian()
    pol = copy.deepcopy(mod.load_policy())
    pol["content_embeddings"]["max_age_owner"] = "librarian"
    monkeypatch.setattr(mod, "load_policy", lambda: pol)
    conn = _LibConn()
    res = mod.apply_retention(conn, dry_run=False)
    assert any(s.startswith("DELETE FROM content_embeddings WHERE created_at") for s in conn.log)
    assert [a["count"] for a in res["actions"] if a["action"] == "purge_by_age"] == [4]
