"""LQ-20261107-512: a refused CIO synthesis is never stored, never served, and the run is marked failed.

Fixtures are synthetic paraphrases of the refusal SHAPES measured on the live table (no real rows,
symbols, accounts or holdings). Each shape below was missed by the LQ-407 predicate.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest

from lib.llm_refusal import REFUSAL_DERIVED_FIELDS, is_refusal, scrub_refused_synthesis

MC = "[MULTI-CONSENSUS] lanes disagreed (Grok=SELL, Flash=AVOID); settled on SELL. "

MISSED_BY_407 = [
    MC + "**Refusal:** This request asks me to generate portfolio allocation and position sizing.",
    MC + "**Refusal** I cannot perform the requested CIO synthesis or JSON output.",
    MC + "**Declined.** This query requests portfolio allocation decisions and BUY/SELL verdicts.",
    MC + "**This request is outside the active profile's authority.** The current Hermes profile is `default`.",
    MC + "I am the default Hermes assistant in a non-trading profile. I do not create trade proposals.",
    MC + "The current active profile is the default general-purpose Hermes assistant.",
    MC + "This request requires acting as a Chief Investment Officer performing trade synthesis.",
    "**Refused.** This request requires the Trade AI advisory profile. The active profile is `default`.",
    "**Profile boundary violation.** The active Hermes profile is **default** (general-purpose).",
    "**Request outside default profile scope.** The active Hermes profile is `default`.",
    "**Request declined.** This query requires the Trade AI advisory identity.",
    "**This request violates the active profile boundaries.** The current Hermes profile is `default`.",
    "I am Hermes in the default general-purpose profile. This request requires acting as CIO.",
    "I agree with Steph on process and authority: under the active Hermes default profile, I cannot issue a recommendation.",
    "**Boundary note:** The active profile is `default` (general-purpose Hermes).",
]
# Real analyses that share words with refusals: Hermes as a data source, "cannot" in reasoning,
# "profile" as a risk/technical profile, a lane vote label, a non-authorizing disclaimer.
REAL = [
    "Not held (0 shares). Both supplied yield figures (0.0% Yahoo, 0.37% Hermes) fall below the 1.5% minimum.",
    "ISRG: Q3 results beat; the thesis holds. I cannot ignore valuation, so trim on strength.",
    "DY fits a speculative-growth watchlist profile only if there is a catalyst and a technical setup.",
    MC.replace("Grok=SELL", "ChatGPT=UNAVAILABLE_IN_DEFAULT_PROFILE") + "Not held, so this is a fresh-entry decision.",
    "This is a non-authorizing research assessment, not a committee approval or trade proposal. Allocation weighs 30%.",
    "Allocation-first rule dominates: the income layer remains underweight at 3.2% against a 25-40% target.",
    "",
    None,
]


@pytest.mark.parametrize("text", MISSED_BY_407)
def test_shapes_missed_by_407_are_refusals(text):
    assert is_refusal(text)


@pytest.mark.parametrize("text", REAL)
def test_real_analysis_is_not_a_refusal(text):
    assert not is_refusal(text)


def test_reader_scrub_blanks_every_field_from_the_refusing_run():
    item = {"symbol": "XMPL", "synthesis_narrative": MISSED_BY_407[0], "synthesis_recommendation": "SELL",
            "grok_recommendation": "SELL", "models_agree": False, "synthesis_actionable": True,
            "conflicts": ["MODEL DISAGREEMENT"], "decision_safety": "unsafe",
            "synthesis_evidence": [{"k": "v"}], "price": 12.5}
    out = scrub_refused_synthesis(item)
    assert out["synthesis_refused"] is True
    for k in REFUSAL_DERIVED_FIELDS:
        if k in item:
            assert out[k] is None, k
    assert out["price"] == 12.5 and out["symbol"] == "XMPL"


def test_reader_scrub_leaves_real_synthesis_alone():
    item = {"synthesis_narrative": REAL[0], "synthesis_recommendation": "AVOID"}
    out = scrub_refused_synthesis(dict(item))
    assert out["synthesis_refused"] is False
    assert out["synthesis_narrative"] == REAL[0] and out["synthesis_recommendation"] == "AVOID"


class _Cur:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))


class _Conn:
    def __init__(self):
        self.log, self.commits, self.rollbacks = [], 0, 0

    def cursor(self):
        return _Cur(self.log)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_writer_marks_refusal_failed_and_never_upserts_synthesis():
    import process_watchlist_agent_jobs as m
    conn = _Conn()
    m._mark_synthesis_refused(conn, "XMPL", {"refused_lanes": ["grok"], "participating_lanes": []},
                              MISSED_BY_407[2])
    sqls = [s for s, _ in conn.log]
    assert any(s.startswith("UPDATE watchlist_analysis_maturity SET final_synthesis_status='failed'")
               and "final_synthesis_status='processing'" in s for s in sqls)
    ev = [(s, p) for s, p in conn.log if s.startswith("INSERT INTO watchlist_events")]
    assert len(ev) == 1 and "'synthesis_refused'" in ev[0][0] and "'failed'" in ev[0][0]
    assert json.loads(ev[0][1][2])["refused_lanes"] == ["grok"]
    assert not any("watchlist_final_synthesis" in s for s in sqls), "a refusal must not touch the stored synthesis"
    assert conn.commits == 1


def test_writer_mark_failure_rolls_back_and_does_not_raise():
    import process_watchlist_agent_jobs as m

    class _Boom(_Conn):
        def cursor(self):
            raise RuntimeError("connection closed")

    conn = _Boom()
    m._mark_synthesis_refused(conn, "XMPL", None, None)
    assert conn.rollbacks == 1 and conn.commits == 0


def test_writer_refusal_branch_checks_raw_and_marks_failed():
    """The run_synthesis refusal branch consults the raw winner text and calls the failure mark."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "process_watchlist_agent_jobs.py").read_text()
    assert "refused = _is_refusal(synthesis_narrative) or _is_refusal(raw)" in src
    assert "_mark_synthesis_refused(conn, symbol, dual_meta, raw)" in src
