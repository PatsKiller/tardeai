"""Counting logic of scripts/report_n8n_cutover_outcomes.py (operator 2026-10-16: one packet that proves OUTCOMES).

Fixture-only: no crontab, no ledger, no DB, no gh. Pins the definitions the packet prints: disposition rows are not
jobs; a lane has exactly one status; PARALLEL needs a live n8n run (else LIVE_LISTED_IDLE); MIGRATED_PROVEN needs a
tagged commented cron line AND a live RUN_DONE; exit 0 without an output verdict is unverified, not useful; a REQUESTED
/ shadow remediation is not a heal; a recovery needs the output condition; unknown provenance stays UNKNOWN; an
unwrapped active cron line is not effect-fenced; the live-lanes env parser returns lane names and nothing else.
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import report_n8n_cutover_outcomes as R  # noqa: E402

SINCE = datetime(2026, 10, 15, 4, 0, tzinfo=timezone.utc)
UNTIL = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)


def _r(lane, mode="live", state="RUN_DONE", verdict=None, at="2026-10-16T14:00:00+00:00", dur=1.0, **kw):
    d = {"lane_id": lane, "mode": mode, "state": state, "started_at": at, "duration_s": dur,
         "lock_skipped": state == "RUN_SKIPPED_LOCK", "run_id": kw.pop("run_id", f"d:{lane}:{mode}:{at}")}
    if verdict is not None:
        d["output_verdict"] = {"verdict": verdict}
    d.update(kw)
    return d


# ── live-lane env: names only ───────────────────────────────────────────────────────────────────────────────────
def test_live_lanes_parser_returns_only_lane_names():
    text = (
        "SOME_SECRET_TOKEN=abc123\n"
        "# TRADEAI_N8N_RELAY_LIVE_LANES=commented-out\n"
        'export TRADEAI_N8N_RELAY_LIVE_LANES="lane-a lane-b,lane-c lane-a"\n'
        "OTHER=lane-z\n"
    )
    assert R.parse_live_lanes(text) == ["lane-a", "lane-b", "lane-c"]
    assert R.parse_live_lanes("PASSWORD=x\n") == []


# ── disposition rows vs lanes ───────────────────────────────────────────────────────────────────────────────────
def test_disposition_rows_are_not_jobs():
    rows = [{"lane_id": "fam-runner", "disposition": "MIGRATE_N8N", "source": "crontab"} for _ in range(3)]
    rows += [{"lane_id": "x", "disposition": "MIGRATE_N8N", "source": "crontab"},
             {"lane_id": "y", "disposition": "RETIRE", "source": "registry_systemd"}]
    t = R.disposition_totals(rows)
    assert t["rows"] == 5 and t["by_disposition"]["MIGRATE_N8N"] == 4
    assert t["unique_lanes_by_disposition"]["MIGRATE_N8N"] == 2
    assert t["unique_lanes"] == 3


# ── commented crontab tags ──────────────────────────────────────────────────────────────────────────────────────
def test_commented_line_classification():
    c = R.classify_commented_line("# RETIRED 2026-10-16 n8n-cutover hermes-news-bridge 40 6 * * * cd $PROJ && x.py")
    assert c["kind"] == "N8N_CUTOVER" and c["lane_id"] == "hermes-news-bridge" and c["date"] == "2026-10-16"
    c = R.classify_commented_line("# N8N-ONLY TEST 2026-10-16 (operator) # 25 6-15 * * 1-5 cd $PROJ && y.py")
    assert c["kind"] == "N8N_ONLY_TEST" and c["lane_id"] == ""
    assert R.classify_commented_line("# RETIRED 2026-10-15 c1-manifest premarket 20 7 * * 1-5 z")["kind"] == "CONSOLIDATED"
    assert R.classify_commented_line("# RETIRED 2026-10-15 retire-ld-w1 0 8 * * 0 w")["kind"] == "RETIRED_OTHER"
    assert R.classify_commented_line("0 8 * * * active.py") is None
    assert R.classify_commented_line("# just a note") is None


def test_parse_cron_attributes_active_and_commented_lines():
    text = "\n".join([
        "PROJ=/x",
        "0 1 * * * cd $PROJ && a.py",
        "# RETIRED 2026-10-16 n8n-cutover lane-b 0 2 * * * b.py",
        "# N8N-ONLY TEST 2026-10-16 (op) # 0 3 * * * c.py",
        "#0 4 * * * d.py",
    ])

    def best(line, schedule="", tag=""):
        for name in ("a", "b", "c", "d"):
            if f"{name}.py" in line:
                return f"lane-{name}"
        return ""

    cron = R.parse_cron(text, best)
    assert [a["lane_id"] for a in cron["active"]] == ["lane-a"]
    assert {(c["kind"], c["lane_id"]) for c in cron["commented"]} == {("N8N_CUTOVER", "lane-b"), ("N8N_ONLY_TEST", "lane-c")}


# ── receipts ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_exit_zero_without_verdict_is_not_useful():
    assert R.receipt_class(_r("a", verdict="produced")) == "useful"
    assert R.receipt_class(_r("a", verdict="empty_allowed")) == "empty"
    for v in (None, "no_rule", "declared_not_enforced"):
        assert R.receipt_class(_r("a", verdict=v)) == "unverified_ok"
    assert R.receipt_class(_r("a", verdict="empty_violation")) == "failure"
    assert R.receipt_class(_r("a", state="RUN_TIMEOUT")) == "failure"
    assert R.receipt_class(_r("a", state="RUN_SKIPPED_LOCK")) == "lock_skip"
    assert R.receipt_class(_r("a", mode="dry_run")) == "dry_done"


def test_count_outcomes_window_and_worker_seconds():
    rs = [
        _r("a", verdict="produced", dur=2.5), _r("a", verdict="empty_allowed", dur=1.0), _r("a", dur=1.0),
        _r("a", state="RUN_FAILED", dur=4.0), _r("a", state="RUN_SKIPPED_LOCK", dur=0.0),
        _r("a", mode="dry_run", dur=0.5), _r("a", verdict="produced", at="2026-10-14T12:00:00+00:00"),
    ]
    o = R.count_outcomes(rs, SINCE, UNTIL)["a"]
    assert (o["live_runs"], o["dry_runs"]) == (5, 1)
    assert (o["useful_live_output"], o["verified_empty"], o["unverified_ok"], o["failures"], o["lock_skips"]) == (1, 1, 1, 1, 1)
    assert o["live_worker_s"] == 8.5 and o["dry_worker_s"] == 0.5


def test_refusals_and_ambiguous_effects():
    relay = [{"state": "REFUSED", "lane_id": "a", "reason": "run_slot_not_due", "at": "2026-10-16T10:00:00Z"},
             {"state": "REFUSED", "lane_id": "a", "reason": "run_slot_not_due", "at": "2026-10-01T10:00:00Z"},
             {"state": "REQUESTED", "lane_id": "a", "at": "2026-10-16T10:00:00Z"}]
    assert R.count_refusals(relay, SINCE, UNTIL) == {"a": Counter({"run_slot_not_due": 1})}
    claims = [{"process": "a", "state": s, "claimed_at": "2026-10-16T10:00:00+00:00"} for s in ("DONE", "UNKNOWN", "CLAIMED")]
    c = R.count_effect_claims(claims, SINCE, UNTIL)["a"]
    assert c["CLAIMED"] + c["UNKNOWN"] == 2


# ── one status per lane ─────────────────────────────────────────────────────────────────────────────────────────
def _states(**over):
    reg = {
        "migrated": {"scheduler": {"kind": "cron"}, "state": "ACTIVE"},
        "tag-no-run": {"scheduler": {"kind": "cron"}, "state": "ACTIVE"},
        "parallel": {"scheduler": {"kind": "cron"}, "state": "ACTIVE"},
        "idle": {"scheduler": {"kind": "cron"}, "state": "ACTIVE"},
        "cronly": {"scheduler": {"kind": "cron"}, "state": "ACTIVE"},
        "daemon": {"scheduler": {"kind": "cron"}, "state": "ACTIVE"},
        "timer": {"scheduler": {"kind": "systemd"}, "state": "ACTIVE"},
        "held": {"scheduler": {"kind": "cron"}, "state": "PAUSED"},
        "folded": {"scheduler": {"kind": "cron"}, "state": "ACTIVE"},
        "gone": {"scheduler": {"kind": "cron"}, "state": "RETIRED"},
        "native": {"scheduler": {"kind": "n8n"}, "state": "ACTIVE"},
    }
    cron = {
        "active": [{"line_no": 10, "lane_id": "parallel"}, {"line_no": 11, "lane_id": "idle"},
                   {"line_no": 12, "lane_id": "cronly"}, {"line_no": 13, "lane_id": "daemon"}],
        "commented": [{"line_no": 20, "kind": "N8N_CUTOVER", "date": "2026-10-16", "lane_id": "migrated"},
                      {"line_no": 21, "kind": "N8N_CUTOVER", "date": "2026-10-16", "lane_id": "tag-no-run"},
                      {"line_no": 22, "kind": "CONSOLIDATED", "date": "2026-10-15", "lane_id": "folded", "token": "c1-manifest"}],
    }
    outcomes = {"migrated": {"live_runs": 1, "useful_live_output": 1}, "parallel": {"live_runs": 2, "lock_skips": 2},
                "native": {"live_runs": 3, "unverified_ok": 3}}
    kw = dict(registry_rows=reg, live_lanes=["migrated", "tag-no-run", "parallel", "idle"], cron=cron,
              families={"daemon": "F07"}, dispositions={}, holds={"held": "operator"}, outcomes=outcomes)
    kw.update(over)
    return R.lane_states(**kw)


def test_each_lane_gets_exactly_one_status():
    s = {k: v["status"] for k, v in _states().items()}
    assert s == {
        "migrated": "MIGRATED_PROVEN", "tag-no-run": "N8N_PRIMARY_UNPROVEN", "parallel": "PARALLEL",
        "idle": "LIVE_LISTED_IDLE", "cronly": "CRON_PRIMARY", "daemon": "RETAINED_F07", "timer": "RETAINED_SYSTEMD",
        "held": "HELD", "folded": "CONSOLIDATED", "gone": "RETIRED", "native": "N8N_NATIVE",
    }
    assert _states()["tag-no-run"]["unproven_reason"] == "no live RUN_DONE in window"


def test_lock_skips_alone_do_not_prove_migration():
    st = _states(outcomes={"migrated": {"live_runs": 4, "lock_skips": 4}})
    assert st["migrated"]["status"] == "N8N_PRIMARY_UNPROVEN"


def test_family_fully_owned_only_when_no_cron_or_parallel_lane():
    lanes = {
        "a": {"lane_id": "a", "family_id": "F1", "status": "MIGRATED_PROVEN"},
        "b": {"lane_id": "b", "family_id": "F1", "status": "RETIRED"},
        "c": {"lane_id": "c", "family_id": "F2", "status": "MIGRATED_PROVEN"},
        "d": {"lane_id": "d", "family_id": "F2", "status": "PARALLEL"},
    }
    f = {r["family_id"]: r for r in R.family_ownership(lanes)}
    assert f["F1"]["fully_n8n_owned"] is True and f["F1"]["lanes"] == 1
    assert f["F2"]["fully_n8n_owned"] is False and f["F2"]["cron_or_parallel_lanes"] == ["d"]


# ── incidents ───────────────────────────────────────────────────────────────────────────────────────────────────
def _b(lane, kind, at, state="OPEN", signal=None):
    ev = {"signal": signal} if signal else {}
    return {"lane_id": lane, "kind": kind, "detected_at": at, "state": state, "evidence": ev}


def test_incident_episodes_duplicates_and_recovery_rules():
    sig = {"kind": "file_mtime", "path": "x"}
    breaches = [
        _b("cleared", "STALE_2X", "2026-10-16T10:00:00+00:00"),
        _b("cleared", "STALE_2X", "2026-10-16T10:05:00+00:00", state="CLEARED"),
        _b("fresh", "NO_OUTPUT", "2026-10-16T10:00:00+00:00", signal=sig),
        _b("stale", "NO_OUTPUT", "2026-10-16T10:00:00+00:00", signal=sig),
        _b("stale", "NO_OUTPUT", "2026-10-16T11:00:00+00:00", signal=sig),
        _b("old", "NO_OUTPUT", "2026-10-01T11:00:00+00:00"),
    ]
    diagnoses = [{"lane": "stale", "event_type": "NO_OUTPUT", "at": "2026-10-16T11:01:00+00:00"}]
    receipts = [
        _r("runfix", state="RUN_FAILED", reason="exit_1", at="2026-10-16T09:00:00+00:00"),
        _r("runfix", verdict="produced", at="2026-10-16T10:00:00+00:00"),
        _r("runmeh", state="RUN_FAILED", reason="exit_1", at="2026-10-16T09:00:00+00:00"),
        _r("runmeh", at="2026-10-16T10:00:00+00:00"),
    ]
    now_by_lane = {"fresh": datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
                   "stale": datetime(2026, 10, 16, 9, tzinfo=timezone.utc)}
    calls = iter(["fresh", "stale"])

    def signal_now(_sig):
        return now_by_lane[next(calls)]

    eps = {(e["lane_id"], e["failure_class"]): e for e in R.incident_episodes(
        breaches=breaches, diagnoses=diagnoses, receipts=receipts, since=SINCE, until=UNTIL, signal_now=signal_now)}
    assert ("old", "NO_OUTPUT") not in eps
    assert eps[("cleared", "STALE_2X")]["recovery"] == "VERIFIED_RECOVERED"
    assert eps[("fresh", "NO_OUTPUT")]["recovery"] == "VERIFIED_RECOVERED"
    st = eps[("stale", "NO_OUTPUT")]
    assert st["recovery"] == "UNRESOLVED" and st["events"] == 3 and st["duplicate_events"] == 2
    assert eps[("runfix", "run:exit_1")]["recovery"] == "VERIFIED_RECOVERED"
    assert eps[("runmeh", "run:exit_1")]["recovery"] == "RAN_AGAIN_UNVERIFIED"


# ── notifications ───────────────────────────────────────────────────────────────────────────────────────────────
def test_provenance_never_guessed():
    assert R.provenance_of({"body": "· via n8n hermes-news-bridge 10:25"}) == ("n8n", "hermes-news-bridge")
    assert R.provenance_of({"body": "· via cron incident-notifier"}) == ("cron", "incident-notifier")
    assert R.provenance_of({"run_id": "d:lane-x:live:20261016T1000"}) == ("n8n", "lane-x")
    assert R.provenance_of({"body": None, "producer": "some.producer"}) == (R.UNKNOWN, R.UNKNOWN)
    s = R.summarize_notifications(
        [{"body": "· via cron a", "delivery_status": "SENT"}, {"body": None, "delivery_status": "SUPPRESSED"}],
        [{"decision": "DIGEST", "producer": "p"}], [])
    assert s["attribution"] == {"attributed": 1, "unknown": 1, "by_source": {"cron:a": 1, "UNKNOWN": 1}}
    assert s["router_decisions"] == {"DIGEST": 1}


# ── effect protection ───────────────────────────────────────────────────────────────────────────────────────────
def test_unwrapped_cron_line_is_not_fenced():
    keys = {
        "solo": {"process": "solo", "n8n_claim": True, "cron_claim": True},
        "dual": {"process": "dual", "n8n_claim": True, "cron_claim": True},
        "wrapped": {"process": "wrapped", "n8n_claim": True, "cron_claim": True},
        "staged": {"process": "staged", "n8n_claim": False, "cron_claim": False},
        "noowner": {"process": "noowner", "n8n_claim": True},
    }
    owners = {k: {"owner": "n8n", "epoch": 1} for k in ("solo", "dual", "wrapped")}
    cron_text = ("0 1 * * * cd /x && dual.py\n"
                 "0 2 * * * cd /x && TRADEAI_EFFECT_CLAIM=wrapped bash scripts/effect_claim_cron.sh wrapped.py\n")
    cron = {"active": [{"line_no": 1, "lane_id": "dual"}, {"line_no": 2, "lane_id": "wrapped"}]}
    claims = {"solo": Counter({"DONE": 3})}
    rows = {r["lane_id"]: r["protection"] for r in R.effect_protection(keys, owners, cron_text, cron, claims)}
    assert rows["solo"] == "SINGLE_OWNER_CLAIMING"
    assert rows["dual"].startswith("N8N_SIDE_ONLY")
    assert rows["wrapped"] == "ARMED_NOT_YET_EXERCISED"
    assert rows["staged"].startswith("STAGED")
    assert rows["noowner"].startswith("NOT_ARMED")


# ── PR proof ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_pr_proof_needs_live_verdict_at_a_containing_sha():
    def contains(a, b):
        return b in ("new", "newer")

    rs = [_r("a", verdict="produced", code_sha="new"), _r("b", verdict="produced", code_sha="old"),
          _r("c", code_sha="new"), _r("d", verdict="empty_allowed", code_sha="newer")]
    assert R.pr_proof(merge_sha="m", lanes=["a", "d"], receipts=rs, contains=contains)[0] == "PROVEN"
    assert R.pr_proof(merge_sha="m", lanes=["a", "b"], receipts=rs, contains=contains)[0] == "PARTIAL"
    assert R.pr_proof(merge_sha="m", lanes=["b", "c"], receipts=rs, contains=contains)[0] == "UNPROVEN"
    assert R.pr_proof(merge_sha="m", lanes=[], receipts=rs, contains=contains)[0] == "UNPROVEN"


# ── burn-down ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_burn_down_cohorts_and_projection():
    lanes = {
        "p": {"status": "PARALLEL"}, "p1": {"status": "PARALLEL"}, "i": {"status": "LIVE_LISTED_IDLE"},
        "s": {"status": "CRON_PRIMARY", "disposition": "MIGRATE_N8N", "dry_runs": 3},
        "al": {"status": "CRON_PRIMARY", "disposition": "MIGRATE_N8N", "dry_runs": 0},
        "no": {"status": "CRON_PRIMARY", "disposition": "CONSOLIDATE", "dry_runs": 0},
        "rt": {"status": "CRON_PRIMARY", "disposition": "RETIRE", "dry_runs": 0},
        "h": {"status": "HELD"}, "f": {"status": "RETAINED_F07"},
    }
    bd = R.burn_down(lanes, {"2026-10-14": 2, "2026-10-15": 2, "2026-10-16": 2}, today="2026-10-16",
                     allowlisted={"al"}, p1_last=["p1"], holds={"h": "x"})
    c = bd["cohorts"]
    assert c["C1_parallel_retire_cron_copy"] == ["p"] and c["C1p_parallel_p1_last"] == ["p1"]
    assert c["C2_live_listed_unproven"] == ["i"] and c["C3_shadow_proven_ready_for_live"] == ["s"]
    assert c["C4a_allowlisted_no_shadow_run"] == ["al"] and c["C4b_not_onboarded"] == ["no"]
    assert c["C7_retire_pending"] == ["rt"] and c["C6_operator_hold"] == ["h"]
    assert bd["remaining_lanes_excluding_holds"] == 7
    assert bd["rate_lanes_per_trading_day"] == 2.0
    # 7 lanes / 2 per trading day = 3.5 trading days -> 5 calendar days
    assert bd["projected_completion"] == "2026-10-21"
    assert R.burn_down({}, {}, today="2026-10-16", allowlisted=set(), p1_last=[], holds={})["projected_completion"] is None
