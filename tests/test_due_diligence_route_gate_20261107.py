"""LQ-20261107-208 — a due-diligence question could never leave the building.

MEASURED 2026-11-07 19:30Z, read-only:

    $ python scripts/hermes_external_researcher.py --lane grok --symbol XRPN \\
        --question "…" --trigger due_diligence_question:2ea9bfcd-…
    [budget-guard] grok/due_diligence_question -> BLOCK (tier=UNKNOWN):
      unknown/unmapped trigger_source 'due_diligence_question' — fail closed

`route()` shells the researcher with `--trigger due_diligence_question:<guid>`, and the
researcher hands the FIRST colon-separated token to `hermes_research_budget_guard.decide()`.
The guard's `trigger_source_tier` map has twenty producer entries and not this one, so the
question is refused before a provider is chosen. The researcher exits 0 having stored no row,
and `route()` reads "exit 0, no row" as a question-level verdict and stops — so the ranked
lane chain (chatgpt, deepseek, grok) is never walked either. Result, in the database:

    due_diligence_questions: 4125 ASKED / routed_at IS NULL, max(routed_at) = 2026-10-05
    hermes_external_research: 0 rows with trigger_reason LIKE 'due_diligence_question:%'

Two separate faults, and fixing only one changes nothing:

1. THE TRIGGER HAS NO TIER. Fail-closed is the correct default; the producer still has to be
   named in the policy, the way `manual`, `research_scheduler` and `paper_postmortem` are.
2. A GATED LANE ENDS THE QUESTION. Budget refusal and an open circuit breaker are facts about
   the LANE, not about the question, and the next ranked lane may well serve it. Today they are
   indistinguishable from "this question cannot be answered" because both exit 0.

No database, no network, no model call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

TRIGGER = "due_diligence_question"


@pytest.fixture(scope="module")
def guard():
    return pytest.importorskip("hermes_research_budget_guard")


@pytest.fixture(scope="module")
def ddq():
    return pytest.importorskip("due_diligence_questions")


@pytest.fixture(scope="module")
def researcher():
    return pytest.importorskip("hermes_external_researcher")


# ── 1. the trigger is tiered, not unknown ───────────────────────────────────

def test_the_due_diligence_trigger_resolves_to_a_tier(guard):
    """Before: decision=BLOCK, tier='UNKNOWN', "unknown/unmapped trigger_source"."""
    d = guard.decide(symbol="XRPN", trigger_source=TRIGGER,
                     research_type="external_research", lane="cloud_grok")
    assert d["tier"] != "UNKNOWN"
    assert d["decision"] == "ALLOW", d["reason"]


def test_the_tier_allows_a_free_lane_and_is_capped(guard):
    """T1, not T0: a question about a material change is actionable research, not held risk.
    The tier must carry a daily call cap — an unmapped producer with no cap is the failure
    mode this guard exists to prevent."""
    pol = guard._load_policy()
    tier = pol["trigger_source_tier"][TRIGGER]
    assert tier == "T1"
    assert pol["tiers"][tier]["max_llm_calls_per_day"] > 0
    assert pol["tiers"][tier]["cloud_allowed"] is True


def test_the_mapping_does_not_open_a_paid_lane(guard):
    """The no-paid-fallback invariant outranks the new mapping."""
    d = guard.decide(symbol="XRPN", trigger_source=TRIGGER,
                     research_type="external_research", lane="cloud_paid")
    assert d["decision"] == "BLOCK"
    assert "paid" in d["reason"]


def test_broad_universe_still_gets_no_llm(guard):
    d = guard.decide(symbol="FOO", trigger_source="broad_universe",
                     research_type="external_research", lane="cloud_grok")
    assert d["decision"] == "METADATA_ONLY"


# ── 2. a gated lane is not the end of the question ──────────────────────────

class _Cur:
    """Just enough cursor for route(): one SELECT ... FOR UPDATE, then one row lookup
    per lane attempt, then UPDATEs."""

    def __init__(self, questions, found_rows):
        self.questions = questions
        self.found = list(found_rows)
        self.sql = []
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        self.sql.append(sql)

    def fetchall(self):
        return self.questions if "FOR UPDATE" in self._last else []

    def fetchone(self):
        return self.found.pop(0) if self.found else None


class _Proc:
    def __init__(self, rc, stderr=""):
        self.returncode = rc
        self.stderr = stderr
        self.stdout = ""


def _route(ddq, monkeypatch, rc_per_lane, found_per_lane, lanes):
    cur = _Cur([("q1", "NVDA", "Q?")], found_per_lane)
    monkeypatch.setattr(ddq, "rank_research_lanes", lambda _c: lanes)
    monkeypatch.setattr(ddq, "via_bridge", lambda: False)
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd[cmd.index("--lane") + 1])
        return _Proc(rc_per_lane[len(seen) - 1])

    monkeypatch.setattr(ddq.subprocess, "run", fake_run)
    return ddq.route(cur, 2), seen


def test_a_gated_lane_falls_through_to_the_next(ddq, researcher, monkeypatch):
    """chatgpt refuses before attempting (its gate), grok serves. Before: one call, routed=0."""
    out, seen = _route(
        ddq, monkeypatch, [researcher.EXIT_LANE_GATED, 0], [None, (1,)],
        [("chatgpt", 0.9, 2.0), ("grok", 0.8, 1.0)])
    assert seen == ["chatgpt", "grok"], seen
    assert out["routed"] == 1
    assert out["used"] == ["NVDA:grok"]


def test_a_question_level_gate_still_stops_the_chain(ddq, monkeypatch):
    """Exit 0 with no row is the researcher saying "this question cannot be asked" (stale
    inputs). Another lane would hit the same wall; do not pay for it twice."""
    out, seen = _route(
        ddq, monkeypatch, [0, 0], [None, (1,)],
        [("chatgpt", 0.9, 2.0), ("grok", 0.8, 1.0)])
    assert seen == ["chatgpt"], seen
    assert out["routed"] == 0 and out["failed"] == 1


def test_an_attempted_failure_still_closes_the_attempt(ddq, monkeypatch):
    """A stored row — even status=error — IS an attempt, and the next lane is not tried.
    That is the existing contract and the fall-through must not break it."""
    out, seen = _route(
        ddq, monkeypatch, [0, 0], [(7,), (8,)],
        [("chatgpt", 0.9, 2.0), ("grok", 0.8, 1.0)])
    assert seen == ["chatgpt"], seen
    assert out["routed"] == 1


# ── 3. the researcher says WHY it stored nothing ────────────────────────────

def test_a_budget_gate_exits_with_its_own_code(researcher, monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_CALL_ACCOUNTING_PATH", str(tmp_path / "acct.jsonl"))
    monkeypatch.setattr(sys, "argv", [
        "hermes_external_researcher.py", "--lane", "grok", "--question", "Q?",
        "--symbol", "XRPN", "--trigger", "who_knows:1"])
    rc = researcher.main()
    assert rc == researcher.EXIT_LANE_GATED
    events = [json.loads(line)["event"]
              for line in (tmp_path / "acct.jsonl").read_text().splitlines()]
    assert "SKIP_GATED" in events


def test_a_tiered_trigger_reaches_the_provider_boundary_in_a_dry_run(researcher, monkeypatch, tmp_path, capsys):
    """The exit code must distinguish "this lane refused" from "nothing was asked to happen".
    Everything past the gate is stubbed: this proves the gate opens, not that a provider runs."""
    import lib.research_data_quality as rdq

    monkeypatch.setenv("RESEARCH_CALL_ACCOUNTING_PATH", str(tmp_path / "acct.jsonl"))
    monkeypatch.setattr(researcher, "_load_env", lambda: None)
    monkeypatch.setattr(researcher, "canonical_prompt_context", lambda *_a, **_k: {})
    monkeypatch.setattr(rdq, "assess_prompt_context", lambda _c: {"provider_call_allowed": True, "reason_codes": []})
    monkeypatch.setattr(sys, "argv", [
        "hermes_external_researcher.py", "--lane", "grok", "--question", "Q?",
        "--symbol", "XRPN", "--trigger", f"{TRIGGER}:2ea9bfcd"])
    rc = researcher.main()
    out = capsys.readouterr().out
    assert "budget-guard" not in out, out
    assert "(dry-run — nothing sent" in out, out
    assert rc in (None, 0), rc
