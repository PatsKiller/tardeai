"""in_directive_watch fixed at the source (2026-10-22, operator-approved: "Yes, I agree with your recommendations.").

Before: ``directive_promotion._upsert_watchlist_master`` set ``in_directive_watch = true`` for ANY directive
(automated think_tank / sector_universe trend and sector directives ≈1,729 symbols), un-removed rows the operator had
removed, and nothing ever cleared the flag (273 symbols from expired/archived directives): 2,310 flagged symbols.

After:
* only an ACTIVE operator-created directive (created_by operator / operator_audit) sets the flag or un-removes a row;
  an automated directive records provenance only, and a row it inserts is 'researched', not 'active';
* ``reconcile_directive_watch_flag`` clears the flag where no active operator directive matches (ownership, ticker
  spec symbol, or a promoted hit), backup first, never a delete; dry run by default; ``--expect-clear`` guard;
  ``--restore`` rolls back;
* after the operator's one-time apply (marker file), watch_directives_service keeps it reconciled incrementally;
* the consumers read the flag, so they see the smaller set with no code change (hermes_top20 ``_top`` proven on a
  real Postgres).

Behaviour is proven on a disposable PostgreSQL cluster (tests/support/isolated_pg.py — never production); skipped
only when the host has no PostgreSQL server binaries.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import directive_promotion as dp  # noqa: E402

DP_SRC = (ROOT / "scripts" / "directive_promotion.py").read_text()


# ── static: the writer no longer sets the flag unconditionally ─────────────────────────────────────────────────
def test_upsert_no_longer_sets_the_flag_for_every_directive():
    body = DP_SRC[DP_SRC.index("def _upsert_watchlist_master("):DP_SRC.index("# ── in_directive_watch reconciler")]
    assert "in_directive_watch = true," not in body
    assert "VALUES (%s, %s, 'active', %s, %s::jsonb, %s, true," not in body
    assert "_OPERATOR_DIRECTIVE_SQL" in body


def test_operator_creators_match_the_watch_projection():
    assert dp.OPERATOR_DIRECTIVE_CREATORS == ("operator", "operator_audit")
    wi = (ROOT / "scripts" / "lib" / "data_broker" / "watch_intelligence.py").read_text()
    m = re.search(r"OPERATOR_DIRECTIVE_CREATORS = \(([^)]*)\)", wi)
    if m:  # present once the enrichment-audit PR lands; the two must agree
        assert m.group(1).replace(" ", "") == '"operator","operator_audit"'


class _Cur:
    def __init__(self):
        self.calls = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


def test_upsert_param_count_matches_placeholders():
    cur = _Cur()
    conn = types.SimpleNamespace(cursor=lambda: cur)
    dp._upsert_watchlist_master(conn, "AAA", "trade_ai", {"x": 1}, 3, "trusted", "r")
    for sql, params in cur.calls:
        assert sql.count("%s") == len(params), sql


def test_the_flag_has_one_writer_module():
    """Only directive_promotion.py writes the flag true; nothing else sets it (the reconciler lives there too)."""
    hits = []
    for p in (ROOT / "scripts").rglob("*.py"):
        t = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"in_directive_watch\s*=\s*(true|TRUE)\s*,", t) or "SET in_directive_watch" in t:
            hits.append(str(p.relative_to(ROOT)))
    assert hits == ["scripts/directive_promotion.py"], hits


# ── behaviour on a disposable Postgres ─────────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE watch_directives (id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL,
  spec JSONB NOT NULL DEFAULT '{}', created_by TEXT NOT NULL DEFAULT 'operator', status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE watch_directive_hits (id BIGSERIAL PRIMARY KEY, directive_id BIGINT NOT NULL, symbol TEXT NOT NULL,
  promoted BOOLEAN NOT NULL DEFAULT false);
CREATE TABLE watchlist_items (id BIGSERIAL PRIMARY KEY, symbol TEXT, source TEXT, status TEXT, bucket TEXT,
  origin_system TEXT, origin_detail JSONB, directive_id BIGINT, in_directive_watch BOOLEAN DEFAULT false,
  source_tier TEXT, first_seen_at TIMESTAMPTZ, last_validated_at TIMESTAMPTZ, seen_count INT,
  provenance_reason TEXT, updated_at TIMESTAMPTZ, hermes_rank INT, hermes_composite_score NUMERIC,
  hermes_score_components JSONB, rsi NUMERIC, trend TEXT);
INSERT INTO watch_directives (id, kind, label, spec, created_by, status) VALUES
  (1, 'ticker', 'AAA', '{"symbol":"AAA"}', 'operator', 'active'),
  (2, 'trend', 'op trend', '{}', 'operator', 'active'),
  (3, 'trend', 'auto trend', '{}', 'think_tank', 'active'),
  (4, 'ticker', 'DDD', '{"symbol":"DDD"}', 'advisory', 'expired'),
  (5, 'trend', 'old op trend', '{}', 'operator', 'archived'),
  (6, 'ticker', 'JJJ', '{"symbol":"JJJ"}', 'operator_audit', 'active');
INSERT INTO watch_directive_hits (directive_id, symbol, promoted) VALUES (2, 'CCC', true), (2, 'KKK', false);
INSERT INTO watchlist_items (id, symbol, source, status, directive_id, in_directive_watch, hermes_rank) VALUES
  (1, 'AAA', 'operator', 'researched', 1, true, NULL),
  (2, 'BBB', 'trade_ai', 'researched', 3, true, NULL),
  (3, 'CCC', 'trade_ai', 'researched', 3, true, NULL),
  (4, 'DDD', 'advisory', 'researched', 4, true, NULL),
  (5, 'EEE', 'trade_ai', 'researched', 5, true, NULL),
  (6, 'FFF', 'trade_ai', 'removed', 3, true, NULL),
  (7, 'GGG', 'finviz', 'active', NULL, false, 5),
  (8, 'JJJ', 'operator', 'researched', 3, true, NULL),
  (9, 'KKK', 'trade_ai', 'researched', 3, true, NULL),
  (10, 'RMV', 'trade_ai', 'removed', NULL, false, NULL);
SELECT setval('watchlist_items_id_seq', 100);
SELECT setval('watch_directives_id_seq', 100);
"""


@pytest.fixture(scope="module")
def pg():
    try:
        from support.isolated_pg import IsolatedPostgres, pg_bin_dir
        pg_bin_dir()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no PostgreSQL server binaries on this host ({type(exc).__name__})")
    cluster = IsolatedPostgres()
    try:
        cluster.start()
        cluster.verify_isolated()
        yield cluster
    finally:
        cluster.stop()


@pytest.fixture
def db(pg):
    import psycopg2
    e = pg.env()
    conn = psycopg2.connect(host=e["DB_HOST"], port=int(e["DB_PORT"]), dbname=e["DB_NAME"], user=e["DB_USER"],
                            password=e["DB_PASSWORD"])
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS watch_directives, watch_directive_hits, watchlist_items")
    cur.execute(SCHEMA)
    conn.commit()
    yield conn
    conn.close()


def _flags(conn):
    cur = conn.cursor()
    cur.execute("SELECT symbol, in_directive_watch, status FROM watchlist_items ORDER BY id")
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def test_plan_counts_before_and_after(db):
    plan = dp.plan_directive_watch_flag_reconcile(db.cursor())
    # flagged, not removed: AAA BBB CCC DDD EEE JJJ KKK (7); FFF is removed (row counted, symbol not)
    assert plan["before"] == {"rows": 8, "symbols": 7}
    # keep: AAA (owner op ticker), CCC (promoted hit of active op trend), JJJ (operator_audit ticker spec)
    assert plan["after"] == {"rows": 3, "symbols": 3}
    assert {r["symbol"] for r in plan["clear"]} == {"BBB", "DDD", "EEE", "FFF", "KKK"}
    assert plan["clear_rows"] == 5
    owners = {(r["created_by"], r["directive_status"]): r["rows"] for r in plan["by_directive"]}
    assert owners == {("think_tank", "active"): 3, ("advisory", "expired"): 1, ("operator", "archived"): 1}


def test_apply_backs_up_first_clears_only_the_flag_and_never_deletes(db, tmp_path):
    plan = dp.plan_directive_watch_flag_reconcile(db.cursor())
    before = _flags(db)
    res = dp.apply_directive_watch_flag_reconcile(db, plan, backup_path=tmp_path / "b.jsonl")
    assert res["cleared"] == 5 and res["attempted"] == 5
    lines = [json.loads(x) for x in (tmp_path / "b.jsonl").read_text().splitlines()]
    assert {x["symbol"] for x in lines} == {"BBB", "DDD", "EEE", "FFF", "KKK"}
    assert all(x["in_directive_watch_before"] is True and x["schema"] == dp.FLAG_BACKUP_SCHEMA for x in lines)
    after = _flags(db)
    assert set(after) == set(before), "no row deleted"
    assert {s for s, (f, _) in after.items() if f} == {"AAA", "CCC", "JJJ"}
    assert {s: st for s, (_, st) in after.items()} == {s: st for s, (_, st) in before.items()}, "status untouched"
    assert dp.plan_directive_watch_flag_reconcile(db.cursor())["clear_rows"] == 0


def test_apply_is_bounded_and_rechecks_the_keep_rule_at_write_time(db, tmp_path):
    plan = dp.plan_directive_watch_flag_reconcile(db.cursor())
    cur = db.cursor()
    # between plan and apply the operator makes BBB a ticker directive: it must keep its flag
    cur.execute("""INSERT INTO watch_directives (kind, label, spec, created_by, status)
                   VALUES ('ticker', 'BBB', '{"symbol":"BBB"}', 'operator', 'active')""")
    db.commit()
    res = dp.apply_directive_watch_flag_reconcile(db, plan, backup_path=tmp_path / "b.jsonl", max_clear=2)
    assert res["attempted"] == 2 and res["cleared"] == 1  # BBB skipped by the write-time re-check
    assert _flags(db)["BBB"][0] is True


def test_restore_puts_the_flag_back(db, tmp_path):
    plan = dp.plan_directive_watch_flag_reconcile(db.cursor())
    dp.apply_directive_watch_flag_reconcile(db, plan, backup_path=tmp_path / "b.jsonl")
    dry = dp.restore_directive_watch_flag(db, tmp_path / "b.jsonl", dry_run=True)
    assert dry == {"restore_ids": 5, "restored": 0, "dry_run": True}
    res = dp.restore_directive_watch_flag(db, tmp_path / "b.jsonl", dry_run=False)
    assert res["restored"] == 5
    assert sum(1 for f, _ in _flags(db).values() if f) == 8


def test_automated_directive_records_provenance_but_does_not_flag_or_activate(db):
    dp._upsert_watchlist_master(db, "NEW", "trade_ai", {"directive_id": 3}, 3, "trusted", "auto trend")
    dp._upsert_watchlist_master(db, "RMV", "trade_ai", {"directive_id": 3}, 3, "trusted", "auto trend")
    db.commit()
    f = _flags(db)
    assert f["NEW"] == (False, "researched")
    assert f["RMV"] == (False, "removed"), "an automated directive never resurrects what the operator removed"
    cur = db.cursor()
    cur.execute("SELECT directive_id, provenance_reason FROM watchlist_items WHERE symbol='NEW'")
    assert cur.fetchone() == (3, "auto trend")


def test_operator_directive_flags_inserts_active_and_unremoves(db):
    dp._upsert_watchlist_master(db, "OPN", "operator", {"directive_id": 1}, 1, "core", "op")
    dp._upsert_watchlist_master(db, "RMV", "operator", {"directive_id": 2}, 2, "core", "op trend")
    db.commit()
    f = _flags(db)
    assert f["OPN"] == (True, "active")
    assert f["RMV"] == (True, "active")


def test_existing_flag_is_kept_when_an_automated_directive_touches_the_row(db):
    dp._upsert_watchlist_master(db, "AAA", "trade_ai", {"directive_id": 3}, 3, "trusted", "auto")
    db.commit()
    assert _flags(db)["AAA"][0] is True


def test_archived_operator_directive_does_not_set_the_flag(db):
    dp._upsert_watchlist_master(db, "ARC", "operator", {"directive_id": 5}, 5, "core", "old")
    db.commit()
    assert _flags(db)["ARC"] == (False, "researched")


def test_hermes_top20_candidates_shrink_after_reconcile(db, tmp_path):
    """Consumers read the flag; after the reconcile hermes_top20._top() is rank<=N plus operator-matched names."""
    import hermes_top20_external_intel as h
    before = {r["symbol"] for r in h._top(db, 20)}
    assert before == {"AAA", "BBB", "CCC", "DDD", "EEE", "GGG", "JJJ", "KKK"}
    dp.apply_directive_watch_flag_reconcile(db, dp.plan_directive_watch_flag_reconcile(db.cursor()),
                                            backup_path=tmp_path / "b.jsonl")
    after = {r["symbol"] for r in h._top(db, 20)}
    assert after == {"AAA", "CCC", "GGG", "JJJ"}


# ── consumers: they read the flag, so the fix propagates without code changes ──────────────────────────────────
CONSUMERS = {
    "scripts/news_ingestion.py": "in_directive_watch = true AND status <> 'removed'",
    "scripts/hermes_top20_external_intel.py": "in_directive_watch=true AND status<>'removed'",
    "scripts/pro_analyst_fetch.py": "in_directive_watch=true AND status<>'removed'",
    "scripts/build_pro_analyst_read_model.py": "in_directive_watch=true AND status<>'removed'",
    "scripts/external_market_data_ingest.py": "in_directive_watch = TRUE",
    "scripts/watch_universe.py": "in_directive_watch = true AND status <> 'removed'",
}


@pytest.mark.parametrize("path,needle", sorted(CONSUMERS.items()))
def test_consumer_reads_the_flag_not_its_own_directive_join(path, needle):
    src = (ROOT / path).read_text()
    assert needle in src, f"{path}: consumer no longer reads the flag — re-check the expected effect"
    assert "created_by" not in src, f"{path}: a consumer must not re-derive operator membership"


# ── the servicer keeps it reconciled, only after the operator's apply ──────────────────────────────────────────
def test_service_reconciles_incrementally_only_after_the_operator_apply(tmp_path, monkeypatch):
    rdw = importlib.import_module("reconcile_directive_watch_flag")
    monkeypatch.setattr(rdw, "marker_path", lambda: tmp_path / "absent.json")
    monkeypatch.setattr(rdw, "backup_dir", lambda: tmp_path / "bk")
    called = []
    monkeypatch.setattr(dp, "plan_directive_watch_flag_reconcile", lambda cur: called.append("plan") or {"clear": []})
    conn = types.SimpleNamespace(cursor=lambda: None)
    assert rdw.incremental_reconcile(conn, dry=False)["skipped"] == "baseline_not_applied"
    assert called == []
    (tmp_path / "absent.json").write_text("{}")
    assert rdw.incremental_reconcile(conn, dry=True)["skipped"] == "dry_run"
    res = rdw.incremental_reconcile(conn, dry=False)
    assert called == ["plan"] and res["cleared"] == 0
    svc = (ROOT / "scripts" / "watch_directives_service.py").read_text()
    assert "incremental_reconcile(c, dry=dry)" in svc


def test_cli_apply_refuses_without_the_reviewed_count(monkeypatch, capsys):
    rdw = importlib.import_module("reconcile_directive_watch_flag")
    plan = {"before": {"rows": 2, "symbols": 2}, "after": {"rows": 1, "symbols": 1}, "clear_rows": 1,
            "clear_symbols": 1, "clear": [{"id": 1, "symbol": "X"}], "by_directive": [], "sample": [],
            "creators": ["operator"]}
    monkeypatch.setattr(dp, "plan_directive_watch_flag_reconcile", lambda cur: plan)
    applied = []
    monkeypatch.setattr(dp, "apply_directive_watch_flag_reconcile", lambda *a, **k: applied.append(1))
    conn = types.SimpleNamespace(cursor=lambda: None)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    assert rdw.main(["--apply"]) == 2
    assert rdw.main(["--apply", "--expect-clear", "7"]) == 2
    assert applied == []
    assert "REFUSED" in capsys.readouterr().err


def test_cli_dry_run_is_read_only_and_prints_counts(monkeypatch, capsys):
    rdw = importlib.import_module("reconcile_directive_watch_flag")
    plan = {"before": {"rows": 3686, "symbols": 2310}, "after": {"rows": 600, "symbols": 401}, "clear_rows": 3086,
            "clear_symbols": 1909, "clear": [], "by_directive": [{"created_by": "sector_universe",
                                                                  "directive_status": "active", "rows": 9}],
            "sample": [], "creators": ["operator", "operator_audit"]}
    monkeypatch.setattr(dp, "plan_directive_watch_flag_reconcile", lambda cur: plan)
    monkeypatch.setattr(dp, "apply_directive_watch_flag_reconcile",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry run applied")))
    ro = []
    conn = types.SimpleNamespace(cursor=lambda: None, set_session=lambda **k: ro.append(k), rollback=lambda: None)
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    assert rdw.main([]) == 0
    out = capsys.readouterr().out
    assert "before: 3686 rows, 2310 symbols" in out and "after : 600 rows, 401 symbols" in out
    assert "--apply --expect-clear 3086" in out
    assert ro == [{"readonly": True}]
