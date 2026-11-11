"""LQ-20261107-1901 / QA E14: LIVE MATURITY n/N counter (LiveAcceptance@v2).

A production fix is not verified by elapsed time or by "no errors seen": it is verified by N consecutive
passing production cycles since it went live. Any failing cycle resets n to 0; a dry_run receipt is never a
production cycle; a cycle counts once; a verdict already given is never downgraded.

Hermetic: synthetic receipts in a temp dir, a fake service reader. Never the real receipts, DB or services.
"""
from __future__ import annotations

import datetime as dt
import json
import zoneinfo

import pytest

from scripts.ops import live_maturity as lm

ET = zoneinfo.ZoneInfo("America/New_York")


def _t(h, m=0, day=11):
    return dt.datetime(2026, 11, day, h, m, tzinfo=ET)


def _receipt(d, lane, stamp, started, *, state="RUN_DONE", exit_code=0, mode="live", effective="live",
             lock_skipped=False, finished=True, name_mode="live"):
    rid = f"d:{lane}:{name_mode}:{stamp}"
    body = {
        "schema": "RunReceipt@v2", "lane_id": lane, "run_id": rid, "mode": mode, "requested_mode": mode,
        "state": state, "exit_code": exit_code, "timed_out": False, "lock_skipped": lock_skipped,
        "stage_clamp": {"clamped": False, "effective_mode": effective},
        "started_at": started.astimezone(dt.timezone.utc).isoformat(),
    }
    if finished:
        body["finished_at"] = (started + dt.timedelta(seconds=30)).astimezone(dt.timezone.utc).isoformat()
    (d / f"{rid}.json").write_text(json.dumps(body))
    return rid


def _item(**kw):
    base = {"id": "x", "lq": "LQ-T", "fix_commit": "abc", "release": "abc-rel", "live_since": "2026-11-11 10:00",
            "cycle_kind": "intraday_lane", "N": 5, "probe": {"kind": "n8n_receipts", "lane": "lane-a"}}
    base.update(kw)
    return base


class Src:
    def __init__(self, tmp_path, svc=None):
        self.receipts_dir = tmp_path / "n8n_runs"
        self.runtime_dir = tmp_path / "runtime"
        self.receipts_dir.mkdir(exist_ok=True)
        self.runtime_dir.mkdir(exist_ok=True)
        self.service_reader = svc or (lambda unit: None)


def _run(item, state, src, now):
    st, res = lm.evaluate_item(item, state, src, now)
    return st, res


def test_counts_consecutive_passing_cycles_since_live(tmp_path):
    s = Src(tmp_path)
    _receipt(s.receipts_dir, "lane-a", "20261111T0930", _t(9, 30))      # before live_since: never counts
    for i, h in enumerate((10, 11, 12)):
        _receipt(s.receipts_dir, "lane-a", f"20261111T{h}00", _t(h))
    st, res = _run(_item(), {}, s, _t(13))
    assert st["n"] == 3
    assert res["verdict"] == "LIVE 3/5"


def test_no_double_count_across_runs(tmp_path):
    s = Src(tmp_path)
    _receipt(s.receipts_dir, "lane-a", "20261111T1000", _t(10))
    st, _ = _run(_item(), {}, s, _t(11))
    st, _ = _run(_item(), st, s, _t(11, 5))
    st, res = _run(_item(), st, s, _t(11, 10))
    assert st["n"] == 1
    _receipt(s.receipts_dir, "lane-a", "20261111T1100", _t(11))
    st, res = _run(_item(), st, s, _t(12))
    assert st["n"] == 2 and res["verdict"] == "LIVE 2/5"
    assert st["last_cycle"] == "d:lane-a:live:20261111T1100"


def test_failing_cycle_resets_to_zero_then_recounts(tmp_path):
    s = Src(tmp_path)
    for h in (10, 11):
        _receipt(s.receipts_dir, "lane-a", f"20261111T{h}00", _t(h))
    _receipt(s.receipts_dir, "lane-a", "20261111T1200", _t(12), state="RUN_FAILED", exit_code=1)
    st, res = _run(_item(), {}, s, _t(13))
    assert st["n"] == 0 and res["verdict"] == "LIVE 0/5"
    _receipt(s.receipts_dir, "lane-a", "20261111T1300", _t(13))
    st, res = _run(_item(), st, s, _t(14))
    assert st["n"] == 1
    assert [h["pass"] for h in st["history"]] == [True, True, False, True]


def test_dry_run_receipts_never_count(tmp_path):
    s = Src(tmp_path)
    _receipt(s.receipts_dir, "lane-a", "20261111T1000", _t(10), mode="dry_run", name_mode="dry_run")
    _receipt(s.receipts_dir, "lane-a", "20261111T1100", _t(11), mode="dry_run")            # live name, dry body
    _receipt(s.receipts_dir, "lane-a", "20261111T1200", _t(12), effective="dry_run")      # clamped to dry
    st, res = _run(_item(), {}, s, _t(13))
    assert st["n"] == 0 and st["history"] == []
    # and a dry_run receipt does not reset a streak either
    _receipt(s.receipts_dir, "lane-a", "20261111T1300", _t(13))
    st, _ = _run(_item(), st, s, _t(14))
    _receipt(s.receipts_dir, "lane-a", "20261111T1400", _t(14), mode="dry_run", exit_code=1, state="RUN_FAILED")
    st, _ = _run(_item(), st, s, _t(15))
    assert st["n"] == 1


def test_inflight_and_lock_skipped_are_not_cycles(tmp_path):
    s = Src(tmp_path)
    _receipt(s.receipts_dir, "lane-a", "20261111T1000", _t(10), finished=False, state="RUN_STARTED")
    _receipt(s.receipts_dir, "lane-a", "20261111T1100", _t(11), lock_skipped=True, exit_code=75, state="RUN_FAILED")
    st, _ = _run(_item(), {}, s, _t(12))
    assert st["n"] == 0 and st["history"] == []


def test_verified_at_N_and_never_downgraded(tmp_path):
    s = Src(tmp_path)
    for h in (10, 11, 12):
        _receipt(s.receipts_dir, "lane-a", f"20261111T{h}00", _t(h))
    item = _item(N=3)
    st, res = _run(item, {}, s, _t(13))
    assert res["verdict"] == "PRODUCTION VERIFIED"
    _receipt(s.receipts_dir, "lane-a", "20261111T1300", _t(13), state="RUN_FAILED", exit_code=1)
    st, res = _run(item, st, s, _t(14))
    assert st["n"] == 0
    assert res["verdict"] == "PRODUCTION VERIFIED · LIVE MATURITY 0/3"


def test_prior_verdict_shows_combined_until_n_equals_N(tmp_path):
    s = Src(tmp_path)
    _receipt(s.receipts_dir, "lane-a", "20261111T1000", _t(10))
    item = _item(prior_verdict="PRODUCTION VERIFIED")
    st, res = _run(item, {}, s, _t(11))
    assert res["verdict"] == "PRODUCTION VERIFIED · LIVE MATURITY 1/5"


def test_pending_fix_and_unknown_never_count(tmp_path):
    s = Src(tmp_path)
    _receipt(s.receipts_dir, "lane-a", "20261111T1000", _t(10))
    st, res = _run(_item(live_since=None, status="pending_fix"), {}, s, _t(11))
    assert res["verdict"].startswith("PENDING FIX") and st.get("n", 0) == 0
    st, res = _run(_item(probe={"kind": "unknown", "reason": "lane name not in any receipt"}), {}, s, _t(11))
    assert res["verdict"].startswith("UNKNOWN") and "lane name" in res["verdict"]
    st, res = _run(_item(probe={"kind": "n8n_receipts", "lane": "no-such-lane"}), {}, s, _t(11))
    assert res["verdict"].startswith("LIVE 0/")   # lane named but no cycle yet: 0, not a guess


def test_last_receipt_probe_for_cron_lane(tmp_path):
    s = Src(tmp_path)
    item = _item(probe={"kind": "last_receipt", "lane": "cron-a"})
    (s.runtime_dir / "cron-a_last.json").write_text(json.dumps(
        {"lane_id": "cron-a", "mode": "live", "status": "ok", "exit": 0,
         "started_at": _t(10, 15).astimezone(dt.timezone.utc).isoformat(),
         "finished_at": _t(10, 16).astimezone(dt.timezone.utc).isoformat()}))
    st, _ = _run(item, {}, s, _t(10, 30))
    st, _ = _run(item, st, s, _t(10, 40))            # same cycle polled twice
    assert st["n"] == 1
    (s.runtime_dir / "cron-a_last.json").write_text(json.dumps(
        {"lane_id": "cron-a", "mode": "live", "status": "failed", "exit": 1,
         "started_at": _t(10, 30).astimezone(dt.timezone.utc).isoformat(),
         "finished_at": _t(10, 31).astimezone(dt.timezone.utc).isoformat()}))
    st, res = _run(item, st, s, _t(10, 45))
    assert st["n"] == 0


def _svc(active="active", enter="Wed 2026-11-11 14:23:48 EST", cwd="/r/abc-rel"):
    return lambda unit: {"active": active, "active_enter": enter, "cwd": cwd}


def test_service_hourly_samples_count_once_per_hour_and_need_a_restart(tmp_path):
    item = _item(cycle_kind="service", N=3, probe={"kind": "service", "unit": "u.service"})
    s = Src(tmp_path, _svc())
    st, _ = _run(item, {}, s, _t(14, 30))
    st, _ = _run(item, st, s, _t(14, 50))            # same hour: no second sample
    assert st["n"] == 1
    st, _ = _run(item, st, s, _t(15, 5))
    st, res = _run(item, st, s, _t(16, 5))
    assert st["n"] == 3
    assert res["verdict"] == "LIVE 3/3 (restart not yet seen)"   # n == N but no restart: not verified
    s.service_reader = _svc(enter="Wed 2026-11-11 16:30:00 EST")
    st, res = _run(item, st, s, _t(17, 5))
    assert st["restart_confirmed"] is True
    assert res["verdict"] == "PRODUCTION VERIFIED"


def test_service_on_wrong_release_or_inactive_fails_and_resets(tmp_path):
    item = _item(cycle_kind="service", N=3, probe={"kind": "service", "unit": "u.service"})
    s = Src(tmp_path, _svc())
    st, _ = _run(item, {}, s, _t(14, 30))
    st, _ = _run(item, st, s, _t(15, 5))
    assert st["n"] == 2
    s.service_reader = _svc(cwd="/r/other-release")
    st, res = _run(item, st, s, _t(16, 5))
    assert st["n"] == 0 and res["verdict"] == "LIVE 0/3 (restart not yet seen)"
    s.service_reader = _svc(active="failed")
    st, _ = _run(item, st, s, _t(17, 5))
    assert st["n"] == 0


def test_service_unreadable_is_unknown_not_pass(tmp_path):
    item = _item(cycle_kind="service", N=3, probe={"kind": "service", "unit": "u.service"})
    s = Src(tmp_path, lambda unit: None)
    st, res = _run(item, {}, s, _t(14, 30))
    assert res["verdict"].startswith("UNKNOWN") and st.get("n", 0) == 0


def test_seed_registry_is_valid_and_complete():
    reg = lm.load_registry(lm.DEFAULT_REGISTRY)
    assert reg["schema"] == "LiveAcceptance@v2"
    ids = {i["id"] for i in reg["items"]}
    assert {"atm", "memory-promotion", "disk-hygiene", "portfolio-server", "jsonl-archive-rotate",
            "reconcile-exit-advisory-outcomes"} <= ids
    for i in reg["items"]:
        assert i["cycle_kind"] in ("daily_lane", "intraday_lane", "service")
        assert i["N"] in (3, 5, 24)
        assert i["probe"]["kind"] in ("n8n_receipts", "last_receipt", "service", "unknown")
        assert i.get("status") == "pending_fix" or i["live_since"]
