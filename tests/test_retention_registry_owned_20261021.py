"""Registry-owned retention (operator rulings 2026-10-21, packets/retention-all-managed/OPERATOR_DECISION.md).

Operator: "approve all archive-first conversions, remove duplicate/rogue deleters, standardize on registry-owned
retention". One test (or a small group) per ruling:
  D1    archive cap + budget declared; market_quotes stays hard DELETE.
  D3.1  options_chain_snapshots: registry ARCHIVE_THEN_DELETE 45 d; options_desk_enterprise deletes nothing.
  D3.2  youtube_transcripts: purge_youtube_transcripts archives first; transcript_processor delegates to it.
  D3.3  news_symbol_guard deletes through managed_purge (children first), never a bare DELETE.
  D3.4  hermes_source_registry RSS-stub cleanup archives first.
  D3.5  reports_portal purge archives first (telegram_outbox included).
  D4.1  health_agent.persist() deletes nothing.
  D4.2  hermes_score_history: retention script RETIRED (counts only); self-tune purge of it gone.
  D4.3  market_movers registry row (DELETE 7 d archive_first); finviz_market_movers deletes nothing.
  D5.1  siem purge: alert_events at the registry's 30 d.
  D5.2  research critique: archived research 180 d by created_at (librarian policy).
  D5.4  self-tune: hermes_external_research purge gone.
  D8.1  rotate_runtime_logs.sh archives the head (verified, tripwire) before truncating.
  D8.3  disk_hygiene_enforcer archives release-local data CURRENT does not hold before removing a release.
  D8.4  portfolio news history / weekly / monthly reports archive-then-unlink.
  D8.5  scalp_cycle_receipt.prune archives first; a failed archive removes nothing.
  D8.6  file_prune row ingestion_summaries removed.
  gate  check_retention_policy: RETIRED owners must not delete; archive_prune counts as a deleter.
No database, no network, no production path: fake connections, tmp dirs, TRADEAI_STATE_ROOT in tmp.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts" / "lib") not in sys.path:
    sys.path.append(str(ROOT / "scripts" / "lib"))  # scalp_cycle_receipt is imported top-level by its callers

from lib import retention_archive as ra  # noqa: E402
from lib import retention_tripwire as rt  # noqa: E402
from scripts import check_retention_policy as crp  # noqa: E402

REG = json.loads((ROOT / "config" / "data_retention_policy.json").read_text(encoding="utf-8"))
POL = {r["table"]: r for r in REG["policies"]}
PP = {e["id"]: e for e in REG["purge_paths"]}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    """Fake credentials (never used) and an archive root in tmp, so no test can touch persistent-state."""
    monkeypatch.setenv("DB_PASSWORD", "synthetic-retention-fixture-unused")
    monkeypatch.setenv("TRADE_AI_DSN", "fixture-only-never-connect")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    # The scripts import ``lib.retention_archive`` at call time; patch whatever module object that name resolves to
    # now (another test file may have re-imported the package), not the one bound when this file was collected.
    global ra
    import importlib

    ra = importlib.import_module("lib.retention_archive")


# ── fake DB: rows carry "old" (the WHERE stand-in); DELETEs stage until COMMIT ─────────────────────
class _Table:
    def __init__(self, n_old=4, n_new=2):
        self.rows = {i: {"id": i, "old": i <= n_old, "payload": "x" * 16} for i in range(1, n_old + n_new + 1)}
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
        self.rowcount, self._all, self._one, self._iter, self.itersize = 0, [], (0,), [], 0

    def execute(self, sql, params=()):
        t = self.t
        s = " ".join(sql.split())
        t.sql.append(s)
        params = tuple(params or ())
        if "FOR UPDATE" in s:
            self._all = [(r["id"],) for r in t.old()][: params[-1]]
        elif s.startswith("SELECT row_to_json(t)") and "ANY(%s)" in s:
            keys = set(params[0])
            self._iter = [(copy.deepcopy(r),) for r in t.live() if r["id"] in keys]
        elif s.startswith("SELECT count(*)"):
            self._one = (len(t.old()),)
        elif s.startswith("DELETE") and "ANY(%s)" in s:
            hit = [k for k in params[0] if k in t.rows and k not in t.staged]
            t.staged.update(hit)
            self.rowcount = len(hit)
        elif s.startswith("DELETE"):
            hit = [r["id"] for r in t.old()]
            t.staged.update(hit)
            self.rowcount = len(hit)
            self._all = [(k,) for k in hit]
        else:
            self._all, self._one = [], (0,)

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

    def close(self):
        pass


def _bare_deletes(t: _Table) -> list[str]:
    """DELETEs that are not the archive helper's key-list delete (``t.id = ANY(%s)`` after a verified archive)."""
    return [s for s in t.sql if s.upper().startswith("DELETE") and "ANY(%s)" not in s]


def _row_archive(tmp_path: Path, table: str) -> list[dict]:
    d = tmp_path / "state" / "archive" / "db_retention" / table
    rows = []
    for f in sorted(d.glob("*.jsonl.gz")):
        rows += [json.loads(line) for line in gzip.open(f, "rt")]
    assert (d / "TRIPWIRE.jsonl").is_file(), f"no tripwire for {table}"
    return rows


# ── D1 / D3.1 / D4.3 / D8.6: the registry ─────────────────────────────────────────────────────────
def test_d1_archive_cap_and_budget_and_market_quotes_stays_hard_delete():
    assert REG["archive_growth_cap_gb_month"] == 2.0 and float(REG["archive_total_budget_gb"]) == 25.0
    mq = POL["market_quotes"]
    assert mq["class"] == "DELETE" and mq["archive_first"] is False and len(mq["archive_first_hold"]) >= 20


def test_d3_1_options_chain_snapshots_is_archive_then_delete_45d():
    r = POL["options_chain_snapshots"]
    assert (r["class"], r["window_days"], r["archive"], r["ts_column"]) == ("ARCHIVE_THEN_DELETE", 45, True, "captured_at")


def test_d4_3_market_movers_has_a_registry_row_archive_first():
    r = POL["market_movers"]
    assert (r["class"], r["window_days"], r["archive_first"], r["ts_column"]) == ("DELETE", 7, True, "captured_at")
    import db_retention as dr

    assert ("market_movers", "captured_at", 7, True) in dr.enforced_policies(REG)


def test_d8_6_dead_ingestion_summaries_file_prune_row_is_gone():
    assert "ingestion_summaries" not in {r["id"] for r in REG["file_prune"]}


def test_d11_no_new_deletion_only_the_moved_owner():
    """D11 HOLD: the only table db_retention newly deletes from is market_movers (deleted today inline at 7 d)."""
    import db_retention as dr

    enforced = {t: (d, af) for t, _c, d, af in dr.enforced_policies(REG)}
    assert len(enforced) == 126 and enforced["market_movers"] == (7, True)
    for t in ("gir_edge", "gir_entity", "gir_envelope"):  # D11 items stay unregistered
        assert t not in enforced
    assert POL["scope_governor_audit"]["window_days"] == 30  # D11: 30 -> 14 held
    assert POL["screener_symbol_membership"]["window_days"] == 365  # unchanged


# ── D3.1: options_desk_enterprise deletes nothing ─────────────────────────────────────────────────
def test_d3_1_options_desk_persist_and_cron_prune_delete_nothing(monkeypatch):
    import options_desk_enterprise as ent

    t = _Table()
    conn = _Conn(t)
    monkeypatch.setattr(ent, "_conn", lambda: conn)
    ent.persist_chain_snapshot("AAPL", {"underlying_price": 1.0, "expirations": []}, {"ok": True})
    assert any(s.startswith("INSERT INTO options_chain_snapshots") for s in t.sql)
    out = ent.prune_chain_snapshots()
    assert out["deleted"] == 0 and out["retired"] and "db_retention" in out["owner"]
    assert not [s for s in t.sql if s.upper().startswith("DELETE")]
    assert PP["options_chain_snapshot_prune"]["state"] == "RETIRED"


# ── D3.2: youtube_transcripts archive-first, one owner ────────────────────────────────────────────
def test_d3_2_youtube_purge_archives_then_deletes(tmp_path):
    import purge_youtube_transcripts as pyt

    t = _Table()
    res = pyt.purge(_Conn(t), apply=False)
    assert res["deleted"] == 0 and not [s for s in t.sql if s.startswith("DELETE")]
    res = pyt.purge(_Conn(t), apply=True)
    assert res["deleted"] == res["archived"] == 4 and not _bare_deletes(t)
    assert sorted(r["id"] for r in _row_archive(tmp_path, "youtube_transcripts")) == [1, 2, 3, 4]
    assert sorted(t.rows) == [5, 6]


def test_d3_2_transcript_processor_purge_expired_delegates_to_the_archive_path(monkeypatch, tmp_path):
    import transcript_processor as tp

    t = _Table()
    monkeypatch.setattr(tp, "_get_conn", lambda: _Conn(t))
    assert tp.purge_expired() == 4
    assert not _bare_deletes(t) and len(_row_archive(tmp_path, "youtube_transcripts")) == 4
    assert PP["purge_youtube_transcripts"]["state"] == "MANAGED"


# ── D3.3: news_symbol_guard ───────────────────────────────────────────────────────────────────────
class _GuardCur:
    def __init__(self):
        self.sql: list[str] = []
        self._pending: list = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.sql.append(s)
        if s.startswith("SELECT id, title, summary FROM news_articles"):
            self._pending = [(11, "Pasqal quantum start-up raises", "")]
        elif s.startswith("SELECT id, headline, description FROM catalyst_events"):
            self._pending = [(42, "Pasqal quantum start-up raises", "")]
        elif s.startswith("SELECT id FROM catalyst_symbol_impact"):
            self._pending = [(7,), (8,)]
        else:
            self._pending = []

    def fetchall(self):
        rows, self._pending = self._pending, []
        return rows

    def fetchone(self):
        return None


class _GuardConn:
    def __init__(self):
        self.cur = _GuardCur()
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def test_d3_3_news_symbol_guard_archives_children_first_and_never_bare_deletes(monkeypatch):
    import news_symbol_guard as g

    calls = []

    def fake_managed_purge(conn, **kw):
        calls.append(kw)
        return {"deleted": len(kw["params"][0]), "archived": len(kw["params"][0])}

    monkeypatch.setattr(ra, "managed_purge", fake_managed_purge)
    monkeypatch.setattr(g, "headline_matches_symbol", lambda *a, **k: (False, "foreign_company"))
    conn = _GuardConn()
    out = g.purge_mismatched_for_symbol(conn, "MRLN", apply=True)
    assert out == {"symbol": "MRLN", "news_removed": 1, "catalyst_removed": 1}
    assert not [s for s in conn.cur.sql if s.upper().startswith("DELETE")]
    assert [(c["table"], c["params"][0]) for c in calls] == [
        ("news_articles", [11]), ("catalyst_symbol_impact", [7, 8]), ("catalyst_events", [42])]
    assert all(c["archive"] is True and c["apply"] is True and c["where_sql"] == "t.id = ANY(%s)" for c in calls)
    calls.clear()
    g.purge_mismatched_for_symbol(_GuardConn(), "MRLN", apply=False)
    assert calls == []


# ── D3.4: hermes_source_registry RSS stubs ────────────────────────────────────────────────────────
def test_d3_4_rss_stub_cleanup_archives_first(tmp_path):
    import hermes_source_registry as hsr

    t = _Table(n_old=2, n_new=3)
    assert hsr.cleanup_orphan_rss_rows(_Conn(t).cursor()) == 2
    assert not _bare_deletes(t)
    assert sorted(r["id"] for r in _row_archive(tmp_path, "research_sources")) == [1, 2]


def test_managed_purge_restores_autocommit_for_an_autocommit_caller(tmp_path):
    class _AC(_Conn):
        autocommit = True
        seen: list = []

        def cursor(self, name=None):
            self.seen.append(self.autocommit)
            return _Cur(self.t, self)

    t = _Table(n_old=2, n_new=1)
    conn = _AC(t)
    r = ra.managed_purge(conn, table="research_sources", where_sql="t.old", label="x", writer="w", apply=True)
    assert r["deleted"] == 2 and conn.autocommit is True
    assert False in conn.seen  # the archived batch ran inside a transaction


# ── D3.5: reports_portal purge ────────────────────────────────────────────────────────────────────
def test_d3_5_reports_portal_purge_archives_every_table_first(monkeypatch, tmp_path):
    import reports_portal as rp

    t = _Table()
    monkeypatch.setattr(rp, "_conn", lambda: _Conn(t))
    out = rp.purge(older_than_days=90, apply=True)
    assert out["ok"] and out["deleted"]["notification_log"] == 4
    assert not _bare_deletes(t)
    assert len(_row_archive(tmp_path, "notification_log")) == 4
    tw = [json.loads(x) for x in (tmp_path / "state/archive/db_retention/notification_log/TRIPWIRE.jsonl")
          .read_text().splitlines()]
    assert {x["writer"] for x in tw} == {"reports_portal"}


def test_d3_5_reports_portal_telegram_outbox_goes_through_the_archive(monkeypatch):
    import reports_portal as rp

    seen = []
    monkeypatch.setattr(ra, "managed_purge", lambda conn, **kw: seen.append(kw) or {"deleted": 0})
    monkeypatch.setattr(rp, "_conn", lambda: _Conn(_Table()))
    assert rp.purge(apply=True)["ok"]
    ob = [kw for kw in seen if kw["table"] == "telegram_outbox"]
    assert ob and ob[0]["archive"] is True and "t.sent_at <" in ob[0]["where_sql"]


# ── D4.1: health_agent.persist ────────────────────────────────────────────────────────────────────
def test_d4_1_health_agent_persist_deletes_nothing(monkeypatch, tmp_path):
    import health_agent as ha

    sql = []
    monkeypatch.setattr(ha, "_db", lambda q, params=None, fetch=None: sql.append(" ".join(q.split())))
    monkeypatch.setattr(ha, "ensure_snapshot_table", lambda: None)
    monkeypatch.setattr(ha, "STATE_DIR", tmp_path)
    monkeypatch.setattr(ha, "STATUS_FILE", tmp_path / "s.json")
    monkeypatch.setattr(ha, "AUDIT_JSONL", tmp_path / "a.jsonl")
    snap = {"overall_score": 90, "status": "ok", "category_scores": {}, "findings": [], "mode": "x",
            "captured_at": "2026-10-21T00:00:00Z", "trends": {}}
    ha.persist(snap, {"history": {"retention_days": 90}})
    assert sql and sql[0].startswith("INSERT INTO health_agent_snapshots")
    assert not [s for s in sql if s.upper().startswith("DELETE")]
    assert POL["health_agent_snapshots"]["window_days"] == 30 and POL["health_agent_snapshots"]["archive_first"]


# ── D4.2 / D5.4: hermes_score_history + hermes_external_research ──────────────────────────────────
def test_d4_2_score_history_retention_is_retired_and_counts_only():
    import hermes_score_history_retention as hsr

    t = _Table()
    out = hsr.run(days=21, apply=True, conn=_Conn(t))
    assert out["rows_deleted"] == 0 and out["retired"] == "2026-10-21" and "db_retention" in out["owner"]
    assert not [s for s in t.sql if s.upper().startswith("DELETE")]
    assert "DELETE FROM" not in (ROOT / "scripts" / "hermes_score_history_retention.py").read_text(encoding="utf-8")
    assert PP["hermes_score_history_retention"]["state"] == "RETIRED"


def test_d4_2_d5_4_self_tune_no_longer_purges_score_history_or_external_research(monkeypatch):
    import hermes_autonomous_self_tune as st

    tables = []
    monkeypatch.setattr(st, "_archived_purge", lambda cur, label, table, *a, **k: tables.append(table) or 0)
    monkeypatch.setattr(st, "_purge", lambda *a, **k: 0)
    monkeypatch.setattr(st, "_refuse_if_learn_only", lambda *a, **k: None)
    monkeypatch.setattr(st, "DEAD_TABLES", [])
    out = st.self_purge(_Cur(_Table(), None), apply=False)
    assert "hermes_score_history" not in tables and "hermes_external_research" not in tables
    assert "hermes_research_intelligence" in tables and "hermes_embedding_queue" in tables
    assert out["score_history_purged"] == 0 and out["external_purged"] == 0


# ── D4.3: finviz_market_movers ────────────────────────────────────────────────────────────────────
def test_d4_3_finviz_market_movers_has_no_inline_delete():
    src = (ROOT / "scripts" / "finviz_market_movers.py").read_text(encoding="utf-8")
    assert crp.DELETER_RE.search(src) is None
    assert PP["finviz_market_movers_prune"]["state"] == "RETIRED"


# ── D5.1: siem alert_events at the registry window ────────────────────────────────────────────────
def test_d5_1_siem_alert_events_follow_the_registry_30d(monkeypatch):
    import siem_retention_purge as sp

    assert sp.table_days("alert_events", 14) == POL["alert_events"]["window_days"] == 30
    assert sp.table_days("system_health_events", 14) == 14
    seen = []
    monkeypatch.setattr(ra, "managed_purge", lambda conn, **kw: seen.append((kw["table"], kw["params"])) or
                        {"table": kw["table"], "eligible": 0, "deleted": 0, "archived": 0, "archive": True})
    out = sp.purge(_Conn(_Table()), 14, apply=False)
    assert dict(seen) == {"system_health_events": (14,), "alert_events": (30,)}
    assert {r["table"]: r["days"] for r in out} == {"system_health_events": 14, "alert_events": 30}


# ── D5.2: research critique follows the librarian's 180 d (created_at) ────────────────────────────
def test_d5_2_research_critique_archived_research_is_180d_by_created_at(monkeypatch):
    import yaml

    import research_critique_pipeline as rcp

    lib = yaml.safe_load((ROOT / "config" / "hermes_librarian_policy.yaml").read_text(encoding="utf-8"))
    assert rcp.RETENTION_RESEARCH_DAYS == lib["hermes_research_intelligence"]["archived_purge_days"] == 180
    seen = {}
    monkeypatch.setattr(ra, "managed_purge", lambda conn, **kw: seen.setdefault(kw["table"], kw) and None
                        or {"deleted": 0, "eligible": 0})
    rcp.retention_purge(_Conn(_Table()), apply=False)
    hri = seen["hermes_research_intelligence"]
    assert "t.created_at <" in hri["where_sql"] and "updated_at" not in hri["where_sql"]
    assert hri["params"] == (180,)


# ── D8.1: rotate_runtime_logs.sh ──────────────────────────────────────────────────────────────────
def _run_rotate(tmp_path: Path, **env) -> subprocess.CompletedProcess:
    e = {**os.environ, "ROTATE_LOG_DIR": str(tmp_path / "logs"), "TRADEAI_STATE_ROOT": str(tmp_path / "state"),
         "ROTATE_LIMIT_MB": "1", "ROTATE_TAIL_MB": "1", **env}
    return subprocess.run(["bash", str(ROOT / "scripts" / "rotate_runtime_logs.sh")], env=e,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(shutil.which("gzip") is None, reason="needs gzip")
def test_d8_1_rotation_archives_the_head_before_truncating(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    body = b"".join(f"line {i:07d} {'z' * 40}\n".encode() for i in range(60000))  # ~3.2 MB
    (logs / "big.log").write_bytes(body)
    r = _run_rotate(tmp_path)
    assert r.returncode == 0, r.stderr
    assert (logs / "big.log").stat().st_size == 0
    head_b = len(body) - 1048576
    adir = tmp_path / "state" / "archive" / "logs"
    (head,) = list(adir.glob("big.*.gz"))
    assert gzip.decompress(head.read_bytes()) == body[:head_b]
    (tail,) = list(logs.glob("big.*.log.gz"))
    assert gzip.decompress(tail.read_bytes()) == body[head_b:]
    (rec,) = [json.loads(x) for x in (adir / "TRIPWIRE.jsonl").read_text().splitlines()]
    assert rec["schema"] == "RetentionArchiveTripwire@v1" and rec["archive"] == str(head)
    assert rec["sha256"] == hashlib.sha256(body[:head_b]).hexdigest() and rec["bytes"] == head_b
    # the tripwire reader sees the new archive root (and reports a missing archive file)
    recs, bad = rt.load_records(tmp_path / "state")
    assert bad == [] and [x["archive"] for x in recs] == [str(head)]


@pytest.mark.skipif(shutil.which("gzip") is None, reason="needs gzip")
def test_d8_1_surplus_tail_archives_move_into_the_archive_not_removed(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    for i in range(3):
        f = logs / f"big.2026010{i}-000000.log.gz"
        f.write_bytes(gzip.compress(f"old {i}\n".encode()))
        os.utime(f, (1_700_000_000 + i, 1_700_000_000 + i))
    (logs / "big.log").write_bytes(b"y" * (2 * 1048576 + 10))
    assert _run_rotate(tmp_path, ROTATE_KEEP="2").returncode == 0
    adir = tmp_path / "state" / "archive" / "logs"
    moved = sorted(p.name for p in adir.glob("big.2026*.log.gz"))
    assert moved == ["big.20260100-000000.log.gz", "big.20260101-000000.log.gz"]
    assert len(list(logs.glob("big.*.log.gz"))) == 2


def test_d8_1_archive_logs_is_a_tripwire_needle_and_the_tree_has_no_reader():
    assert "archive/logs" in rt.NEEDLES and "scripts/rotate_runtime_logs.sh" in rt.ALLOWLIST_REL
    assert [h for h in rt.scan_references(ROOT, crontab_text="", unit_dir=ROOT / "no-such-dir")] == []


# ── D8.3: disk_hygiene_enforcer release-local data ────────────────────────────────────────────────
def _release(root: Path, name: str, files: dict, mtime: float) -> Path:
    d = root / name
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    os.utime(d, (mtime, mtime))
    return d


def _hygiene():
    import disk_hygiene_enforcer as hy

    return hy


def test_d8_3_release_local_data_not_in_current_is_archived_before_the_release_goes(tmp_path):
    hy = _hygiene()
    root = tmp_path / "portfolio-server"
    old = _release(root, "000aaa-main-exact-phase2-20261001-000000",
                   {"data/portfolios/reports/r.html": "same", "data/raw/x.csv": "only-old",
                    "state/hermes.release-local/s.json": "old-state", "code.py": "c"}, 1_700_000_000)
    _release(root, "0a0a0a-main-exact-phase2-20261010-000000", {"code.py": "c"}, 1_700_000_050)
    cur = _release(root, "111bbb-main-exact-phase2-20261021-000000",
                   {"data/portfolios/reports/r.html": "same", "data/raw/x.csv": "newer"}, 1_700_000_100)
    (root / "CURRENT").symlink_to(cur)
    plan = hy.plan_releases({"root": str(root), "glob": "*-main-exact-*", "keep_n": 1, "protect_symlinks": ["CURRENT"]})
    assert plan["delete"] == [str(old)] and plan["reference"] == str(cur)
    dry = hy.apply_release_deletes(plan, dry_run=True)
    assert dry["deleted"][0]["release_local"]["files"] == 2 and old.exists()
    res = hy.apply_release_deletes(plan, dry_run=False)
    assert res["ok"] and not old.exists() and cur.exists()
    (tar,) = list((tmp_path / "state/archive/file_prune/release_local_data").glob("*.tar.gz"))
    with tarfile.open(tar) as tf:
        names = sorted(tf.getnames())
        assert names == ["data/raw/x.csv", "state/hermes.release-local/s.json"]
        assert tf.extractfile("data/raw/x.csv").read() == b"only-old"
    assert (tar.parent / "TRIPWIRE.jsonl").is_file()


def test_d8_3_failed_archive_keeps_the_release(tmp_path, monkeypatch):
    hy = _hygiene()
    root = tmp_path / "portfolio-server"
    old = _release(root, "000aaa-main-exact-phase2-20261001-000000", {"data/raw/x.csv": "only-old"}, 1_700_000_000)
    _release(root, "0a0a0a-main-exact-phase2-20261010-000000", {"code.py": "c"}, 1_700_000_050)
    cur = _release(root, "111bbb-main-exact-phase2-20261021-000000", {"code.py": "c"}, 1_700_000_100)
    (root / "CURRENT").symlink_to(cur)

    def boom(*a, **k):
        raise ra.ArchiveVerifyError("simulated")

    monkeypatch.setattr(ra, "archive_files_then_unlink", boom)
    plan = hy.plan_releases({"root": str(root), "glob": "*-main-exact-*", "keep_n": 1, "protect_symlinks": ["CURRENT"]})
    res = hy.apply_release_deletes(plan, dry_run=False)
    assert not res["ok"] and old.exists() and (old / "data/raw/x.csv").read_text() == "only-old"
    assert "release kept" in res["errors"][0]


# ── D8.4: portfolio report rotation ───────────────────────────────────────────────────────────────
def test_d8_4_portfolio_news_history_is_archived_then_unlinked(tmp_path):
    import portfolio_news as pn

    hist = tmp_path / "history"
    hist.mkdir()
    for day in ("2020-01-01", "2020-01-02", "2999-01-01"):
        (hist / f"{day}.json").write_text(json.dumps({"d": day}))
    res = pn._prune_history(hist)
    assert res["unlinked"] == 2 and sorted(p.name for p in hist.iterdir()) == ["2999-01-01.json"]
    with tarfile.open(res["archive"]) as tf:
        assert sorted(tf.getnames()) == ["2020-01-01.json", "2020-01-02.json"]
    assert Path(res["archive"]).parent.name == "portfolio_news_history"


@pytest.mark.parametrize("mod,label", [("portfolio_weekly_report", "portfolio_weekly_reports"),
                                       ("portfolio_monthly_report", "portfolio_monthly_reports"),
                                       ("portfolio_monthly_synthesis", "portfolio_monthly_synthesis")])
def test_d8_4_report_rotation_archives_and_never_bare_unlinks(mod, label, tmp_path):
    import importlib

    m = importlib.import_module(mod)
    src = (ROOT / "scripts" / f"{mod}.py").read_text(encoding="utf-8")
    assert ".unlink()" not in src and f'"{label}"' in src
    d = tmp_path / "reports"
    d.mkdir()
    (d / "monthly_2020-01.html").write_text("x")
    res = m._archive_prune([d / "monthly_2020-01.html"], d, label, mod)
    assert res["unlinked"] == 1 and not (d / "monthly_2020-01.html").exists()
    assert Path(res["archive"]).parent.name == label


def test_archive_prune_failure_unlinks_nothing_and_reports(tmp_path, monkeypatch):
    f = tmp_path / "a.json"
    f.write_text("{}")

    def boom(*a, **k):
        raise ra.ArchiveVerifyError("simulated")

    monkeypatch.setattr(ra, "archive_files_then_unlink", boom)
    res = ra.archive_prune([f], base_dir=tmp_path, label="x", writer="w")
    assert res["unlinked"] == 0 and "simulated" in res["error"] and f.exists()


# ── D8.5: scalp_cycle_receipt.prune ───────────────────────────────────────────────────────────────
def test_d8_5_scalp_receipts_are_archived_before_they_are_pruned(tmp_path):
    import scalp_cycle_receipt as scr

    d = tmp_path / scr.LEDGER_REL
    d.mkdir(parents=True)
    for name in ("2026-08-01.jsonl", "2026-09-09.jsonl", "notes.jsonl"):
        (d / name).write_text(f'{{"f": "{name}"}}\n')
    removed = scr.prune(d, keep_days=30, today="2026-10-09")
    assert removed == ["2026-08-01.jsonl"]
    assert sorted(p.name for p in d.iterdir()) == ["2026-09-09.jsonl", "notes.jsonl"]
    adir = tmp_path / "archive" / "file_prune" / "scalp_cycle_receipts"
    (tar,) = list(adir.glob("*.tar.gz"))
    with tarfile.open(tar) as tf:
        assert tf.getnames() == ["2026-08-01.jsonl"]
    assert (adir / "TRIPWIRE.jsonl").is_file()


def test_d8_5_failed_archive_removes_nothing(tmp_path, monkeypatch):
    import scalp_cycle_receipt as scr

    d = tmp_path / scr.LEDGER_REL
    d.mkdir(parents=True)
    (d / "2026-08-01.jsonl").write_text("{}\n")

    def boom(*a, **k):
        raise ra.ArchiveVerifyError("simulated")

    monkeypatch.setattr(ra, "archive_files_then_unlink", boom)
    assert scr.prune(d, keep_days=30, today="2026-10-09") == []
    assert (d / "2026-08-01.jsonl").exists()


# ── the gate ──────────────────────────────────────────────────────────────────────────────────────
def test_gate_committed_registry_is_clean_including_retired_owners():
    assert crp.validate(REG) == []
    assert crp.unregistered_deleters(REG) == []
    assert crp.retired_still_deleting(REG) == []
    retired = {e["id"] for e in REG["purge_paths"] if e["state"] == "RETIRED"}
    assert retired == {"options_chain_snapshot_prune", "health_agent_snapshot_prune", "finviz_market_movers_prune",
                       "hermes_score_history_retention"}


def test_gate_fails_a_retired_owner_whose_script_still_deletes(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "old_owner.py").write_text('cur.execute("DELETE FROM foo WHERE x")\n')
    (tmp_path / "scripts" / "shared.py").write_text("managed_purge(conn, table='t')\n")
    (tmp_path / "scripts" / "files.py").write_text("archive_prune(files, base_dir=d, label='l', writer='w')\n")
    doc = {"purge_paths": [
        {"id": "old", "state": "RETIRED", "scripts": ["scripts/old_owner.py"]},
        {"id": "shared_retired", "state": "RETIRED", "scripts": ["scripts/shared.py"]},
        {"id": "shared_live", "state": "MANAGED", "scripts": ["scripts/shared.py"]},
    ]}
    errs = crp.retired_still_deleting(doc, root=tmp_path)
    assert len(errs) == 1 and "old_owner.py" in errs[0]
    assert crp.unregistered_deleters(doc, root=tmp_path) == [
        "scripts/files.py: deletes/purges data but no purge_paths entry names it (register owner + class)"]
