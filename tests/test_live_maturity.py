"""LQ-20261107-1901 / LQ-1957 / QA E14: LIVE MATURITY n/N counter (LiveAcceptance@v2).

A production fix is verified by N consecutive passing production cycles since it went live, one per expected
cadence slot. Never by elapsed time, never by "no errors seen", and never by a verdict the evidence cannot support:
  R1 no observed cycle is UNKNOWN (not "LIVE 0/N"); R2 a slot with no receipt is SILENT and breaks the streak;
  R3 a cron lane whose only evidence is its last receipt cannot hide a failure: an unobserved slot breaks the streak;
  R4 N counts slots (days for a daily lane), not receipts; R5 a service needs a release to match, >= 24 h elapsed and
  a restart seen by systemd's own timestamp; R6 a failing/silent lane says so first; R7 state is bounded and locked.

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


def _slot(d, h, day=11, lane="lane-a", **kw):
    return _receipt(d, lane, f"202611{day:02d}T{h:02d}00", _t(h, 0, day), **kw)


def _item(**kw):
    base = {"id": "x", "lq": "LQ-T", "fix_commit": "abc", "release": "abc-rel", "live_since": "2026-11-11 09:30",
            "cycle_kind": "intraday_lane", "N": 5, "cadence": {"cron": "0 * * * *", "grace_min": 30},
            "probe": {"kind": "n8n_receipts", "lane": "lane-a"}}
    base.update(kw)
    return base


class Src:
    def __init__(self, tmp_path, svc=None, anc=None):
        self.ancestor_fn = anc or (lambda fix, sha: None)
        self.receipts_dir = tmp_path / "n8n_runs"
        self.runtime_dir = tmp_path / "runtime"
        self.receipts_dir.mkdir(exist_ok=True)
        self.runtime_dir.mkdir(exist_ok=True)
        self.service_reader = svc or (lambda unit: None)


def _run(item, state, src, now):
    return lm.evaluate_item(item, state, src, now)


# ---- the counting rules ---------------------------------------------------------------------------------------

def test_counts_consecutive_passing_slots_since_live(tmp_path):
    s = Src(tmp_path)
    _slot(s.receipts_dir, 9)                                   # slot before live_since 09:30: never counts
    for h in (10, 11, 12):
        _slot(s.receipts_dir, h)
    st, res = _run(_item(), {}, s, _t(12, 45))
    assert st["n"] == 3 and res["verdict"] == "LIVE 3/5" and res["state"] == "live"


def test_no_double_count_across_runs(tmp_path):
    s = Src(tmp_path)
    _slot(s.receipts_dir, 10)
    st, _ = _run(_item(), {}, s, _t(10, 45))
    st, _ = _run(_item(), st, s, _t(10, 50))
    st, res = _run(_item(), st, s, _t(10, 55))
    assert st["n"] == 1
    _slot(s.receipts_dir, 11)
    st, res = _run(_item(), st, s, _t(11, 45))
    assert st["n"] == 2 and res["verdict"] == "LIVE 2/5" and st["last_cycle"] == "d:lane-a:live:20261111T1100"


def test_failing_cycle_resets_to_zero_then_recounts(tmp_path):
    s = Src(tmp_path)
    _slot(s.receipts_dir, 10)
    _slot(s.receipts_dir, 11)
    _slot(s.receipts_dir, 12, state="RUN_FAILED", exit_code=1)
    st, res = _run(_item(), {}, s, _t(12, 45))
    assert st["n"] == 0 and res["verdict"].startswith("FAILING · ") and res["state"] == "failing"
    _slot(s.receipts_dir, 13)
    st, res = _run(_item(), st, s, _t(13, 45))
    assert st["n"] == 1 and res["verdict"] == "LIVE 1/5"
    assert [h["pass"] for h in st["history"]] == [True, True, False, True]


def test_dry_run_receipts_never_count(tmp_path):
    s = Src(tmp_path)
    _receipt(s.receipts_dir, "lane-a", "20261111T1000", _t(10), mode="dry_run", name_mode="dry_run")
    _slot(s.receipts_dir, 11, mode="dry_run")                  # live name, dry body: not production
    _slot(s.receipts_dir, 12, effective="dry_run")             # clamped to dry by the stage gate
    st, res = _run(_item(), {}, s, _t(12, 45))
    assert st["n"] == 0 and res["state"] == "silent"           # three slots, no production receipt: SILENT
    assert all(h["pass"] is False and h["kind"] == "missed" for h in st["history"])


def test_inflight_is_pending_and_lock_skipped_is_not_a_cycle(tmp_path):
    s = Src(tmp_path)
    _slot(s.receipts_dir, 10, finished=False, state="RUN_STARTED")
    st, res = _run(_item(), {}, s, _t(10, 45))
    assert st["n"] == 0 and st["history"] == [] and res["state"] == "awaiting"
    _slot(s.receipts_dir, 11, lock_skipped=True, exit_code=75, state="RUN_FAILED")
    st, res = _run(_item(), {}, s, _t(11, 45))
    assert res["state"] != "live" and st["n"] == 0


def test_verified_at_N_then_failure_keeps_verdict_but_leads_with_the_failure(tmp_path):
    s = Src(tmp_path)
    for h in (10, 11, 12):
        _slot(s.receipts_dir, h)
    item = _item(N=3)
    st, res = _run(item, {}, s, _t(12, 45))
    assert res["verdict"] == "PRODUCTION VERIFIED"
    _slot(s.receipts_dir, 13, state="RUN_FAILED", exit_code=1)
    st, res = _run(item, st, s, _t(13, 45))
    assert st["n"] == 0 and res["state"] == "failing"
    assert res["verdict"].startswith("FAILING · ") and "PRODUCTION VERIFIED · LIVE MATURITY 0/3" in res["verdict"]


def test_prior_verdict_shows_combined_until_n_equals_N(tmp_path):
    s = Src(tmp_path)
    _slot(s.receipts_dir, 10)
    st, res = _run(_item(prior_verdict="PRODUCTION VERIFIED"), {}, s, _t(10, 45))
    assert res["verdict"] == "PRODUCTION VERIFIED · LIVE MATURITY 1/5"


def test_pending_fix_and_unknown_never_count(tmp_path):
    s = Src(tmp_path)
    _slot(s.receipts_dir, 10)
    st, res = _run(_item(live_since=None, status="pending_fix"), {}, s, _t(11))
    assert res["verdict"].startswith("PENDING FIX") and st.get("n", 0) == 0
    st, res = _run(_item(probe={"kind": "unknown", "reason": "lane name not in any receipt"}), {}, s, _t(11))
    assert res["verdict"].startswith("UNKNOWN") and "lane name" in res["verdict"]


# ---- R1: nothing observed is UNKNOWN, never "LIVE 0/N" -----------------------------------------------------

def test_r1_no_slot_elapsed_yet_is_unknown_awaiting(tmp_path):
    st, res = _run(_item(), {}, Src(tmp_path), _t(10, 10))
    assert res["verdict"].startswith("UNKNOWN") and "first live cycle" in res["verdict"] and res["state"] == "awaiting"
    assert "LIVE 0/" not in res["verdict"]


def test_r1_lane_named_but_dead_is_silent_not_young(tmp_path):
    st, res = _run(_item(probe={"kind": "n8n_receipts", "lane": "no-such-lane"}), {}, Src(tmp_path), _t(12, 45))
    assert res["state"] == "silent" and "SILENT" in res["verdict"] and "LIVE 0/" not in res["verdict"]


# ---- R2: silence is visible and breaks the streak ---------------------------------------------------------

def test_r2_three_passes_then_five_days_of_silence_is_not_verified(tmp_path):
    s = Src(tmp_path)
    for h in (10, 11, 12):
        _slot(s.receipts_dir, h)
    item = _item(N=3, cadence={"cron": "0 10-12 * * *", "grace_min": 30})
    st, res = _run(item, {}, s, _t(12, 45))
    assert res["verdict"] == "PRODUCTION VERIFIED"
    st, res = _run(item, st, s, _t(12, 45, day=16))             # five days, no receipt at any slot
    assert st["n"] == 0 and res["state"] == "silent"
    assert "SILENT" in res["verdict"] and res["verdict"].startswith("SILENT · ")


def test_r2_a_slot_inside_its_grace_is_not_yet_a_miss(tmp_path):
    st, res = _run(_item(), {}, Src(tmp_path), _t(10, 20))      # 10:00 slot, grace 30 min
    assert st["history"] == [] and res["state"] == "awaiting"


# ---- R3: a cron lane's last receipt cannot hide a failure -------------------------------------------------

def _last(s, lane, started, status="ok", exit_=0):
    (s.runtime_dir / f"{lane}_last.json").write_text(json.dumps(
        {"lane_id": lane, "mode": "live", "status": status, "exit": exit_,
         "started_at": started.astimezone(dt.timezone.utc).isoformat(),
         "finished_at": (started + dt.timedelta(seconds=40)).astimezone(dt.timezone.utc).isoformat()}))


def test_r3_failure_overwritten_between_polls_breaks_the_streak(tmp_path):
    s = Src(tmp_path)
    item = _item(cadence={"cron": "*/15 * * * *", "grace_min": 5}, probe={"kind": "last_receipt", "lane": "cron-a"})
    _last(s, "cron-a", _t(10, 0))
    st, _ = _run(item, {}, s, _t(10, 7))                         # baseline: first observation, slot 10:00 pass
    assert st["n"] == 1
    st, _ = _run(item, st, s, _t(10, 7))                         # same cycle polled again
    assert st["n"] == 1
    # 10:15 ran and FAILED, 10:30 passed and overwrote the file; we polled only after 10:30
    _last(s, "cron-a", _t(10, 30))
    st, res = _run(item, st, s, _t(10, 37))
    assert st["n"] == 1                                          # 10:15 unobserved -> streak broke, then 10:30 = 1
    kinds = [h["kind"] for h in st["history"]]
    assert kinds == ["pass", "unobserved", "pass"]


def test_r3_polling_every_slot_counts_each_once(tmp_path):
    s = Src(tmp_path)
    item = _item(cadence={"cron": "*/15 * * * *", "grace_min": 5}, probe={"kind": "last_receipt", "lane": "cron-a"})
    st = {}
    for i, (h, m) in enumerate(((10, 0), (10, 15), (10, 30))):
        _last(s, "cron-a", _t(h, m))
        st, _ = _run(item, st, s, _t(h, m + 7))
    assert st["n"] == 3


def test_r3_failing_last_receipt_resets(tmp_path):
    s = Src(tmp_path)
    item = _item(cadence={"cron": "*/15 * * * *", "grace_min": 5}, probe={"kind": "last_receipt", "lane": "cron-a"})
    _last(s, "cron-a", _t(10, 0))
    st, _ = _run(item, {}, s, _t(10, 7))
    _last(s, "cron-a", _t(10, 15), status="failed", exit_=1)
    st, res = _run(item, st, s, _t(10, 22))
    assert st["n"] == 0 and res["state"] == "failing"


# ---- R4: N counts slots, not receipts ---------------------------------------------------------------------

def test_r4_three_runs_in_one_day_on_a_daily_lane_is_one_cycle(tmp_path):
    s = Src(tmp_path)
    item = _item(N=3, cycle_kind="daily_lane", cadence={"cron": "45 16 * * 1-5", "grace_min": 30})
    for stamp, started in (("20261111T1645", _t(16, 45)), ("20261111T1700", _t(17, 0)), ("20261111T1730", _t(17, 30))):
        _receipt(s.receipts_dir, "lane-a", stamp, started)
    st, res = _run(item, {}, s, _t(18))
    assert st["n"] == 1 and res["verdict"] == "LIVE 1/3"          # off-slot passes are not cycles


def test_r4_an_off_slot_failure_is_still_a_failure(tmp_path):
    s = Src(tmp_path)
    item = _item(N=3, cycle_kind="daily_lane", cadence={"cron": "45 16 * * 1-5", "grace_min": 30})
    _receipt(s.receipts_dir, "lane-a", "20261111T1645", _t(16, 45))
    _receipt(s.receipts_dir, "lane-a", "20261111T1700", _t(17, 0), state="RUN_FAILED", exit_code=1)
    st, res = _run(item, {}, s, _t(18))
    assert st["n"] == 0 and res["state"] == "failing"


def test_r4_daily_lane_needs_three_distinct_days(tmp_path):
    s = Src(tmp_path)
    item = _item(N=3, cycle_kind="daily_lane", live_since="2026-11-09 08:00", cadence={"cron": "45 16 * * 1-5", "grace_min": 30})
    for day in (9, 10, 11):
        _receipt(s.receipts_dir, "lane-a", f"202611{day:02d}T1645", _t(16, 45, day))
    st, res = _run(item, {}, s, _t(18))
    assert st["n"] == 3 and res["verdict"] == "PRODUCTION VERIFIED"


# ---- R5: services -----------------------------------------------------------------------------------------

def _svc(active="active", enter="Wed 2026-11-11 14:23:48 EST", cwd="/r/aaaaaaa1-rel"):
    return lambda unit: {"active": active, "active_enter": enter, "cwd": cwd}


def _sitem(**kw):
    base = _item(cycle_kind="service", N=24, live_since="2026-11-11 14:23", cadence=None, fix_commit="fff0001",
                 release="aaaaaaa1-rel", probe={"kind": "service", "unit": "u.service"})
    base.update(kw)
    return base


def test_r5_service_with_neither_fix_commit_nor_accepted_releases_is_rejected():
    reg = {"schema": "LiveAcceptance@v2", "items": [_sitem(fix_commit="")]}
    with pytest.raises(ValueError, match="accepted_releases"):
        lm.validate_registry(reg)


def test_r5_hourly_samples_once_per_hour_wrong_release_resets(tmp_path):
    item = _sitem()
    s = Src(tmp_path, _svc())
    st, _ = _run(item, {}, s, _t(14, 30))
    st, _ = _run(item, st, s, _t(14, 50))
    assert st["n"] == 1
    st, _ = _run(item, st, s, _t(15, 5))
    assert st["n"] == 2
    s.service_reader = _svc(cwd="/r/bbbbbbb2-rel")
    s.ancestor_fn = lambda fix, sha: False                         # a release that does NOT contain the fix
    st, res = _run(item, st, s, _t(16, 5))
    assert st["n"] == 0 and res["state"] == "failing" and "changed_not_contained" in res["verdict"]


def test_r5_missed_hour_breaks_the_streak(tmp_path):
    item = _sitem()
    s = Src(tmp_path, _svc())
    st, _ = _run(item, {}, s, _t(14, 30))
    st, _ = _run(item, st, s, _t(15, 5))
    st, res = _run(item, st, s, _t(18, 5))                         # 16:xx and 17:xx never sampled
    assert st["n"] == 1 and [h["kind"] for h in st["history"]][-2:] == ["unobserved", "pass"]


def test_r5_needs_24h_elapsed_and_a_restart_seen_by_systemd_timestamp(tmp_path):
    item = _sitem(N=3)
    s = Src(tmp_path, _svc())
    st = {}
    for h in (14, 15, 16):
        st, res = _run(item, st, s, _t(h, 30))
    assert st["n"] == 3 and res["verdict"] == "LIVE 3/3 (restart not yet seen; 24 h not elapsed)"
    # restart at 16:40, i.e. after live_since + slack, though before the next sample
    s.service_reader = _svc(enter="Wed 2026-11-11 16:40:00 EST")
    st, res = _run(item, st, s, _t(17, 30))
    assert st["restart_confirmed"] is True and res["verdict"] == "LIVE 4/3 (24 h not elapsed)"
    st2, res2 = _run(item, st, s, _t(14, 30, day=12))             # next day: a gap -> streak broke; not verified
    assert res2["verdict"] != "PRODUCTION VERIFIED"


def test_r5_restart_before_the_first_sample_is_seen(tmp_path):
    item = _sitem(N=2, live_since="2026-11-11 08:00")
    s = Src(tmp_path, _svc(enter="Wed 2026-11-11 12:00:00 EST"))   # restarted 4 h after live_since, before sampling
    st, _ = _run(item, {}, s, _t(13, 30))
    assert st["restart_confirmed"] is True


def test_r5_the_activation_restart_itself_is_not_the_confirming_restart(tmp_path):
    item = _sitem(N=2)
    s = Src(tmp_path, _svc(enter="Wed 2026-11-11 14:23:48 EST"))   # the deploy's own start, within slack of live_since
    st, _ = _run(item, {}, s, _t(14, 30))
    assert st["restart_confirmed"] is False


def test_r5_verified_after_24h_with_restart(tmp_path):
    item = _sitem(N=3, live_since="2026-11-10 10:00")
    s = Src(tmp_path, _svc(enter="Wed 2026-11-11 05:00:00 EST"))
    st = {}
    for h in (11, 12, 13):
        st, res = _run(item, st, s, _t(h, 30, 11))
    assert res["verdict"] == "PRODUCTION VERIFIED"


def test_r5_service_unreadable_is_unknown_not_pass(tmp_path):
    st, res = _run(_sitem(), {}, Src(tmp_path, lambda unit: None), _t(14, 30))
    assert res["verdict"].startswith("UNKNOWN") and st.get("n", 0) == 0


# ---- R6/R7: wording, bounded state, lock, registry --------------------------------------------------------

def test_cron_slots_parse_ranges_steps_and_weekdays():
    slots = lm.cron_slots("*/15 4-5 * * 1-5", _t(3), _t(6))
    assert [s.strftime("%H:%M") for s in slots] == ["04:00", "04:15", "04:30", "04:45", "05:00", "05:15", "05:30", "05:45"]
    assert lm.cron_slots("40 */6 * * *", _t(0), _t(23, 59)) == [_t(0, 40), _t(6, 40), _t(12, 40), _t(18, 40)]
    assert lm.cron_slots("0 9 * * 0", _t(0, day=8), _t(23, day=9)) == [dt.datetime(2026, 11, 8, 9, 0, tzinfo=ET)]  # Sunday
    assert lm.cron_slots("45 16 * * 1-5", _t(0, day=14), _t(23, day=15)) == []                                     # Sat/Sun


def test_state_history_is_bounded(tmp_path):
    s = Src(tmp_path)
    item = _item(cadence={"cron": "* * * * *", "grace_min": 1}, live_since="2026-11-11 10:00")
    lm.HISTORY_CAP = 20
    try:
        for m in range(60):
            _receipt(s.receipts_dir, "lane-a", f"20261111T10{m:02d}", _t(10, m))
        st, _ = _run(item, {}, s, _t(11, 0))
        assert len(st["history"]) <= 20 and st["n"] == 60
    finally:
        lm.HISTORY_CAP = 100


def test_write_state_takes_a_lock_and_is_atomic(tmp_path, monkeypatch):
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"schema": "LiveAcceptance@v2", "items": [_item(live_since=None, status="pending_fix")]}))
    st = tmp_path / "state.json"
    assert lm.main(["--registry", str(reg), "--state", str(st), "--write-state"]) == 0
    assert st.exists() and (tmp_path / "state.json.lock").exists()
    assert not (tmp_path / "state.tmp").exists()


def test_seed_registry_is_valid_and_complete():
    reg = lm.load_registry(lm.DEFAULT_REGISTRY)
    lm.validate_registry(reg)
    ids = {i["id"] for i in reg["items"]}
    assert {"atm", "memory-promotion", "disk-hygiene", "portfolio-server", "jsonl-archive-rotate",
            "reconcile-exit-advisory-outcomes"} <= ids
    for i in reg["items"]:
        assert i["cycle_kind"] in ("daily_lane", "intraday_lane", "service")
        assert i["N"] in (3, 5, 24)
        assert i["probe"]["kind"] in ("n8n_receipts", "last_receipt", "service", "unknown")
        assert i.get("status") == "pending_fix" or i["live_since"]
        assert i["cycle_kind"] == "service" or i["cadence"]["cron"]


# ---- LQ-1969 B1: release membership by ancestry, not by a name substring ---------------------------------

def test_b1_later_release_containing_the_fix_stays_live_and_says_so(tmp_path):
    seen = []
    s = Src(tmp_path, _svc(cwd="/r/c085dc5ea-live-integration-1"), lambda fix, sha: seen.append((fix, sha)) or True)
    st = {}
    for h in (14, 15, 16):
        st, res = _run(_sitem(), st, s, _t(h, 30))
    assert st["n"] == 3 and res["state"] == "live" and res["verdict"] == "LIVE 3/24 · release changed, fix still contained"
    assert seen[0] == ("fff0001", "c085dc5ea")


def test_b1_release_that_lacks_the_fix_fails_and_inactive_unit_fails(tmp_path):
    s = Src(tmp_path, _svc(cwd="/r/c085dc5ea-x"), lambda fix, sha: False)
    st, res = _run(_sitem(), {}, s, _t(14, 30))
    assert res["state"] == "failing" and st["n"] == 0
    s = Src(tmp_path, _svc(active="failed"), lambda fix, sha: True)
    st, res = _run(_sitem(), {}, s, _t(14, 30))
    assert res["state"] == "failing"


def test_b1_ancestry_unanswerable_is_unknown_and_counts_nothing(tmp_path):
    s = Src(tmp_path, _svc(cwd="/r/c085dc5ea-x"), lambda fix, sha: None)
    st, res = _run(_sitem(), {}, s, _t(14, 30))
    assert res["state"] == "unknown" and "cannot prove fix fff0001" in res["verdict"] and st["history"] == []


def test_b1_explicit_accepted_release_needs_no_ancestry(tmp_path):
    item = _sitem(probe={"kind": "service", "unit": "u.service", "accepted_releases": ["c085dc5"]})
    s = Src(tmp_path, _svc(cwd="/r/c085dc5ea-x"), lambda fix, sha: pytest.fail("ancestry must not be asked"))
    st, res = _run(item, {}, s, _t(14, 30))
    assert st["n"] == 1 and "accepted release" in res["verdict"]


def test_b1_the_real_ancestry_check_answers_from_git():
    import subprocess
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    first = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], capture_output=True, text=True).stdout.split()[0]
    assert lm.git_is_ancestor(first, head) is True and lm.git_is_ancestor(head, first) in (False, None)
    assert lm.git_is_ancestor("0000000", head) is None
