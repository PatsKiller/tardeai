#!/usr/bin/env python3
"""ALPACA-OPTIONS Stage 2 (Parts C/D) — Alpaca paper options lane tests.

All HTTP is mocked (FakeHTTP / FakeClient); NO test can ever reach a broker.

Covers: the paper-URL hard lock (live URL / spoof host / missing env / live-
indicating env names all refused), limit-only + 1-contract + buy-to-open order
policy, operator-flag requirements on the CLI (submit refused without
--proposal-id/--confirm), request/response/read-back persisted into row meta,
state-machine legality incl. READY_FOR_LIVE_REVIEW being operator-only and
never automatic, reconcile fill→close→record_outcome→OUTCOME_RECORDED with
correct premium-diff math, forbidden-import sweeps (no other-broker / stop /
second-factor machinery), no desk-review mutation (resolve_approval untouched,
legacy statuses never written), scanner/generator isolation (they never import
this lane), and migration shape (additive states, protective trigger).

    .venv/bin/python -m pytest tests/test_alpaca_paper_options_executor.py -q
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import alpaca_paper as ap  # noqa: E402
import alpaca_paper_options_executor as cli  # noqa: E402

PAPER_ENV = {
    "ALPACA_PAPER_BASE_URL": "https://paper-api.alpaca.markets",
    "ALPACA_API_KEY": "PKTESTKEY",
    "ALPACA_SECRET_KEY": "testsecret",
    "ALPACA_MODE": "paper",
}

RTX_PROPOSAL = {
    "id": "opt_deep_itm_call_RTX_paper_model_160p0000_20260918",
    "strategy": "deep_itm_call",
    "symbol": "RTX",
    "underlying": "RTX",
    "side": "BUY",
    "option_type": "call",
    "strike": 160.0,
    "expiration": "2026-09-18",
    "contracts": 1,
    "premium": 40.62,
}


def _row(status="pending", proposal=None, meta=None, pid=None):
    p = copy.deepcopy(proposal or RTX_PROPOSAL)
    return {"id": 1, "proposal_id": pid or p["id"], "symbol": p["symbol"],
            "strategy": p["strategy"], "status": status,
            "proposal_json": p, "meta": meta or {},
            "created_at": None, "updated_at": None}


class FakeDB:
    """Stateful executor matching the module's exact query shapes."""

    def __init__(self, rows=()):
        self.rows = {r["proposal_id"]: r for r in rows}
        self.calls = []

    def __call__(self, sql, params=None, fetch=None):
        s = " ".join(sql.split())
        self.calls.append({"sql": s, "params": params, "fetch": fetch})
        if s.startswith("SELECT") and "WHERE proposal_id=%s" in s:
            r = self.rows.get(params[0])
            return copy.deepcopy(r) if r else None
        if s.startswith("SELECT") and "WHERE status=%s" in s:
            return [copy.deepcopy(r) for r in self.rows.values()
                    if r["status"] == params[0]]
        if "GROUP BY status" in s:
            out = {}
            for r in self.rows.values():
                out[r["status"]] = out.get(r["status"], 0) + 1
            return [{"status": k, "n": v} for k, v in sorted(out.items())]
        if s.startswith("UPDATE options_approval_queue SET status=%s"):
            to_status, patch_json, pid, from_status = params
            r = self.rows.get(pid)
            if not r or r["status"] != from_status:
                return None
            r["status"] = to_status
            r["meta"] = {**(r.get("meta") or {}), **json.loads(patch_json)}
            return {"id": r["id"]}
        if s.startswith("UPDATE options_approval_queue SET meta ="):
            patch_json, pid = params
            r = self.rows.get(pid)
            if r:
                r["meta"] = {**(r.get("meta") or {}), **json.loads(patch_json)}
            return True
        if "INSERT INTO options_monitored_positions" in s:
            return True
        if "SELECT * FROM options_monitored_positions WHERE proposal_id" in s:
            return None
        if s.startswith("UPDATE options_monitored_positions"):
            return True
        if "SELECT id FROM options_monitored_alerts" in s:
            return None
        if s.startswith("UPDATE options_monitored_alerts"):
            return True
        raise AssertionError(f"FakeDB got unexpected SQL: {s[:120]}")


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeHTTP:
    """requests-shaped double; records every call so tests can assert zero HTTP."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        return self.responses.get(("POST", url), FakeResponse({"id": "ord-1",
                                                               "status": "accepted"}))

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(("GET", url, params))
        return self.responses.get(("GET", url), FakeResponse({}, 404))


def _client(http=None, env=None):
    return ap.AlpacaPaperOptionsClient(env=dict(env or PAPER_ENV),
                                       http=http or FakeHTTP())


# ── (1) paper endpoint hard lock ─────────────────────────────────────────────

def test_live_url_refused():
    env = {**PAPER_ENV, "ALPACA_PAPER_BASE_URL": "https://api.alpaca.markets"}
    with pytest.raises(ap.PaperEndpointError):
        ap.resolve_paper_base_url(env)


def test_missing_env_refused_no_default():
    env = {k: v for k, v in PAPER_ENV.items() if k != "ALPACA_PAPER_BASE_URL"}
    with pytest.raises(ap.PaperEndpointError, match="not set"):
        ap.resolve_paper_base_url(env)


def test_spoof_hosts_refused():
    for url in ("https://paper-api.alpaca.markets.evil.com",
                "https://evil.com/paper-api.alpaca.markets",
                "https://broker-api.alpaca.markets",
                "https://example.com/?u=paper-api.alpaca.markets"):
        with pytest.raises(ap.PaperEndpointError):
            ap.resolve_paper_base_url({**PAPER_ENV, "ALPACA_PAPER_BASE_URL": url})


def test_live_indicating_env_names_refused():
    for name in ("ALPACA_LIVE_API_KEY", "APCA_LIVE_BASE_URL", "ALPACA_API_KEY_LIVE"):
        with pytest.raises(ap.PaperEndpointError, match="live-indicating"):
            ap.resolve_paper_base_url({**PAPER_ENV, name: "something"})
    # empty value is inert
    assert ap.resolve_paper_base_url({**PAPER_ENV, "ALPACA_LIVE_API_KEY": ""})


def test_other_alpaca_url_envs_must_be_paper():
    env = {**PAPER_ENV, "ALPACA_BASE_URL": "https://api.alpaca.markets"}
    with pytest.raises(ap.PaperEndpointError, match="non-paper"):
        ap.resolve_paper_base_url(env)
    # data host + paper host are fine
    assert ap.resolve_paper_base_url({**PAPER_ENV,
                                      "ALPACA_BASE_URL": "https://paper-api.alpaca.markets"})


def test_non_paper_mode_refused():
    with pytest.raises(ap.PaperEndpointError, match="ALPACA_MODE"):
        ap.resolve_paper_base_url({**PAPER_ENV, "ALPACA_MODE": "live"})


def test_client_requires_credentials():
    env = {k: v for k, v in PAPER_ENV.items() if k != "ALPACA_API_KEY"}
    with pytest.raises(ap.PaperEndpointError, match="missing"):
        ap.AlpacaPaperOptionsClient(env=env, http=FakeHTTP())


def test_valid_paper_env_resolves():
    assert ap.resolve_paper_base_url(dict(PAPER_ENV)) == "https://paper-api.alpaca.markets"


# ── (2) order policy: limit-only, 1-contract, buy-to-open ───────────────────

OCC = "RTX260918C00160000"


def test_limit_only_rejects_other_types():
    for t in ("market", "stop", "stop_limit", "trailing_stop", "", None):
        with pytest.raises(ap.OrderPolicyError, match="LIMIT"):
            ap.build_order_request(occ_symbol=OCC, limit_price=40.62, order_type=t)


def test_qty_cap_one_contract():
    for q in (2, 5, 100):
        with pytest.raises(ap.OrderPolicyError, match="cap"):
            ap.build_order_request(occ_symbol=OCC, limit_price=40.62, qty=q)
    with pytest.raises(ap.OrderPolicyError):
        ap.build_order_request(occ_symbol=OCC, limit_price=40.62, qty=0)


def test_buy_to_open_only():
    with pytest.raises(ap.OrderPolicyError, match="buy-to-open"):
        ap.build_order_request(occ_symbol=OCC, limit_price=40.62, side="sell")


def test_payload_literals():
    p = ap.build_order_request(occ_symbol=OCC, limit_price=40.625,
                               client_order_id="aopt_x")
    assert p["type"] == "limit" and p["qty"] == "1" and p["side"] == "buy"
    assert p["limit_price"] == "40.62" and p["symbol"] == OCC
    assert p["time_in_force"] == "day"


def test_occ_symbol_construction():
    assert ap.build_occ_symbol("RTX", "2026-09-18", 160.0, "call") == OCC
    assert ap.build_occ_symbol("rtx", "2026-12-18", 172.5, "put") == "RTX261218P00172500"
    with pytest.raises(ap.OrderPolicyError):
        ap.build_occ_symbol("TOOLONGROOT", "2026-09-18", 160, "call")
    with pytest.raises(ap.OrderPolicyError):
        ap.build_occ_symbol("RTX", "18/09/2026", 160, "call")
    with pytest.raises(ap.OrderPolicyError):
        ap.build_occ_symbol("RTX", "2026-09-18", -5, "call")
    with pytest.raises(ap.OrderPolicyError):
        ap.build_occ_symbol("RTX", "2026-09-18", 160, "straddle")


def test_proposal_with_multiple_contracts_refused():
    db = FakeDB([_row(status=ap.STATE_READY,
                      proposal={**RTX_PROPOSAL, "contracts": 3})])
    with pytest.raises(ap.OrderPolicyError, match="cap"):
        ap.build_order_payload(db.rows[RTX_PROPOSAL["id"]])


# ── (3) state machine legality ───────────────────────────────────────────────

def test_full_happy_path_transitions():
    db = FakeDB([_row("pending")])
    pid = RTX_PROPOSAL["id"]
    ap.transition(pid, ap.STATE_READY, operator_actor="operator:test", executor=db)
    ap.transition(pid, ap.STATE_SUBMITTED, executor=db)
    ap.transition(pid, ap.STATE_FILLED, executor=db)
    ap.transition(pid, ap.STATE_CLOSED, executor=db)
    ap.transition(pid, ap.STATE_OUTCOME, executor=db)
    ap.transition(pid, ap.STATE_LIVE_REVIEW, operator_actor="operator:john", executor=db)
    assert db.rows[pid]["status"] == ap.STATE_LIVE_REVIEW
    log = db.rows[pid]["meta"]["alpaca_state_log"]
    assert [e["to"] for e in log][-1] == ap.STATE_LIVE_REVIEW


def test_illegal_transitions_raise():
    pid = RTX_PROPOSAL["id"]
    for from_st, to_st in (("pending", ap.STATE_SUBMITTED),
                           ("pending", ap.STATE_FILLED),
                           (ap.STATE_READY, ap.STATE_FILLED),
                           (ap.STATE_SUBMITTED, ap.STATE_CLOSED),
                           (ap.STATE_FILLED, ap.STATE_OUTCOME),
                           (ap.STATE_REJECTED, ap.STATE_FILLED),
                           ("rejected", ap.STATE_READY)):
        db = FakeDB([_row(from_st)])
        with pytest.raises(ap.IllegalTransitionError):
            ap.transition(pid, to_st, operator_actor="operator:test", executor=db)
        assert db.rows[pid]["status"] == from_st  # unchanged


def test_module_never_writes_legacy_statuses():
    db = FakeDB([_row("pending")])
    for legacy in ("approved", "rejected", "executed", "pending", "blocked"):
        with pytest.raises(ap.IllegalTransitionError, match="legacy|target"):
            ap.transition(RTX_PROPOSAL["id"], legacy,
                          operator_actor="operator:test", executor=db)


def test_live_review_requires_operator_and_outcome_recorded():
    pid = RTX_PROPOSAL["id"]
    # from OUTCOME_RECORDED without operator actor → refused
    db = FakeDB([_row(ap.STATE_OUTCOME)])
    with pytest.raises(ap.OperatorActionRequiredError, match="NEVER set automatically"):
        ap.transition(pid, ap.STATE_LIVE_REVIEW, executor=db)
    with pytest.raises(ap.OperatorActionRequiredError):
        ap.transition(pid, ap.STATE_LIVE_REVIEW, operator_actor="cron", executor=db)
    assert db.rows[pid]["status"] == ap.STATE_OUTCOME
    # from any other state, even WITH operator → illegal
    for st in ("pending", ap.STATE_READY, ap.STATE_SUBMITTED, ap.STATE_FILLED,
               ap.STATE_CLOSED, ap.STATE_REJECTED):
        db2 = FakeDB([_row(st)])
        with pytest.raises(ap.IllegalTransitionError):
            ap.transition(pid, ap.STATE_LIVE_REVIEW,
                          operator_actor="operator:john", executor=db2)
    # the one legal path
    db3 = FakeDB([_row(ap.STATE_OUTCOME)])
    res = ap.mark_live_review(pid, operator_actor="operator:john", executor=db3)
    assert res["ok"] and db3.rows[pid]["status"] == ap.STATE_LIVE_REVIEW


def test_mark_ready_requires_operator():
    db = FakeDB([_row("pending")])
    with pytest.raises(ap.OperatorActionRequiredError):
        ap.transition(RTX_PROPOSAL["id"], ap.STATE_READY, executor=db)


# ── (4) submit: operator flags + audit persistence ───────────────────────────

def test_submit_requires_confirm():
    db = FakeDB([_row(ap.STATE_READY)])
    with pytest.raises(ap.OperatorActionRequiredError, match="confirm"):
        ap.submit_ready_proposal(RTX_PROPOSAL["id"], confirm=False,
                                 executor=db, client=_client())
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == ap.STATE_READY


def test_submit_requires_ready_state():
    for st in ("pending", "approved", ap.STATE_SUBMITTED, ap.STATE_FILLED):
        db = FakeDB([_row(st)])
        with pytest.raises(ap.IllegalTransitionError):
            ap.submit_ready_proposal(RTX_PROPOSAL["id"], confirm=True,
                                     executor=db, client=_client())


def test_dry_run_zero_http_zero_writes():
    db = FakeDB([_row(ap.STATE_READY)])
    http = FakeHTTP()
    res = ap.submit_ready_proposal(RTX_PROPOSAL["id"], dry_run=True, executor=db)
    assert res["ok"] and res["dry_run"] and res["would_submit"]
    assert res["payload"]["symbol"] == OCC
    assert res["payload"]["type"] == "limit" and res["payload"]["qty"] == "1"
    assert http.calls == []  # no client even constructed
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == ap.STATE_READY
    assert not any(c["sql"].startswith("UPDATE") for c in db.calls)


def test_submit_persists_request_response_readback():
    pid = RTX_PROPOSAL["id"]
    db = FakeDB([_row(ap.STATE_READY)])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("POST", f"{base}/v2/orders"): FakeResponse(
            {"id": "ord-42", "status": "accepted", "symbol": OCC}),
        ("GET", f"{base}/v2/orders/ord-42"): FakeResponse(
            {"id": "ord-42", "status": "new", "symbol": OCC}),
    })
    res = ap.submit_ready_proposal(pid, confirm=True, executor=db,
                                   client=_client(http))
    assert res["ok"] and res["order_id"] == "ord-42"
    row = db.rows[pid]
    assert row["status"] == ap.STATE_SUBMITTED
    aj = row["meta"]["alpaca_json"]
    assert aj["request"]["symbol"] == OCC and aj["request"]["type"] == "limit"
    assert aj["request"]["qty"] == "1"
    assert aj["response"]["id"] == "ord-42"
    assert aj["readback"]["status"] == "new"       # GET-after-submit read-back
    assert aj["submitted_at"]
    # exactly one POST and one GET happened
    assert [m for m, _, _ in http.calls] == ["POST", "GET"]


def test_submit_http_failure_leaves_ready_and_persists_attempt():
    pid = RTX_PROPOSAL["id"]
    db = FakeDB([_row(ap.STATE_READY)])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({("POST", f"{base}/v2/orders"): FakeResponse({"msg": "boom"}, 500)})
    res = ap.submit_ready_proposal(pid, confirm=True, executor=db, client=_client(http))
    assert res["ok"] is False
    row = db.rows[pid]
    assert row["status"] == ap.STATE_READY
    assert row["meta"]["alpaca_submit_error"]["request"]["symbol"] == OCC


# ── (5) CLI operator-flag enforcement ────────────────────────────────────────

def test_cli_submit_without_proposal_id_refused(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    called = []
    monkeypatch.setattr(ap, "submit_ready_proposal",
                        lambda *a, **k: called.append(1))
    assert cli.main(["--submit", "--confirm"]) == 2
    assert not called
    assert "REFUSED" in capsys.readouterr().out


def test_cli_submit_without_confirm_refused(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    called = []
    monkeypatch.setattr(ap, "submit_ready_proposal",
                        lambda *a, **k: called.append(1))
    assert cli.main(["--submit", "--proposal-id", "x"]) == 2
    assert not called
    assert "REFUSED" in capsys.readouterr().out


def test_cli_submit_dry_run_builds_payload_only(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    seen = {}

    def fake_submit(pid, *, confirm=False, dry_run=False, **kw):
        seen.update(pid=pid, confirm=confirm, dry_run=dry_run)
        return {"ok": True, "dry_run": True, "payload": {"type": "limit"}}

    monkeypatch.setattr(ap, "submit_ready_proposal", fake_submit)
    assert cli.main(["--submit", "--proposal-id", "x", "--dry-run"]) == 0
    assert seen == {"pid": "x", "confirm": False, "dry_run": True}


def test_cli_requires_exactly_one_action(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    assert cli.main([]) == 2
    assert cli.main(["--status", "--reconcile"]) == 2


# ── (6) reconcile: fills, rejects, close → outcome → record_outcome ──────────

def _submitted_row(status=None):
    meta = {"alpaca_json": {
        "request": ap.build_order_request(occ_symbol=OCC, limit_price=40.62,
                                          client_order_id="aopt_t"),
        "response": {"id": "ord-42", "status": "accepted"},
        "readback": {"id": "ord-42", "status": "new"},
        "submitted_at": "2026-07-06T14:00:00+00:00"}}
    return _row(status or ap.STATE_SUBMITTED, meta=meta)


def test_reconcile_dry_run_zero_http():
    db = FakeDB([_submitted_row()])
    res = ap.reconcile_fills(executor=db, dry_run=True)
    assert res["ok"] and res["dry_run"]
    assert res["would_poll"] == [{"proposal_id": RTX_PROPOSAL["id"],
                                  "status": ap.STATE_SUBMITTED}]
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == ap.STATE_SUBMITTED


def test_reconcile_fill_transition():
    db = FakeDB([_submitted_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({("GET", f"{base}/v2/orders/ord-42"): FakeResponse(
        {"id": "ord-42", "status": "filled", "filled_avg_price": "40.10",
         "filled_qty": "1", "filled_at": "2026-07-06T14:31:00Z"})})
    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=lambda *a, **k: {"ok": True})
    row = db.rows[RTX_PROPOSAL["id"]]
    assert row["status"] == ap.STATE_FILLED
    assert row["meta"]["alpaca_json"]["fill"]["price"] == 40.10
    assert res["transitions"][0]["to"] == ap.STATE_FILLED


def test_reconcile_reject_transition():
    db = FakeDB([_submitted_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({("GET", f"{base}/v2/orders/ord-42"): FakeResponse(
        {"id": "ord-42", "status": "rejected", "reject_reason": "insufficient buying power"})})
    ap.reconcile_fills(executor=db, client=_client(http),
                       record_outcome_fn=lambda *a, **k: {"ok": True})
    row = db.rows[RTX_PROPOSAL["id"]]
    assert row["status"] == ap.STATE_REJECTED
    assert row["meta"]["alpaca_json"]["reject"]["reason"] == "insufficient buying power"


def test_reconcile_close_records_outcome():
    pid = RTX_PROPOSAL["id"]
    row = _submitted_row(ap.STATE_FILLED)
    row["meta"]["alpaca_json"]["fill"] = {"price": 40.10, "qty": "1",
                                          "filled_at": "2026-07-06T14:31:00Z"}
    db = FakeDB([row])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{OCC}"): FakeResponse({}, 404),  # gone → closed
        ("GET", f"{base}/v2/orders"): FakeResponse([
            {"id": "ord-77", "side": "sell", "status": "filled",
             "filled_avg_price": "43.85", "filled_at": "2026-07-20T15:00:00Z"}]),
    })
    recorded = {}

    def fake_record(pid_, **kw):
        recorded.update(proposal_id=pid_, **kw)
        return {"ok": True}

    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=fake_record)
    assert db.rows[pid]["status"] == ap.STATE_OUTCOME
    # premium-diff math: (43.85 - 40.10) × 100 × 1 = 375.00
    assert recorded["pnl"] == 375.0
    assert recorded["entry_debit"] == 4010.0 and recorded["exit_value"] == 4385.0
    assert recorded["outcome"] == "win"
    assert recorded["proposal_id"] == pid
    assert recorded["strategy_id"] == "deep_itm_call"
    close = db.rows[pid]["meta"]["alpaca_json"]["close"]
    assert close["pnl"] == 375.0 and close["exit_price"] == 43.85
    tos = [t["to"] for t in res["transitions"]]
    assert tos == [ap.STATE_CLOSED, ap.STATE_OUTCOME]


def test_reconcile_position_still_open_no_change():
    row = _submitted_row(ap.STATE_FILLED)
    row["meta"]["alpaca_json"]["fill"] = {"price": 40.10}
    db = FakeDB([row])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({("GET", f"{base}/v2/positions/{OCC}"): FakeResponse(
        {"symbol": OCC, "qty": "1"})})
    ap.reconcile_fills(executor=db, client=_client(http),
                       record_outcome_fn=lambda *a, **k: {"ok": True})
    assert db.rows[RTX_PROPOSAL["id"]]["status"] == ap.STATE_FILLED


def test_reconcile_record_failure_stays_closed_then_retries():
    pid = RTX_PROPOSAL["id"]
    row = _submitted_row(ap.STATE_FILLED)
    row["meta"]["alpaca_json"]["fill"] = {"price": 40.10, "filled_at": "2026-07-06T14:31:00Z"}
    db = FakeDB([row])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{OCC}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/orders"): FakeResponse([
            {"id": "ord-77", "side": "sell", "status": "filled",
             "filled_avg_price": "39.00", "filled_at": "2026-07-20T15:00:00Z"}]),
    })
    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=lambda *a, **k: {"ok": False,
                                                                "error": "db down"})
    assert db.rows[pid]["status"] == ap.STATE_CLOSED   # honest: NOT outcome-recorded
    assert any("record_outcome failed" in w for w in res["warnings"])
    # next run retries the CLOSED row without HTTP and records a LOSS
    recorded = {}

    def ok_record(pid_, **kw):
        recorded.update(proposal_id=pid_, **kw)
        return {"ok": True}

    res2 = ap.reconcile_fills(executor=db, client=_client(FakeHTTP()),
                              record_outcome_fn=ok_record)
    assert db.rows[pid]["status"] == ap.STATE_OUTCOME
    assert recorded["outcome"] == "loss" and recorded["pnl"] == -110.0


def test_reconcile_scratch_band():
    assert ap._outcome_from_pnl(0.5) == "scratch"
    assert ap._outcome_from_pnl(-0.5) == "scratch"
    assert ap._outcome_from_pnl(2.0) == "win"
    assert ap._outcome_from_pnl(-2.0) == "loss"


# ── (7) isolation invariants (source inspection) ─────────────────────────────

LANE_SOURCES = [
    ROOT / "scripts" / "lib" / "options_pipeline" / "alpaca_paper.py",
    ROOT / "scripts" / "alpaca_paper_options_executor.py",
]

FORBIDDEN = re.compile(
    r"schwab|fidelity|snaptrade|tastytrade|\boco\b|stop_manager|protective_stop|"
    r"two_factor|totp|second[_-]factor|telegram",
    re.IGNORECASE)


def test_no_forbidden_broker_or_stop_machinery():
    for path in LANE_SOURCES:
        src = path.read_text(encoding="utf-8")
        hits = FORBIDDEN.findall(src)
        assert not hits, f"{path.name} references forbidden machinery: {hits}"


def test_no_desk_review_mutation():
    for path in LANE_SOURCES:
        src = path.read_text(encoding="utf-8")
        assert "resolve_approval" not in src
        assert "sync_approval_queue" not in src
        assert "options_desk_enterprise" not in src
        # never writes legacy review statuses
        assert "status='approved'" not in src and 'status="approved"' not in src
    # runtime check too: legacy statuses are not legal targets
    assert not set(ap.LEGAL_TRANSITIONS) & {"pending", "blocked", "approved",
                                            "rejected", "executed"}


def test_scanner_and_generator_never_import_this_lane():
    for rel in ("scripts/options_strategy_scanner.py",
                "scripts/lib/options_pipeline/deep_itm_generator.py",
                "scripts/lib/options_pipeline/__init__.py",
                "scripts/options_engine.py"):
        p = ROOT / rel
        if p.exists():
            src = p.read_text(encoding="utf-8")
            assert "alpaca_paper" not in src, f"{rel} must not touch the submit lane"
            assert "alpaca_paper_options_executor" not in src


def test_no_default_base_url_anywhere_in_lane():
    """The paper URL must come from env — no hardcoded fallback submit target."""
    src = LANE_SOURCES[0].read_text(encoding="utf-8")
    assert re.search(r'ALPACA_PAPER_BASE_URL.{0,20}\bor\s*["\']https', src) is None
    with pytest.raises(ap.PaperEndpointError):
        ap.resolve_paper_base_url({})  # empty env → no URL is ever assumed


# ── (8) migration shape ──────────────────────────────────────────────────────

MIGRATION = ROOT / "migrations" / "2026_07_06_options_queue_alpaca_states.sql"


def test_migration_additive_and_complete():
    sql = MIGRATION.read_text(encoding="utf-8")
    for st in ap.ALPACA_STATES:
        assert f"'{st}'" in sql, f"missing state {st}"
    for legacy in ("'pending'", "'blocked'", "'approved'", "'rejected'", "'executed'"):
        assert legacy in sql, f"legacy status {legacy} must stay legal"
    assert "ADD COLUMN IF NOT EXISTS meta" in sql
    up = sql.upper()
    assert "DROP TABLE" not in up and "DROP COLUMN" not in up
    assert "DELETE FROM" not in up and "TRUNCATE" not in up
    assert "trg_oaq_protect_alpaca_states" in sql  # sync-clobber guard rail
