"""ANCHOR: LANE_DRY_RUN_ONLY_20261107 — a shadow lane is not "missed", it is dry run only.

LQ-20261107-245. `prospectus-build` is an n8n-native lane at shadow: its registry row carries
`dispatch.mode: "dry_run"` and `config/n8n_run_allowlist.json` has `live_arg: null`, so every fire runs
`scripts/prospectus_window.py --dry-run`, which writes no receipt by design. The lane's last live
receipt is from 2026-10-28, so `cron_outage_watchdog.evaluate()` graded it `MISSED_RUNS`, the watcher
opened a P1 "cron/lane outage: prospectus-build missed its schedule", and the incidents page has said
"missed" for ten days about a lane that is behaving exactly as configured.

The rules pinned here:

  1. a lane whose row declares `dispatch.mode: dry_run` is `DRY_RUN_ONLY` — visible in `rows`, named in
     `dry_run_only_lane_ids`, never in `missed_lane_ids`, and it never raises the alert;
  2. the same stale receipt on a live lane is still `MISSED_RUNS` with an alert — the rule still bites;
  3. the incident watcher gives a shadow lane an informational P3 "dry run only" finding on its own
     fingerprint, so the page says what is true and the old P1 auto-resolves when the condition clears;
  4. a genuinely missed live lane keeps its P1 "missed its schedule" finding;
  5. the shipped registry row for `prospectus-build` is classified by these rules, not by a name list.

Hermetic: in-memory registry rows, a temporary state root, no DB, no network, no scheduler.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import incident_watchers as W  # noqa: E402
from scripts.lib.cron_outage_watchdog import evaluate  # noqa: E402

NOW = datetime.fromisoformat("2026-11-07T20:30:00+00:00")
STALE = "2026-10-28T22:44:02Z"  # the lane's last live receipt: ten days behind NOW


def lane(**changes):
    """A dispatcher row for an n8n-native lane, live unless a test says otherwise."""
    row = {"lane_id": "shadow-lane", "state": "ACTIVE", "expected_cadence_hours": 0.25,
           "scheduler": {"kind": "n8n", "expression": "dispatcher", "stage": "canary",
                         "cadence": "*/15 * * * *", "match": "scripts/shadow_lane.py"},
           "dispatch": {"mode": "live", "cron": ["*/15 * * * *"], "tz": "America/New_York",
                        "class": "report", "priority": 5, "retry_policy": "transient-2"},
           "output_signal": {"kind": "json_key", "path": "data/runtime/shadow-lane_last.json", "key": "ok_at"}}
    row.update(changes)
    return row


def shadow(row):
    row = json.loads(json.dumps(row))
    row["scheduler"]["stage"] = "shadow"
    row["dispatch"]["mode"] = "dry_run"
    return row


def assess(row):
    """One lane, one stale validated receipt, nothing else observed."""
    return evaluate({"lanes": [row]}, [], {"shadow-lane": [{"at": STALE, "validated_success": True}]}, now=NOW)


# ── 1. the rule ───────────────────────────────────────────────────────────────────────────────────

def test_a_shadow_lane_with_a_stale_receipt_is_dry_run_only_not_missed():
    result = assess(shadow(lane()))

    row = result["rows"][0]
    assert row["status"] == "DRY_RUN_ONLY", row
    assert row["missed_fires"] == 0
    assert "dry_run" in (row["reason"] or "")
    assert result["dry_run_only_lane_ids"] == ["shadow-lane"]
    assert result["missed_lane_ids"] == []
    assert result["alert_required"] is False
    assert result["status"] != "CRIT"


def test_the_grade_the_live_path_would_have_given_is_kept_on_the_row():
    result = assess(shadow(lane()))

    assert result["rows"][0]["missed_fires_if_live"] >= 2
    assert result["dry_run_only_missed_lane_ids"] == ["shadow-lane"]


def test_a_shadow_lane_is_still_listed_so_it_cannot_disappear():
    result = assess(shadow(lane()))
    assert [r["lane_id"] for r in result["rows"]] == ["shadow-lane"]


def test_the_stale_receipt_is_still_reported_so_the_reader_can_see_how_old_it_is():
    row = assess(shadow(lane()))["rows"][0]
    assert row["last_success_at"] == "2026-10-28T22:44:02Z"


# ── 2. the control: a live lane keeps the real rule ───────────────────────────────────────────────

def test_a_live_lane_with_the_same_stale_receipt_is_still_missed():
    result = assess(lane())

    assert result["rows"][0]["status"] == "MISSED_RUNS"
    assert result["missed_lane_ids"] == ["shadow-lane"]
    assert result["alert_required"] is True and result["status"] == "CRIT"


def test_a_shadow_lane_with_no_receipt_at_all_is_also_dry_run_only():
    result = evaluate({"lanes": [shadow(lane())]}, [], {}, now=NOW)

    assert result["rows"][0]["status"] == "DRY_RUN_ONLY"
    assert result["coverage_gap_lane_ids"] == []
    assert result["dry_run_only_lane_ids"] == ["shadow-lane"]


def test_a_shadow_lane_that_is_still_succeeding_keeps_its_ok_grade():
    """A wrapper completion is real execution: a row that is actually working is not "dry run only"."""
    from datetime import timedelta
    recent = (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = [{"event_type": "completed", "exit_code": 0, "mode": "business", "component": "shadow_lane",
               "ts": recent}]

    result = evaluate({"lanes": [shadow(lane(watchdog_wrapper_component="shadow_lane"))]}, events, {}, now=NOW)

    assert result["rows"][0]["status"] == "OK"
    assert result["dry_run_only_lane_ids"] == []


# ── 3. the watcher tells the page the truthful sentence ───────────────────────────────────────────

def _ctx(tmp_path, *, missed=(), shadowed=()):
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    rows = [{"lane_id": lane, "status": "DRY_RUN_ONLY", "last_success_at": STALE} for lane in shadowed]
    doc = {"observed_at": "2026-11-07T20:25:00Z", "missed_lane_ids": list(missed),
           "dry_run_only_missed_lane_ids": list(shadowed), "rows": rows,
           "coverage_gap_lane_ids": [], "status": "CRIT" if missed else "OK"}
    (tmp_path / "data" / "runtime" / "cron_outage_watchdog_latest.json").write_text(json.dumps(doc))
    return W.Ctx(state_root=tmp_path, now=NOW, cfg={}, state={},
                 gh=lambda argv: (1, ""), git=lambda sub, argv: (1, ""), llm_queue=lambda: None)


def _watch(tmp_path, **kw):
    c = {"cron_watchdog_rel": "data/runtime/cron_outage_watchdog_latest.json",
         "research_rel": "data/runtime/research_lane_health.json", "stale_minutes": 120}
    return W.w_lane_health(_ctx(tmp_path, **kw), c)


def test_the_watcher_says_dry_run_only_instead_of_missed(tmp_path):
    res = _watch(tmp_path, shadowed=["shadow-lane"])

    assert res.gap is None
    [f] = res.findings
    assert f.title == "lane shadow-lane is dry run only (shadow) — no live result by design"
    assert f.severity == "P3"
    assert f.fingerprint == W.L.fingerprint_of("lane_dry_run_only", "shadow-lane")
    assert f.fingerprint != W.L.fingerprint_of("cron_outage", "shadow-lane")


def test_a_genuinely_missed_live_lane_keeps_its_p1_outage(tmp_path):
    res = _watch(tmp_path, missed=["live-lane"])

    [f] = res.findings
    assert f.severity == "P1"
    assert f.title == "cron/lane outage: live-lane missed its schedule"
    assert f.fingerprint == W.L.fingerprint_of("cron_outage", "live-lane")


def test_both_kinds_in_one_document_produce_two_distinct_findings(tmp_path):
    res = _watch(tmp_path, missed=["live-lane"], shadowed=["shadow-lane"])

    by_sev = {f.severity: f.title for f in res.findings}
    assert by_sev["P1"].startswith("cron/lane outage:")
    assert by_sev["P3"].endswith("dry run only (shadow) — no live result by design")


# ── 4. the shipped row, not a name list ──────────────────────────────────────────────────────────

def test_the_shipped_prospectus_build_row_is_classified_dry_run_only():
    registry = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in registry["lanes"] if r["lane_id"] == "prospectus-build")
    assert row["dispatch"]["mode"] == "dry_run", "the row changed shape; re-read it before trusting this pin"

    result = evaluate({"lanes": [row]}, [], {"prospectus-build": [{"at": STALE, "validated_success": True}]},
                      now=NOW)

    assert result["rows"][0]["status"] == "DRY_RUN_ONLY"
    assert "prospectus-build" in result["dry_run_only_lane_ids"]
    assert "prospectus-build" not in result["missed_lane_ids"]
