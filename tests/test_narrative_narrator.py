"""The model narrator: grounded, governed, and never armed by import.

compose() takes an injected narrator and stays deterministic without one,
because a composition path that silently reaches a paid provider is what §12
forbids. These controls pin that the injection stays explicit, that the ladder is
the operator-set one rather than a second copy, and that an ungrounded sentence
is dropped rather than repaired.
"""
from __future__ import annotations

import json

from scripts.lib.cio_narrative_compose import assess, compose
from scripts.lib.cio_narrative_narrator import narrate

R1 = {"content_hash": "h1", "title": "Filing A", "source_url": "https://reuters.com/a"}
R2 = {"content_hash": "h2", "title": "Filing B", "source_url": "https://ft.com/b"}


def _asker(payload, lane="deepseek-flash", model=None):
    def ask(prompt):
        return {"text": json.dumps(payload), "lane": lane, "model": model}
    return ask


# --- grounding ----------------------------------------------------------------

def test_a_sentence_citing_an_id_not_in_the_dossier_is_DROPPED():
    """"A model told not to invent will still occasionally invent." Enforced in
    code, not asked for in the prompt."""
    out = narrate(subject_label="AES", research=[R1],
                  asker=_asker({"sentences": [
                      {"sentence": "Real.", "cites": ["content_hash:h1"]},
                      {"sentence": "Invented.", "cites": ["content_hash:NOPE"]}]}))
    assert [s["sentence"] for s in out] == ["Real."]


def test_a_sentence_with_no_cites_is_dropped():
    out = narrate(subject_label="AES", research=[R1],
                  asker=_asker({"sentences": [{"sentence": "Vibes.", "cites": []}]}))
    assert out == []


def test_research_with_no_usable_id_never_calls_the_model():
    called = []

    def ask(prompt):
        called.append(1)
        return {"text": "{}"}

    assert narrate(subject_label="AES", research=[{"title": "no id"}], asker=ask) == []
    assert called == [], "a model call with nothing to cite is spend for nothing"


# --- malformed model output ---------------------------------------------------

def test_unparsable_output_falls_back_rather_than_raising():
    def ask(prompt):
        return {"text": "not json at all"}

    assert narrate(subject_label="AES", research=[R1], asker=ask) == []


def test_fenced_json_is_unwrapped():
    def ask(prompt):
        return {"text": '```json\n{"sentences":[{"sentence":"A.","cites":["content_hash:h1"]}]}\n```'}

    assert narrate(subject_label="AES", research=[R1], asker=ask)[0]["sentence"] == "A."


# --- attribution --------------------------------------------------------------

def test_lane_and_model_are_recorded_on_every_sentence():
    """`model` was NULL on all 153 live narrative rows because neither lane set
    it. Attribution that is always null is not attribution."""
    out = narrate(subject_label="AES", research=[R1],
                  asker=_asker({"sentences": [{"sentence": "A.", "cites": ["content_hash:h1"]}]},
                               lane="chatgpt-oauth", model="gpt-x"))
    assert out[0]["lane"] == "chatgpt-oauth" and out[0]["model"] == "gpt-x"


# --- the injection boundary ---------------------------------------------------

def test_compose_without_a_narrator_stays_deterministic_and_free():
    a = assess(research=[R1], prior_narratives=[])
    assert compose(subject_label="AES", research=[R1],
                   assessment=a)["narrated_by"] == "deterministic"


def test_compose_uses_the_narrator_when_one_is_injected():
    a = assess(research=[R1, R2], prior_narratives=[])
    c = compose(subject_label="AES", research=[R1, R2], assessment=a,
                model_narrator=lambda **kw: [{"sentence": "Model said.", "cites": ["content_hash:h1"]}])
    assert c["narrated_by"] == "model"
    assert c["sentences"][0]["sentence"] == "Model said."


def test_a_hard_stop_degrades_to_FACT_rather_than_silence():
    """EscalationStopped means every lane refused. The desk still says what was
    found and where; it stops short of interpreting it. Silence on a subject that
    just cleared the novelty gate would be worse, and the escalation has already
    notified the operator."""
    def boom(**kw):
        raise RuntimeError("EscalationStopped")

    a = assess(research=[R1], prior_narratives=[])
    c = compose(subject_label="AES", research=[R1], assessment=a, model_narrator=boom)
    assert c["narrated_by"] == "deterministic" and c["sentences"]


# --- one ladder, not two ------------------------------------------------------

def test_the_ladder_is_imported_not_reimplemented():
    """A second ladder drifts, and the cheaper lane quietly stops being first."""
    import inspect

    from scripts.lib import cio_narrative_narrator as n

    src = inspect.getsource(n._ask_governed)
    assert "due_diligence_questions" in src
    assert "_curate_via_deepseek" in src and "_curate_via_oauth" in src
    assert "run_with_escalation" in src


def test_the_prompt_forbids_behaviour_language():
    from scripts.lib.cio_narrative_narrator import PROMPT

    low = PROMPT.lower()
    for word in ("size", "weight", "stop", "order", "buy or sell"):
        assert word in low, f"prompt must explicitly forbid {word!r}"
