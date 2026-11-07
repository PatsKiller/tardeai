"""ANCHOR: RUNQFIX_20261107 — Jobs & n8n Quality tab defects (operator paste, Degraded+Empty, 2026-11-07).

1. last run / status read the lane's own run receipt as a run source ("lane receipt"), so the card agrees with the grade;
2. a runtime is never judged "far above" a median under the floor or with too few samples;
3. an output file time alone is never written up as "Ran live";
4. a run whose receipt states a reviewed idle reason (config/run_quality_idle_reasons.json) is GOOD · idle, unless an
   input is stale (DEGRADED). Synthetic lanes and receipts only.
"""
from datetime import datetime, timedelta, timezone
import json

from scripts.lib import jobs_history as J
from scripts.lib import run_quality as Q

NOW = datetime(2026, 11, 4, 15, 7, tzinfo=timezone.utc)  # Wednesday 10:07 ET
WEEKDAY = lambda d: d.weekday() < 5  # noqa: E731


def z(dt):
    return dt.astimezone(timezone.utc).isoformat()


# ── defect 1: the lane receipt is a run source ──────────────────────────────────────────────────────────────────────

def n8n_lane(lane_id="synthetic-n8n-lane", cron="0 * * * *"):
    return {"lane_id": lane_id, "state": "ACTIVE", "expected_cadence_hours": 1,
            "scheduler": {"kind": "n8n"}, "dispatch": {"cron": cron, "tz": "America/New_York"}}


def ledger_row(lane, start, *, state="RUN_DONE", exit_code=0, dur=30, reason=None):
    run_id = f"d:{lane}:live:{start:%Y%m%dT%H%M}"
    return {"run_id": run_id, "lane_id": lane, "mode": "live", "state": state, "requested_by": "n8n:workflow:synthetic",
            "requested_at": z(start), "started_at": z(start), "finished_at": z(start + timedelta(seconds=dur)),
            "exit_code": exit_code, "duration_s": dur, "attempt": 1, "parent_run_id": None, "slot_key": run_id,
            "reason": reason, "attempt_states": None}


def lane_receipt_run(start, *, dur=60, **extra):
    doc = {"schema": "LaneRunReceipt@v1", "mode": "live", "status": "ok", "exit": 0, "started_at": z(start),
           "finished_at": z(start + timedelta(seconds=dur)), "ok_at": z(start + timedelta(seconds=dur)), **extra}
    run = J.receipt_run(doc, None)
    run["source"] = "lane receipt"
    return run


def build(lanes, **inputs):
    inputs.setdefault("ledger_since", NOW - timedelta(days=10))
    inputs.setdefault("journal_since", NOW - timedelta(days=10))
    return J.build({"lanes": lanes}, inputs, now=NOW, trading_day=WEEKDAY)


def row_of(out, lane_id="synthetic-n8n-lane"):
    return next(r for r in out["rows"] if r["lane_id"] == lane_id)


def test_newer_lane_receipt_success_is_the_last_run_over_an_old_ledger_failure():
    lane = "synthetic-n8n-lane"
    old = ledger_row(lane, NOW - timedelta(days=2), state="RUN_FAILED", exit_code=1, reason="exit_1 timeout")
    rec = lane_receipt_run(NOW.replace(minute=0, second=0, microsecond=0) + timedelta(seconds=20))
    row = row_of(build([n8n_lane()], ledger_runs=[old], lane_receipts={lane: rec}))
    assert row["last_run"]["source"] == "lane receipt" and row["last_run"]["result"] == "succeeded"
    assert row["last_run"]["started_at"] == rec["started_at"]
    assert row["status"] != "failed"
    assert row["last_success_at"] == rec["finished_at"].replace("+00:00", "Z") or row["last_success_at"].startswith(rec["finished_at"][:19])
    assert "lane receipt" in row["history_sources"]
    # the slot the receipt run started in is "ran", never "missed"
    ran = [s for s in row["slots"] if s["status"] == "ran"]
    assert ran and ran[0]["started_at"].startswith(rec["started_at"][:19])


def test_lane_receipt_only_lane_shows_a_run_and_succeeds():
    lane = "synthetic-n8n-lane"
    rec = lane_receipt_run(NOW - timedelta(minutes=10))
    row = row_of(build([n8n_lane()], lane_receipts={lane: rec}))
    assert row["last_run"] is not None and row["last_run"]["source"] == "lane receipt"
    assert row["status"] == "ok" and row["status_reason"] is None
    assert row["history_sources"] == ["lane receipt"]
    assert row["missed_count"] is None  # a single receipt never counts missed slots
    assert build([n8n_lane()], lane_receipts={lane: rec})["summary"]["no_run_history"] == 1


def test_receipt_of_a_ledger_run_is_not_counted_twice():
    lane = "synthetic-n8n-lane"
    start = NOW - timedelta(minutes=50)
    led = ledger_row(lane, start, dur=600)
    rec = lane_receipt_run(start + timedelta(minutes=4))  # n8n queued the script 4 min after requesting it
    row = row_of(build([n8n_lane()], ledger_runs=[led], lane_receipts={lane: rec}))
    assert row["last_run"]["source"] == "n8n run ledger"
    assert row["history_sources"] == ["n8n run ledger"]
    assert len(row["runs"]) == 1


def test_lane_receipt_failure_stays_failed_and_a_dry_receipt_is_no_run():
    lane = "synthetic-n8n-lane"
    good = ledger_row(lane, NOW - timedelta(hours=3))
    doc = {"mode": "live", "status": "failed", "exit": 2, "started_at": z(NOW - timedelta(minutes=5)),
           "finished_at": z(NOW - timedelta(minutes=4)), "error": "upstream refused"}
    bad = J.receipt_run(doc, None)
    bad["source"] = "lane receipt"
    row = row_of(build([n8n_lane()], ledger_runs=[good], lane_receipts={lane: bad}))
    assert row["status"] == "failed" and row["last_run"]["source"] == "lane receipt"
    assert J.receipt_run({**doc, "mode": "dry_run"}, None) is None


def test_read_lane_receipts_needs_a_run_time_not_a_bare_as_of(tmp_path):
    rt = tmp_path / "data/runtime"
    rt.mkdir(parents=True)
    (rt / "synthetic-a_last.json").write_text(json.dumps({"status": "ok", "exit": 0, "started_at": z(NOW),
                                                          "finished_at": z(NOW), "ok_at": z(NOW)}))
    (rt / "synthetic-b_last.json").write_text(json.dumps({"schema": "Doc@v1", "as_of": z(NOW)}))
    reg = {"lanes": [{"lane_id": "synthetic-a", "state": "ACTIVE"}, {"lane_id": "synthetic-b", "state": "ACTIVE"},
                     {"lane_id": "synthetic-c", "state": "PAUSED"}]}
    out = J.read_lane_receipts(reg, tmp_path)
    assert set(out) == {"synthetic-a"} and out["synthetic-a"]["source"] == "lane receipt"
    assert out["synthetic-a"]["result"] == "succeeded"


# ── run_quality fixtures (same shapes as tests/test_run_quality_20261106.py) ─────────────────────────────────────────

def lane(lane_id="synthetic-lane", kind="file_mtime"):
    signal = {"kind": kind, **({"path": f"data/runtime/{lane_id}_out.json"} if kind != "none" else {})}
    return {"lane_id": lane_id, "state": "ACTIVE", "output_signal": signal, "scheduler": {"kind": "n8n"},
            "dispatch": {"mode": "live"}}


def run(ago_min=30, *, result="succeeded", dur=60, run_id="r1", source="n8n run ledger"):
    start = NOW - timedelta(minutes=ago_min)
    return {"mode": "live", "result": result, "started_at": z(start), "finished_at": z(start + timedelta(seconds=dur)),
            "duration_s": dur, "run_id": run_id, "exit_code": 0, "reason": None, "source": source}


def row(*runs):
    return {"lane_id": "synthetic-lane", "state": "ACTIVE", "status": "ok", "runs": list(runs),
            "last_run": runs[0] if runs else None}


def receipt(ago_min=30, dur=60, **extra):
    start = NOW - timedelta(minutes=ago_min)
    return {"started_at": z(start), "finished_at": z(start + timedelta(seconds=dur)), "status": "ok", **extra}


def led(ago_min, *, run_id, dur=60, produced=None):
    return {"run_id": run_id, "mode": "live", "state": "RUN_DONE", "started": NOW - timedelta(minutes=ago_min),
            "duration_s": dur, "produced": produced, "mtime_before": None, "mtime_after": None, "reason": None, "why": None}


def ev(**kw):
    base = {"receipt": None, "receipt_path": None, "output_at": NOW - timedelta(minutes=29), "ledger": [], "history": [],
            "contract": None, "freshness": [], "freshness_known": True, "plausibility": [], "plausibility_known": True}
    base.update(kw)
    return base


def g(r, ln, e):
    return Q.grade(r, ln, e, now=NOW)


# ── defect 2: no duration breach against a meaningless median ───────────────────────────────────────────────────────

def test_duration_against_a_zero_median_is_unknown_not_degraded():
    ledger = [led(60 * (i + 2), run_id=f"p{i}", dur=0) for i in range(8)]
    q = g(row(run(dur=85, run_id="now")), lane(), ev(ledger=ledger, receipt=receipt(dur=85, produced_count=5)))
    assert q["grade"] == "GOOD"
    assert q["checks"]["duration_vs_history"]["result"] == "unknown"
    assert "floor" in q["checks"]["duration_vs_history"]["detail"]
    assert "median 0 s" not in json.dumps(q)


def test_duration_with_too_few_samples_is_unknown():
    ledger = [led(60 * (i + 2), run_id=f"p{i}", dur=20) for i in range(2)]
    q = g(row(run(dur=900, run_id="now")), lane(), ev(ledger=ledger, receipt=receipt(dur=900, produced_count=5)))
    assert q["grade"] == "GOOD" and q["checks"]["duration_vs_history"]["result"] == "unknown"


def test_duration_breach_against_a_real_median_still_degrades():
    ledger = [led(60 * (i + 2), run_id=f"p{i}", dur=20) for i in range(8)]
    q = g(row(run(dur=900, run_id="now")), lane(), ev(ledger=ledger, receipt=receipt(dur=900, produced_count=5)))
    assert q["grade"] == "DEGRADED" and "far above its median 20 s" in q["headline"]


# ── defect 3: a file write is not "Ran live" ───────────────────────────────────────────────────────────────────────

def test_document_with_only_a_time_is_output_written_not_ran_live():
    doc = {"schema": "SyntheticDoc@v1", "as_of": z(NOW - timedelta(minutes=9)), "items": 4}
    q = g(row(), lane(kind="json_key"), ev(receipt=doc, receipt_path="data/runtime/synthetic-lane_out.json"))
    assert (q["grade"], q["sub"]) == ("UNPROVEN", "no_run_record")
    assert q["headline"].startswith("Output written 9 min ago; no run record proves it ran")
    assert "Ran live" not in json.dumps(q["reasons"])


def test_output_mtime_without_any_run_record_says_output_written():
    q = g(row(), lane(), ev(output_at=NOW - timedelta(hours=2)))
    assert q["grade"] == "UNPROVEN"
    assert q["headline"].startswith("Output written 2 h ago; no run record proves it ran")


def test_bare_document_never_displaces_a_recorded_run():
    doc = {"schema": "SyntheticDoc@v1", "as_of": z(NOW - timedelta(minutes=1)), "produced_count": 3}
    q = g(row(run(30)), lane(), ev(receipt=doc))
    assert q["graded_run"]["source"] == "n8n run ledger" and q["headline"].startswith("Ran live")


def test_receipt_without_success_does_not_say_exited_ok():
    q = g(row(), lane(kind="none"), ev(receipt=receipt(status="", produced_count=None, exit=None, mode="live",
                                                       summary={"note": "x"})))
    assert "exited ok" not in q["headline"]


# ── defect 4: a stated idle reason is GOOD · idle ──────────────────────────────────────────────────────────────────

def test_idle_reasons_live_in_config():
    reasons = Q.idle_reasons()
    for token in ("market_closed", "nothing_due", "no_new_events", "no_new_input"):
        assert token in reasons and reasons[token]
    for not_idle in ("credit_cap_reached", "data_blocked", "deferred_to_batch"):
        assert not_idle not in reasons


def test_market_closed_idle_run_is_good_and_names_the_reason():
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=0, empty_reason="market_closed")))
    assert (q["grade"], q["sub"]) == ("GOOD", "idle")
    assert "nothing to do: the market was closed" in q["headline"]
    assert q["checks"]["item_count"]["result"] == "pass"


def test_idle_reason_in_summary_counts():
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=0, summary={"empty_reason": "no_new_events"})))
    assert (q["grade"], q["sub"]) == ("GOOD", "idle") and "no new events" in q["headline"]


def test_idle_run_with_a_stale_input_is_degraded():
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=0, empty_reason="no_new_input"),
                                  freshness=["input synthetic_feed is 3 d old (limit 1 d)"]))
    assert q["grade"] == "DEGRADED" and "synthetic_feed" in q["headline"]
    assert q["checks"]["input_freshness"]["result"] == "fail"


def test_zero_output_without_a_stated_or_known_reason_stays_empty():
    assert g(row(run()), lane(), ev(receipt=receipt(produced_count=0)))["grade"] == "EMPTY"
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=0, empty_reason="because")))
    assert (q["grade"], q["sub"]) == ("EMPTY", "unexpected")
    # output not written by the run is EMPTY even with an idle reason
    q = g(row(run()), lane(), ev(output_at=NOW - timedelta(days=2),
                                  receipt=receipt(produced_count=0, empty_reason="market_closed")))
    assert (q["grade"], q["sub"]) == ("EMPTY", "not_written")


def test_idle_config_path_is_read_from_file(tmp_path):
    p = tmp_path / "idle.json"
    p.write_text(json.dumps({"reasons": {"Synthetic_Idle": "a synthetic reason"}}))
    assert Q.idle_reasons(p) == {"synthetic_idle": "a synthetic reason"}
    assert Q.idle_reasons(tmp_path / "missing.json") == {}


def test_lock_skip_with_a_twin_lane_receipt_shows_the_twin_as_last_run():
    lane = "synthetic-n8n-lane"
    slot = NOW.replace(minute=0, second=0, microsecond=0)
    skip = ledger_row(lane, slot + timedelta(seconds=4), state="RUN_SKIPPED_LOCK", exit_code=None, dur=0)
    twin = lane_receipt_run(slot + timedelta(seconds=2))
    row = row_of(build([n8n_lane()], ledger_runs=[skip], lane_receipts={lane: twin}))
    assert row["last_run"]["source"] == "lane receipt" and row["last_run"]["result"] == "succeeded"
    assert {r["source"] for r in row["runs"]} == {"n8n run ledger", "lane receipt"}
