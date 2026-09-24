"""2026-09-24: the watch pipeline must not hold locks across network I/O.

Measured 09-24 during the M5 deploy: watch_directives_service.py sessions sat
"idle in transaction" ~1 min holding watchlist_items / watch_directives locks.
That blocked the 1c migration once (lock_timeout) and the GUID backfill 11
times. Root cause: promote_directive_lead UPDATEd watchlist_items and THEN ran
the Finviz network enrichment inside the same transaction, and the service kept
its own read transaction open across every promote.

psycopg2-free: every connection here is a fake.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import directive_promotion as dp  # noqa: E402
from lib import two_way_curation as tc  # noqa: E402


class TxnConn:
    """Fake connection: tracks statements executed since the last commit/rollback."""

    def __init__(self):
        self.events: list = []
        self.pending: list = []

    def cursor(self):
        conn = self

        class _Cur:
            rowcount = 1

            def execute(self, sql, params=None):
                conn.pending.append(" ".join(sql.split())[:60])
                conn.events.append(("sql", " ".join(sql.split())[:60], params))

            def fetchone(self):
                return None

            def fetchall(self):
                return []

        return _Cur()

    def commit(self):
        self.events.append(("commit",))
        self.pending = []

    def rollback(self):
        self.events.append(("rollback",))
        self.pending = []


def _stub_promote(monkeypatch, conn, *, tech=None):
    seen = {}
    monkeypatch.setattr(dp, "_conn", lambda: conn)
    monkeypatch.setattr(dp, "get_source_tier", lambda *a, **k: "trusted")
    monkeypatch.setattr(dp, "get_divergence_status", lambda *a, **k: "aligned")
    monkeypatch.setattr(dp, "classify_tradeable", lambda sym, t: [])
    monkeypatch.setattr(dp, "_record_hit", lambda *a, **k: conn.events.append(("record_hit",)))
    monkeypatch.setattr(dp, "_touch_directive_serviced", lambda *a, **k: None)
    monkeypatch.setattr(dp, "_mark_needs_review", lambda *a, **k: None)

    def enrich(symbol, conn=None):
        # The network fetch: nothing may be open on the promote's connection here.
        seen["pending_at_fetch"] = list(conn.pending) if conn is not None else []
        conn_events = conn.events if conn is not None else []
        conn_events.append(("network_fetch",))
        return tech if tech is not None else {"price": 10.0}

    monkeypatch.setattr(dp, "enrich_symbol_on_demand", enrich)
    return seen


def test_promote_fetches_enrichment_with_no_open_transaction(monkeypatch):
    conn = TxnConn()
    seen = _stub_promote(monkeypatch, conn)
    res = dp.promote_directive_lead("AXTI", 7, "directive:test", "operator", auto=True)
    assert res["status"] == "MONITORED_NO_QUALIFY"
    assert seen["pending_at_fetch"] == [], "network fetch ran inside an open transaction"
    kinds = [e[0] for e in conn.events]
    fetch = kinds.index("network_fetch")
    update = next(i for i, e in enumerate(conn.events) if e[0] == "sql" and "UPDATE watchlist_items" in e[1])
    assert fetch < update, "watchlist_items must be written only after the network fetch"
    assert kinds[-1] == "commit"


def test_promote_no_tech_path_writes_the_same_rows_after_the_fetch(monkeypatch):
    conn = TxnConn()
    seen = _stub_promote(monkeypatch, conn, tech={})
    res = dp.promote_directive_lead("AXTI", 7, "directive:test", "operator", auto=True)
    assert res["status"] == "REGISTERED_NO_TECH"
    assert seen["pending_at_fetch"] == []
    assert any(e[0] == "sql" and "UPDATE watchlist_items" in e[1] for e in conn.events)


def test_promote_on_a_caller_connection_keeps_the_caller_boundary(monkeypatch):
    conn = TxnConn()
    _stub_promote(monkeypatch, conn)
    conn.pending.append("caller's open work")
    dp.promote_directive_lead("AXTI", 7, "r", "operator", conn=conn, auto=True)
    assert ("rollback",) not in conn.events, "must not end a transaction it does not own"
    assert ("commit",) not in conn.events


def test_owned_promote_connection_gets_session_guards(monkeypatch):
    monkeypatch.setenv("PROMOTE_LOCK_TIMEOUT_MS", "1234")
    monkeypatch.setenv("PROMOTE_IDLE_TXN_TIMEOUT_MS", "5678")
    conn = TxnConn()
    _stub_promote(monkeypatch, conn)
    dp.promote_directive_lead("AXTI", 7, "r", "operator", auto=True)
    sets = [e[2] for e in conn.events if e[0] == "sql" and "set_config" in e[1]]
    assert ("1234ms",) in sets and ("5678ms",) in sets


def test_promote_guard_defaults_are_bounded(monkeypatch):
    monkeypatch.delenv("PROMOTE_LOCK_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("PROMOTE_IDLE_TXN_TIMEOUT_MS", raising=False)
    assert dp._env_ms("PROMOTE_IDLE_TXN_TIMEOUT_MS", dp.DEFAULT_PROMOTE_IDLE_TXN_TIMEOUT_MS) < 60000
    assert dp._env_ms("PROMOTE_LOCK_TIMEOUT_MS", dp.DEFAULT_PROMOTE_LOCK_TIMEOUT_MS) < 60000


# ── watch_directives_service (source-level: main() needs the live stores) ──────


def _service_src() -> str:
    return (ROOT / "scripts" / "watch_directives_service.py").read_text(encoding="utf-8")


def _fn_src(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{name} not found")


def test_service_main_loop_commits_before_each_promote():
    body = _fn_src(_service_src(), "evaluate")
    assert body.index("c.commit()") < body.index("evaluate_in_claim(")
    assert "if not dry:" in body[: body.index("c.commit()")]


def test_service_drain_keeps_its_claim_across_the_promote():
    body = _fn_src(_service_src(), "main")
    assert "_drain_curation_sources(c, cur, dry, report, evaluate_in_claim, _resolve)" in body
    drain = _fn_src(_service_src(), "_drain_curation_sources")
    assert "commit_each=None if dry else c.commit" in drain


def test_service_commits_the_pause_before_the_telegram_send():
    body = _fn_src(_service_src(), "pause_cold_trends")
    assert body.index("c.commit()") < body.index("_notify(")


def test_service_session_guards_from_env(monkeypatch):
    src = _service_src()
    ns: dict = {"os": __import__("os")}
    for name in ("_env_ms", "_session_guard_sql"):
        exec(
            compile(
                ast.Module(
                    [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name],
                    type_ignores=[],
                ),
                "svc",
                "exec",
            ),
            ns,
        )
    for const in ("DEFAULT_LOCK_TIMEOUT_MS", "DEFAULT_IDLE_TXN_TIMEOUT_MS"):
        ns[const] = int(src.split(f"{const} = ", 1)[1].split()[0])
    assert ns["DEFAULT_IDLE_TXN_TIMEOUT_MS"] < 60000, "the idle cap must stay under a minute"
    monkeypatch.setenv("WATCH_DIRECTIVES_LOCK_TIMEOUT_MS", "2500")
    monkeypatch.setenv("WATCH_DIRECTIVES_IDLE_TXN_TIMEOUT_MS", "30000")
    assert dict(ns["_session_guard_sql"]()) == {
        "lock_timeout": "2500ms",
        "idle_in_transaction_session_timeout": "30000ms",
    }


# ── curation drain: one claimed row per transaction when commit_each is given ───


class ClaimCursor:
    """Serves staging rows one at a time for `LIMIT 1 … NOT (id::text = ANY …)` claims."""

    def __init__(self, rows):
        self.rows = rows
        self.sql: list = []
        self._next = None

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.sql.append(flat)
        self._next = None
        if "drained=false" in flat and "LIMIT 1" in flat:
            seen = set(params[0])
            self._next = next((r for r in self.rows if str(r["id"]) not in seen), None)

    def fetchone(self):
        return self._next

    def fetchall(self):
        return []


def _row(i, sym):
    return {
        "id": i,
        "directive_id": 42,
        "symbol": sym,
        "thesis": "t",
        "source_detail": {"directive_kind": "ticker", "directive_label": f"L{i}", "spec": {"symbol": sym}},
    }


def test_drain_commit_each_claims_one_row_per_transaction(monkeypatch):
    monkeypatch.setattr(tc, "SOURCES", ["cio"])
    cur = ClaimCursor([_row(1, "AAA"), _row(2, "BBB")])
    log: list = []

    def evaluate(sym, did, reason, source, auto):
        log.append(("promote", sym))
        return {"status": "PROMOTED"}

    tc.drain_curation_sources(
        cur,
        False,
        {},
        evaluate,
        lambda d: [d["spec"]["symbol"]],
        drain_limit=5,
        commit_each=lambda: log.append(("commit",)),
    )
    assert log == [("promote", "AAA"), ("commit",), ("promote", "BBB"), ("commit",)]
    claims = [s for s in cur.sql if "FOR UPDATE SKIP LOCKED" in s]
    assert all("LIMIT 1" in s for s in claims)


def test_drain_commit_each_does_not_reclaim_a_retry_row_in_the_same_run(monkeypatch):
    monkeypatch.setattr(tc, "SOURCES", ["cio"])
    cur = ClaimCursor([_row(1, "AAA")])
    promotes: list = []

    def evaluate(sym, did, reason, source, auto):
        promotes.append(sym)
        return {"status": "ERROR", "error": "lock_timeout"}  # row stays undrained for retry

    tc.drain_curation_sources(
        cur,
        False,
        {"curation_errors": 0},
        evaluate,
        lambda d: [d["spec"]["symbol"]],
        drain_limit=5,
        commit_each=lambda: None,
    )
    assert promotes == ["AAA"], "a retry row must not be re-claimed within one run"


def test_drain_without_commit_each_keeps_the_batch_claim():
    src = (ROOT / "scripts" / "lib" / "two_way_curation.py").read_text(encoding="utf-8")
    assert 'f"LIMIT %s FOR UPDATE SKIP LOCKED"' in src
