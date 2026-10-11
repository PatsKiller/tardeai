"""B families top 5 (n8n-maturity, 2026-10-11): one parameterised job per same-script cron family.

Equivalence proof for scripts/lib/family_slot_jobs.py + scripts/run_family_slot.py:

  1. text   — each mode's command is the retired crontab line's command, verbatim (the lines below are copied
              from the live crontab of 2026-10-11, sha256 7eb97ad6…, with the served root replaced by a fake one);
              same log, same schedule recorded, same lock inside the command.
  2. time   — minute by minute over an EDT week and an EST week, the union of the family's crontab lines fires
              exactly at the slot-table minutes (no fire without a slot, no slot without a fire, never two lines
              in one minute).
  3. effect — over the same weeks every EFFECTIVE run of a retired line (it fired and every gate wrapper in it
              would let it through) is a run of the same mode of the new job at the same minute, and every new
              run is such a run — except the deltas each Family declares, which are asserted exactly.
  4. gates  — no new fire is a predicted gate refusal in a week without a market holiday (the wasted fires
              stop); the fires/week saved are 67 + 10 + 5 + 5 + 0.
  5. entry  — the CLI refuses a fire outside every slot (exit 2), runs nothing on --dry-run, and on a real run
              executes `/bin/bash -c <command>` in the root with the cron env, appends to the mode's log, keeps
              going after a failing mode, returns its exit code and writes a LaneRunReceipt@v1.
  6. registry — one ACTIVE row per family whose schedules are the crontab lines and whose match hits only that
              family's lines; every retired lane is RETIRED with superseded_by.

Hermetic: tmp_path roots, TRADEAI_STATE_ROOT under tmp_path, fake mode commands for the run test; nothing on the
host is read or written. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import family_slot_jobs as FSJ  # noqa: E402
from scripts.lib.lane_registry import discover_cron, find_undeclared  # noqa: E402

FAKE = "/srv/tradeai/portfolio-server/CURRENT"
EDT_WEEK = datetime(2026, 10, 12)   # Mon; no NYSE holiday that week
EST_WEEK = datetime(2026, 12, 7)    # Mon; EST, no holiday
MONTH_WEEK = datetime(2026, 11, 30)  # Mon 11-30 .. Sun 12-06: contains Tue the 1st (B1 monthly)

# Live crontab 2026-10-11 (sha256 7eb97ad6adef5e725c9d1847b081d5ecf5059ceb3257b444ae34736880737412), L379/L380 and
# the 12 other retired lines, verbatim except the served root -> {R}.
RETIRED_LINES = {
    "L379": "*/30 4-9 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_premarket.lock $PY scripts/catalyst_momentum_engine.py --band premarket_scalp --apply --generate-proposals >> logs/catalyst_momentum_engine.log 2>&1",
    "L380": "30 9-15 * * 1-5 cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_swing.lock $PY scripts/catalyst_momentum_engine.py --band market_swing --apply --generate-proposals >> logs/catalyst_momentum_engine.log 2>&1",
    "L381": "0 18,22 * * * cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_overnight.lock $PY scripts/catalyst_momentum_engine.py --band overnight --apply >> logs/catalyst_momentum_engine.log 2>&1",
    "L581": "5 9 * * 1-5 cd {R} && env LLM_GLOBAL_DAILY_USD_CAP=2.00 flock -n /tmp/research_sched.lock env RESEARCH_SKIP_GATE=1 $PY {R}/scripts/research_scheduler.py --mode holdings --apply --budget 70 >> {R}/logs/research_scheduler.log 2>&1",
    "L582": "0 10-16 * * 1-5 cd {R} && bash {R}/scripts/llm_priority_guard.sh && env LLM_GLOBAL_DAILY_USD_CAP=2.00 flock -n /tmp/research_sched.lock env RESEARCH_SKIP_GATE=1 $PY {R}/scripts/research_scheduler.py --mode priority --apply --budget 40 >> {R}/logs/research_scheduler.log 2>&1",
    "L583": "30 20 * * 1-5 cd {R} && env LLM_GLOBAL_DAILY_USD_CAP=2.00 flock -n /tmp/research_sched.lock env RESEARCH_SKIP_GATE=1 $PY {R}/scripts/research_scheduler.py --mode watchlist --apply --budget 50 >> {R}/logs/research_scheduler.log 2>&1",
    "L585": "0 19 * * 0 cd {R} && env LLM_GLOBAL_DAILY_USD_CAP=2.00 flock -n /tmp/research_sched.lock env RESEARCH_SKIP_GATE=1 $PY {R}/scripts/research_scheduler.py --mode incubator --apply --budget 30 >> {R}/logs/research_scheduler.log 2>&1",
    "L732": "20 * * * * cd {R} && bash {R}/scripts/non_trading_hours_gate.sh bash -c 'bash {R}/scripts/llm_priority_guard.sh && flock -n /tmp/topic_synth.lock $PY scripts/topic_research_synthesizer.py --max 15 --apply' >> {R}/logs/topic_research_synth.log 2>&1",
    "L734": "45 20 * * 1-5 cd {R} && bash {R}/scripts/non_trading_hours_gate.sh timeout 30m $PY scripts/topic_ingestion.py --use-llm-queries --max-topics 14 >> {R}/logs/topic_ingestion.log 2>&1",
    "L735": "45 2 * * * cd {R} && bash \"$HOME/.config/tradeai/bin/run_with_deepseek_offpeak.sh\" --official -- bash {R}/scripts/non_trading_hours_gate.sh timeout 30m $PY scripts/topic_ingestion.py --use-llm-queries --max-topics 14 >> {R}/logs/topic_ingestion.log 2>&1",
    "L736": "50 21 * * * cd {R} && bash \"$HOME/.config/tradeai/bin/run_with_deepseek_offpeak.sh\" --official -- bash {R}/scripts/non_trading_hours_gate.sh flock -n /tmp/topic_reground.lock $PY scripts/topic_research_synthesizer.py --reground --max 20 --apply >> {R}/logs/topic_research_synth.log 2>&1",
    "L847": "0 5 * * 1-5 cd {R} && python3 -c 'from scripts.lib.cio_event_detector import run_cio_event_detector_once; r=run_cio_event_detector_once(); print(\"Wakes:\", r.get(\"wakes_created\", 0))' >> logs/cio_detector.log 2>&1",
    "L848": "0 8 * * 0 cd {R} && python3 -c 'from scripts.lib.cio_event_detector import run_cio_event_detector_once; r=run_cio_event_detector_once(); print(\"Wakes:\", r.get(\"wakes_created\", 0))' >> logs/cio_detector_weekly.log 2>&1",
    "L849": "0 9 1 * * cd {R} && python3 -c 'from scripts.lib.cio_event_detector import run_cio_event_detector_once; r=run_cio_event_detector_once(); print(\"Wakes:\", r.get(\"wakes_created\", 0))' >> logs/cio_detector_monthly.log 2>&1",
}
#: (family, mode) -> retired line. L381 is the B8 overnight mode, kept on its own line (D3 shadow lane).
MODE_LINE = {
    ("catalyst-momentum-engine", "premarket_scalp"): "L379",
    ("catalyst-momentum-engine", "market_swing"): "L380",
    ("catalyst-momentum-engine", "overnight"): "L381",
    ("research-scheduler", "holdings"): "L581",
    ("research-scheduler", "priority"): "L582",
    ("research-scheduler", "watchlist"): "L583",
    ("research-scheduler", "incubator"): "L585",
    ("topic-research-synthesizer", "synth"): "L732",
    ("topic-research-synthesizer", "reground"): "L736",
    ("topic-ingestion", "after_close"): "L734",
    ("topic-ingestion", "weekend_overnight"): "L735",
    ("cio-event-detector", "daily"): "L847",
    ("cio-event-detector", "weekly"): "L848",
    ("cio-event-detector", "monthly"): "L849",
}
#: The one deliberate command change: B1 gains a lock (design B1).
B1_LOCK = "flock -n /tmp/cio_event_detector.lock "
LINE_RE = re.compile(r"^(\S+ \S+ \S+ \S+ \S+) cd (\S+) && (.*) >> (\S+) 2>&1$")


def _parse(line_id: str) -> tuple[str, str, str]:
    m = LINE_RE.match(RETIRED_LINES[line_id].replace("{R}", FAKE))
    assert m, line_id
    sched, _cd, body, log = m.groups()
    return sched, body, log.replace(FAKE + "/", "")


def _all_modes():
    return [(f, m) for f in FSJ.FAMILIES for m in f.modes]


# ── 1. text ─────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fam,mode", _all_modes(), ids=lambda x: getattr(x, "lane_id", None) or x.name)
def test_mode_command_is_the_retired_line_verbatim(fam, mode):
    sched, body, log = _parse(MODE_LINE[(fam.lane_id, mode.name)])
    rendered = FSJ.render(mode, FAKE)
    if fam.lane_id == "cio-event-detector":
        assert rendered.startswith(B1_LOCK)
        rendered = rendered[len(B1_LOCK):]
    assert rendered == body
    assert mode.log == log
    assert mode.old_schedule == sched


def test_every_retired_line_is_exactly_one_mode():
    assert sorted(MODE_LINE.values()) == sorted(RETIRED_LINES)
    assert {(f.lane_id, m.name) for f, m in _all_modes()} == set(MODE_LINE)


def test_locks_are_the_retired_lines_locks():
    for (lane, name), line_id in MODE_LINE.items():
        old = set(re.findall(r"/tmp/[\w.]+\.lock", RETIRED_LINES[line_id]))
        new = set(re.findall(r"/tmp/[\w.]+\.lock", FSJ.family(lane).mode(name).command))
        if lane == "cio-event-detector":
            assert old == set() and new == {"/tmp/cio_event_detector.lock"}
        else:
            assert new == old, (lane, name)   # topic-ingestion had no lock and still has none


# ── 2. time ─────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("monday", [EDT_WEEK, EST_WEEK, MONTH_WEEK], ids=["edt", "est", "month"])
@pytest.mark.parametrize("fam", FSJ.FAMILIES, ids=lambda f: f.lane_id)
def test_crontab_lines_fire_exactly_at_the_slot_minutes(fam, monday):
    for t in FSJ.minutes_of_week(monday):
        n_lines = sum(FSJ.cron_matches(e, t) for e in fam.cron_lines)
        assert n_lines <= 1, (fam.lane_id, t)
        assert bool(n_lines) == bool(FSJ.slot_modes_at(fam, t)), (fam.lane_id, t)


# ── 3. effect ───────────────────────────────────────────────────────────────────────────────────────────


def _old_effective(fam, monday):
    out = set()
    for t in FSJ.minutes_of_week(monday):
        for m in fam.modes:
            if m.name in fam.unscheduled_modes:
                continue
            if FSJ.cron_matches(m.old_schedule, t) and all(FSJ.gate_allows(g, t) for g in m.gates):
                out.add((t, m.name))
    return out


def _new_runs(fam, monday):
    return {(t, name) for t in FSJ.minutes_of_week(monday) for name in FSJ.slot_modes_at(fam, t)}


def _expected_deltas(fam, monday):
    """(old-only, new-only) runs the family declares; empty for a family without deltas."""
    old_only, new_only = set(), set()
    for d in range(7):
        day = monday + timedelta(days=d)
        if fam.lane_id == "topic-research-synthesizer" and day.weekday() in (4, 5):  # Fri, Sat
            old_only.add((day.replace(hour=21, minute=50), "reground"))
            new_only.add((day.replace(hour=21, minute=20), "reground"))
        if fam.lane_id == "catalyst-momentum-engine" and day.weekday() <= 4:
            old_only.add((day.replace(hour=9, minute=30), "premarket_scalp"))
    return old_only, new_only


@pytest.mark.parametrize("monday", [EDT_WEEK, EST_WEEK, MONTH_WEEK], ids=["edt", "est", "month"])
@pytest.mark.parametrize("fam", FSJ.FAMILIES, ids=lambda f: f.lane_id)
def test_every_effective_old_run_is_a_new_mode_run(fam, monday):
    old, new = _old_effective(fam, monday), _new_runs(fam, monday)
    old_only, new_only = _expected_deltas(fam, monday)
    assert old - new == old_only, (fam.lane_id, sorted(old - new)[:5])
    assert new - old == new_only, (fam.lane_id, sorted(new - old)[:5])


def test_holiday_delta_is_only_the_documented_one():
    """Thanksgiving week 2026: the session gate allowed L732 on the holiday (and the early-close afternoon);
    the slot table does not schedule those weekday hours. Nothing else differs."""
    fam = FSJ.family("topic-research-synthesizer")
    monday = datetime(2026, 11, 23)
    old, new = _old_effective(fam, monday), _new_runs(fam, monday)
    lost = sorted(old - new)
    assert {(t.date().isoformat(), name) for t, name in lost} >= {("2026-11-26", "synth")}
    for t, name in lost:
        if name == "synth":
            assert t.date().isoformat() in ("2026-11-26", "2026-11-27") and 4 <= t.hour <= 15, t
    # 04:20, 05:20, 12:20-15:20: the priority guard still defers 06-11 on a holiday (it checks the weekday only)
    assert len([x for x in lost if x[0].date().isoformat() == "2026-11-26"]) == 6
    assert len([x for x in lost if x[0].date().isoformat() == "2026-11-27" and x[1] == "synth"]) == 3  # 13-15:20


# ── 4. gates / fires saved ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("monday", [EDT_WEEK, EST_WEEK], ids=["edt", "est"])
def test_no_new_fire_is_a_predicted_gate_refusal_and_fires_saved(monday):
    want = {"topic-research-synthesizer": (175, 65, 108), "research-scheduler": (46, 10, 36),
            "catalyst-momentum-engine": (95, 0, 90), "topic-ingestion": (12, 5, 7), "cio-event-detector": (6, 0, 6)}
    total = 0
    for fam in FSJ.FAMILIES:
        a = FSJ.audit_week(fam, monday)
        assert (a["old_fires"], a["old_predicted_refusals"], a["new_fires"]) == want[fam.lane_id], a
        assert a["new_predicted_refusals"] == 0, a
        total += a["fires_saved"]
    assert total == 87


def test_gate_model_matches_the_wrapper_windows():
    t = datetime(2026, 10, 14, 10, 20)   # Wed regular session, guard window
    assert not FSJ.gate_allows(FSJ.GATE_NON_TRADING_HOURS, t)
    assert not FSJ.gate_allows(FSJ.GATE_LLM_PRIORITY, t)
    assert FSJ.gate_allows(FSJ.GATE_LLM_PRIORITY, t.replace(hour=12, minute=0))
    assert FSJ.gate_allows(FSJ.GATE_NON_TRADING_HOURS, t.replace(hour=16, minute=20))   # afterhours
    # 21:50 EDT Wed = 01:50Z Thu (peak); Fri 21:20 EDT = Sat 01:20Z (no UTC-weekday peak)
    assert not FSJ.gate_allows(FSJ.GATE_DEEPSEEK_OFFICIAL, datetime(2026, 10, 14, 21, 50))
    assert FSJ.gate_allows(FSJ.GATE_DEEPSEEK_OFFICIAL, datetime(2026, 10, 16, 21, 20))
    assert not FSJ.gate_allows(FSJ.GATE_DEEPSEEK_OFFICIAL, datetime(2026, 10, 14, 2, 45))   # 06:45Z Wed
    assert FSJ.gate_allows(FSJ.GATE_DEEPSEEK_OFFICIAL, datetime(2026, 10, 17, 2, 45))       # Sat


# ── 5. entry ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lane,now,modes", [
    ("topic-research-synthesizer", "2026-10-16T21:20", ("synth", "reground")),
    ("topic-research-synthesizer", "2026-10-16T21:29", ("synth", "reground")),
    ("topic-research-synthesizer", "2026-10-15T21:20", ("synth",)),
    ("topic-research-synthesizer", "2026-10-17T10:20", ("synth",)),
    ("catalyst-momentum-engine", "2026-10-14T09:00", ("premarket_scalp",)),
    ("catalyst-momentum-engine", "2026-10-14T09:30", ("market_swing",)),
    ("catalyst-momentum-engine", "2026-10-14T08:30", ("premarket_scalp",)),
    ("research-scheduler", "2026-10-14T09:05", ("holdings",)),
    ("research-scheduler", "2026-10-18T19:00", ("incubator",)),
    ("topic-ingestion", "2026-10-17T02:45", ("weekend_overnight",)),
    ("cio-event-detector", "2026-12-01T09:00", ("monthly",)),
])
def test_resolve_maps_the_clock_to_modes(lane, now, modes):
    hit = FSJ.resolve(FSJ.family(lane), datetime.fromisoformat(now))
    assert hit is not None and hit[1] == modes


@pytest.mark.parametrize("lane,now", [
    ("topic-research-synthesizer", "2026-10-16T21:50"),   # old reground minute: no slot any more
    ("topic-research-synthesizer", "2026-10-14T10:20"),   # weekday session hour
    ("research-scheduler", "2026-10-14T10:00"),           # old priority 10:00 (always DEFERRED)
    ("topic-ingestion", "2026-10-14T02:45"),              # weekday 02:45 (always PEAK_SKIP)
    ("cio-event-detector", "2026-10-14T09:00"),           # not the 1st
])
def test_cli_refuses_a_fire_outside_every_slot(lane, now, capsys):
    from scripts import run_family_slot as RFS
    assert RFS.main(["--family", lane, "--now", now, "--dry-run"]) == 2
    assert "REFUSED_NO_SLOT" in capsys.readouterr().out


def test_cli_dry_run_prints_the_exact_command_and_writes_nothing(tmp_path, monkeypatch, capsys):
    from scripts import run_family_slot as RFS
    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    rc = RFS.main(["--family", "topic-research-synthesizer", "--now", "2026-10-17T21:20", "--dry-run",
                   "--project-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    for name in ("synth", "reground"):
        cmd = FSJ.render(FSJ.family("topic-research-synthesizer").mode(name), str(tmp_path))
        assert repr(cmd) in out
    assert not state.exists() and not (tmp_path / "logs").exists()


def test_cli_real_run_executes_in_root_with_cron_env_and_writes_receipt(tmp_path, monkeypatch, capsys):
    from scripts import run_family_slot as RFS
    fake = FSJ.Family(
        lane_id="zz-test-family", design_id="T",
        modes=(FSJ.Mode("a", 'echo "a pwd=$(pwd) py=$PY root={root}"; exit 3', "logs/a.log", "x", "0 1 * * *"),
               FSJ.Mode("b", 'echo "b ran"', "logs/a.log", "y", "0 1 * * *")),
        slots=(FSJ.Slot("0 1 * * *", ("a", "b")),), cron_lines=("0 1 * * *",))
    monkeypatch.setitem(FSJ.BY_LANE, fake.lane_id, fake)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("PY", "/opt/fake/python")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.log").write_text("previous\n")
    rc = RFS.main(["--family", fake.lane_id, "--now", "2026-10-14T01:03", "--project-root", str(tmp_path)])
    assert rc == 3                                            # first failing mode's exit
    log = (tmp_path / "logs" / "a.log").read_text().splitlines()
    assert log[0] == "previous"                               # appended, never truncated
    assert log[1] == f"a pwd={tmp_path} py=/opt/fake/python root={tmp_path}"
    assert log[2] == "b ran"                                  # a failing mode does not stop the next
    receipt = json.loads((tmp_path / "state" / "data" / "runtime" / f"{fake.lane_id}_last.json").read_text())
    assert receipt["schema"] == "LaneRunReceipt@v1" and receipt["status"] == "failed" and receipt["ok_at"] is None
    assert [r["rc"] for r in receipt["summary"]["results"]] == [3, 0]
    assert '"status": "FAILED"' in capsys.readouterr().out


def test_print_crontab_is_the_candidate_line_shape(capsys):
    from scripts import run_family_slot as RFS
    for fam in FSJ.FAMILIES:
        assert RFS.main(["--family", fam.lane_id, "--print-crontab"]) == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert lines == [f"{e} cd $PROJ && $PY scripts/run_family_slot.py --family {fam.lane_id} "
                         f">> logs/run_family_slot.log 2>&1" for e in fam.cron_lines]


# ── 6. registry ─────────────────────────────────────────────────────────────────────────────────────────

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}


@pytest.mark.parametrize("fam", FSJ.FAMILIES, ids=lambda f: f.lane_id)
def test_registry_row_declares_the_family_lines(fam):
    row = ROWS[fam.lane_id]
    sched = row["scheduler"]
    assert row["state"] == "ACTIVE" and sched["kind"] == "cron"
    assert sched["schedules"] == list(fam.cron_lines)
    assert sched["expression"] == " + ".join(fam.cron_lines)
    assert sched["match"] == FSJ.registry_match(fam)
    assert [s["cron"] for s in row["family_slots"]] == [s.cron for s in fam.slots]
    for other in FSJ.FAMILIES:
        hits = [ln for ln in FSJ.crontab_lines(other) if sched["match"] in ln]
        assert len(hits) == (len(other.cron_lines) if other is fam else 0), (fam.lane_id, other.lane_id)
    # the cadence covers the longest gap between the family's fires
    fires = sorted(FSJ.fires_in_week(fam.cron_lines, EDT_WEEK) + FSJ.fires_in_week(fam.cron_lines, EDT_WEEK + timedelta(days=7)))
    gap = max((b - a).total_seconds() / 3600 for a, b in zip(fires, fires[1:]))
    assert row["expected_cadence_hours"] >= gap


@pytest.mark.parametrize("fam,mode", [(f, m) for f, m in _all_modes() if m.name not in f.unscheduled_modes
                                      and m.replaces_lane != f.lane_id],
                         ids=lambda x: getattr(x, "lane_id", None) or x.name)
def test_retired_rows_name_their_successor(fam, mode):
    row = ROWS[mode.replaces_lane]
    assert row["state"] == "RETIRED" and row["superseded_by"] == fam.lane_id
    assert row["state_reason"] and row["state_since"] and row["reason_confidence"] == "ESTABLISHED"


def test_overnight_dispatcher_shadow_row_is_untouched():
    row = ROWS["catalyst-momentum-engine-overnight"]
    assert row["state"] == "ACTIVE" and row["dispatch"]["cron"] == ["0 18,22 * * *"]
    assert "superseded_by" not in row


def test_candidate_lines_are_declared_and_retired_lines_are_not_live():
    """The candidate crontab shape: retired lines commented, family lines live -> nothing undeclared."""
    text = "\n".join([f"# RETIRED 2026-10-11 b-family x {RETIRED_LINES[k].replace('{R}', FAKE)}"
                      for k in RETIRED_LINES if k != "L381"]
                     + [RETIRED_LINES["L381"]]
                     + [ln for f in FSJ.FAMILIES for ln in FSJ.crontab_lines(f)])
    found = {"cron": discover_cron(text), "systemd": []}
    assert find_undeclared(REGISTRY, found) == []
    live = "\n".join(c["expression"] for c in found["cron"])
    for fam in FSJ.FAMILIES:
        for m in fam.modes:
            if m.replaces_lane != fam.lane_id and m.name not in fam.unscheduled_modes:
                assert str(ROWS[m.replaces_lane]["scheduler"]["match"]) not in live, m.replaces_lane
