"""LQ-20261107-1638 — disk hygiene by an ABSOLUTE budget, not by how big the drive is.

Operator, 2026-11-09, verbatim: "a new 2TB drive is going in this week; hygiene must NOT relax because there is
more space — cache and scratch must not just grow."

The measurements behind these tests (2026-11-09, read-only, worker cc-deepseek-8):

  * the standing lane planned 19.65 GiB of rule T and applied 0.78 GiB; ~/.cache/agent-tmp held 91.3 GiB across
    592 entries, 0 of them candidates at that pass;
  * the operator's own ruling — "48 hours and 10 GB is fine, build them", the floor later ruled down to 24 h — was
    implemented in apply_scratch_cap() but the numbers were never written into config/disk_hygiene_rules.json, so
    the cap never ran. The test that pins those numbers had been xfail since 2026-11-04;
  * the monitor bands on df used% only, so the same 420 GB of usage reads 95% on this 468 GB disk and 21% on the
    2 TB disk arriving this week — silence while scratch grows.

What is pinned here:

  1. the operator's numbers are IN the rules file, not merely in code (the cap cannot run without them);
  2. a root over its cap is reclaimed OLDEST-ORPHAN-FIRST, in bytes, and a candidate that has to stay is named;
  3. the protected floor is reported and ESCALATED, never crossed: live claims, running processes and unmeasured
     trees are not evicted to reach a number;
  4. the monitor reads each root's measurement from the lane that owns it, and never reads "not measured" as ok;
  5. growth in GiB/day alerts while the root is still under its cap and the mount is quiet — the used% bands'
     blind spot, by construction.

Hermetic: synthetic rows shaped like the real producer (fingerprint.activity epoch seconds, evidence.idle_days);
no host paths are walked and nothing is deleted.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import disk_hygiene as H  # noqa: E402
from scripts import disk_usage_monitor as DM  # noqa: E402

GIB = 1024 ** 3
CONFIG = ROOT / "config" / "disk_hygiene_rules.json"


def _rules() -> dict:
    return H.load_rules(CONFIG)


def _row(path, size_gib, age_hours, *, candidate=True, rule="T", kind="agent_scratch", reasons=None):
    return {
        "path": path, "rule": rule, "kind": kind, "size_bytes": int(size_gib * GIB),
        "candidate": candidate,
        "reasons": list(reasons or ([] if candidate else ["referenced:processes"])),
        "evidence": {"idle_days": round(age_hours / 24.0, 2)},
        "fingerprint": {"activity": time.time() - age_hours * 3600.0, "kind": kind},
    }


# ── 1. the contract is in the rules file ─────────────────────────────────────────


def test_the_scratch_cap_the_operator_ruled_is_in_the_rules_file():
    """D16 (2026-11-04): floor 24 h, ceiling 10 GB. It was in code and in an xfail test; it must be in the config,
    because standing_plan only runs the cap when the numbers are there."""
    rules = _rules()
    scratch = rules["standing_apply"]["agent_scratch"]
    assert scratch["keep_younger_than_hours"] == 24
    assert scratch["max_total_gb"] == 10


def test_every_budget_root_names_an_absolute_cap_and_the_rule_that_feeds_it():
    rules = _rules()
    roots = rules["_budget_roots"]
    assert roots, "an empty budget section is how the monitor goes quiet without anyone noticing"
    names = [r["name"] for r in roots]
    assert len(names) == len(set(names))
    for root in roots:
        assert float(root["max_total_gb"]) > 0, root["name"]
        assert root["rules"], root["name"]
        assert str(root["_path"]).startswith("/"), root["name"]
    # the roots the operator named, by name, so a later edit that drops one is visible
    assert {"agent_tmp", "claude_scratch", "pip_cache", "npm_cache", "playwright_cache",
            "closed_releases"} <= set(names)


def test_every_enabled_cache_root_carries_a_byte_cap():
    """Rule C had no ceiling; enabling it without one is how a cache fills whatever drive it is given."""
    rules = _rules()
    enabled = [c for c in rules["_cache_rules"] if c.get("enabled")]
    assert enabled, "the operator asked for the caches to be under retention, not left off"
    for c in enabled:
        assert float(c["max_total_gb"]) > 0, c["path"]


def test_a_budget_root_without_a_cap_is_refused(tmp_path):
    doc = json.loads(CONFIG.read_text())
    doc["budgets"]["roots"][0].pop("max_total_gb")
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(doc))
    with pytest.raises(H.RulesError):
        H.load_rules(p, home=tmp_path)


def test_an_enabled_budget_with_no_routeable_alert_kind_is_refused(tmp_path, capsys):
    """A budget that measures a breach and has no intent kind to say it with is the old silence with extra steps."""
    doc = json.loads(CONFIG.read_text())
    doc["budgets"].pop("alert_kinds")
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(doc))
    rc = DM.main(["--dry-run", "--rules", str(p), "--home", str(tmp_path), "--state-root", str(tmp_path / "st")])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["ok"] is False and out["error"] == "budgets_alert_kinds"


def test_a_measure_only_row_is_never_reported_as_reclaimable():
    """The caches section is not a standing rule, so its rows are measured for the budget only. Reporting them as
    "planned" would promise a reclaim the standing lane cannot perform: they stay in the floor and escalate."""
    rows = [dict(_row("/c/x", 20, 40), rule="C", kind="cache_entry", budget_measure_only=True)]
    roots = [{"name": "c", "path": "/c", "_path": "/c", "rules": ["C"], "max_total_gb": 10}]
    out, report = H.apply_root_budgets(rows, roots)
    assert out[0]["candidate"] is False and "budget_measure_only" in out[0]["reasons"]
    assert report[0]["planned_bytes"] == 0
    assert report[0]["floor_bytes"] == 20 * GIB
    assert report[0]["floor_exceeds_cap"] is True and report[0]["escalate"] is True
    assert report[0]["measure_only_rows"] == 1


def test_the_budget_clock_is_slower_than_the_mount_clock_and_says_worse_at_once():
    rules = _rules()
    assert rules["budgets"]["realert_minutes"] == 240
    mon = {"realert_minutes": 60.0}
    policy = DM.budget_alert_policy(mon, rules["budgets"])
    assert policy["realert_minutes"] == 240.0
    assert mon["realert_minutes"] == 60.0, "the mount clock must not be rewritten by the budget's"
    # no configured clock: the band machine's own interval is used unchanged
    assert DM.budget_alert_policy(mon, {})["realert_minutes"] == 60.0


# ── 2. over cap: oldest orphaned first, in bytes ─────────────────────────────────


def test_a_root_over_its_cap_takes_the_oldest_orphans_first():
    rows = [
        _row("/s/new", 5, 2),
        _row("/s/oldest", 4, 100),
        _row("/s/older", 3, 50),
        _row("/s/live", 6, 200, candidate=False),     # a live claim: old, and still not ours to take
    ]
    roots = [{"name": "s", "path": "/s", "_path": "/s", "rules": ["T"], "max_total_gb": 10}]
    out, report = H.apply_root_budgets(rows, roots)
    taken = [r["path"] for r in out if r["candidate"]]
    # 18 GiB total, cap 10: 8 GiB must come off. Oldest first takes /s/oldest (4), /s/older (3), /s/new (5), and all
    # three have to go: 18-4=14 > 10, 14-3=11 > 10, 11-5=6 <= 10.
    assert sorted(taken) == ["/s/new", "/s/older", "/s/oldest"]
    assert report[0]["status"] == "cap_met"
    assert report[0]["measured_bytes"] == 18 * GIB
    assert report[0]["planned_bytes"] == 12 * GIB
    assert report[0]["floor_bytes"] == 6 * GIB
    assert report[0]["escalate"] is False


def test_only_as_many_as_the_cap_needs_are_taken_and_age_decides_not_size():
    """12 GiB against a 10 GiB cap: the single oldest entry (4 GiB) brings it to 8, so the sweep STOPS. The two
    younger ones stay — including the biggest — because the rule is oldest-first, not largest-first."""
    rows = [_row("/s/oldest", 4, 100), _row("/s/older", 3, 50), _row("/s/new", 5, 2)]
    roots = [{"name": "s", "path": "/s", "_path": "/s", "rules": ["T"], "max_total_gb": 10}]
    out, report = H.apply_root_budgets(rows, roots)
    assert [r["path"] for r in out if r["candidate"]] == ["/s/oldest"]
    kept = {r["path"]: r for r in out if "budget_over_cap_kept" in r["reasons"]}
    assert set(kept) == {"/s/older", "/s/new"}
    assert all(r["candidate"] is False for r in kept.values())
    assert report[0]["planned_bytes"] == 4 * GIB


def test_a_candidate_that_has_to_stay_is_named_not_dropped():
    rows = [_row("/s/a", 9, 100), _row("/s/b", 9, 90)]
    roots = [{"name": "s", "path": "/s", "_path": "/s", "rules": ["T"], "max_total_gb": 10}]
    out, report = H.apply_root_budgets(rows, roots)
    # 18 GiB, cap 10: the oldest (9) goes, the second (9) must stay to keep 9 <= 10 — and it is excluded BY NAME.
    kept = [r for r in out if not r["candidate"]]
    assert [r["path"] for r in kept] == ["/s/b"]
    assert "budget_over_cap_kept" in kept[0]["reasons"]


def test_a_root_under_its_cap_touches_nothing():
    rows = [_row("/s/a", 4, 100), _row("/s/b", 2, 5, candidate=False)]
    roots = [{"name": "s", "path": "/s", "_path": "/s", "rules": ["T"], "max_total_gb": 10}]
    out, report = H.apply_root_budgets(rows, roots)
    assert [(r["path"], r["candidate"], r["reasons"]) for r in out] == [
        ("/s/a", True, []), ("/s/b", False, ["referenced:processes"]),
    ]
    assert report[0]["status"] == "under_cap" and report[0]["planned_bytes"] == 0


def test_a_root_whose_cap_cannot_be_read_reclaims_nothing_and_escalates():
    """A missing cap is not "unlimited" and not zero: it is a number the sweep does not have. Reclaiming toward
    an unreadable cap would either evict the whole root (cap 0) or nothing at all while reporting "under cap"."""
    rows = [_row("/s/a", 9, 100), _row("/s/b", 9, 90)]
    roots = [{"name": "s", "path": "/s", "_path": "/s", "rules": ["T"]}]  # no max_total_gb at all
    out, report = H.apply_root_budgets(rows, roots)
    assert all(r["candidate"] for r in out)                 # untouched: nothing is taken on a guess
    e = report[0]
    assert e["status"] == "cap_unknown" and e["cap_bytes"] is None and e["over_by_bytes"] is None
    assert e["planned_bytes"] == 0 and e["escalate"] is True


def test_an_undated_row_is_never_taken_before_a_dated_one_and_is_counted():
    """The budget's order is age; a row with no age has no place in that order. It is the LAST resort, and the
    entry says how much of the root it could not date, so "oldest first" is never claimed over a blind spot."""
    old = _row("/s/dated_old", 4, 100)
    undated = _row("/s/undated", 4, 1)
    undated["fingerprint"] = {}                 # no activity, no mtime
    undated["evidence"] = {}                    # no idle_days either
    rows = [undated, old]
    roots = [{"name": "s", "path": "/s", "_path": "/s", "rules": ["T"], "max_total_gb": 5}]
    out, report = H.apply_root_budgets(rows, roots)
    assert [r["path"] for r in out if r["candidate"]] == ["/s/dated_old"]   # 8 -> 4 <= 5 after the dated row only
    e = report[0]
    assert e["planned_bytes"] == 4 * GIB
    assert e["undated_rows"] == 1 and e["undated_bytes"] == 4 * GIB
    assert "budget_over_cap_kept" in {r["path"]: r for r in out}["/s/undated"]["reasons"]


def test_a_cache_entry_is_dated_from_its_newest_mtime():
    """Rule C emits fingerprint.mtime, not activity: before 2026-11-09 the budget saw every cache entry as undatable,
    so "oldest first" degraded to "largest first" and the caches' max_item_age_days counted nothing."""
    old = {"path": "/c/ancient", "rule": "C", "kind": "cache_entry", "size_bytes": GIB, "candidate": True,
           "reasons": [], "fingerprint": {"mtime": time.time() - 40 * 86400.0, "kind": "cache_entry"},
           "evidence": {"cache_root": "/c", "newest_mtime": time.time() - 40 * 86400.0}}
    fresh = {"path": "/c/fresh", "rule": "C", "kind": "cache_entry", "size_bytes": 2 * GIB, "candidate": False,
             "reasons": ["recent_activity"], "fingerprint": {"mtime": time.time() - 3600.0, "kind": "cache_entry"},
             "evidence": {"cache_root": "/c", "newest_mtime": time.time() - 3600.0}}
    roots = [{"name": "c", "path": "/c", "_path": "/c", "rules": ["C"], "max_total_gb": 2,
              "max_item_age_days": 30}]
    out, report = H.apply_root_budgets([old, fresh], roots)
    assert [r["path"] for r in out if r["candidate"]] == ["/c/ancient"]
    # 2 GiB taken leaves 2 GiB against a 2 GiB cap: met exactly, and nothing else touched
    assert report[0]["status"] == "cap_met" and report[0]["planned_bytes"] == GIB
    # the held fresh entry is younger than 30 days, so the age raise stays empty
    assert report[0]["over_max_age"]["count"] == 0


def test_a_held_cache_entry_past_its_max_age_is_measured_even_though_it_is_held():
    held = {"path": "/c/held", "rule": "C", "kind": "cache_entry", "size_bytes": GIB, "candidate": False,
            "reasons": ["never_touch_name:keep"],
            "fingerprint": {"mtime": time.time() - 60 * 86400.0, "kind": "cache_entry"},
            "evidence": {"cache_root": "/c", "newest_mtime": time.time() - 60 * 86400.0}}
    roots = [{"name": "c", "path": "/c", "_path": "/c", "rules": ["C"], "max_total_gb": 4,
              "max_item_age_days": 30}]
    _out, report = H.apply_root_budgets([held], roots)
    assert report[0]["over_max_age"]["count"] == 1
    assert report[0]["over_max_age"]["reasons"] == ["never_touch_name"]


# ── 3. the floor is reported and escalated, never crossed ────────────────────────


def test_the_protected_floor_alone_over_the_cap_escalates():
    """91 GiB held by live sessions against a 10 GiB cap is THIS case: the number cannot be met by evicting eligible
    work, so the pass says so and hands the decision to a human."""
    rows = [
        _row("/s/live-1", 20, 300, candidate=False),
        _row("/s/live-2", 15, 150, candidate=False),
        _row("/s/orphan", 2, 100),
    ]
    roots = [{"name": "s", "path": "/s", "_path": "/s", "rules": ["T"], "max_total_gb": 10}]
    out, report = H.apply_root_budgets(rows, roots)
    assert [r["path"] for r in out if r["candidate"]] == ["/s/orphan"]
    entry = report[0]
    assert entry["floor_bytes"] == 35 * GIB
    assert entry["floor_exceeds_cap"] is True
    assert entry["escalate"] is True
    assert entry["status"] == "over_cap_after_reclaim"
    # the held rows are untouched: no reason added, still not candidates, never taken
    held = [r for r in out if not r["candidate"] and r["path"].startswith("/s/live-")]
    assert all(r["reasons"] == ["referenced:processes"] for r in held)


def test_held_entries_older_than_the_max_age_are_measured_and_raised():
    rows = [_row("/s/live", 12, 24 * 40, candidate=False, reasons=["referenced:processes"])]
    roots = [{"name": "s", "path": "/s", "_path": "/s", "rules": ["T"], "max_total_gb": 10,
              "max_item_age_days": 30}]
    _out, report = H.apply_root_budgets(rows, roots)
    age = report[0]["over_max_age"]
    assert age["count"] == 1 and age["bytes"] == 12 * GIB
    assert age["reasons"] == ["referenced"]


# ── 4. the monitor reads the lanes' own measurements, and never reads unknown as ok ──


def _root(name, path, cap, rules):
    return {"name": name, "path": path, "_path": path, "rules": rules, "max_total_gb": cap}


def test_each_root_is_measured_once_by_the_lane_that_owns_it():
    rules = {"_budget_roots": [_root("agent_tmp", "/h/.cache/agent-tmp", 10, ["T"]),
                               _root("claude_scratch", "/tmp/claude-1000", 10, ["tmp"])]}
    lane = [{"root": "agent_tmp", "status": "over_cap", "measured_bytes": 40 * GIB, "floor_bytes": 39 * GIB,
             "floor_exceeds_cap": True}]
    tmp = [{"path": "/tmp/claude-1000/proj/sess/a", "size_bytes": 4 * GIB, "candidate": False},
           {"path": "/tmp/claude-1000/proj/sess/b", "size_bytes": 2 * GIB, "candidate": True}]
    rows = DM.budget_measurements(rules, lane, tmp)
    by = {r["root"]: r for r in rows}
    assert by["agent_tmp"]["source"] == "lane_manifest" and by["agent_tmp"]["measured_bytes"] == 40 * GIB
    assert by["agent_tmp"]["floor_exceeds_cap"] is True
    assert by["claude_scratch"]["source"] == "tmp_manifest" and by["claude_scratch"]["measured_bytes"] == 6 * GIB
    assert by["claude_scratch"]["over_bytes"] == 0, "6 GiB against a 10 GiB cap is under it"


def test_a_root_no_lane_measured_is_unmeasured_never_zero():
    rules = {"_budget_roots": [_root("agent_tmp", "/h/.cache/agent-tmp", 10, ["T"])]}
    rows = DM.budget_measurements(rules, None, None)
    assert rows[0]["status"] == "unmeasured"
    assert rows[0]["measured_bytes"] is None and rows[0]["over_bytes"] is None


def test_an_unmeasured_root_has_no_band_so_it_cannot_read_as_ok():
    growth = {"window_days": 3, "min_samples": 3, "max_gb_per_day": 5.0}
    now = datetime.now(timezone.utc)
    rows = [{"root": "r", "status": "unmeasured", "measured_bytes": None, "over_bytes": None}]
    finding = DM.budget_findings(rows, {}, now, growth)[0]
    assert finding["band"] is None and finding["why"] == "unmeasured"


def test_a_root_without_a_readable_cap_is_cap_unknown_and_is_never_ok():
    """The rules file is the contract, but the monitor must not turn an unreadable cap into a green row: with no
    cap there is nothing to be "under", and `measured_gb of 0 GiB` would read as a breach against nothing."""
    rules = {"_budget_roots": [{"name": "r", "path": "/r", "_path": "/r", "rules": ["T"]}]}
    rows = DM.budget_measurements(rules, [{"root": "r", "status": "over_cap", "measured_bytes": 4 * GIB}], None)
    assert rows[0]["status"] == "cap_unknown"
    assert rows[0]["cap_bytes"] is None and rows[0]["cap_gb"] is None and rows[0]["over_bytes"] is None
    finding = DM.budget_findings(rows, {}, datetime.now(timezone.utc), {"window_days": 3, "min_samples": 3})[0]
    assert finding["band"] is None and finding["why"] == "cap_unknown"


def test_a_growth_rate_with_no_configured_ceiling_is_not_banded():
    """A rate with no ceiling is measurable but not actionable. It must not be silently warned about, and it must
    not read as a clean ok either: the row says the alarm is off by configuration."""
    now = datetime.now(timezone.utc)
    growth = {"window_days": 3, "min_samples": 3}      # no max_gb_per_day
    row = {"root": "r", "status": "under_cap", "measured_bytes": 28 * GIB, "over_bytes": 0, "cap_bytes": 40 * GIB}
    finding = DM.budget_findings([row], {"r": _samples(now, 8.0)}, now, growth)[0]
    assert finding["band"] == "ok" and finding["why"] == "growth_unconfigured"
    assert finding["growth_gb_per_day"] is not None


# ── 5. growth is a rate, independent of the used% bands ─────────────────────────


def _samples(now, gb_per_day, days=3, start_gb=4.0, step_hours=6):
    series = []
    n = int(days * 24 / step_hours)
    for i in range(n + 1):
        ts = (now - timedelta(hours=step_hours * (n - i))).timestamp()
        series.append([ts, int((start_gb + gb_per_day * (i * step_hours / 24.0)) * GIB)])
    return series


def test_growth_alerts_while_the_root_is_still_under_its_cap():
    now = datetime.now(timezone.utc)
    growth = {"window_days": 3, "min_samples": 3, "max_gb_per_day": 5.0}
    series = _samples(now, 8.0)                      # 8 GiB/day, ending at 28 GiB
    row = {"root": "r", "status": "under_cap", "measured_bytes": 28 * GIB, "over_bytes": 0,
           "cap_bytes": 40 * GIB}
    finding = DM.budget_findings([row], {"r": series}, now, growth)[0]
    assert finding["band"] == "warn" and finding["why"] == "growth_rate"
    assert 7.5 <= finding["growth_gb_per_day"] <= 8.5


def test_a_quiet_root_is_ok_and_needs_no_alert():
    now = datetime.now(timezone.utc)
    growth = {"window_days": 3, "min_samples": 3, "max_gb_per_day": 5.0}
    row = {"root": "r", "status": "under_cap", "measured_bytes": 4 * GIB, "over_bytes": 0, "cap_bytes": 40 * GIB}
    finding = DM.budget_findings([row], {"r": _samples(now, 0.0)}, now, growth)[0]
    assert finding["band"] == "ok" and finding["why"] is None
    assert finding["growth_gb_per_day"] <= 5.0


def test_growth_is_not_guessed_from_too_few_samples():
    now = datetime.now(timezone.utc)
    growth = {"window_days": 3, "min_samples": 3, "max_gb_per_day": 5.0}
    two = [[now.timestamp() - 3600, GIB], [now.timestamp(), 9 * GIB]]
    assert DM.growth_gb_per_day(two, now, growth) is None


def test_samples_are_pruned_to_the_window_and_a_hard_cap():
    now = datetime.now(timezone.utc)
    growth = {"window_days": 1, "min_samples": 3, "max_samples_per_root": 4}
    old = [[(now - timedelta(days=5)).timestamp(), 100 * GIB]]
    rows = [{"root": "r", "measured_bytes": GIB}]
    samples = DM.budget_samples({"r": old}, rows, now, growth)
    assert len(samples["r"]) == 1, "a five-day-old sample is outside a one-day window"
    assert samples["r"][0][1] == GIB


def test_the_alert_text_names_the_cap_the_measurement_and_the_floor():
    finding = {"root": "agent_tmp", "path": "/h/.cache/agent-tmp", "why": "over_cap",
               "cap_gb": 10.0, "measured_gb": 91.3, "over_bytes": int(81.3 * GIB),
               "floor_exceeds_cap": True, "floor_bytes": int(89.0 * GIB),
               "over_max_age": {"count": 3, "bytes": int(9.0 * GIB), "max_item_age_days": 30,
                                "reasons": ["referenced"]}}
    subject, text = DM.budget_intent_text(finding)
    assert "91.3 GiB of 10.0 GiB" in subject
    assert "81.30 GiB" in text and "89.0 GiB" in text
    assert "referenced" in text, "the operator needs to know WHAT holds the rest"


def test_the_alert_text_never_prints_a_missing_number_as_zero():
    """An unreadable over-by is a number the alert does not have. Printing "0.00 GiB must come off" beside a cap is
    the same failure as a green band on an unmeasured root: the reader cannot tell "nothing" from "unknown"."""
    finding = {"root": "r", "path": "/r", "why": "over_cap", "cap_gb": 10.0, "measured_gb": 12.0,
               "over_bytes": None, "floor_exceeds_cap": False,
               "over_max_age": {"count": 1, "bytes": None, "max_item_age_days": 30, "reasons": ["referenced"]}}
    _, text = DM.budget_intent_text(finding)
    assert "0.00 GiB" not in text and " 0 GiB" not in text
    assert text.count("an unknown number of GiB") == 2
