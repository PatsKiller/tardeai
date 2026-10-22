"""Desk truth, 2026-10-22 (operator: "fix all of these n8n first for scheduling and monitoring").

Covers, hermetically (tmp files, fake readers, fake intent queue; no DB, no broker, no network):
  * scripts/desk_truth_monitor.py — holdings drift, options desk staleness, held exit coverage; alert-on-gain;
    needs-action source desk_truth; the lane closure reaches no db_adapter, sender, broker or order module;
  * scripts/options_desk_quote_refresh.py — quote-only refresh: offline dry run (no broker import), bounded reads,
    live_quote written without touching card economics, access-mode refusal, concurrent-rebuild refusal;
  * the options CIO review on its own LLM process (AGENTS.md §9.2): task -> process, registry row, routing row,
    bridge maps, FAST_THINK allowed (the POLICY_NOT_ALLOWED cause), Steph's row unchanged;
  * scripts/options_thesis_reopen.py --review-cap.
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

from scripts import desk_truth_monitor as DTM  # noqa: E402
from scripts import options_desk_quote_refresh as QR  # noqa: E402

CFG = DTM.load_config()
# Wed 2026-10-21 14:00 ET (18:00Z): a trading day, in session
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
ALWAYS = lambda _now: True  # noqa: E731
NEVER = lambda _now: False  # noqa: E731


# ── holdings drift ───────────────────────────────────────────────────────────────────────────────────────────────


def _store(**over):
    rows = [
        {"account": "schwab_rollover_ira", "symbol": "SCHD", "shares": 4000, "broker_position_as_of_at": "2026-10-21T17:30:00+00:00"},
        {"account": "schwab_rollover_ira", "symbol": "SCHG", "shares": 2000},
        {"account": "schwab_rollover_ira", "symbol": "CASH", "is_cash": True, "market_value": 200000.0},
        {"account": "schwab_roth", "symbol": "V", "shares": 130.4985},
        {"account": "fidelity_x", "symbol": "ZZZ", "shares": 5},
    ]
    doc = {"holdings": rows, "positions_built_at": "2026-10-10T00:00:00+00:00"}
    doc.update(over)
    return doc


PC = [
    {"account_key": "schwab_rollover_ira", "symbol": "SCHD", "qty": 6000.2529, "is_cash": False, "as_of": "2026-10-21T17:55:00+00:00"},
    {"account_key": "schwab_rollover_ira", "symbol": "SCHG", "qty": 4000, "is_cash": False, "as_of": "2026-10-21T17:55:00+00:00"},
    {"account_key": "schwab_rollover_ira", "symbol": "NAVN", "qty": 500, "is_cash": False, "as_of": "2026-10-21T17:55:00+00:00"},
    {"account_key": "schwab_rollover_ira", "symbol": "CASH", "qty": 46080.0, "is_cash": True, "as_of": "2026-10-21T17:55:00+00:00"},
    {"account_key": "schwab_roth_ira", "symbol": "V", "qty": 130.4985, "is_cash": False, "as_of": "2026-10-21T17:55:00+00:00"},
]


def _run(check, sources, now=NOW, trading_day=ALWAYS):
    return DTM.run_check(check, now=now, cfg=CFG, sources=sources, trading_day=trading_day)


def test_holdings_drift_reports_the_2026_10_22_shape():
    rep = _run("holdings-drift", {"holdings": _store, "positions_current": lambda: PC})
    codes = {(f["code"], f["key"]) for f in rep["findings"]}
    assert ("MISSING_IN_HOLDINGS", "missing:schwab_rollover_ira:NAVN") in codes
    assert ("QTY_DRIFT", "qty:schwab_rollover_ira:SCHD") in codes
    assert ("QTY_DRIFT", "qty:schwab_rollover_ira:SCHG") in codes
    cash = next(f for f in rep["findings"] if f["code"] == "CASH_DRIFT")
    assert cash["evidence"]["delta"] == 153920.0
    # the roth alias maps holdings 'schwab_roth' onto positions_current 'schwab_roth_ira': no drift for V
    assert not any("V" == f["evidence"].get("symbol") for f in rep["findings"])
    # a non-compared account (fidelity) is ignored
    assert not any("ZZZ" in f["key"] for f in rep["findings"])
    assert rep["holdings_basis"] == "broker_position_as_of_at" and rep["holdings_age_h"] == 0.5
    assert "HOLDINGS_STALE" not in rep["by_code"] and rep["alertable"]


def test_holdings_stale_in_session_only_and_falls_back_to_positions_built_at():
    store = _store()
    for r in store["holdings"]:
        r.pop("broker_position_as_of_at", None)
    rep = _run("holdings-drift", {"holdings": lambda: store, "positions_current": lambda: PC})
    stale = next(f for f in rep["findings"] if f["code"] == "HOLDINGS_STALE")
    assert stale["evidence"]["basis"] == "positions_built_at"
    rep = _run("holdings-drift", {"holdings": lambda: store, "positions_current": lambda: PC}, trading_day=NEVER)
    assert "HOLDINGS_STALE" not in rep["by_code"] and rep["in_session"] is False


def test_holdings_drift_clean_and_unreadable_sources():
    same = [{"account_key": "schwab_rollover_ira", "symbol": "SCHD", "qty": 4000, "is_cash": False,
             "as_of": "2026-10-21T17:55:00+00:00"},
            {"account_key": "schwab_rollover_ira", "symbol": "SCHG", "qty": 2000, "is_cash": False,
             "as_of": "2026-10-21T17:55:00+00:00"},
            {"account_key": "schwab_rollover_ira", "symbol": "CASH", "qty": 200010.0, "is_cash": True,
             "as_of": "2026-10-21T17:55:00+00:00"},
            {"account_key": "schwab_roth_ira", "symbol": "V", "qty": 130.4985, "is_cash": False,
             "as_of": "2026-10-21T17:55:00+00:00"}]
    rep = _run("holdings-drift", {"holdings": _store, "positions_current": lambda: same})
    assert rep["findings"] == [] and rep["fingerprint"] == DTM.fingerprint([])

    def boom():
        raise OSError("no db")
    rep = _run("holdings-drift", {"holdings": _store, "positions_current": boom})
    assert rep["error"].startswith("positions_current_unreadable")
    rep = _run("holdings-drift", {"holdings": lambda: {}, "positions_current": lambda: same})
    assert rep["error"].startswith("holdings_unreadable")


def test_positions_current_stale_is_named_and_not_trusted():
    old = [dict(r, as_of="2026-10-21T12:00:00+00:00") for r in PC]
    rep = _run("holdings-drift", {"holdings": _store, "positions_current": lambda: old})
    assert "POSITIONS_CURRENT_STALE" in rep["by_code"]


# ── options desk staleness ───────────────────────────────────────────────────────────────────────────────────────


def test_desk_stale_in_regular_session_uses_the_newer_of_build_and_quote_refresh():
    doc = {"generated_at": "2026-10-21T13:30:00+00:00", "proposals": [{}]}
    rep = _run("options-desk-staleness", {"options_desk": lambda: doc})
    f = rep["findings"][0]
    assert f["code"] == "DESK_STALE" and f["evidence"]["age_min"] == 270.0
    doc["quote_refresh"] = {"at": "2026-10-21T17:50:00+00:00"}
    rep = _run("options-desk-staleness", {"options_desk": lambda: doc})
    assert rep["findings"] == [] and rep["freshness_basis"] == "quote_refresh.at" and rep["age_min"] == 10.0


def test_desk_staleness_is_quiet_outside_the_session():
    doc = {"generated_at": "2026-10-20T20:05:00+00:00", "proposals": []}
    rep = _run("options-desk-staleness", {"options_desk": lambda: doc}, trading_day=NEVER)
    assert rep["market_session"] == "CLOSED" and rep["findings"] == []
    rep = _run("options-desk-staleness", {"options_desk": lambda: doc},
               now=datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc))
    assert rep["market_session"] == "AFTER_HOURS" and rep["findings"] == []


# ── held exit coverage ───────────────────────────────────────────────────────────────────────────────────────────


SNAP_AT = "2026-10-21T17:58:00+00:00"
HELD = [
    {"account_key": "schwab_rollover_ira", "symbol": "SCHD", "qty": 6000, "is_cash": False, "broker_market_value": 210000},
    {"account_key": "schwab_rollover_ira", "symbol": "NAVN", "qty": 500, "is_cash": False, "broker_market_value": 13555},
    {"account_key": "schwab_roth_ira", "symbol": "V", "qty": 130, "is_cash": False, "broker_market_value": 53000},
    {"account_key": "schwab_taxable", "symbol": "PFLT", "qty": 1.1, "is_cash": False, "broker_market_value": 7.3},
    {"account_key": "schwab_taxable", "symbol": "XYZ", "qty": 10, "is_cash": False, "broker_market_value": None},
    {"account_key": "schwab_taxable", "symbol": "CASH", "qty": 5000, "is_cash": True},
]
SNAP = [
    {"account": "schwab_rollover_ira", "symbol": "NAVN", "lifecycle": "working", "snapshot_at": SNAP_AT},
    {"account": "schwab_rollover_ira", "symbol": "SCHD", "lifecycle": "cancelled", "snapshot_at": SNAP_AT},
    {"account": "schwab_roth", "symbol": "V", "lifecycle": "near_trigger", "snapshot_at": SNAP_AT},
    {"account": "tradeai_automated", "symbol": "AAPL", "lifecycle": "working", "snapshot_at": SNAP_AT},
]


def test_exit_coverage_names_uncovered_live_positions_and_tags_paper():
    rep = _run("held-exit-coverage", {"positions_current": lambda: HELD, "stop_lifecycle": lambda: SNAP})
    keys = [f["key"] for f in rep["findings"]]
    assert keys == ["uncovered:schwab_rollover_ira:SCHD", "uncovered:schwab_taxable:XYZ"]
    assert all(f["evidence"]["tag"] == "LIVE" for f in rep["findings"])
    assert rep["coverage_verdict"] == "GAPS" and rep["below_value_floor"] == 1
    assert rep["paper_stop_rows"] == 1 and rep["paper_tag"] == "PAPER"
    assert rep["alertable"] == keys


def test_stale_snapshot_is_not_measured_never_uncovered():
    old = [dict(s, snapshot_at="2026-10-21T10:00:00+00:00") for s in SNAP]
    rep = _run("held-exit-coverage", {"positions_current": lambda: HELD, "stop_lifecycle": lambda: old})
    assert rep["coverage_verdict"] == "NOT_MEASURED"
    assert rep["alertable"] == ["snapshot_stale"]
    assert all(not f["alert"] for f in rep["findings"] if f["code"] == "UNCOVERED")


def test_exemptions_are_honoured():
    cfg = json.loads(json.dumps(CFG))
    cfg["held_exit_coverage"]["exempt"] = [{"account": "schwab_rollover_ira", "symbol": "SCHD", "reason": "t"}]
    rep = DTM.run_check("held-exit-coverage", now=NOW, cfg=cfg, trading_day=ALWAYS,
                        sources={"positions_current": lambda: HELD, "stop_lifecycle": lambda: SNAP})
    assert [f["key"] for f in rep["findings"]] == ["uncovered:schwab_taxable:XYZ"] and rep["exempt"] == 1


# ── alerting: alert-on-gain, one intent, never a sender ──────────────────────────────────────────────────────────


def test_alert_queues_only_when_the_finding_set_gains(tmp_path):
    calls = []

    def fake_queue(**kw):
        calls.append(kw)
        return {"intent_id": "i1", "duplicate": False}

    rep = _run("held-exit-coverage", {"positions_current": lambda: HELD, "stop_lifecycle": lambda: SNAP})
    a = DTM.emit_alert(rep, state_root=str(tmp_path), ledger_path=tmp_path / "l.sqlite", execution_id="r1",
                       queue=fake_queue)
    assert a["queued"] and len(calls) == 1
    assert calls[0]["domain"] == "stops" and calls[0]["kind"] == "held_exit_coverage_gap"
    assert calls[0]["producer"] == "desk_truth_monitor" and "SCHD" in calls[0]["summary"]
    a = DTM.emit_alert(rep, state_root=str(tmp_path), ledger_path=tmp_path / "l.sqlite", execution_id="r2",
                       queue=fake_queue)
    assert not a["queued"] and len(calls) == 1


def test_refused_intent_keeps_the_old_state_so_the_next_run_retries(tmp_path):
    from scripts.check_registry_runtime_truth import IntentRefused

    def refuse(**_kw):
        raise IntentRefused("intent_unrouted")

    rep = _run("options-desk-staleness", {"options_desk": lambda: {"generated_at": "2026-10-21T13:30:00+00:00"}})
    a = DTM.emit_alert(rep, state_root=str(tmp_path), ledger_path=tmp_path / "l.sqlite", execution_id="r",
                       queue=refuse)
    assert a == {"queued": False, "gained": ["desk_stale"], "reason": "intent_intent_unrouted"}
    assert not DTM.alert_state_path("options-desk-staleness-monitor", str(tmp_path)).exists()


def test_intent_routes_are_owned_digest_routes():
    from scripts.lib.n8n_fabric_store import load_host_intent_routes

    routes = load_host_intent_routes()["routes"]
    for check, spec in DTM.CHECKS.items():
        r = routes[(spec["domain"], spec["kind"])]
        assert r["tier"] == "DIGEST" and r["producer"] == DTM.PRODUCER, check


def test_queue_host_intent_into_a_tmp_ledger(tmp_path):
    """The real store path: the intent lands as one row; a repeat inside the window is a duplicate."""
    import sqlite3

    from scripts.check_registry_runtime_truth import queue_host_intent

    ledger = tmp_path / "ledger.sqlite"
    sqlite3.connect(str(ledger)).close()  # an existing ledger file (the store refuses ledger_absent otherwise)
    kw = dict(producer=DTM.PRODUCER, domain="positions", kind="holdings_drift_finding",
              subject="holdings-drift: 1 finding(s) (1 new)", summary="x", execution_id="run1", node="fp",
              ledger_path=ledger, now=1_800_000_000.0)
    rec = queue_host_intent(**kw)
    assert rec.get("intent_id") and not rec.get("duplicate")
    again = queue_host_intent(**dict(kw, execution_id="run2", now=1_800_000_060.0))
    assert again.get("duplicate") is True


def test_apply_writes_receipt_and_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    doc = tmp_path / "options_proposals.json"
    doc.write_text(json.dumps({"generated_at": "2026-10-21T17:55:00+00:00", "proposals": []}))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "ledger.sqlite"))
    rc = DTM.main(["--check", "options-desk-staleness", "--proposals", str(doc), "--state-root", str(tmp_path),
                   "--now", "2026-10-21T18:00:00+00:00"])
    assert rc == 0 and not (tmp_path / "data").exists()
    rc = DTM.main(["--check", "options-desk-staleness", "--apply", "--proposals", str(doc), "--state-root",
                   str(tmp_path), "--now", "2026-10-21T18:00:00+00:00"])
    assert rc == 0
    r = json.loads((tmp_path / "data" / "runtime" / "options-desk-staleness-monitor_last.json").read_text())
    assert r["lane_id"] == "options-desk-staleness-monitor" and r["status"] == "ok"
    assert r["produced_count"] == 1 and r["summary"]["finding_count"] == 0


def test_monitor_closure_reaches_no_db_adapter_sender_broker_or_order():
    import audit_lane_transitive_capabilities as cap

    res = cap.Resolver()
    order, _ = res.closure(ROOT / "scripts" / "desk_truth_monitor.py")
    rels = {res.info(m).path for m in order}
    assert not rels & {"scripts/db_adapter.py", "scripts/telegram_alert.py", "scripts/lib/host_comms_intents.py",
                       "scripts/n8n_coordination_gateway.py", "scripts/schwab_transport.py"}, rels
    caps = set().union(*(res.info(m).caps for m in order))
    assert not caps & {"direct_sender", "broker_module", "order_placement", "chokepoint_send"}, caps


def test_monitor_lane_ids_and_argv_pass_the_forbidden_token_rule():
    from scripts.lib.lane_dispatch import forbidden_text_hits

    for check, spec in DTM.CHECKS.items():
        assert forbidden_text_hits(spec["lane"]) == []
        assert forbidden_text_hits(f"$PY scripts/desk_truth_monitor.py --check {check} --apply") == []
    assert forbidden_text_hits("options-desk-quote-refresh $PY scripts/options_desk_quote_refresh.py --apply") == []


def test_monitor_never_names_the_holdings_file_literal():
    """tests/test_portfolio_price_truth_20261005.py ratchets direct readers; the monitor uses load_store()."""
    assert "holdings" + ".json" not in (ROOT / "scripts" / "desk_truth_monitor.py").read_text()


# ── needs-action source ──────────────────────────────────────────────────────────────────────────────────────────


def test_needs_action_desk_truth_rule():
    from scripts.lib import needs_action as NA

    none = {lane: {"status": "NO_RECEIPT"} for lane in NA.DESK_TRUTH_LANES}
    items = NA.rule_desk_truth(none, NOW)
    assert [i["severity"] for i in items] == ["P3"]
    rec = {"lane_id": "held-exit-coverage-monitor", "status": "ok", "ok_at": "2026-10-21T17:00:00+00:00",
           "summary": {"as_of": "x", "findings": [
               {"code": "UNCOVERED", "key": "uncovered:a:SCHD", "detail": "a SCHD: held 6000, no WORKING stop",
                "alert": True},
               {"code": "UNCOVERED", "key": "uncovered:a:Q", "detail": "q", "alert": False}]}}
    items = NA.rule_desk_truth(dict(none, **{"held-exit-coverage-monitor": rec}), NOW)
    sev = sorted(i["severity"] for i in items)
    assert sev == ["P2", "P3", "P3"] and any("SCHD" in i["title"] for i in items)
    stale = dict(rec, ok_at="2026-10-19T00:00:00+00:00", status="failed", error="db down")
    items = NA.rule_desk_truth(dict(none, **{"held-exit-coverage-monitor": stale}), NOW)
    titles = [i["title"] for i in items]
    assert "held-exit-coverage-monitor failed" in titles and "held-exit-coverage-monitor is stale" in titles
    assert "desk_truth" in NA.RULES


def test_needs_action_probe_reads_receipts(tmp_path):
    from scripts.lib import needs_action as NA

    out = NA.probe_desk_truth(tmp_path)
    assert all(v["status"] == "NO_RECEIPT" for v in out.values())
    d = tmp_path / "data" / "runtime"
    d.mkdir(parents=True)
    (d / "holdings-drift-monitor_last.json").write_text(json.dumps({"lane_id": "holdings-drift-monitor"}))
    assert NA.probe_desk_truth(tmp_path)["holdings-drift-monitor"]["lane_id"] == "holdings-drift-monitor"


def test_api_v2_wires_the_desk_truth_source():
    assert '"desk_truth": _na.probe_desk_truth' in (ROOT / "scripts" / "api_v2.py").read_text()


# ── options desk quote refresh ───────────────────────────────────────────────────────────────────────────────────


def _desk(tmp_path, cards=None):
    cards = cards if cards is not None else [
        {"id": "a", "symbol": "SPCX", "expiration": "2026-11-20", "option_type": "put", "strike": 148,
         "premium": 9.1, "bid": 9.0, "ask": 9.2, "account": "schwab_rollover_ira"},
        {"id": "b", "symbol": "SPCX", "expiration": "2026-11-20", "option_type": "put", "strike": 148,
         "premium": 9.1, "account": "schwab_taxable"},
        {"id": "c", "symbol": "SCHG", "expiration": "2026-12-18", "option_type": "put", "short_strike": 30,
         "long_strike": 28, "account": "schwab_rollover_ira"},
        {"id": "d", "symbol": "XYZ"},
    ]
    p = tmp_path / "options_proposals.json"
    p.write_text(json.dumps({"generated_at": "2026-10-21T13:30:00+00:00", "proposals": cards}))
    return p


def _chain(symbol, *, expiration, contract_type=None, all_strikes=False):
    assert all_strikes is True
    strikes = {"SPCX": [148.0], "SCHG": [30.0, 28.0]}[symbol]
    return {"status": "ok", "underlying_price": 150.5, "underlying_quote_time": "2026-10-21T13:59:58+00:00",
            "fetched_at": "2026-10-21T14:00:00+00:00",
            "expirations": [{"exp": expiration, "strikes": [
                {"side": "put", "strike": k, "bid": 1.0 + k / 100, "ask": 1.2 + k / 100, "symbol": f"{symbol}_{k}",
                 "quote_time": "2026-10-21T13:59:59+00:00"} for k in strikes]}]}


def test_plan_groups_one_read_per_symbol_expiration_and_bounds_it():
    cards = json.loads(_desk(Path(__import__("tempfile").mkdtemp())).read_text())["proposals"]
    plan = QR.plan_groups(cards, 25)
    assert plan["groups"] == 2 and plan["requests_planned"] == 2 and plan["no_contract"] == ["d"]
    assert [(g["symbol"], g["contract_type"], len(g["cards"])) for g in plan["read"]] == [("SPCX", "put", 2),
                                                                                          ("SCHG", "put", 1)]
    plan = QR.plan_groups(cards, 1)
    assert plan["requests_planned"] == 1 and len(plan["over_budget"]) == 1


def test_dry_run_is_offline_and_imports_no_broker_module(tmp_path, monkeypatch):
    p = _desk(tmp_path)
    before = p.read_text()
    sys.modules.pop("schwab_transport", None)
    rep = QR.run(proposals=p, apply=False, max_requests=25, now=NOW,
                 mode_fn=lambda: pytest.fail("dry run must not read the access mode"))
    assert rep["requests_made"] == 0 and rep["requests_planned"] == 2 and "schwab_transport" not in sys.modules
    assert p.read_text() == before


def test_apply_writes_live_quote_only_and_stamps_the_session(tmp_path):
    p = _desk(tmp_path)
    reads = []

    def chain(*a, **kw):
        reads.append((a, kw))
        return _chain(*a, **kw)

    rep = QR.run(proposals=p, apply=True, max_requests=25, now=NOW, chain_fn=chain, mode_fn=lambda: "read_only")
    assert rep.get("wrote") and rep["requests_made"] == 2 == len(reads) and rep["cards_requoted"] == 3
    doc = json.loads(p.read_text())
    a, b, c, d = doc["proposals"]
    assert a["live_quote"]["bid"] == 2.48 and a["live_quote"]["mid"] == 2.58 and a["live_quote"]["occ_symbol"] == "SPCX_148.0"
    assert a["premium"] == 9.1 and a["bid"] == 9.0  # the build's economics are untouched
    assert a["live_quote"]["underlying_price"] == 150.5 and a["live_quote"]["provenance"] == "observed_quote"
    assert [leg["leg"] for leg in c["live_quote"]["legs"]] == ["short", "long"]
    assert "live_quote" not in d
    assert doc["generated_at"] == "2026-10-21T13:30:00+00:00"
    qr = doc["quote_refresh"]
    assert qr["requests"] == 2 and qr["request_budget"] == 25 and qr["market_session"] == "REGULAR"
    assert qr["cards_skipped"] == {"card_has_no_contract": 1}
    assert QR.lane_output(rep)["produced_count"] == 3


def test_access_mode_other_than_read_only_refuses_before_any_read(tmp_path):
    p = _desk(tmp_path)
    for mode in ("normal", "forbidden"):
        rep = QR.run(proposals=p, apply=True, max_requests=25, now=NOW,
                     chain_fn=lambda *a, **k: pytest.fail("no read"), mode_fn=lambda m=mode: m)
        assert rep["error"] == f"schwab_access_mode_not_read_only:{mode}"
        assert QR.lane_output(rep)["skipped_reasons"] == {"disabled": 1}  # closed FATAL_SKIP_REASONS vocabulary


def test_concurrent_rebuild_wins(tmp_path):
    p = _desk(tmp_path)

    def chain(*a, **kw):
        p.write_text(json.dumps({"generated_at": "2026-10-21T14:00:01+00:00", "proposals": []}))
        import os
        os.utime(p, ns=(1, 1))
        return _chain(*a, **kw)

    rep = QR.run(proposals=p, apply=True, max_requests=25, now=NOW, chain_fn=chain, mode_fn=lambda: "read_only")
    assert rep["error"] == "snapshot_changed_during_refresh"
    assert json.loads(p.read_text())["proposals"] == []


def test_outside_regular_hours_reads_nothing(tmp_path):
    """The single cadence 5,20,35,50 9-11 also fires 09:05 / 09:20 ET: those runs read nothing (NYSE calendar)."""
    p = _desk(tmp_path)
    before = p.read_text()
    for when in (datetime(2026, 10, 21, 13, 5, tzinfo=timezone.utc),    # 09:05 EDT, pre-open
                 datetime(2026, 11, 26, 15, 35, tzinfo=timezone.utc),   # Thanksgiving 10:35 EST, holiday
                 datetime(2026, 12, 2, 14, 20, tzinfo=timezone.utc)):   # 09:20 EST: the coarse -4h label says REGULAR
        rep = QR.run(proposals=p, apply=True, max_requests=25, now=when, mode_fn=lambda: "read_only",
                     chain_fn=lambda *a, **k: pytest.fail("no read outside RTH"))
        assert rep["empty_reason"] == "market_closed" and rep["requests_made"] == 0, when
    assert p.read_text() == before
    from scripts.lib.desk_session import market_session

    assert market_session(datetime(2026, 12, 2, 14, 40, tzinfo=timezone.utc)) == "REGULAR"  # 09:40 EST


def test_failed_reads_skip_cards_and_all_failed_is_an_error(tmp_path):
    p = _desk(tmp_path)
    rep = QR.run(proposals=p, apply=True, max_requests=25, now=NOW, chain_fn=lambda *a, **k: {"status": "error"},
                 mode_fn=lambda: "read_only")
    assert rep["error"] == "every_chain_read_failed" and rep["skipped"]["chain_unavailable"] == 3


def test_quote_refresh_cli_bounds_and_default_is_dry_run(tmp_path):
    p = _desk(tmp_path)
    assert QR.main(["--max-requests", "0", "--proposals", str(p)]) == 2
    assert QR.main(["--max-requests", "61", "--proposals", str(p)]) == 2
    assert QR.main(["--proposals", str(p), "--state-root", str(tmp_path)]) == 0
    assert not (tmp_path / "data").exists()


# ── options CIO review on its own process (AGENTS.md §9.2) ──────────────────────────────────────────────────────


def _reg():
    return {p["id"]: p for p in json.loads((ROOT / "config" / "llm_process_registry.json").read_text())["processes"]}


def test_options_review_names_its_own_process():
    from scripts.lib.agent_flash_governance import TASK_TO_PROCESS, policy_for_task, process_for_task

    assert process_for_task("options_thesis_review") == "options_thesis_cio_review"
    assert process_for_task("cio_synthesis") == "watchlist_steph_flash_narrative"  # Steph unchanged
    assert TASK_TO_PROCESS["options_thesis_review"] == "options_thesis_cio_review"
    # the cause: thesis text with "reconcile" escalates to FAST_THINK
    pol, why = policy_for_task("options_thesis_review",
                               prompt="thesis: neither level can be validated or reconciled from the sources")
    assert pol == "FAST_THINK" and why


def test_registry_row_allows_fast_think_with_caps_and_no_pro():
    from scripts.lib.llm_consumption import _allowed_lanes_from_registry

    row = _reg()["options_thesis_cio_review"]
    lanes = _allowed_lanes_from_registry(row)
    assert "fast_think" in lanes and "fast" in lanes and {"grok", "chatgpt"} <= set(lanes)
    assert row["deepseek_allowed_policies"] == ["FAST", "FAST_THINK"] and row["deepseek_default_policy"] == "FAST"
    assert row["daily_soft_cap"] == 40 and row["daily_cost_cap_usd"] == 0.4
    assert row["default_mode"] == "automated" and row["max_output_tokens"] >= 2500
    assert row["tools_allowed"] is False and row["fallback_allowed"] is False and row["advisory_only"] is True
    assert not any(p.startswith("PRO") for p in row["deepseek_allowed_policies"])
    steph = _reg()["watchlist_steph_flash_narrative"]
    assert "fast_think" not in steph["allowed_lanes"]  # the shared pool is not widened


def test_bridge_maps_routing_row_and_caps_sync_agree():
    from scripts.lib import governed_process_routes as G
    from scripts.lib.cio_governed_model_bridge import CALLER_TASK_PROCESS_MAP
    from scripts.sync_cio_process_caps import CAPS

    assert CALLER_TASK_PROCESS_MAP["advisory_desk"]["options_thesis_cio_review"] == "options_thesis_cio_review"
    assert G.route_for_process("options_thesis_cio_review") == ("advisory_desk", "options_thesis_cio_review")
    pol = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text())
    rows = pol["policies"]["default"]["processes"]
    assert rows["options_thesis_cio_review"]["fallback"]["provider"] == "deepseek"
    assert rows["options_thesis_cio_review"]["cost_ceiling_usd"] == 0.4
    assert CAPS["options_thesis_cio_review"] == (0.40, 40)


def test_review_calls_the_router_with_its_own_task(monkeypatch):
    import scripts.lib.options_cio_review as OCR

    seen = {}

    def fake(task, prompt, **kw):
        seen["task"] = task
        seen["meta"] = kw.get("metadata")
        return {"success": True, "response": "{}"}

    import llm_router
    monkeypatch.setattr(llm_router, "get_llm_response", fake)
    OCR._default_llm("p", symbol="SPCX", job_key="k")
    assert seen["task"] == "options_thesis_review" and seen["meta"]["task"] == "options_thesis_review"


def test_sync_caps_dry_run_touches_no_database(capsys):
    from scripts.sync_cio_process_caps import main

    assert main(["--dry-run"]) == 0
    assert "would upsert options_thesis_cio_review: cost=0.4 soft=40" in capsys.readouterr().out


# ── broker READ-ONLY lanes wait for AGENTS 18.0.0; the forbidden-token rule is untouched ─────────────────────────


def test_holdings_writer_n8n_lane_is_gated_on_18_0_0_and_still_refused():
    from scripts.lib import lane_dispatch as LD
    from scripts.pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS

    reg = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
    allow = {e["lane_id"] for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
    row = reg["schwab-position-sync"]
    gate = row["f09_staged"]["gated_on"]
    assert "18.0.0" in gate["policy"] and gate["status_required"] == "ACTIVE"
    assert "host cron line 501" in row["f09_staged"]["host_schedule_until_18"]
    assert "schwab-position-sync" not in allow and "dispatch" not in row
    # the check is not weakened: the token and the word still refuse the lane
    assert "schwab_position_sync.py" in FORBIDDEN_COMMAND_TOKENS and "schwab" in LD.EXTRA_FORBIDDEN_WORDS
    candidate = dict(row, dispatch={"mode": "dry_run", "cron": ["7,22,37,52 9-16 * * 1-5"], "tz": "America/New_York",
                                    "wave": "W5", "class": "pipeline", "priority": 2, "retry_policy": "none"})
    ok, why = LD.dispatch_eligible(candidate)
    assert not ok and why.startswith("forbidden_token:"), why


# ── options_thesis_reopen --review-cap ───────────────────────────────────────────────────────────────────────────


class _FakeStore:
    def __init__(self, lives):
        self.lives = lives
        self.appended = []

    def lifecycle(self, guid):
        life = dict(self.lives[guid])
        if any(g == guid for g, *_ in self.appended):
            life["review_failures"] = 0
        return life

    def append_event(self, guid, event, **kw):
        self.appended.append((guid, event, kw))


def _reopen(monkeypatch, store, argv):
    import lib.options_thesis as OT
    import options_thesis_reopen as REOPEN

    monkeypatch.setattr(OT, "OptionsThesisStore", lambda: store)
    return REOPEN.main(argv)


def test_reopen_review_cap_dry_run_then_apply(monkeypatch, capsys):
    g = "19e3db3f-ea61-59a7-9091-a369ee6e58d9"
    store = _FakeStore({g: {"stage": "CREATED", "review_failures": 3, "decisions": []}})
    assert _reopen(monkeypatch, store, ["--guid", g, "--reason", "t"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["steps"][0]["action"] == "SKIP" and "--review-cap" in out["steps"][0]["reason"]
    assert _reopen(monkeypatch, store, ["--guid", g, "--review-cap", "--reason", "t"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["steps"][0]["action"] == "REOPEN_REVIEW_CAP" and not store.appended
    assert _reopen(monkeypatch, store, ["--guid", g, "--review-cap", "--reason", "t", "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert store.appended == [(g, "OPTIONS_THESIS_REOPENED", {"actor": "operator", "reason": "t",
                                                              "reopened_from": "review_failure_cap"})]
    assert out["steps"][0]["review_failures_now"] == 0


def test_reopen_review_cap_skips_an_idea_under_the_cap(monkeypatch, capsys):
    g = "g-under"
    store = _FakeStore({g: {"stage": "CREATED", "review_failures": 1, "decisions": []}})
    _reopen(monkeypatch, store, ["--guid", g, "--review-cap", "--reason", "t", "--apply"])
    out = json.loads(capsys.readouterr().out)
    assert out["steps"][0]["action"] == "SKIP" and not store.appended
