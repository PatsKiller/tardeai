"""The numbers-truth strike ladder (LQ-20261107-1702, DSN-20261109 sections 3 / REV 2 D,E / REV 3 G,H).

Every test here is synthetic: inline findings, an in-memory state, an explicit clock, and injected heal / escalate /
ticket callables that record what they were asked to do. Nothing reads a live store, the DB, the network or the
coordination ledger.

The behaviours pinned, one class each:

  1. strikes 1-2 record and alert nothing; the third asks for exactly one heal of a healable producer
  2. a KEEP_ON_CRON producer, an unmapped figure and an authority finding never heal: they ticket at strike 3
  3. one heal per lane per hour, even across two figures of the same lane
  4. a refused heal tickets in the same run (it is strike 3 with nothing healed)
  5. strike 4 tickets; a repeated failure of an already-ticketed figure does not ticket twice
  6. NOT_MEASURED holds the counter: it neither strikes nor clears, and an unreadable truth is never a pass
  7. a measured pass clears once, with one line; a figure the run did not audit holds instead of clearing
  8. malformed findings are reported and strike nothing
  9. a dry run writes nothing and calls nothing
 10. an apply run writes the atomic state and the escalation carries BOTH sides with their timestamps
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from lib import numbers_truth_strikes as S

NOW = datetime(2026, 11, 9, 22, 7, tzinfo=timezone.utc)


def fail_row(page="risk", figure_id="vix_tile", account=None, symbol=None, *, severity="P1", check=None,
             served=18.5, truth=19.1, served_as_of="2026-11-09T22:00:00+00:00",
             truth_as_of="2026-11-09T21:59:30+00:00", family=None, detail=None):
    return {
        "page": page, "figure_id": figure_id, "account": account, "symbol": symbol,
        "severity": severity, "verdict": "FAIL", "check": check or figure_id, "family": family,
        "served": {"value": served, "source": "served-json", "as_of": served_as_of},
        "truth": {"value": truth, "source": "db", "as_of": truth_as_of},
        "tolerance": "0.005", "detail": detail,
    }


def nm_row(page="risk", figure_id="vix_tile", *, symbol=None):
    return {"page": page, "figure_id": figure_id, "symbol": symbol, "severity": "P1",
            "verdict": "NOT_MEASURED", "check": figure_id,
            "truth": {"value": None, "source": "db", "as_of": None}}


def state_with(*rows, fails=1):
    figures = {}
    for row in rows:
        fp = S.fingerprint(row["page"], row["figure_id"], row.get("account"), row.get("symbol"))
        figures[fp] = {"consecutive_fails": fails, "first_seen_at": "2026-11-09T19:07:00+00:00",
                       "last_seen_at": "2026-11-09T21:07:00+00:00", "page": row["page"],
                       "figure_id": row["figure_id"], "account": row.get("account"), "symbol": row.get("symbol"),
                       "severity": row.get("severity"), "check": row.get("check")}
    return {"schema": S.STATE_SCHEMA, "figures": figures}


CONFIG = {
    "rate_limit": {"per_lane_per_hour": 1},
    "healable": {"vix-index-quotes-schwab": {"mode": "dry_run"},
                 "cio-overnight-brief": {"mode": "live"},
                 "holdings-drift-monitor": {"mode": "dry_run"},
                 "held-exit-coverage-monitor": {"mode": "dry_run"}},
    "by_figure_id": {"vix_tile": "vix-index-quotes-schwab", "now_price": "cio-overnight-brief",
                     "stop_state": "held-exit-coverage-monitor", "qty": "positions-sync",
                     "day_pnl": "market-quotes-*"},
    "by_page": {},
    "default_lane": None,
    "escalation": {"domain": "data", "kind_ticket": "numbers_truth_ticket",
                   "kind_cleared": "numbers_truth_cleared"},
}


def plan(findings, state=None, **kw):
    return S.plan(findings=findings, state=state or S.empty_state(), config=CONFIG, now=kw.pop("now", NOW), **kw)


# ── 1. strikes 1-2, then one heal ────────────────────────────────────────────────────────────────────────────────


def test_two_failures_record_and_alert_nothing():
    out = plan([fail_row()], state_with(fail_row(), fails=1))
    assert out["counts"]["fail"] == 1
    assert [d["action"] for d in out["decisions"]] == [S.ACTION_RECORD]
    assert out["decisions"][0]["fails"] == 2
    assert out["decisions"][0]["reason"] == "strike_recorded"


def test_the_third_failure_asks_for_exactly_one_heal_of_the_producer():
    out = plan([fail_row()], state_with(fail_row(), fails=2))
    (decision,) = out["decisions"]
    assert decision["action"] == S.ACTION_HEAL
    assert decision["lane"] == "vix-index-quotes-schwab"
    assert decision["mode"] == "dry_run"
    assert out["counts"]["heals"] == 1 and out["counts"]["tickets"] == 0
    assert out["figures"][decision["fingerprint"]]["status"] == "healing"


# ── 2. what never heals ──────────────────────────────────────────────────────────────────────────────────────────


def test_a_keep_on_cron_producer_tickets_at_strike_three():
    out = plan([fail_row(page="holdings", figure_id="qty", symbol="XLV", account="acct1")],
               state_with(fail_row(page="holdings", figure_id="qty", symbol="XLV", account="acct1"), fails=2))
    (decision,) = out["decisions"]
    assert decision["action"] == S.ACTION_TICKET
    assert decision["reason"] == "not_healable:positions-sync"
    assert decision["fails"] == 3


def test_an_unmapped_figure_tickets_at_strike_three():
    cfg = {**CONFIG, "by_figure_id": {}}
    out = S.plan(findings=[fail_row(page="prospectus", figure_id="cash_flow")],
                 state=S.empty_state(), config=cfg, now=NOW)
    assert out["decisions"][0]["action"] == S.ACTION_RECORD          # strike 1 first
    st = state_with(fail_row(page="prospectus", figure_id="cash_flow"), fails=1)
    out = S.plan(findings=[fail_row(page="prospectus", figure_id="cash_flow")], state=st, config=cfg, now=NOW)
    assert out["decisions"][0]["action"] == S.ACTION_RECORD
    st = {"schema": S.STATE_SCHEMA, "figures": {S.fingerprint("prospectus", "cash_flow"): {
        "consecutive_fails": 2, "page": "prospectus", "figure_id": "cash_flow", "severity": "P1"}}}
    out = S.plan(findings=[fail_row(page="prospectus", figure_id="cash_flow")], state=st, config=cfg, now=NOW)
    (decision,) = out["decisions"]
    assert decision["action"] == S.ACTION_TICKET and decision["reason"] == "no_heal_mapped"


def test_an_authority_finding_never_heals_even_for_a_healable_figure():
    # REV 3 G: a source change is operator-only, so a healable lane mapping must not be used.
    out = plan([fail_row(family="authority")], state_with(fail_row(), fails=2))
    (decision,) = out["decisions"]
    assert decision["action"] == S.ACTION_TICKET
    assert decision["reason"] == "authority_finding"


# ── 3. rate limit ───────────────────────────────────────────────────────────────────────────────────────────────


def test_one_heal_per_lane_per_hour_across_two_figures():
    a = fail_row(page="risk", figure_id="vix_tile", symbol="VIX")
    b = fail_row(page="risk", figure_id="vix_tile", symbol="SPX")
    state = state_with(a, b, fails=2)
    out = plan([a, b], state)
    actions = sorted(d["action"] for d in out["decisions"])
    assert actions == [S.ACTION_HEAL, S.ACTION_TICKET]
    ticket = [d for d in out["decisions"] if d["action"] == S.ACTION_TICKET][0]
    assert ticket["reason"] == "heal_rate_limited:vix-index-quotes-schwab"
    # the healing row's own heal does not count as "used" twice; one heal in the run either way
    assert out["counts"]["heals"] == 1


def test_a_heal_requested_an_hour_ago_does_not_block_a_new_one():
    a = fail_row(page="risk", figure_id="vix_tile", symbol="VIX")
    state = state_with(a, fails=2)
    row = state["figures"][S.fingerprint("risk", "vix_tile", None, "VIX")]
    row["heal"] = {"lane": "vix-index-quotes-schwab", "requested_at": "2026-11-09T20:00:00+00:00", "state": "REFUSED"}
    out = plan([a], state)
    assert out["decisions"][0]["action"] == S.ACTION_HEAL


# ── 4. a refused heal ───────────────────────────────────────────────────────────────────────────────────────────


def test_a_refused_heal_tickets_in_the_same_run(tmp_path):
    calls = []

    def heal(**kw):
        calls.append(kw)
        return {"ok": False, "accepted": False, "state": "REFUSED", "reason": "mode_unavailable:live", "run_id": "r1"}

    escalations = []
    row = fail_row()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"schema": S.STATE_SCHEMA, "figures": {
        S.fingerprint("risk", "vix_tile"): {"consecutive_fails": 2, "page": "risk", "figure_id": "vix_tile",
                                            "severity": "P1"}}}))
    out = S.run(findings=[row], state_path_=state_path, config_path=_config_file(tmp_path),
                apply=True, now=NOW, heal=heal, escalate=lambda **kw: escalations.append(kw) or {"ok": True},
                inbox=tmp_path / "inbox")
    assert len(calls) == 1
    assert out["actions"][0]["action"] == S.ACTION_TICKET
    assert out["actions"][0]["taken"]["heal"]["state"] == "REFUSED"
    assert len(escalations) == 1


# ── 5. strike 4 and dedup ───────────────────────────────────────────────────────────────────────────────────────


def test_strike_four_tickets_and_a_repeat_does_not_ticket_twice(tmp_path):
    row = fail_row()
    fp = S.fingerprint(row["page"], row["figure_id"], row["account"], row["symbol"])
    state = {"schema": S.STATE_SCHEMA, "figures": {fp: {
        "consecutive_fails": 3, "status": "healing", "page": "risk", "figure_id": "vix_tile",
        "severity": "P1", "heal": {"lane": "vix-index-quotes-schwab", "requested_at": "2026-11-09T21:07:00+00:00",
                                   "state": "ACCEPTED"}}}}
    out = plan([row], state)
    (decision,) = out["decisions"]
    assert decision["action"] == S.ACTION_TICKET and decision["reason"] == "strike_4"
    assert decision["ticket_id"] if "ticket_id" in decision else True
    # next hour, still failing: one record, no second ticket, and the ticket stays on the row
    figures = out["figures"]
    out2 = S.plan(findings=[row], state={"figures": figures}, config=CONFIG, now=NOW + timedelta(hours=1))
    (d2,) = out2["decisions"]
    assert d2["action"] == S.ACTION_RECORD and d2["reason"] == "ticket_open"
    assert out2["counts"]["tickets"] == 0


# ── 6. NOT_MEASURED ────────────────────────────────────────────────────────────────────────────────────────────


def test_not_measured_holds_the_counter_and_never_clears():
    row = fail_row()
    st = state_with(row, fails=2)
    out = plan([nm_row()], st)
    (decision,) = out["decisions"]
    assert decision["action"] == "hold" and decision["fails"] == 2
    assert out["figures"][S.fingerprint("risk", "vix_tile")]["consecutive_fails"] == 2
    assert out["counts"]["cleared"] == 0
    # the next measured failure is strike 3, not strike 1
    out2 = S.plan(findings=[row], state={"figures": out["figures"]}, config=CONFIG, now=NOW)
    assert out2["decisions"][0]["action"] == S.ACTION_HEAL


def test_an_unreadable_truth_is_never_a_pass():
    out = plan([nm_row()], state_with(fail_row(), fails=1))
    assert out["counts"]["pass"] == 0
    assert out["counts"]["not_measured"] == 1


# ── 7. recovery ────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_failing_figure_clears_when_it_is_no_longer_in_the_findings():
    st = state_with(fail_row(), fails=2)
    out = plan([], st)
    (decision,) = out["decisions"]
    assert decision["action"] == S.ACTION_CLEAR and decision["fails_before"] == 2
    assert S.cleared_line(decision).startswith("cleared:")
    assert out["figures"][S.fingerprint("risk", "vix_tile")]["consecutive_fails"] == 0


def test_a_figure_the_run_did_not_audit_holds_instead_of_clearing():
    st = state_with(fail_row(), fails=2)
    out = plan([], st, audited=[])
    (decision,) = out["decisions"]
    assert decision["action"] == "hold" and decision["reason"] == "not_audited"
    assert out["figures"][S.fingerprint("risk", "vix_tile")]["consecutive_fails"] == 2


# ── 8. malformed input ─────────────────────────────────────────────────────────────────────────────────────────


def test_malformed_findings_are_reported_and_strike_nothing():
    bad = fail_row()
    bad["truth"] = None                       # a FAIL needs both sides
    bad2 = fail_row()
    bad2["verdict"] = "maybe"
    bad3 = fail_row()
    bad3["fingerprint"] = "risk|vix_tile|extra|pipe|field"
    out = plan([bad, bad2, bad3], S.empty_state())
    assert out["counts"]["malformed"] == 3
    assert out["counts"]["fail"] == 0 and out["decisions"] == []


def test_a_finding_fingerprint_that_contradicts_its_fields_is_malformed():
    row = fail_row(symbol="VIX")
    row["fingerprint"] = "risk|vix_tile||spx"
    out = plan([row], S.empty_state())
    assert out["counts"]["malformed"] == 1


# ── 9. dry run ────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_dry_run_writes_nothing_and_calls_nothing(tmp_path):
    def boom(**kw):  # pragma: no cover - it must never run
        raise AssertionError("a dry run must not act")

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"schema": S.STATE_SCHEMA, "figures": {
        S.fingerprint("risk", "vix_tile"): {"consecutive_fails": 2, "page": "risk", "figure_id": "vix_tile",
                                            "severity": "P1"}}}))
    before = state_path.read_text()
    out = S.run(findings=[fail_row()], state_path_=state_path, config_path=_config_file(tmp_path), apply=False,
                now=NOW, heal=boom, escalate=boom, inbox=tmp_path / "inbox")
    assert out["counts"]["heals"] == 1            # planned
    assert out["actions"][0]["would"] is True     # not taken
    assert state_path.read_text() == before
    assert not (tmp_path / "inbox").exists()


# ── 10. apply: state + escalation content ────────────────────────────────────────────────────────────────────────


def test_apply_writes_the_state_atomically_and_escalates_both_sides_with_timestamps(tmp_path):
    row = fail_row(page="holdings", figure_id="qty", symbol="XLV", account="acct1",
                   served=0, truth=100, severity="P0",
                   detail="row renders 0 shares; positions_current says 100")
    state_path = tmp_path / "state.json"
    fp = S.fingerprint("holdings", "qty", "acct1", "XLV")
    state_path.write_text(json.dumps({"schema": S.STATE_SCHEMA, "figures": {fp: {
        "consecutive_fails": 2, "page": "holdings", "figure_id": "qty", "account": "acct1", "symbol": "xlv",
        "severity": "P0"}}}))
    escalations = []
    out = S.run(findings=[row], state_path_=state_path, config_path=_config_file(tmp_path), apply=True, now=NOW,
                heal=lambda **kw: {"accepted": False, "reason": "never"},      # not reached: not healable
                escalate=lambda **kw: escalations.append(kw) or {"ok": True, "queued": True},
                inbox=tmp_path / "inbox")
    assert out["counts"]["tickets"] == 1
    written = json.loads(state_path.read_text())
    assert written["figures"][fp]["consecutive_fails"] == 3
    assert written["figures"][fp]["ticket"]["id"] == S.ticket_id(fp)
    assert written["updated_at"] == "2026-11-09T22:07:00+00:00"
    (esc,) = escalations
    assert esc["domain"] == "data" and esc["kind"] == "numbers_truth_ticket"
    assert "0 (served-json @ 2026-11-09T22:00:00+00:00)" in esc["summary"]
    assert "100 (db @ 2026-11-09T21:59:30+00:00)" in esc["summary"]
    assert "XLV" in esc["subject"] or "xlv" in esc["subject"]
    finding = tmp_path / "inbox" / f"FINDING-{S.ticket_id(fp)}.md"
    assert finding.exists()
    body = finding.read_text()
    assert "served-json @ 2026-11-09T22:00:00+00:00" in body and "db @ 2026-11-09T21:59:30+00:00" in body


def test_pruning_drops_old_settled_rows_and_keeps_an_open_ticket():
    old = (NOW - timedelta(days=9)).isoformat()
    figures = {
        "risk|a||": {"consecutive_fails": 0, "last_seen_at": old},
        "risk|b||": {"consecutive_fails": 1, "last_seen_at": old, "ticket": {"id": "LQ-AUTO-x"}},
    }
    st = {"schema": S.STATE_SCHEMA, "figures": figures}
    dropped = S.prune(st, now=NOW)
    assert dropped == ["risk|a||"]
    assert list(st["figures"]) == ["risk|b||"]


def test_the_core_spelling_is_accepted():
    # LQ-1701 emits status/shown/code; a MISMATCH is a FAIL and `shown` is the served side.
    core = {"fingerprint": "holdings|qty|acct1|XLV", "page": "holdings", "figure_id": "qty",
            "account": "acct1", "symbol": "XLV", "severity": "P0", "status": "MISMATCH",
            "code": "NT_VALUE_MISMATCH", "detail": "acct1 XLV: the page shows 0; truth 100 (positions_current)",
            "shown": {"value": 0, "source": "positions_current", "as_of": "2026-11-09T22:00:00+00:00"},
            "truth": {"value": 100, "provider": "positions_current", "as_of": "2026-11-09T21:59:00+00:00"},
            "domain": "positions", "producer_lane": "positions-sync", "reason": None}
    out = plan([core], S.empty_state())
    assert out["counts"]["malformed"] == 0 and out["counts"]["fail"] == 1
    (decision,) = out["decisions"]
    assert decision["fingerprint"] == "holdings|qty|acct1|xlv"
    assert decision["check"] == "NT_VALUE_MISMATCH"


def test_a_missing_as_of_is_recorded_not_rejected():
    row = fail_row(served_as_of=None, truth_as_of=None)
    out = plan([row], S.empty_state())
    assert out["counts"]["malformed"] == 0
    assert out["decisions"][0]["missing_as_of"] is True


def test_ticket_id_is_stable_and_filename_safe():
    assert S.ticket_id("holdings|qty|acct1|xlv") == "LQ-AUTO-holdings-qty-acct1-xlv"
    assert S.ticket_id("holdings|qty||") == "LQ-AUTO-holdings-qty"


def test_the_heal_lanes_are_the_active_ones_the_design_allows():
    cfg = S.load_config()
    healable = set(cfg["healable"])
    assert healable == {"vix-index-quotes-schwab", "cio-overnight-brief", "holdings-drift-monitor",
                        "held-exit-coverage-monitor"}
    # every configured mode is one the run allowlist actually offers for that lane
    allow = {x["lane_id"]: x for x in json.loads(
        (S._root() / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8")).get("lanes", [])}
    for lane, spec in cfg["healable"].items():
        assert lane in allow, lane
        key = "dry_run_arg" if spec["mode"] == "dry_run" else "live_arg"
        assert allow[lane].get(key) is not None, (lane, spec["mode"])


def _config_file(tmp_path):
    path = tmp_path / "heal.json"
    path.write_text(json.dumps(CONFIG), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
