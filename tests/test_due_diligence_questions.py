"""Stages 3-5: read what we hold, say what it looks like, ask what to ask, send it out.

Measured 2026-09-06: ZERO rows in hermes_external_research had ever been requested
because a name moved. Research is swept on a clock; it had never been driven by a
change. The 2026-09-06 alert said "AOUT: 64 articles, 70 catalysts; no prior
research" and then nothing happened.

Closed the same day. The first row in this system's history carrying
trigger_source='material_change':

    lane=grok  status=sent  subject_guid=12572890
    Q: What details on sales growth and profitability appear in the Q1 earnings call?
    A: AOUT remains under the INSUFFICIENT_DATA thesis state...

Four properties, each paid for by something that went wrong in the first hour:

CURATION RUNS FLASH-FIRST, INVERTING THE HOUSE DEFAULT
    Operator decision. Curation emits strict JSON whose citations this code parses
    and enforces, so consistency beats free. OAuth is the escalation, and ASK is
    still the hard stop after it.

THE LOOP INHERITS THE DETECTOR'S REJECTIONS
    The first run picked JEPI and BND — both corrupt prices already suppressed as
    UNCORROBORATED — and the model wrote "JEPI showed a large price excursion",
    describing a fiction because the row said so.

GROUNDING IS ENFORCED IN CODE
    Not merely requested in the prompt. A model told not to invent will still
    occasionally invent, and an ungrounded question is indistinguishable from a real
    one to the person reading it.

A DEFAULT POINTING AT A DEAD LANE PRODUCES ROWS AND NO KNOWLEDGE
    The first routed question went to `claude`, which is credits_required, and came
    back [CREDITS_REQUIRED]. The request was correctly created, correctly stored,
    and answered nothing.

No database, no network, no model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCRIPT = ROOT / "scripts" / "due_diligence_questions.py"


@pytest.fixture(scope="module")
def mod():
    return pytest.importorskip("due_diligence_questions")


ITEMS = [{"id": "news:1", "date": "2026-09-04", "text": "earnings beat"},
         {"id": "catalyst:2", "date": "2026-09-04", "text": "[10-Q] filed"}]


# ── lane policy ─────────────────────────────────────────────────────────────

def test_the_curation_chain_is_in_the_operator_order(mod):
    """flash -> free OAuth -> deepseek pro -> ASK. Inverted from the house default
    (free first) on purpose: curation emits a parsed contract, so consistency beats
    free, and the OAuth lanes stay as the escalation rather than the entry point."""
    assert mod.CURATION_MODEL.startswith("deepseek")
    assert "pro" in mod.CURATION_MODEL_PRO
    src = SCRIPT.read_text(encoding="utf-8")
    chain = src.split("res = (_curate_via_deepseek(prompt, CURATION_MODEL)", 1)[1]
    chain = chain.split("if res is None:", 1)[0]
    assert "_curate_via_oauth(prompt)" in chain
    assert "CURATION_MODEL_PRO" in chain
    oauth_at = chain.index("_curate_via_oauth")
    pro_at = chain.index("CURATION_MODEL_PRO")
    assert oauth_at < pro_at, "pro must be tried AFTER the free lanes, not before"


def test_ask_is_still_the_stop_after_the_whole_chain(mod):
    """The inversion must not remove the hard stop."""
    src = SCRIPT.read_text(encoding="utf-8")
    after = src.split("or _curate_via_deepseek(prompt, CURATION_MODEL_PRO))", 1)[1]
    assert "run_with_escalation(" in after.split("text =", 1)[0]


def test_oauth_is_the_escalation_and_ask_is_still_the_stop(mod):
    """The inversion must not remove the hard stop. run_with_escalation ends in
    notify-and-STOP, so keeping it as step 2 preserves it."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "run_with_escalation(" in src
    assert "EscalationStopped" in src


def test_a_capped_lane_is_skipped_not_fatal(mod, monkeypatch, capsys):
    """A cap refusal is a 429, not an outage — it degrades the lane and the run
    continues. Observed live: flash refused with COST_CAP_EXCEEDED, the run
    escalated to grok, and the questions were produced anyway."""
    def boom(*a, **k):
        raise RuntimeError("COST_CAP_EXCEEDED: global cap")

    fake = type(sys)("hermes_external_researcher")
    fake.call_governed_deepseek = boom
    monkeypatch.setitem(sys.modules, "hermes_external_researcher", fake)
    assert mod._curate_via_deepseek("p", "deepseek-v4-flash") is None
    assert "unavailable" in capsys.readouterr().err


def test_the_cap_check_runs_in_this_process_and_says_so(mod, monkeypatch):
    """call_governed_deepseek reads LLM_GLOBAL_DAILY_USD_CAP from the CALLER's env,
    not the bridge's. A cron job inherits nothing, so every call would refuse with a
    message that reads like a budget problem and is actually a missing variable."""
    monkeypatch.delenv("LLM_GLOBAL_DAILY_USD_CAP", raising=False)
    warn = mod.cap_env_warning()
    assert warn and "runs here, not in the bridge" in warn
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "7.00")
    assert mod.cap_env_warning() is None


def test_the_research_lane_is_measured_not_hardcoded(mod):
    """A fixed default is wrong twice over: it goes stale, and it optimises for
    whoever wrote it. `--lane claude` was the shipped default and claude has answered
    nothing since 2026-08-01; replacing it with grok then picked the WORST lane by
    measured quality (0.470 vs chatgpt 0.616 over 11,116 scored answers)."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'os.getenv("DDQ_LANE", "claude")' not in src, "the dead default is back"
    assert "def rank_research_lanes" in src
    assert "claude" not in mod.RESEARCH_LANE_CANDIDATES


def test_lane_ranking_gates_on_delivery_then_ranks_on_quality(mod):
    """Quality is only meaningful among lanes that actually deliver."""
    class C:
        def __init__(self): self._r = []
        def execute(self, sql, params=None):
            if "status='sent'" in sql and "success" in sql:
                # lane, success_rate, sent
                self._r = [("chatgpt", 0.995, 2384), ("grok", 0.993, 2441),
                           ("deepseek", 0.25, 896)]
            else:
                self._r = [("chatgpt", 0.616), ("grok", 0.470), ("deepseek", 0.9)]
        def fetchall(self): return self._r

    ranked = mod.rank_research_lanes(C())
    names = [r[0] for r in ranked]
    assert names[0] == "chatgpt", "the best-quality delivering lane must be first"
    assert "deepseek" not in names, "a 25% success rate must be gated out on quality alone"


def test_an_unmeasured_lane_sorts_last_rather_than_being_excluded(mod):
    """Unmeasured is not the same as bad."""
    class C:
        def __init__(self): self._r = []
        def execute(self, sql, params=None):
            self._r = ([("grok", 0.99, 100), ("chatgpt", 0.99, 100)]
                       if "success" in sql else [("grok", 0.47)])
        def fetchall(self): return self._r

    ranked = mod.rank_research_lanes(C())
    assert [r[0] for r in ranked] == ["grok", "chatgpt"]
    assert ranked[-1][2] == -1.0


# ── the loop inherits the detector's rejections ─────────────────────────────

def test_suppressed_changes_are_not_reasoned_about(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    q = src.split("def pending_changes", 1)[1].split("def ", 1)[0]
    assert "UNCORROBORATED" in q, "corrupt changes would be described as real events"


# ── grounding is enforced, not requested ────────────────────────────────────

def test_an_uncited_question_is_dropped(mod):
    parsed = {"narrative": [], "questions": [{"question": "invented?", "cites": []}]}
    n, qs, stats = mod.ground(parsed, ITEMS)
    assert qs == [] and stats["questions_dropped"] == 1


def test_a_question_citing_an_unknown_id_is_dropped(mod):
    parsed = {"narrative": [], "questions": [{"question": "q", "cites": ["news:999"]}]}
    _, qs, stats = mod.ground(parsed, ITEMS)
    assert qs == [] and stats["questions_dropped"] == 1


def test_an_uncited_narrative_sentence_is_dropped(mod):
    parsed = {"narrative": [{"sentence": "asserted", "cites": []}], "questions": []}
    n, _, stats = mod.ground(parsed, ITEMS)
    assert n == [] and stats["narrative_dropped"] == 1


def test_a_grounded_pair_survives_with_only_valid_cites(mod):
    parsed = {"narrative": [{"sentence": "s", "cites": ["news:1", "news:999"]}],
              "questions": [{"question": "q", "why_now": "w",
                             "what_would_settle_it": "x",
                             "cites": ["catalyst:2", "bogus:1"]}]}
    n, qs, stats = mod.ground(parsed, ITEMS)
    assert n[0]["cites"] == ["news:1"]
    assert qs[0]["cites"] == ["catalyst:2"]
    assert stats == {"narrative_dropped": 0, "questions_dropped": 0}


def test_what_was_dropped_reaches_the_result(mod):
    """A layer that silently discards model output cannot be audited."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"dropped"' in src


# ── identity: nothing is lost ───────────────────────────────────────────────

def test_the_same_question_mints_the_same_id(mod):
    a = mod.question_guid("s-1", "c-1", "What changed in margins?")
    assert a == mod.question_guid("s-1", "c-1", "what changed in margins?  ")
    assert a != mod.question_guid("s-1", "c-2", "What changed in margins?")
    assert a != mod.question_guid("s-2", "c-1", "What changed in margins?")


def test_a_new_trigger_makes_it_a_new_question(mod):
    """Correct: 'is the thesis intact?' after an earnings miss is not the same
    question as those words last month."""
    assert (mod.question_guid("s-1", "c-1", "is the thesis intact?")
            != mod.question_guid("s-1", "c-2", "is the thesis intact?"))


def test_questions_dedupe_rather_than_accumulate(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert "ON CONFLICT (question_guid) DO NOTHING" in src
    assert "ON CONFLICT (narrative_guid) DO NOTHING" in src


def test_the_question_carries_its_whole_lineage(mod):
    """subject, issuer, the trigger, the narrative it came from, and the evidence."""
    src = SCRIPT.read_text(encoding="utf-8")
    for col in ("subject_guid", "issuer_guid", "change_guid", "narrative_guid",
                "supersedes_guid", "cited_ids"):
        assert col in src, f"the question loses {col}"


def test_the_answer_is_stamped_back_onto_the_spine(mod):
    """An answer that cannot be joined to its subject cannot re-rank the next
    dossier — which is the only part of this loop that compounds."""
    src = SCRIPT.read_text(encoding="utf-8")
    r = src.split("def route(", 1)[1]
    assert "UPDATE hermes_external_research" in r
    assert "trigger_source = 'material_change'" in r


# ── control flow ────────────────────────────────────────────────────────────

def test_routing_does_not_depend_on_new_changes(mod):
    """An earlier version returned early when no new change existed, so a question
    generated on one run could never be sent on the next."""
    src = SCRIPT.read_text(encoding="utf-8")
    early = src.split("if not changes:", 1)[1].split("return 0", 1)[0]
    assert "route(cur, MAX_ROUTED)" in early


def test_a_failed_route_leaves_the_question_asked(mod):
    """An unrouted question is a standing gap and must stay visible."""
    src = SCRIPT.read_text(encoding="utf-8")
    r = src.split("def route(", 1)[1]
    failed = r.split("else:", 1)[1]
    assert "status='ROUTED'" not in failed


def test_internal_scoring_is_stripped_from_the_dossier(mod):
    """The prototype asked "what would move the internal composite score higher?" —
    grounded, well-formed, and about this system rather than the company."""
    assert mod._INTERNAL_NOISE.search("its composite score rose")
    assert mod._INTERNAL_NOISE.search("watchlist rank #26")
    assert not mod._INTERNAL_NOISE.search("gross margin expanded 240bps")


def test_the_prompt_forbids_asking_about_ourselves(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert "Never ask about this system's own scores" in src


def test_it_is_advisory_only(mod):
    assert mod.AUTHORITY == "READ_ONLY_ADVISORY"
    src = SCRIPT.read_text(encoding="utf-8")
    for banned in ("place_order(", "submit_order(", "position_size("):
        assert banned not in src


def test_a_dry_run_reports_unmeasured_not_zero(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'result["rows_produced"] = total_q if args.apply else None' in src


def test_the_oauth_escalation_prefers_the_stronger_free_lane(mod):
    """Measured on one real dossier, identical prompt: chatgpt gave 4 questions and
    15 citations in 19s; grok gave 2 questions and 8 citations in 28s. Both are free,
    so there is no reason to try the weaker one first."""
    assert mod.OAUTH_ORDER[0] == "chatgpt"
    assert "grok" in mod.OAUTH_ORDER


def test_a_dead_oauth_lane_falls_through_to_the_next(mod, monkeypatch, capsys):
    """One free lane being down is not a reason to skip to a paid one."""
    calls = []

    def call_external(lane, model, prompt, max_tokens=1500):
        calls.append(lane)
        if lane == "chatgpt":
            raise RuntimeError("hermes_headless_limit")
        return '{"narrative": [], "questions": []}'

    fake = type(sys)("hermes_external_researcher")
    fake.call_external = call_external
    fake.LANE_CFG = {"chatgpt": {"model": "gpt-5.4"}, "grok": {"model": "grok-3-mini"}}
    monkeypatch.setitem(sys.modules, "hermes_external_researcher", fake)

    res = mod._curate_via_oauth("p")
    assert calls == ["chatgpt", "grok"]
    assert res and res["lane"] == "grok-oauth"
    assert "chatgpt unavailable" in capsys.readouterr().err
