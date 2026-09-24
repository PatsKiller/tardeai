"""Event lineage across the hops an operator question takes (M5 Module 1, 1c/1d).

Measured 2026-09-23: only communication_events had causation_id /
parent_event_id; 0 of 35,393 outbound rows in 7 days carried a real cause, and
turn -> gap / research request -> completion -> outbound could only be joined
by ticker. The operator's reply to message 53969 stayed a root event because
the send that carried 53969 was stored as provider_message_id "53968,53969"
and the parent lookup matched exactly, in process memory only.

Also 1c: watch_directives / watchlist_items get subject_guid via an additive
migration; the writer stamps it only after a probe finds the columns.

No test here opens a database connection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import event_lineage as EL  # noqa: E402

INBOUND = "01a0d03b-cc5c-754b-946b-31b04719bd1a"  # the 2026-09-23 reply to 53969
SENT = "01a0d03b-15e6-7635-81c4-790110ca4bd6"  # the send that carried "53968,53969"


# ── the scope itself ────────────────────────────────────────────────────────
def test_scope_stamps_rows_and_unwinds():
    assert EL.current() is None
    with EL.lineage_scope(parent_event_id=INBOUND):
        row = EL.stamp_row({"x": 1})
        assert row["causation_id"] == INBOUND and row["parent_event_id"] == INBOUND
        own = EL.stamp_row({"causation_id": "other"})
        assert own == {"causation_id": "other"}, "a row naming its own lineage keeps it"
    assert EL.current() is None
    assert EL.stamp_row({"x": 1}) == {"x": 1}, "outside a scope nothing is invented"


def test_empty_scope_is_a_no_op():
    with EL.lineage_scope(parent_event_id=None) as lin:
        assert lin is None and EL.current() is None


def test_both_import_paths_share_one_scope():
    import importlib

    other = importlib.import_module("lib.event_lineage")
    with EL.lineage_scope(parent_event_id=INBOUND):
        assert other.current() is not None
        assert other.current().parent_event_id == INBOUND


def test_enter_row_scope_swaps_per_row():
    tok = EL.enter_row_scope({"causation_id": "a", "parent_event_id": "a"})
    assert EL.current().parent_event_id == "a"
    tok = EL.enter_row_scope({"note": "no lineage"}, tok)
    assert EL.current() is None
    tok = EL.enter_row_scope({"parent_event_id": "b"}, tok)
    assert EL.current().causation_id == "b"
    EL.enter_row_scope(None, tok)
    assert EL.current() is None


def test_provider_ids_split():
    assert EL.provider_ids("53968,53969") == ["53968", "53969"]
    assert EL.provider_ids(None) == []


def test_db_lookups_refuse_under_pytest_without_conn():
    assert EL.resolve_inbound_event("8797974247", 53970) is None  # hardcode-ok: fixture asserts Maria-chat routing
    assert EL.resolve_event_by_provider_message_id("53969") is None


# ── communication events inherit the scope ─────────────────────────────────
def _event(**kw):
    from scripts.lib.comms.event import CommunicationEvent

    base = dict(
        direction="OUTBOUND",
        event_type="health",
        message_class="operator_alert",
        producer="t",
        subject_key="s:t",
        retention_class="ops_7d",
        sanitized_body="b",
    )
    base.update(kw)
    return CommunicationEvent(**base).mint_identity()


def test_outbound_event_minted_in_scope_names_the_inbound_event():
    with EL.lineage_scope(parent_event_id=INBOUND):
        ev = _event()
    assert ev.parent_event_id == INBOUND and ev.causation_id == INBOUND


def test_outbound_event_outside_scope_stays_a_root_event():
    ev = _event()
    assert ev.parent_event_id is None and ev.causation_id == ev.event_id


def test_scope_never_overrides_a_producer_link_or_an_inbound_event():
    with EL.lineage_scope(parent_event_id=INBOUND):
        replied = _event(reply_to_event_id="evt-parent")
        inbound = _event(direction="INBOUND", event_type="telegram_command")
    assert replied.parent_event_id == "evt-parent"
    assert inbound.parent_event_id is None and inbound.causation_id == inbound.event_id


# ── the 53969 reply binds ────────────────────────────────────────────────────
def test_reply_to_a_multi_message_send_binds_from_memory(monkeypatch):
    from scripts.lib.comms import client, inbound

    monkeypatch.setattr(
        client, "memory_store_snapshot", lambda: {SENT: {"event_id": SENT, "provider_message_id": "53968,53969"}}
    )
    monkeypatch.setattr("scripts.lib.comms.delivery.find_delivery_by_provider_message_id", lambda pmid: None)
    got = inbound.resolve_event_by_provider_message_id("53969", chat_id="8797974247")  # hardcode-ok: fixture asserts Maria-chat routing
    assert got and got["event_id"] == SENT


def test_reply_to_another_process_send_binds_from_the_ledger(monkeypatch):
    from scripts.lib.comms import client, inbound

    monkeypatch.setattr(client, "memory_store_snapshot", lambda: {})
    monkeypatch.setattr("scripts.lib.comms.delivery.find_delivery_by_provider_message_id", lambda pmid: None)
    seen = {}

    def fake(pmid, *, chat_id=None, conn=None):
        seen["args"] = (pmid, chat_id)
        return {"event_id": SENT, "provider_message_id": "53968,53969"} if pmid == "53969" else None

    monkeypatch.setattr(EL, "resolve_event_by_provider_message_id", fake)
    got = inbound.resolve_event_by_provider_message_id("53969", chat_id="8797974247")  # hardcode-ok: fixture asserts Maria-chat routing
    assert got["event_id"] == SENT and seen["args"] == ("53969", "8797974247")  # hardcode-ok: fixture asserts Maria-chat routing


def test_list_aware_sql_matches_joined_ids():
    sql = EL._BY_PROVIDER_MSG_SQL
    assert "string_to_array(provider_message_id, ',')" in sql


# ── turns ────────────────────────────────────────────────────────────────────
class TurnCursor:
    def __init__(self, columns_present: bool):
        self.present = columns_present
        self.sql: list = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        sql, _ = self.sql[-1]
        if "information_schema.columns" in sql:
            return (1,) if self.present else None
        return None


class TurnConn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def commit(self):
        pass


@pytest.fixture(autouse=True)
def _fresh_probe_caches():
    from scripts.lib.writers import watch_directives_writer as W

    reset = getattr(W, "reset_identity_probe", lambda: None)
    EL.reset_column_cache()
    reset()
    yield
    EL.reset_column_cache()
    reset()


def _inserts(cur):
    return [(s, p) for s, p in cur.sql if "INSERT INTO operator_conversation_turns" in s]


def test_operator_turn_records_its_inbound_event():
    from scripts.lib.inbound_identity_tagger import persist_turn

    cur = TurnCursor(columns_present=True)
    persist_turn(
        {"resolved": []},
        conn=TurnConn(cur),
        text="research this",
        role="operator",
        chat_id="8797974247",  # hardcode-ok: fixture asserts Maria-chat routing
        message_id=53970,
        reply_to_message_id=53969,
        event_id=INBOUND,
        causation_id=SENT,
        parent_event_id=SENT,
    )
    ((sql, params),) = _inserts(cur)
    assert "event_id, causation_id, parent_event_id" in sql
    assert params[-3:] == (INBOUND, SENT, SENT)


def test_agent_turn_inherits_the_open_scope():
    from scripts.lib.inbound_identity_tagger import persist_turn

    cur = TurnCursor(columns_present=True)
    with EL.lineage_scope(parent_event_id=INBOUND):
        persist_turn(
            {"resolved": []}, conn=TurnConn(cur), text="answer", role="agent", chat_id="8797974247", message_id=53971  # hardcode-ok: fixture asserts Maria-chat routing
        )
    ((sql, params),) = _inserts(cur)
    assert "causation_id, parent_event_id" in sql and "event_id," not in sql.split("unresolved_mentions")[1]
    assert params[-2:] == (INBOUND, INBOUND)


def test_turn_write_survives_an_unmigrated_table():
    from scripts.lib.inbound_identity_tagger import persist_turn

    cur = TurnCursor(columns_present=False)
    persist_turn({"resolved": []}, conn=TurnConn(cur), text="q", role="operator", event_id=INBOUND)
    ((sql, params),) = _inserts(cur)
    assert "causation_id" not in sql and len(params) == 16


def test_turn_without_lineage_does_not_probe():
    from scripts.lib.inbound_identity_tagger import persist_turn

    cur = TurnCursor(columns_present=True)
    persist_turn({"resolved": []}, conn=TurnConn(cur), text="q", role="operator")
    assert not any("information_schema" in s for s, _ in cur.sql)


def test_desk_opens_the_inbound_scope_for_everything_the_turn_causes(monkeypatch):
    import scripts.lib.cio_converse_core as core
    import scripts.lib.cio_telegram_converse as conv

    captured = {}
    monkeypatch.setattr(
        EL,
        "resolve_inbound_event",
        lambda chat, mid, conn=None: {"event_id": INBOUND, "causation_id": SENT, "parent_event_id": SENT},
    )
    monkeypatch.setattr(conv, "allowlist_chat_ids", lambda: {"8797974247"})  # hardcode-ok: fixture asserts Maria-chat routing
    monkeypatch.setattr(
        conv, "_best_effort_capture_turn", lambda text, **kw: captured.setdefault("operator_lineage", kw.get("lineage"))
    )

    def fake_process(**kw):
        captured["scope"] = EL.current()
        return {"ok": True}

    monkeypatch.setattr(core, "process_operator_message", fake_process)
    conv.process_telegram_message(
        {
            "chat": {"id": 8797974247},  # hardcode-ok: fixture asserts Maria-chat routing
            "message_id": 53970,
            "text": "research this",
            "reply_to_message": {"message_id": 53969},
        },
        dedup_path=Path("/nonexistent/d"),
        msg_map_path=Path("/nonexistent/m"),
        rate_path=Path("/nonexistent/r"),
    )
    assert captured["operator_lineage"]["event_id"] == INBOUND
    assert captured["scope"].parent_event_id == INBOUND and captured["scope"].causation_id == INBOUND
    assert EL.current() is None


def test_desk_dry_run_resolves_nothing(monkeypatch):
    import scripts.lib.cio_telegram_converse as conv

    monkeypatch.setattr(EL, "resolve_inbound_event", lambda *a, **k: pytest.fail("must not look up"))
    assert conv._inbound_event_for("1", 2, dry_run=True) is None


# ── Hermes: request, claim, completion carry the originating event ─────────
@pytest.fixture
def hermes_tmp(tmp_path, monkeypatch):
    import lib.cio_hermes_research as hr

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "cio").mkdir(parents=True)
    monkeypatch.setattr(hr, "REQUEST_PATH", Path("data/cio/hermes_research_requests.jsonl"))
    monkeypatch.setattr(hr, "RESULT_PATH", Path("data/cio/hermes_research_results.jsonl"))
    monkeypatch.setattr(hr, "PROJECTION_PATH", Path("data/cio/hermes_research_projection.json"))
    for name in ("scripts.lib.research_identity", "lib.research_identity"):
        try:
            import importlib

            mod = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        monkeypatch.setattr(mod, "load_registry", lambda *a, **k: {})
        monkeypatch.setattr(mod, "resolve", lambda _d, s: {"symbol": s, "subject_guid": "g-" + str(s)})
    return hr


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def _plan():
    return {
        "plan_id": "plan_lineage_1",
        "situation_type": "S0_OPERATOR_CONVERSE",
        "symbols": ["S"],
        "thesis_version": "desk@v5",
    }


def test_research_rows_carry_the_asking_event_across_processes(hermes_tmp):
    hr = hermes_tmp
    from lib.hermes_worker import HermesWorker, StubResearchBackend

    with EL.lineage_scope(parent_event_id=INBOUND):
        enq = hr.enqueue_research_request(_plan(), priority="high")
    assert enq["created"]
    seen = {}

    def on_completed(request, result):
        seen["scope"] = EL.current()

    # The worker runs later, in another process: no scope is open here.
    assert EL.current() is None
    HermesWorker(store=hr, backend=StubResearchBackend(), worker_id="w", on_completed=on_completed).run_once(limit=1)

    req_rows = _rows(Path("data/cio/hermes_research_requests.jsonl"))
    res_rows = _rows(Path("data/cio/hermes_research_results.jsonl"))
    by_event = {r["event"]: r for r in req_rows}
    for ev in ("HERMES_RESEARCH_REQUESTED", "HERMES_RESEARCH_ENQUEUE", "HERMES_RESEARCH_CLAIMED"):
        assert by_event[ev].get("causation_id") == INBOUND, ev
        assert by_event[ev].get("parent_event_id") == INBOUND, ev
    done = [r for r in res_rows if r.get("event") == "HERMES_RESEARCH_COMPLETED"]
    assert done and done[0]["causation_id"] == INBOUND and done[0]["parent_event_id"] == INBOUND
    assert seen["scope"] is not None and seen["scope"].parent_event_id == INBOUND
    assert EL.current() is None


def test_dedupe_enqueue_row_names_the_later_ask(hermes_tmp):
    hr = hermes_tmp
    with EL.lineage_scope(parent_event_id=INBOUND):
        hr.enqueue_research_request(_plan(), priority="high")
    with EL.lineage_scope(parent_event_id="evt-second-ask"):
        second = hr.enqueue_research_request(_plan(), priority="high")
    assert not second["created"]
    enq = [r for r in _rows(Path("data/cio/hermes_research_requests.jsonl")) if r["event"] == "HERMES_RESEARCH_ENQUEUE"]
    assert enq[-1]["parent_event_id"] == "evt-second-ask"


def test_research_without_lineage_writes_no_lineage_keys(hermes_tmp):
    hr = hermes_tmp
    hr.enqueue_research_request(_plan(), priority="high")
    for r in _rows(Path("data/cio/hermes_research_requests.jsonl")):
        assert "causation_id" not in r and "parent_event_id" not in r


# ── desk loop rows ───────────────────────────────────────────────────────────
def test_desk_gap_and_pending_rows_carry_the_turn(tmp_path):
    import scripts.lib.cio_operator_desk_loop as D

    p = tmp_path / "gap.jsonl"
    with EL.lineage_scope(parent_event_id=INBOUND):
        D._append_jsonl(p, {"pending_id": "opr_x", "kind": "hermes_operator_forced"})
    D._append_jsonl(p, {"pending_id": "opr_y"})
    rows = _rows(p)
    assert rows[0]["parent_event_id"] == INBOUND and rows[0]["causation_id"] == INBOUND
    assert "parent_event_id" not in rows[1]


# ── the chain joins end to end ───────────────────────────────────────────────
def test_chain_report_joins_turn_gap_research_and_outbound(hermes_tmp, tmp_path):
    hr = hermes_tmp
    import scripts.lib.cio_operator_desk_loop as D
    from lib.hermes_worker import HermesWorker, StubResearchBackend
    from scripts.report_event_lineage_chain import build_chain

    gap = tmp_path / "gap.jsonl"
    with EL.lineage_scope(parent_event_id=INBOUND):
        enq = hr.enqueue_research_request(_plan(), priority="high")
        D._append_jsonl(
            gap,
            {
                "pending_id": "opr_1",
                "kind": "hermes_operator_forced",
                "research_id": enq["research_id"],
                "symbols": ["S"],
            },
        )
        agent_turn = EL.stamp_row({"id": 411, "role": "agent", "message_id": 53971})
    outbound = []

    def on_completed(request, result):
        outbound.append(_event(producer="hermes_followup").__dict__)

    HermesWorker(store=hr, backend=StubResearchBackend(), worker_id="w", on_completed=on_completed).run_once(limit=1)
    chain = build_chain(
        INBOUND,
        turns=[
            {"id": 410, "role": "operator", "event_id": INBOUND, "causation_id": SENT, "parent_event_id": SENT},
            agent_turn,
            {"id": 999, "role": "operator"},
        ],
        gap_rows=_rows(gap),
        research_request_rows=_rows(Path("data/cio/hermes_research_requests.jsonl")),
        research_result_rows=_rows(Path("data/cio/hermes_research_results.jsonl")),
        outbound_events=outbound,
    )
    assert chain["hop_counts"]["turns"] == 2
    assert chain["hop_counts"]["gap_requests"] == 1
    assert chain["hop_counts"]["research_requests"] >= 3
    assert chain["hop_counts"]["research_results"] == 1
    assert chain["hop_counts"]["outbound_events"] == 1
    assert chain["complete"] is True
    assert chain["research_ids"] == [enq["research_id"]]


def test_chain_report_requires_a_root():
    from scripts.report_event_lineage_chain import build_chain

    with pytest.raises(ValueError):
        build_chain("")


# ── 1c: watch identity columns ──────────────────────────────────────────────
class WatchCursor:
    def __init__(self, present: bool, exact=None):
        self.present = present
        self.exact = exact
        self.sql: list = []
        self._id = 500

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        sql, _ = self.sql[-1]
        if "information_schema.columns" in sql:
            return {"n": 2 if self.present else 0}
        if sql.lstrip().upper().startswith("INSERT") and "RETURNING id" in sql:
            self._id += 1
            return {"id": self._id}
        if sql.startswith("SELECT id FROM watch_directives WHERE kind = %s AND label = %s"):
            return {"id": self.exact} if self.exact else None
        return None

    def fetchall(self):
        return []


def _ident(monkeypatch):
    from scripts.lib.writers import watch_directives_writer as W

    monkeypatch.setattr(
        W,
        "resolve_directive_subject",
        lambda kind, spec: {
            "subject_guid": "84601d7d-ae35-5b36-9f1b-4c2f0d6a1e11",
            "issuer_guid": "0ac8534e-1b2c-5d3e-8f4a-5b6c7d8e9f00",
            "identity_source": "registry",
            "symbol": "S",
        },
    )
    return W


ROW = {"kind": "ticker", "label": "M5 lineage", "spec": {"symbol": "S"}}


def test_watch_insert_writes_the_guid_when_the_columns_exist(monkeypatch):
    W = _ident(monkeypatch)
    cur = WatchCursor(present=True)
    rec = W.write_watch_directives(cur, [ROW], source="t", on_duplicate="insert")
    ins = [(s, p) for s, p in cur.sql if s.startswith("INSERT INTO watch_directives")]
    assert rec.rows_written == 1 and "subject_guid, issuer_guid" in ins[0][0]
    assert ins[0][1][-2:] == ("84601d7d-ae35-5b36-9f1b-4c2f0d6a1e11", "0ac8534e-1b2c-5d3e-8f4a-5b6c7d8e9f00")


def test_watch_insert_before_the_migration_uses_the_old_columns(monkeypatch):
    W = _ident(monkeypatch)
    cur = WatchCursor(present=False)
    rec = W.write_watch_directives(cur, [ROW], source="t", on_duplicate="insert")
    ins = [(s, p) for s, p in cur.sql if s.startswith("INSERT INTO watch_directives")]
    assert rec.rows_written == 1 and "subject_guid" not in ins[0][0] and len(ins[0][1]) == 10


def test_watch_reuse_stamps_the_existing_row(monkeypatch):
    W = _ident(monkeypatch)
    cur = WatchCursor(present=True, exact=77)
    rec = W.write_watch_directives(
        cur, [{"kind": "sector", "label": "M5 lineage", "spec": {"symbol": "S"}}], source="t"
    )
    ups = [(s, p) for s, p in cur.sql if s.lstrip().startswith("UPDATE watch_directives")]
    assert rec.reused and rec.reused[0].get("identity_stamped") is True
    assert ups and ups[0][1][2] == 77 and "IS DISTINCT FROM" in ups[0][0]


def test_watch_identity_switch_off(monkeypatch):
    W = _ident(monkeypatch)
    monkeypatch.setenv("TRADEAI_WATCH_IDENTITY_COLUMNS", "off")
    cur = WatchCursor(present=True)
    W.write_watch_directives(cur, [ROW], source="t", on_duplicate="insert")
    assert not any("information_schema" in s for s, _ in cur.sql)


def test_watch_migration_is_additive():
    up = (ROOT / "migrations" / "2026_09_24_watch_subject_guid.sql").read_text()
    lin = (ROOT / "migrations" / "2026_09_24_event_lineage_columns.sql").read_text()
    for sql in (up, lin):
        assert "DROP" not in sql.upper().replace("-- ", "")
        assert "ADD COLUMN IF NOT EXISTS" in sql
    assert "watchlist_items" in up and "watch_directives" in up
    assert "causation_id" in lin and "parent_event_id" in lin


# ── 1c backfill ──────────────────────────────────────────────────────────────
class BackfillCursor:
    def __init__(self, rows, present=True):
        self.rows = rows
        self.present = present
        self.sql: list = []
        self.rowcount = -1

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        if sql.lstrip().startswith("UPDATE"):
            self.rowcount = len(params) // 3

    def fetchone(self):
        return (2 if self.present else 0,)

    def fetchall(self):
        return list(self.rows)


class BackfillConn:
    def __init__(self, cur):
        self.cur = cur
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _resolver(sym):
    return {
        "S": {"subject_guid": "g-s", "identity_source": "registry"},
        "NOC": {"subject_guid": "g-noc", "issuer_guid": "i-noc", "identity_source": "spine"},
    }.get(sym, {})


def test_backfill_dry_run_counts_and_writes_nothing():
    import scripts.backfill_watch_subject_guid as B

    cur = BackfillCursor([(1, "S", None), (2, "S", "g-s"), (3, "NOC", None), (4, "ZZZZ", None)])
    rep = B.run(BackfillConn(cur), tables=("watchlist_items",), resolver=_resolver)
    t = rep["tables"][0]
    assert (t["rows_in_scope"], t["resolved_rows"], t["unresolved_rows"]) == (4, 3, 1)
    assert t["already_stamped"] == 1 and t["would_update"] == 2
    assert t["unresolved_sample"] == ["ZZZZ"]
    assert not any(s.lstrip().startswith("UPDATE") for s, _ in cur.sql)


def test_backfill_apply_batches_and_is_idempotent():
    import scripts.backfill_watch_subject_guid as B

    cur = BackfillCursor([(1, "S", None), (3, "NOC", None), (5, "S", None)])
    conn = BackfillConn(cur)
    rep = B.run(conn, tables=("watch_directives",), apply=True, batch_size=2, resolver=_resolver)
    ups = [(s, p) for s, p in cur.sql if s.lstrip().startswith("UPDATE")]
    assert len(ups) == 2 and conn.commits == 2
    assert all("IS DISTINCT FROM" in s for s, _ in ups)
    assert rep["tables"][0]["written"] == 3


def test_backfill_apply_refuses_before_the_migration():
    import scripts.backfill_watch_subject_guid as B

    cur = BackfillCursor([(1, "S")], present=False)
    rep = B.run(BackfillConn(cur), tables=("watchlist_items",), apply=True, resolver=_resolver)
    assert rep["tables"][0]["error"].startswith("migration_not_applied")
    assert not any(s.lstrip().startswith("UPDATE") for s, _ in cur.sql)


def test_backfill_refuses_a_real_connection_under_pytest():
    import scripts.backfill_watch_subject_guid as B

    with pytest.raises(RuntimeError):
        B._connect()
