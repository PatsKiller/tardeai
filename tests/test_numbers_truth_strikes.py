"""The numbers-truth strike ladder (LQ-20261107-1702, DSN-20261109 sections 3 / REV 2 D,E / REV 3 G,H).

Every test here is synthetic: inline findings, an in-memory state, an explicit clock, and injected heal / escalate /
ticket / critical callables that record what they were asked to do. Nothing reads a live store, the DB, the network or
the coordination ledger.

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
 11. a NEW ticket pages email + Telegram + Fi text promptly (23:00 ET, inside the notifier's quiet window); a cleared
     line never pages; a hub that cannot be reached is a named count, not a crash
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from lib import critical_texts as CT
from lib import numbers_truth_strikes as S

NOW = datetime(2026, 11, 9, 22, 7, tzinfo=timezone.utc)
#: 23:05 ET on 2026-11-09 (EST, UTC-5) — inside the incident notifier's 22:00–07:00 ET quiet window, which is exactly
#: where a DIGEST/P2 escalation is held until morning. The page must not be held there.
NIGHT = datetime(2026, 11, 10, 4, 5, tzinfo=timezone.utc)
ET = ZoneInfo("America/New_York")
#: Synthetic operator contact. The real one is private and lives under the persistent-state root, never in this repo.
CONTACT = {"schema": "OperatorContact@v1", "critical_email_to": "operator@example.invalid",
           "critical_sms_email_gateways": [{"address": "gw-line-1@example.invalid", "label": "line 1",
                                            "verified": True}]}


def write_state(path, figures):
    """Seed a state file the way the module writes one: temp file in the same directory, then os.replace."""
    tmp = path.with_name(path.name + ".fixture-tmp")
    tmp.write_text(json.dumps({"schema": S.STATE_SCHEMA, "figures": figures}), encoding="utf-8")
    os.replace(tmp, path)


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
    write_state(state_path, {
        S.fingerprint("risk", "vix_tile"): {"consecutive_fails": 2, "page": "risk", "figure_id": "vix_tile",
                                            "severity": "P1"}})
    out = S.run(findings=[row], state_path_=state_path, config_path=_config_file(tmp_path),
                apply=True, now=NOW, heal=heal, escalate=lambda **kw: escalations.append(kw) or {"ok": True},
                critical=lambda **kw: {"ok": True, "delivered": True, "receipts": []},
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


def test_a_malformed_finding_holds_its_page_instead_of_clearing_it():
    # a producer emitting a row we cannot key must not read as "the figure we were tracking has passed"
    st = state_with(fail_row(page="risk", figure_id="vix_tile"), fails=2)
    bad = fail_row(page="risk", figure_id="vix_tile")
    bad["fingerprint"] = "risk|vix_tile|too|many|fields"
    out = plan([bad], st)
    (decision,) = out["decisions"]
    assert decision["action"] == "hold" and decision["reason"] == "malformed_findings"
    assert out["figures"][S.fingerprint("risk", "vix_tile")]["consecutive_fails"] == 2


def test_a_malformed_row_too_broken_to_name_a_page_holds_every_page():
    st = state_with(fail_row(page="risk", figure_id="vix_tile"), fails=2)
    out = plan(["not even a mapping"], st)
    (decision,) = out["decisions"]
    assert decision["action"] == "hold" and decision["reason"] == "malformed_findings"
    assert out["figures"][S.fingerprint("risk", "vix_tile")]["consecutive_fails"] == 2


def test_a_recurrence_after_a_clear_opens_a_new_ticket_not_ticket_open():
    # a cleared figure must not keep its old ticket: leaving it set would record every later run as "ticket_open"
    # and never escalate the defect again.
    fp = S.fingerprint("holdings", "qty", None, "XLV")
    st = {"schema": S.STATE_SCHEMA, "figures": {fp: {
        "consecutive_fails": 4, "page": "holdings", "figure_id": "qty", "symbol": "xlv", "severity": "P0",
        "status": "ticketed", "ticket": {"id": "LQ-AUTO-holdings-qty-xlv", "at": "2026-11-09T20:00:00+00:00"}}}}
    out = plan([], st)
    (cleared,) = out["decisions"]
    assert cleared["action"] == S.ACTION_CLEAR and cleared["ticket"] == {"id": "LQ-AUTO-holdings-qty-xlv", "at": "2026-11-09T20:00:00+00:00"}
    row = out["figures"][fp]
    assert "ticket" not in row and row["last_ticket"]["id"] == "LQ-AUTO-holdings-qty-xlv"
    assert row["status"] == "cleared"

    # it fails again, twice (strikes 1-2 after the reset) and then a third time: a fresh ticket, not "ticket_open"
    row["consecutive_fails"] = 2
    out2 = plan([fail_row(page="holdings", figure_id="qty", symbol="XLV")], {"schema": S.STATE_SCHEMA, "figures": {fp: row}})
    (decision,) = out2["decisions"]
    assert decision["action"] == S.ACTION_TICKET and decision["reason"] == "not_healable:positions-sync"
    assert out2["figures"][fp]["ticket"]["id"] == "LQ-AUTO-holdings-qty-xlv"


def test_a_settled_heal_still_counts_against_the_lane_hourly_budget():
    a = fail_row(page="risk", figure_id="vix_tile", symbol="VIX")
    st = state_with(a, fails=2)
    other = S.fingerprint("risk", "index_tile", None, "SPX")
    st["figures"][other] = {"consecutive_fails": 0, "status": "cleared",
                            "last_heal": {"lane": "vix-index-quotes-schwab", "requested_at": "2026-11-09T21:57:00+00:00",
                                          "state": "cleared"}}
    out = plan([a], st)
    (decision,) = out["decisions"]
    assert decision["action"] == S.ACTION_TICKET
    assert decision["reason"] == "heal_rate_limited:vix-index-quotes-schwab"


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
    write_state(state_path, {
        S.fingerprint("risk", "vix_tile"): {"consecutive_fails": 2, "page": "risk", "figure_id": "vix_tile",
                                            "severity": "P1"}})
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
    write_state(state_path, {fp: {
        "consecutive_fails": 2, "page": "holdings", "figure_id": "qty", "account": "acct1", "symbol": "xlv",
        "severity": "P0"}})
    escalations = []
    out = S.run(findings=[row], state_path_=state_path, config_path=_config_file(tmp_path), apply=True, now=NOW,
                heal=lambda **kw: {"accepted": False, "reason": "never"},      # not reached: not healable
                escalate=lambda **kw: escalations.append(kw) or {"ok": True, "queued": True},
                critical=lambda **kw: {"ok": True, "delivered": True, "receipts": []},
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


# ── 11. the prompt page: a NEW ticket reaches all three channels (DSN-20261109 REV 3 H) ─────────────────────────


def test_the_ticket_class_is_enabled_for_text():
    """The one config link the text channel depends on: the hub refuses a class absent from the operator's allowlist
    (``assert_critical_class``) and skips a class present-but-disabled, so the page carries a text only while this
    entry is on. Pinned here because deleting the entry would otherwise show up only as a skipped receipt at 03:00."""
    assert CT.class_enabled(CT.load_policy(), S.CRITICAL_CLASS) is True


def test_a_new_ticket_at_2300_et_pages_email_telegram_and_fi_text_promptly(tmp_path, monkeypatch):
    """The lead's test: a NEW fingerprint at 23:00 ET produces the intent AND a page on all three channels.

    The page is the REAL production wrapper (`S.deliver_critical`) and the REAL D34 hub and allowlist; only the three
    transports are injected, so nothing leaves the process. A DIGEST/P2 intent would be held overnight here — the
    assertion that the run's clock is inside the quiet window is what makes that difference explicit.
    """
    monkeypatch.setenv("TRADEAI_CRITICAL_ALERT_CHAT_ID", "chat-fixture")
    assert NIGHT.astimezone(ET).hour == 23

    row = fail_row(page="holdings", figure_id="qty", symbol="XLV", account="acct1", served=0, truth=100,
                   detail="row renders 0 shares; positions_current says 100")
    fp = S.fingerprint("holdings", "qty", "acct1", "XLV")
    state_path = tmp_path / "state.json"
    write_state(state_path, {fp: {"consecutive_fails": 2, "page": "holdings", "figure_id": "qty",
                                  "account": "acct1", "symbol": "xlv", "severity": "P0"}})

    intents, sends, events = [], [], []

    def page(**kw):
        return S.deliver_critical(
            kw["decision"], now=kw["now"], contact=CONTACT,
            telegram_sender=lambda chat, text: sends.append(("telegram", chat, text)) or "mid-1",
            email_sender=lambda to, subject, body: sends.append(("email", to, subject, body)) or "gog-accepted",
            text_sender=lambda event: events.append(event) or {"sent": True},
        )

    out = S.run(findings=[row], state_path_=state_path, config_path=_config_file(tmp_path), apply=True, now=NIGHT,
                heal=lambda **kw: {"accepted": False, "reason": "never"},   # not healable: tickets at strike 3
                escalate=lambda **kw: intents.append(kw) or {"ok": True, "queued": True, "intent_id": "i1"},
                critical=page, inbox=tmp_path / "inbox")

    # the durable record still exists: the intent is queued (and its P2 copy is mirrored to email by config)
    assert [i["kind"] for i in intents] == ["numbers_truth_ticket"]
    # and the page went out, at 23:00 ET, on every channel (the text sender also hands us the event it was given)
    assert [s[0] for s in sends] == ["telegram", "email"]
    assert len(events) == 1
    delivery = out["actions"][0]["taken"]["critical"]
    assert {r["channel"]: r["status"] for r in delivery["receipts"]} == {
        "telegram_critical": "sent", "email": "sent", "text_gateway": "sent"}
    assert out["counts"]["paged"] == 1 and out["counts"]["page_failed"] == 0

    # the event itself: the class the allowlist enables, both sides with timestamps, deduped by ticket id, and a
    # sentence the text primitive accepts (it would refuse an over-cap or URL-carrying one)
    (event,) = events
    assert event["alert_class"] == S.CRITICAL_CLASS
    assert event["event_id"] == S.ticket_id(fp)
    assert "qty FAIL 3x" in event["trigger"]
    assert "0 (served-json @ 2026-11-09T22:00:00+00:00)" in event["trigger"]
    assert "100 (db @ 2026-11-09T21:59:30+00:00)" in event["trigger"]
    text = CT.format_text(event, max_chars=CT.MAX_TEXT_CHARS)
    assert text.endswith("CC Risk") and "check the figure's source" in text


def test_a_cleared_line_never_pages_and_rides_the_intent_only(tmp_path):
    """REV 3 H: "cleared" is Telegram + email, never a text. A clear must not touch the critical hub at all."""
    fp = S.fingerprint("holdings", "qty", "acct1", "xlv")
    state_path = tmp_path / "state.json"
    write_state(state_path, {fp: {
        "consecutive_fails": 4, "status": "ticketed", "page": "holdings", "figure_id": "qty", "account": "acct1",
        "symbol": "xlv", "severity": "P0",
        "ticket": {"id": S.ticket_id(fp), "at": "2026-11-09T20:00:00+00:00"}}})

    def boom(**kw):  # pragma: no cover - it must never run
        raise AssertionError("a cleared line must never page")

    kinds = []
    out = S.run(findings=[], state_path_=state_path, config_path=_config_file(tmp_path), apply=True, now=NIGHT,
                escalate=lambda **kw: kinds.append(kw["kind"]) or {"ok": True, "queued": True},
                critical=boom, inbox=tmp_path / "inbox")

    assert [a["action"] for a in out["actions"]] == [S.ACTION_CLEAR]
    assert kinds == ["numbers_truth_cleared"]
    assert out["counts"]["paged"] == 0 and out["counts"]["page_failed"] == 0


def test_a_page_callable_that_raises_still_lets_the_run_save_its_state(tmp_path):
    """Belt and braces around `deliver_critical`'s own guard: whatever a page callable does, the run must reach
    save_state. Otherwise the next hourly run re-opens the same ticket and pages the operator again, every hour."""
    row = fail_row(page="holdings", figure_id="qty", symbol="XLV", account="acct1", served=0, truth=100)
    fp = S.fingerprint("holdings", "qty", "acct1", "XLV")
    state_path = tmp_path / "state.json"
    write_state(state_path, {fp: {"consecutive_fails": 2, "page": "holdings", "figure_id": "qty",
                                  "account": "acct1", "symbol": "xlv", "severity": "P0"}})

    def boom(**kw):  # pragma: no cover - only the wrapper is exercised
        raise ValueError("callable broke")

    out = S.run(findings=[row], state_path_=state_path, config_path=_config_file(tmp_path), apply=True, now=NIGHT,
                heal=lambda **kw: {"accepted": False, "reason": "never"},
                escalate=lambda **kw: {"ok": True, "queued": True}, critical=boom, inbox=tmp_path / "inbox")

    assert out["actions"][0]["taken"]["critical"] == {"ok": False, "delivered": False,
                                                     "reason": "critical_call_error:ValueError"}
    assert out["counts"]["page_failed"] == 1
    assert json.loads(state_path.read_text())["figures"][fp]["status"] == "ticketed"


def test_a_page_the_hub_cannot_send_is_a_named_outcome_not_a_crash(tmp_path):
    """A hub that cannot be reached (the class removed from the allowlist, the module missing) must not take the
    audit down: the run still records the state and the intent, and the failure is visible as a count."""
    row = fail_row(page="holdings", figure_id="qty", symbol="XLV", account="acct1", served=0, truth=100)
    fp = S.fingerprint("holdings", "qty", "acct1", "XLV")
    state_path = tmp_path / "state.json"
    write_state(state_path, {fp: {"consecutive_fails": 2, "page": "holdings", "figure_id": "qty",
                                  "account": "acct1", "symbol": "xlv", "severity": "P0"}})

    class BrokenHub:
        def deliver(self, event, **kw):  # noqa: ARG002 -- the signature is the point, the arguments are unused
            raise RuntimeError("smtp down")

    out = S.run(findings=[row], state_path_=state_path, config_path=_config_file(tmp_path), apply=True, now=NIGHT,
                heal=lambda **kw: {"accepted": False, "reason": "never"},
                escalate=lambda **kw: {"ok": True, "queued": True},
                critical=lambda **kw: S.deliver_critical(kw["decision"], now=kw["now"], hub=BrokenHub()),
                inbox=tmp_path / "inbox")

    critical = out["actions"][0]["taken"]["critical"]
    assert critical == {"ok": False, "delivered": False, "reason": "critical_hub_error:RuntimeError"}
    assert out["ok"] is True and out["counts"]["tickets"] == 1
    assert out["counts"]["paged"] == 0 and out["counts"]["page_failed"] == 1
    assert json.loads(state_path.read_text())["figures"][fp]["ticket"]["id"] == S.ticket_id(fp)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
