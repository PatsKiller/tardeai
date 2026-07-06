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
    # The registry FLAG NAME 'alpaca_paper_enabled' may appear as metadata
    # (the scanner surfaces it on desk cards since PR #124) — what must never
    # appear is an import of the submit lane or a call into its submit paths.
    lane_import = re.compile(
        r"(?:from\s+\S*options_pipeline\S*\s+import\s+[^\n]*\balpaca_paper\b"
        r"|from\s+\S*\balpaca_paper\b\S*\s+import"
        r"|import\s+[^\n]*\balpaca_paper\b"
        r"|alpaca_paper_options_executor"
        r"|submit_ready_proposal|submit_spread_paper_order|submit_option_)")
    for rel in ("scripts/options_strategy_scanner.py",
                "scripts/lib/options_pipeline/deep_itm_generator.py",
                "scripts/lib/options_pipeline/atm_long_premium_generator.py",
                "scripts/lib/options_pipeline/__init__.py",
                "scripts/options_engine.py"):
        p = ROOT / rel
        if p.exists():
            src = p.read_text(encoding="utf-8")
            hit = lane_import.search(src)
            assert hit is None, (
                f"{rel} must not touch the submit lane (found {hit.group(0)!r})")


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


# ═══ (9) EARNINGS-SPREADS Stage 1b (Part G) — guarded multi-leg lane ═════════

LONG_OCC = "NVDA260821C00190000"
SHORT_OCC = "NVDA260821C00195000"

SPREAD_PROPOSAL = {
    "id": "opt_earnings_vertical_debit_call_NVDA_190_195_20260821",
    "strategy": "earnings_vertical_debit_call",
    "symbol": "NVDA",
    "underlying": "NVDA",
    "net_debit": 1.50,
    "spreads": 1,
    "legs": [
        {"underlying": "NVDA", "expiration": "2026-08-21", "strike": 190.0,
         "option_type": "call", "side": "buy"},
        {"underlying": "NVDA", "expiration": "2026-08-21", "strike": 195.0,
         "option_type": "call", "side": "sell"},
    ],
}

SPREAD_PID = SPREAD_PROPOSAL["id"]
SPREAD_META = {"strategy_json": {"family": "earnings_vertical_debit",
                                 "strategy_id": "earnings_vertical_debit_call"}}


def _spread_reg(enabled=True, proven=True, sid="earnings_vertical_debit_call"):
    return {"strategies": {sid: {"alpaca_paper_enabled": enabled,
                                 "multi_leg_proven": proven}}}


def _spread_row(status=ap.STATE_READY, proposal=None, meta=None):
    return _row(status, proposal=proposal or SPREAD_PROPOSAL,
                meta=copy.deepcopy(meta if meta is not None else SPREAD_META))


# ── (9a) guard matrix: family / registry-enabled / multi_leg_proven ──────────

def test_spread_refused_non_earnings_family():
    db = FakeDB([_spread_row(meta={"strategy_json":
                                   {"family": "directional_long_premium"}})])
    with pytest.raises(ap.SpreadNotEnabledError, match="earnings_vertical"):
        ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                     registry=_spread_reg())
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_READY


def test_spread_refused_missing_family_even_dry_run():
    for kwargs in ({"confirm": True}, {"dry_run": True}):
        db = FakeDB([_spread_row(meta={})])
        with pytest.raises(ap.SpreadNotEnabledError):
            ap.submit_spread_paper_order(SPREAD_PID, executor=db,
                                         registry=_spread_reg(), **kwargs)


def test_spread_refused_without_registry_entry():
    db = FakeDB([_spread_row()])
    with pytest.raises(ap.SpreadNotEnabledError, match="no registry entry"):
        ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                     registry={"strategies": {}})


def test_spread_refused_without_alpaca_paper_enabled():
    db = FakeDB([_spread_row()])
    with pytest.raises(ap.SpreadNotEnabledError, match="alpaca_paper_enabled"):
        ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                     registry=_spread_reg(enabled=False))
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_READY


def test_spread_refused_without_multi_leg_proven():
    # explicit false AND absent-entirely both refuse — absent == false
    for reg in (_spread_reg(proven=False),
                {"strategies": {"earnings_vertical_debit_call":
                                {"alpaca_paper_enabled": True}}}):
        db = FakeDB([_spread_row()])
        with pytest.raises(ap.SpreadNotEnabledError, match="multi_leg_proven"):
            ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                         registry=reg)
        assert db.rows[SPREAD_PID]["status"] == ap.STATE_READY


def test_spread_default_registry_refuses_today():
    """With the REAL config/options_strategy_registry.yaml (registry=None):
    no entry carries multi_leg_proven, so nothing can submit today."""
    db = FakeDB([_spread_row()])
    with pytest.raises(ap.SpreadNotEnabledError):
        ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db)
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_READY


# ── (9b) credit family: refused UNCONDITIONALLY ──────────────────────────────

def test_credit_family_always_refused():
    credit_meta = {"strategy_json": {"family": "earnings_vertical_credit"}}
    reg = _spread_reg(sid="earnings_vertical_credit_put")  # flags fully true
    for kwargs in ({"confirm": True}, {"dry_run": True},
                   {"confirm": True, "dry_run": False}):
        p = {**copy.deepcopy(SPREAD_PROPOSAL),
             "strategy": "earnings_vertical_credit_put"}
        db = FakeDB([_spread_row(proposal=p, meta=credit_meta)])
        with pytest.raises(ap.SpreadNotEnabledError,
                           match="credit spreads blocked until "
                                 "assignment/reconciliation proven"):
            ap.submit_spread_paper_order(SPREAD_PID, executor=db,
                                         registry=reg, **kwargs)
        assert db.rows[SPREAD_PID]["status"] == ap.STATE_READY


def test_credit_subfamily_prefix_also_refused():
    meta = {"strategy_json": {"family": "earnings_vertical_credit_put_spread"}}
    db = FakeDB([_spread_row(meta=meta)])
    with pytest.raises(ap.SpreadNotEnabledError, match="credit spreads blocked"):
        ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                     registry=_spread_reg())


# ── (9c) mleg payload shape + spread order policy ────────────────────────────

def test_mleg_payload_shape():
    p = ap.build_spread_order_payload(_spread_row())
    assert p["order_class"] == "mleg"
    assert p["type"] == "limit" and p["qty"] == "1"
    assert p["time_in_force"] == "day"
    assert p["limit_price"] == "1.50"           # net DEBIT limit
    assert len(p["legs"]) == 2
    buy, sell = p["legs"]
    assert buy == {"symbol": LONG_OCC, "ratio_qty": "1", "side": "buy",
                   "position_intent": "buy_to_open"}
    assert sell == {"symbol": SHORT_OCC, "ratio_qty": "1", "side": "sell",
                    "position_intent": "sell_to_open"}
    assert p["client_order_id"].startswith("aspr_")


def test_spread_no_market_orders():
    for t in ("market", "stop", "stop_limit", "", None):
        with pytest.raises(ap.OrderPolicyError, match="LIMIT"):
            ap.build_spread_order_request(legs=SPREAD_PROPOSAL["legs"],
                                          net_debit_limit=1.50, order_type=t)
    with pytest.raises(ap.OrderPolicyError, match="day"):
        ap.build_spread_order_request(legs=SPREAD_PROPOSAL["legs"],
                                      net_debit_limit=1.50, time_in_force="gtc")


def test_spread_exactly_two_legs_ratio_one():
    legs = copy.deepcopy(SPREAD_PROPOSAL["legs"])
    with pytest.raises(ap.OrderPolicyError, match="exactly 2 legs"):
        ap.build_spread_order_request(legs=legs + [legs[0]], net_debit_limit=1.5)
    with pytest.raises(ap.OrderPolicyError, match="exactly 2 legs"):
        ap.build_spread_order_request(legs=legs[:1], net_debit_limit=1.5)
    ratio2 = copy.deepcopy(legs)
    ratio2[0]["ratio_qty"] = 2
    with pytest.raises(ap.OrderPolicyError, match="ONE spread max"):
        ap.build_spread_order_request(legs=ratio2, net_debit_limit=1.5)
    two_buys = copy.deepcopy(legs)
    two_buys[1]["side"] = "buy"
    with pytest.raises(ap.OrderPolicyError, match="one buy leg and one sell"):
        ap.build_spread_order_request(legs=two_buys, net_debit_limit=1.5)


def test_spread_one_spread_cap_from_proposal():
    for extra in ({"spreads": 2}, {"spreads": 0}, {"contracts": 3, "spreads": 3}):
        row = _spread_row(proposal={**copy.deepcopy(SPREAD_PROPOSAL), **extra})
        with pytest.raises(ap.OrderPolicyError, match="ONE spread"):
            ap.build_spread_order_payload(row)


def test_spread_net_debit_required_and_positive():
    for bad in (0, -1.5):
        with pytest.raises(ap.OrderPolicyError, match="credit structure|sane range"):
            ap.build_spread_order_request(legs=SPREAD_PROPOSAL["legs"],
                                          net_debit_limit=bad)
    row = _spread_row(proposal={k: v for k, v in SPREAD_PROPOSAL.items()
                                if k != "net_debit"})
    with pytest.raises(ap.OrderPolicyError, match="net_debit"):
        ap.build_spread_order_payload(row)


def test_spread_debit_vertical_shape_enforced():
    def leg(strike, side, ot="call", exp="2026-08-21", under="NVDA"):
        return {"underlying": under, "expiration": exp, "strike": strike,
                "option_type": ot, "side": side}
    # call debit must be long-low/short-high; the inverse is a credit shape
    with pytest.raises(ap.OrderPolicyError, match="CREDIT structure"):
        ap.build_spread_order_request(legs=[leg(195.0, "buy"), leg(190.0, "sell")],
                                      net_debit_limit=1.5)
    # put debit must be long-high/short-low
    with pytest.raises(ap.OrderPolicyError, match="CREDIT structure"):
        ap.build_spread_order_request(
            legs=[leg(190.0, "buy", "put"), leg(195.0, "sell", "put")],
            net_debit_limit=1.5)
    with pytest.raises(ap.OrderPolicyError, match="different strikes"):
        ap.build_spread_order_request(legs=[leg(190.0, "buy"), leg(190.0, "sell")],
                                      net_debit_limit=1.5)
    with pytest.raises(ap.OrderPolicyError, match="one expiration"):
        ap.build_spread_order_request(
            legs=[leg(190.0, "buy"), leg(195.0, "sell", exp="2026-09-18")],
            net_debit_limit=1.5)
    with pytest.raises(ap.OrderPolicyError, match="one option type"):
        ap.build_spread_order_request(
            legs=[leg(190.0, "buy"), leg(195.0, "sell", ot="put")],
            net_debit_limit=1.5)
    with pytest.raises(ap.OrderPolicyError, match="one underlying"):
        ap.build_spread_order_request(
            legs=[leg(190.0, "buy"), leg(195.0, "sell", under="AMD")],
            net_debit_limit=1.5)
    # a correct put debit vertical builds fine
    p = ap.build_spread_order_request(
        legs=[leg(195.0, "buy", "put"), leg(190.0, "sell", "put")],
        net_debit_limit=2.10)
    assert p["limit_price"] == "2.10" and p["legs"][0]["side"] == "buy"


# ── (9d) endpoint locks hold for the spread path ─────────────────────────────

def test_spread_endpoint_lock_reused():
    for url in ("https://api.alpaca.markets",
                "https://paper-api.alpaca.markets.evil.com"):
        db = FakeDB([_spread_row()])
        env = {**PAPER_ENV, "ALPACA_PAPER_BASE_URL": url}
        with pytest.raises(ap.PaperEndpointError):
            ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                         env=env, registry=_spread_reg())
        assert db.rows[SPREAD_PID]["status"] == ap.STATE_READY
    # live-indicating env name refuses too
    db = FakeDB([_spread_row()])
    with pytest.raises(ap.PaperEndpointError, match="live-indicating"):
        ap.submit_spread_paper_order(
            SPREAD_PID, confirm=True, executor=db,
            env={**PAPER_ENV, "ALPACA_LIVE_API_KEY": "x"}, registry=_spread_reg())


# ── (9e) spread submit: confirm/state/persistence per leg ────────────────────

def test_spread_submit_requires_confirm():
    db = FakeDB([_spread_row()])
    with pytest.raises(ap.OperatorActionRequiredError, match="confirm"):
        ap.submit_spread_paper_order(SPREAD_PID, confirm=False, executor=db,
                                     client=_client(), registry=_spread_reg())
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_READY


def test_spread_submit_requires_ready_state():
    for st in ("pending", "approved", ap.STATE_SUBMITTED, ap.STATE_FILLED):
        db = FakeDB([_spread_row(st)])
        with pytest.raises(ap.IllegalTransitionError):
            ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                         client=_client(), registry=_spread_reg())


def test_spread_dry_run_zero_http_zero_writes_reports_flags():
    db = FakeDB([_spread_row()])
    res = ap.submit_spread_paper_order(SPREAD_PID, dry_run=True, executor=db,
                                       registry=_spread_reg(proven=False))
    assert res["ok"] and res["dry_run"]
    assert res["payload"]["order_class"] == "mleg"
    assert res["payload"]["limit_price"] == "1.50"
    assert res["guards"]["multi_leg_proven"] is False
    assert res["would_submit"] is False        # unproven → could not really submit
    assert res["http"].startswith("none")
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_READY
    assert not any(c["sql"].startswith("UPDATE") for c in db.calls)
    # both flags true + READY → would_submit flips true, still zero HTTP/writes
    res2 = ap.submit_spread_paper_order(SPREAD_PID, dry_run=True, executor=db,
                                        registry=_spread_reg())
    assert res2["would_submit"] is True
    assert not any(c["sql"].startswith("UPDATE") for c in db.calls)


def _spread_http(post_resp=None, readback=None):
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    resp_legs = [{"id": "leg-1", "symbol": LONG_OCC, "side": "buy",
                  "ratio_qty": "1", "status": "accepted"},
                 {"id": "leg-2", "symbol": SHORT_OCC, "side": "sell",
                  "ratio_qty": "1", "status": "accepted"}]
    post = post_resp or FakeResponse({"id": "spr-42", "status": "accepted",
                                      "order_class": "mleg", "legs": resp_legs})
    rb = readback or FakeResponse({"id": "spr-42", "status": "new",
                                   "order_class": "mleg", "legs": resp_legs})
    return FakeHTTP({("POST", f"{base}/v2/orders"): post,
                     ("GET", f"{base}/v2/orders/spr-42"): rb})


def test_spread_submit_persists_every_leg():
    db = FakeDB([_spread_row()])
    http = _spread_http()
    res = ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                       client=_client(http),
                                       registry=_spread_reg())
    assert res["ok"] and res["order_id"] == "spr-42" and res["spread"] is True
    row = db.rows[SPREAD_PID]
    assert row["status"] == ap.STATE_SUBMITTED
    aj = row["meta"]["alpaca_json"]
    assert aj["spread"] is True and aj["submitted_at"]
    assert aj["request"]["order_class"] == "mleg"
    assert aj["response"]["id"] == "spr-42"
    assert aj["readback"]["status"] == "new"
    assert len(aj["legs"]) == 2                       # EVERY leg detailed
    for leg, occ, strike in zip(aj["legs"], (LONG_OCC, SHORT_OCC), (190.0, 195.0)):
        assert leg["symbol"] == occ and leg["ratio_qty"] == "1"
        assert leg["strike"] == strike and leg["expiration"] == "2026-08-21"
        assert leg["option_type"] == "call"
        assert leg["response_leg"]["symbol"] == occ   # broker echo per leg
    assert [(e["symbol"], e["event"]) for e in aj["leg_events"]] == [
        (LONG_OCC, "submitted"), (SHORT_OCC, "submitted")]
    # exactly one POST (mleg body) and one read-back GET
    assert [m for m, _, _ in http.calls] == ["POST", "GET"]
    assert http.calls[0][2]["order_class"] == "mleg"
    assert len(http.calls[0][2]["legs"]) == 2


def test_spread_submit_http_failure_leaves_ready_and_persists_attempt():
    db = FakeDB([_spread_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({("POST", f"{base}/v2/orders"): FakeResponse({"m": "boom"}, 500)})
    res = ap.submit_spread_paper_order(SPREAD_PID, confirm=True, executor=db,
                                       client=_client(http), registry=_spread_reg())
    assert res["ok"] is False
    row = db.rows[SPREAD_PID]
    assert row["status"] == ap.STATE_READY
    err = row["meta"]["alpaca_submit_error"]
    assert err["spread"] is True
    assert err["request"]["order_class"] == "mleg"


# ── (9f) CLI: --submit-spread flag gating ────────────────────────────────────

def test_cli_submit_spread_without_proposal_id_refused(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    called = []
    monkeypatch.setattr(ap, "submit_spread_paper_order",
                        lambda *a, **k: called.append(1))
    assert cli.main(["--submit-spread", "--confirm"]) == 2
    assert not called
    assert "REFUSED" in capsys.readouterr().out


def test_cli_submit_spread_without_confirm_refused(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    called = []
    monkeypatch.setattr(ap, "submit_spread_paper_order",
                        lambda *a, **k: called.append(1))
    assert cli.main(["--submit-spread", "--proposal-id", "x"]) == 2
    assert not called
    assert "REFUSED" in capsys.readouterr().out


def test_cli_submit_spread_dry_run_and_confirm_paths(monkeypatch):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    seen = {}

    def fake(pid, *, confirm=False, dry_run=False, **kw):
        seen.update(pid=pid, confirm=confirm, dry_run=dry_run)
        return {"ok": True, "payload": {"order_class": "mleg"}}

    monkeypatch.setattr(ap, "submit_spread_paper_order", fake)
    assert cli.main(["--submit-spread", "--proposal-id", "x", "--dry-run"]) == 0
    assert seen == {"pid": "x", "confirm": False, "dry_run": True}
    assert cli.main(["--submit-spread", "--proposal-id", "x", "--confirm"]) == 0
    assert seen == {"pid": "x", "confirm": True, "dry_run": False}


def test_cli_spread_not_enabled_prints_refused(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_env", lambda: None)

    def raise_blocked(*a, **k):
        raise ap.SpreadNotEnabledError(
            "credit spreads blocked until assignment/reconciliation proven")

    monkeypatch.setattr(ap, "submit_spread_paper_order", raise_blocked)
    assert cli.main(["--submit-spread", "--proposal-id", "x", "--confirm"]) == 1
    assert "REFUSED: credit spreads blocked" in capsys.readouterr().out


def test_cli_spread_counts_as_action(monkeypatch):
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    assert cli.main(["--submit-spread", "--submit",
                     "--proposal-id", "x", "--confirm"]) == 2


# ── (9g) reconcile: multi-leg fills aggregate to ONE outcome ─────────────────

def _spread_submitted_row(status=None):
    request = ap.build_spread_order_request(
        legs=SPREAD_PROPOSAL["legs"], net_debit_limit=1.50,
        client_order_id="aspr_t")
    meta = {**copy.deepcopy(SPREAD_META),
            "alpaca_json": {"request": request,
                            "response": {"id": "spr-42", "status": "accepted"},
                            "readback": {"id": "spr-42", "status": "new"},
                            "submitted_at": "2026-07-06T14:00:00+00:00",
                            "spread": True, "leg_events": []}}
    return _row(status or ap.STATE_SUBMITTED, proposal=SPREAD_PROPOSAL, meta=meta)


def test_reconcile_spread_fill_aggregates_net_debit():
    db = FakeDB([_spread_submitted_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({("GET", f"{base}/v2/orders/spr-42"): FakeResponse(
        {"id": "spr-42", "status": "filled", "order_class": "mleg",
         "filled_at": "2026-07-06T14:31:00Z",
         "legs": [{"symbol": LONG_OCC, "side": "buy", "filled_avg_price": "5.10"},
                  {"symbol": SHORT_OCC, "side": "sell", "filled_avg_price": "3.60"}]})})
    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=lambda *a, **k: {"ok": True})
    row = db.rows[SPREAD_PID]
    assert row["status"] == ap.STATE_FILLED
    # 5.10 paid − 3.60 received = 1.50 net debit — ONE aggregated entry
    assert row["meta"]["alpaca_json"]["fill"]["net_debit"] == 1.5
    assert [(e["symbol"], e["event"])
            for e in row["meta"]["alpaca_json"]["leg_events"]] == [
        (LONG_OCC, "filled"), (SHORT_OCC, "filled")]
    t = res["transitions"][0]
    assert t["to"] == ap.STATE_FILLED and t["spread"] is True


def test_reconcile_spread_reject_uses_existing_path():
    db = FakeDB([_spread_submitted_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({("GET", f"{base}/v2/orders/spr-42"): FakeResponse(
        {"id": "spr-42", "status": "rejected", "reject_reason": "oi too low"})})
    ap.reconcile_fills(executor=db, client=_client(http),
                       record_outcome_fn=lambda *a, **k: {"ok": True})
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_REJECTED


def _spread_filled_row():
    row = _spread_submitted_row(ap.STATE_FILLED)
    row["meta"]["alpaca_json"]["fill"] = {"net_debit": 1.50,
                                          "filled_at": "2026-07-06T14:31:00Z"}
    return row


def test_reconcile_spread_close_single_outcome_math():
    db = FakeDB([_spread_filled_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    close_order = {"id": "spr-77", "status": "filled", "order_class": "mleg",
                   "filled_at": "2026-08-10T15:00:00Z",
                   "legs": [{"symbol": LONG_OCC, "side": "sell",
                             "filled_avg_price": "4.80"},
                            {"symbol": SHORT_OCC, "side": "buy",
                             "filled_avg_price": "2.50"}]}
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{LONG_OCC}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/positions/{SHORT_OCC}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/orders"): FakeResponse([close_order]),
    })
    recorded = {}

    def fake_record(pid_, **kw):
        recorded.update(proposal_id=pid_, **kw)
        return {"ok": True}

    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=fake_record)
    # Part G math: debit 1.50 in, 2.30 out → (2.30 − 1.50) × 100 = +$80, ONE outcome
    assert recorded["pnl"] == 80.0
    assert recorded["entry_debit"] == 150.0 and recorded["exit_value"] == 230.0
    assert recorded["outcome"] == "win"
    assert recorded["proposal_id"] == SPREAD_PID
    assert recorded["strategy_id"] == "earnings_vertical_debit_call"
    assert recorded["meta"]["occ_symbol"] == f"{LONG_OCC},{SHORT_OCC}"
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_OUTCOME
    close = db.rows[SPREAD_PID]["meta"]["alpaca_json"]["close"]
    assert close["pnl"] == 80.0 and close["exit_net"] == 2.3
    assert close["entry_debit"] == 150.0 and close["exit_value"] == 230.0
    tos = [t["to"] for t in res["transitions"]]
    assert tos == [ap.STATE_CLOSED, ap.STATE_OUTCOME]


def test_reconcile_spread_both_legs_open_no_change():
    db = FakeDB([_spread_filled_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{LONG_OCC}"): FakeResponse(
            {"symbol": LONG_OCC, "qty": "1"}),
        ("GET", f"{base}/v2/positions/{SHORT_OCC}"): FakeResponse(
            {"symbol": SHORT_OCC, "qty": "-1"}),
    })
    ap.reconcile_fills(executor=db, client=_client(http),
                       record_outcome_fn=lambda *a, **k: {"ok": True})
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_FILLED
    assert "close" not in db.rows[SPREAD_PID]["meta"]["alpaca_json"]


def test_reconcile_spread_gone_no_close_not_expired_warns_only():
    row = _spread_filled_row()
    db = FakeDB([row])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{LONG_OCC}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/positions/{SHORT_OCC}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/orders"): FakeResponse([]),   # no closing fill
    })
    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=lambda *a, **k: {"ok": True})
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_FILLED   # honest: no outcome
    assert any("operator investigation" in w for w in res["warnings"])


# ── (9h) expiry / exercise / assignment poll ─────────────────────────────────

EXP_LONG = "NVDA260619C00190000"    # expired 2026-06-19 (before today)
EXP_SHORT = "NVDA260619C00195000"


def _expired_spread_row():
    legs = [{"underlying": "NVDA", "expiration": "2026-06-19", "strike": 190.0,
             "option_type": "call", "side": "buy"},
            {"underlying": "NVDA", "expiration": "2026-06-19", "strike": 195.0,
             "option_type": "call", "side": "sell"}]
    request = ap.build_spread_order_request(legs=legs, net_debit_limit=1.50)
    meta = {**copy.deepcopy(SPREAD_META),
            "alpaca_json": {"request": request,
                            "response": {"id": "spr-42", "status": "accepted"},
                            "submitted_at": "2026-06-01T14:00:00+00:00",
                            "spread": True, "leg_events": [],
                            "fill": {"net_debit": 1.50,
                                     "filled_at": "2026-06-01T14:31:00Z"}}}
    p = {**copy.deepcopy(SPREAD_PROPOSAL), "legs": legs}
    return _row(ap.STATE_FILLED, proposal=p, meta=meta)


def test_reconcile_spread_postexpiry_assignment_detected():
    db = FakeDB([_expired_spread_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{EXP_LONG}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/positions/{EXP_SHORT}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/orders"): FakeResponse([]),
        ("GET", f"{base}/v2/positions/NVDA"): FakeResponse(
            {"symbol": "NVDA", "qty": "100"}),          # residual stock!
    })
    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=lambda *a, **k: {"ok": True})
    row = db.rows[SPREAD_PID]
    assert row["status"] == ap.STATE_FILLED             # honest: NOT auto-closed
    a = row["meta"]["alpaca_json"]["assignment"]
    assert a["underlying"] == "NVDA"
    assert a["stock_position"]["qty"] == "100"
    assert "NOT auto-recorded" in a["risk_note"]
    assert any("RISK" in w for w in res["warnings"])
    # idempotent: second pass warns, does not rewrite
    res2 = ap.reconcile_fills(executor=db, client=_client(http),
                              record_outcome_fn=lambda *a, **k: {"ok": True})
    assert any("already flagged" in w for w in res2["warnings"])
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_FILLED


def test_reconcile_spread_postexpiry_unknown_disposition():
    db = FakeDB([_expired_spread_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{EXP_LONG}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/positions/{EXP_SHORT}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/orders"): FakeResponse([]),
        ("GET", f"{base}/v2/positions/NVDA"): FakeResponse({}, 404),  # no stock
    })
    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=lambda *a, **k: {"ok": True})
    row = db.rows[SPREAD_PID]
    assert row["status"] == ap.STATE_FILLED             # no outcome invented
    ec = row["meta"]["alpaca_json"]["expiry_check"]
    assert ec["disposition"] == "unknown"
    assert "NOT auto-recorded" in ec["note"]
    assert any("UNKNOWN" in w for w in res["warnings"])


def test_reconcile_spread_partial_leg_flags_early_assignment():
    db = FakeDB([_expired_spread_row()])
    base = PAPER_ENV["ALPACA_PAPER_BASE_URL"]
    http = FakeHTTP({
        ("GET", f"{base}/v2/positions/{EXP_LONG}"): FakeResponse(
            {"symbol": EXP_LONG, "qty": "1"}),           # long survives
        ("GET", f"{base}/v2/positions/{EXP_SHORT}"): FakeResponse({}, 404),
        ("GET", f"{base}/v2/positions/NVDA"): FakeResponse(
            {"symbol": "NVDA", "qty": "-100"}),          # short stock from assignment
    })
    res = ap.reconcile_fills(executor=db, client=_client(http),
                             record_outcome_fn=lambda *a, **k: {"ok": True})
    row = db.rows[SPREAD_PID]
    assert row["status"] == ap.STATE_FILLED
    a = row["meta"]["alpaca_json"]["assignment"]
    assert "early exercise/assignment" in a["risk_note"]
    assert a["stock_position"]["qty"] == "-100"
    assert any("RISK" in w for w in res["warnings"])


def test_reconcile_dry_run_lists_spread_rows_zero_http():
    db = FakeDB([_spread_submitted_row()])
    res = ap.reconcile_fills(executor=db, dry_run=True)
    assert res["would_poll"] == [{"proposal_id": SPREAD_PID,
                                  "status": ap.STATE_SUBMITTED}]
    assert db.rows[SPREAD_PID]["status"] == ap.STATE_SUBMITTED
