"""SINCE_CLOSE_LANE_REGISTRATION_20261108 — the since-close lanes are registered LIVE, and their cadence table is data.

LQ-20261107-1261 registered the "Since last close" home-card producer (cc-sonnet-3, LQ-20261107-1253 head
0d593b2bc) as one SHADOW n8n dispatcher lane. LQ-20261107-1279 (operator GO 2026-11-08 19:01 ET) activates it
with a cadence that replaced the 18:05 ET amendment table: a forced rebuild every 2 h on trading days and every
6 h at weekends, plus a cheap ``--if-changed`` check every 15 min between rebuilds. One fire carries one argv, so
the conditional half is a second lane, ``since-close-check``, on the same script. Nothing about that is provable by
reading the JSON — a row that names the wrong script, a cadence list that fires when nobody wrote down, or an
allowlist entry the executor would refuse all read the same in a diff. This module pins the four files to each
other and to the script:

* both rows are dispatcher rows on the real script, stage canary and dispatch mode live, and both pass
  ``lane_dispatch.validate_dispatch_block``;
* the cadence tables are ``dispatch.cron``, one expression per row, and the fire sets are asserted against an
  independently computed week — the rebuild fires 12 times a weekday and 4 times a weekend day, the check fires at
  :15/:30/:45 only (every weekday, plus Sunday 20:00-23:45 since LQ-20261107-1304), and the two never land in the same
  minute (the property that lets them take distinct locks);
* each allowlist entry is accepted by the executor's own ``validate_entry``: the rebuild's ``live_arg`` is
  ``--apply`` against persistent-state with NO ``--llm`` (the operator keeps the model off), the check's is
  ``--apply --if-changed``, and the locks are distinct;
* the registry ``output_signal``, the allowlist ``output_signal`` and the freshness contract name the same file;
* each health contract's stage is a copy of its registry row's stage, each is REVIEWED (a DRAFT at canary is
  DRAFT_AT_LIVE_STAGE), and neither exempts a lock skip — the LQ-20261107-1284 lesson, where an exemption written
  for a cron twin that no longer exists would have turned a dead lane green;
* the live argv is emulated in an isolated state root (a tmp PROJECT_ROOT): ``--apply`` writes the snapshot with no
  model call, an unchanged ``--apply --if-changed`` fire writes nothing, and a change writes — proving the two
  rows' argv, not just their shape.

Hermetic: synthetic ZZ* symbols, a stub DB cursor, a tmp state root. No network, no psycopg2, no production state.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import ci_gates as CG  # noqa: E402
from scripts.lib import cron_schedule as CRON  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib import n8n_health_contracts as HC  # noqa: E402
from scripts.lib.n8n_output_verdict import validate_expected_output  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
import since_close_snapshot as SCS  # noqa: E402

LID = "since-close-snapshot"     # the forced rebuild: --apply every 2 h (weekdays) / 6 h (weekends)
CID = "since-close-check"        # the conditional check: --apply --if-changed at :15/:30/:45
FKEY = "pfm.since_close_snapshot"
SNAPSHOT = "data/portfolios/state/since_close_latest.json"
STATE_DIR_ARG = "$STATE_ROOT/data/portfolios/state"  # the executor expands $STATE_ROOT (TRADEAI_STATE_ROOT)
TZ = "America/New_York"
ET = ZoneInfo(TZ)

REG = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
ALLOW = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
HEALTH = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REG["lanes"]}
ROW = ROWS[LID]
CHECK_ROW = ROWS[CID]
ENTRY = {e["lane_id"]: e for e in ALLOW["lanes"]}[LID]
CHECK_ENTRY = {e["lane_id"]: e for e in ALLOW["lanes"]}[CID]
FRESH = {c["key"]: c for c in REG["freshness_contracts"]}[FKEY]
CONTRACT = {c["id"]: c for c in HEALTH["contracts"]}[LID]
CHECK_CONTRACT = {c["id"]: c for c in HEALTH["contracts"]}[CID]


# ── the rows ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("row", [ROW, CHECK_ROW], ids=["rebuild", "check"])
def test_each_row_is_a_live_canary_dispatcher_row_for_the_real_script(row):
    sched = row["scheduler"]
    assert sched["kind"] == "n8n"
    assert sched["expression"] == "dispatcher"  # never the workflow id (AGENTS 23.11)
    assert sched["stage"] == "canary"
    assert sched["timezone"] == TZ
    assert sched["match"] == "scripts/since_close_snapshot.py"
    assert (ROOT / sched["match"]).is_file(), sched["match"]
    assert row["dispatch"]["mode"] == "live"  # canary without a live mode would be a shadow in disguise
    assert row["dispatch"]["tz"] == TZ
    assert row["state"] == "ACTIVE" and row["state_since"] and row["state_reason"]


def test_both_rows_run_the_same_script_and_say_why_they_are_two():
    """One fire carries one argv: the row that must be forced carries --apply, the conditional row --if-changed."""
    assert ROW["scheduler"]["match"] == CHECK_ROW["scheduler"]["match"]
    assert "--if-changed" not in ENTRY["live_arg"] and "--if-changed" in CHECK_ENTRY["live_arg"]
    assert "--apply" in ENTRY["live_arg"] and "--apply" in CHECK_ENTRY["live_arg"]
    assert "two rows" in ROW["note"] or "sibling lane" in ROW["note"]
    assert "since-close-check" in ROW["state_reason"]


@pytest.mark.parametrize("row", [ROW, CHECK_ROW], ids=["rebuild", "check"])
def test_the_dispatch_block_passes_the_lane_dispatch_gate(row):
    policies = json.loads((ROOT / "config/n8n_retry_policies.json").read_text(encoding="utf-8"))["policies"]
    known = [r["lane_id"] for r in REG["lanes"]]
    assert LD.validate_dispatch_block(row, known_lane_ids=known, retry_policy_names=list(policies)) == []
    assert LD.dispatch_eligible(row)[0] is True


@pytest.mark.parametrize("row", [ROW, CHECK_ROW], ids=["rebuild", "check"])
def test_each_registry_row_is_structurally_valid_and_carries_the_snapshot_signal(row):
    assert LR.validate_row(row) == []
    assert row["output_signal"]["kind"] == "json_key"
    assert row["output_signal"]["path"] == SNAPSHOT
    assert row["output_signal"]["key"] == "generated_at"


def test_the_check_row_says_its_cadence_is_the_write_gap_not_the_fire_spacing():
    """0.25 h would read a healthy quiet lane as stale on every clock; 6.0 h is the longest legitimate write gap."""
    assert CHECK_ROW["expected_cadence_hours"] == ROW["expected_cadence_hours"] == 6.0
    assert "0.25 h cadence here would read the shared file as stale" in CHECK_ROW["output_signal"]["evidence_ref"]


# ── the cadence tables (data, and asserted against an independently computed week) ──────────────────────────────
WEEK_START = datetime(2026, 11, 9, 0, 0, tzinfo=ET)  # Monday; US DST ended 2026-11-01, so no offset change
WEEK_END = WEEK_START + timedelta(days=7)


def _fired(row) -> set[str]:
    out: set[str] = set()
    # fires_between is (start, end]: bracket the week with one second either side so Monday 00:00 is inside it and
    # the next Monday's 00:00 is not.
    for expr in row["dispatch"]["cron"]:
        for f in CRON.fires_between(expr, WEEK_START - timedelta(seconds=1), WEEK_END - timedelta(seconds=1), TZ):
            out.add(f.slot_local)
    return out


def _slot(day, hh: int, mm: int) -> str:
    return f"{day.strftime('%Y%m%d')}T{hh:02d}{mm:02d}"


def test_the_rebuild_is_forced_every_2h_on_trading_days_and_every_6h_at_weekends():
    """LQ-20261107-1279: 'Trading days: a forced rebuild every 2 h. Weekends and holidays: every 6 h.' Written out
    by hand, so extending the cadence means adding a line here and an expression in dispatch.cron — never one
    without the other. The rebuild is forced at weekends too (not --if-changed) so the card's UPDATED stamp and the
    freshness contract advance every 6 h instead of going stale for 48 h."""
    expected: set[str] = set()
    for d in range(7):
        day = (WEEK_START + timedelta(days=d)).date()
        hours = range(0, 24, 2) if day.weekday() < 5 else (0, 6, 12, 18)
        expected |= {_slot(day, h, 0) for h in hours}
    got = _fired(ROW)
    assert got == expected
    assert len(got) == 5 * 12 + 2 * 4  # 12 fires on a trading day, 4 on a weekend day


def test_the_check_fires_every_quarter_hour_except_the_rebuild_minute():
    """LQ-20261107-1279: 'between those, a cheap --if-changed check every 15 min'. Between rebuilds at :00, so
    :15/:30/:45 — 72 fires a weekday. LQ-20261107-1304 adds 12 Sunday fires (20:00-23:45) so a Sunday-night
    print reaches the card the same evening instead of waiting for Monday 00:00; Saturday still has none."""
    expected: set[str] = set()
    for d in range(5):
        day = (WEEK_START + timedelta(days=d)).date()
        expected |= {_slot(day, h, m) for h in range(24) for m in (15, 30, 45)}
    sunday = (WEEK_START + timedelta(days=6)).date()  # WEEK_START is a Monday; cron day 0 = Sunday
    expected |= {_slot(sunday, h, m) for h in range(20, 24) for m in (15, 30, 45)}
    got = _fired(CHECK_ROW)
    assert got == expected
    assert len(got) == 5 * 72 + 12


def test_the_sunday_check_slot_keeps_sunday_an_active_day():
    """A lane that fires on Sunday but lists no Sunday in active_days is excused as SILENT_OK by heartbeat_watch
    (0=Mon..6=Sun), so a dead Sunday fire would never be graded. The expression and the day list move together."""
    assert 6 in CHECK_ROW["active_days"]
    assert set(CHECK_ROW["active_days"]) <= set(range(7))


def test_the_two_rows_never_land_in_the_same_minute():
    """The property that lets them take distinct locks: a fire is killed at timeout_s 300, so a disjoint schedule
    is strictly more than 'usually separate' — neither can still be running when the other starts."""
    both = _fired(ROW) & _fired(CHECK_ROW)
    assert both == set(), sorted(both)[:5]


@pytest.mark.parametrize("row", [ROW, CHECK_ROW], ids=["rebuild", "check"])
def test_the_cron_list_fits_the_dispatcher_slot_cap(row):
    assert len(row["dispatch"]["cron"]) <= LD.DISPATCH_CRON_MAX_SLOTS  # 8
    assert len(set(row["dispatch"]["cron"])) == len(row["dispatch"]["cron"])


# ── the allowlist entries ───────────────────────────────────────────────────────────────────────────────────────
def test_the_rebuild_entry_applies_against_persistent_state_and_never_spends():
    assert X.validate_entry(ENTRY) is None, X.validate_entry(ENTRY)
    assert ENTRY["command"] == ["$PY", "scripts/since_close_snapshot.py"]
    assert (ROOT / ENTRY["command"][1]).is_file()
    # The script has no --dry-run flag (LQ-1253): its default IS the dry run, so dry_run_arg is [] not null.
    assert ENTRY["dry_run_arg"] == []
    assert ENTRY["live_arg"] == ["--apply", "--state-dir", STATE_DIR_ARG]
    # The operator's other word: keep --llm OFF until since_close_card is a row in llm_process_registry.
    assert "--llm" not in ENTRY["live_arg"] and "llm_route" not in ENTRY
    assert ENTRY["lock"] == "/tmp/since_close_snapshot.lock"
    assert ENTRY["lock_kind"] == "flock"
    assert not ENTRY["lock"].endswith(".dryrun")
    assert ENTRY["timeout_s"] == 300
    assert ENTRY["output_signal"] == SNAPSHOT == ROW["output_signal"]["path"]
    assert "DB_PASSWORD" in ENTRY["env_names"] and not any(
        n.startswith(("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR")) for n in ENTRY["env_names"]
    )


def test_the_check_entry_applies_if_changed_with_its_own_lock():
    assert X.validate_entry(CHECK_ENTRY) is None, X.validate_entry(CHECK_ENTRY)
    assert CHECK_ENTRY["command"] == ENTRY["command"]
    assert CHECK_ENTRY["dry_run_arg"] == []
    assert CHECK_ENTRY["live_arg"] == ["--apply", "--if-changed", "--state-dir", STATE_DIR_ARG]
    assert "--llm" not in CHECK_ENTRY["live_arg"]
    assert CHECK_ENTRY["lock"] == "/tmp/since_close_snapshot_check.lock"
    assert CHECK_ENTRY["lock"] != ENTRY["lock"]
    assert CHECK_ENTRY["lock_kind"] == "flock"
    assert CHECK_ENTRY["timeout_s"] == ENTRY["timeout_s"] == 300  # < the 15-min slot spacing
    assert CHECK_ENTRY["output_signal"] == SNAPSHOT


def test_the_state_dir_is_the_state_root_token_not_a_home_path():
    """The operator named an absolute path under their home; git gets the token instead. $STATE_ROOT is expanded by
    the executor (resolve_token) to TRADEAI_STATE_ROOT, whose default is <home>/trade-ai-releases/persistent-state —
    the same directory the operator named, resolved at run time (and the repo's PII gate refuses the literal)."""
    for entry in (ENTRY, CHECK_ENTRY):
        toks = list(entry["command"]) + list(entry["live_arg"])
        assert not any(t.startswith("/home/") for t in toks), toks
        assert toks[toks.index("--state-dir") + 1] == STATE_DIR_ARG
    resolved = X.resolve_token(STATE_DIR_ARG, env={}, state_root=Path("/srv/persistent-state"), code_root=ROOT)
    assert resolved == "/srv/persistent-state/data/portfolios/state"
    assert str(Path.home() / "trade-ai-releases" / "persistent-state").endswith("/trade-ai-releases/persistent-state")


def test_live_mode_takes_the_declared_lock_and_a_dry_run_the_dryrun_lock():
    for entry in (ENTRY, CHECK_ENTRY):
        assert X.lock_path_for(entry, "dry_run").endswith(".dryrun")
        assert X.lock_path_for(entry, "live") == entry["lock"]


# ── the freshness contract ─────────────────────────────────────────────────────────────────────────────────────
def test_the_forty_five_minute_freshness_contract_rides_on_the_forced_rebuild():
    assert LR.validate_freshness_contracts(REG["freshness_contracts"], {r["lane_id"] for r in REG["lanes"]}) == []
    assert FRESH["lane_id"] == LID  # the forced row: a contract on the conditional row would alert on a quiet hour
    assert FRESH["signal"] == {"kind": "json_key", "path": SNAPSHOT, "key": "generated_at"}
    assert FRESH["max_age_hours"] == 0.75  # the operator's 45 min in market hours (2026-11-08 18:05 ET)
    assert FRESH["basis"] == "lane_due"  # never a wall-clock bound: the weekend 6 h gap would read stale
    assert FRESH["severity"] == "P2"


# ── the health contracts ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("contract,row", [(CONTRACT, ROW), (CHECK_CONTRACT, CHECK_ROW)], ids=["rebuild", "check"])
def test_each_health_contract_copies_its_registry_stage_and_is_reviewed(contract, row):
    assert HC.validate_contract(contract) == []
    assert contract["kind"] == "lane" and contract["workflow_id"] == "tradeai-dispatcher"
    assert contract["stage"] == row["scheduler"]["stage"] == "canary"  # STAGE_DRIFT otherwise
    # A DRAFT contract at canary is DRAFT_AT_LIVE_STAGE: the lane would run live with UNKNOWN limits.
    assert contract["status"] == "REVIEWED"
    assert contract["review"]["status"] == "REVIEWED" and contract["review"]["reviewed_by"]


@pytest.mark.parametrize("contract,row", [(CONTRACT, ROW), (CHECK_CONTRACT, CHECK_ROW)], ids=["rebuild", "check"])
def test_the_staleness_bounds_are_2x_and_3x_the_rows_own_cadence_not_the_fire_spacing(contract, row):
    """The contract's staleness bounds follow cadence (as in every sibling contract), not the 45 min freshness
    contract, which is the operative tight bound evaluated on ``basis: lane_due`` in the registry."""
    base = contract["baseline"]
    cadence = row["expected_cadence_hours"]
    assert base["freshness_degraded_after_h"] == 2 * cadence
    assert base["freshness_failed_after_h"] == 3 * cadence
    assert base["freshness_failed_after_h"] > 1.75  # the longest legitimate gap between writes
    assert base["timeout_s"] == ENTRY["timeout_s"]
    assert base["class"] == row["dispatch"]["class"]


@pytest.mark.parametrize("contract", [CONTRACT, CHECK_CONTRACT], ids=["rebuild", "check"])
def test_the_expected_output_rules_are_valid_and_read_the_snapshot(contract):
    eo = contract["expected_output"]
    assert validate_expected_output(eo) == []
    assert eo["schema"] == "N8nExpectedOutput@v1" and eo["rule"] == "empty_allowed"
    assert eo["produced_field"] == "generated_at"
    assert "no_new_input" in eo["empty_allowed_reasons"]  # a quiet --if-changed fire is designed, not empty
    assert "no_runner" in eo["fatal_skip_reasons"]


@pytest.mark.parametrize("contract", [CONTRACT, CHECK_CONTRACT], ids=["rebuild", "check"])
def test_neither_canary_contract_exempts_a_lock_skip(contract):
    """LQ-20261107-1284: an exemption for 'RUN_SKIPPED_LOCK while the cron twin holds the shared flock' was written
    for a twin that has since been retired — a declared gap that would turn a dead lane green. Neither lane has a
    cron twin, so a skip is a finding here."""
    text = next(c["text"] for c in contract["healthy"] if c["check"] == "canary_live_done")
    assert "RUN_SKIPPED_LOCK is a finding" in text
    assert "while the cron twin holds" not in text


# ── the emulated fires: the live argv, in an isolated state root ────────────────────────────────────────────────
AS_OF = "2026-11-09T05:30:00-05:00"


class _Cur:
    description: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.description = []

    def fetchall(self):
        return []


class _Conn:
    """A stub read-only session: every query answers no rows, which is what a synthetic ZZ universe returns."""

    def __init__(self):
        self.closed = False

    def cursor(self):
        return _Cur()

    def close(self):
        self.closed = True


def _write_quotes(state_dir: Path, zza_pct: float) -> None:
    """Rewrite the synthetic quote snapshot: the only input the change signature can see without a DB."""
    # nosemgrep: tq-py-nonatomic-store-write -- synthetic ZZ fixture inside pytest's tmp_path, not a live store
    (state_dir / "ticker_snapshot_latest.json").write_text(json.dumps({
        "_meta": {"generated_at": "2026-11-06T20:05:00Z"},
        "tickers": {
            "ZZA": {
                "quote": {"price": 100.0, "change_pct": zza_pct},
                "holdings_context": {"shares_total": 10, "market_value_total": 1000.0},
                "performance": {"perf_week": 2.0},
            },
            "ZZB": {"quote": {"price": 50.0, "change_pct": -1.5}, "performance": {"perf_week": -0.5}},
        },
    }))


def _state_root(tmp_path: Path) -> Path:
    st = tmp_path / "state"
    state_dir = st / "data/portfolios/state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _write_quotes(state_dir, 4.5)
    return st


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    # ``lib.cio_market_context_state``, not ``scripts.lib.…``: the script imports the top-level ``lib`` package
    # (scripts/ is on its own sys.path), so the two module objects are distinct and only this one is consulted.
    import lib.cio_market_context_state as CM

    st = _state_root(tmp_path)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(st))
    monkeypatch.setenv("TRADEAI_STATE_DIR", str(st / "data/portfolios/state"))
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)
    conn = _Conn()
    monkeypatch.setattr(CM, "connect_trade_ai_readonly", lambda: conn)
    return st, conn


def _argv(entry, state_root: Path) -> list[str]:
    """The entry's live argv with $STATE_ROOT expanded to the temp PROJECT_ROOT (never the real one)."""
    out = [t.replace("$STATE_ROOT", str(state_root)) for t in entry["live_arg"]]
    assert not any("$" in t for t in out), out
    return out


def test_the_rebuild_argv_writes_the_snapshot_and_makes_no_model_call(isolated, capsys, monkeypatch):
    """The rebuild row's live argv: the file is the artifact, never an exit code (AGENTS rule 8)."""
    st, conn = isolated
    state_dir = st / "data/portfolios/state"
    calls = []
    monkeypatch.setattr(SCS, "_flash", lambda prompt: calls.append(prompt) or "text")  # must never run
    rc = SCS.main([*_argv(ENTRY, st), "--now", AS_OF])
    out, _err = capsys.readouterr()
    assert rc == 0
    assert calls == []  # no model call: the live argv carries no --llm
    assert f"wrote {state_dir / 'since_close_latest.json'}" in out
    snap = json.loads((st / SNAPSHOT).read_text())
    assert snap["schema"] == "since_close_card.v1" and snap["generated_at"]
    assert snap["summary"]["source"] == "deterministic"
    assert snap["window"]["session_date"] == "2026-11-06"
    assert [m["symbol"] for m in snap["moves"] if m["held"]] == ["ZZA"]
    assert conn.closed  # the session is opened and closed even when nothing is written


def test_the_check_argv_writes_nothing_when_quiet_and_writes_when_something_moved(isolated, capsys, monkeypatch):
    """The check row's live argv, end to end: quiet -> no write (the artifact is unchanged), a held +/-3% cross ->
    write, and a coarser change (a 1% bucket step) -> still a write. That last assertion PINS the operator-visible
    gap recorded in the row note: --if-changed is coarser than 'writes ONLY when something significant changed',
    and tightening it is an edit to scripts/lib/since_close_card.py, not to config."""
    st, conn = isolated
    state_dir = st / "data/portfolios/state"
    snap_path = st / SNAPSHOT
    calls = []
    monkeypatch.setattr(SCS, "_flash", lambda prompt: calls.append(prompt) or "text")

    # 1) baseline: below the 3% threshold, so a later cross is visible to detect_change.
    _write_quotes(state_dir, 2.0)
    assert SCS.main([*_argv(ENTRY, st), "--now", AS_OF]) == 0
    capsys.readouterr()
    before = snap_path.read_bytes()
    before_mtime = snap_path.stat().st_mtime_ns

    # 2) the same inputs again through the check argv: unchanged, so no write and no model call.
    assert SCS.main([*_argv(CHECK_ENTRY, st), "--now", AS_OF]) == 0
    out, _err = capsys.readouterr()
    assert "unchanged since the last build" in out and "no write, no LLM call" in out
    assert snap_path.read_bytes() == before
    assert snap_path.stat().st_mtime_ns == before_mtime

    # 3) a held name crosses +3%: material, so the check writes.
    _write_quotes(state_dir, 4.5)
    assert SCS.main([*_argv(CHECK_ENTRY, st), "--now", AS_OF]) == 0
    out, _err = capsys.readouterr()
    assert f"wrote {snap_path}" in out
    snap = json.loads(snap_path.read_text())
    assert snap["change_state"]["held_exact"]["ZZA"] == 4.5  # the new price reached the file, not just the log

    # 4) an unmaterial 1% bucket step after the cross: still a write (documented, and the reason for the follow-up).
    _write_quotes(state_dir, 5.2)
    assert SCS.main([*_argv(CHECK_ENTRY, st), "--now", AS_OF]) == 0
    out, _err = capsys.readouterr()
    assert f"wrote {snap_path}" in out
    assert json.loads(snap_path.read_text())["change_state"]["held_exact"]["ZZA"] == 5.2

    assert calls == []  # four fires, zero model calls: --llm is off in both rows' argv
    assert conn.closed


def test_a_dry_run_fire_as_of_monday_0530_et_writes_nothing_and_makes_no_model_call(isolated, capsys, monkeypatch):
    st, conn = isolated
    calls = []
    monkeypatch.setattr(SCS, "_flash", lambda prompt: calls.append(prompt) or "text")  # must never run
    rc = SCS.main(["--state-dir", str(st / "data/portfolios/state"), "--now", AS_OF])
    out, _err = capsys.readouterr()
    assert rc == 0
    assert calls == []
    assert "DRY RUN: nothing written, no LLM call" in out
    assert "window='Since Fri 4:00 PM'" in out and "held=1" in out
    assert not (st / SNAPSHOT).exists()
    assert conn.closed


def test_llm_without_apply_is_refused_and_writes_nothing(isolated, capsys):
    st, _conn = isolated
    rc = SCS.main(["--state-dir", str(st / "data/portfolios/state"), "--now", AS_OF, "--llm"])
    _out, err = capsys.readouterr()
    assert rc == 2
    assert "--llm needs --apply" in err
    assert not (st / SNAPSHOT).exists()


# ── the ci gate that runs this module ───────────────────────────────────────────────────────────────────────────
def test_this_module_is_registered_in_the_ci_gate_registry():
    path = CG.gate_path(ROOT, "since_close_lane_registration_20261108")
    doc = CG.validate(json.loads(path.read_text(encoding="utf-8")), stem=path.stem)
    assert doc["files"] == ["tests/test_since_close_lane_registration_20261108.py"]
    assert doc.get("anchor") == "SINCE_CLOSE_LANE_REGISTRATION_20261108"
