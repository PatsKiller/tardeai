"""Options order-authorization contract (reviewer 2026-09-27), built under a per-task
execution-engineering grant. Hermetic: every broker, DB and Telegram touch is faked.

Proves, with negative tests, that after approval a changed leg, account, quantity, limit,
proposal version, quote timestamp or buying power fails closed; that no options order submits
without its exact evidence-bound authorization; and that an absent or stale quote age fails
regardless of the data source named. Positive control: everything valid authorizes once."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")]

from brokers import options_order_pilot as oop  # noqa: E402
from brokers import evidence_approval as ea  # noqa: E402
from brokers.execution_readiness import evaluate_execution_readiness  # noqa: E402
import options_desk_enterprise as ent  # noqa: E402
from test_options_order_gates_20260927 import NOW, GUID, PID, _proposal, _store, _row  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_earnings_calendar(monkeypatch):
    """LP-DEF-04 (live-proof 2026-09-28): a cached ``enterprise.earnings`` verdict without a gate_version is
    no longer trusted at preflight — it is recomputed against the live gate. This suite is hermetic and CI
    has no earnings provider (the recompute returned EARNINGS_TIMESTAMP_UNKNOWN there, run 36452009384), so
    the calendar answers "no scheduled event" for every symbol; a test that needs a blackout sets its own."""
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {str(s).upper(): "" for s in syms})


def _iso(dt):
    return dt.isoformat()


def _prop(**over):
    p = _proposal(**over)
    p.setdefault("options_thesis", {"pin": f"opt_{GUID}@v1", "missing_required": []})
    # Every fixture timestamp is anchored to the fixed test clock NOW (2026-09-28T15:00Z) and the
    # freshness gate is evaluated ON that clock (_clock / _readiness_no_db(now=...)), so the
    # suite is deterministic: it neither goes red when the wall clock passes 15:02Z (PR #1339 CI
    # run 36442022000, "quote stale 1221s > 120s") nor depends on the wall clock at all (the
    # #1340 interim repair stamped the quotes from datetime.now(), which could not exercise a
    # 'stale on the confirm clock' case without sleeping).
    p.setdefault("quotes_as_of", _iso(NOW - timedelta(seconds=30)))
    p.setdefault("chain_fetched_at", _iso(NOW - timedelta(seconds=60)))
    p.setdefault("economics", {"collateral": 2500.0})
    return p


def _intent(p=None, *, bp=50_000.0, bp_age_s=10):
    p = p or _prop()
    return oop.build_intent("rollover", p, held_qty=0, buying_power=bp,
                            buying_power_as_of=_iso(NOW - timedelta(seconds=bp_age_s)) if bp is not None else None, now=NOW)


def _all_open():
    """Every broker-layer lock open and 2FA confirmed, so only the contract's own checks decide."""
    return [
        mock.patch("brokers.execution_readiness._global_live_allowed",
                   return_value={"ok": True, "code": "global_live_allowed", "reason": "ok", "severity": "hard"}),
        mock.patch("brokers.execution_readiness._paper_mode", return_value=False),
        mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])),
        mock.patch("brokers.approval_service.is_fully_approved", return_value=True),
        mock.patch("brokers.execution_readiness._kill_switches_clear",
                   return_value={"ok": True, "code": "kill_switches_clear", "reason": "ok", "severity": "hard"}),
    ]


class _Patches:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()


class _FakeCursor:
    """Answers the policy-arm / write-fence lookups as enabled (like tests/test_execution_readiness.py)."""
    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return (True,)

    def fetchall(self):
        return []


class _FakeConn:
    def cursor(self):
        return _FakeCursor()


def _clock(now):
    """Pin the freshness gate's evaluation clock to the test clock ``now``.

    The gate recomputes quote / chain age from the timestamps on the intent
    (execution_readiness._age_from -> brokers.quote_time.quote_age_seconds(ts, now=None)); with
    ``now`` unset that is the wall clock, so a fixture stamped at the fixed test instant ``NOW``
    (2026-09-28T15:00Z) aged past the 120 s rule the moment the wall clock passed 15:02Z and the
    positive control failed in CI (PR #1339, run 36442022000: "quote stale 1221s > 120s").

    This is clock injection at the test boundary, through the parameter the rule already has:
    the age arithmetic, the 120 s production TTL and the fail-closed branches all still run.
    Nothing here fakes a quote time or bypasses validation."""
    import brokers.quote_time as qt
    real = qt.quote_age_seconds
    return mock.patch.object(qt, "quote_age_seconds", side_effect=lambda raw, now_=None: real(raw, now=now_ or now))


def _readiness_no_db(dct, *, now=None, **kw):
    """Submit-mode readiness with the DB-backed gates (policy arm, write fence, desk queue) and
    the desk hard-risk evaluator stubbed as PASS, so the contract's own freshness / buying-power /
    2FA / kill-switch / LLM gates are what is tested. ``now`` pins the gate's clock (see _clock);
    ``None`` keeps the wall clock for the tests that stamp their fixtures from it."""
    import brokers.execution_readiness as er
    import db_adapter
    patches = _all_open() + [
        mock.patch.object(db_adapter, "_get_conn", return_value=_FakeConn()),
        mock.patch("brokers.options_execution_policy.evaluate", return_value=(True, [])),
        mock.patch.object(ent, "evaluate_hard_risk_blocks", return_value=[]),
        mock.patch.object(ent, "is_desk_queue_approved", return_value=True),
    ] + ([_clock(now)] if now is not None else [])
    with _Patches(patches):
        r = er.evaluate_execution_readiness(dct, **kw)
    return r


# ── freshness recomputed from timestamps; absent fails regardless of source ─────────────────

def test_absent_quote_timestamp_fails_closed_even_with_a_named_source():
    for ev in ({"data_source": "schwab_chain"}, {"data_source": "schwab_chain", "quote_age_seconds": None}, {}):
        r = _readiness_no_db({"intent_id": "i", "correlation_id": "c", "account_key": "rollover", "signal_evidence": ev},
                             asset_class="option", account_key="rollover", mode="submit")
        g = r["gate_results"]["fresh_market_data"]
        assert g["ok"] is False and "unknown" in g["reason"], ev


def test_quote_age_is_recomputed_from_the_timestamp_at_submit_time():
    fresh = {"data_source": "schwab_chain", "quotes_as_of": _iso(datetime.now(timezone.utc) - timedelta(seconds=20)),
             "chain_fetched_at": _iso(datetime.now(timezone.utc) - timedelta(seconds=30)), "quote_age_seconds": 5}
    stale = dict(fresh, quotes_as_of=_iso(datetime.now(timezone.utc) - timedelta(minutes=10)), quote_age_seconds=5)
    ok = _readiness_no_db({"intent_id": "i", "correlation_id": "c", "account_key": "rollover", "signal_evidence": fresh},
                          asset_class="option", account_key="rollover", mode="submit")["gate_results"]["fresh_market_data"]
    bad = _readiness_no_db({"intent_id": "i", "correlation_id": "c", "account_key": "rollover", "signal_evidence": stale},
                           asset_class="option", account_key="rollover", mode="submit")["gate_results"]["fresh_market_data"]
    assert ok["ok"] is True
    assert bad["ok"] is False and "stale" in bad["reason"]   # the stored age number (5 s) is NOT trusted
    no_chain = _readiness_no_db({"intent_id": "i", "correlation_id": "c", "account_key": "rollover",
                                 "signal_evidence": {k: v for k, v in fresh.items() if k != "chain_fetched_at"}},
                                asset_class="option", account_key="rollover", mode="submit")["gate_results"]["option_chain_fresh"]
    assert no_chain["ok"] is False


# ── buying power ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ev,expect", [
    ({"buying_power": None}, "unknown"),
    ({"buying_power": 50_000.0}, "undated"),
    ({"buying_power": 50_000.0, "buying_power_as_of": None}, "undated"),
    ({"buying_power": 50_000.0, "buying_power_as_of": "2026-09-27T00:00:00+00:00"}, "old"),
    ({"buying_power": 1_000.0, "buying_power_as_of": None, "collateral_required": 2500.0}, "undated"),
])
def test_buying_power_absent_undated_stale_fails_closed(ev, expect):
    base = {"data_source": "schwab_chain", "quotes_as_of": _iso(datetime.now(timezone.utc)),
            "chain_fetched_at": _iso(datetime.now(timezone.utc))}
    r = _readiness_no_db({"intent_id": "i", "correlation_id": "c", "account_key": "rollover", "signal_evidence": {**base, **ev}},
                         asset_class="option", account_key="rollover", mode="submit")
    g = r["gate_results"]["buying_power_sufficient"]
    assert g["ok"] is False and expect in g["reason"], g


def test_buying_power_below_collateral_blocks_and_enough_passes():
    base = {"data_source": "schwab_chain", "quotes_as_of": _iso(datetime.now(timezone.utc)),
            "chain_fetched_at": _iso(datetime.now(timezone.utc)), "buying_power_as_of": _iso(datetime.now(timezone.utc)),
            "collateral_required": 2500.0}
    low = _readiness_no_db({"intent_id": "i", "correlation_id": "c", "account_key": "rollover",
                            "signal_evidence": {**base, "buying_power": 2000.0}},
                           asset_class="option", account_key="rollover", mode="submit")["gate_results"]["buying_power_sufficient"]
    ok = _readiness_no_db({"intent_id": "i", "correlation_id": "c", "account_key": "rollover",
                           "signal_evidence": {**base, "buying_power": 2600.0}},
                          asset_class="option", account_key="rollover", mode="submit")["gate_results"]["buying_power_sufficient"]
    assert low["ok"] is False and "< collateral" in low["reason"]
    assert ok["ok"] is True


def test_read_buying_power_fails_closed_on_degraded_or_missing_reads():
    assert oop.read_buying_power("rollover", reader=lambda k: {"status": "degraded"}) == (None, None)
    assert oop.read_buying_power("rollover", reader=lambda k: {"status": "active"}) == (None, None)
    assert oop.read_buying_power("rollover", reader=lambda k: (_ for _ in ()).throw(RuntimeError("x"))) == (None, None)
    bp, as_of = oop.read_buying_power("rollover", reader=lambda k: {"status": "active", "buying_power": 12345.6})
    assert bp == 12345.6 and as_of


# ── the intent carries the authorization evidence; the order comes from the intent only ─────

def test_intent_carries_the_authorization_evidence():
    p = _prop()
    i = _intent(p)
    ev = i.meta.signal_evidence
    assert ev["proposal_pin"] == f"opt_{GUID}@v1" and ev["approved_strategy_guid"] == GUID
    assert ev["approval_hash"] == ent.approval_pin(p)["approved_hash"]
    assert ev["quotes_as_of"] == p["quotes_as_of"] and ev["chain_fetched_at"] == p["chain_fetched_at"]
    assert ev["data_source"] == "schwab_chain" and ev["collateral_required"] == 2500.0
    assert ev["buying_power"] == 50_000.0 and ev["buying_power_as_of"]
    assert ev["quote_age_seconds"] == 30.0 and ev["chain_age_seconds"] == 60.0
    assert ev["limit_price"] == 6.35 and ev["expiration"] == "2026-11-20"


def test_order_is_built_from_the_intent_and_ignores_the_cache(monkeypatch, tmp_path):
    import json
    import options_engine as oe
    i = _intent()
    cache = tmp_path / "options_proposals.json"
    cache.write_text(json.dumps({"proposals": [dict(_prop(), long_strike=485.0, premium=9.10, contracts=3)]}))
    monkeypatch.setattr(oe, "PROPOSALS_CACHE", cache)
    spec = oop.order_from_intent(i)
    legs = spec["orderLegCollection"]
    assert legs[0]["instrument"]["symbol"].endswith("00522500") and legs[1]["instrument"]["symbol"].endswith("00497500")
    assert legs[0]["quantity"] == 1 and spec["price"] == "6.35" and spec["orderType"] == "NET_CREDIT"
    assert oop.spec_from_intent(i) == spec


# ── confirm_authorization: every reviewer-listed change after approval fails closed ─────────

def _run_auth(intent, *, proposal, store, now=NOW, bp=(50_000.0, None), bind=None, approved=None):
    """Drive the contract with the desk gate live: the approval-queue row is pinned to the
    APPROVED proposal (``approved``, default the unchanged one) while ``proposal`` is what the
    desk holds now; readiness is stubbed only where it needs a DB. ``bp`` = the broker read."""
    calls = {"bind": []}
    approved_row = _row(approved or _prop())

    def gate(pid, prop, now=None):
        return ent.preflight_desk_gate(pid, prop, store=store, now=now, row=approved_row, cfg=ent.load_desk_config())

    def readiness(dct, **kw):
        # the SAME clock the contract confirms with is the clock the freshness gate evaluates on
        return _readiness_no_db(dct, now=now, **kw)

    def _bind(i, spec, *, readiness):
        calls["bind"].append((spec, readiness.get("ok")))
        return {"ok": True, "approval_id": 1, "evidence_hash": "e", "order_spec_hash": ea.order_spec_hash(spec)}

    reader = (lambda k: {"status": "active", "buying_power": bp[0]}) if bp[0] is not None else (lambda k: {"status": "degraded"})
    res = oop.confirm_authorization(intent, now=now, buying_power_reader=reader,
                                    proposal_loader=lambda pid: proposal, desk_gate=gate,
                                    readiness_fn=readiness, bind_fn=bind or _bind,
                                    # This suite isolates the existing desk/readiness contract.
                                    # The mandatory new final quote/revision gate has its own
                                    # fake-clock adapter suite in test_options_workflow_execution.
                                    workflow_gate=lambda *_: {"ok": True, "refusals": []})
    res["_bind_calls"] = calls["bind"]
    return res


def _codes(res):
    return {r["code"] for r in res["refusals"]}


def test_positive_control_authorizes_once_and_binds_the_exact_order(tmp_path):
    """Quote 30 s old, chain 60 s old ON THE TEST CLOCK; the same fixture is refused on a clock
    2 minutes later (see test_stale_quote_timestamp_at_confirm_is_refused) so the pass is the
    rule passing, not the rule missing."""
    p = _prop()
    res = _run_auth(_intent(p), proposal=p, store=_store(tmp_path))
    assert res["ok"] is True, res["refusals"]
    assert len(res["_bind_calls"]) == 1 and res["_bind_calls"][0][1] is True
    assert res["order_spec"]["price"] == "6.35" and res["evidence"]["order_spec_hash"] == ea.order_spec_hash(res["order_spec"])


def test_clock_injection_does_not_change_the_rule(tmp_path):
    """The injected clock only moves 'now': at NOW+119s the 30 s-old quote is 149 s old and the
    gate refuses; at NOW+89s it is 119 s old and passes. The 120 s production TTL is read from
    the gate, not restated here."""
    p = _prop()
    late = _run_auth(_intent(p), proposal=p, store=_store(tmp_path), now=NOW + timedelta(seconds=119))
    assert late["ok"] is False and "fresh_market_data" in _codes(late), _codes(late)
    assert any("stale 149s > 120s" in r["reason"] for r in late["refusals"]), late["refusals"]
    edge = _run_auth(_intent(p), proposal=p, store=_store(tmp_path), now=NOW + timedelta(seconds=89))
    assert edge["ok"] is True, edge["refusals"]


def test_stale_chain_is_refused_even_when_the_quote_is_fresh(tmp_path):
    """Chain fetched 10 minutes before the quote: fresh_market_data passes, option_chain_fresh
    refuses. Both timestamps are evaluated on the injected clock."""
    p = _prop(chain_fetched_at=_iso(NOW - timedelta(minutes=10)))
    res = _run_auth(_intent(p), proposal=p, store=_store(tmp_path))
    assert res["ok"] is False and "option_chain_fresh" in _codes(res), _codes(res)
    assert "fresh_market_data" not in _codes(res)


def test_changed_quote_evidence_after_approval_is_refused(tmp_path):
    """Changed-evidence negative: the desk re-quoted after approval (a NEWER quotes_as_of, so not
    a staleness refusal on the injected clock) and now prices the spread 21% away from the
    approved limit (the desk's own max_premium_change_pct is 15). The contract refuses before
    binding; a re-quote INSIDE the tolerance is allowed (the order is built from the intent)."""
    p = _prop()
    requoted = dict(p, quotes_as_of=_iso(NOW - timedelta(seconds=5)), premium=5.00, executable_credit=5.00)
    res = _run_auth(_intent(p), proposal=requoted, store=_store(tmp_path))
    assert res["ok"] is False and res["_bind_calls"] == [], _codes(res)
    assert "limit_changed" in _codes(res) and "fresh_market_data" not in _codes(res), _codes(res)
    inside = dict(p, quotes_as_of=_iso(NOW - timedelta(seconds=5)), premium=6.30, executable_credit=6.30)
    ok = _run_auth(_intent(p), proposal=inside, store=_store(tmp_path))
    assert ok["ok"] is True, ok["refusals"]
    # and at the submit boundary: readiness that flipped to a hard block after binding is refused
    rec = {"id": 1, "hashes": {}, "readiness_hash": "r0", "proposal_snapshot": {}, "used_at": None, "expires_at": None}
    with mock.patch.object(ea, "fetch_approval", return_value=rec), mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
        blocked = ea.revalidate_before_submit("i", current_readiness={"ok": False, "evidence_hash": "r1",
                                                                     "hard_blocks": [{"code": "fresh_market_data"}]})
    assert blocked["ok"] is False and blocked["reason"] == "readiness_changed_to_block"


def test_changed_long_leg_after_approval_is_refused(tmp_path):
    p = _prop()
    changed = dict(p, long_strike=485.0)
    res = _run_auth(_intent(p), proposal=changed, store=_store(tmp_path))
    assert res["ok"] is False and "legs_changed" in _codes(res) and res["_bind_calls"] == []


def test_changed_quantity_or_limit_after_approval_is_refused(tmp_path):
    p = _prop()
    for change, code in (({"contracts": 3}, "quantity_changed"), ({"premium": 9.10, "executable_credit": 9.10}, "limit_changed")):
        res = _run_auth(_intent(p), proposal=dict(p, **change), store=_store(tmp_path))
        assert res["ok"] is False and code in _codes(res), (change, _codes(res))


def test_changed_account_is_refused_at_submit_boundary(tmp_path):
    """The account is on the intent; place_order refuses when intent.account_key differs (AST-proven)."""
    import ast
    src = (ROOT / "scripts" / "schwab_transport.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "place_order")
    body = ast.get_source_segment(src, fn)
    assert 'intent.account_key or "") != account_key' in body and body.index("!= account_key") < body.index("evaluate_execution_readiness(")
    p = _prop()
    res = _run_auth(_intent(p), proposal=dict(p, account="taxable"), store=_store(tmp_path))
    assert res["ok"] is False and "legs_changed" in _codes(res)   # account is part of the canonical legs pin


def test_changed_proposal_version_is_refused(tmp_path):
    p = _prop()
    res = _run_auth(_intent(p), proposal=dict(p, options_thesis={"pin": f"opt_{GUID}@v2", "missing_required": []}),
                    store=_store(tmp_path))
    assert res["ok"] is False and "proposal_version_changed" in _codes(res) and res["_bind_calls"] == []


def test_stale_quote_timestamp_at_confirm_is_refused(tmp_path):
    p = _prop()
    i = _intent(p)
    res = _run_auth(i, proposal=p, store=_store(tmp_path), now=NOW + timedelta(minutes=10))
    assert res["ok"] is False
    assert any(r["code"] in ("fresh_market_data", "quote_stale") for r in res["refusals"]), _codes(res)


def test_buying_power_changes_at_confirm_are_refused(tmp_path):
    p = _prop()
    unreadable = _run_auth(_intent(p), proposal=p, store=_store(tmp_path), bp=(None, None))
    assert unreadable["ok"] is False and "buying_power_sufficient" in _codes(unreadable)
    low = _run_auth(_intent(p), proposal=p, store=_store(tmp_path), bp=(1_000.0, None))
    assert low["ok"] is False and any("< collateral" in r["reason"] for r in low["refusals"])


def test_archived_thesis_and_missing_proposal_are_refused(tmp_path):
    p = _prop()
    res = _run_auth(_intent(p), proposal=p, store=_store(tmp_path, abandoned=True))
    assert res["ok"] is False and "thesis_abandoned" in _codes(res)
    gone = oop.confirm_authorization(_intent(p), now=NOW, buying_power_reader=lambda k: {"status": "active", "buying_power": 5e4},
                                     proposal_loader=lambda pid: None, desk_gate=lambda *a, **k: {"refusals": []},
                                     readiness_fn=lambda d, **k: {"ok": True, "hard_blocks": []}, bind_fn=lambda *a, **k: {"ok": True})
    assert gone["ok"] is False and "proposal_missing" in _codes(gone)


def test_no_order_without_its_exact_evidence_bound_authorization(tmp_path):
    p = _prop()
    failing = _run_auth(_intent(p), proposal=p, store=_store(tmp_path),
                        bind=lambda i, spec, *, readiness: {"ok": False, "error": "db_unavailable"})
    assert failing["ok"] is False and "evidence_approval_failed" in _codes(failing)
    # and at the submit boundary: no bound approval -> revalidation fails closed
    with mock.patch.object(ea, "fetch_approval", return_value=None):
        assert ea.revalidate_before_submit("i", current_readiness={"ok": True, "evidence_hash": "x"})["reason"] == "no_evidence_bound_approval"
    # a bound approval pins the exact spec; a different spec at submit is refused
    spec = oop.order_from_intent(_intent(p))
    rec = {"id": 1, "hashes": {}, "proposal_snapshot": {"order_spec_hash": ea.order_spec_hash(spec)}, "used_at": None, "expires_at": None}
    other = oop.order_from_intent(_intent(dict(p, long_strike=485.0)))
    with mock.patch.object(ea, "fetch_approval", return_value=rec), mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
        assert ea.revalidate_before_submit("i", current_order_spec=other, current_readiness={"ok": True})["reason"] == "order_spec_hash_changed"
        assert ea.revalidate_before_submit("i", current_order_spec=spec, current_readiness={"ok": True})["ok"] is True


# ── the api confirm handler and the router run the contract before submit ───────────────────

def test_api_confirm_refuses_before_submit_when_the_contract_refuses(monkeypatch):
    from brokers import intent_submit_router as router
    monkeypatch.setitem(sys.modules, "brokers.intent_submit_router", router)
    from unittest.mock import MagicMock
    brokers = MagicMock(name="brokers")
    oopm = MagicMock(name="brokers.options_order_pilot")
    guard = MagicMock(name="brokers.execution_guard")
    aps = MagicMock(name="brokers.approval_service")
    ready = MagicMock(name="brokers.execution_readiness")
    for name, mod in (("brokers", brokers), ("brokers.options_order_pilot", oopm), ("brokers.execution_guard", guard),
                      ("brokers.approval_service", aps), ("brokers.execution_readiness", ready)):
        monkeypatch.setitem(sys.modules, name, mod)
    brokers.options_order_pilot, brokers.execution_guard, brokers.approval_service, brokers.execution_readiness = oopm, guard, aps, ready
    import api_v2
    intent = MagicMock(); intent.account_key = "rollover"
    oopm.load_intent.return_value = intent
    aps._load_intent_any.return_value = intent
    aps.is_fully_approved.return_value = True
    aps.confirm.return_value = {"ok": True, "fully_approved": True}
    oopm.confirm_authorization.return_value = {"ok": False, "refusals": [{"code": "legs_changed", "reason": "x"}]}
    body = {"intent_id": "i1", "channel": "web", "code": "DELL"}
    status, resp = api_v2.handle("/api/v2/options/confirm", "POST", body=body)
    assert status == 200 and resp["ok"] is False and resp["stage"] == "authorization" and resp["broker_submitted"] is False
    assert [r["code"] for r in resp["refusals"]] == ["legs_changed"]
    assert oopm.submit.call_count == 0 and oopm.spec_from_intent.call_count == 0
    # not fully approved: the contract is not even consulted, nothing submits
    aps.confirm.return_value = {"ok": True, "fully_approved": False}
    status, resp = api_v2.handle("/api/v2/options/confirm", "POST", body=body)
    assert resp["fully_approved"] is False and oopm.confirm_authorization.call_count == 1 and oopm.submit.call_count == 0
    # everything authorized: the exact contract order is what submits, once
    aps.confirm.return_value = {"ok": True, "fully_approved": True}
    oopm.confirm_authorization.return_value = {"ok": True, "order_spec": {"price": "6.35"}, "evidence": {"ok": True, "order_spec_hash": "h"}}
    oopm.submit.return_value = {"status": "submitted"}
    status, resp = api_v2.handle("/api/v2/options/confirm", "POST", body=body)
    assert status == 200 and resp["stage"] == "submit" and resp["result"]["status"] == "submitted"
    oopm.submit.assert_called_once_with("rollover", {"price": "6.35"}, intent)


def test_router_options_branch_runs_the_contract_before_submit():
    """AST-proven on intent_submit_router: confirm_authorization precedes submit and a refusal returns."""
    import ast
    src = (ROOT / "scripts" / "brokers" / "intent_submit_router.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "submit_fully_approved")
    body = ast.get_source_segment(src, fn)
    i_auth, i_sub = body.index("oop.confirm_authorization(ointent)"), body.index("oop.submit(acct, auth[\"order_spec\"], ointent)")
    assert i_auth < i_sub and 'if not auth.get("ok"):' in body[i_auth:i_sub] and "return {" in body[i_auth:i_sub]
