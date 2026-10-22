"""Shared Momentum / Alerts redesign — Gate 1 data bug fixes (operator 2026-10-22). Hermetic.

1. AT rows carry the catalyst the AT alert prints (Trade-AI scan -> earlier scan today -> Hermes), origin labelled.
2. momentum_alert_pass.trade_ai_today maps columns by NAME for tuple cursors (was decision/not_tradeable only).
3. read_candidate_snapshot reads the journal's whole latest session (backwards to the session boundary), not a
   fixed 4 MB tail; tail_truncated only when the byte bound is hit first.
4. security_guid from the identity registry (by symbol) and a read-side SecurityEvent@v1 for a published
   catalyst; never invented, mismatches are reported, not picked.
5. The gap pillar for AT reads today's Trade-AI row (the AT Candidate has no gap field).

Fixtures only: tmp_path state roots, fake cursors, injected lookups. No live store, DB, network or send.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_alert_pass as pass5  # noqa: E402
from active_trader import momentum_alerts as ma  # noqa: E402
from lib import scanner_candidate_projection as proj  # noqa: E402
from lib.hermes_scalp_catalyst_record import select_scalp_catalyst  # noqa: E402

DAY = "2026-10-22"
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)  # 11:00 ET
SCANNED = "2026-10-22T09:05:00-04:00"


def _ta_entry(**over):
    entry = {
        "decision": "WAIT",
        "not_tradeable": False,
        "scanned_at": SCANNED,
        "run_date": DAY,
        "scan_run_date": DAY,
        "price": 3.2,
        "float_m": 8.0,
        "rvol": 6.0,
        "gap_pct": 24.0,
        "change_pct": 30.0,
        "catalyst": "XLAB announces FDA clearance",
        "catalyst_verified": None,
        "catalyst_source": "globenewswire",
        "catalyst_url": "https://example.com/xlab",
        "catalyst_at": "2026-10-22T07:30:00-04:00",
    }
    entry.update(over)
    return entry


def _at_row(symbol="XLAB", *, trade_ai=None, ts=None, session_date=DAY, verdict="ALERT", **cand):
    candidate = {"symbol": symbol, "lane": "A", "ign": 1.0, "session_date": session_date, "trade_ai": trade_ai,
                 "float_mm": 8.0, "rvol": 6.0, "last": 3.2, **cand}
    return {"contract": proj.AT_CONTRACT, "kind": "ARMED", "verdict": verdict, "sent": True,
            "ts_epoch": ts if ts is not None else NOW.timestamp() - 600, "candidate": candidate}


def _at_evidence(projection, symbol="XLAB"):
    rows = [c for c in projection["candidates"] if c["symbol"] == symbol]
    assert rows, projection["candidates"]
    return [o["setup_evidence"] for c in rows for o in c["active_trader"]["observations"]]


# ── 1. AT catalyst: the same one the alert prints, origin labelled ────────────────────────────────────────


@pytest.mark.parametrize(
    "trade_ai, origin, text",
    [
        ({"setup_evidence": {"catalyst": {"text": "FDA nod", "source": "news"}}}, "TRADE_AI_SCAN", "FDA nod"),
        ({"catalyst": "Raw headline", "catalyst_source": "yahoo"}, "TRADE_AI_SCAN", "Raw headline"),
        ({"day_catalyst": {"text": "Earlier headline", "source": "yahoo"}}, "TRADE_AI_SCAN_EARLIER_TODAY",
         "Earlier headline"),
    ],
)
def test_at_catalyst_follows_trade_ai_scan_like_the_alert(trade_ai, origin, text):
    called = []
    fields = proj.active_trader_catalyst(
        {"symbol": "XLAB", "session_date": DAY, "trade_ai": trade_ai},
        catalyst_lookup=lambda s, d: called.append((s, d)) or {"status": "FOUND", "summary": "Hermes text"},
    )
    assert fields["catalyst"] == text and fields["catalyst_origin"] == origin
    assert called == []  # Hermes only when the scan has nothing — the alert's order
    alert_text, alert_source = ma._trade_ai_catalyst(trade_ai)
    assert (fields["catalyst"], fields["catalyst_source"]) == (alert_text, alert_source)


def test_at_catalyst_falls_back_to_hermes_and_labels_it():
    fields = proj.active_trader_catalyst(
        {"symbol": "XLAB", "session_date": DAY, "trade_ai": None},
        catalyst_lookup=lambda s, d: {"status": "FOUND", "summary": "XLAB wins contract", "catalyst_type": "contract"},
    )
    assert fields == {
        "catalyst": "XLAB wins contract",
        "catalyst_source": "Hermes contract",
        "catalyst_type": "contract",
        "catalyst_origin": "HERMES_SCALP_RESEARCH",
    }
    for status in ("NONE_FOUND", "NOT_RESEARCHED", "STORE_MISSING"):
        assert proj.active_trader_catalyst(
            {"symbol": "XLAB", "session_date": DAY}, catalyst_lookup=lambda s, d, st=status: {"status": st}
        ) == {}
    assert proj.active_trader_catalyst(
        {"symbol": "XLAB", "session_date": DAY}, catalyst_lookup=lambda s, d: 1 / 0
    ) == {}


def test_projection_at_rows_carry_catalyst_text_and_origin():
    out = proj.build_candidate_projection(
        {"tickers": []}, [_at_row(trade_ai=_ta_entry())], now=NOW, catalyst_lookup=None
    )
    (evidence,) = _at_evidence(out)
    assert evidence["catalyst"]["text"] == "XLAB announces FDA clearance"
    assert evidence["catalyst"]["origin"] == "TRADE_AI_SCAN"
    assert evidence["catalyst"]["source"] == "globenewswire"
    assert evidence["execution_authority"] == "NONE"
    assert out["memory_behavior_influence"] == 0
    assert all(c["execution_authority"] == "NONE" for c in out["candidates"])


def test_hermes_record_selection_is_shared_with_the_data_broker(tmp_path):
    from lib.data_broker import scalp_list

    lines = [
        json.dumps({"symbol": "XLAB", "research_timestamp": "2026-10-22T06:25:00-04:00",
                    "catalyst_type": "no_clear_catalyst"}),
        json.dumps({"symbol": "XLAB", "research_timestamp": "2026-10-22T08:25:00-04:00",
                    "catalyst_type": "contract", "catalyst_summary": "XLAB wins contract"}),
        "not json",
    ]
    store = tmp_path / "data/hermes/momentum_catalysts"
    store.mkdir(parents=True)
    (store / f"{DAY}_catalysts.jsonl").write_text("\n".join(lines) + "\n")
    broker = scalp_list.get_scalp_catalyst("XLAB", DAY, root=tmp_path)
    picked = select_scalp_catalyst("xlab", lines)
    assert picked["status"] == broker["status"] == "FOUND"
    assert {k: broker[k] for k in picked} == picked
    lookup = proj._hermes_catalyst_lookup(tmp_path)
    assert lookup("XLAB", DAY)["summary"] == "XLAB wins contract"
    assert lookup("NOPE", DAY)["status"] == "NOT_RESEARCHED"
    assert lookup("XLAB", "2026-10-21")["status"] == "STORE_MISSING"


# ── 2. trade_ai_today maps tuple rows by column name ─────────────────────────────────────────────────────


class _Col(tuple):
    @property
    def name(self):
        return self[0]


class _Cursor:
    def __init__(self, rows, description):
        self.rows, self.description = rows, description

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sql = sql

    def fetchall(self):
        return self.rows if "DISTINCT ON (symbol) symbol, decision" in self.sql else []


class _Conn:
    def __init__(self, rows, description=None):
        self.rows, self.description = rows, description

    def cursor(self):
        return _Cursor(self.rows, self.description)

    def rollback(self):
        pass


def _tuple_row():
    e = _ta_entry()
    return tuple(["XLAB"] + [e[k] for k in pass5.TRADE_AI_RICH_COLUMNS[1:]])


@pytest.mark.parametrize("description", [None, [_Col((n, None)) for n in pass5.TRADE_AI_RICH_COLUMNS]])
def test_trade_ai_today_tuple_cursor_keeps_every_fact(description):
    out = pass5.trade_ai_today(_Conn([_tuple_row()], description), ["XLAB"], DAY)["XLAB"]
    for key in ("price", "float_m", "rvol", "gap_pct", "change_pct", "catalyst", "catalyst_source", "catalyst_at"):
        assert out[key] == _ta_entry()[key], key
    assert out["decision"] == "WAIT" and out["setup_evidence"]["catalyst"]["text"] == "XLAB announces FDA clearance"
    assert {p["id"]: p["value"] for p in out["setup_evidence"]["pillars"]}["float"] == 8.0


def test_trade_ai_today_dict_cursor_and_reordered_description_agree():
    row = dict(zip(pass5.TRADE_AI_RICH_COLUMNS, _tuple_row()))
    by_dict = pass5.trade_ai_today(_Conn([row]), ["XLAB"], DAY)["XLAB"]
    names = list(reversed(pass5.TRADE_AI_RICH_COLUMNS))
    by_name = pass5.trade_ai_today(
        _Conn([tuple(row[n] for n in names)], [(n,) for n in names]), ["XLAB"], DAY
    )["XLAB"]
    assert by_dict == by_name


def test_trade_ai_today_old_schema_tuple_rows_still_map():
    out = pass5.trade_ai_today(_Conn([("XLAB", "GO", False, SCANNED)]), ["XLAB"], DAY)["XLAB"]
    assert out["decision"] == "GO" and out["scanned_at"] == SCANNED and out["price"] is None


# ── 3. the whole latest session, not a byte tail ─────────────────────────────────────────────────────────


def _write_journal(path, days):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for day, count in days:
            for i in range(count):
                row = _at_row(f"S{i % 7}", session_date=day, ts=NOW.timestamp() - 5000 + i, pad="x" * 200)
                fh.write(json.dumps(row) + "\n")


def test_journal_reader_returns_every_row_of_the_latest_session(tmp_path):
    jp = tmp_path / "state/data/active_trader/momentum_alerts.jsonl"
    _write_journal(jp, [("2026-10-20", 300), ("2026-10-21", 300), (DAY, 250)])
    rows, bad, details = proj.read_journal_session(jp, max_bytes=10_000_000, block_bytes=4096)
    assert len(rows) == 250 and bad == 0
    assert {r["candidate"]["session_date"] for r in rows} == {DAY}
    assert details["tail_truncated"] is False and details["session_boundary_found"] is True
    assert details["session_window"] == DAY and details["bytes_read"] < jp.stat().st_size


def test_journal_reader_reports_truncation_when_the_bound_hits_first(tmp_path):
    jp = tmp_path / "state/data/active_trader/momentum_alerts.jsonl"
    _write_journal(jp, [("2026-10-21", 50), (DAY, 400)])
    rows, _, details = proj.read_journal_session(jp, max_bytes=20_000, block_bytes=4096)
    assert details["tail_truncated"] is True and details["session_boundary_found"] is False
    assert 0 < len(rows) < 400


def test_snapshot_status_is_available_for_a_full_session(tmp_path):
    state = tmp_path / "state"
    jp = state / "data/active_trader/momentum_alerts.jsonl"
    _write_journal(jp, [("2026-10-21", 100), (DAY, 120)])
    cp = state / "data/runtime/trade_ai_cache.json"
    cp.parent.mkdir(parents=True)
    cp.write_text(json.dumps({"tickers": []}))
    before = (jp.read_bytes(), cp.read_bytes())
    out = proj.read_candidate_snapshot(cp, jp, now=NOW, max_journal_bytes=10_000_000)
    meta = out["source_metadata"]["ACTIVE_TRADER"]
    assert meta["status"] == "AVAILABLE" and meta["tail_truncated"] is False
    assert meta["earlier_session_rows_excluded"] >= 0
    assert sum(len(c["active_trader"]["observations"]) for c in out["candidates"]) == 120
    assert (jp.read_bytes(), cp.read_bytes()) == before  # read only


# ── 4. identity + event, read side ───────────────────────────────────────────────────────────────────────

SEC, ISSUER, OLD = "sec-xlab-0001", "iss-xlab-0001", "alias-xlab-0000"


def _registry(issuer=ISSUER):
    return {
        "by_symbol": {"XLAB": OLD, "NOID": "alias-noid"},
        "entities": {
            OLD: {"superseded_by": SEC, "active": False},
            SEC: {"security_guid": SEC, "issuer_guid": issuer, "active": True, "subject_guid": SEC},
            "alias-noid": {"security_guid": None, "issuer_guid": None, "identity_status": "UNRESOLVED_WITH_REASON"},
        },
    }


def test_registry_entity_matches_identity_registry_lookup_symbol():
    from scripts.lib.identity_registry import lookup_symbol

    reg = _registry()
    for sym in ("XLAB", "xlab", "NOID", "MISSING"):
        assert proj.registry_entity(reg, sym) == lookup_symbol(reg, sym)


def _ta_cache(**over):
    row = {"symbol": "XLAB", "decision": "GO", "run_id": f"{DAY}::0900", "observed_at": "2026-10-22T13:05:00+00:00",
           "catalyst": "XLAB announces FDA clearance", "catalyst_published_at": "2026-10-22T11:30:00+00:00", **over}
    return {"tickers": [row], "source_observations": [row]}


def test_at_and_trade_ai_rows_merge_on_the_registry_guid_and_event():
    out = proj.build_candidate_projection(
        _ta_cache(), [_at_row(trade_ai=_ta_entry(catalyst_at="2026-10-22T07:30:00-04:00"))],
        now=NOW, identity_registry=_registry(),
    )
    (cand,) = out["candidates"]
    assert cand["security_guid"] == SEC and cand["sources"] == ["ACTIVE_TRADER", "TRADE_AI"]
    assert cand["reconciliation_status"] == "COMPARABLE_EVENT" and cand["reconciliation_reasons"] == []
    assert cand["event_basis"] == "READ_SIDE_CATALYST_BINDING"
    assert cand["event"]["schema"] == "SecurityEvent@v1" and cand["event"]["issuer_guid"] == ISSUER
    assert cand["event_id"] == cand["event"]["event_guid"] and cand["event_at"]
    at_obs = cand["active_trader"]["observations"][0]
    assert at_obs["security_guid_basis"] == "IDENTITY_REGISTRY"
    from scripts.lib.event_identity import event_guid

    assert cand["event_id"] == event_guid(issuer_guid=ISSUER, event_type="other", period="20261022")


def test_without_registry_rows_stay_unresolved_with_reasons():
    out = proj.build_candidate_projection({"tickers": []}, [_at_row(trade_ai=_ta_entry())], now=NOW)
    (cand,) = out["candidates"]
    assert cand["security_guid"] is None and cand["reconciliation_status"] == "IDENTITY_OR_EVENT_UNRESOLVED"
    assert cand["reconciliation_reasons"] == ["SECURITY_GUID_UNRESOLVED", "EVENT_UNRESOLVED"]


def test_alias_only_entity_is_never_promoted_to_a_security_guid():
    out = proj.build_candidate_projection({"tickers": []}, [_at_row("NOID")], now=NOW, identity_registry=_registry())
    (cand,) = out["candidates"]
    assert cand["security_guid"] is None and "SECURITY_GUID_UNRESOLVED" in cand["reconciliation_reasons"]


def test_different_catalyst_events_are_a_mismatch_not_a_pick():
    out = proj.build_candidate_projection(
        _ta_cache(catalyst_published_at="2026-10-20T11:30:00+00:00"),
        [_at_row(trade_ai=_ta_entry())],
        now=NOW,
        identity_registry=_registry(),
    )
    (cand,) = out["candidates"]
    assert cand["event_id"] is None and cand["reconciliation_reasons"] == ["EVENT_MISMATCH"]


def test_hermes_research_time_is_not_an_event_time():
    out = proj.build_candidate_projection(
        {"tickers": []}, [_at_row()], now=NOW, identity_registry=_registry(),
        catalyst_lookup=lambda s, d: {"status": "FOUND", "summary": "XLAB wins contract", "catalyst_type": "contract",
                                      "researched_at": "2026-10-22T08:25:00-04:00"},
    )
    (cand,) = out["candidates"]
    assert cand["security_guid"] == SEC and cand["event_id"] is None
    assert cand["reconciliation_reasons"] == ["EVENT_UNRESOLVED"]
    (evidence,) = _at_evidence(out)
    assert evidence["catalyst"]["origin"] == "HERMES_SCALP_RESEARCH"


def test_snapshot_reads_registry_only_from_the_journal_state_root(tmp_path):
    state = tmp_path / "state"
    jp = state / "data/active_trader/momentum_alerts.jsonl"
    jp.parent.mkdir(parents=True)
    jp.write_text(json.dumps(_at_row()) + "\n")
    reg = state / "data/runtime/identity_registry.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(json.dumps(_registry()))
    out = proj.read_candidate_snapshot(tmp_path / "missing_cache.json", jp, now=NOW)
    assert out["candidates"][0]["security_guid"] == SEC
    flat = tmp_path / "momentum_alerts.jsonl"  # not a state-root layout: nothing resolved, nothing guessed
    flat.write_text(json.dumps(_at_row()) + "\n")
    assert proj.read_candidate_snapshot(tmp_path / "missing_cache.json", flat, now=NOW)["candidates"][0][
        "security_guid"
    ] is None


# ── 5. gap pillar from today's Trade-AI row ──────────────────────────────────────────────────────────────


def test_at_gap_pillar_reads_trade_ai_row_with_its_scan_clock():
    out = proj.build_candidate_projection({"tickers": []}, [_at_row(trade_ai=_ta_entry())], now=NOW)
    (evidence,) = _at_evidence(out)
    gap = {p["id"]: p for p in evidence["pillars"]}["gap"]
    assert gap["value"] == 24.0 and gap["status"] == "PASSED"
    assert gap["observed_at"] == datetime.fromisoformat(SCANNED).astimezone(timezone.utc).isoformat()
    assert gap["source_ref"] == f"trade_ai_scans:{DAY}"


def test_at_gap_stays_unknown_without_a_trade_ai_row():
    out = proj.build_candidate_projection({"tickers": []}, [_at_row()], now=NOW)
    (evidence,) = _at_evidence(out)
    gap = {p["id"]: p for p in evidence["pillars"]}["gap"]
    assert gap["value"] is None and gap["status"] == "UNKNOWN"
