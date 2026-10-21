"""Operator rulings 2026-10-21, priority set (OPERATOR_DECISION D6, D8.2, D7, D5.3, D10). Hermetic.

D6   weekly_disk_cleanup_notify runs no DB retention (dev-tree db_retention + librarian steps removed).
D8.2 run_pg_backup.sh writes <name>.part, verifies (size + gzip -t), renames atomically; backup_enforcer
     never touches a .part or anything younger than 2 h (default, no config key needed).
D7   db_trim.py --apply refuses (exit 2) without an active db-write grant, before any DB call.
D5.3 comms_lifecycle's purge never archives or deletes communication_thread_membership (KEEP_FOREVER).
D10  content_embeddings source windows measure the SOURCE document's age; still disabled.

No database, no network, no subprocess.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REG = ROOT / "config" / "data_retention_policy.json"


def _registry() -> dict:
    return json.loads(REG.read_text(encoding="utf-8"))


# ── D6 ──────────────────────────────────────────────────────────────────────
def test_d6_weekly_cleanup_runs_no_db_retention_or_librarian(monkeypatch, tmp_path):
    import weekly_disk_cleanup_notify as w

    monkeypatch.setattr(w, "ROOT", tmp_path)
    (tmp_path / "logs").mkdir()
    disk = {"free_gb": 80.0, "used_pct": 82.0, "free_pct": 18.0, "level": "ok"}
    monkeypatch.setattr(w, "_disk", lambda: dict(disk))
    monkeypatch.setattr(w, "_clean_preclean_dirs",
                        lambda dry_run=True: {"ok": True, "deleted": [], "bytes_reclaimed_est": 0})
    launched: list[str] = []

    def _run_json(argv, timeout=60):
        launched.append(" ".join(str(a) for a in argv))
        return True, {"ok": True, "releases_result": {}, "backups_result": {}, "total_affected": 0}

    monkeypatch.setattr(w, "_run_json", _run_json)
    summary = w.run(apply=True, notify=False)
    assert launched and all("disk_hygiene_enforcer.py" in a for a in launched), launched
    assert not any("db_retention" in a or "librarian_retention" in a for a in launched), launched
    assert {s["name"] for s in summary["steps"]} == {"disk_hygiene", "backup_preclean_dirs"}
    assert summary["db_rows_deleted"] == 0 and summary["librarian_affected"] == 0


def test_d6_registry_names_one_db_retention_scheduler():
    pp = {e["id"]: e for e in _registry()["purge_paths"]}
    sched = pp["db_retention"]["scheduler"]
    assert "platform-maintenance-nightly" in sched and "ONLY" in sched
    assert "ALSO" not in sched


# ── D8.2 ────────────────────────────────────────────────────────────────────
def _load_enforcer():
    spec = importlib.util.spec_from_file_location("backup_enforcer_d82", ROOT / "scripts" / "backup_enforcer.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _stamp(path: Path, age_s: float, now: float, payload: bytes) -> None:
    path.write_bytes(payload)
    os.utime(path, (now - age_s, now - age_s))


def test_d82_pg_backup_writes_part_verifies_then_renames():
    src = (ROOT / "linux_launchers" / "run_pg_backup.sh").read_text(encoding="utf-8")
    assert re.search(r'gzip -9 > "\$PART_FILE"', src), "pg_dump must stream into the .part name"
    i_size = src.index('if [ "$BYTES" -lt "$PARTIAL_MIN_BYTES" ]')          # existing size check, kept
    i_gzip = src.index('gzip -t -- "$PART_FILE"')                            # stream integrity
    i_mv = src.index('mv -f -- "$PART_FILE" "$BACKUP_FILE"')                 # atomic rename
    assert i_size < i_gzip < i_mv
    assert "trap _park_part EXIT" in src                                      # failed dump: parked, not orphaned
    assert not re.search(r"\brm\b[^\n]*PART_FILE", src)                       # never unlinked (rule 6)


def test_d82_enforcer_skips_part_and_dumps_younger_than_2h_by_default(tmp_path):
    be = _load_enforcer()
    d = tmp_path / "db_backups"
    d.mkdir()
    now = 1_800_000_000.0
    cfg = {"dir": str(d), "pattern": "trade_ai_*", "max_count": 1, "min_bytes": 50, "max_total_bytes": 10_000}
    young = d / "trade_ai_young.sql.gz"            # 1.5 h old, under the size floor: a dump still being written
    _stamp(young, 90 * 60, now, b"tiny")
    part = d / "trade_ai_open.sql.gz.part"         # matches this glob; still never touched
    _stamp(part, 5 * 3600, now, b"tiny")
    old = d / "trade_ai_abandoned.sql.gz"          # 3 h old partial: retired to archive/, not unlinked
    _stamp(old, 3 * 3600, now, b"tiny")
    res = be.enforce_local(cfg, dry_run=False, now=now)
    assert young.exists() and part.exists() and not old.exists()
    assert (d / "archive" / old.name).exists()
    assert {Path(p).name for p in res["skipped_in_progress"]} == {young.name, part.name}
    assert be.DEFAULT_SKIP_YOUNGER_S == 2 * 3600


# ── D7 ──────────────────────────────────────────────────────────────────────
class _ReachedDb(Exception):
    pass


def _trim(monkeypatch, tmp_path):
    import db_trim as dt
    calls: list[str] = []

    def _psql(sql, **_k):
        calls.append(sql)
        raise _ReachedDb(sql)

    monkeypatch.setattr(dt, "psql", _psql)
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path / "approvals"))   # empty ledger: no active grant
    return dt, calls


@pytest.mark.parametrize("action", ["drop-duplicate-indexes", "archive-drop-tables", "purge-dead-queues"])
def test_d7_db_trim_apply_without_grant_refuses_exit_2_before_db(monkeypatch, tmp_path, capsys, action):
    dt, calls = _trim(monkeypatch, tmp_path)
    monkeypatch.delenv("TRADEAI_DB_WRITE_GRANT", raising=False)
    assert dt.main([action, "--apply"]) == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "REFUSED --apply" in err and "TRADEAI_DB_WRITE_GRANT" in err


def test_d7_db_trim_apply_with_unknown_grant_still_refuses(monkeypatch, tmp_path):
    dt, calls = _trim(monkeypatch, tmp_path)
    monkeypatch.setenv("TRADEAI_DB_WRITE_GRANT", "c45f5cc126cd1d7c")
    assert dt.main(["purge-dead-queues", "--apply"]) == 2
    assert calls == []


def test_d7_db_trim_dry_run_is_not_gated(monkeypatch, tmp_path):
    dt, calls = _trim(monkeypatch, tmp_path)
    monkeypatch.delenv("TRADEAI_DB_WRITE_GRANT", raising=False)
    with pytest.raises(_ReachedDb):                 # no refusal: it goes straight to its read-only census
        dt.main(["purge-dead-queues"])
    assert len(calls) == 1


def test_d7_db_trim_apply_with_active_grant_proceeds(monkeypatch, tmp_path):
    dt, calls = _trim(monkeypatch, tmp_path)
    monkeypatch.setattr(dt, "_verify_db_write_grant", lambda: {"ok": True, "grant_id": "f" * 32})
    with pytest.raises(_ReachedDb):
        dt.main(["purge-dead-queues", "--apply"])
    assert len(calls) == 1


# ── D5.3 ────────────────────────────────────────────────────────────────────
class _Conn:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class _Cur:
    def __init__(self):
        self.connection, self._rows, self.touched, self.deleted = _Conn(), [], [], []
        self.rowcount, self._served = 0, False

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT count(*) FROM communication_events WHERE status IN"):
            self._rows = [(1,)]
        elif s.startswith("SELECT event_id FROM communication_events"):
            self._rows = [] if self._served else [("e1",)]
            self._served = True
        elif s.startswith("SELECT count(*) FROM"):
            self.touched.append(s.split(" FROM ")[1].split()[0])
            self._rows = [(1,)]
        elif s.startswith("SELECT row_to_json"):
            self.touched.append(s.split(" FROM ")[1].split()[0])
            self._rows = [({"x": 1},)]
        elif s.startswith("DELETE FROM"):
            self.deleted.append(s.split()[2])
            self.rowcount = 1

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


def test_d53_comms_purge_never_touches_thread_membership(monkeypatch, tmp_path):
    import comms_lifecycle as lc
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    cur = _Cur()
    out = lc.step_purge(cur, apply=True)
    assert "communication_thread_membership" not in cur.deleted
    assert "communication_thread_membership" not in cur.touched
    assert "communication_thread_membership" not in out["archived"]
    assert cur.deleted == ["communication_deliveries", "communication_outbox", "communication_entity_links",
                           "communication_events"]                       # other children keep archive-first purge
    assert not (tmp_path / "archive" / "comms_lifecycle" / "communication_thread_membership").exists()
    assert "communication_thread_membership" in lc.KEPT_TABLES


def test_d53_registry_keeps_membership_forever():
    row = next(r for r in _registry()["policies"] if r["table"] == "communication_thread_membership")
    assert row["class"] == "KEEP_FOREVER"


# ── D10 ─────────────────────────────────────────────────────────────────────
def _enabled_windows():
    import db_retention as dr
    doc = _registry()
    for r in doc["policies"]:
        r.pop("source_windows_enabled", None)
    return dr, dr.enforced_source_windows(doc)


def test_d10_source_window_measures_the_source_documents_age():
    dr, ws = _enabled_windows()
    by = {w["source"]: w for w in ws}
    assert set(by) == {"fused_signal", "social_post"}
    for source, table, ts in (("fused_signal", "fused_signals", "created_at"),
                              ("social_post", "social_posts", "ingested_at")):
        pred, params = dr.source_window_predicate(by[source])
        assert f'FROM "{table}" s' in pred and f's."{ts}" < now() - make_interval(days => %s)' in pred
        assert 's."id" = t."source_id"' in pred
        assert 't."created_at"' not in pred                     # the embedding's own age is never the clock
        assert params == (source, 30)


def test_d10_missing_source_table_fails_closed():
    import db_retention as dr
    doc = _registry()
    row = next(r for r in doc["policies"] if r["table"] == "content_embeddings")
    row.pop("source_windows_enabled")
    row["source_windows_source_tables"].pop("social_post")
    with pytest.raises(SystemExit, match="source document"):
        dr.enforced_source_windows(doc)
    with pytest.raises(ValueError):
        dr.source_window_predicate({"source_column": "source_type", "source": "x", "days": 30,
                                    "source_key_column": "source_id", "source_table": "x; DROP",
                                    "source_table_key": "id", "source_table_ts": "created_at"})


def test_d10_still_disabled_so_nothing_runs():
    import db_retention as dr
    doc = _registry()
    row = next(r for r in doc["policies"] if r["table"] == "content_embeddings")
    assert row["source_windows_enabled"] is False
    assert dr.enforced_source_windows(doc) == []

    class _NoCur:
        def execute(self, *a, **k):
            raise AssertionError("a disabled source window reached the database")

    assert dr.run_source_windows(_NoCur(), None, dr.enforced_source_windows(doc), dry_run=True) == (0, [])
