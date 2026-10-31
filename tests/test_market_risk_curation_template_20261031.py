"""Template-mode curation: the model chooses phrases, it never writes the sentence.

Review of #2383 round 2 (B3) and operator 2026-10-31: "you switched the LLM off, but there needs to be a reminder to
switch it back on ... we got to get it working correctly." Every probe string from the round-2 review
(~/agent_scratch/review-2383/probes/p_cur2.py and p_cur3.py, copied verbatim below) is fed as the model's answer
with curation FORCED ON for every tier: 0 may pass. Every valid phrase choice must render from the card's own names
and figures and pass the character, behaviour, grounding and vocabulary checks. The model is always stubbed.
"""

from __future__ import annotations

import itertools
import json

import pytest

from scripts.lib.market_risk import curation

P_CUR2 = [
    "Reduce exposure to tech.",
    "Pare back the AI names.",
    "Sell into strength.",
    "Buy the dip.",
    "Add on weakness.",
    "Size down.",
    "Hedge with SQQQ.",
    "Sell ５００ shares.",
    "Five hundred shares of NVDA go.",
    "Trim 5️⃣0️⃣0️⃣ shares",
    "Lock in gains on the AI basket.",
    "Go defensive now.",
    "Load up on SQQQ.",
    "Tighten your stops.",
    "Trail your stops.",
    "Tighten stops on NVDA.",
    "Accumulate QQQ.",
    "Back up the truck on QQQ.",
    "Take chips off the table.",
    "Book gains in semis.",
    "Lower your NVDA position.",
    "Raise your cash buffer.",
    "Move into Treasuries.",
    "Switch to bonds.",
    "Park money in T-bills.",
    "Ring the register on NVDA.",
    "Stay underweight semis.",
    "Go underweight tech.",
    "Close NVDA.",
    "Close out the NVDA position.",
    "Bail on semis.",
    "Run for the exits.",
    "QQQ could fall twenty percent from here.",
    "A crash of fifty percent is possible.",
    "VIX could hit 𝟒𝟓.",
    "QQQ could fall 2⁰ percent.",
    "Risk is 50 with 32 points from options flow, 3.97 P/C.",
    "Risk could reach 3.9 next week.",
    "Risk is 50; QQQ P/C 3.97 implies 397 basis points.",
    "Put/call 3.97 means about 4 times normal.",
    "QQQ may drop to 3,97.",
    "Options flow scores 32 at 3.85x.",
    "Lessen exposure.",
    "Diminish holdings.",
    "Protect gains with a collar on QQQ.",
    "Buy protection.",
    "Get long volatility.",
    "Short QQQ.",
    "Stand aside.",
    "Wait before deploying fresh capital.",
    "Do not deploy new money.",
    "Keep powder dry.",
    "Sit on your hands.",
    "Don’t chase.",
    "It’s time to lighten up.",
    "Be a seller.",
    "Sellers should act.",
    "Selling makes sense.",
    "Buying here is risky.",
    "Purchase SQQQ.",
    "Unwind NVDA.",
    "Halve NVDA.",
    "Quarter the NVDA stake.",
    "Dial down risk.",
    "Turn down risk.",
    "Tone down exposure.",
    "Scale back.",
    "Pull back on new buys.",
    "Ｓｅｌｌ NVDA.",
    "S\u200bell NVDA.",
    "Ѕell NVDA.",
]
P_CUR3 = [
    "QQQ could fall 25 percent this week.",
    "The S&P could drop to 2050.",
    "Expect a 30 point drop in QQQ.",
    "Risk 50 could become 51.6 tomorrow.",
    "QQQ could fall 12 percent, VIX to 31.",
    "Risk is 50, 3.97 P/C means 52 by Monday.",
    "NVDA could lose 5.0 percent.",
    "NVDA could lose 5.0%.",
]


CARD = (
    "🟡 MARKET RISK YELLOW 50/100 · 2 of 9 categories confirm\nWhy: Options flow and technicals are stressed.\n"
    "options_flow +32 · Options flow: QQQ P/C OI 3.97 (3.85x median) · 10-30 17:35 ET\nEvaluated 10-31 10:36 ET. Advisory."
)
DOC = {
    "tier": "YELLOW",
    "score": 50,
    "confirming": {"n": 2, "of": 9},
    "contributors": [
        {"category": "options_flow", "points": 32, "headline": "Options flow: QQQ P/C OI 3.97 (3.85x median)"},
        {"category": "technical", "points": 24, "headline": "SOXX 28% off its 52-week high"},
    ],
    "observations": [
        {"category": "options_flow", "state": "STRESS"},
        {"category": "technical", "state": "STRESS"},
        {"category": "extended_hours", "state": "UNKNOWN"},
    ],
}
TIERS = ("RED", "ORANGE", "YELLOW", "BLUE", "GREEN", "NONE")


def _forced_on():
    return dict(curation.load_config(), skip_tiers=[])


def _wrappings(t: str) -> list[str]:
    """The probe as raw prose and smuggled inside JSON shapes a model might try."""
    return [
        t,
        json.dumps({"phrases": [{"id": t}]}),
        json.dumps({"text": t}),
        json.dumps({"phrases": [{"id": "lead", "text": t}]}),
        json.dumps({"phrases": [{"id": "lead"}], "why": t}),
        "```json\n" + json.dumps({"phrases": [{"id": t}]}) + "\n```",
    ]


@pytest.mark.parametrize("tier", TIERS)
def test_every_probe_is_refused_with_curation_forced_on_for_every_tier(tier):
    cfg, doc = _forced_on(), dict(DOC, tier=tier)
    leaks = []
    for t in P_CUR2 + P_CUR3:
        for answer in _wrappings(t):
            r = curation.curate(CARD, doc, call_model=lambda p, to, a=answer: a, cfg=cfg)
            if r["curated"] or r["text"] != CARD:
                leaks.append((t, r["reason"]))
    assert leaks == [], leaks[:5]


def test_every_valid_choice_renders_only_card_figures_and_no_behaviour():
    cfg = _forced_on()
    bank = list(cfg["why_template"]["phrase_bank"])
    pats = list(cfg["behaviour_patterns"])
    rendered = 0
    for k in (1, 2, 3):
        for combo in itertools.permutations(bank, k):
            answer = json.dumps({"phrases": [{"id": i} for i in combo]})
            r = curation.curate(CARD, DOC, call_model=lambda p, to, a=answer: a, cfg=cfg)
            assert r["curated"], (combo, r["reason"])
            why = r["text"].splitlines()[1]
            assert not curation.behaviour_hits(why, pats), why
            assert curation.ungrounded_numbers(why, CARD, DOC) == [], why
            assert curation.non_ascii_chars(why) == [], why
            rendered += 1
    assert rendered == len(bank) + len(bank) * (len(bank) - 1) + len(bank) * (len(bank) - 1) * (len(bank) - 2)


@pytest.mark.parametrize(
    "answer",
    [
        '{"phrases": []}',
        '{"phrases": [{"id": "lead"}, {"id": "lead"}]}',
        '{"phrases": [{"id": "lead", "c": [3]}]}',
        '{"phrases": [{"id": "lead", "c": [0]}]}',
        '{"phrases": [{"id": "lead", "c": [true]}]}',
        '{"phrases": [{"id": "lead", "c": [1, 1]}]}',
        '{"phrases": [{"id": "lead"}, {"id": "pair"}, {"id": "detail"}, {"id": "confirm"}]}',
        '{"phrases": [{"id": "Lead"}]}',
        "[]",
        "null",
        '{"phrases": "lead"}',
    ],
)
def test_malformed_choices_are_refused(answer):
    r = curation.curate(CARD, DOC, call_model=lambda p, to, a=answer: a, cfg=_forced_on())
    assert r["curated"] is False and r["text"] == CARD and r["reason"].startswith("not a phrase choice")


def test_a_phrase_whose_slot_the_card_does_not_show_is_refused():
    doc = {k: v for k, v in DOC.items() if k != "observations"}
    r = curation.curate(CARD, doc, call_model=lambda p, to: '{"phrases": [{"id": "unmeasured"}]}', cfg=_forced_on())
    assert r["curated"] is False and "does not show" in r["reason"]


def test_rendered_sentence_is_exact_and_uses_the_chosen_contributors():
    answer = '{"phrases": [{"id": "lead", "c": [2]}, {"id": "confirm"}, {"id": "unmeasured"}]}'
    r = curation.curate(CARD, DOC, call_model=lambda p, to: answer, cfg=_forced_on())
    assert r["curated"] and r["choice"][0] == {"id": "lead", "c": [2]}
    assert r["text"].splitlines()[1] == (
        "Why: Technical carries the largest share of the score at 24 points. 2 of 9 categories confirm. "
        "1 categories are unmeasured."
    )


def test_prompt_asks_for_a_choice_not_prose():
    prompt = curation.build_prompt(CARD, DOC, "x", _forced_on())
    assert "Return ONLY JSON" in prompt and "Do not write any sentence yourself" in prompt
    for pid in _forced_on()["why_template"]["phrase_bank"]:
        assert f"- {pid}:" in prompt


def test_shipped_config_still_skips_every_tier_and_carries_the_reminder():
    cfg = curation.load_config()
    assert {"RED", "ORANGE", "YELLOW", "BLUE", "GREEN"} <= {str(t).upper() for t in cfg["skip_tiers"]}
    assert cfg["disabled_until"]["review_by"].__str__() == "2026-11-07"
    for tier in TIERS:
        r = curation.curate(CARD, dict(DOC, tier=tier), call_model=lambda p, to: pytest.fail("model called"), cfg=cfg)
        assert r["curated"] is False
