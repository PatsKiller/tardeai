"""Phase 9 (One Source of Truth): watch_directives has ONE write module.

Before this change eighteen files under scripts/ each carried their own
INSERT/UPDATE against watch_directives (config/data_source_authority_baseline.json
records the ceiling: 18). The column list, the dedup rule, the status vocabulary
and the JSON coercion of `spec` could drift between them — the same class of
defect as the Finviz column shift. Now the SQL lives in exactly one place,
scripts/lib/writers/watch_directives_writer.py, and every producer calls it.

These tests are offline: a recording cursor / executor stands in for the DB and
an autouse fixture pins TRADEAI_IDENTITY_REGISTRY to a temp file so nothing here
reads the production identity registry. For each legacy writer there is a golden
test: the SAME input the legacy code fed now yields an equivalent statement from
the module (same target columns, same values after coercion, same conflict
behaviour, same identity GUID).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib.writers import watch_directives_writer as w  # noqa: E402
from lib import two_way_curation as tc  # noqa: E402
import check_data_source_authority as gate  # noqa: E402
from scripts.lib import identity_registry as ir  # noqa: E402
from scripts.lib.security_identity import resolve_identity_spine  # noqa: E402

AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
BASELINE = json.loads((ROOT / "config" / "data_source_authority_baseline.json").read_text())


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """No test here may read the production identity registry (rule d)."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_isolated_registry.json"))
    ir._CACHE.clear()


# ── fakes ────────────────────────────────────────────────────────────────────
class Row(dict):
    """A RETURNING row that answers both dict-style (module) and row[0]-style (legacy callers)."""

    def __getitem__(self, k):
        if isinstance(k, int):
            return list(self.values())[k]
        return super().__getitem__(k)


class RecordingCursor:
    """Records every statement; answers lookups from a small in-memory table."""

    def __init__(self, active_rows=None, exact=None, next_id=900, rowcount=1):
        self.sql: list = []            # (raw_sql, params)
        self.active_rows = list(active_rows or [])   # rows for the active-by-kind lookup
        self.exact = exact             # id returned for the exact (kind,label) lookup
        self._next_id = next_id
        self.rowcount = rowcount
        self.inserted: list = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        sql, params = self.sql[-1]
        if "RETURNING id" in sql and sql.lstrip().upper().startswith("INSERT"):
            self._next_id += 1
            self.inserted.append(params)
            return Row(id=self._next_id)
        if sql.startswith("SELECT id FROM watch_directives WHERE kind = %s AND label = %s"):
            return {"id": self.exact} if self.exact else None
        return None

    def fetchall(self):
        sql, _ = self.sql[-1]
        if "FROM watch_directives wd" in sql:
            return list(self.active_rows)
        if "RETURNING id, label" in sql:
            return [{"id": 1, "label": "old one"}]
        return []

    # ── helpers for assertions ──
    def inserts(self):
        return [(s, p) for s, p in self.sql if s.lstrip().upper().startswith("INSERT INTO WATCH_DIRECTIVES")]

    def updates(self):
        return [(s, p) for s, p in self.sql if s.lstrip().upper().startswith("UPDATE WATCH_DIRECTIVES")]


class FakeConn:
    def __init__(self, cur):
        self._cur = cur
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def make_executor(cur: RecordingCursor):
    """db_adapter._execute-shaped callable backed by the same recording cursor."""
    def ex(sql, params=None, fetch=None):
        cur.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return True
    return ex


def insert_row(sql: str, params) -> dict:
    """Parse the module's INSERT into {column: value} so goldens compare by column, not position."""
    cols = re.search(r"\(([^)]*)\)\s*VALUES", sql, re.S).group(1)
    cols = [c.strip() for c in cols.replace("\n", " ").split(",")]
    assert len(cols) == len(params), (cols, params)
    d = dict(zip(cols, params))
    d["spec"] = json.loads(d["spec"])
    return d


def update_sets(sql: str) -> list[str]:
    m = re.search(r"SET (.*) WHERE", sql, re.S)
    return [s.strip() for s in m.group(1).split(", ")]


LEGACY_DEFAULTS = {"status": "active", "priority": "normal", "ttl_days": None,
                   "trade_ai_enabled": True, "hermes_enabled": True}


def expect_row(**kw) -> dict:
    """A legacy INSERT's row: columns it omitted take the table's DEFAULTs, which the module writes explicitly."""
    d = {"rationale": None, **LEGACY_DEFAULTS}
    d.update(kw)
    return d


# ── the reduction itself (negative control) ──────────────────────────────────
def test_writer_count_was_18_and_is_now_1():
    assert BASELINE["history"]["2026-09-13_pre_phase9"]["writers"]["watch_directives"] == 18 > 1
    assert BASELINE["writers"]["watch_directives"] == 1
    now = gate.count_writers(AUTH, gate._files())["watch_directives"]
    assert now == 1, now


def test_only_the_write_module_carries_the_sql():
    pat = re.compile(r"\b(INSERT\s+INTO|UPDATE|COPY)\s+watch_directives\b", re.I)
    hits = [gate._rel(p) for p in gate._files() if pat.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert hits == ["scripts/lib/writers/watch_directives_writer.py"], hits


def test_registry_target_module_reexports_the_writer():
    assert tc.write_watch_directives is w.write_watch_directives
    assert tc.find_existing_directive is w.find_existing_directive


# ── rails: rejected rows come back, never silently dropped ───────────────────
def test_rejected_rows_are_returned_with_reasons_and_not_written():
    cur = RecordingCursor()
    rc = w.write_watch_directives(cur, [
        {"kind": "bogus", "label": "x", "spec": {}},
        {"kind": "ticker", "label": "", "spec": {"symbol": "NVDA"}},
        {"kind": "ticker", "label": "x", "spec": {"symbol": "BAD SYM"}},
        {"kind": "ticker", "label": "x", "spec": None},
        {"kind": "trend", "label": "x", "spec": "{not json"},
        {"kind": "trend", "label": "x", "spec": {}, "status": "deleted"},
        {"kind": "trend", "label": "x", "spec": {}, "ttl_days": -3},
    ], source="t")
    assert rc.rows_in == 7 and rc.rows_written == 0 and cur.inserts() == []
    assert [r["reason"] for r in rc.rows_rejected] == [
        "kind_invalid:bogus", "label_empty", "symbol_implausible:BAD SYM", "spec_missing",
        "spec_not_json", "status_invalid:deleted", "ttl_days_negative",
    ]


def test_update_rejects_bad_status_and_unknown_column():
    cur = RecordingCursor()
    rc = w.set_watch_directive_status(cur, 5, "deleted", source="t")
    assert rc.rows_rejected[0]["reason"] == "status_invalid:deleted" and cur.updates() == []
    with pytest.raises(ValueError):
        w.update_watch_directive(cur, 5, source="t", created_by="x")


def test_executor_returning_none_is_a_rejection_not_a_silent_drop():
    rc = w.write_watch_directives(lambda sql, params=None, fetch=None: None,
                                  [{"kind": "trend", "label": "t", "spec": {"keywords": ["a"]}}], source="t")
    assert rc.rows_written == 0 and rc.rows_rejected[0]["reason"].startswith("db_unavailable")


# ── identity (rules a–e) ─────────────────────────────────────────────────────
def test_table_has_no_identity_column_and_module_adds_none():
    ddl = (ROOT / "migrations" / "2026-06-08_watch_directives.sql").read_text()
    body = ddl.split("CREATE TABLE IF NOT EXISTS watch_directives (")[1].split(");")[0]
    assert "guid" not in body.lower()
    assert not any("guid" in c for c in w.INSERT_COLUMNS + w.UPDATE_COLUMNS)


def test_symbol_only_row_resolves_to_the_registry_guid_when_minted(tmp_path):
    doc = ir.empty_registry()
    ir.register(doc, {"symbol": "NVDA", "cik": "0001045810", "company": "NVIDIA Corp"})
    ir.save(doc)
    expected = ir.resolve_guid(ir.load(), ir.load()["by_symbol"]["NVDA"])
    cur = RecordingCursor()
    rc = w.write_watch_directives(cur, [{"kind": "ticker", "label": "watch nvda", "spec": {"symbol": "nvda"}}],
                                  source="t")
    assert rc.details[0]["subject_guid"] == expected
    assert rc.details[0]["identity_source"] == "registry"


def test_superseded_registry_guid_follows_the_chain():
    doc = ir.empty_registry()
    ir.register(doc, {"symbol": "ACME"})
    old = doc["by_symbol"]["ACME"]
    ir.register(doc, {"symbol": "ACME", "cik": "0000012345", "company": "Acme"})
    ir.save(doc)
    new = ir.resolve_guid(ir.load(), old)
    assert new != old
    assert w.resolve_directive_subject("ticker", {"symbol": "ACME"})["subject_guid"] == new


def test_unminted_symbol_only_row_gets_the_ticker_alias_never_null():
    res = w.resolve_directive_subject("ticker", {"symbol": "ZZQX"})
    assert res["subject_guid"] == ir.ticker_alias_guid("ZZQX") is not None
    assert res["identity_source"] == "spine"


def test_company_row_gets_issuer_derived_security_guid():
    spine = resolve_identity_spine({"symbol": "RGTI", "company": "Rigetti Computing"})
    res = w.resolve_directive_subject("ticker", {"symbol": "RGTI", "company": "Rigetti Computing"})
    assert res["subject_guid"] == spine["security_guid"] == ir.subject_guid_of(spine, "RGTI")


def test_sector_and_trend_directives_have_no_security_subject():
    assert w.resolve_directive_subject("sector", {"finviz_sector": "Energy"})["subject_guid"] is None
    assert w.resolve_directive_subject("trend", {"keywords": ["ai"]})["subject_guid"] is None


# ── the ONE dedup rule ───────────────────────────────────────────────────────
def test_ticker_dedups_by_symbol_not_by_shared_list_label():
    active = [{"id": 11, "label": "White House Quantum Computing", "spec": {"symbol": "GFS"}, "hits": 0}]
    cur = RecordingCursor(active_rows=active)
    same = w.find_existing_directive(cur, "ticker", "White House Quantum Computing", {"symbol": "gfs"})
    assert same == {"id": 11, "label": "White House Quantum Computing", "match": "symbol"}
    other = w.find_existing_directive(cur, "ticker", "White House Quantum Computing", {"symbol": "IBM"})
    assert other is None  # IBM keeps its own row: the label is a list name, the symbol is the identity
    assert not any(s.startswith("SELECT id FROM watch_directives WHERE kind = %s AND label") for s, _ in cur.sql)


def test_trend_family_fold_picks_most_hits_survivor():
    active = [
        {"id": 1, "label": "trend M&A surge", "spec": {}, "hits": 2},
        {"id": 2, "label": "trend event-driven M&A and consolidation", "spec": {}, "hits": 9},
    ]
    cur = RecordingCursor(active_rows=active)
    found = w.find_existing_directive(cur, "trend", "trend merger wave", {})
    assert found["match"] == "family" and found["id"] == 2 and found["hits"] == 9
    assert w.find_existing_directive(cur, "trend", "trend merger wave", {}, include_family=False) is None


def test_sector_dedups_by_sector_name_then_normalised_label():
    active = [{"id": 5, "label": "sector Energy", "spec": {"finviz_sector": "Energy"}, "hits": 0}]
    cur = RecordingCursor(active_rows=active)
    assert w.find_existing_directive(cur, "sector", "Energy names", {"gics_sector": "Energy"})["match"] == "sector"
    assert w.find_existing_directive(cur, "sector", "SECTOR   energy!", {})["match"] == "label_normalized"


def test_exact_label_match_is_first_for_non_ticker_kinds():
    cur = RecordingCursor(exact=42)
    assert w.find_existing_directive(cur, "trend", "trend AI", {}) == {"id": 42, "label": "trend AI", "match": "label"}


# ── GOLDEN: one test per migrated legacy writer ──────────────────────────────
# Legacy SQL is quoted in each docstring from the pre-phase-9 file.

def test_golden_two_way_curation_drain_mints_desk_directive():
    """two_way_curation.drain_curation_sources: INSERT (kind,label,spec,rationale,created_by,
    status,priority,trade_ai_enabled,hermes_enabled,ttl_days) VALUES (...,'active','normal',true,true,14)."""
    staged = [{"id": 1, "directive_id": None, "symbol": "NVDA", "thesis": "Advisory ADD",
               "source_detail": {"directive_kind": "ticker", "directive_label": "Advisory ADD — NVDA",
                                 "spec": {"symbol": "NVDA"}, "rationale": "adds on strength"}}]

    class DrainCursor(RecordingCursor):
        def fetchall(self):
            if "drained=false" in self.sql[-1][0]:
                return staged if not getattr(self, "_claimed", False) else []
            return super().fetchall()

    cur = DrainCursor()
    report = {}
    tc.drain_curation_sources(cur, False, report, evaluate=lambda *a: {"status": "PROMOTED"},
                              resolve_fn=lambda d: [d["spec"]["symbol"]])
    rows = [insert_row(s, p) for s, p in cur.inserts()]
    assert rows[0] == expect_row(kind="ticker", label="Advisory ADD — NVDA", spec={"symbol": "NVDA"},
                                 rationale="adds on strength", created_by="cio", ttl_days=tc.DESK_DIRECTIVE_TTL_DAYS)


def test_golden_two_way_curation_ensure_directive_executor_style():
    """two_way_curation.ensure_directive: SELECT id ... kind=%s AND label=%s; else INSERT ... ttl 14, created_by=source."""
    cur = RecordingCursor()
    ex = make_executor(cur)
    did = tc.ensure_directive("advisory", {"directive_kind": "sector", "directive_label": "Advisory — Energy",
                                           "spec": {"gics_sector": "Energy"}, "rationale": "rotate"}, executor=ex)
    assert did == 901
    assert insert_row(*cur.inserts()[0]) == expect_row(kind="sector", label="Advisory — Energy",
                                                        spec={"gics_sector": "Energy"}, rationale="rotate",
                                                        created_by="advisory", ttl_days=14)
    cur2 = RecordingCursor(exact=77)
    assert tc.ensure_directive("advisory", {"directive_kind": "sector", "directive_label": "x", "spec": {}},
                               executor=make_executor(cur2)) == 77 and cur2.inserts() == []


def test_golden_strategy_planner(monkeypatch):
    """strategy_planner.approve: INSERT ... VALUES (%s,%s,%s::jsonb,%s,'strategy_planner',%s,'normal','active',true,true) RETURNING id
    with ttl int(d.ttl_days or 30) and rationale default 'Redeploy target from strategy plan: …'."""
    import strategy_planner as sp
    import db_adapter
    cur = RecordingCursor()
    conn = FakeConn(cur)
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    monkeypatch.setattr(sp, "normalize_intent", lambda it: {"action": "liquidate", "note": "trim bonds"})
    out = sp.approve({"action": "liquidate"}, {"cash_freed": 1}, {"advice": "a", "provider": "grok"},
                     directives=[{"kind": "ticker", "label": "schd", "ttl_days": "45"},
                                 {"kind": "ticker", "label": "nvda"}])
    rows = [insert_row(s, p) for s, p in cur.inserts()]
    assert rows[0] == expect_row(kind="ticker", label="schd", spec={"symbol": "SCHD"},
                                 rationale="Redeploy target from strategy plan: trim bonds",
                                 created_by="strategy_planner", ttl_days=45)
    assert rows[1]["ttl_days"] == 30 and rows[1]["spec"] == {"symbol": "NVDA"}
    assert out["directive_ids"] == [901, 902]


def test_golden_claude_challenger_infuse_trends(monkeypatch):
    """claude_challenger_curator.infuse_trends: INSERT (kind,label,spec,rationale,created_by,ttl_days,priority,
    status,trade_ai_enabled,hermes_enabled,created_at,updated_at) VALUES ('trend',%s,%s::jsonb,%s,'claude_challenger',
    45,'normal',%s,true,true,NOW(),NOW()); dup → UPDATE spec,rationale,status='active',last_confirmed_at=NOW()."""
    import claude_challenger_curator as cc
    import db_adapter
    cur = RecordingCursor()
    monkeypatch.setattr(db_adapter, "_execute", make_executor(cur))
    t = {"trend": "Sovereign AI capex", "thesis": "govts fund compute", "keywords": ["sovereign ai"],
         "sectors": ["Technology"], "tickers": ["NVDA"], "conviction": "high"}
    assert cc.infuse_trends([t], apply=True) == 1
    row = insert_row(*cur.inserts()[0])
    assert row == expect_row(kind="trend", label="trend Sovereign AI capex",
                             spec={"keywords": ["sovereign ai"], "sectors": ["Technology"], "example_tickers": ["NVDA"],
                                   "conviction": "high", "evidence": "claude_challenger"},
                             rationale="govts fund compute", created_by="claude_challenger", ttl_days=45)
    # created_at/updated_at NOW() were the column defaults: dropping them is value-identical.
    cur2 = RecordingCursor(exact=31)
    monkeypatch.setattr(db_adapter, "_execute", make_executor(cur2))
    cc.infuse_trends([t], apply=True)
    sql, params = cur2.updates()[0]
    assert update_sets(sql) == ["spec=%s::jsonb", "rationale=%s", "status=%s", "last_confirmed_at=NOW()", "updated_at=NOW()"]
    assert params[1:] == ("govts fund compute", "active", 31) and cur2.inserts() == []


def test_golden_hermes_think_tank_upsert_themes():
    """hermes_think_tank.upsert_themes: INSERT ... VALUES (%s,%s,%s::jsonb,%s,'think_tank','active','normal',true,true,90)
    with label[:120]; existing → UPDATE spec=%s::jsonb, rationale=%s."""
    import hermes_think_tank as tt
    cur = RecordingCursor()
    theme = {"kind": "trend", "label": "trend " + "x" * 130, "rationale": "why",
             "spec": {"keywords": ["k1"], "seed_symbols": ["NVDA"]}}
    res = tt.upsert_themes(FakeConn(cur), [theme], apply=True, max_themes=5)
    row = insert_row(*cur.inserts()[0])
    assert row == expect_row(kind="trend", label=theme["label"][:120], spec=theme["spec"], rationale="why",
                             created_by="think_tank", ttl_days=90)
    assert res[0]["action"] == "created" and res[0]["id"] == 901
    active = [{"id": 7, "label": "trend K1 momentum", "spec": {"keywords": ["old"]}, "hits": 1}]
    cur2 = RecordingCursor(active_rows=active)
    cur2.fetchone_spec = {"keywords": ["old"]}
    orig = cur2.fetchone

    def fo():
        if cur2.sql[-1][0].startswith("SELECT spec FROM watch_directives"):
            return ({"keywords": ["old"]},)
        return orig()
    cur2.fetchone = fo
    res2 = tt.upsert_themes(FakeConn(cur2), [{"kind": "trend", "label": "trend k1 MOMENTUM", "rationale": "r2",
                                              "spec": {"keywords": ["k1"]}}], apply=True, max_themes=5)
    sql, params = cur2.updates()[0]
    assert res2[0]["action"] == "updated" and res2[0]["id"] == 7
    assert update_sets(sql) == ["spec=%s::jsonb", "rationale=%s", "updated_at=NOW()"]
    assert json.loads(params[0])["keywords"] == ["old", "k1"] and params[1:] == ("r2", 7)


def test_golden_sector_research_universe_rows():
    """sector_research_universe: INSERT ... VALUES (%s,%s,%s::jsonb,%s,'sector_universe','active','normal',true,true,180)
    (label[:120]); existing → UPDATE spec,rationale. _find_directive matched spec finviz_sector/gics_sector or finviz_industry."""
    cur = RecordingCursor()
    label = "sector " + "Y" * 130
    rc = w.write_watch_directives(cur, [{
        "kind": "sector", "label": label[:120], "spec": {"finviz_sector": "Energy"}, "rationale": "rs",
        "created_by": "sector_universe", "status": "active", "priority": "normal",
        "trade_ai_enabled": True, "hermes_enabled": True, "ttl_days": 180}], source="sector_universe", on_duplicate="insert")
    assert insert_row(*cur.inserts()[0]) == expect_row(kind="sector", label=label[:120], spec={"finviz_sector": "Energy"},
                                                        rationale="rs", created_by="sector_universe", ttl_days=180)
    import sector_research_universe as su
    active = [{"id": 3, "label": "sector Energy", "spec": {"gics_sector": "Energy"}, "hits": 0},
              {"id": 4, "label": "trend Oil & Gas E&P", "spec": {"finviz_industry": "Oil & Gas E&P"}, "hits": 0}]
    assert su._find_directive(RecordingCursor(active_rows=active), {"kind": "sector", "label": "x", "spec": {"finviz_sector": "Energy"}}) == 3
    assert su._find_directive(RecordingCursor(active_rows=active), {"kind": "trend", "label": "x", "spec": {"finviz_industry": "Oil & Gas E&P"}}) == 4
    assert rc.directive_id == 901


def test_golden_seed_quantum_chips():
    """seed_quantum_chips_watchlist._upsert_directive: INSERT (kind,label,spec,rationale,created_by,priority,
    trade_ai_enabled,hermes_enabled) VALUES ('ticker',%s,%s::jsonb,%s,'operator','high',true,true) RETURNING id;
    four symbols share ONE label — each must still get its own row."""
    import seed_quantum_chips_watchlist as sq

    class SeedCursor(RecordingCursor):
        def fetchone(self):
            if self.sql[-1][0].lstrip().startswith("SELECT id, label FROM watch_directives"):
                return None
            return super().fetchone()

    cur = SeedCursor()
    ids = [sq._upsert_directive(cur, s) for s in ("GFS", "IBM")]
    assert ids == [(901, True), (902, True)]
    rows = [insert_row(s, p) for s, p in cur.inserts()]
    assert rows[0] == expect_row(kind="ticker", label=sq.LIST_LABEL, spec={"symbol": "GFS", "company": "GlobalFoundries"},
                                 rationale=sq.RATIONALE, created_by="operator", priority="high")
    assert rows[1]["spec"]["symbol"] == "IBM"
    # relabel path: UPDATE label=%s, rationale=%s
    cur2 = SeedCursor()
    cur2.fetchone = lambda: (55, "GFS")
    assert sq._upsert_directive(cur2, "GFS") == (55, False)
    sql, params = cur2.updates()[0]
    assert update_sets(sql) == ["label=%s", "rationale=%s", "updated_at=NOW()"]
    assert params == (sq.LIST_LABEL, sq.RATIONALE, 55)


def test_golden_telegram_watch_command(monkeypatch):
    """telegram_command_handler._handle_watch: INSERT (kind,label,spec,rationale,created_by) VALUES (%s,%s,%s::jsonb,%s,'operator')."""
    import telegram_command_handler as th
    cur = RecordingCursor()
    conn = FakeConn(cur)
    monkeypatch.setattr(th, "_get_conn", lambda: conn)
    monkeypatch.setattr(th, "_notify_both", lambda msg: None)
    msg = th._handle_watch("ticker rklb because launch cadence")
    assert msg.startswith("✓ Watch directive #901: ticker — watch RKLB")
    assert insert_row(*cur.inserts()[0]) == expect_row(kind="ticker", label="watch RKLB", spec={"symbol": "RKLB"},
                                                        rationale="launch cadence", created_by="operator")
    assert conn.commits == 1


def test_golden_api_v2_create_update_and_service_touch(monkeypatch):
    """api_v2._watch_directive_create: INSERT (kind,label,spec,rationale,created_by,ttl_days,priority,trade_ai_enabled,
    hermes_enabled) from body; _watch_directive_update: UPDATE status='paused'|'active'|'archived'; service-at-creation
    touch: UPDATE last_serviced_at=now()."""
    import api_v2
    cur = RecordingCursor()
    monkeypatch.setattr(api_v2, "_db_query", make_executor(cur), raising=True)
    code, out = api_v2._watch_directive_create({"kind": "ticker", "label": "watch CIFR", "spec": {"symbol": "CIFR"},
                                                "rationale": "miner", "ttl_days": 21, "priority": "high",
                                                "hermes_enabled": False})
    assert code == 200 and out["directive_id"] == 901
    assert insert_row(*cur.inserts()[0]) == expect_row(kind="ticker", label="watch CIFR", spec={"symbol": "CIFR"},
                                                        rationale="miner", created_by="operator", ttl_days=21,
                                                        priority="high", hermes_enabled=False)
    # row-action transitions
    cur2 = RecordingCursor()
    ex2 = make_executor(cur2)

    def dbq(sql, params=None, fetch="all"):
        if sql.startswith("SELECT id, kind, label, status FROM watch_directives"):
            return {"id": 9, "kind": "trend", "label": "t", "status": "active"}
        return ex2(sql, params, fetch=fetch)
    monkeypatch.setattr(api_v2, "_db_query", dbq, raising=True)
    assert api_v2._watch_directive_update({"id": 9, "action": "pause"}) == {"ok": True, "id": 9, "action": "pause"}
    sql, params = cur2.updates()[0]
    assert update_sets(sql) == ["status=%s", "updated_at=NOW()"] and params == ("paused", 9)
    assert api_v2._watch_directive_update({"id": 9, "action": "archive"})["ok"]
    assert cur2.updates()[1][1] == ("archived", 9)
    assert api_v2._watch_directive_update({"id": 9, "action": "resume"}) == {"ok": False, "error": "invalid transition active → resume"}


def test_golden_api_v2_rotation_research_gaps_row():
    """api_v2 /rotation/research-gaps _mkdir: INSERT ... VALUES (%s,%s,%s::jsonb,%s,'rotation_advisor',30,'normal','active',true,true)."""
    cur = RecordingCursor()
    rc = w.write_watch_directives(cur, [{
        "kind": "trend", "label": "Healthcare", "spec": {"term": "Healthcare"},
        "rationale": "Rotation gap: portfolio underweight Healthcare", "created_by": "rotation_advisor",
        "ttl_days": 30, "priority": "normal", "status": "active", "trade_ai_enabled": True, "hermes_enabled": True,
    }], source="rotation_advisor")
    assert insert_row(*cur.inserts()[0]) == expect_row(kind="trend", label="Healthcare", spec={"term": "Healthcare"},
                                                        rationale="Rotation gap: portfolio underweight Healthcare",
                                                        created_by="rotation_advisor", ttl_days=30)
    assert rc.ids == [901]


def test_golden_directive_keyword_enhancer_backfill(monkeypatch):
    """directive_keyword_enhancer.backfill(apply=True): UPDATE spec=%s::jsonb, updated_at=now() WHERE id=%s."""
    import directive_keyword_enhancer as dke
    import db_adapter

    class Cur(RecordingCursor):
        def fetchall(self):
            if self.sql[-1][0].startswith("SELECT id, label, kind, spec FROM watch_directives"):
                return [(12, "trend AI datacenter", "trend", {"keywords": []})]
            return super().fetchall()
    cur = Cur()
    conn = FakeConn(cur)
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    monkeypatch.setattr(dke, "enhance", lambda label, kind, existing_keywords=None: {"keywords": ["ai datacenter"], "seed_symbols": ["NVDA"], "lane": "grok"})
    dke.backfill(apply=True)
    sql, params = cur.updates()[0]
    assert update_sets(sql) == ["spec=%s::jsonb", "updated_at=NOW()"]
    assert json.loads(params[0]) == {"keywords": ["ai datacenter"], "seed_symbols": ["NVDA"], "keywords_source": "llm:grok"}
    assert params[1] == 12 and conn.commits == 1


def test_golden_directive_promotion_touch_serviced():
    """directive_promotion._touch_directive_serviced: UPDATE last_serviced_at=NOW(), updated_at=NOW() WHERE id=%s."""
    import directive_promotion as dp
    cur = RecordingCursor()
    dp._touch_directive_serviced(FakeConn(cur), 44)
    sql, params = cur.updates()[0]
    assert update_sets(sql) == ["last_serviced_at=NOW()", "updated_at=NOW()"] and params == (44,)


def test_golden_research_critique_pipeline_shapes():
    """research_critique_pipeline: (a) UPDATE status='archived', spec=%s::jsonb; (b) UPDATE spec=%s::jsonb, priority=%s;
    (c) UPDATE spec=%s::jsonb — all with updated_at=NOW() WHERE id=%s."""
    import research_critique_pipeline as rcp
    wr = rcp._wd_writer()
    assert wr is w
    cur = RecordingCursor()
    wr.set_watch_directive_status(cur, 1, "archived", source=rcp.ARCHIVE_AGENT, spec={"archived_by": "librarian_auto"})
    wr.update_watch_directive(cur, 2, source="research_critique_pipeline", spec={"composite_verdict": "reject"}, priority="low")
    wr.update_watch_directive(cur, 3, source="research_critique_pipeline", spec={"librarian_stale_flag": True})
    ups = cur.updates()
    assert update_sets(ups[0][0]) == ["spec=%s::jsonb", "status=%s", "updated_at=NOW()"] and ups[0][1][1:] == ("archived", 1)
    assert update_sets(ups[1][0]) == ["spec=%s::jsonb", "priority=%s", "updated_at=NOW()"] and ups[1][1][1:] == ("low", 2)
    assert update_sets(ups[2][0]) == ["spec=%s::jsonb", "updated_at=NOW()"] and json.loads(ups[2][1][0]) == {"librarian_stale_flag": True}


def test_golden_watch_directive_hygiene_ttl_expiry(monkeypatch):
    """watch_directive_hygiene._expire_ttl: UPDATE SET status='expired' WHERE active AND past ttl RETURNING id, label."""
    import watch_directive_hygiene as hy
    import db_adapter
    cur = RecordingCursor()
    monkeypatch.setattr(db_adapter, "_execute", make_executor(cur))
    line = hy._expire_ttl()
    sql, _ = cur.updates()[0]
    assert "SET status='expired', updated_at=now()" in sql and "created_at < now() - (ttl_days || ' days')::interval" in sql
    assert "RETURNING id, label" in sql
    assert line == "TTL expiry: 1 directive(s) → expired: #1 old one"


def test_golden_watch_directive_dedup_apply_plan(monkeypatch):
    """watch_directive_dedup.apply_plan: UPDATE label=%s (relabel) and
    UPDATE status='archived', rationale=COALESCE(rationale,'')||' [archived by watch_directive_dedup]' WHERE id = ANY(%s)."""
    import watch_directive_dedup as dd
    import db_adapter
    cur = RecordingCursor()
    conn = FakeConn(cur)
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    dd.apply_plan({"relabel": [{"id": 1, "new_label": "trend Analyst revision & upgrade momentum", "hits": 3}],
                   "malformed_merge": [], "dead": [{"id": 8}, {"id": 9}], "merges": []})
    ups = cur.updates()
    assert update_sets(ups[0][0]) == ["label=%s", "updated_at=NOW()"] and ups[0][1] == ("trend Analyst revision & upgrade momentum", 1)
    assert update_sets(ups[1][0]) == ["status=%s", "rationale=COALESCE(rationale,'')||%s", "updated_at=NOW()"]
    assert ups[1][1] == ("archived", " [archived by watch_directive_dedup]", [8, 9]) and "id = ANY(%s)" in ups[1][0]
    assert conn.commits == 1


def test_golden_reclassify_knowledge_directives_row():
    """reclassify_knowledge_directives: UPDATE status='archived', updated_at=now() WHERE id=%s."""
    cur = RecordingCursor()
    w.set_watch_directive_status(cur, 17, "archived", source="reclassify_knowledge_directives")
    sql, params = cur.updates()[0]
    assert update_sets(sql) == ["status=%s", "updated_at=NOW()"] and params == ("archived", 17)


def test_golden_watch_directives_service_cold_detector(monkeypatch):
    """watch_directives_service.pause_cold_trends: UPDATE last_confirmed_at=now(), cold_since=NULL;
    UPDATE cold_since=now(); UPDATE status='paused' — and the servicer's UPDATE last_serviced_at=now()."""
    # the service reads ROOT/.env at import; a checkout without one must still be testable
    _orig_read_text = Path.read_text

    def _read_text(self, *a, **k):
        if self.name == ".env":
            return ""
        return _orig_read_text(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", _read_text)
    import watch_directives_service as svc

    class SvcCursor(RecordingCursor):
        def __init__(self, hits, cold_days, cold_since):
            super().__init__()
            self._hits, self._cold_days, self._cold_since = hits, cold_days, cold_since

        def fetchall(self):
            if self.sql[-1][0].startswith("SELECT * FROM watch_directives WHERE status='active' AND kind='trend'"):
                return [{"id": 3, "label": "trend x", "last_confirmed_at": None, "created_at": None, "cold_since": self._cold_since}]
            return super().fetchall()

        def fetchone(self):
            s = self.sql[-1][0]
            if "count(*) AS n FROM watch_directive_hits" in s:
                return {"n": self._hits}
            if "EXTRACT(EPOCH" in s:
                return {"days": self._cold_days}
            return super().fetchone()
    monkeypatch.setattr(svc, "_notify", lambda msg: None)
    c1 = SvcCursor(hits=2, cold_days=0, cold_since=None)
    svc.pause_cold_trends(None, c1, False, {"detail": []})
    assert update_sets(c1.updates()[0][0]) == ["last_confirmed_at=NOW()", "cold_since=%s", "updated_at=NOW()"]
    assert c1.updates()[0][1] == (None, 3)
    c2 = SvcCursor(hits=0, cold_days=0, cold_since=None)
    svc.pause_cold_trends(None, c2, False, {"detail": []})
    assert update_sets(c2.updates()[0][0]) == ["cold_since=NOW()", "updated_at=NOW()"] and c2.updates()[0][1] == (3,)
    c3 = SvcCursor(hits=0, cold_days=20, cold_since="2026-08-01")
    rep = {"detail": []}
    svc.pause_cold_trends(None, c3, False, rep)
    assert c3.updates()[0][1] == ("paused", 3) and rep["paused_cold"] == 1
    c4 = RecordingCursor()
    svc._wd.touch_watch_directive_serviced(c4, 3, source="watch_directives_service")
    assert update_sets(c4.updates()[0][0]) == ["last_serviced_at=NOW()", "updated_at=NOW()"]


def test_golden_drain_hermes_directive_staging_quiet_touch():
    """ops/drain_hermes_directive_staging --touch-quiet: UPDATE watch_directives d SET last_serviced_at=now(), updated_at=now()
    WHERE active AND (never serviced OR older than 24h) AND NOT EXISTS undrained hermes staging; rowcount is the count."""
    cur = RecordingCursor(rowcount=7)
    rc = w.touch_quiet_watch_directives_serviced(cur, source="drain_hermes_directive_staging", stale_hours=24)
    sql, params = cur.updates()[0]
    assert "NOT EXISTS" in sql and "hermes_directive_hits_staging h" in sql and "d.last_serviced_at IS NULL" in sql
    assert params == ("24",) and rc.rows_written == 7


def test_golden_watch_directive_gate_alias_and_family(monkeypatch):
    """watch_directive_gate.attach_alias: UPDATE spec=%s::jsonb, last_confirmed_at=NOW(), updated_at=NOW() WHERE id=%s;
    family_gate: same-family active survivor (most hits) → allow=False."""
    from lib import watch_directive_gate as g
    import db_adapter
    active = [{"id": 1, "label": "trend M&A surge", "spec": {}, "hits": 2},
              {"id": 2, "label": "trend event-driven M&A", "spec": {}, "hits": 9}]
    cur = RecordingCursor(active_rows=active)

    def ex(sql, params=None, fetch=None):
        cur.execute(sql, params)
        if sql.startswith("SELECT spec FROM watch_directives"):
            return {"spec": {"keywords": ["m&a"]}}
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return True
    monkeypatch.setattr(db_adapter, "_execute", ex)
    monkeypatch.setattr(g, "_cfg", lambda: {"gate_enabled": True, "active_trend_cap": 0})
    out = g.family_gate("trend merger wave", "trend")
    assert out["allow"] is False and out["survivor_id"] == 2 and "family" in out["reason"]
    assert g.attach_alias(2, "trend merger wave", rationale="r", keywords=["mergers"], created_by="claude_challenger") is True
    sql, params = cur.updates()[0]
    assert update_sets(sql) == ["spec=%s::jsonb", "last_confirmed_at=NOW()", "updated_at=NOW()"]
    spec = json.loads(params[0])
    assert spec["aliases"] == ["trend merger wave"] and spec["keywords"] == ["m&a", "mergers"] and params[1] == 2


def test_hermes_discovery_promotion_still_has_no_direct_write():
    """The 18th 'writer' was a docstring the gate regex matched; the module still routes via api_v2."""
    src = (ROOT / "scripts" / "lib" / "hermes_discovery" / "promotion.py").read_text()
    assert not re.search(r"\b(INSERT\s+INTO|UPDATE|COPY)\s+watch_directives\b", src, re.I)
    assert "_watch_directive_create" in src
