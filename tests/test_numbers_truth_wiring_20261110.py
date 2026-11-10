"""LQ-20261107-1726 — the audit's findings reach the strike engine, and only the page codes page.

Operator, 2026-11-09 19:00 ET: promote the numbers-truth lane live "and make sure the alerting is turned on".
Before this change nothing called ``numbers_truth_strikes.run()``: ``--apply`` wrote a LaneRunReceipt and stopped.
The contract this module pins:

  * on ``--apply`` the audit feeds its own findings (list M) to the engine, with the engine's state file under the
    lane's state root, after the receipt; a dry run never calls the engine at all;
  * the D34 critical page (Telegram + email + every Fi text line) is reached ONLY by the codes in
    ``config/numbers_truth_heal.json`` ``page_codes`` — a config list, not a literal in the code;
  * every other code produces its ticket, its FINDING file and its state row, and NO text, Telegram or email. The
    escalation intent is itself a Telegram route, so it is gated with the page;
  * a clear reaches Telegram only for a ticket that was paged: a non-paged ticket's clear stays silent;
  * ``known_disagreement`` (operator-approved, dated, reason-carrying) suppresses its own strike and nothing else,
    expires fail-closed on its own date, and is visible in every run it touches.

The replay is the lead's proof, synthetically: 39 findings over four simulated hours, injected senders, a throwaway
state root. Nothing here touches the live store, the coordination ledger, a broker or a network sender; the 1713
guard would raise if a real sender were reached anyway.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import numbers_truth_strikes as S  # noqa: E402

NOW = datetime(2026, 11, 9, 22, 7, tzinfo=timezone.utc)

#: The 19:03 ET shape, by code: 3 P0 page codes and 36 others, one of which is NOT_MEASURED (a hold, never a strike).
PAGE_CODES = ("NT_STOP_PRICE_MISMATCH", "NT_STOP_QTY_MISMATCH", "NT_UNPROTECTED")
OTHER_CODES = {"NT_QUOTE_SOURCE": 18, "NT_AUTHORITY_STATIC": 12, "NT_ACCOUNT_TOTAL_MISMATCH": 2,
               "NT_PRICE_MISMATCH": 2, "NT_TOTAL_MISMATCH": 1, "NT_NOT_MEASURED": 1}

CONFIG = {
    "rate_limit": {"per_lane_per_hour": 1},
    "page_codes": list(PAGE_CODES),
    "known_disagreement": [],
    "healable": {"vix-index-quotes-schwab": {"mode": "dry_run"}, "cio-overnight-brief": {"mode": "live"},
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


@pytest.fixture(autouse=True)
def _no_authority_subprocess(monkeypatch):
    """The authority gate is a 66-second ``check_data_source_authority.py`` run over this repo; these tests are about
    the wiring after the receipt, so the gate is stubbed. Its own behaviour is pinned in the audit's own test module."""
    from scripts import numbers_truth_audit as A

    monkeypatch.setattr(A, "authority_static", lambda **kw: [])


def _config(tmp_path, **overrides):
    path = tmp_path / "heal.json"
    path.write_text(json.dumps({**CONFIG, **overrides}), encoding="utf-8")
    return path


def _finding(code, index, *, status="MISMATCH"):
    """One finding in the audit core's own spelling (LQ-1701): status/shown/code, not verdict/served/check."""
    symbol = f"SYN{index:02d}"
    base = {
        "fingerprint": S.fingerprint("holdings", "qty", "acct-fixture", symbol),
        "page": "holdings", "figure_id": "qty", "account": "acct-fixture", "symbol": symbol,
        "severity": "P0" if code in PAGE_CODES else "P1", "status": status, "code": code,
        "detail": f"{code} synthetic finding {index}",
        "truth": {"value": 100, "provider": "positions_current", "as_of": "2026-11-09T21:59:00+00:00"},
        "domain": "positions", "producer_lane": "positions-sync", "reason": None,
    }
    if status == "MISMATCH":
        base["shown"] = {"value": 0, "source": "served-json", "as_of": "2026-11-09T22:00:00+00:00"}
    else:
        base["truth"] = {"value": None, "provider": None, "as_of": None}
    return base


def replay_findings():
    """39 findings: exactly one per page code, then the 19:03 distribution of the rest."""
    out = [_finding(code, i) for i, code in enumerate(PAGE_CODES)]
    index = len(out)
    for code, count in OTHER_CODES.items():
        for _ in range(count):
            out.append(_finding(code, index, status="NOT_MEASURED" if code == "NT_NOT_MEASURED" else "MISMATCH"))
            index += 1
    assert len(out) == 39
    return out


def _seed_state(path, findings):
    """Every FAIL at strike 3, so the replay's first hour is the ticket hour (strike 4 is the ticket rung)."""
    figures = {}
    for f in findings:
        if f["status"] != "MISMATCH":
            continue
        figures[f["fingerprint"]] = {"consecutive_fails": 3, "status": "healing", "page": f["page"],
                                     "figure_id": f["figure_id"], "account": f["account"],
                                     "symbol": f["symbol"].lower(), "check": f["code"]}
    path.write_text(json.dumps({"schema": S.STATE_SCHEMA, "figures": figures}), encoding="utf-8")


def test_only_the_page_codes_page_across_four_replayed_hours(tmp_path):
    findings = replay_findings()
    state_path = tmp_path / "state.json"
    _seed_state(state_path, findings)
    cfg = _config(tmp_path)

    pages, intents = [], []

    def page(**kw):
        pages.append((kw["now"], kw["decision"]["fingerprint"]))
        return {"ok": True, "delivered": True, "receipts": []}

    def escalate(**kw):
        intents.append(kw)
        return {"ok": True, "queued": True, "intent_id": f"i{len(intents)}"}

    runs = []
    for hour in range(4):
        runs.append(S.run(findings=findings, state_path_=state_path, config_path=cfg, apply=True,
                          now=NOW + timedelta(hours=hour), heal=lambda **kw: {"accepted": False, "reason": "never"},
                          escalate=escalate, critical=page, inbox=tmp_path / "inbox"))

    # exactly the three page fingerprints, once each, over the four hours — and nothing else ever paged
    page_fps = {S.fingerprint("holdings", "qty", "acct-fixture", f"SYN{i:02d}") for i in range(3)}
    assert {fp for _, fp in pages} == page_fps
    assert len(pages) == 3 and len({fp for _, fp in pages}) == 3
    # the escalation intent is a Telegram route, so it is the same three and only in hour one
    assert {kw["fingerprint_"] for kw in intents} == page_fps
    assert [kw["now"] for kw in intents] == [NOW] * 3

    # the first hour tickets every FAIL once and pages the three; hours two-four reopen nothing
    assert runs[0]["counts"]["tickets"] == 38 and runs[0]["counts"]["paged"] == 3
    for later in runs[1:]:
        assert later["counts"]["tickets"] == 0 and later["counts"]["paged"] == 0

    # every non-page ticket says why nothing was sent, and carries no critical/escalation outcome at all
    suppressed = 0
    for action in runs[0]["actions"]:
        taken = action["taken"]
        if action["action"] != S.ACTION_TICKET:
            continue
        decision = next(d for d in runs[0]["decisions"] if d["fingerprint"] == action["fingerprint"])
        if decision["check"] in PAGE_CODES:
            assert "critical" in taken and "escalation" in taken
        else:
            assert "critical" not in taken and "escalation" not in taken
            assert taken["page_suppressed"] == "code_not_in_page_codes"
            suppressed += 1
    assert suppressed == 35  # 38 tickets, minus the 3 page codes; the NOT_MEASURED row holds

    # every ticket left its FINDING on disk — the operator's record for the codes that never reach a phone
    finding_files = sorted(p.name for p in (tmp_path / "inbox").glob("FINDING-*.md"))
    assert len(finding_files) == 38


def test_a_non_page_ticket_writes_its_finding_and_never_calls_a_sender(tmp_path):
    row = _finding("NT_QUOTE_SOURCE", 0)
    state_path = tmp_path / "state.json"
    _seed_state(state_path, [row])
    sent = []

    def boom(**kw):  # pragma: no cover - it must never run
        sent.append(kw)
        raise AssertionError("a non-page code must not reach a sender")

    out = S.run(findings=[row], state_path_=state_path, config_path=_config(tmp_path), apply=True, now=NOW,
                heal=lambda **kw: {"accepted": False, "reason": "never"}, escalate=boom, critical=boom,
                inbox=tmp_path / "inbox")
    (action,) = out["actions"]
    assert action["action"] == S.ACTION_TICKET
    assert action["taken"]["page_suppressed"] == "code_not_in_page_codes"
    assert "critical" not in action["taken"] and "escalation" not in action["taken"]
    assert sent == []
    assert (tmp_path / "inbox" / f"FINDING-{S.ticket_id(row['fingerprint'])}.md").exists()


def test_a_clear_reaches_no_channel_for_a_ticket_that_was_never_paged(tmp_path):
    """The clear intent is Telegram + email. A ticket the operator was never told about must clear in silence."""
    row = _finding("NT_QUOTE_SOURCE", 0)
    fp = row["fingerprint"]
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"schema": S.STATE_SCHEMA, "figures": {fp: {
        "consecutive_fails": 4, "status": "ticketed", "page": "holdings", "figure_id": "qty",
        "symbol": "syn00", "check": "NT_QUOTE_SOURCE",
        "ticket": {"id": S.ticket_id(fp), "at": "2026-11-09T20:00:00+00:00", "paged": False}}}}),
        encoding="utf-8")

    def boom(**kw):  # pragma: no cover - it must never run
        raise AssertionError("an unpaged ticket's clear must not reach a channel")

    out = S.run(findings=[], state_path_=state_path, config_path=_config(tmp_path), apply=True, now=NOW,
                escalate=boom, critical=boom, inbox=tmp_path / "inbox")
    (action,) = out["actions"]
    assert action["action"] == S.ACTION_CLEAR
    assert action["taken"]["clear_suppressed"] == "ticket_was_not_paged"


# ── known_disagreement: narrow, dated, visible, and fail-closed on its own date ──────────────────────────────────

ENTRY = {"check": "NT_QUOTE_SOURCE", "symbol": "SYN00",
         "reason": "finviz source disagrees with stored quote by design on this figure; see LQ-1702",
         "approved_by": "operator", "approved_at": "2026-11-09", "expires": "2026-12-09"}


def test_an_approved_disagreement_records_the_operator_reason_and_strikes_nothing(tmp_path):
    row = _finding("NT_QUOTE_SOURCE", 0)
    state_path = tmp_path / "state.json"
    _seed_state(state_path, [row])

    out = S.run(findings=[row], state_path_=state_path, config_path=_config(tmp_path, known_disagreement=[ENTRY]),
                apply=True, now=NOW, heal=lambda **kw: {"accepted": False, "reason": "never"},
                escalate=lambda **kw: (_ for _ in ()).throw(AssertionError("no intent for an accepted row")),
                critical=lambda **kw: (_ for _ in ()).throw(AssertionError("no page for an accepted row")),
                inbox=tmp_path / "inbox")

    (decision,) = out["decisions"]
    assert decision["action"] == S.ACTION_KNOWN
    assert decision["reason"] == f"known_disagreement:{ENTRY['reason']}"
    assert out["counts"]["known_disagreement"] == 1
    assert out["counts"]["tickets"] == 0 and out["counts"]["heals"] == 0 and out["counts"]["cleared"] == 0
    # visible, with the operator's reason and the date it dies on — never a silent drop
    (recorded,) = out["known_disagreements"]
    assert recorded["fingerprint"] == row["fingerprint"] and recorded["reason"] == ENTRY["reason"]
    assert recorded["expires"] == ENTRY["expires"] and recorded["approved_by"] == "operator"
    # and it is never counted as a pass, and the counter it found is the counter it leaves
    assert out["counts"]["pass"] == 0 and out["counts"]["fail"] == 1
    written = json.loads(state_path.read_text())
    assert written["figures"][row["fingerprint"]]["consecutive_fails"] == 3


def test_the_day_after_expiry_the_row_is_an_ordinary_strike_again(tmp_path):
    """Pinned clocks either side of the entry's date — not a relative offset, which would re-derive the bug."""
    row = _finding("NT_QUOTE_SOURCE", 0)
    cfg = _config(tmp_path, known_disagreement=[ENTRY])

    on_the_day = S.plan(findings=[row], state=S.empty_state(), config=json.loads(cfg.read_text()),
                        now=datetime(2026, 12, 9, 23, 30, tzinfo=timezone.utc))
    assert on_the_day["decisions"][0]["action"] == S.ACTION_KNOWN
    assert on_the_day["counts"]["known_disagreement"] == 1

    day_after = S.plan(findings=[row], state=S.empty_state(), config=json.loads(cfg.read_text()),
                       now=datetime(2026, 12, 10, 0, 5, tzinfo=timezone.utc))
    (decision,) = day_after["decisions"]
    assert decision["action"] == S.ACTION_RECORD and decision["reason"] == "strike_recorded"
    assert decision["fails"] == 1
    assert day_after["counts"]["known_disagreement"] == 0
    assert day_after["counts"]["fail"] == 1 and day_after["counts"]["pass"] == 0


def test_the_audits_own_not_measured_row_holds_instead_of_grading_malformed():
    """LQ-1701 emits ``shown: {}``/``truth: {}`` with a typed reason when nothing was readable in either direction
    (live 2026-11-09: ``no_such_field`` on overview.day_pnl). That reason is the row's evidence: it must reach the
    hold branch and the not_measured count, not the malformed list. A row with neither side nor reason is refused."""
    core = {"fingerprint": "/|overview.day_pnl||", "page": "/", "figure_id": "overview.day_pnl",
            "account": None, "symbol": None, "severity": "P1", "status": "NOT_MEASURED", "code": "NT_NOT_MEASURED",
            "detail": "the served figure is not measurable: header today_pnl.total_change (null or absent)",
            "shown": {}, "truth": {}, "reason": "no_such_field"}
    out = S.plan(findings=[core], state=S.empty_state(), config=CONFIG, now=NOW)
    assert out["counts"]["malformed"] == 0 and out["counts"]["not_measured"] == 1
    (decision,) = out["decisions"]
    assert decision["action"] == "hold" and decision["reason"] == "not_measured"

    (_, bad) = S.split_findings([{**core, "reason": None}])
    assert len(bad) == 1 and "NOT_MEASURED needs the side" in bad[0]["reason"]


def test_a_malformed_agreement_table_refuses_the_whole_run(tmp_path):
    """Fail-closed: an entry that cannot say who approved it or why is not a narrow exception, it is an open hole."""
    for broken in ({**ENTRY, "reason": ""}, {**ENTRY, "approved_by": ""}, {**ENTRY, "expires": "soon"}):
        with pytest.raises(S.StrikesError):
            S.plan(findings=[_finding("NT_QUOTE_SOURCE", 0)], state=S.empty_state(),
                   config={**CONFIG, "known_disagreement": [broken]}, now=NOW)


def test_the_shipped_config_ships_the_mechanism_with_an_empty_table():
    """The operator approved the design, not an entry: every suppression today is an explicit operator act."""
    cfg = json.loads((ROOT / "config" / "numbers_truth_heal.json").read_text(encoding="utf-8"))
    assert cfg["page_codes"] == list(PAGE_CODES)
    assert cfg["known_disagreement"] == []
    # and the gate is the config's list, not a literal anyone can edit along with the code
    assert S.page_codes({}) == frozenset()


# ── the audit's wiring: findings in, after the receipt, with the lane's own state root ──────────────────────────


def test_the_audit_feeds_its_findings_to_the_engine_under_its_own_state_root(tmp_path, monkeypatch):
    from scripts import numbers_truth_audit as A
    from scripts.lib import numbers_truth_strikes as SC

    captured = {}

    def fake_run(**kw):
        captured.update(kw)
        return {"counts": {"paged": 0}, "known_disagreements": []}

    monkeypatch.setattr(SC, "run", fake_run)
    findings = replay_findings()
    out = A.run_strike_lane({"findings": findings}, state_root=tmp_path, now=NOW)

    assert captured["findings"] == findings
    assert captured["state_path_"] == SC.state_path(tmp_path)
    assert captured["apply"] is True and captured["now"] == NOW
    assert out["counts"] == {"paged": 0}


def test_apply_runs_the_engine_after_the_receipt_and_reports_its_failure_without_changing_rc(tmp_path, monkeypatch, capsys):
    from scripts import numbers_truth_audit as A

    seen = {}

    def fake(summary, **kw):
        seen.update(kw)
        assert summary["findings"], "the engine is fed the receipt's own findings list"
        return {"counts": {"paged": 3, "tickets": 3}, "state_path": str(tmp_path / "state.json"),
                "known_disagreements": []}

    monkeypatch.setattr(A, "run_strike_lane", fake)
    rc = A.main(["--apply", "--no-db", "--no-http", "--state-root", str(tmp_path),
                 "--now", "2026-11-09T22:07:00+00:00"])
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 1                               # no truth source readable under --no-db: the audit's own verdict
    assert line["receipt"] and Path(line["receipt"]).exists()
    assert line["strikes"]["counts"]["paged"] == 3 and line["strikes_error"] is None
    assert seen["state_root"] == tmp_path        # the engine writes under the lane's state root, not the checkout

    monkeypatch.setattr(A, "run_strike_lane",
                        lambda *a, **kw: (_ for _ in ()).throw(S.StrikesError("config refused")))
    rc = A.main(["--apply", "--no-db", "--no-http", "--state-root", str(tmp_path),
                 "--now", "2026-11-09T22:07:00+00:00"])
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 1 and line["strikes"] is None
    assert line["strikes_error"].startswith("StrikesError:") and "config refused" in line["strikes_error"]


def test_a_dry_run_never_calls_the_engine_and_writes_nothing(tmp_path, monkeypatch, capsys):
    from scripts import numbers_truth_audit as A

    def boom(**kw):  # pragma: no cover - it must never run
        raise AssertionError("a dry run must not reach the strike engine")

    monkeypatch.setattr(A, "run_strike_lane", boom)
    rc = A.main(["--dry-run", "--json", "--no-db", "--no-http", "--state-root", str(tmp_path),
                 "--now", "2026-11-09T22:07:00+00:00"])
    assert rc == 1
    assert not (tmp_path / "data" / "runtime" / "numbers_truth_state.json").exists()
    assert not list(tmp_path.rglob("*_last.json"))
