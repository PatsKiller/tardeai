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

# Round-3 review probes, ~/agent_scratch/r3probes/p_cur4.py (verbatim).
P_CUR4 = [
    "Lower risk now.",
    "Less risk now.",
    "Hedging now, with options.",
    "Options hedging now is the only open.",
    "Index fell 50 percent today.",
    "The index fell 32 percent today.",
    "Market down 50 percent.",
    "Semiconductors fell 18 percent.",
    "Risk is low and the market is calm.",
    "All categories calm; risk is low.",
    "No stress; market steady; risk low.",
    "Volatility is low and quiet; no risk.",
    "Index up 32 percent.",
    "Below 50 now, so lower.",
    "Put/call 3.97, so options hedging and more puts.",
    "Less market, more options hedging.",
    "Hedging demand high: hedging now.",
    "Ass.",
    "Less semiconductor risk.",
    "Semiconductors: less now.",
    "Lower semiconductors now.",
    "Open interest is high, so open hedging now.",
    "Index to 2 percent below.",
    "Market is 50 percent below the high.",
    "QQQ fell 3.97 percent.",
    "QQQ 32 percent lower by the open.",
    "Down 18 percent at the open.",
    "Risk is 50 and lower is better.",
    "Exit",
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
    for t in P_CUR2 + P_CUR3 + P_CUR4:
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
            if "calm_rest" in combo:  # a YELLOW card may never say the rest is calm (review #2383 round 3)
                assert not r["curated"] and "not allowed at tier YELLOW" in r["reason"], (combo, r["reason"])
                continue
            assert r["curated"], (combo, r["reason"])
            why = r["text"].splitlines()[1]
            assert not curation.behaviour_hits(why, pats), why
            assert curation.ungrounded_numbers(why, CARD, DOC) == [], why
            assert curation.non_ascii_chars(why) == [], why
            rendered += 1
    b = len(bank) - 1  # calm_rest is refused on this YELLOW card
    assert rendered == b + b * (b - 1) + b * (b - 1) * (b - 2)


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
    # review #2406 F3: "lead" always names the top-points contributor, whatever position the model asks for (this
    # test used to pin "Technical carries the largest share ... 24 points", which was false); F8: "1 category is".
    answer = '{"phrases": [{"id": "lead", "c": [2]}, {"id": "confirm"}, {"id": "unmeasured"}]}'
    r = curation.curate(CARD, DOC, call_model=lambda p, to: answer, cfg=_forced_on())
    assert r["curated"], r["reason"]
    assert r["text"].splitlines()[1] == (
        "Why: Options flow carries the largest share of the score at 32 points. 2 of 9 categories confirm. "
        "1 category is unmeasured."
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


TIERS_ALL = ("RED", "ORANGE", "YELLOW", "BLUE", "GREEN")


@pytest.mark.parametrize("tier", TIERS_ALL)
def test_validator_alone_refuses_every_probe_on_every_tier(tier):
    """Defence in depth: even if prose ever reached the checks, every probe fails them."""
    cfg, doc = _forced_on(), dict(DOC, tier=tier)
    passed = [t for t in P_CUR2 + P_CUR3 + P_CUR4 if curation.validate_sentence(t, CARD, doc, cfg) is None]
    assert passed == []


@pytest.mark.parametrize(
    "sentence,reason",
    [
        ("Lower risk now.", "imperative"),
        ("Hedging demand high: hedging now.", "imperative"),
        ("Index fell 50 percent today.", "outside the template"),
        ("Options flow carries 50 points.", "own label"),
        ("Risk is low and the market is calm.", "calm wording"),
        ("Ass.", "outside the template"),
    ],
)
def test_round3_examples_fail_for_the_named_reason(sentence, reason):
    r = curation.validate_sentence(sentence, CARD, dict(DOC, tier="RED"), _forced_on())
    assert r is not None and reason in r[0], (sentence, r)


def test_numbers_only_next_to_their_own_label():
    cfg, doc = _forced_on(), DOC
    assert curation.validate_sentence("The risk score reads 50, led by Options flow.", CARD, doc, cfg) is None
    assert (
        curation.validate_sentence("Options flow carries the largest share of the score at 32 points.", CARD, doc, cfg)
        is None
    )
    for bad in ("The risk score reads 32, led by Options flow.", "2 of 9 points.", "Options flow at 3.97 points."):
        r = curation.validate_sentence(bad, CARD, doc, cfg)
        assert r is not None, bad


def test_exact_plural_rule():
    vocab = {"a", "category", "box", "score"}
    assert curation._in_vocab("categorys", vocab) is True  # plain plural of a listed word
    assert curation._in_vocab("boxes", vocab) and curation._in_vocab("score's", vocab)
    assert not curation._in_vocab("ass", vocab) and not curation._in_vocab("as", {"a"})


def test_calm_rest_needs_low_tier_and_every_other_category_calm():
    cfg = _forced_on()
    choice = '{"phrases": [{"id": "lead", "c": [1]}, {"id": "calm_rest"}]}'
    calm_doc = dict(
        DOC,
        tier="BLUE",
        contributors=DOC["contributors"][:1],
        observations=[{"category": "options_flow", "state": "WARN"}, {"category": "technical", "state": "CALM"}],
    )
    r = curation.curate(CARD, calm_doc, call_model=lambda p, to: choice, cfg=cfg)
    assert r["curated"], r["reason"]
    warm = dict(
        calm_doc,
        observations=[{"category": "options_flow", "state": "WARN"}, {"category": "technical", "state": "WARN"}],
    )
    r = curation.curate(CARD, warm, call_model=lambda p, to: choice, cfg=cfg)
    assert not r["curated"] and "CALM" in r["reason"]
    r = curation.curate(CARD, dict(calm_doc, tier="RED"), call_model=lambda p, to: choice, cfg=cfg)
    assert not r["curated"] and r["reason"] == "tier RED is never curated"  # code floor (F2)


# ── review #2406, F1-F8 ────────────────────────────────────────────────────────────────────────────────────────


def _syn(tier: str, score: int, cons: list[dict]) -> dict:
    return {
        "schema": "MarketRiskAssessment@v1",
        "tier": tier,
        "market_tier": tier,
        "score": score,
        "market_score": score,
        "as_of": "2026-10-31T14:30:00Z",
        "confirming": len(cons),
        "contributors": cons,
        "observations": [
            {
                "category": c["category"],
                "state": "STRESS",
                "score": 80.0,
                "observed_at": "2026-10-31T14:00:00Z",
                "headline": c["headline"],
            }
            for c in cons
        ],
    }


def test_f1_a_retried_card_is_never_curated_against_a_later_doc(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import market_risk_evaluate as mre
    from scripts.lib.market_risk import alerts
    from scripts.lib.market_risk import policy as mr_policy

    pol = mr_policy.load_policy()
    red = _syn("RED", 88, [{"category": "volatility", "points": 44, "headline": "Volatility: VIX 41.0 (2.9x median)"}])
    yel = _syn("YELLOW", 55, [{"category": "options_flow", "points": 32, "headline": "Options flow: QQQ P/C OI 3.97"}])
    curated: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mre,
        "_curate",
        lambda text, d, call_model, live: (
            curated.append((d["tier"], text.splitlines()[0])) or {"text": text, "curated": False, "reason": "spy"}
        ),
    )
    sent = {"ok": False}
    monkeypatch.setattr(alerts, "deliver", lambda m, intent, policy, **k: {"sent": sent["ok"], "intent": intent})
    store, ledger = tmp_path / "ep.json", tmp_path / "keys.json"
    t1 = datetime(2026, 10, 31, 14, 31, tzinfo=timezone.utc)
    mre._cycle(t1, red, None, None, pol, True, store, ledger, None)  # RED card fails to send, stays queued
    curated.clear()
    sent["ok"] = True
    out = mre._cycle(t1 + timedelta(minutes=15), yel, None, red, pol, True, store, ledger, None)
    reasons = {s["intent"]["tier"]: s["curation_reason"] for s in out["sends"]}
    assert reasons["RED"] == "not curated: card built in an earlier cycle"
    assert [t for t, _ in curated] == ["YELLOW"] and "RED" not in curated[0][1]


@pytest.mark.parametrize("tier", ["RED", "red", " RED", "Red​", "", "NONE", "ORANGE", "orange ", "PURPLE", None])
def test_f2_code_floor_refuses_before_config(tier):
    cfg = dict(_forced_on(), skip_tiers=[], enabled=True)
    r = curation.curate(CARD, dict(DOC, tier=tier), call_model=lambda p, to: pytest.fail("model called"), cfg=cfg)
    assert r["curated"] is False and r["reason"].endswith("is never curated")


def test_f2_curatable_is_exactly_blue_yellow_green():
    assert curation.CURATABLE == frozenset({"BLUE", "YELLOW", "GREEN"})


def test_f3_lead_and_score_always_name_the_top_contributor():
    cfg = _forced_on()
    for pid in ("lead", "score"):
        r = curation.curate(
            CARD, DOC, call_model=lambda p, to, i=pid: f'{{"phrases": [{{"id": "{i}", "c": [2]}}]}}', cfg=cfg
        )
        assert (
            r["curated"]
            and "Options flow" in r["text"].splitlines()[1]
            and "Technical" not in r["text"].splitlines()[1]
        )


def test_f3_pair_needs_half_the_points():
    cfg = _forced_on()
    doc = dict(
        DOC,
        contributors=DOC["contributors"]
        + [
            {"category": "breadth", "points": 30, "headline": "Breadth: 3 of 11 sectors up"},
            {"category": "event", "points": 30, "headline": "Event: 4 names report"},
        ],
    )
    # options_flow 32 + technical 24 = 56 of 116 (48%): refused; options_flow 32 + breadth 30 + ... positions 1, 3
    r = curation.curate(CARD, doc, call_model=lambda p, to: '{"phrases": [{"id": "pair", "c": [1, 2]}]}', cfg=cfg)
    assert not r["curated"] and "at least half" in r["reason"]
    ok = dict(doc, contributors=doc["contributors"][:2])
    r = curation.curate(CARD, ok, call_model=lambda p, to: '{"phrases": [{"id": "pair"}]}', cfg=cfg)
    assert r["curated"], r["reason"]


def test_f4_calm_rest_rules():
    cfg = _forced_on()
    base = dict(
        DOC,
        tier="BLUE",
        observations=[
            {"category": "options_flow", "state": "WARN"},
            {"category": "technical", "state": "WARN"},
            {"category": "breadth", "state": "CALM"},
        ],
    )
    alone = '{"phrases": [{"id": "calm_rest"}]}'
    assert "cannot stand alone" in curation.curate(CARD, base, call_model=lambda p, to: alone, cfg=cfg)["reason"]
    one_named = '{"phrases": [{"id": "lead"}, {"id": "calm_rest"}]}'
    r = curation.curate(CARD, base, call_model=lambda p, to: one_named, cfg=cfg)
    assert not r["curated"] and "every displayed contributor named" in r["reason"]
    both = '{"phrases": [{"id": "pair"}, {"id": "calm_rest"}]}'
    assert curation.curate(CARD, base, call_model=lambda p, to: both, cfg=cfg)["curated"]
    warm = dict(base, observations=base["observations"][:2] + [{"category": "breadth", "state": "WARN"}])
    assert "CALM" in curation.curate(CARD, warm, call_model=lambda p, to: both, cfg=cfg)["reason"]


def test_f5_confirm_must_match_the_header():
    cfg = _forced_on()
    ans = '{"phrases": [{"id": "lead"}, {"id": "confirm"}]}'
    assert curation.curate(CARD, DOC, call_model=lambda p, to: ans, cfg=cfg)["curated"]
    off = dict(DOC, confirming={"n": 2, "of": 7})
    r = curation.curate(CARD, off, call_model=lambda p, to: ans, cfg=cfg)
    assert not r["curated"] and "header" in r["reason"]
    no_header = CARD.replace(" · 2 of 9 categories confirm", "")
    r = curation.curate(no_header, DOC, call_model=lambda p, to: ans, cfg=cfg)
    assert not r["curated"] and "header" in r["reason"]


@pytest.mark.parametrize("pts", [float("nan"), float("inf"), "32", True, None])
def test_f6_points_must_be_finite_numbers(pts):
    doc = dict(DOC, contributors=[dict(DOC["contributors"][0], points=pts), DOC["contributors"][1]])
    r = curation.curate(CARD, doc, call_model=lambda p, to: '{"phrases": [{"id": "lead"}]}', cfg=_forced_on())
    assert not r["curated"] and "finite number" in r["reason"]


def test_f7_a_hung_model_runs_on_a_daemon_thread():
    import threading
    import time as _t

    gate = threading.Event()

    def hang(p, to):
        gate.wait(5)
        return '{"phrases": [{"id": "lead"}]}'

    cfg = dict(_forced_on(), timeout_s={"YELLOW": 0.2, "default": 0.2})
    t0 = _t.monotonic()
    r = curation.curate(CARD, DOC, call_model=hang, cfg=cfg)
    assert r["reason"].startswith("timeout") and _t.monotonic() - t0 < 1.5
    workers = [t for t in threading.enumerate() if t.name == "market-risk-curation"]
    assert workers and all(t.daemon for t in workers)
    gate.set()


def test_f8_singular_unmeasured():
    assert curation.unmeasured_clause(1) == "1 category is unmeasured"
    assert curation.unmeasured_clause(3) == "3 categories are unmeasured"


def test_f1r2_a_key_collision_never_curates_the_old_card_against_new_data(tmp_path, monkeypatch):
    """Review #2406 round 2, F1-r2 scenario C: BLUE→YELLOW (send fails), back to BLUE (still failing), YELLOW again
    the same day. The second YELLOW recomputes the same dedupe key, outbox_put keeps the OLD text, and that old card
    must go out uncurated rather than with a Why line built from the new assessment."""
    from datetime import datetime, timedelta, timezone

    import market_risk_evaluate as mre
    from scripts.lib.market_risk import alerts
    from scripts.lib.market_risk import policy as mr_policy

    pol = mr_policy.load_policy()
    blue = _syn("BLUE", 20, [{"category": "seasonal", "points": 20, "headline": "Seasonal: month-end"}])
    y_old = _syn("YELLOW", 55, [{"category": "volatility", "points": 44, "headline": "Volatility: VIX 31.0"}])
    y_new = _syn("YELLOW", 57, [{"category": "options_flow", "points": 29, "headline": "Options flow: QQQ P/C OI 2.9"}])
    curated: list[str] = []
    monkeypatch.setattr(
        mre,
        "_curate",
        lambda text, d, call_model, live: (
            curated.append(text) or {"text": text, "curated": True, "reason": "spy"}
        ),
    )
    sent = {"ok": False}
    monkeypatch.setattr(alerts, "deliver", lambda m, intent, policy, **k: {"sent": sent["ok"], "intent": intent})
    store, ledger = tmp_path / "ep.json", tmp_path / "keys.json"
    t1 = datetime(2026, 10, 30, 14, 31, tzinfo=timezone.utc)
    mre._cycle(t1, y_old, None, blue, pol, True, store, ledger, None)
    mre._cycle(t1 + timedelta(minutes=15), blue, None, y_old, pol, True, store, ledger, None)
    curated.clear()
    sent["ok"] = True
    out = mre._cycle(t1 + timedelta(minutes=30), y_new, None, blue, pol, True, store, ledger, None)
    old_sends = [s for s in out["sends"] if "+44" in s["text"] or "VIX 31.0" in s["text"]]
    assert old_sends, "scenario did not reproduce the key collision"
    for s in old_sends:
        assert s["curated"] is False and s["curation_reason"] == "not curated: card built in an earlier cycle"
    assert not any("VIX 31.0" in t or "+44" in t for t in curated)
