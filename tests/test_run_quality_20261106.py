"""ANCHOR: RUN_QUALITY_20261106 — per-lane run QUALITY grade on /api/v2/jobs-history.

Operator 2026-11-06: lanes showed "OK" when their last run was skipped or a dry run (a classifier skipped 7 days ago,
a scalp lane skipped, a monitor "fully moved" with a dry-run last run). Every grade is exercised here with synthetic
lanes and receipts only: no real lanes, holdings or stores. The snapshot script writes only under tmp_path.
"""
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts.lib import jobs_history as J
from scripts.lib import run_quality as Q
import scripts.run_quality_snapshot as S

NOW = datetime(2026, 11, 4, 15, 7, tzinfo=timezone.utc)


def z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def lane(lane_id="synthetic-lane", *, state="ACTIVE", kind="file_mtime", sched="n8n", stage=None, dispatch="live"):
    signal = {"kind": kind}
    if kind in {"file_mtime", "json_key"}:
        signal["path"] = f"data/runtime/{lane_id}_out.json"
    return {"lane_id": lane_id, "state": state, "output_signal": signal,
            "scheduler": {"kind": sched, **({"stage": stage} if stage else {})}, "dispatch": {"mode": dispatch}}


def run(ago_min=30, *, result="succeeded", dur=60, run_id="r1", exit_code=0, reason=None, source="n8n run ledger"):
    start = NOW - timedelta(minutes=ago_min)
    return {"mode": "live", "result": result, "started_at": z(start), "finished_at": z(start + timedelta(seconds=dur)),
            "duration_s": dur, "run_id": run_id, "exit_code": exit_code, "reason": reason, "source": source}


def row(*runs, lane_id="synthetic-lane", status="ok"):
    return {"lane_id": lane_id, "state": "ACTIVE", "status": status, "runs": list(runs),
            "last_run": runs[0] if runs else None}


def receipt(ago_min=30, dur=60, **extra):
    start = NOW - timedelta(minutes=ago_min)
    return {"started_at": z(start), "finished_at": z(start + timedelta(seconds=dur)), "status": "ok", **extra}


def led(ago_min, *, run_id, state="RUN_DONE", mode="live", dur=60, produced=None, reason=None, why=None, mb=None, ma=None):
    return {"run_id": run_id, "mode": mode, "state": state, "started": NOW - timedelta(minutes=ago_min),
            "duration_s": dur, "produced": produced, "mtime_before": mb, "mtime_after": ma, "reason": reason, "why": why}


def ev(**kw):
    base = {"receipt": None, "receipt_path": None, "output_at": NOW - timedelta(minutes=29), "ledger": [], "history": [],
            "contract": None, "freshness": [], "freshness_known": True, "plausibility": [], "plausibility_known": True}
    base.update(kw)
    return base


def g(r, ln, e):
    return Q.grade(r, ln, e, now=NOW)


# ── GOOD ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_good_run_wrote_output_with_items():
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=50)))
    assert q["grade"] == "GOOD", q
    assert q["checks"]["output_written"]["result"] == "pass"
    assert q["checks"]["item_count"] == {"result": "pass", "value": 50, "detail": "produced_count"}
    assert q["as_designed"] is True


# ── FAILED ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_failed_nonzero_exit():
    q = g(row(run(result="failed", exit_code=2, reason="Traceback: boom")), lane(), ev())
    assert q["grade"] == "FAILED"
    assert "exit 2" in q["reasons"][0] and "boom" in q["reasons"][0]


def test_failed_receipt_status_with_streak():
    rc = receipt(status="failed", exit=0, consecutive_failures=4)
    q = g(row(run()), lane(), ev(receipt=rc))
    assert q["grade"] == "FAILED"
    assert "4 failures in a row" in q["reasons"][0]


# ── NOT_LIVE ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_not_live_inactive_lane_is_never_ok():
    q = g(row(run()), lane(state="PAUSED"), ev())
    assert (q["grade"], q["sub"]) == ("NOT_LIVE", "inactive")


def test_not_live_only_dry_runs():
    dry = {"mode": "dry_run", "result": "succeeded", "started_at": z(NOW - timedelta(hours=1))}
    q = g(row(dry), lane(dispatch="dry_run"), ev(ledger=[led(60, run_id="d1", mode="dry_run")]))
    assert (q["grade"], q["sub"]) == ("NOT_LIVE", "dry_run")
    assert q["checks"]["ran_live"]["result"] == "fail"


def test_not_live_shadow_receipt():
    q = g(row(), lane(), ev(receipt=receipt(mode="shadow")))
    assert (q["grade"], q["sub"]) == ("NOT_LIVE", "shadow")


def test_not_live_skipped_has_reason():
    q = g(row(run(result="skipped", reason="market_closed")), lane(), ev())
    assert (q["grade"], q["sub"]) == ("NOT_LIVE", "skipped")
    assert "the market was closed" in q["reasons"][0]


# ── the three operator false positives (synthetic shapes) ─────────────────────────────────────────────────────────

def test_false_positive_classifier_skipped_7_days_ago_with_cron_twin():
    """n8n slot skipped on flock_held 7 days ago; the cron twin held the lock and ran. Must not read OK."""
    slot = 7 * 24 * 60
    ln = lane("synthetic-classifier", sched="cron", stage="canary", kind="none")
    r = row(run(slot, result="skipped_lock", run_id="s1", exit_code=75, reason="flock_held"), lane_id="synthetic-classifier")
    rc = receipt(slot + 1, dur=900, produced_count=3435)
    q = g(r, ln, ev(receipt=rc, ledger=[led(slot, run_id="s1", state="RUN_SKIPPED_LOCK", reason="flock_held")]))
    assert (q["grade"], q["sub"]) == ("NOT_LIVE", "skipped"), q
    assert "7 d ago" in q["reasons"][0] and "another copy of the job still held its lock" in q["reasons"][0]
    assert any("produced_count = 3435" in x for x in q["reasons"])
    assert q["as_designed"] is False and any("both cron and n8n" in d for d in q["design_issues"])


def test_false_positive_scalp_every_n8n_slot_skipped():
    ln = lane("synthetic-scalp", sched="cron", stage="canary", kind="none")
    ledger = [led(m, run_id=f"s{m}", state="RUN_SKIPPED_LOCK", reason="flock_held") for m in (90, 60, 30)]
    r = row(run(30, result="skipped_lock", run_id="s30", exit_code=75, reason="flock_held"), lane_id="synthetic-scalp")
    q = g(r, ln, ev(receipt=receipt(31, dur=120, universe=144), ledger=ledger,
                    contract={"stage": "shadow"}))
    assert (q["grade"], q["sub"]) == ("NOT_LIVE", "skipped")
    assert any("last 3 n8n live slots were all skipped" in x for x in q["reasons"])
    assert any("registry stage is canary but its n8n health contract says shadow" in d for d in q["design_issues"])


def test_false_positive_monitor_fully_moved_but_dry_shadow_still_fires():
    ln = lane("synthetic-monitor", stage="cutover")
    rc = receipt(summary={"status": "DEGRADED", "overlap_pct": 28.6}, produced_count=1)
    q = g(row(run(), lane_id="synthetic-monitor"), ln,
          ev(receipt=rc, contract={"stage": "canary"}, ledger=[led(15 * 60, run_id="d1", mode="dry_run")]))
    assert q["grade"] == "DEGRADED", q
    assert any("summary status is DEGRADED" in x for x in q["reasons"])
    assert q["as_designed"] is False
    assert any("stage is cutover but a dry-run shadow of it still fires" in d for d in q["design_issues"])


# ── EMPTY ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_empty_output_not_written_this_run():
    q = g(row(run()), lane(), ev(output_at=NOW - timedelta(days=2)))
    assert (q["grade"], q["sub"]) == ("EMPTY", "not_written")
    assert q["checks"]["output_written"]["result"] == "fail"


def test_empty_zero_items_nothing_due_vs_unexpected():
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=0, empty_reason="nothing_due")))
    assert (q["grade"], q["sub"]) == ("EMPTY", "nothing_due")
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=0)))
    assert (q["grade"], q["sub"]) == ("EMPTY", "unexpected")


def test_n8n_exit0_empty_output_is_empty_not_failed():
    r = row(run(result="failed", run_id="x1"))
    q = g(r, lane(), ev(ledger=[led(30, run_id="x1", state="RUN_FAILED", reason="empty_output", produced=0)]))
    assert (q["grade"], q["sub"]) == ("EMPTY", "unexpected")


# ── DEGRADED ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_degraded_receipt_flags_partial_and_errors():
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=20, errors=3, fallback_used=True)))
    assert q["grade"] == "DEGRADED"
    text = " ".join(q["reasons"])
    assert "errors = 3" in text and "fallback" in text


def test_degraded_item_count_drop_vs_own_median():
    hist = [{"lane_id": "synthetic-lane", "count_key": "produced_count", "count": 100,
             "run_started_at": z(NOW - timedelta(days=d))} for d in (1, 2, 3, 4)]
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=10), history=hist))
    assert q["grade"] == "DEGRADED"
    assert q["checks"]["count_vs_history"]["result"] == "fail"
    assert "90% below its median 100" in q["reasons"][0]


def test_degraded_duration_far_outside_history():
    ledger = [led(60 * h, run_id=f"p{h}", dur=10) for h in range(2, 8)] + [led(30, run_id="r1", dur=500)]
    q = g(row(run(dur=500)), lane(), ev(receipt=receipt(dur=500, produced_count=5), ledger=ledger))
    assert q["grade"] == "DEGRADED"
    assert "far above its median 10 s" in q["checks"]["duration_vs_history"]["detail"]


def test_degraded_input_freshness_breach():
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=5),
                                freshness=["input freshness breach open: synthetic_table is stale"]))
    assert q["grade"] == "DEGRADED" and q["checks"]["input_freshness"]["result"] == "fail"


def test_degraded_plausibility_violation():
    q = g(row(run()), lane(), ev(receipt=receipt(produced_count=5),
                                plausibility=["data plausibility FAIL: synthetic_table.px has 4 violating rows ()"]))
    assert q["grade"] == "DEGRADED" and q["checks"]["data_plausibility"]["result"] == "fail"


def test_benign_skipped_reasons_do_not_degrade():
    rc = receipt(produced_count=2, skipped_reasons={"already_settled": 40})
    assert g(row(run()), lane(), ev(receipt=rc))["grade"] == "GOOD"


# ── UNPROVEN ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_unproven_no_run_record_says_what_is_missing():
    q = g(row(), lane(), ev())
    assert (q["grade"], q["sub"]) == ("UNPROVEN", "no_run_record")
    assert "file time does not prove a run" in q["reasons"][0]


def test_unproven_no_output_signal_and_no_count():
    q = g(row(run()), lane(kind="none"), ev(output_at=None))
    assert (q["grade"], q["sub"]) == ("UNPROVEN", "output_unverifiable")
    assert "declares no output signal" in q["reasons"][0]


def test_n8n_exit0_output_unverifiable_is_unproven_not_failed():
    r = row(run(result="failed", run_id="x1"))
    q = g(r, lane(), ev(ledger=[led(30, run_id="x1", state="RUN_FAILED", reason="output_unverifiable",
                                    why="counts_inconsistent")]))
    assert (q["grade"], q["sub"]) == ("UNPROVEN", "output_unverifiable")
    assert "counts_inconsistent" in q["reasons"][0]


# ── not as designed: missed slot ────────────────────────────────────────────────────────────────────────────────────

def test_missed_slot_is_not_as_designed():
    r = row(run(), status="missed")
    r["status_reason"] = "no run in the 10:00 slot"
    q = g(r, lane(), ev(receipt=receipt(produced_count=5)))
    assert q["as_designed"] is False and "missed" in q["design_issues"][0]


# ── attach + API filter ─────────────────────────────────────────────────────────────────────────────────────────────

def _result():
    return {"summary": {}, "rows": [
        {**row(run(), lane_id="a"), "lane_id": "a"},
        {**row(lane_id="b"), "lane_id": "b"},
        {**row(run(), lane_id="c"), "state": "RETIRED"},
    ]}


def test_attach_adds_quality_and_all_six_counts():
    registry = {"lanes": [lane("a"), lane("b"), lane("c", state="RETIRED")]}
    evidence = {"a": ev(receipt=receipt(produced_count=3)), "b": ev()}
    out = Q.attach(_result(), registry, root=None, now=NOW, evidence=evidence)
    assert set(out["summary"]["quality_counts"]) == set(Q.GRADES)
    assert out["summary"]["quality_counts"]["GOOD"] == 1
    assert out["summary"]["quality_counts"]["UNPROVEN"] == 1
    assert out["summary"]["quality_not_live_by_reason"] == {"inactive": 1}
    assert all("quality" in r for r in out["rows"])


def test_jobs_history_quality_filter_and_unknown_is_400(monkeypatch):
    registry = {"lanes": [lane("a"), lane("b"), lane("c", state="RETIRED")]}
    res = Q.attach(_result(), registry, root=None, now=NOW,
                   evidence={"a": ev(receipt=receipt(produced_count=3)), "b": ev()})
    for r in res["rows"]:
        r.update(job=r["lane_id"], scheduler="n8n", missed_count=0, fix_count=0, title=r["lane_id"],
                 cadence={"expressions": [], "timezone": "UTC", "every_hours": 1, "market_days_only": False})
    monkeypatch.setattr(J, "snapshot", lambda **kw: res)
    out = J.get_jobs_history({"filter": "all", "quality": "good"})
    assert out["quality"] == "GOOD" and [r["lane_id"] for r in out["rows"]] == ["a"]
    assert out["rows"][0]["quality"]["grade"] == "GOOD"
    assert J.get_jobs_history({"filter": "all", "quality": "not_live"})["total"] == 1
    with pytest.raises(ValueError, match="unknown quality"):
        J.get_jobs_history({"filter": "all", "quality": "OK"})


# ── snapshot script: dry-run default, apply, dedup, writes only under the given root ─────────────────────────────

def test_snapshot_script_dry_run_then_apply(tmp_path, capsys):
    state = tmp_path / "state"
    out_root = tmp_path / "out"
    (state / "data/runtime").mkdir(parents=True)
    (state / "data/runtime/synthetic-lane_last.json").write_text(json.dumps(receipt(produced_count=7)))
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"lanes": [lane(kind="none"), lane("retired-lane", state="RETIRED", kind="none")]}))
    hist = out_root / Q.HISTORY_FILE
    base = ["--state-root", str(state), "--history-root", str(out_root), "--registry", str(reg)]

    assert S.main(base) == 0
    assert '"would_append": 1' in capsys.readouterr().out
    assert not hist.exists() and not (state / Q.HISTORY_FILE).exists()

    assert S.main(base + ["--apply"]) == 0
    rows = [json.loads(x) for x in hist.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["schema"] == Q.HISTORY_SCHEMA
    assert (rows[0]["lane_id"], rows[0]["count"], rows[0]["count_key"]) == ("synthetic-lane", 7, "produced_count")
    assert rows[0]["duration_s"] == 60.0

    assert S.main(base + ["--apply"]) == 0  # same run again: nothing appended
    assert len(hist.read_text().splitlines()) == 1
    assert not (state / Q.HISTORY_FILE).exists()
