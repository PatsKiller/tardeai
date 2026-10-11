"""heartbeat-watch lane (scripts/heartbeat_watch.py): health-plane dead-man, phase 1 (2026-10-11).

Hermetic: synthetic registry rows, tmp_path state roots, a pinned clock. Covers:
* FRESH / LATE / STALE / EXPECTED_SILENT / UNVERIFIABLE classification at 2x cadence;
* cron rows judged against the latest scheduled fire, so a weekday-only line is not STALE on a Sunday;
  active_days honoured in America/New_York;
* the breach plan: OPEN once, re-emitted after 24 h, CLEARED when fresh again, nothing for LATE;
* --dry-run writes nothing (state tree byte-identical before and after); a live run writes STALE_2X rows and a
  LaneRunReceipt@v1 whose ok_at advances only on success;
* the fan-in reads STALE_2X as P1 and a later CLEARED row closes it;
* the registry row and allowlist entry agree (shadow, dry_run, monitor, priority 0, no live_arg);
* the lane sends nothing.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import heartbeat_watch as H  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402

# Sunday 2026-10-11 10:00 America/New_York (EDT, UTC-4)
SUNDAY = datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)


def _row(lane="health-tick", *, kind="systemd", expr="tradeai-health-tick.timer", cad=0.0833, state="ACTIVE",
         path=None, **extra):
    r = {"lane_id": lane, "state": state, "scheduler": {"kind": kind, "expression": expr},
         "expected_cadence_hours": cad,
         "output_signal": {"kind": "file_mtime", "path": path or f"data/runtime/{lane}_last.json"}}
    r.update(extra)
    return r


def _obs(at):
    return {"last_output_at": at, "readable": True, "detail": "x"}


# ── classification ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("age_min,verdict", [(3, "FRESH"), (7, "LATE"), (11, "STALE")])
def test_cadence_row_fresh_late_stale_at_2x(age_min, verdict):
    v = H.classify(_row(cad=5 / 60), _obs(SUNDAY - timedelta(minutes=age_min)), SUNDAY)
    assert v["verdict"] == verdict and v["basis"].startswith("cadence:")


def test_no_output_is_stale_and_unreadable_is_unverifiable():
    assert H.classify(_row(), _obs(None), SUNDAY)["verdict"] == "STALE"
    v = H.classify(_row(), {"last_output_at": None, "readable": False, "detail": "bad json"}, SUNDAY)
    assert v["verdict"] == "UNVERIFIABLE"
    assert H.classify(_row(output_signal={"kind": "none"}), _obs(None), SUNDAY)["verdict"] == "UNVERIFIABLE"


def test_paused_row_is_expected_silent():
    v = H.classify(_row(state="PAUSED"), _obs(None), SUNDAY)
    assert v["verdict"] == "EXPECTED_SILENT" and v["basis"] == "registry_state:PAUSED"


def test_active_days_exclude_sunday_in_new_york():
    weekdays = _row(active_days=[0, 1, 2, 3, 4])
    assert H.classify(weekdays, _obs(None), SUNDAY)["verdict"] == "EXPECTED_SILENT"
    # 2026-10-11 02:00Z is still Saturday 22:00 in New York: Saturday is inactive too
    assert H.classify(weekdays, _obs(None), datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc))["verdict"] == \
        "EXPECTED_SILENT"
    monday = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)
    assert H.classify(weekdays, _obs(monday - timedelta(minutes=1)), monday)["verdict"] == "FRESH"


def test_weekday_cron_row_on_sunday_is_judged_by_fridays_last_fire():
    row = _row("weekday-lane", kind="cron", expr="*/5 9-16 * * 1-5", cad=5 / 60)
    friday_last_fire = datetime(2026, 10, 9, 20, 55, tzinfo=timezone.utc)          # Fri 16:55 EDT
    fresh = H.classify(row, _obs(friday_last_fire + timedelta(minutes=1)), SUNDAY)
    assert fresh["verdict"] == "FRESH" and fresh["basis"].startswith("cron:")
    assert fresh["due_since"] == friday_last_fire.isoformat()
    stale = H.classify(row, _obs(datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)), SUNDAY)
    assert stale["verdict"] == "STALE"


def test_every_five_minute_cron_row_uses_its_schedule():
    row = _row("incident-notifier", kind="cron", expr="*/5 * * * *", cad=0.1)
    now = datetime(2026, 10, 11, 14, 2, tzinfo=timezone.utc)
    # due slot = last fire <= now - 300 s = 13:55; 2x deadline = last fire <= 13:51 = 13:50
    assert H.classify(row, _obs(datetime(2026, 10, 11, 13, 56, tzinfo=timezone.utc)), now)["verdict"] == "FRESH"
    assert H.classify(row, _obs(datetime(2026, 10, 11, 13, 52, tzinfo=timezone.utc)), now)["verdict"] == "LATE"
    assert H.classify(row, _obs(datetime(2026, 10, 11, 13, 40, tzinfo=timezone.utc)), now)["verdict"] == "STALE"


# ── breach plan ─────────────────────────────────────────────────────────────────────────────────────

def _v(lane, verdict):
    return {"lane_id": lane, "verdict": verdict, "last_output_at": None, "expected_by": None, "basis": "t"}


def _own(lane, state, at):
    return {"kind": "STALE_2X", "lane_id": lane, "state": state, "detected_at": at.isoformat(),
            "breach_id": f"br_{state}", "evidence": {"watcher": "heartbeat-watch"}}


def test_plan_opens_once_reemits_after_24h_and_clears_when_fresh():
    first = H.plan_rows([_v("a", "STALE")], {}, SUNDAY)
    assert [(r["lane_id"], r["state"], r["kind"], r["level"]) for r in first] == [("a", "OPEN", "STALE_2X", 2)]
    assert H.plan_rows([_v("a", "STALE")], {"a": _own("a", "OPEN", SUNDAY - timedelta(hours=1))}, SUNDAY) == []
    again = H.plan_rows([_v("a", "STALE")], {"a": _own("a", "OPEN", SUNDAY - timedelta(hours=25))}, SUNDAY)
    assert [r["state"] for r in again] == ["OPEN"]
    cleared = H.plan_rows([_v("a", "FRESH")], {"a": _own("a", "OPEN", SUNDAY - timedelta(hours=1))}, SUNDAY)
    assert [r["state"] for r in cleared] == ["CLEARED"] and cleared[0]["evidence"]["clears"] == "br_OPEN"
    assert H.plan_rows([_v("a", "LATE")], {"a": _own("a", "OPEN", SUNDAY)}, SUNDAY) == []
    assert H.plan_rows([_v("a", "FRESH")], {"a": _own("a", "CLEARED", SUNDAY)}, SUNDAY) == []
    assert H.plan_rows([_v("a", "FRESH")], {}, SUNDAY) == []


def test_last_own_rows_ignores_detector_rows():
    rows = [{"kind": "STALE_2X", "lane_id": "a", "state": "OPEN", "evidence": {}},          # not ours
            {"kind": "NO_OUTPUT", "lane_id": "a", "state": "OPEN", "evidence": {"watcher": "heartbeat-watch"}},
            _own("a", "OPEN", SUNDAY), _own("a", "CLEARED", SUNDAY)]
    assert H.last_own_rows(rows)["a"]["state"] == "CLEARED"


# ── run: dry run writes nothing; live writes rows and the receipt ───────────────────────────────────

def _world(tmp_path, *, stale_lane="incident-notifier", drop=None):
    reg_rows = [_row(lid, cad=5 / 60) for lid in H.WATCH_SET if lid != drop]
    reg = tmp_path / "code" / "config" / "lane_registry.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(json.dumps({"lanes": reg_rows}))
    state = tmp_path / "state"
    (state / "data" / "runtime").mkdir(parents=True)
    (state / "data" / "runtime" / "supervisor_breaches.jsonl").write_text(
        json.dumps({"kind": "NO_OUTPUT", "lane_id": "other", "state": "OPEN"}) + "\n")
    times = {lid: SUNDAY - timedelta(minutes=1) for lid in H.WATCH_SET}
    if stale_lane:
        times[stale_lane] = SUNDAY - timedelta(hours=2)
    by_path = {f"data/runtime/{lid}_last.json": times[lid] for lid in H.WATCH_SET}
    return reg, state, (lambda sig: _obs(by_path.get(sig.get("path"))))


def _snapshot(d: Path) -> dict[str, str]:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in d.rglob("*") if p.is_file()}


def test_dry_run_writes_nothing(tmp_path, capsys):
    reg, state, observe = _world(tmp_path)
    before = _snapshot(tmp_path)
    rc = H.run(registry_path=reg, state_root=state, now=SUNDAY, dry_run=True, observe=observe)
    assert rc == 0 and _snapshot(tmp_path) == before
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "supervisor_breaches.jsonl +1 rows" in out and "STALE" in out


def test_dry_run_flag_through_main_writes_nothing(tmp_path, capsys):
    reg, state, _ = _world(tmp_path, stale_lane=None)
    before = _snapshot(tmp_path)
    rc = H.main(["--dry-run", "--root", str(reg.parents[1]), "--state-root", str(state), "--now", SUNDAY.isoformat()])
    assert rc == 0 and _snapshot(tmp_path) == before          # every signal absent -> STALE, still nothing written
    assert "DRY-RUN" in capsys.readouterr().out


def test_live_run_records_stale_once_then_clears(tmp_path):
    reg, state, observe = _world(tmp_path)
    led = state / "data" / "runtime" / "supervisor_breaches.jsonl"
    receipt = state / "data" / "runtime" / "heartbeat-watch_last.json"
    assert H.run(registry_path=reg, state_root=state, now=SUNDAY, dry_run=False, observe=observe) == 0
    rows = [json.loads(x) for x in led.read_text().splitlines()]
    assert rows[0]["kind"] == "NO_OUTPUT"                     # the detector's row is untouched
    assert [(r["lane_id"], r["state"]) for r in rows[1:]] == [("incident-notifier", "OPEN")]
    doc = json.loads(receipt.read_text())
    assert doc["schema"] == "LaneRunReceipt@v1" and doc["status"] == "ok" and doc["ok_at"]
    assert doc["summary"]["stale"] == ["incident-notifier"]
    # a second tick inside 24 h adds nothing
    H.run(registry_path=reg, state_root=state, now=SUNDAY + timedelta(minutes=5), dry_run=False, observe=observe)
    assert len(led.read_text().splitlines()) == 2
    # the lane recovers -> one CLEARED row
    _, _, fresh = _world(tmp_path / "again", stale_lane=None)
    H.run(registry_path=reg, state_root=state, now=SUNDAY, dry_run=False, observe=fresh)
    last = json.loads(led.read_text().splitlines()[-1])
    assert (last["lane_id"], last["state"], last["kind"]) == ("incident-notifier", "CLEARED", "STALE_2X")


def test_missing_watch_set_row_fails_and_does_not_advance_ok_at(tmp_path):
    reg, state, observe = _world(tmp_path, stale_lane=None, drop="health-tick")
    rc = H.run(registry_path=reg, state_root=state, now=SUNDAY, dry_run=False, observe=observe)
    doc = json.loads((state / "data" / "runtime" / "heartbeat-watch_last.json").read_text())
    assert rc == 1 and doc["status"] == "failed" and doc["ok_at"] is None
    assert doc["summary"]["missing_rows"] == ["health-tick"]


def test_unreadable_registry_exits_1(tmp_path):
    state = tmp_path / "state"
    rc = H.run(registry_path=tmp_path / "absent.json", state_root=state, now=SUNDAY, dry_run=True)
    assert rc == 1 and not state.exists()


# ── fan-in: STALE_2X is P1 and CLEARED closes it ────────────────────────────────────────────────────

def _quiet_fanin(monkeypatch):
    for var in ("TRADEAI_FANIN_LANE_REGISTRY", "TRADEAI_FANIN_RUNS", "TRADEAI_FANIN_RELAY", "TRADEAI_FANIN_DLQ",
                "TRADEAI_FANIN_GOVERNANCE", "TRADEAI_FANIN_DIAGNOSIS", "TRADEAI_ALERT_PATH_WATCH", "TRADEAI_FANIN_WFERR"):
        monkeypatch.setenv(var, "0")
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    monkeypatch.setattr(fanin, "_scalp_lane_findings", lambda root, now: [])
    monkeypatch.setattr(fanin, "_scalp_cycle_findings", lambda root, now: [])


def test_fanin_reads_stale_2x_as_p1_and_cleared_closes_it(tmp_path, monkeypatch):
    _quiet_fanin(monkeypatch)
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    led = rt / "supervisor_breaches.jsonl"
    opened = H.plan_rows([_v("incident-notifier", "STALE")], {}, SUNDAY)
    det = {"kind": "NO_OUTPUT", "lane_id": "x", "state": "OPEN", "detected_at": SUNDAY.isoformat(), "evidence": {}}
    H.append_rows(led, [det] + opened)
    found = {f["item"]: f["severity"] for f in fanin.collect(tmp_path, SUNDAY, prev={}) if f["source"] == "breach_detector"}
    assert found == {"incident-notifier:STALE_2X": "P1", "x:NO_OUTPUT": "P2"}
    cleared = H.plan_rows([_v("incident-notifier", "FRESH")], H.last_own_rows(opened), SUNDAY + timedelta(minutes=5))
    H.append_rows(led, cleared)
    found = {f["item"] for f in fanin.collect(tmp_path, SUNDAY + timedelta(minutes=6), prev={})
             if f["source"] == "breach_detector"}
    assert found == {"x:NO_OUTPUT"}


# ── registry row, allowlist entry, no sends ─────────────────────────────────────────────────────────

def test_registry_row_and_allowlist_entry_agree():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r["lane_id"] == "heartbeat-watch")
    al = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    entry = next(e for e in al["lanes"] if e["lane_id"] == "heartbeat-watch")
    s, d = row["scheduler"], row["dispatch"]
    assert (s["kind"], s["expression"], s["stage"]) == ("n8n", "dispatcher", "shadow")
    assert (d["mode"], d["class"], d["priority"], d["retry_policy"]) == ("dry_run", "monitor", 0, "transient-2")
    assert row["output_signal"] == {"kind": "json_key", "path": "data/runtime/heartbeat-watch_last.json", "key": "ok_at"}
    assert entry["output_signal"] == row["output_signal"]["path"]
    assert entry["command"] == ["$PY", "scripts/heartbeat_watch.py"] and (ROOT / entry["command"][1]).exists()
    assert entry["dry_run_arg"] == ["--dry-run"] and entry["live_arg"] is None and entry["lock_kind"] == "flock"
    assert entry["env_allowlist_mode"] == "report" and entry["env_report_reason"]
    assert not any(b in n for n in entry["env_names"] for b in ("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR",
                                                                 "TELEGRAM", "PASSWORD", "TOKEN", "KEY"))
    from scripts.lib import lane_dispatch

    ok, why = lane_dispatch.dispatch_eligible(row, allowlist_argv={"heartbeat-watch": " ".join(entry["command"])})
    assert ok, why
    assert set(H.WATCH_SET) <= {r["lane_id"] for r in reg["lanes"]}


def test_lane_sends_nothing_and_touches_no_broker():
    src = (ROOT / "scripts" / "heartbeat_watch.py").read_text()
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]                            # skip the module docstring
    for token in ("telegram", "send_", "smtplib", "requests", "urllib", "subprocess", "psycopg", "alpaca", "schwab"):
        assert token not in body.lower(), token


# ── the first dispatcher row exposed two tooling bugs (fixed 2026-10-11) ────────────────────────────

def _dispatcher_reg():
    return {"lanes": [{"lane_id": "heartbeat-watch", "state": "ACTIVE",
                       "scheduler": {"kind": "n8n", "expression": "dispatcher", "match": "scripts/heartbeat_watch.py"}}]}


def test_dispatcher_expression_declares_no_crontab_line():
    from scripts.lib import lane_registry as lr
    from scripts import reconcile_lane_registry as R

    line = "30 8,16 * * * cd $PROJ && $PY scripts/alert_dispatcher_unified.py >> logs/alert_dispatcher.log 2>&1"
    und = lr.find_undeclared(_dispatcher_reg(), {"cron": [{"kind": "cron", "expression": line}]}, n8n_known_ids=[])
    assert [u["expression"] for u in und if u["kind"] == "cron"] == [line]
    assert R.declarations(_dispatcher_reg()["lanes"][0]) == ["scripts/heartbeat_watch.py"]
    assert R.line_mapping(_dispatcher_reg(), [line]) == {line: []}


def test_dispatcher_row_is_live_when_the_dispatcher_workflow_is_active():
    from scripts.lib import lane_registry as lr

    on = {"n8n": [{"expression": "tradeai-dispatcher"}]}
    off = {"n8n": [{"expression": "722fac0e043ea5c4"}]}
    assert lr.find_inactive_n8n_rows(_dispatcher_reg(), on) == []
    assert [r["lane_id"] for r in lr.find_inactive_n8n_rows(_dispatcher_reg(), off)] == ["heartbeat-watch"]
