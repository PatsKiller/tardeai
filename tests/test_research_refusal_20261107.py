"""LQ-20261107-316 (RESEARCH_REFUSAL_20261107): a refusal is not research.

Grok answers a research prompt under the default Hermes profile by declining it in prose — 20–30 rows a
day were stored with ``status='sent'`` for a week. Every consumer that reads sent rows then treated the
refusal as a completed piece of research: the usefulness backfill spent a model call rating it (measured:
id 69387, a refusal, scored 0.55), the outcome grader parsed a direction from it, and the lane's own
"success rate" counted it.

These tests pin the three places that decide:

1. the classifier — anchored at the opening sentence, so real research that merely mentions the profile
   limit in passing stays research;
2. the writer — a refusal is stored as ``refused`` with the row annotated, and a transport failure or a
   rejected quality gate keeps its own status;
3. the backfill — never rates a refusal, reclassifies the rows written before this fix, and states what it
   reclassified on the receipt as an exclusion rather than a skip.

Synthetic fixtures only: no DB, no model, no network, no live row. The repo is PUBLIC.
"""
from __future__ import annotations

import re
import sys
import types

import pytest

ROOT = None  # set by the first lazy import; keeps this file importable at the base commit


# ── the classifier ───────────────────────────────────────────────────────────────────────────────────────────
def _refusal_classifier():
    from scripts.lib.research_refusal import classify_refusal
    return classify_refusal


def _codes():
    from scripts.lib import research_refusal as R
    return R


#: Openings taken from the stored corpus (30 days, read 2026-11-07), one per shape in use.
REFUSALS = [
    "I cannot provide the requested market verdict, as the active Hermes profile does not permit "
    "trade analysis.",
    "I can't supply a directional recommendation under this configuration.",
    "I won’t generate a trading signal for this instrument.",
    "I am unable to produce the requested JSON research object.",
    "I'm unable to approve or recommend a position here.",
    "I am operating under the default Hermes profile, which excludes equity analysis.",
    "I am Hermes in a non-trading, non-advisory configuration.",
    "Refused: this task requires the Trade AI advisory identity, which is not the active profile.",
    "Decline — the profile in force prohibits trade analysis.",
    "Scope refusal: no equity research is produced for this request.",
    "No. This request falls outside the active default Hermes profile.",
    "This request conflicts with the active default Hermes profile, so no output is generated.",
    "The request conflicts with the default Hermes profile.",
    "The active Hermes profile does not generate equity analysis.",
    "Default hermes profile: no analysis or JSON output generated.",
    "Under the active default profile I produce no market view.",
    "I do not generate trade recommendations.",
]

#: Real research. Several mention the profile limit — after the verdict, which is where a limit belongs.
RESEARCH = [
    "STIM evidence review only: the active default Hermes profile cannot create a trade proposal, "
    "so below is the analysis. Revenue growth re-accelerated and the multiple remains below the "
    "three-year median; I would watch the next print.",
    "Verdict: neutral-to-constructive. The default profile restriction prevents a formal trade "
    "proposal, but the evidence supports a watch.",
    "Rating: BUY. Note that the active profile forbids approval language; this is analysis, not an "
    "approval.",
    "The catalyst is a guidance raise, and the stock has not priced it in. JSON follows: {\"rating\": "
    "\"bullish\"}",
    "Net: the filing raises doubt about the dividend. I cannot confirm the payout ratio from the "
    "provided context, so treat that leg as unresolved.",
]


@pytest.mark.parametrize("text", REFUSALS)
def test_a_reply_that_declines_at_the_opening_is_a_refusal(text):
    classify_refusal = _refusal_classifier()
    is_refusal, reason = classify_refusal(text)
    assert is_refusal is True, text
    assert reason == _codes().PROFILE_REFUSAL


@pytest.mark.parametrize("text", RESEARCH)
def test_research_that_merely_mentions_the_profile_is_not_a_refusal(text):
    """Precision over recall: the profile phrase appears AFTER the verdict, so the reply is research."""
    classify_refusal = _refusal_classifier()
    assert classify_refusal(text) == (False, None), text


def test_the_three_measured_false_positives_are_kept():
    """Phrase-anywhere matching misclassified these real rows; anchoring at the start is what saves them."""
    classify_refusal = _refusal_classifier()
    for text in (
        "CYBR thesis: the default Hermes profile would not approve a position, but the evidence is "
        "constructive. Downgrade risk is the renewal cycle.",
        "MU: I cannot recommend or approve a trade, however the HBM ramp is real. Analysis below.",
        "ANET: outside the default Hermes profile for approvals, yet the margin trend supports a watch.",
    ):
        assert classify_refusal(text) == (False, None), text


def test_markdown_and_whitespace_do_not_hide_a_refusal():
    classify_refusal = _refusal_classifier()
    text = "**I  cannot**\n\n  provide the requested *market* verdict.\n\n```json\n{}\n```"
    assert classify_refusal(text)[0] is True


def test_an_empty_or_missing_reply_is_not_a_refusal():
    """Never turn a missing answer into a confident one: unknown stays unknown."""
    classify_refusal = _refusal_classifier()
    for text in (None, "", "   \n\t ", 0):
        assert classify_refusal(text) == (False, None), repr(text)


def test_a_phrase_deep_inside_a_real_answer_does_not_classify_the_row():
    classify_refusal = _refusal_classifier()
    head = "Verdict: accumulate on weakness. " * 8
    text = head + "I cannot approve trades under the default Hermes profile."
    assert classify_refusal(text) == (False, None)


def test_the_classifier_is_case_and_punctuation_insensitive_at_the_opening():
    classify_refusal = _refusal_classifier()
    assert classify_refusal("I CANNOT provide a market verdict.")[0] is True
    assert classify_refusal("REFUSED. The profile forbids this.")[0] is True


# ── the writer: what status the row is stored with ──────────────────────────────────────────────────────────
def _writer():
    from scripts import hermes_external_researcher as H
    return H


def test_a_sent_reply_that_declines_is_stored_as_refused_and_annotated():
    H = _writer()
    parsed = {"recommendation": "I cannot provide the requested market verdict."}
    status = H.classify_reply_status("sent", parsed, "raw")
    assert status == H.REFUSED_STATUS == "refused"
    assert "PROFILE_REFUSAL" in parsed["risk_flags"]
    assert parsed["operator_action"] == "REPROMPT_WITH_RESEARCH_PROFILE"
    assert parsed["learning_candidate"].startswith("refused:")
    assert "nothing to rate" in parsed["learning_candidate"]


def test_a_sent_reply_that_is_research_is_left_exactly_as_it_was():
    H = _writer()
    parsed = {"recommendation": "Verdict: BUY on the guidance raise; watch the next print."}
    before = dict(parsed)
    assert H.classify_reply_status("sent", parsed, "raw") == "sent"
    assert parsed == before


def test_a_transport_failure_keeps_its_own_status_even_if_the_body_says_cannot():
    """An HTTP 403 body may quote the model declining; the cause is the HTTP code, not the prose."""
    H = _writer()
    parsed = {"recommendation": "[ERROR HTTP 403] I cannot serve this request", "error": "forbidden"}
    assert H.classify_reply_status("error", parsed, "") == "error"
    assert H.classify_reply_status("rejected_data_quality", parsed, "") == "rejected_data_quality"
    assert H.classify_reply_status("skipped", parsed, "") == "skipped"


def test_the_raw_prose_is_classified_when_the_parse_produced_no_recommendation():
    """The researcher stores a truncated JSON reply's raw text as the recommendation; a refusal there
    must not survive as sent just because the JSON envelope was unparsable."""
    H = _writer()
    parsed = {}
    status = H.classify_reply_status("sent", parsed, "I cannot provide the requested market verdict.")
    assert status == "refused"
    assert "PROFILE_REFUSAL" in parsed["risk_flags"]


def test_a_sent_row_with_no_text_at_all_is_not_reclassified():
    H = _writer()
    assert H.classify_reply_status("sent", {}, "") == "sent"


def test_an_existing_risk_flag_written_as_a_string_is_kept_in_the_list():
    H = _writer()
    parsed = {"recommendation": "I cannot provide the requested market verdict.", "risk_flags": "LOW_LIQUIDITY"}
    H.classify_reply_status("sent", parsed, "")
    assert parsed["risk_flags"] == ["LOW_LIQUIDITY", "PROFILE_REFUSAL"]


# ── the backfill: never rate a refusal; reclassify the rows already stored ──────────────────────────────────
from scripts import hermes_external_feedback_loop as fb  # noqa: E402


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        if "GROUP BY lane" in self.calls[-1][0]:
            return [("grok", 2, 0.5)]
        return self.rows


class FakeConn:
    def __init__(self, rows):
        self.cur = FakeCursor(rows)
        self.committed = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed += 1

    def close(self):
        pass


def row(rid=1, rec="Verdict: BUY on the guidance raise."):
    return (rid, "grok", "AAA", "what changed?", rec, None, "2026-11-07T10:00:00Z")


def args(*, apply=True, max_rows=25, reclassify=False):
    return types.SimpleNamespace(apply=apply, max_rows=max_rows, model="deepseek-flash",
                                 reclassify_refusals=reclassify)


@pytest.fixture()
def lane(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "KILL", tmp_path / "HERMES_DISABLED")
    monkeypatch.setattr(fb, "_outcome", lambda cur, symbol, created: {})
    rated = []

    def _rate(*a):
        rated.append(a[1])
        return 0.5, "specific and grounded", {"provider": "fake", "model": "m"}

    monkeypatch.setattr(fb, "_rate", _rate)
    return rated


def _updates(conn):
    return [c for c in conn.cur.calls if "UPDATE hermes_external_research" in c[0]]


REFUSAL = "I cannot provide the requested market verdict under the active Hermes profile."


def test_a_refusal_is_never_rated(monkeypatch, lane):
    conn = FakeConn([row(7, REFUSAL)])
    monkeypatch.setattr(fb, "_db", lambda: conn)
    result = fb._run_feedback(args())
    assert lane == [], "a refusal must not spend a model call"
    assert result["refusals_skipped"] == 1 and result["scored"] == 0
    assert not _updates(conn), "an hourly run does not move a row's status: the backfill asks for that"


def test_the_backfill_flips_the_stored_status_only_when_asked(monkeypatch, lane):
    """The status is the per-lane success rate every router ranks on: it moves on request, not on deploy."""
    conn = FakeConn([row(7, REFUSAL)])
    monkeypatch.setattr(fb, "_db", lambda: conn)
    result = fb._run_feedback(args(reclassify=True))
    assert result["reclassified"] == 1 and result["scored"] == 0
    ups = _updates(conn)
    assert len(ups) == 1
    sql, params = ups[0]
    assert params[0] == "refused" and params[2] == 7
    assert "usefulness_score" not in sql, "the row keeps an unset score; there is nothing to rate"
    assert "status='sent'" in sql, "the update must be idempotent, not clobber another writer's status"


def test_the_preview_reports_the_same_verdicts_without_writing(monkeypatch, lane):
    conn = FakeConn([row(7, REFUSAL), row(8, "Verdict: accumulate.")])
    monkeypatch.setattr(fb, "_db", lambda: conn)
    result = fb._run_feedback(args(apply=False, reclassify=True))
    assert result["refusals_skipped"] == 1
    assert result["scored"] == 0, "a preview never counts a row it did not write"
    assert not _updates(conn) and conn.committed == 0


def test_a_batch_of_refusals_does_not_starve_the_rows_that_have_research(monkeypatch, lane):
    """Without the over-fetch a window of refusals would push real research out of every run."""
    rows = [row(i, REFUSAL) for i in range(1, 6)] + [row(6, "Verdict: BUY.")]
    conn = FakeConn(rows)
    monkeypatch.setattr(fb, "_db", lambda: conn)
    result = fb._run_feedback(args(max_rows=2))
    assert result["scored"] == 1 and lane == ["Verdict: BUY."]
    select = conn.cur.calls[0]
    assert select[1] == (2 * fb.REFUSAL_OVERFETCH,), "the window must widen with the over-fetch factor"
    assert select[1] == (8,)


def test_the_rating_budget_is_still_the_caller_s_max_rows(monkeypatch, lane):
    conn = FakeConn([row(i + 1, "Verdict: BUY.") for i in range(10)])
    monkeypatch.setattr(fb, "_db", lambda: conn)
    result = fb._run_feedback(args(max_rows=2))
    assert len(lane) == 2 and result["scored"] == 2


def test_a_run_that_only_reclassified_states_why_it_scored_nothing(monkeypatch, lane):
    conn = FakeConn([row(7, REFUSAL)])
    monkeypatch.setattr(fb, "_db", lambda: conn)
    result = fb._run_feedback(args())
    assert result["empty_reason"] == fb.NO_ELIGIBLE_REASON


def test_a_provider_failure_still_does_not_claim_idle(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "KILL", tmp_path / "HERMES_DISABLED")
    monkeypatch.setattr(fb, "_outcome", lambda cur, symbol, created: {})

    def boom(*a):
        raise RuntimeError("BRIDGE_ROUTE_REFUSED: governance refused the request")

    monkeypatch.setattr(fb, "_rate", boom)
    monkeypatch.setattr(fb, "_db", lambda: FakeConn([row(9)]))
    result = fb._run_feedback(args())
    assert result["aborted"] is True and not result.get("empty_reason")


# ── the receipt the operator's page grades ─────────────────────────────────────────────────────────────────
class FakeReceiptModule(types.ModuleType):
    def __init__(self):
        super().__init__("lib.lane_last_receipt")
        self.calls = []

    def now_iso(self):
        return "2026-11-07T22:00:00Z"

    def write_lane_receipt(self, *a, **kw):
        self.calls.append((a, kw))
        return None


def test_the_receipt_states_reclassified_rows_as_excluded_not_produced(monkeypatch, lane):
    import lib  # noqa: F401 -- the real parent package; only the receipt writer is replaced
    fake = FakeReceiptModule()
    monkeypatch.setitem(sys.modules, "lib.lane_last_receipt", fake)
    monkeypatch.setattr(fb, "_load_env", lambda: None)
    conn = FakeConn([row(7, REFUSAL), row(8, "Verdict: BUY.")])
    monkeypatch.setattr(fb, "_db", lambda: conn)
    assert fb.main(["--apply", "--max-rows", "25"]) == 0
    _a, kw = fake.calls[0]
    assert kw["produced_count"] == 1, "only the row it actually scored is produced"
    assert kw["excluded_reasons"] == {"REFUSED_BY_PROFILE": 1}
    assert kw["attempted_count"] == 1
    assert kw["summary"]["refusals_skipped"] == 1
