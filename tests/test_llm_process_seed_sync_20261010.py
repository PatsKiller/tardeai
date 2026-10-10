"""llm_process_config seeding writes the registry's allowlist and dollar cap (2026-10-10).

Measured on the host (read-only SELECT, 2026-10-10 ~12:00 ET): the row for
``n8n_lane_failure_diagnosis`` read ``allowed_lanes {grok,chatgpt}`` and ``daily_cost_cap_usd NULL``
while ``config/llm_process_registry.json`` says ``[grok, chatgpt, fast, deepseek-flash]`` and ``0.10``.
``{grok,chatgpt}`` is the TABLE default from migrations/2026_07_08_llm_consumption_monitoring.sql:
``_seed_registry`` (called by every ``ensure_schema``) inserted new rows without either column.

Pinned here:
  * a NEW row carries ``_allowed_lanes_from_registry`` (de-duplicated) and the registry dollar cap;
  * an EXISTING row's NULL dollar cap is filled from the registry; a non-NULL one is never
    overwritten (``llm_cap_admin.set_caps`` writes DB first and the release's registry copy);
  * an EXISTING row's ``allowed_lanes`` is never rewritten by seeding (enforcement reads the
    registry; narrowing rows widened by ``sync_process_policies_from_registry`` is an operator call);
  * ``get_process_config`` still takes the allowlist from the registry, never the DB.

Hermetic: an in-memory fake cursor that evaluates the two upsert statements; no DB, no psycopg2.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2. Install a stand-in ONLY when the real driver is absent; nothing here
# connects -- every test replaces llm_consumption._conn with the fake below.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must not connect")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)

from lib import llm_consumption as lc  # noqa: E402

COVERS = ["scripts/lib/llm_consumption.py"]

TABLE_DEFAULT_LANES = ["grok", "chatgpt"]  # migrations/2026_07_08_llm_consumption_monitoring.sql:29
COLS = ("process_id", "process_name", "category", "mode", "allowed_lanes", "daily_soft_cap",
        "daily_cost_cap_usd", "notes")


class FakeTable:
    """Evaluates ``INSERT ... ON CONFLICT (process_id) DO NOTHING | DO UPDATE SET ... [WHERE ...]``."""

    def __init__(self, rows: dict | None = None):
        self.rows: dict[str, dict] = {k: dict(v) for k, v in (rows or {}).items()}
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.statements.append((sql, params))
        flat = " ".join(sql.split())
        m = re.search(r"INSERT INTO llm_process_config \(([^)]*)\)", flat)
        assert m, flat
        cols = [c.strip() for c in m.group(1).split(",") if c.strip() != "updated_at"]
        excluded = dict(zip(cols, params))
        for c in COLS:
            excluded.setdefault(c, TABLE_DEFAULT_LANES if c == "allowed_lanes" else
                                ("manual" if c == "mode" else None))
        pid = excluded["process_id"]
        existing = self.rows.get(pid)
        if existing is None:
            self.rows[pid] = {c: excluded[c] for c in COLS}
            return
        if "DO NOTHING" in flat:
            return
        upd = re.search(r"DO UPDATE SET (.*?)(?: WHERE (.*))?$", flat)
        assert upd, flat
        sets, where = upd.group(1), upd.group(2)

        def ref(tok: str):
            tok = tok.strip()
            if tok.startswith("EXCLUDED."):
                return excluded[tok.split(".", 1)[1]]
            if tok.startswith("llm_process_config."):
                return existing[tok.split(".", 1)[1]]
            raise AssertionError(f"unhandled ref {tok!r}")

        if where:
            for cond in re.split(r"\s+AND\s+", where):
                cm = re.fullmatch(r"(\S+) IS (NOT )?NULL", cond.strip())
                assert cm, cond
                isnull = ref(cm.group(1)) is None
                if isnull == bool(cm.group(2)):
                    return
        for assign in re.split(r",\s*(?![^()]*\))", sets):
            col, expr = (x.strip() for x in assign.split("=", 1))
            if col == "updated_at":
                continue
            cm = re.fullmatch(r"COALESCE\((.*),(.*)\)", expr)
            if cm:
                a, b = ref(cm.group(1)), ref(cm.group(2))
                existing[col] = a if a is not None else b
            else:
                existing[col] = ref(expr)


class FakeConn:
    def __init__(self, table: FakeTable):
        self.table = table
        self.commits = 0

    def cursor(self):
        return self.table

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _registry(*procs: dict) -> dict:
    return {"default_mode": "manual", "processes": list(procs)}


DIAG = {
    "id": "n8n_lane_failure_diagnosis", "name": "diag", "category": "N8nCoordination",
    "lane_policy": "either", "default_mode": "automated",
    "allowed_lanes": ["grok", "chatgpt", "fast", "deepseek-flash"],
    "deepseek_default_policy": "FAST", "deepseek_allowed_policies": ["FAST"],
    "daily_soft_cap": 40, "daily_cost_cap_usd": 0.1,
}
NO_MODE = {  # no default_mode -> the insert-only branch
    "id": "watchlist_agent_oauth_fallback", "name": "fb", "category": "Watch",
    "allowed_lanes": ["grok", "chatgpt", "grok"], "daily_soft_cap": 10, "daily_cost_cap_usd": 1.0,
}
DERIVED = {  # no explicit allowed_lanes -> derived from lane_policy + deepseek policies
    "id": "journal_ask", "name": "ja", "category": "Ask", "lane_policy": "either",
    "deepseek_allowed_policies": ["FAST"], "default_mode": "manual",
}


@pytest.fixture
def seed(monkeypatch):
    def run(registry: dict, rows: dict | None = None) -> FakeTable:
        table = FakeTable(rows)
        conn = FakeConn(table)
        monkeypatch.setattr(lc, "_REGISTRY", registry)
        monkeypatch.setattr(lc, "_conn", lambda: conn)
        lc._seed_registry()
        assert conn.commits == 1
        return table
    return run


def test_new_row_gets_registry_lanes_and_dollar_cap(seed):
    t = seed(_registry(DIAG))
    row = t.rows["n8n_lane_failure_diagnosis"]
    assert row["allowed_lanes"] == ["grok", "chatgpt", "fast", "deepseek-flash"]
    assert row["daily_cost_cap_usd"] == 0.1
    assert row["daily_soft_cap"] == 40
    assert row["mode"] == "automated"
    # The pre-fix bug: the INSERT omitted both columns, so the table default {grok,chatgpt} + NULL won.
    sql = " ".join(t.statements[0][0].split())
    assert "allowed_lanes" in sql and "daily_cost_cap_usd" in sql


def test_new_row_insert_only_branch_dedupes_and_writes_cap(seed):
    t = seed(_registry(NO_MODE))
    row = t.rows["watchlist_agent_oauth_fallback"]
    assert row["allowed_lanes"] == ["grok", "chatgpt"]
    assert row["daily_cost_cap_usd"] == 1.0


def test_new_row_derived_lanes_match_runtime_allowlist(seed):
    t = seed(_registry(DERIVED))
    assert t.rows["journal_ask"]["allowed_lanes"] == list(dict.fromkeys(lc._allowed_lanes_from_registry(DERIVED)))
    assert "fast" in t.rows["journal_ask"]["allowed_lanes"]
    assert t.rows["journal_ask"]["daily_cost_cap_usd"] is None  # registry declares none -> none invented


def test_existing_null_cap_is_filled_lanes_untouched(seed):
    """The host's diagnoser row: lanes stay (one-time sync packet), NULL cap is filled."""
    rows = {"n8n_lane_failure_diagnosis": dict(zip(COLS, (
        "n8n_lane_failure_diagnosis", "old", "N8nCoordination", "automated", ["grok", "chatgpt"], 40, None, "")))}
    t = seed(_registry(DIAG), rows)
    row = t.rows["n8n_lane_failure_diagnosis"]
    assert row["daily_cost_cap_usd"] == 0.1
    assert row["allowed_lanes"] == ["grok", "chatgpt"]


def test_existing_null_cap_filled_in_insert_only_branch(seed):
    rows = {"watchlist_agent_oauth_fallback": dict(zip(COLS, (
        "watchlist_agent_oauth_fallback", "fb", "Watch", "manual", ["grok"], 10, None, "")))}
    t = seed(_registry(NO_MODE), rows)
    assert t.rows["watchlist_agent_oauth_fallback"]["daily_cost_cap_usd"] == 1.0
    assert t.rows["watchlist_agent_oauth_fallback"]["allowed_lanes"] == ["grok"]


@pytest.mark.parametrize("proc", [DIAG, NO_MODE])
def test_existing_operator_cap_is_never_overwritten(seed, proc):
    """llm_cap_admin.set_caps writes DB first; a registry-wins seed would revert it on deploy."""
    rows = {proc["id"]: dict(zip(COLS, (proc["id"], "x", "c", "manual", ["grok"], 7, 1.25, "")))}
    t = seed(_registry(proc), rows)
    assert t.rows[proc["id"]]["daily_cost_cap_usd"] == 1.25


def test_existing_widened_lanes_are_not_narrowed(seed):
    """Rows widened by sync_process_policies_from_registry keep their lanes; seeding is not a remediation."""
    wide = list(lc.DEFAULT_ALLOWED_LANES)
    rows = {"n8n_lane_failure_diagnosis": dict(zip(COLS, (
        "n8n_lane_failure_diagnosis", "x", "c", "automated", wide, 40, 0.1, "")))}
    t = seed(_registry(DIAG), rows)
    assert t.rows["n8n_lane_failure_diagnosis"]["allowed_lanes"] == wide


def test_no_on_conflict_clause_assigns_allowed_lanes():
    src = Path(lc.__file__).read_text(encoding="utf-8")
    body = src[src.index("def _seed_registry"):src.index("def summarize_prompt")]
    for clause in re.findall(r"ON CONFLICT.*?\"\"\"", body, re.S):
        assert "allowed_lanes" not in clause
        assert "COALESCE(llm_process_config.daily_cost_cap_usd" in clause or "IS NULL" in clause


def test_runtime_allowlist_still_from_registry_not_db(monkeypatch):
    """get_process_config never takes lanes from the DB, so the seed's DB lanes are reporting only."""

    class Cur:
        def execute(self, *_a, **_k):
            pass

        def fetchone(self):
            return ("automated", ["grok", "chatgpt"], 40, None)

    class Conn:
        def cursor(self):
            return Cur()

        def rollback(self):
            pass

    monkeypatch.setattr(lc, "_REGISTRY", _registry(DIAG))
    monkeypatch.setattr(lc, "_conn", lambda: Conn())
    monkeypatch.setattr(lc, "_SCHEMA_OK", True)
    cfg = lc.get_process_config("n8n_lane_failure_diagnosis")
    assert cfg["allowed_lanes"] == ["grok", "chatgpt", "fast", "deepseek-flash"]
    assert cfg["daily_cost_cap_usd"] == 0.1  # NULL DB cap falls back to the registry


def test_real_registry_diagnoser_entry_is_what_the_seed_writes():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    p = next(x for x in reg["processes"] if x["id"] == "n8n_lane_failure_diagnosis")
    assert list(dict.fromkeys(lc._allowed_lanes_from_registry(p))) == ["grok", "chatgpt", "fast", "deepseek-flash"]
    assert p["daily_cost_cap_usd"] == 0.1
