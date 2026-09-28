"""Broker-layer order gate proofs for the options desk (reviewer work order 2026-09-27, item 5).

Built under a per-task execution-engineering grant (AGENTS 1.3.0 rule 2). Hermetic: every DB,
Schwab and Telegram touch is faked; nothing here arms, submits, or requests a real 2FA code.

The reviewer asked for proof that stale quotes, missing thesis/CIO approval, failed liquidity,
insufficient buying power, archived proposals and changed legs prevent ORDER CREATION even when
the broker route is open and the user has 2FA. The desk-layer half lives in
tests/test_options_order_gates_20260927.py. This file proves the broker layer:

  (a) confirm without verified 2FA never reaches submit; authorize denies without 2FA
  (b) a kill switch (or an unreadable kill-switch table) blocks readiness and post-approval revalidation
  (c) submit re-runs readiness + evidence revalidation + authorize (a state change after preflight blocks)
  (d) legs are NOT pinned on the options path today: spec_from_intent rebuilds the order from the
      proposals cache (xfail, strict) -- and, separately, options preflight never creates the
      evidence-bound approval that place_order demands, so every options submit fails closed
  (e) stale or unknown quote age fails closed; build_intent carries no quote age, so it fails closed
  (f) LLM metadata cannot unlock the live path
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

DELL = {"id": "opt_credit_spread_DELL_schwab_taxable_522p5000_20261120_d20260927", "strategy": "credit_spread",
        "symbol": "DELL", "underlying": "DELL", "account": "schwab_taxable", "option_type": "put",
        "short_strike": 522.5, "long_strike": 497.5, "strike": 522.5, "expiration": "2026-11-20",
        "contracts": 1, "premium": 6.35, "executable_credit": 6.35, "data_source": "schwab_chain"}


class _Cur:
    """Cursor whose answers are scripted per SQL fragment; default is 'nothing found'."""
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.executed = []
        self._last = None

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))
        self._last = None
        for frag, ans in self.answers.items():
            if frag in " ".join(str(sql).split()):
                self._last = ans
                break
        self.rowcount = 0

    def fetchone(self):
        return self._last

    def fetchall(self):
        return self._last or []


class _Conn:
    def __init__(self, cur):
        self._cur = cur
        self.commits = 0

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _intent(proposal=DELL, account="schwab_taxable"):
    from brokers import options_order_pilot as oop
    return oop.build_intent(account, dict(proposal), held_qty=0)


def _no_audit():
    import brokers.audit as audit
    return mock.patch.object(audit, "record_guard_decision", lambda *a, **k: None)


# ── (a) 2FA ──────────────────────────────────────────────────────────────────────────────────

def test_a_confirm_refuses_a_wrong_code_and_a_web_click_without_the_typed_ticker():
    from brokers import approval_service as aps
    row = (7, "123456", None, "pending")
    cur = _Cur({"SELECT id, code, expires_at, status FROM trade_approvals": row})
    with mock.patch.object(aps, "_conn", return_value=_Conn(cur)):
        assert aps.confirm("i1", "telegram", "000000") == {"ok": False, "reason": "invalid confirmation code"}
        assert aps.confirm("i1", "telegram", None)["ok"] is False
    cur = _Cur({"SELECT id, code, expires_at, status FROM trade_approvals": (8, "DELL", None, "pending")})
    with mock.patch.object(aps, "_conn", return_value=_Conn(cur)):
        r = aps.confirm("i1", "web", "")          # a click, no typed ticker
        assert r["ok"] is False and "typing the ticker" in r["reason"]
        assert not any("UPDATE trade_approvals SET status='confirmed'" in s for s, _ in cur.executed)


def test_a_api_confirm_returns_before_submit_when_not_fully_approved():
    """The /api/v2/options/confirm handler submits only on cr['fully_approved']; prove it structurally:
    in the handler body the call to oop.submit is guarded by the fully_approved check (AST, not text)."""
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Find the `if method == "POST" and base_path == "/api/v2/options/confirm":` block.
    block = None
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and '"/api/v2/options/confirm"' in ast.get_source_segment(src, node.test):
            block = node
            break
    assert block is not None
    body_src = ast.get_source_segment(src, block)
    submit_line = body_src.index("oop.submit(")
    guard_line = body_src.index('if not cr.get("fully_approved")')
    twofa_line = body_src.index("approval_service.confirm(")
    assert twofa_line < guard_line < submit_line
    # and the guard returns (does not fall through) when not fully approved
    guard_ret = body_src[guard_line:submit_line]
    assert "return 200, {\"ok\": True, \"stage\": \"confirm\", \"fully_approved\": False}" in guard_ret


def test_a_authorize_denies_options_submit_without_2fa_even_with_every_lock_open():
    from brokers import execution_guard as eg
    intent = _intent()
    with _no_audit(), \
         mock.patch.object(eg, "_options_unlocked", return_value=True), \
         mock.patch.object(eg, "_live_future_unlocked", return_value=True), \
         mock.patch.object(eg, "_options_gate_reason", return_value=None), \
         mock.patch("brokers.approval_service.is_fully_approved", return_value=False):
        d = eg.authorize(intent, "submit")
    assert d.allowed is False and "two-factor" in d.reason
    with _no_audit(), \
         mock.patch.object(eg, "_options_unlocked", return_value=True), \
         mock.patch.object(eg, "_live_future_unlocked", return_value=True), \
         mock.patch.object(eg, "_options_gate_reason", return_value=None), \
         mock.patch("brokers.approval_service.is_fully_approved", return_value=True):
        d2 = eg.authorize(intent, "submit")
    assert d2.allowed is True and "Options" in d2.reason   # positive control: the gate is not always-false


def test_a_readiness_submit_mode_hard_blocks_on_missing_2fa_for_an_option():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True), \
         mock.patch("brokers.execution_readiness._paper_mode", return_value=False), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])), \
         mock.patch("brokers.approval_service.is_fully_approved", return_value=False):
        r = evaluate_execution_readiness({**DELL, "intent_id": "i-2fa", "signal_evidence": {"quote_age_seconds": 5, "data_source": "schwab_chain"}},
                                         asset_class="option", account_key="schwab_taxable", mode="submit")
    assert "operator_2fa_confirmed" in [b["code"] for b in r["hard_blocks"]] and r["ok"] is False


# ── (b) kill switch ──────────────────────────────────────────────────────────────────────────

def test_b_kill_switch_blocks_readiness_and_post_approval_revalidation():
    from brokers.execution_readiness import evaluate_execution_readiness
    from brokers import evidence_approval as ea
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(True, ["kill_switch:global"])):
        r = evaluate_execution_readiness({**DELL, "intent_id": "i-ks"}, asset_class="option",
                                         account_key="schwab_taxable", mode="submit")
    assert r["gate_results"]["kill_switches_clear"]["ok"] is False and r["mode"] == "blocked"
    # Flipped AFTER approval: revalidation catches it even when every stored bundle still matches.
    rec = {"id": 1, "hashes": {}, "proposal_snapshot": {}, "used_at": None, "expires_at": None, "evidence_hash": "e"}
    with mock.patch.object(ea, "fetch_approval", return_value=rec), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(True, ["kill_switch:global"])):
        rev = ea.revalidate_before_submit("i-ks", current_readiness={"ok": True, "evidence_hash": "x"})
    assert rev == {"ok": False, "reason": "kill_switch_after_approval", "hard_block": True,
                   "reasons": ["kill_switch:global"], "checks": []}


def test_b_unreadable_kill_switch_table_fails_closed():
    """No connection -> a synthetic global switch; a raising connection -> readiness and revalidation
    both fail closed one layer up (kill_switch_inspect_failed / kill_switch_check_failed)."""
    from brokers import kill_switches as ks
    from brokers import evidence_approval as ea
    from brokers.execution_readiness import _kill_switches_clear
    with mock.patch.object(ks, "_conn", return_value=None):
        active = ks.list_active()
        blocked, reasons = ks.is_blocked(live_submit=True)
    assert active and active[0].get("fail_closed") is True
    assert blocked is True and "db_unavailable_fail_closed" in reasons[0]
    with mock.patch.object(ks, "_conn", side_effect=RuntimeError("db down")):
        g = _kill_switches_clear(broker="schwab", account_key="a", strategy="credit_spread", symbol="DELL", asset_class="option")
        rec = {"id": 1, "hashes": {}, "proposal_snapshot": {}, "used_at": None, "expires_at": None}
        with mock.patch.object(ea, "fetch_approval", return_value=rec):
            rev = ea.revalidate_before_submit("i", current_readiness={"ok": True})
    assert g["ok"] is False and "kill_switch_inspect_failed" in g["reason"]
    assert rev["reason"] == "kill_switch_check_failed"


def test_b_kill_switch_is_enforced_by_readiness_and_revalidation_not_by_authorize_alone():
    """Documented layering: authorize() does not consult kill switches; place_order runs readiness and
    revalidation BEFORE require(). A caller that skipped place_order would also skip the kill switch."""
    from brokers import execution_guard as eg
    intent = _intent()
    with _no_audit(), \
         mock.patch.object(eg, "_options_unlocked", return_value=True), \
         mock.patch.object(eg, "_live_future_unlocked", return_value=True), \
         mock.patch.object(eg, "_options_gate_reason", return_value=None), \
         mock.patch("brokers.approval_service.is_fully_approved", return_value=True), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(True, ["kill_switch:global"])):
        d = eg.authorize(intent, "submit")
    assert d.allowed is True   # by itself, authorize does not see the kill switch
    src = (ROOT / "scripts" / "schwab_transport.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "place_order")
    body = ast.get_source_segment(src, fn)
    i_ready, i_rev, i_req = body.index("evaluate_execution_readiness("), body.index("revalidate_before_submit("), body.index("require(intent, \"submit\")")
    assert i_ready < i_rev < i_req
    assert body.index("_pilot_ensure_table(") > i_req    # broker work starts only after all three


# ── (c) re-check at submit ────────────────────────────────────────────────────────────────────

def test_c_revalidation_blocks_when_readiness_changed_after_approval():
    from brokers import evidence_approval as ea
    rec = {"id": 1, "hashes": {"readiness_hash": "h-approved"}, "proposal_snapshot": {}, "used_at": None,
           "expires_at": None, "evidence_hash": "e"}
    with mock.patch.object(ea, "fetch_approval", return_value=rec), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
        blocked_now = ea.revalidate_before_submit("i", current_readiness={"ok": False, "hard_blocks": [{"code": "x"}]})
        hash_moved = ea.revalidate_before_submit("i", current_readiness={"ok": True, "evidence_hash": "h-now"})
        same = ea.revalidate_before_submit("i", current_readiness={"ok": True, "evidence_hash": "h-approved"})
        missing = ea.revalidate_before_submit("i", current_readiness=None)
    assert blocked_now["reason"] == "readiness_changed_to_block"
    assert hash_moved["reason"] == "readiness_hash_changed"
    assert same["ok"] is True
    assert missing["reason"] == "readiness_bundle_unavailable_fail_closed"


def test_c_single_use_and_expiry_are_enforced_at_revalidation():
    import datetime as dt
    from brokers import evidence_approval as ea
    used = {"id": 1, "hashes": {}, "proposal_snapshot": {}, "used_at": "2026-09-27T20:00:00+00:00", "expires_at": None}
    old = {"id": 1, "hashes": {}, "proposal_snapshot": {}, "used_at": None,
           "expires_at": dt.datetime(2026, 9, 27, tzinfo=dt.timezone.utc)}
    with mock.patch.object(ea, "fetch_approval", return_value=used):
        assert ea.revalidate_before_submit("i")["reason"] == "approval_already_used_single_use"
    with mock.patch.object(ea, "fetch_approval", return_value=old):
        assert ea.revalidate_before_submit("i")["reason"] == "approval_expired"


# ── (d) legs pinned? ─────────────────────────────────────────────────────────────────────────

def test_d_options_intent_without_a_confirm_bound_approval_fails_closed_at_submit():
    """options_order_pilot.request_2fa -> approval_service.request_approval writes trade_approvals rows
    only; create_order_evidence_approval is called by the protective-stop and router paths, never by the
    options preflight. place_order then demands an evidence-bound approval and fails closed. Safe -- and
    it means the options route cannot submit at all today (functional defect, reported)."""
    # Since 2026-09-27 the evidence approval is bound at CONFIRM (after 2FA) by
    # options_order_pilot.confirm_authorization -> bind_options_authorization, mirroring the
    # protective-stop router path; preflight itself still creates none (there is nothing
    # approved yet), and an intent that never went through confirm still fails closed:
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    block = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                 and '"/api/v2/options/preflight"' in ast.get_source_segment(src, n.test))
    assert "create_order_evidence_approval" not in ast.get_source_segment(src, block)
    pilot = (ROOT / "scripts" / "brokers" / "options_order_pilot.py").read_text(encoding="utf-8")
    assert "create_order_evidence_approval" in pilot
    from brokers import evidence_approval as ea
    with mock.patch.object(ea, "fetch_approval", return_value=None):
        rev = ea.revalidate_before_submit("options-intent", current_readiness={"ok": True, "evidence_hash": "x"})
    assert rev == {"ok": False, "reason": "no_evidence_bound_approval", "hard_block": True}


def test_d_order_spec_hash_pins_legs_when_an_evidence_approval_exists():
    """The pin mechanism itself works: a changed long leg changes the order spec hash."""
    from brokers import evidence_approval as ea, options_order_pilot as oop
    spec_ok = oop.build_order_spec(DELL)
    spec_changed = oop.build_order_spec({**DELL, "long_strike": 485.0})
    rec = {"id": 1, "hashes": {}, "proposal_snapshot": {"order_spec_hash": ea.order_spec_hash(spec_ok)},
           "used_at": None, "expires_at": None}
    with mock.patch.object(ea, "fetch_approval", return_value=rec), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])):
        same = ea.revalidate_before_submit("i", current_order_spec=spec_ok, current_readiness={"ok": True})
        moved = ea.revalidate_before_submit("i", current_order_spec=spec_changed, current_readiness={"ok": True})
        absent = ea.revalidate_before_submit("i", current_order_spec=None, current_readiness={"ok": True})
    assert same["ok"] is True and moved["reason"] == "order_spec_hash_changed"
    assert absent["reason"] == "order_spec_bundle_unavailable_fail_closed"


def test_d_spec_from_intent_must_build_from_the_approved_intent_not_the_cache(monkeypatch, tmp_path):
    """Closed 2026-09-27 (order-authorization contract): the order is built from the intent only."""
    import json
    import options_engine as oe
    from brokers import options_order_pilot as oop
    intent = _intent()   # legs 522.5 / 497.5 at 6.35
    cache = tmp_path / "options_proposals.json"
    cache.write_text(json.dumps({"proposals": [{**DELL, "long_strike": 485.0, "premium": 9.10}]}))
    monkeypatch.setattr(oe, "PROPOSALS_CACHE", cache)
    spec = oop.spec_from_intent(intent)
    legs = spec["orderLegCollection"]
    assert legs[1]["instrument"]["symbol"].endswith("00497500"), legs   # long leg must be the intent's 497.5
    assert spec["price"] == "6.35"                                       # and the 2FA'd credit


def test_d_build_intent_carries_the_legs_it_was_approved_for():
    intent = _intent()
    legs = intent.instrument.option_legs
    assert [l["strike"] for l in legs] == [522.5, 497.5] and [l["side"] for l in legs] == ["SELL", "BUY"]
    assert intent.entry.limit_price == 6.35 and intent.meta.signal_evidence["proposal_id"] == DELL["id"]


# ── (e) stale quote ──────────────────────────────────────────────────────────────────────────

def _ready_option(ev, **top):
    """Readiness exactly as schwab_transport.place_order calls it: an intent-shaped dict carrying only
    intent_id / correlation_id / account_key / signal_evidence (plus any keys a caller adds)."""
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_readiness._global_live_allowed",
                    return_value={"ok": True, "code": "global_live_allowed", "reason": "ok", "severity": "hard"}), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])), \
         mock.patch("brokers.approval_service.is_fully_approved", return_value=True):
        return evaluate_execution_readiness({"intent_id": "i-q", "correlation_id": "c", "account_key": "schwab_taxable",
                                             "signal_evidence": ev, **top},
                                            asset_class="option", account_key="schwab_taxable", mode="submit")


def test_e_missing_quote_age_with_a_named_data_source_must_still_fail_closed():
    """Closed 2026-09-27 (order-authorization contract): absent quote age fails closed regardless of source."""
    gate = _ready_option({"data_source": "schwab_chain"})["gate_results"]["fresh_market_data"]
    assert gate["ok"] is False


def test_e_stale_or_unknown_quote_age_fails_closed_and_a_fresh_chain_quote_passes():
    unknown = _ready_option({})["gate_results"]["fresh_market_data"]
    stale = _ready_option({"quote_age_seconds": 500, "data_source": "schwab_chain"})["gate_results"]["fresh_market_data"]
    modelled = _ready_option({"quote_age_seconds": 5, "data_source": "bs_estimate"})["gate_results"]["fresh_market_data"]
    fresh = _ready_option({"quote_age_seconds": 30, "data_source": "schwab_chain"})["gate_results"]["fresh_market_data"]
    assert unknown["ok"] is False and "unknown" in unknown["reason"]
    assert stale["ok"] is False and "stale" in stale["reason"]
    assert modelled["ok"] is False and "bs_estimate" in modelled["reason"]
    assert fresh["ok"] is True
    old_chain = _ready_option({"quote_age_seconds": 30, "data_source": "schwab_chain", "chain_age_seconds": 900})
    assert old_chain["gate_results"]["option_chain_fresh"]["ok"] is False


def test_e_build_intent_carries_quote_timestamps_and_readiness_recomputes_the_age():
    """Closed 2026-09-27 (order-authorization contract): the intent carries quotes_as_of /
    chain_fetched_at / data_source; readiness recomputes the age from them at submit time and
    an intent built from a proposal WITHOUT timestamps still fails closed."""
    intent = _intent()   # DELL fixture: no quote timestamps on the proposal
    ev = intent.meta.signal_evidence
    assert "quotes_as_of" in ev and ev["quote_age_seconds"] is None and ev["data_source"] == "schwab_chain"
    gate = _ready_option(ev)["gate_results"]["fresh_market_data"]
    assert gate["ok"] is False and "unknown" in gate["reason"]
    import datetime as dt
    fresh = _intent(dict(DELL, quotes_as_of=dt.datetime.now(dt.timezone.utc).isoformat(),
                         chain_fetched_at=dt.datetime.now(dt.timezone.utc).isoformat()))
    assert fresh.meta.signal_evidence["quote_age_seconds"] is not None
    assert _ready_option(fresh.meta.signal_evidence)["gate_results"]["fresh_market_data"]["ok"] is True


def test_e_quote_time_parser_never_guesses_and_ages_correctly():
    import datetime as dt
    from brokers import quote_time as qt
    now = dt.datetime(2026, 9, 28, 14, 0, tzinfo=dt.timezone.utc)
    assert qt.quote_age_seconds("garbage", now=now) is None and qt.is_fresh("garbage", now=now) is False
    assert qt.quote_age_seconds("2026-09-28T13:59:00+00:00", now=now) == 60.0
    assert qt.is_fresh("2026-09-28T13:00:00+00:00", now=now) is False   # 60 min in a regular session


# ── (f) LLM cannot unlock ────────────────────────────────────────────────────────────────────

def test_f_llm_metadata_cannot_unlock_an_options_submit():
    from brokers.execution_readiness import evaluate_execution_readiness
    with mock.patch("brokers.execution_guard._live_future_unlocked", return_value=True), \
         mock.patch("brokers.kill_switches.is_blocked", return_value=(False, [])), \
         mock.patch("brokers.approval_service.is_fully_approved", return_value=True):
        r = evaluate_execution_readiness({**DELL, "intent_id": "i-llm", "model_snapshot": {"unlock_live": True},
                                          "signal_evidence": {"quote_age_seconds": 5, "data_source": "schwab_chain"}},
                                         asset_class="option", account_key="schwab_taxable", mode="submit")
    assert r["gate_results"]["llm_advisory_only"]["ok"] is False and r["mode"] == "blocked"
    assert r["autonomous_live_submit_allowed"] is False
