"""ANCHOR: JOB_CATALOG_20261106 — job descriptions, ?status= / ?category= filters and /api/v2/jobs-catalog.

Operator 2026-11-06: "You can't click on the statuses to filter", "at least a line or two of normalization of what each
job does" and "another page that categorizes all of the jobs". Hermetic: synthetic lanes, tmp description parts and a
tmp category list only. No real lane ids or descriptions.
"""
import json
import logging
from pathlib import Path

import pytest

from scripts.lib import jobs_history as J
from tests.test_jobs_history import NOW, _state_root, cron_lane, n8n_lane, systemd_lane

CATS = [{"key": k, "label": k.title(), "blurb": f"synthetic {k}"} for k in ("market_data", "portfolio", "ops", "other")]


def _lanes():
    a = n8n_lane("synthetic-a")
    a["owner"] = "portfolio"
    b = cron_lane("synthetic-b")
    b["owner"] = "platform"
    c = systemd_lane("synthetic-c")
    c["owner"] = "nobody-knows"
    d = n8n_lane("synthetic-d")
    d.update(state="PAUSED", owner="portfolio")
    return [a, b, c, d]


def _setup(tmp_path, parts):
    reg = _state_root(tmp_path, _lanes())
    desc = tmp_path / "job_descriptions"
    desc.mkdir()
    for name, body in parts.items():
        (desc / name).write_text(body if isinstance(body, str) else json.dumps(body))
    cats = tmp_path / "job_categories.json"
    cats.write_text(json.dumps(CATS))
    return {"state_root": tmp_path, "registry_path": reg, "descriptions_dir": desc, "categories_path": cats}


GOOD = {"synthetic-a": {"title": "Synthetic price pull", "category": "market_data", "does": "Pulls synthetic prices.",
                        "breaks": "Synthetic pages go stale."},
        "synthetic-b": {"title": "Synthetic sweep", "category": "not-a-category", "does": "Sweeps.", "breaks": "  "}}


def test_descriptions_merge_and_fall_back(tmp_path, caplog):
    kw = _setup(tmp_path, {"part1.json": GOOD, "part2.json": "{not json", "part3.json": "[1, 2]"})
    with caplog.at_level(logging.WARNING, logger=J.__name__):
        snap = J.snapshot(now=NOW, **kw)
    assert sum("skipped" in r.message for r in caplog.records) == 2
    rows = {r["lane_id"]: r for r in snap["rows"]}
    a = rows["synthetic-a"]
    assert (a["title"], a["category"], a["category_key"], a["does"]) == ("Synthetic price pull", "market_data", "market_data", "Pulls synthetic prices.")
    b = rows["synthetic-b"]
    assert b["category"] is None and b["category_key"] == "ops" and b["breaks"] is None and b["does"] == "Sweeps."
    c = rows["synthetic-c"]
    assert c["title"] is None and c["does"] is None and c["category_fallback"] == "other" and c["category_key"] == "other"
    assert snap["described"] == 2 and [x["key"] for x in snap["categories"]] == [x["key"] for x in CATS]
    note = next(s for s in snap["sources"] if s["name"] == "job descriptions")["note"]
    assert "2 job descriptions from 1 file(s)" in note and "part2.json" in note and "part3.json" in note


def test_missing_descriptions_and_categories_never_crash(tmp_path):
    kw = _setup(tmp_path, {})
    kw["descriptions_dir"] = tmp_path / "absent"
    kw["categories_path"] = tmp_path / "absent.json"
    snap = J.snapshot(now=NOW, **kw)
    assert all(r["does"] is None and r["title"] is None for r in snap["rows"])
    assert "the job category list could not be read" in snap["gaps"]
    assert {r["category_key"] for r in snap["rows"]} == {"portfolio", "ops", "other"}


def test_status_and_category_filters_and_catalog(tmp_path):
    J._CACHE.clear()
    kw = _setup(tmp_path, {"part1.json": GOOD})
    full = J.get_jobs_history({"filter": "all", "limit": "200"}, **kw)
    assert full["total"] == 4 and full["rows"][0].keys() >= {"title", "does", "breaks", "category_key", "owner"}
    by_status = {}
    for r in full["rows"]:
        by_status.setdefault(r["status"], 0)
        by_status[r["status"]] += 1
    for status, count in by_status.items():
        if status in J.STATUS_FILTERS:
            assert J.get_jobs_history({"filter": "all", "status": status}, **kw)["total"] == count
    assert J.get_jobs_history({"filter": "all", "status": "paused"}, **kw)["rows"][0]["lane_id"] == "synthetic-d"
    assert J.get_jobs_history({"filter": "all", "status": "fixed"}, **kw)["total"] == full["summary"]["fixed_14d"]
    assert J.get_jobs_history({"filter": "all", "status": "missed"}, **kw)["total"] == full["summary"]["with_missed"]
    cat = J.get_jobs_history({"filter": "all", "category": "portfolio"}, **kw)
    assert [r["lane_id"] for r in cat["rows"]] == ["synthetic-d"] and cat["category"] == "portfolio"
    assert J.get_jobs_history({"filter": "all", "q": "price pull"}, **kw)["rows"][0]["lane_id"] == "synthetic-a"
    with pytest.raises(ValueError):
        J.get_jobs_history({"filter": "all", "status": "nope"}, **kw)
    with pytest.raises(ValueError):
        J.get_jobs_history({"filter": "all", "category": "nope"}, **kw)

    catalog = J.get_jobs_catalog({}, **kw)
    assert catalog["schema"] == "JobCatalog@v1" and catalog["jobs"] == 4 and catalog["described"] == 2
    keys = [c["key"] for c in catalog["categories"]]
    assert keys == ["market_data", "portfolio", "ops", "other"]  # config order; every category shown even when empty
    counts = {c["key"]: c for c in catalog["categories"]}
    assert counts["market_data"]["jobs"] == 1 and counts["market_data"]["described"] == 1
    assert counts["portfolio"]["status_mix"]["inactive"] == 1
    assert sum(c["jobs"] for c in catalog["categories"]) == 4
    assert all(sum(c["status_mix"].values()) == c["jobs"] for c in catalog["categories"])
    J._CACHE.clear()


def test_shipped_category_list_is_the_agreed_one():
    cats = json.loads((Path(J.ROOT) / "config/job_categories.json").read_text())
    assert [c["key"] for c in cats] == ["market_data", "portfolio", "signals", "cio", "research", "risk", "alerts",
                                        "learning", "agents_llm", "ops", "hygiene", "services", "side", "other"]
    assert all(set(c) == {"key", "label", "blurb"} and c["label"] and c["blurb"] for c in cats)
    assert set(J.OWNER_CATEGORY.values()) <= {c["key"] for c in cats}


def test_api_routes_are_get_only():
    src = (Path(J.ROOT) / "scripts/api_v2.py").read_text()
    block = src[src.index('if base_path == "/api/v2/jobs-catalog":'):][:400]
    assert 'if method != "GET":' in block and "get_jobs_catalog" in block
