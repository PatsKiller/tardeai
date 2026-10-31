"""Market Risk Engine × CIO × LLM curation (DSN-20261031-market-risk-engine P3-T3). Synthetic fixtures only; the
model is always stubbed (no network, no spend)."""

import time
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.market_risk import cio_context as cc
from scripts.lib.market_risk import curation as cur

NOW = datetime(2026, 10, 29, 22, 15, tzinfo=timezone.utc)

CARD = (
    "🔴 MARKET RISK RED 83/100 · 5 of 9 categories confirm\n"
    "Why: futures, event concentration and index options flow all point lower.\n"
    "Futures / extended hours +18 · NQ -1.6% 18:04 ET\n"
    "Options flow +15 · QQQ P/C vol 3.31 (2.9x median)\n"
    "Advisory. No order, size or stop level is implied."
)


def _mr(tier="ORANGE", state="evaluated", score=63, as_of=None):
    return {
        "state": state,
        "tier": tier,
        "score": score,
        "as_of": (as_of or NOW).isoformat(),
        "confirming": {"n": 4, "of": 9},
        "contributors": [
            {"name": "Event cluster", "points": 17, "detail": "25% of index cap reports in 48h"},
            {"name": "Volatility", "points": 13, "detail": "VIX 16.9 at the week low"},
            {"name": "Technical", "points": 12, "detail": "QQQ failed retest"},
        ],
        "deescalates_if": "QQQ holds its 20-day average",
        "stale": state == "stale",
    }


ASSESS = {
    "tier": "RED",
    "score": 83,
    "confirming": {"n": 5, "of": 9},
    # the contributor's displayed figures are the ONLY grounding material besides the score (review of #2362, B3)
    "contributors": [{"name": "Futures", "points": 18, "detail": "NQ -1.6% after hours · QQQ P/C vol 3.31"}],
}


def _cfg(**over):
    cfg = cur.load_config()
    # The shipped config never curates ORANGE/RED (review of #2362, B3); these tests exercise the lexicon and grounding
    # on a RED fixture card, so they lift the skip explicitly. test_market_risk_review_fixes pins the shipped default.
    cfg["skip_tiers"] = []
    cfg.update(over)
    return cfg


# ── curation ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_grounded_rewrite_replaces_only_the_why_line():
    out = cur.curate(
        CARD,
        ASSESS,
        call_model=lambda p, t: ("Futures fell 1.6% after hours and options hedging hit 3.31.", "grok"),
        cfg=_cfg(),
    )
    assert out["curated"] is True and out["lane"] == "grok"
    lines = out["text"].splitlines()
    assert lines[1] == "Why: Futures fell 1.6% after hours and options hedging hit 3.31."
    assert lines[0] == CARD.splitlines()[0] and lines[2:] == CARD.splitlines()[2:]


def test_new_number_is_rejected_and_card_unchanged():
    out = cur.curate(
        CARD, ASSESS, call_model=lambda p, t: "Futures fell 4.7% and the index lost 212 points.", cfg=_cfg()
    )
    assert out["curated"] is False and out["text"] == CARD
    assert out["reason"] == "ungrounded numbers rejected" and out["rejected"]


@pytest.mark.parametrize(
    "answer",
    ["Consider a trim of 500 shares before the open.", "Set stops at the 20-day average.", "Buy puts on QQQ now."],
)
def test_behaviour_wording_is_rejected(answer):
    out = cur.curate(CARD, ASSESS, call_model=lambda p, t: answer, cfg=_cfg())
    assert out["curated"] is False and out["text"] == CARD and out["reason"] == "behaviour wording rejected"


def test_timeout_sends_deterministic_card_without_waiting():
    cfg = _cfg(timeout_s={"RED": 0.2, "default": 0.2})

    def slow(p, t):
        time.sleep(2)
        return "too late"

    t0 = time.monotonic()
    out = cur.curate(CARD, ASSESS, call_model=slow, cfg=cfg)
    assert out["curated"] is False and out["text"] == CARD and out["reason"].startswith("timeout")
    assert time.monotonic() - t0 < 1.5


def test_lane_failure_and_empty_answer_fall_back():
    def boom(p, t):
        raise RuntimeError("AllLanesFailed")

    assert cur.curate(CARD, ASSESS, call_model=boom, cfg=_cfg())["text"] == CARD
    assert cur.curate(CARD, ASSESS, call_model=lambda p, t: "  ", cfg=_cfg())["reason"] == "empty answer"


def test_skip_tiers_and_disabled_never_call_the_model():
    def never(p, t):
        raise AssertionError("model must not be called")

    assert cur.curate(CARD, ASSESS, call_model=never, cfg=_cfg(skip_tiers=["RED"]))["reason"].startswith("tier RED")
    assert cur.curate(CARD, ASSESS, call_model=never, cfg=_cfg(enabled=False))["reason"] == "curation disabled"


def test_card_without_why_line_gets_one_after_the_header():
    card = "\n".join(l for l in CARD.splitlines() if not l.startswith("Why:"))
    out = cur.curate(card, ASSESS, call_model=lambda p, t: "Futures fell 1.6% after hours.", cfg=_cfg())
    assert out["curated"] and out["text"].splitlines()[1] == "Why: Futures fell 1.6% after hours."


def test_policy_file_and_registry_row_exist():
    cfg = cur.load_config()
    assert cfg["allow_paid"] is False and cfg["process_id"] == "market_risk_alert_curation"
    import json
    from pathlib import Path

    reg = json.loads((Path(cur.PROJECT_ROOT) / "config/llm_process_registry.json").read_text())
    row = next(p for p in reg["processes"] if p["id"] == cfg["process_id"])
    assert (
        row["allowed_lanes"] == ["grok", "chatgpt"] and row["advisory_only"] is True and row["tools_allowed"] is False
    )


# ── CIO context ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_tier_line_evaluated_and_not_evaluated():
    line = cc.tier_line(_mr())
    assert line.startswith("Market risk ORANGE 63/100 — Event cluster, Volatility, Technical; as of ")
    assert cc.tier_line(None) == "Market risk: not yet evaluated (no engine snapshot)"
    ne = {
        "state": "not_evaluated",
        "tier": "NOT_EVALUATED",
        "reason": "engine not live",
        "sources": {"options_flow": {"findings": [{"symbol": "QQQ", "state": "STRESS"}]}},
    }
    assert cc.tier_line(ne) == "Market risk: not yet evaluated · options flow QQQ stress"
    assert "ORANGE" not in cc.tier_line({"state": "not_evaluated", "tier": "ORANGE"})  # never a tier nobody computed


def test_ask_facts_carry_tier_contributors_and_as_of():
    f = cc.ask_facts(_mr())
    assert f["tier"] == "ORANGE" and f["score"] == 63 and f["as_of"] == NOW.isoformat()
    assert [c["name"] for c in f["contributors"]] == ["Event cluster", "Volatility", "Technical"]
    assert cc.ask_facts(None)["tier"] == "NOT_EVALUATED"


GATE = {
    "enabled": True,
    "demote_tiers": ["YELLOW"],
    "hold_tiers": ["ORANGE", "RED"],
    "entry_types": ["new_position", "re_entry", "add_on"],
    "hold_stances": {"ADD": "HOLD", "RE_ENTER": "WATCH"},
    "max_stale_hours": 4,
}


def _book():
    return [
        {"symbol": "AAA", "type": "add_on", "stance": "ADD", "conviction": 82, "rank": 1},
        {"symbol": "BBB", "type": "re_entry", "stance": "RE_ENTER", "conviction": 75, "rank": 2},
        {"symbol": "CCC", "type": "new_position", "stance": "WATCH", "conviction": 71, "rank": 3},
        {"symbol": "DDD", "type": "existing", "stance": "HOLD", "conviction": 60, "rank": 4},
    ]


def test_gate_holds_entries_at_orange_and_leaves_rank_and_conviction():
    out, rep = cc.apply_entry_gate(_book(), _mr("ORANGE"), GATE, now=NOW)
    by = {a["symbol"]: a for a in out}
    assert rep["action"] == "hold" and rep["held"] == ["AAA", "BBB", "CCC"]
    assert by["AAA"]["stance"] == "HOLD" and by["AAA"]["stance_suppressed"]["from"] == "ADD"
    assert by["BBB"]["stance"] == "WATCH"
    assert "market_risk_gate" not in by["DDD"] and by["DDD"]["stance"] == "HOLD"
    assert [a["conviction"] for a in out] == [82, 75, 71, 60] and [a["rank"] for a in out] == [1, 2, 3, 4]


def test_gate_demotes_at_yellow_without_changing_stance():
    out, rep = cc.apply_entry_gate(_book(), _mr("YELLOW", score=44), GATE, now=NOW)
    assert rep["action"] == "demote" and rep["demoted"] == ["AAA", "BBB", "CCC"]
    assert [a["stance"] for a in out] == ["ADD", "RE_ENTER", "WATCH", "HOLD"]


def test_gate_ignores_unevaluated_blue_and_old_stale_tiers():
    for mr in (
        None,
        {"state": "not_evaluated", "tier": "NOT_EVALUATED"},
        _mr("BLUE"),
        _mr("RED", state="stale", as_of=NOW - timedelta(hours=9)),
    ):
        out, rep = cc.apply_entry_gate(_book(), mr, GATE, now=NOW)
        assert rep["action"] is None and all("market_risk_gate" not in a for a in out)
    _, rep = cc.apply_entry_gate(_book(), _mr("RED", state="stale", as_of=NOW - timedelta(hours=2)), GATE, now=NOW)
    assert rep["action"] == "hold"


def test_repo_gate_config_matches_the_approved_shape():
    g = cc.load_gate_config()
    assert g["enabled"] is True and g["demote_tiers"] == ["YELLOW"] and g["hold_tiers"] == ["ORANGE", "RED"]


# ── CIO consumers ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_temperament_turns_defensive_at_orange_and_red_only_when_evaluated():
    from scripts.lib.cio_investment_product import build_temperament

    base = dict(
        regime={"label": "risk_on_trend"},
        holdings={},
        fs_rows=[],
        lessons={},
        infl={
            "gates": {"lesson_mode": "x", "financial_senses_mode": "x"},
            "memory_mode": "x",
            "memory_behavior_influence": "x",
        },
    )
    red = build_temperament(**base, market_risk=_mr("RED", score=83))
    assert red["title"].startswith("RISK ON TREND — DEFENSIVE") and "MARKET RISK RED 83/100" in red["title"]
    assert red["market_risk"]["posture"].startswith("DEFENSIVE")
    plain = build_temperament(**base, market_risk={"state": "not_evaluated", "tier": "NOT_EVALUATED"})
    assert plain["title"] == "RISK ON TREND — SELECTIVE RISK" and plain["market_risk"]["posture"] is None


def test_advice_digest_opens_with_tier_line_and_sorts_gated_entries_last():
    from scripts.lib import advice_digest as ad

    msgs = ad.render("10", {}, [], {}, None, {}, NOW, market_risk_line=cc.tier_line(_mr()))
    assert "Market risk ORANGE 63/100" in msgs[0].split("\n━━")[0]
    msgs = ad.render("10", {}, [], {}, None, {}, NOW, market_risk_line=cc.tier_line(None))
    assert "Market risk: not yet evaluated" in msgs[0]
    items = [{"symbol": "AAA"}, {"symbol": "BBB"}]
    facts = {
        "AAA": {"cio": {"conviction": 90, "market_risk_gate": {"action": "demote"}}},
        "BBB": {"cio": {"conviction": 70}},
    }
    shown, _ = ad.rank_by_conviction(items, facts, 55)
    assert [i["symbol"] for i in shown] == ["BBB", "AAA"]


def _patch_loader(monkeypatch, value):
    # the cron path imports lib.market_risk.cio_context (scripts/ on sys.path), tests import scripts.lib...; patch both
    import importlib

    for name in ("scripts.lib.market_risk.cio_context", "lib.market_risk.cio_context"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "load_market_risk", lambda v=value: v)


def test_morning_brief_carries_the_tier_line(monkeypatch):
    import scripts.send_morning_brief as smb

    _patch_loader(monkeypatch, _mr("RED", score=83))
    text = smb.format_telegram({"generated_at": "2026-10-30T11:30:00Z"})
    assert text.splitlines()[1].startswith("Market risk RED 83/100")
    _patch_loader(monkeypatch, None)
    assert "Market risk: not yet evaluated" in smb.format_telegram({"generated_at": "2026-10-30"})


def test_ask_the_cio_facts_contain_the_tier(monkeypatch):
    from scripts.lib import cio_operator_desk_loop as dl

    _patch_loader(monkeypatch, _mr("ORANGE"))
    ev = dl.gather_freeform_context({"symbols": [], "text": ""})
    facts = ev["available"]["freeform_context"]
    assert facts["market_risk"]["tier"] == "ORANGE" and facts["market_risk"]["score"] == 63
    assert "market_risk_projection" in ev["sources"]
