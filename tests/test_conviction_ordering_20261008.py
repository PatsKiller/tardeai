"""Advice ranked by CIO conviction (operator 2026-10-08: the reward list was ordered by each message's own reward
score, and CIO entry alerts fired on names the CIO ranks near the bottom — "fix implement").

Communications: conviction sort / reward board ordering with below-floor names last and tagged. Advice digest: entry
and re-entry sections ordered by conviction, below-floor names collapsed to one line, CIO notes never capped (each is
marked delivered after a send). Fakes only: no database, no network, no real CIO memory.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import communications_portal as cp  # noqa: E402
from scripts.lib import advice_digest as ad  # noqa: E402

PROJ = {"QTEX": {"conviction": 83.1, "rank": 5}, "NFLX": {"conviction": 74.5, "rank": 141},
        "VCIG": {"conviction": 34.4, "rank": 1314}, "GXAI": {"conviction": 50.1, "rank": 1074}}
NOW = datetime(2026, 10, 8, 19, 0, tzinfo=timezone.utc)


def ev(sym, **k):
    return {"event_id": f"e-{sym}", "symbols": [sym] if sym else [], **k}


def test_conviction_order_floor_and_unscored(monkeypatch):
    monkeypatch.setattr(cp, "_opportunity_items", lambda: PROJ)
    rows = [ev("VCIG"), ev("NFLX"), ev("UNSCORED"), ev("QTEX"), ev("GXAI"), ev(None)]
    order = [(e["symbols"] or ["-"])[0] for e in cp.conviction_order(rows, 55.0)]
    assert order == ["QTEX", "NFLX", "UNSCORED", "-", "GXAI", "VCIG"]
    # no floor: a plain conviction ranking, unscored after scored
    order = [(e["symbols"] or ["-"])[0] for e in cp.conviction_order(rows, None)]
    assert order[:4] == ["QTEX", "NFLX", "GXAI", "VCIG"]


def test_attach_market_tags_low_conviction(monkeypatch):
    monkeypatch.setattr(cp, "_opportunity_items", lambda: {
        "VCIG": {"conviction": 34.4, "rank": 1314, "risk_reward": {"entry_zone": [1.55, 1.75], "primary_target": 2.2}},
        "QTEX": {"conviction": 83.1, "rank": 5, "risk_reward": {"entry_zone": [1.82, 1.92], "primary_target": 5.0}},
        "BARE": {"conviction": 40.0, "rank": 1200}})
    monkeypatch.setattr(cp, "conviction_floor", lambda: 55.0)
    import lib.data_broker.market_quote as mq
    monkeypatch.setattr(mq, "get_price_batch", lambda *a, **k: {})
    out = {e["symbols"][0]: e for e in cp.attach_market([ev("VCIG"), ev("QTEX"), ev("BARE")])}
    assert out["VCIG"]["levels"]["low_conviction"] is True and out["VCIG"]["levels"]["conviction_floor"] == 55.0
    assert "low_conviction" not in out["QTEX"]["levels"]
    assert out["BARE"]["levels"] == {"conviction": 40.0, "rank": 1200, "low_conviction": True, "conviction_floor": 55.0}


def test_conviction_is_a_hub_sort_and_reward_panel_is_ranked():
    assert "conviction" in cp.HUB_SORTS and "reward" in cp.CONVICTION_PANELS
    parts = (ROOT / "apps/command-center-v3/src/components/comms/CommsHubParts.tsx").read_text(encoding="utf-8")
    assert "category: 'reward,high_conviction_opportunity,re_entry', sort: 'conviction'" in parts


def test_floor_is_configured():
    from lib.data_broker.opportunity import load_config

    assert 0 < float(load_config()["advice"]["conviction_floor"]) < 100


def _facts():
    return {s: {"cio": a} for s, a in PROJ.items()}


def test_digest_ranks_entries_and_collapses_below_floor():
    items = [{"symbol": s, "event_id": f"e-{s}"} for s in ("VCIG", "NFLX", "NEWCO", "QTEX", "GXAI")]
    shown, below = ad.rank_by_conviction(items, _facts(), 55.0)
    assert [i["symbol"] for i in shown] == ["QTEX", "NFLX", "NEWCO"]
    assert [i["symbol"] for i in below] == ["GXAI", "VCIG"]


def test_render_caps_ranked_sections_but_never_cio_notes(monkeypatch):
    monkeypatch.setattr(ad, "_conviction_floor", lambda: 55.0)
    cfg = dict(ad.load_config())
    cfg["max_items_per_section"] = 2
    monkeypatch.setattr(ad, "load_config", lambda: cfg)
    sections = {"entries": [{"symbol": s, "event_id": f"e-{s}", "headline": f"{s} entry"} for s in
                            ("VCIG", "NFLX", "NEWCO", "QTEX", "GXAI")],
                "reentry": [], "cio": [{"symbol": f"C{i}", "event_id": f"c{i}", "headline": "note"} for i in range(4)]}
    held = [{"symbol": f"H{i}", "notification_id": f"n{i}", "headline": "held"} for i in range(5)]
    html = "\n".join(ad.render("15", sections, held, _facts(), None, {"rows": []}, NOW))
    assert html.index("$QTEX") < html.index("$NFLX")
    assert "+1 more, ranked by conviction" in html and "preset=reward" in html
    assert "Below CIO conviction 55 (2)" in html and html.index("$GXAI") < html.index("$VCIG")
    # CIO section: comms items capped as before (2), every held note shown
    for i in range(5):
        assert f"$H{i}" in html
    assert "$C0" in html and "$C1" in html and "$C2" not in html
