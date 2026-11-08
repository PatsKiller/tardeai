"""LQ-20261107-513: the Home banner and the Home risk card name the same shock.

MEASURED 2026-11-07 20:41 ET (Saturday, market closed). Home showed, one above the other:
  * banner  "Market event · Broad selloff · baseline 2026-11-04 · RED"  (GET /api/v2/market-event/active
    episode.title, built in ``market_event_api.consumer_view`` from the stored episode KIND ``broad_selloff``);
  * risk card "Sector selloff — Technology / Semis. Not market-wide: 10 of 11 sectors holding."
    (GET /api/v2/market-risk/latest ``shock_type.class = SECTOR``, confidence 1.0, rendered by
    ``marketRisk.ts verdictLine``).
The episode kind is a trigger label: the detector opens ``broad_selloff/market`` when the MRE TIER is >= ORANGE
or an index draws down (spec §4.1); neither measures breadth. The Market Risk Engine's shock classifier does
(SYSTEMIC needs >= 80% of sectors down; it measured 8 of 11, defensives up, volatility calm). So the card was
right and the banner claimed a breadth nothing measured.

The fix: a market-scope episode's title is the MRE's shock verdict, in the same words and the same counts as the
risk card. Synthetic fixtures only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import market_event_brief as meb  # noqa: E402
from lib import market_event_api as api  # noqa: E402

MARKET_RISK_TS = ROOT / "apps/command-center-v3/src/lib/marketRisk.ts"

SECTOR_STATES = {"tech": "STRESS", "comm": "RESILIENT", "discretionary": "RESILIENT", "staples": "RESILIENT",
                 "healthcare": "RESILIENT", "utilities": "RESILIENT", "energy": "NEUTRAL",
                 "financials": "RESILIENT", "industrials": "NEUTRAL", "materials": "NEUTRAL",
                 "real_estate": "RESILIENT"}
LABELS = {"tech": "Technology", "comm": "Communications", "real_estate": "Real estate"}


def _heatmap(states: dict[str, str], themes: dict[str, str] | None = None) -> list[dict]:
    rows = [{"key": k, "label": LABELS.get(k, k.replace("_", " ").capitalize()), "kind": "sector", "state": s}
            for k, s in states.items()]
    rows += [{"key": k, "label": k.capitalize(), "kind": "theme", "state": s} for k, s in (themes or {}).items()]
    rows += [{"key": "defensive", "label": "Defensives", "kind": "defensive", "state": "RESILIENT"},
             {"key": "rates", "label": "Long Treasuries", "kind": "macro", "state": "STRESS"}]
    return rows


def _snap(cls: str | None, states=SECTOR_STATES, themes=None, measured: int | None = 11) -> dict:
    snap = {"schema": "MarketRiskSnapshot@v1", "as_of": "2026-11-08T01:00:00+00:00", "tier": "RED",
            "heatmap": _heatmap(states, {"semis": "STRESS", "ai_basket": "NEUTRAL"} if themes is None else themes),
            "sectors": {"sectors_measured": measured}}
    if cls is not None:
        snap["shock_type"] = {"schema": "MarketRiskShockType@v1", "class": cls, "confidence": 1.0}
    return snap


def _doc(kind="broad_selloff", scope="market") -> dict:
    return {"market_gate": {"evaluated": True, "passed": False, "tier": "RED", "primary": {}, "confirmations": []},
            "episode": {"episode_id": f"{kind}:{scope}:2026-11-04", "kind": kind, "scope": scope, "state": "OPEN",
                        "baseline_date": "2026-11-04"},
            "accounts": [], "candidates": []}


def test_sector_shock_banner_says_sector_selloff_not_broad():
    ep = api.consumer_view(_doc(), snapshot=_snap("SECTOR"))["episode"]
    assert ep["title"] == "Sector selloff · Technology / Semis · baseline 2026-11-04"
    assert "broad" not in ep["title"].lower()
    sh = ep["shock"]
    assert sh["class"] == "SECTOR" and sh["source"] == "market_risk"
    assert (sh["holding"], sh["measured"]) == (10, 11)
    # the exact sentence the Home risk card prints (marketRisk.ts verdictLine, its own test pins the same shape)
    assert sh["line"] == "Sector selloff — Technology / Semis. Not market-wide: 10 of 11 sectors holding."


def test_systemic_shock_says_market_wide_with_the_cards_count():
    states = {k: "STRESS" for k in SECTOR_STATES} | {"utilities": "RESILIENT", "staples": "NEUTRAL"}
    ep = api.consumer_view(_doc(), snapshot=_snap("SYSTEMIC", states=states, themes={}))["episode"]
    assert ep["title"].startswith("Market-wide selloff · ")
    assert ep["shock"]["line"] == "Market-wide selloff — 9 of 11 sectors down."


def test_unclassified_shock_claims_no_breadth():
    for snap in (_snap(None), _snap("MIXED"), None, {"schema": "MarketRiskUnreadable@v1"}):
        ep = api.consumer_view(_doc(), snapshot=snap)["episode"]
        assert "broad" not in ep["title"].lower() and "market-wide" not in ep["title"].lower(), ep["title"]
        assert ep["title"].endswith("· baseline 2026-11-04")
    assert api.consumer_view(_doc(), snapshot=None)["episode"]["shock"] is None
    assert api.consumer_view(_doc(), snapshot=_snap("MIXED"))["episode"]["title"].startswith("Mixed selloff")


def test_sector_scoped_episode_keeps_its_own_measured_title():
    ep = api.consumer_view(_doc(kind="sector_rotation", scope="tech"), snapshot=_snap("SYSTEMIC"))["episode"]
    assert ep["title"] == "Sector rotation · tech · baseline 2026-11-04"


def test_shock_words_match_the_risk_card():
    """One vocabulary: the Python map must equal marketRisk.ts SHOCK_WORDS, or the two surfaces drift again."""
    src = MARKET_RISK_TS.read_text()
    block = re.search(r"const SHOCK_WORDS[^{]*\{(.*?)\}", src, re.S)
    assert block, "SHOCK_WORDS not found in marketRisk.ts"
    ts = dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))
    assert ts == api.SHOCK_WORDS
    assert re.search(r"new Set\(\['STRESS', 'WEAK'\]\)", src) and api.STRESSED_STATES == ("STRESS", "WEAK")


def test_brief_and_open_text_use_the_same_name():
    payload = api.consumer_view(_doc(), snapshot=_snap("SECTOR"))
    assert meb._headline(payload).startswith("Sector selloff · Technology / Semis OPEN - tier RED")
    ev = meb.text_events(payload, {"last": {}})[0]
    assert ev["trigger"].startswith("Sector selloff · Technology / Semis opened, tier RED")
    assert len(ev["trigger"]) <= 160 and "broad" not in ev["trigger"].lower()
