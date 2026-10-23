"""Options Desk accuracy (2026-10-22 audit): per-quote session, honest quote ages,
lifecycle-aware Next/Owner, liquidity-aware edge, CSP on the bid, both earnings dates,
execution-state text, intent conflicts, account grouping, honest coverage, lifecycle
freshness, blocked-row expiry, abandon-before-liquidity-skip, watch-only intents and a
null avg POP.

Hermetic: no network, broker, database or model. Fixtures mirror the captured production
payload of 2026-10-22 (SPCX protective put, CIO review POLICY_NOT_ALLOWED x3, quote from the
2026-10-21 16:00 close, PRE_MARKET stamped by a 09:29 run). Field contract:
docs/ops/OPTIONS_DESK_FIELDS.md.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import pytest  # noqa: E402

from lib import options_desk_accuracy as acc  # noqa: E402
from lib.options_decision_packet import review_workflow  # noqa: E402
from lib.options_intent import matcher as mt  # noqa: E402
from lib.options_intent import ranking as rk  # noqa: E402

NOW_REGULAR = datetime(2026, 10, 22, 14, 57, 8, tzinfo=timezone.utc)   # 10:57 ET
NOW_PRE = datetime(2026, 10, 22, 13, 29, 0, tzinfo=timezone.utc)       # 09:29 ET
CLOSE_QUOTE = "2026-10-21T20:00:00.269000+00:00"                       # 16:00:00 ET close
OPEN_QUOTE = "2026-10-22T13:31:00+00:00"                               # 09:31 ET

CRONTAB = """\
PROJ=/x
*/10 12-15 * * 1-5 cd /x && bash /x/linux_launchers/run_options_monitor.sh  # noon-close
5 16 * * 1-5 cd /x && bash /x/linux_launchers/run_options_monitor.sh
# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) */20 9-16 * * 1-5 cd /x && flock -n /tmp/l.lock bash -c "$PY scripts/options_lifecycle_run.py" >> logs/options_lifecycle.log 2>&1
"""


def _failed(at: str) -> dict:
    return {"stage": "CIO_REVIEW_FAILED", "at": at, "reason": "POLICY_NOT_ALLOWED", "status": "LLM_ERROR"}


def _spcx(**kw) -> dict:
    card = {
        "id": "opt_protective_put_SPCX_schwab_rollover_ira_148p0000_20261120_d20261022",
        "strategy": "protective_put", "symbol": "SPCX", "account": "schwab_rollover_ira",
        "option_type": "put", "strike": 148.0, "expiration": "2026-11-20", "dte": 29, "contracts": 6,
        "premium": 4.65, "bid": 4.4, "ask": 4.65, "oi": 476, "volume": 0, "bid_ask_spread_pct": 5.52,
        "quote_time": CLOSE_QUOTE, "underlying_price": 154.12, "edge_score": 68.4, "max_loss": 6462.0,
        "data_source": "schwab_chain", "contract_guid": "f75a0c29", "approvable": False,
        "chain_fetched_at": "2026-10-22T13:30:02+00:00",
        "price_source": {"source": "schwab_chain_underlying", "as_of": "2026-10-22T13:30:02.416900+00:00"},
        "options_thesis": {"pin": "opt_19e3@v4", "missing_required": []},
        "enterprise": {"live_eligible": False, "liquidity": {"pass": True, "oi": 476, "volume": 0,
                                                              "bid_ask_spread_pct": 5.52, "issues": []},
                       "blocks": [{"code": "awaiting_cio_decision", "reason": "no CIO decision issued yet"},
                                  {"code": "quote_stale", "reason": "quote age 68227.1s exceeds cap"},
                                  {"code": "option_chain_stale", "reason": "chain age 5228.4s exceeds cap"}]},
        "lifecycle": {"stage": "CIO_REVIEW_FAILED", "timeline": [
            {"stage": "CREATED", "at": "2026-10-22T09:15:49+00:00"},
            {"stage": "CIO_REVIEW_QUEUED", "at": "2026-10-22T09:22:02+00:00", "status": "LLM_ERROR"},
            _failed("2026-10-22T09:22:03+00:00"), _failed("2026-10-22T09:37:02+00:00"),
            _failed("2026-10-22T09:52:04+00:00")]},
    }
    card.update(kw)
    return card


# ── 1. session per quote ─────────────────────────────────────────────────────

def test_session_is_the_quotes_own_not_the_run_start():
    assert acc.session_at(CLOSE_QUOTE) == "AFTER_HOURS"
    assert acc.session_at(OPEN_QUOTE) == "REGULAR"
    assert acc.session_at("2026-10-22T13:29:00+00:00") == "PRE_MARKET"
    assert acc.session_at("2026-10-24T15:00:00+00:00") == "WEEKEND"
    # DST-correct: 14:31 UTC on 2026-12-01 is 09:31 EST (a fixed -4h offset said 10:31).
    assert acc.session_at("2026-12-01T14:15:00+00:00") == "PRE_MARKET"


def test_engine_liquidity_deferral_follows_the_quote_session(monkeypatch):
    import options_engine as oe
    monkeypatch.setattr(oe, "_DESK_CFG", {})
    monkeypatch.setitem(oe._SESSION, "now", "PRE_MARKET")  # the run started at 09:29
    oe.LIQUIDITY_DEFERRED.clear()
    oe.INCOME_SCREEN_DROPS.clear()
    thin = {"strike": 90.0, "mid": 2.0, "bid": 1.0, "ask": 3.0, "oi": 0, "dte": 30}
    # A 09:31 quote is a regular-session quote: its liquidity miss is real, not deferred.
    reason = oe._income_screen("cash_secured_put", "XYZ", {**thin, "quote_time": OPEN_QUOTE}, "schwab_chain", 100.0)
    assert reason == "NO_LIQUID_CONTRACT"
    assert oe.LIQUIDITY_DEFERRED == []
    # Yesterday's closing quote is deferred, and the record names ITS session.
    assert oe._income_screen("cash_secured_put", "XYZ", {**thin, "quote_time": CLOSE_QUOTE},
                             "schwab_chain", 100.0) is None
    assert oe.LIQUIDITY_DEFERRED[-1]["session"] == "AFTER_HOURS"
    summary = oe._income_screen_summary()["liquidity_deferred"]
    assert summary["session"] == "AFTER_HOURS" and summary["run_started_session"] == "PRE_MARKET"


def test_quote_without_a_time_is_never_deferred_by_the_wall_clock(monkeypatch):
    """Main red 2026-10-22 16:24 ET: a timestamp-less liquidity miss was deferred because the
    fallback read the wall clock (AFTER_HOURS); the named NO_LIQUID_CONTRACT drop vanished."""
    import options_engine as oe
    monkeypatch.setattr(oe, "_DESK_CFG", {})
    monkeypatch.setattr(oe, "_market_session_now", lambda: "AFTER_HOURS")
    monkeypatch.delitem(oe._SESSION, "now", raising=False)
    oe.LIQUIDITY_DEFERRED.clear()
    oe.INCOME_SCREEN_DROPS.clear()
    thin = {"strike": 90.0, "mid": 2.0, "bid": 1.0, "ask": 3.0, "oi": 0, "dte": 30}
    assert oe._income_screen("cash_secured_put", "XYZ", thin, "schwab_chain", 100.0) == "NO_LIQUID_CONTRACT"
    assert oe.LIQUIDITY_DEFERRED == []
    oe.INCOME_SCREEN_DROPS.clear()


def test_served_payload_carries_the_current_session_and_restamps_cached_cards():
    card = _spcx(economics={"market_session": "PRE_MARKET"},
                 price_basis="ask estimate; not a fill; session PRE_MARKET; fees and slippage excluded from premium")
    acc.restamp_session_if_stale(card)
    assert card["economics"]["market_session"] == "AFTER_HOURS"
    assert "session AFTER_HOURS" in card["price_basis"]
    data = {"generated_at": "2026-10-22T13:30:15+00:00", "market_session": "PRE_MARKET", "proposals": [card]}
    acc.apply_served_accuracy(data, [card], now=NOW_REGULAR, armed=True, intents=[], scan_enabled=False,
                              schedule={"lane": "run-options-monitor", "schedules": [], "source": "none"})
    assert data["market_session"] == "REGULAR"


# ── 2. honest quote clock and snapshot schedule ──────────────────────────────

def test_card_quote_clock_separates_option_spot_and_chain_ages():
    card = acc.stamp_quote_clock(_spcx(), now=NOW_REGULAR, quote_max_age_s=120)
    assert card["quote_session"] == "AFTER_HOURS"
    assert card["quote_age_s"] == pytest.approx(68227.7, abs=1)
    assert card["underlying_price_source"] == "schwab_chain_underlying"
    assert card["underlying_price_time_basis"] == "fetch_time"
    assert card["underlying_price_age_s"] == pytest.approx(5225.6, abs=1)
    assert card["chain_age_s"] == pytest.approx(5226, abs=1)
    assert card["quote_stale"] is True
    with_provider = acc.stamp_quote_clock(
        _spcx(price_source={"source": "schwab_chain_underlying", "as_of": "2026-10-22T13:30:02+00:00",
                            "quote_time": CLOSE_QUOTE}), now=NOW_REGULAR)
    assert with_provider["underlying_price_time_basis"] == "provider_quote_time"
    assert with_provider["underlying_price_time"] == CLOSE_QUOTE


def test_snapshot_next_refresh_reads_the_active_crontab_lines():
    sch = acc.producer_schedule(match="run_options_monitor.sh", lane="run-options-monitor", crontab_text=CRONTAB)
    assert sch["schedules"] == ["*/10 12-15 * * 1-5", "5 16 * * 1-5"] and sch["source"] == "crontab"
    snap = acc.snapshot_block("2026-10-22T13:30:15+00:00", now=NOW_REGULAR, schedule=sch)
    assert snap["age_s"] == pytest.approx(5213, abs=1)
    assert snap["next_scheduled_refresh"] == "2026-10-22T12:00:00-04:00"
    assert snap["session_at_generation"] == "REGULAR"
    reg = {"lanes": [{"lane_id": "run-options-monitor", "scheduler": {"schedules": ["5 16 * * 1-5"]}}]}
    fb = acc.producer_schedule(match="run_options_monitor.sh", lane="run-options-monitor", registry=reg)
    assert fb["source"] == "lane_registry"
    assert acc.next_scheduled(fb["schedules"], NOW_REGULAR) == "2026-10-22T16:05:00-04:00"


# ── 3. lifecycle-aware Next / Owner ──────────────────────────────────────────

def test_review_failure_cap_names_the_policy_refusal_and_the_operator():
    wf = review_workflow(_spcx(), now=NOW_REGULAR)
    assert wf["lifecycle_stage"] == "REVIEW_FAILURE_CAP"
    assert wf["next_action"] == ("CIO review stopped after 3 failures (policy refusal POLICY_NOT_ALLOWED)"
                                 " · operator reopen needed")
    assert wf["owner"] == "Operator" and wf["state"] == "BLOCKED"
    card = _spcx()
    acc.stamp_lifecycle_stage(card)
    assert card["lifecycle_stage"] == "REVIEW_FAILURE_CAP" and card["review_failures"] == 3


def test_stale_quote_says_requote_now_in_session_and_after_the_open_otherwise():
    fresh_life = {"stage": "CIO_REVIEW_QUEUED", "timeline": []}
    wf = review_workflow(_spcx(lifecycle=fresh_life), now=NOW_REGULAR)
    assert (wf["state"], wf["next_action"], wf["owner"]) == ("NEEDS_DATA", "Re-quote now", "Quote validation")
    wf = review_workflow(_spcx(lifecycle=fresh_life), now=NOW_PRE)
    assert wf["next_action"] == "Re-quote after the open (market pre market)"


def test_a_decision_resets_the_failure_count():
    card = _spcx()
    card["lifecycle"]["timeline"].append({"stage": "DECISION_ISSUED", "at": "2026-10-22T10:00:00+00:00"})
    card["lifecycle"]["stage"] = "DECISION_ISSUED"
    assert acc.lifecycle_stage(card)["stage"] == "DECISION_ISSUED"
    assert acc.lifecycle_stage(card)["review_failures"] == 0


# ── 4. liquidity-aware edge ──────────────────────────────────────────────────

def test_edge_is_withheld_when_the_liquidity_gate_fails_and_penalised_otherwise():
    bad = _spcx(enterprise={"liquidity": {"pass": False, "issues": ["spread 18.0% > 12.0%"],
                                          "bid_ask_spread_pct": 18.0, "oi": 10, "volume": 0}})
    acc.apply_edge_liquidity(bad, {"min_open_interest": 50})
    assert bad["edge_score"] is None and bad["edge_status"] == "WITHHELD_LIQUIDITY"
    assert "spread 18.0%" in bad["edge_withheld_reason"] and bad["edge_score_raw"] == 68.4
    ok = acc.apply_edge_liquidity(_spcx(), {"min_open_interest": 50})
    # 0.75 x 5.52 = 4.1, + 2 for zero volume (OI 476 is above 2 x 50).
    assert ok["edge_liquidity_penalty"] == 6.1 and ok["edge_score"] == 62.3
    assert ok["edge_inputs"]["conviction_basis"].startswith("fixed placeholder")
    assert acc.apply_edge_liquidity(ok, {"min_open_interest": 50})["edge_score"] == 62.3  # idempotent


# ── 5. CSP on the bid ────────────────────────────────────────────────────────

def _chain(**leg) -> dict:
    base = {"side": "put", "symbol": "SPCX  261120P00144000", "exp": "2026-11-20", "strike": 144.0, "dte": 29,
            "bid": 5.35, "ask": 5.45, "iv": 50.1, "delta": -0.347, "oi": 149, "volume": 6, "spread_pct": 1.9,
            "two_sided": True, "quote_time": "2026-10-22T14:45:01+00:00"}
    base.update(leg)
    return {"underlying_price": 156.6, "expirations": [{"exp": "2026-11-20", "strikes": [base]}]}


def test_intent_csp_credit_and_yield_are_on_the_bid():
    row = rk.rank_csp(_chain(), {"dte": [25, 45], "delta": [0.15, 0.35]})[0]
    assert row["credit_per_contract"] == 535.0 and row["credit_basis"] == "bid"
    assert row["credit_per_contract_at_mid"] == 540.0
    assert row["premium_over_collateral_pct"] == pytest.approx(3.715, abs=0.001)
    assert row["simple_annualized_yield_pct"] == 46.8 and row["annualized_pct"] == 46.8
    assert row["breakeven"] == pytest.approx(138.65)
    assert "not repeatable" in row["yield_basis"]
    assert row["not_applicable_metrics"] == ["risk_reward", "max_loss_to_zero"]


def test_desk_csp_card_marks_reward_risk_not_applicable():
    card = acc.apply_csp_metrics({"strategy": "cash_secured_put", "bid": 2.0, "premium": 2.0, "strike": 100.0,
                                  "dte": 30, "risk_reward": 0.02})
    assert card["risk_reward"] is None
    assert card["premium_over_collateral_pct"] == 2.0 and card["simple_annualized_yield_pct"] == 24.3
    assert "max_loss_to_zero" in card["not_applicable_metrics"]


def test_engine_csp_premium_and_edge_use_the_bid(monkeypatch):
    import options_engine as oe
    monkeypatch.setattr(oe, "_DESK_CFG", {})
    monkeypatch.setattr(oe, "_stamp_execution", lambda row, acct, holdings: row)
    monkeypatch.setattr(oe, "_build_reasoning", lambda *a, **k: "")
    monkeypatch.setattr(oe, "_execution_note", lambda *a, **k: "")
    out: list = []
    contract = {"mid": 2.5, "bid": 2.0, "ask": 3.0, "strike": 90.0, "dte": 30, "iv": 0.6, "exp": "2026-11-20"}
    oe._append_csp_proposal(out, sym="XYZ", und=100.0, conf=0.9, iv_rank=80.0, c={}, contract=contract,
                            data_source="schwab_chain", account="schwab_taxable")
    assert len(out) == 1
    assert out[0]["premium"] == 2.0 and out[0]["premium_midpoint"] == 2.5
    assert out[0]["premium_total"] == 200.0 and out[0]["max_profit"] == 200.0


# ── 6. both earnings dates ───────────────────────────────────────────────────

def test_matcher_keeps_both_earnings_dates_and_avoids_the_earlier():
    intent = {"symbol": "SPCX", "earnings_estimate": "2026-11-03", "avoid_earnings_cross": True,
              "plays": {"cash_secured_put": {"dte": [25, 45], "delta": [0.15, 0.35]}}}
    m = mt.match_intent(intent, chain_fn=lambda s, side: _chain(), holdings=[],
                        earnings_fn=lambda s: {"date": "2027-02-09", "source": "options desk earnings gate"},
                        now=NOW_REGULAR)
    e = m["earnings"]
    assert e["provider_date"] == "2027-02-09" and e["operator_estimate"] == "2026-11-03"
    assert e["conflict"] is True and e["conflict_days"] == 98
    assert e["date"] == "2026-11-03"
    # The 2026-11-20 put crosses the operator's estimate, so it is not offered.
    assert m["plays"]["cash_secured_put"] == []


# ── 7. execution state text ──────────────────────────────────────────────────

def test_execution_state_text_is_plain_and_read_only():
    es = acc.execution_state(True, [_spcx(), _spcx(id="b")])
    assert es["text"] == ("Manual only: you can send an approved option order yourself with per-order 2FA. "
                          "Nothing trades automatically. 0 of 2 ideas eligible now.")
    assert es["automatic_trading"] is False
    assert acc.execution_state(False, [])["state"] == "OFF"
    assert acc.execution_state(None, [])["state"] == "UNKNOWN"


# ── 8. intent vs hedge conflict ──────────────────────────────────────────────

def test_hedge_on_an_accumulate_intent_is_flagged():
    intents = [{"symbol": "SPCX", "status": "active", "goals": ["accumulate", "income"], "directive_id": 17}]
    rows = acc.intent_conflicts([_spcx(), _spcx(symbol="XLB", id="x")], intents)
    assert [r["kind"] for r in rows] == ["HEDGE_VS_ACCUMULATE"]
    assert "accumulate shares and earn income" in rows[0]["text"]
    rows = acc.intent_conflicts([{"id": "c", "symbol": "V", "strategy": "cash_secured_put"}],
                                [{"symbol": "V", "status": "active", "goals": ["reduce"]}])
    assert rows[0]["kind"] == "ACCUMULATE_VS_HEDGE"


# ── 9. per-account grouping ──────────────────────────────────────────────────

def test_same_contract_in_two_accounts_is_one_group():
    a, b = _spcx(), _spcx(id="t", account="schwab_taxable", contracts=2)
    groups = acc.proposal_groups([a, b, _spcx(id="x", symbol="XLB", contract_guid="g2")])
    assert len(groups) == 1 and groups[0]["account_count"] == 2
    assert {leg["account"] for leg in groups[0]["legs"]} == {"schwab_rollover_ira", "schwab_taxable"}
    assert a["group_key"] == b["group_key"] == "SPCX|protective_put|f75a0c29" and a["group_size"] == 2


# ── 10. honest coverage ──────────────────────────────────────────────────────

def test_disabled_expanded_scan_is_not_pending_work():
    rows = ([{"symbol": f"W{i}", "status": "PENDING", "source_lanes": ["watchlist"], "accounts": []} for i in range(5)]
            + [{"symbol": "H", "status": "PENDING", "source_lanes": ["holdings"], "accounts": [{"account": "a"}]}]
            + [{"symbol": "E", "status": "EVALUATED", "source_lanes": ["holdings"], "accounts": []}])
    cov = acc.honest_coverage({"status_counts": {"PENDING": 6, "EVALUATED": 1}, "rows": rows}, scan_enabled=False)
    assert cov["status_counts"] == {"EVALUATED": 1, "PENDING": 1, acc.NOT_SCANNED: 5}
    assert cov["not_scanned"] == {"count": 5, "reason": "not scanned (expanded scan disabled)"}
    assert cov["pending_evaluation_count"] == 1 and cov["status_counts_raw"]["PENDING"] == 6
    assert acc.honest_coverage(cov, scan_enabled=False)["status_counts"] == cov["status_counts"]  # idempotent
    on = acc.honest_coverage({"status_counts": {"PENDING": 6}, "rows": []}, scan_enabled=True)
    assert on["status_counts"] == {"PENDING": 6} and on["not_scanned"] is None


# ── 11. lifecycle tab freshness ──────────────────────────────────────────────

def test_paused_lifecycle_producer_is_named_with_its_date():
    payload = {"generated_at": "2026-10-14T19:40:03+00:00",
               "health": [{"check": "monitor_freshness", "ok": True,
                           "detail": "lifecycle payload 20 min old; covers last scheduled fire (Wed 15:40 ET)"}]}
    acc.lifecycle_freshness(payload, now=NOW_REGULAR, crontab_text=CRONTAB)
    f = payload["freshness"]
    assert f["state"] == "PAUSED" and f["paused_since"] == "2026-10-14"
    assert f["text"].startswith("PAUSED since 2026-10-14 (schwab-app-deactivated (incident SPCX))")
    assert "7.8 days old" in f["text"]
    h = payload["health"][0]
    assert h["ok"] is False and h["detail_at_write"].startswith("lifecycle payload 20 min old")


def test_unpaused_lifecycle_payload_goes_stale_by_serve_time_age():
    live = CRONTAB.replace("# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) ", "")
    payload = {"generated_at": "2026-10-22T13:00:00+00:00"}
    acc.lifecycle_freshness(payload, now=NOW_REGULAR, crontab_text=live)
    assert payload["freshness"]["state"] == "STALE"
    assert payload["freshness"]["next_scheduled_run"] == "2026-10-22T11:00:00-04:00"


# ── 12. blocked approval-queue rows expire ───────────────────────────────────

class _Cur:
    def __init__(self, found):
        self.sql, self.found = [], found

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.found


def test_expiry_sweep_closes_blocked_rows_and_dry_run_writes_nothing():
    import options_desk_enterprise as ode
    dry = _Cur([("blocked", 7), ("pending", 1)])
    out = ode.expire_stale_queue_rows(dry, apply=False)
    assert out == {"dry_run": True, "would_expire": {"blocked": 7, "pending": 1}, "total": 8}
    assert all(s.startswith("SELECT") for s, _ in dry.sql)
    live = _Cur([("blocked", 7)])
    ode.expire_stale_queue_rows(live, apply=True)
    update, params = live.sql[-1]
    assert update.startswith("UPDATE options_approval_queue")
    assert "status IN ('pending','blocked') AND expires_at < NOW()" in update
    assert "reviewer='system_expiry'" in update and "status='rejected'" in update
    assert params == (ode.QUEUE_EXPIRY_NOTES["blocked"], ode.QUEUE_EXPIRY_NOTES["pending"])


def test_sync_approval_queue_runs_the_widened_sweep(monkeypatch):
    import options_desk_enterprise as ode
    cur = _Cur([])

    class _Conn:
        def cursor(self):
            return cur

        def commit(self):
            pass

    monkeypatch.setattr(ode, "_conn", lambda: _Conn())
    monkeypatch.setattr(ode, "load_desk_config", lambda: {"approval_required": True})
    ode.sync_approval_queue([], apply=True)
    assert any("status IN ('pending','blocked')" in s and s.startswith("UPDATE") for s, _ in cur.sql)


# ── 13. abandon before the liquidity skip ────────────────────────────────────

def test_liquidity_blocked_idea_is_still_abandoned_after_the_window(tmp_path):
    from lib import options_thesis as ot
    from lib import options_thesis_lifecycle as lc
    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    store = ot.OptionsThesisStore(tmp_path / "t.jsonl")
    store._append({"event_type": "OPTIONS_THESIS_VERSION", "position_guid": "g1", "version": 1,
                   "pin": "opt_g1@v1", "recorded_at": t0.isoformat()})
    p = {"symbol": "XAR", "strategy": "protective_put", "option_strategy_guid": "g1", "expiration": "2026-11-20",
         "options_thesis": {"pin": "opt_g1@v1", "missing_required": ["catalysts"]},
         "enterprise": {"blocks": ["OI 3 < 50"]}}

    def run(now):
        return lc.advance([p], store, {"options_thesis_lifecycle": {"abandon_after_hours": 48}},
                          request_research=lambda *_a, **_k: {"research_id": "r"},
                          research_status=lambda rid: {"status": "queued"},
                          review_fn=lambda *_a: {"status": "DRY_RUN"}, record_decision=lambda r: None,
                          apply=True, now=now)

    assert run(t0 + timedelta(hours=2))[0]["action"] == "SKIP_ENTERPRISE_BLOCK"
    step = run(t0 + timedelta(hours=49))[0]
    assert step["action"] == "ABANDON" and "liquidity" in step["reason"]
    assert store.lifecycle("g1")["stage"] == "ARCHIVED_ABANDONED"


# ── 14. watch-only intents ───────────────────────────────────────────────────

def test_intent_not_tied_to_a_holding_is_watch_only():
    nflx = {"symbol": "NFLX"}
    assert acc.holding_flags(nflx, {"shares_by_account": {}}, None) == {
        "held": False, "shares_held_total": 0, "watch_only": True, "held_source": "match.shares_by_account"}
    held = acc.holding_flags({"symbol": "SPCX"}, None, [{"symbol": "SPCX", "shares": 600}, {"symbol": "X", "shares": 1}])
    assert held["held"] is True and held["watch_only"] is False and held["shares_held_total"] == 600


# ── 15. avg POP null, not zero ───────────────────────────────────────────────

def test_overview_avg_pop_is_null_when_no_card_has_pop(monkeypatch):
    import options_engine as oe
    monkeypatch.setattr(oe, "read_proposals", lambda: {
        "generated_at": "2026-10-22T13:30:15+00:00",
        "strategy_overview": {"avg_pop": 0.0, "total_edge_avg": 64.7},
        "proposals": [{"pop_pct": None, "edge_score": 60.0}, {"pop_pct": None, "edge_score": None}]})
    monkeypatch.setattr(oe, "_load_json", lambda path: {})
    ov = oe.get_overview()["proposals"]
    assert ov["avg_pop"] is None and ov["avg_pop_n"] == 0
    assert ov["total_edge_avg"] == 60.0 and ov["total_edge_n"] == 1
    assert oe._avg_or_none([None, None]) is None
