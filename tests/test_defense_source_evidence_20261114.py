"""DR-D05 (sprint 8H-2 b3): every Defense source states who answers for it and where it is reviewed.

The desk could say a source was PAUSED or 30 h old, and nothing about who owns it or where to go to review it —
so "this evidence needs attention" had no addressee. The lane registry already publishes an `owner` per lane; the
projection now carries it (and the review surface) instead of leaving the page to invent one. A source with no
registered owner says so rather than guessing. Synthetic lanes and values only (the repository is public).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import desks_a as desk  # noqa: E402

NOW = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)
STATES = {lane: "ACTIVE" for lane in
          ["market-risk-evaluate", "sector-momentum-engine", "industry-momentum-groups", "defense-recommendations",
           "defense-inverse-stoplights", "options-lifecycle-run", "defense-cash-alternatives"]}

REGISTRY = {"lanes": [
    {"lane_id": "market-risk-evaluate", "state": "ACTIVE", "owner": "platform"},
    {"lane_id": "sector-momentum-engine", "state": "ACTIVE", "owner": "defense"},
    {"lane_id": "industry-momentum-groups", "state": "ACTIVE", "owner": "defense"},
    {"lane_id": "defense-recommendations", "state": "ACTIVE", "owner": "portfolio"},
    {"lane_id": "defense-inverse-stoplights", "state": "ACTIVE", "owner": "defense"},
    {"lane_id": "options-lifecycle-run", "state": "PAUSED", "owner": "execution"},
    {"lane_id": "defense-cash-alternatives", "state": "ACTIVE", "owner": "platform"},
    # deliberately no `owner`: a lane registered without one must not inherit a neighbour's answer
    {"lane_id": "industry-momentum-groups-flagless", "state": "ACTIVE"},
]}


def build(tmp_path, registry=REGISTRY):
    if registry is not None:
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "lane_registry.json").write_text(json.dumps(registry))
    return desk.defense_payload(root=tmp_path, now=NOW, truth={}, states=STATES)


def source(payload, sid):
    return next(s for s in payload["sources"] if s["id"] == sid)


def test_every_source_publishes_the_owner_its_lane_is_registered_under(tmp_path):
    doc = build(tmp_path)
    assert source(doc, "engine")["owner"] == "platform"          # market-risk-evaluate
    assert source(doc, "posture")["owner"] == "defense"          # sector-momentum-engine
    assert source(doc, "recommendations")["owner"] == "portfolio"
    assert source(doc, "options")["owner"] == "execution"
    # the owner travels with the source the writer belongs to, not with the desk
    assert source(doc, "posture")["lane_ids"] == ["sector-momentum-engine"]


def test_a_source_whose_lane_registers_no_owner_says_not_published(tmp_path):
    registry = {"lanes": [l for l in REGISTRY["lanes"] if l["lane_id"] != "options-lifecycle-run"]}
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "lane_registry.json").write_text(json.dumps(registry))
    doc = desk.defense_payload(root=tmp_path, now=NOW, truth={}, states=STATES)
    # every source names an owner, and one with none registered says so rather than borrowing the desk's
    assert all(s.get("owner") for s in doc["sources"])
    assert source(doc, "options")["owner"] == "not published"
    assert source(doc, "posture")["owner"] == "defense"


def test_an_unreadable_registry_is_not_published_never_a_guess(tmp_path):
    doc = build(tmp_path, registry=None)
    for s in doc["sources"]:
        if s["id"] == "review":
            continue
        assert s["owner"] == "not published", f"{s['id']} invented an owner with no registry: {s['owner']}"


def test_every_source_publishes_where_it_is_reviewed(tmp_path):
    doc = build(tmp_path)
    assert source(doc, "engine")["review_href"] == "/defense" and source(doc, "engine")["review_label"]
    assert source(doc, "stoplights")["review_href"] == "/defense?tab=hedges"
    assert source(doc, "review")["review_href"] == "/defense?tab=review-log"
    # each review surface is a route this app serves, not a page that does not exist
    served = {"/defense"} | {f"/defense?tab={t}" for t in ("where-to-act", "your-book", "hedges", "review-log")}
    for s in doc["sources"]:
        href = s["review_href"]
        assert href in served or href == "/watch?tab=sectors", f"{s['id']} links to a surface that is not served: {href}"


def test_the_operator_written_review_console_is_owned_by_the_operator(tmp_path):
    doc = build(tmp_path)
    review = source(doc, "review")
    # it has no writer lane by construction; its owner is the person who writes it
    assert review["lane_ids"] == []
    assert review["owner"] == "operator"


def test_the_existing_source_contract_is_unchanged(tmp_path):
    doc = build(tmp_path)
    engine = source(doc, "engine")
    # the fields the clocks and health line read stay exactly as they were
    assert engine["lane_ids"] == ["market-risk-evaluate"]
    assert "gap" in engine and "as_of" in engine and "label" in engine
    assert set(engine) - {"owner", "review_href", "review_label"} == {
        "id", "label", "as_of", "lane_ids", "gap", "max_age_hours"}
