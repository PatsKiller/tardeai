"""ANCHOR: JOBS_NOT_MEASURED_GROUPS_LQ246_20261107. LQ-20261107-246 — "191 jobs not measured" was one flat
number that named no cause.

Measured live 2026-11-07T20:32Z (the projection with this change; ``not_measured: 191`` of 717 registry
lanes) — the split, which sums to the flat count:

* **34 never scheduled** — a registered lane no scheduler installs; "schedule not measured" would blame this
  reader for a schedule that does not exist;
* **123 schedule this reader cannot measure** — mostly host ``systemd`` timers, which
  ``cron_outage_watchdog.schedules`` cannot turn into a schedule;
* **29 no run source** — no ledger row, wrapper event or proven log at all;
* **5 dry run only** — lanes that execute every few minutes in n8n shadow, invisible before this change
  because ``build()`` dropped every non-live run, so the page could not tell "runs, in shadow" from
  "nothing records this";
* **0 run recorded, no success** — the live-but-uncounted case, kept because it is the one an operator must
  act on.

What this pins:

1. an unmeasured row says **which** evidence is missing (``evidence_gap``), and a lane seen only in a
   dry run is named as such — while never becoming a success (a dry run does not prove work);
2. ``summary.not_measured_groups`` splits the total by why, and the groups sum to it;
3. the flat ``not_measured`` / ``unknown`` / ``gap_reasons`` contract is untouched — platform_health and
   the LQ-219 last-good body keep reading what they read before.

Synthetic lanes and receipts only; no registry, ledger, network or clock reads.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib import jobs_health as J

#: A weekday inside the fixture cron's 9-16 ET window (Mon 2026-11-09 10:30 ET): a Saturday clock makes every
#: row OUTSIDE_WINDOW, which is a measured outcome and would hide the unmeasured paths under test.
NOW = datetime(2026, 11, 9, 15, 37, tzinfo=timezone.utc)


def lane(name, kind="cron", expression="*/15 9-16 * * 1-5", state="ACTIVE"):
    return {"lane_id": name, "state": state, "expected_cadence_hours": 1 / 4,
            "scheduler": {"kind": kind, "expression": expression},
            "output_signal": {"kind": "file_mtime", "path": f"logs/{name}.log"}}


def run(name, at, *, mode="live", state="RUN_DONE", exit_code=0, verdict="produced"):
    base = {"run_id": f"{name}-{mode}-run", "lane_id": name, "mode": mode, "state": state,
            "exit_code": exit_code, "finished_at": at.isoformat(), "requested_at": at.isoformat()}
    if mode == "dry_run":
        return {**base, "receipt": {**base, "schema": "RunReceipt@v3", "mode": "dry_run",
                                    "output_verdict": {"verdict": verdict}}}
    return {**base, "receipt": {**base, "schema": "RunReceipt@v3", "output_verdict": {"verdict": verdict}}}


def build(lanes, runs=()):
    snapshot = {"events": [], "successes": {}, "collection_gaps": []}
    return J.build({"lanes": lanes}, snapshot, list(runs), {}, now=NOW, trading_day=lambda d: d.weekday() < 5)


def row(report, lane_id):
    return next(r for r in report["rows"] if r["lane_id"] == lane_id)


# ── each unmeasured row names what is missing ────────────────────────────────────────────────────────────────

def test_a_lane_nothing_records_is_grouped_as_no_run_source():
    report = build([lane("quiet-cron")])
    r = row(report, "quiet-cron")
    assert r["result"] == "unknown"
    assert r["evidence_gap"] == "no_run_source"
    assert "ledger" in r["cause"].lower() or "wrapper" in r["cause"].lower()


def test_a_lane_seen_only_in_a_dry_run_is_named_as_such_and_never_becomes_a_success():
    """The live shape: cio-ask-research / momentum-lifecycle-monitor run every few minutes in n8n shadow."""
    report = build([lane("shadow-only")], runs=[run("shadow-only", NOW - timedelta(minutes=5), mode="dry_run")])
    r = row(report, "shadow-only")
    assert r["result"] == "unknown", "a dry run is not proof of work"
    assert r["evidence_gap"] == "dry_run_only"
    assert "dry run" in r["cause"]
    assert (NOW - timedelta(minutes=5)).strftime("%Y-%m-%d") in r["cause"], "the row says WHEN it last ran"
    assert report["summary"]["succeeded"] == 0


def test_a_registered_lane_with_no_installed_unit_is_grouped_as_never_scheduled():
    """Blaming the reader for a schedule that does not exist hides a lane nobody wired up (or nobody retired)."""
    report = build([lane("ghost", state="NEVER_SCHEDULED")])
    r = row(report, "ghost")
    assert r["result"] == "unknown"
    assert r["evidence_gap"] == "never_scheduled"
    assert "never scheduled" in r["cause"].lower()


def test_a_systemd_timer_the_reader_cannot_schedule_is_grouped_as_a_schedule_gap():
    report = build([lane("host-timer", kind="systemd", expression="tradeai-example.timer")])
    r = row(report, "host-timer")
    assert r["result"] == "unknown"
    assert r["evidence_gap"] == "schedule_not_measured"


def test_a_live_run_that_is_not_a_success_is_grouped_as_a_run_without_success():
    report = build([lane("unproven")], runs=[run("unproven", NOW - timedelta(hours=2), exit_code=2)])
    r = row(report, "unproven")
    assert r["result"] == "unknown"
    assert r["evidence_gap"] == "no_success_measured"


# ── the summary splits the total, and the split adds up to it ───────────────────────────────────────────────

def test_groups_sum_to_the_flat_not_measured_count():
    report = build([lane("quiet-cron"), lane("shadow-only"), lane("unproven"),
                    lane("host-timer", kind="systemd", expression="tradeai-example.timer")],
                   runs=[run("shadow-only", NOW - timedelta(minutes=5), mode="dry_run"),
                         run("unproven", NOW - timedelta(hours=2), exit_code=2)])
    summary = report["summary"]
    groups = summary["not_measured_groups"]
    assert summary["not_measured"] == summary["unknown"] == 4
    assert sum(groups.values()) == 4, f"the split must add up to the flat count: {groups}"
    assert groups["dry_run_only"] == 1 and groups["no_run_source"] == 1
    assert groups["schedule_not_measured"] == 1 and groups["no_success_measured"] == 1


def test_every_unmeasured_row_carries_a_group():
    report = build([lane("a"), lane("b", kind="systemd", expression="x.timer"), lane("c", state="NEVER_SCHEDULED")])
    unmeasured = [r for r in report["rows"] if r["result"] == "unknown"]
    assert unmeasured and all(r["evidence_gap"] in dict(J.NOT_MEASURED_GROUPS) for r in unmeasured)
    assert row(report, "c")["evidence_gap"] == "never_scheduled"


# ── the contract existing readers depend on is unchanged ────────────────────────────────────────────────────

def test_the_flat_count_and_gap_reasons_are_untouched():
    """platform_health reads `not_measured` and `gap_reasons.missed`; LQ-219 stores this body as-is."""
    summary = build([lane("quiet-cron")])["summary"]
    assert summary["not_measured"] == 1 and summary["unknown"] == 1
    assert set(summary["gap_reasons"]) == {"missed", "not_measured"}
    assert "1 job not measured" in summary["gap_reasons"]["missed"]
    assert summary["missed_measured"] is False


def test_a_measured_success_is_still_a_success_with_no_gap():
    report = build([lane("healthy")], runs=[run("healthy", NOW - timedelta(minutes=5))])
    r = row(report, "healthy")
    assert r["result"] == "succeeded"
    assert r["evidence_gap"] is None
    assert report["summary"]["not_measured"] == 0
    assert report["summary"]["not_measured_groups"] == {
        "never_scheduled": 0, "schedule_not_measured": 0, "no_run_source": 0,
        "dry_run_only": 0, "no_success_measured": 0}
