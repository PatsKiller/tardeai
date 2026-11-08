"""LQ-20261107-1122: the market-outlook-weekly lane (Sun 20:00 + Mon 07:00 ET) runs the engine, then the brief.

Hermetic: the engine and the brief are replaced by a fake runner, the state root is tmp_path, and the records
are synthetic. No DB, no network, no send.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.market_outlook_lane as lane

ROOT = Path(__file__).resolve().parents[1]
LANE = "market-outlook-weekly"
CRON = ["0 20 * * 0", "0 7 * * 1"]
SUN_2000_ET = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)   # Sun 2026-11-08 20:00 EST
MON_0700_ET = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)  # Mon 2026-11-09 07:00 EST
TUE_0700_ET = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

RECORD = {"record_id": "outlook:2026-11-08:sunday:1", "score": -18.74, "band": "DEFENSIVE", "mode": "sunday"}


class FakeRunner:
    def __init__(self, engine_rc=0, engine_stdout=None, brief_rc=0):
        self.calls: list[list[str]] = []
        self.engine_rc = engine_rc
        self.engine_stdout = json.dumps({"record": RECORD, "problems": []}) if engine_stdout is None else engine_stdout
        self.brief_rc = brief_rc
        self.record_file_body = None

    def __call__(self, argv, timeout):
        argv = list(argv)
        self.calls.append(argv)
        if argv[1].endswith("market_outlook_evaluate.py"):
            return subprocess.CompletedProcess(argv, self.engine_rc, self.engine_stdout, "")
        if "--record-file" in argv:
            self.record_file_body = json.loads(Path(argv[argv.index("--record-file") + 1]).read_text())
        return subprocess.CompletedProcess(argv, self.brief_rc, 'LANE_OUTPUT {"lane_id": "market-outlook-weekly"}\n', "")


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """No test reaches a DB: the default lookup is a first run (no record yet) unless a test injects one."""
    monkeypatch.setattr(lane, "newest_record_id", lambda day, mode: None)


def _receipt(tmp_path: Path) -> Path:
    return tmp_path / "data" / "runtime" / f"{LANE}_last.json"


@pytest.mark.parametrize("now,mode", [
    (SUN_2000_ET, "sunday"),
    (MON_0700_ET, "monday"),
    (TUE_0700_ET, None),
    # 00:30 UTC Monday is still Sunday 19:30 in New York: the ET calendar decides, never UTC.
    (datetime(2026, 11, 9, 0, 30, tzinfo=timezone.utc), "sunday"),
])
def test_the_mode_is_read_on_the_et_calendar(now, mode):
    assert lane.mode_for(now) == mode


def test_a_dry_run_evaluates_without_apply_and_renders_that_same_record(tmp_path):
    run = FakeRunner()
    rc = lane.main(["--dry-run", "--state-root", str(tmp_path)], runner=run, now=SUN_2000_ET)
    assert rc == 0
    engine, brief = run.calls
    assert engine[engine.index("--mode") + 1] == "sunday"
    assert "--dry-run" in engine and "--apply" not in engine and "--json" in engine
    assert "--dry-run" in brief and "--deliver" not in brief
    assert run.record_file_body == RECORD
    assert not Path(brief[brief.index("--record-file") + 1]).exists(), "the temp record must not outlive the run"
    assert not _receipt(tmp_path).exists(), "a dry run writes no receipt"


def test_a_live_monday_run_applies_then_delivers_by_record_id(tmp_path):
    run = FakeRunner()
    rc = lane.main(["--deliver", "--state-root", str(tmp_path)], runner=run, now=MON_0700_ET)
    assert rc == 0
    engine, brief = run.calls
    assert engine[engine.index("--mode") + 1] == "monday"
    assert "--apply" in engine
    assert brief[brief.index("--record") + 1] == RECORD["record_id"]
    assert "--deliver" in brief and "--latest" not in brief
    assert brief[brief.index("--state-root") + 1] == str(tmp_path)


def test_the_brief_exit_code_is_the_lane_exit_code(tmp_path):
    assert lane.main(["--deliver", "--state-root", str(tmp_path)], runner=FakeRunner(brief_rc=1),
                     now=SUN_2000_ET) == 1


def test_an_engine_refusal_is_a_refused_live_run_with_a_receipt_and_no_send(tmp_path, capsys):
    out = json.dumps({"record": RECORD, "problems": ["record store missing"]})
    run = FakeRunner(engine_rc=2, engine_stdout=out)
    rc = lane.main(["--deliver", "--state-root", str(tmp_path)], runner=run, now=SUN_2000_ET)
    assert rc == 3
    assert len(run.calls) == 1, "the brief must not run on a refused record"
    body = json.loads(_receipt(tmp_path).read_text())
    assert body["produced_count"] == 0 and body["skipped_reasons"] == {"refused": 1}
    assert "record store missing" in (body.get("error") or "")
    assert "LANE_OUTPUT" in capsys.readouterr().err, "lane_output.emit writes the graded line to stderr"


def test_engine_output_that_is_not_a_record_is_refused(tmp_path):
    run = FakeRunner(engine_rc=3, engine_stdout="")
    assert lane.main(["--deliver", "--state-root", str(tmp_path)], runner=run, now=SUN_2000_ET) == 3
    assert len(run.calls) == 1
    assert json.loads(_receipt(tmp_path).read_text())["skipped_reasons"] == {"refused": 1}


def test_an_off_schedule_day_is_refused_unless_a_mode_is_named(tmp_path):
    run = FakeRunner()
    assert lane.main(["--dry-run", "--state-root", str(tmp_path)], runner=run, now=TUE_0700_ET) == 2
    assert run.calls == []
    assert lane.main(["--dry-run", "--mode", "daily", "--state-root", str(tmp_path)], runner=run,
                     now=TUE_0700_ET) == 0


def _allow_row():
    rows = [r for r in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]
            if r["lane_id"] == LANE]
    assert len(rows) == 1
    return rows[0]


def test_the_allowlist_row_runs_the_lane_wrapper_dry_first():
    row = _allow_row()
    assert row["command"] == ["$PY", "$CODE_ROOT/scripts/market_outlook_lane.py"]
    assert row["dry_run_arg"] == ["--dry-run"] and row["live_arg"] == ["--deliver"]
    assert row["output_receipt"] == "v2"
    assert row["output_signal"] == lane.RECEIPT_REL
    assert row["timeout_s"] > lane.ENGINE_TIMEOUT_S + lane.BRIEF_TIMEOUT_S
    assert (ROOT / "scripts/market_outlook_lane.py").exists()


def test_the_brief_writes_the_receipt_the_allowlist_grades():
    import scripts.market_outlook_brief as brief

    assert brief.LANE_ID == LANE and brief.RECEIPT_REL == lane.RECEIPT_REL


def test_the_effect_key_carries_the_sunday_and_monday_slots_staged():
    key = json.loads((ROOT / "config/n8n_effect_keys.json").read_text())["lanes"][LANE]
    assert key["schedule"] == CRON and key["slot_tz"] == "America/New_York"
    assert key["n8n_claim"] is False and key["cron_claim"] is False, "staged: no owner row is needed yet"


# ── LQ-20261107-1177: a live re-fire for the same ET day + mode reuses the record, never mints :<n+1> ──────────
class FakeLookup:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def __call__(self, day, mode):
        self.calls.append((day, mode))
        if self.exc:
            raise self.exc
        return self.result


def test_a_live_refire_skips_the_engine_and_delivers_the_existing_record(tmp_path, capsys):
    run, look = FakeRunner(), FakeLookup(result="outlook:2026-11-08:sunday:1")
    rc = lane.main(["--deliver", "--state-root", str(tmp_path)], runner=run, now=SUN_2000_ET, lookup=look)
    assert rc == 0
    assert look.calls == [("2026-11-08", "sunday")], "the ET day (01:00 UTC Mon is Sun 20:00 ET) and the mode"
    assert len(run.calls) == 1, "the engine must not run: it would mint outlook:2026-11-08:sunday:2"
    (brief,) = run.calls
    assert brief[1].endswith("market_outlook_brief.py")
    assert brief[brief.index("--record") + 1] == "outlook:2026-11-08:sunday:1"
    assert "--deliver" in brief and "--record-file" not in brief
    assert "engine skipped" in capsys.readouterr().out


def test_a_first_live_run_with_no_record_runs_the_engine_as_before(tmp_path):
    run, look = FakeRunner(), FakeLookup(result=None)
    rc = lane.main(["--deliver", "--state-root", str(tmp_path)], runner=run, now=MON_0700_ET, lookup=look)
    assert rc == 0
    assert look.calls == [("2026-11-09", "monday")]
    engine, brief = run.calls
    assert engine[1].endswith("market_outlook_evaluate.py") and "--apply" in engine
    assert brief[brief.index("--record") + 1] == RECORD["record_id"]


def test_a_failed_lookup_refuses_rather_than_minting_a_duplicate(tmp_path):
    run, look = FakeRunner(), FakeLookup(exc=RuntimeError("connection refused"))
    rc = lane.main(["--deliver", "--state-root", str(tmp_path)], runner=run, now=SUN_2000_ET, lookup=look)
    assert rc == 3 and run.calls == []
    body = json.loads(_receipt(tmp_path).read_text())
    assert body["skipped_reasons"] == {"refused": 1} and "record lookup failed" in body["error"]


def test_a_dry_run_never_looks_up_the_record_store(tmp_path):
    run, look = FakeRunner(), FakeLookup(exc=AssertionError("a dry run must not read the record store"))
    assert lane.main(["--dry-run", "--state-root", str(tmp_path)], runner=run, now=SUN_2000_ET, lookup=look) == 0
    assert look.calls == [] and len(run.calls) == 2


def test_the_newest_record_is_the_largest_numeric_suffix(monkeypatch):
    import scripts.lib.market_outlook.sources as sources

    class Cur:
        def execute(self, sql, params):
            assert sql.lstrip().upper().startswith("SELECT") and params == ["outlook:2026-11-08:sunday:%"]

        def fetchall(self):
            return [("outlook:2026-11-08:sunday:9",), ("outlook:2026-11-08:sunday:10",),
                    ("outlook:2026-11-08:sunday:2",)]

        def close(self):
            pass

    class Conn:
        closed = False

        def cursor(self):
            return Cur()

        def close(self):
            Conn.closed = True

    monkeypatch.undo()  # the real lookup, with only the connection faked
    monkeypatch.setattr(sources, "_app_conn", lambda: Conn())
    assert lane.newest_record_id("2026-11-08", "sunday") == "outlook:2026-11-08:sunday:10"
    assert Conn.closed
