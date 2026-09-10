"""The desk speaks when something changed, and narrates the research when it does.

The operator's complaint: "It seems like I'm seeing the same text day after day
with the same subject matter." The measurement said outbound text was only 0-14%
literally duplicated -- what repeated was the SHAPE. "Material change — N name(s)
worth a look" every hour, a notification format and never a finding, while 49,094
research rows never reached them.

Two guarantees pinned here:
  * silence is a legitimate, recorded outcome when nothing changed
  * when the desk does speak, it cites the research it is speaking about
"""
from __future__ import annotations

from scripts.lib.cio_narrative_compose import (
    SILENT_NO_CHANGE,
    SILENT_NO_EVIDENCE,
    SPEAK_FIRST_VIEW,
    SPEAK_NEW_EVIDENCE,
    SPEAK_THESIS_CHANGED,
    assess,
    compose,
    prior_cited,
)

R1 = {"content_hash": "h1", "title": "Filing A", "source_url": "https://x.com/a"}
R2 = {"content_hash": "h2", "title": "Filing B", "source_url": "https://y.com/b"}


# --- the repetition fix -------------------------------------------------------

def test_the_same_research_an_hour_later_says_NOTHING():
    """THE control for the operator's complaint. Must go red if the gate is
    removed -- without it the wake produces something every hour forever."""
    prior = [{"cited_ids": ["content_hash:h1", "content_hash:h2"]}]
    a = assess(research=[R1, R2], prior_narratives=prior)
    assert a["speak"] is False and a["reason"] == SILENT_NO_CHANGE


def test_silence_is_recorded_with_a_reason_not_just_absent():
    """A silent hour must be auditable, otherwise it is indistinguishable from a
    broken one."""
    a = assess(research=[], prior_narratives=[])
    assert a["reason"] == SILENT_NO_EVIDENCE
    assert "research_count" in a and "prior_cited_count" in a


# --- when it should speak -----------------------------------------------------

def test_first_view_speaks():
    a = assess(research=[R1], prior_narratives=[])
    assert a["speak"] and a["reason"] == SPEAK_FIRST_VIEW


def test_genuinely_new_evidence_speaks():
    prior = [{"cited_ids": ["content_hash:h1"]}]
    a = assess(research=[R1, R2], prior_narratives=prior)
    assert a["speak"] and a["reason"] == SPEAK_NEW_EVIDENCE
    assert a["new_evidence_ids"] == ["content_hash:h2"], "only the NEW item counts"


def test_a_changed_thesis_speaks_even_with_no_new_evidence():
    """The operator's stake is in the conclusion, not the footnotes."""
    prior = [{"cited_ids": ["content_hash:h1"]}]
    a = assess(research=[R1], prior_narratives=prior,
               prior_thesis="hold", new_thesis="reduce")
    assert a["speak"] and a["reason"] == SPEAK_THESIS_CHANGED


def test_an_unchanged_thesis_does_not_trigger_speech():
    prior = [{"cited_ids": ["content_hash:h1"]}]
    a = assess(research=[R1], prior_narratives=prior,
               prior_thesis="hold", new_thesis="HOLD")
    assert a["speak"] is False


# --- de-duplication -----------------------------------------------------------

def test_the_same_article_via_two_feeds_is_ONE_fact():
    """content_hash beats row id. Counting a duplicate as new would let the same
    story re-open a subject the desk already spoke about."""
    dup = {"content_hash": "h1", "id": 999, "title": "Filing A (syndicated)"}
    prior = [{"cited_ids": ["content_hash:h1"]}]
    a = assess(research=[R1, dup], prior_narratives=prior)
    assert a["speak"] is False


def test_prior_cited_reads_both_shapes():
    """Narratives store cites per-sentence AND flattened; both must count."""
    got = prior_cited([{"cited_ids": ["a"]},
                       {"sentences": [{"sentence": "x", "cites": ["b"]}]}])
    assert got == {"a", "b"}


# --- narration ----------------------------------------------------------------

def test_composition_cites_what_it_speaks_about():
    """'worth a look' cites nothing. A finding cites its evidence."""
    a = assess(research=[R1, R2], prior_narratives=[])
    c = compose(subject_label="AES", research=[R1, R2], assessment=a)
    assert c["sentences"]
    assert all(s["cites"] for s in c["sentences"] if "new source" in s["sentence"])


def test_composition_names_the_actual_source():
    a = assess(research=[R1], prior_narratives=[])
    c = compose(subject_label="AES", research=[R1], assessment=a)
    text = " ".join(s["sentence"] for s in c["sentences"])
    assert "Filing A" in text and "x.com" in text


def test_a_thesis_change_is_stated_first():
    a = assess(research=[R1], prior_narratives=[{"cited_ids": ["content_hash:h1"]}],
               prior_thesis="hold", new_thesis="reduce")
    c = compose(subject_label="AES", research=[R1], assessment=a,
                prior_thesis="hold", new_thesis="reduce")
    assert "hold" in c["sentences"][0]["sentence"]
    assert "reduce" in c["sentences"][0]["sentence"]


def test_the_model_narrator_is_INJECTED_never_constructed():
    """A composition path that silently reaches a paid provider is what §12
    forbids. Absent a narrator this must stay deterministic and free."""
    a = assess(research=[R1], prior_narratives=[])
    assert compose(subject_label="AES", research=[R1],
                   assessment=a)["narrated_by"] == "deterministic"


def test_a_failing_model_narrator_falls_back_rather_than_going_silent():
    def boom(**kw):
        raise RuntimeError("lane down")

    a = assess(research=[R1], prior_narratives=[])
    c = compose(subject_label="AES", research=[R1], assessment=a, model_narrator=boom)
    assert c["narrated_by"] == "deterministic" and c["sentences"]
