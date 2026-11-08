"""SINCE_CLOSE_LANE_REGISTRATION_20261108 — the since-close-snapshot n8n lane is registered, and its cadence table is data.

LQ-20261107-1261 registers the "Since last close" home-card producer (cc-sonnet-3, LQ-20261107-1253 head
0d593b2bc) as an n8n dispatcher lane: a registry row, a freshness contract, an allowlist entry and a health
contract. Nothing about that is provable by reading the JSON — a row that names the wrong script, a cadence list
that fires when nobody wrote down, or an allowlist entry the executor would refuse all read the same in a diff.
This module pins the four files to each other and to the script:

* the cadence table is ``dispatch.cron``, one expression per row, and the fire set it produces over one week is
  asserted against an independently computed expectation — so adding the intraday ``--if-changed`` cadence
  (LQ-20261107-1260) is one expression in the row and one line in the expectation, and a row that drifts from
  what the operator approved fails here;
* the allowlist entry is accepted by the executor's own ``validate_entry``, is shadow-only (``live_arg`` null at
  stage shadow) and takes its lock at ``<lock>.dryrun`` for a dry run;
* the registry ``output_signal``, the allowlist ``output_signal`` and the freshness contract name the same file;
* the health contract's stage is a copy of the registry's (a drifted copy makes run_quality call the lane "not as
  designed");
* the lane's default mode is the dry run, and an emulated fire as of **Mon 2026-11-09 05:30 ET** in an isolated
  state root writes nothing, prints the window and makes no model call. ``--llm`` without ``--apply`` is refused,
  and the ``--apply --llm`` path is exercised with an injected model callable, never a provider.

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
from scripts import n8n_run_executor as X  # noqa: E402
import since_close_snapshot as SCS  # noqa: E402

LID = "since-close-snapshot"
FKEY = "pfm.since_close_snapshot"
SNAPSHOT = "data/portfolios/state/since_close_latest.json"
ET = ZoneInfo("America/New_York")

REG = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
ALLOW = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
HEALTH = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))
ROW = {r["lane_id"]: r for r in REG["lanes"]}[LID]
ENTRY = {e["lane_id"]: e for e in ALLOW["lanes"]}[LID]
FRESH = {c["key"]: c for c in REG["freshness_contracts"]}[FKEY]
CONTRACT = {c["id"]: c for c in HEALTH["contracts"]}[LID]


# ── the row ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_row_is_a_shadow_dispatcher_row_for_the_real_script():
    sched = ROW["scheduler"]
    assert sched["kind"] == "n8n"
    assert sched["expression"] == "dispatcher"  # never the workflow id (AGENTS 23.11)
    assert sched["stage"] == "shadow"
    assert sched["timezone"] == "America/New_York"
    assert (ROOT / sched["match"]).is_file(), sched["match"]
    assert ROW["dispatch"]["mode"] == "dry_run"
    assert ROW["dispatch"]["tz"] == "America/New_York"
    assert ROW["state"] == "ACTIVE" and ROW["state_since"] and ROW["state_reason"]


def test_the_dispatch_block_passes_the_lane_dispatch_gate():
    policies = json.loads((ROOT / "config/n8n_retry_policies.json").read_text(encoding="utf-8"))["policies"]
    known = [r["lane_id"] for r in REG["lanes"]]
    assert LD.validate_dispatch_block(ROW, known_lane_ids=known, retry_policy_names=list(policies)) == []


def test_the_registry_row_is_structurally_valid_and_carries_the_snapshot_signal():
    assert LR.validate_row(ROW) == []
    assert ROW["output_signal"]["kind"] == "json_key"
    assert ROW["output_signal"]["path"] == SNAPSHOT
    assert ROW["output_signal"]["key"] == "generated_at"


# ── the cadence table (data, and asserted against an independently computed week) ────────────────────────────────
WEEK_START = datetime(2026, 11, 9, 0, 0, tzinfo=ET)  # Monday; US DST ended 2026-11-01, so no offset change


def _expected_slots(start: datetime) -> set[str]:
    """The operator's cadence amendment (2026-11-08 18:05 ET), written out by hand. Extending the lane's cadence
    means adding a line here and an expression in dispatch.cron — never one without the other. Weekdays: the fixed
    rebuilds at 06:00, 08:30, 09:15, 09:45, 10:30, 12:00, 14:00, 15:30 and 16:15; the 15-min --if-changed window
    09:30-16:00 (which covers 09:30 besides those); hourly 18:00-04:59. Weekends: every 2 h."""
    out: set[str] = set()
    for d in range(7):
        day = (start + timedelta(days=d)).date()

        def at(hh: int, mm: int) -> str:
            return f"{day.strftime('%Y%m%d')}T{hh:02d}{mm:02d}"

        if day.weekday() < 5:
            out |= {at(h, m) for h in range(10, 16) for m in (0, 15, 30, 45)}  # the 15-min window, 10:00-15:45
            out |= {at(6, 0), at(8, 30), at(9, 15), at(9, 30), at(9, 45), at(16, 0), at(16, 15)}
            out |= {at(h, 0) for h in (0, 1, 2, 3, 4, 18, 19, 20, 21, 22, 23)}
        else:
            out |= {at(h, 0) for h in range(0, 24, 2)}
    return out


def test_the_cadence_table_fires_exactly_what_the_row_declares():
    fired = set()
    # fires_between is (start, end]: bracket the week with one second either side so Monday 00:00 is inside it and
    # the next Monday's 00:00 is not.
    for expr in ROW["dispatch"]["cron"]:
        for f in CRON.fires_between(expr, WEEK_START - timedelta(seconds=1),
                                    WEEK_START + timedelta(days=7, seconds=-1), "America/New_York"):
            fired.add(f.slot_local)
    assert fired == _expected_slots(WEEK_START)
    assert len(fired) == 5 * 42 + 2 * 12  # 42 fires on a trading day, 12 on a weekend day
    # The operator's fixed slots are all inside the set, and each is one fire rather than two expressions landing
    # in the same minute (a duplicate slot would also be deduped here, so the count above is the real proof).
    assert {f"20261109T{h:02d}{m:02d}" for h, m in
            ((6, 0), (8, 30), (9, 15), (9, 45), (10, 30), (12, 0), (14, 0), (15, 30), (16, 15))} <= fired


def test_the_cron_list_fits_the_dispatcher_slot_cap():
    assert len(ROW["dispatch"]["cron"]) <= LD.DISPATCH_CRON_MAX_SLOTS  # 8
    assert len(set(ROW["dispatch"]["cron"])) == len(ROW["dispatch"]["cron"])


# ── the allowlist entry ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_allowlist_entry_is_runnable_and_shadow_only():
    assert X.validate_entry(ENTRY) is None, X.validate_entry(ENTRY)
    assert ENTRY["command"] == ["$PY", "scripts/since_close_snapshot.py"]
    assert (ROOT / ENTRY["command"][1]).is_file()
    # SHADOW: the only mode the executor can run is the script's default, which is the dry run. The script has no
    # --dry-run flag (LQ-1253), so dry_run_arg is the empty list, not null; live_arg is null until canary.
    assert ENTRY["dry_run_arg"] == []
    assert ENTRY["live_arg"] is None
    assert ENTRY["lock"] == "/tmp/since_close_snapshot.lock"
    assert ENTRY["lock_kind"] == "flock"
    assert not ENTRY["lock"].endswith(".dryrun")
    assert ENTRY["timeout_s"] == 300
    assert ENTRY["output_signal"] == SNAPSHOT == ROW["output_signal"]["path"]
    assert "DB_PASSWORD" in ENTRY["env_names"] and not any(
        n.startswith(("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR")) for n in ENTRY["env_names"]
    )


def test_the_dry_run_takes_the_dry_run_lock_and_the_live_mode_is_unavailable_until_canary():
    assert X.lock_path_for(ENTRY, "dry_run").endswith(".dryrun")
    assert X.lock_path_for(ENTRY, "live") == ENTRY["lock"]


# ── the freshness contract ─────────────────────────────────────────────────────────────────────────────────────
def test_the_forty_five_minute_market_hours_freshness_contract_is_valid_and_names_the_snapshot():
    assert LR.validate_freshness_contracts(REG["freshness_contracts"], {r["lane_id"] for r in REG["lanes"]}) == []
    assert FRESH["lane_id"] == LID
    assert FRESH["signal"] == {"kind": "json_key", "path": SNAPSHOT, "key": "generated_at"}
    assert FRESH["max_age_hours"] == 0.75  # the operator's 45 min in market hours (2026-11-08 18:05 ET)
    assert FRESH["basis"] == "lane_due"  # never a wall-clock bound: the weekend 2 h cadence and the overnight hourly one
    assert FRESH["severity"] == "P2"


# ── the health contract ────────────────────────────────────────────────────────────────────────────────────────
def test_the_health_contract_copies_the_registry_stage_and_is_structurally_valid():
    assert HC.validate_contract(CONTRACT) == []
    assert CONTRACT["kind"] == "lane" and CONTRACT["workflow_id"] == "tradeai-dispatcher"
    assert CONTRACT["stage"] == ROW["scheduler"]["stage"]  # STAGE_DRIFT otherwise
    # A new lane's contract must be REVIEWED by its owner before its registry PR. It is DRAFT here on purpose:
    # check_n8n_health_contracts reports DRAFT_NOT_GRANDFATHERED for this lane until the owner flips that one field.
    assert CONTRACT["status"] in ("DRAFT", "REVIEWED")


def test_the_staleness_bounds_are_2x_and_3x_the_rows_own_cadence_not_the_freshness_bound():
    """The contract's staleness bounds follow cadence (as in every sibling contract), not the 45 min freshness
    contract, which is the operative tight bound evaluated on ``basis: lane_due`` in the registry."""
    base = CONTRACT["baseline"]
    cadence = ROW["expected_cadence_hours"]
    assert base["freshness_degraded_after_h"] == 2 * cadence
    assert base["freshness_failed_after_h"] == 3 * cadence
    assert base["freshness_failed_after_h"] > 1.75  # the longest legitimate gap between fires
    assert base["timeout_s"] == ENTRY["timeout_s"]
    assert base["class"] == ROW["dispatch"]["class"]


# ── the emulated fire: as of Mon 2026-11-09 05:30 ET, in an isolated state root ─────────────────────────────────
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


def _state_root(tmp_path: Path) -> Path:
    st = tmp_path / "state"
    state_dir = st / "data/portfolios/state"
    state_dir.mkdir(parents=True, exist_ok=True)
    # A synthetic quote snapshot in the shape build_moves reads: one held name, one watchlist name.
    (state_dir / "ticker_snapshot_latest.json").write_text(json.dumps({
        "_meta": {"generated_at": "2026-11-06T20:05:00Z"},
        "tickers": {
            "ZZA": {
                "quote": {"price": 100.0, "change_pct": 4.5},
                "holdings_context": {"shares_total": 10, "market_value_total": 1000.0},
                "performance": {"perf_week": 2.0},
            },
            "ZZB": {"quote": {"price": 50.0, "change_pct": -1.5}, "performance": {"perf_week": -0.5}},
        },
    }))
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


def test_a_dry_run_fire_as_of_monday_0530_et_writes_nothing_and_makes_no_model_call(isolated, capsys, monkeypatch):
    st, conn = isolated
    calls = []
    monkeypatch.setattr(SCS, "_flash", lambda prompt: calls.append(prompt) or "text")  # must never run
    rc = SCS.main(["--state-dir", str(st / "data/portfolios/state"), "--now", AS_OF])
    out, _err = capsys.readouterr()
    assert rc == 0
    assert calls == []  # no model call on a dry run
    assert "DRY RUN: nothing written, no LLM call" in out
    assert "window='Since Fri 4:00 PM'" in out and "held=1" in out  # the emulated instant is after Friday's close
    assert not (st / SNAPSHOT).exists()
    assert conn.closed  # the session is opened and closed even when nothing is written


def test_llm_without_apply_is_refused_and_writes_nothing(isolated, capsys):
    st, _conn = isolated
    rc = SCS.main(["--state-dir", str(st / "data/portfolios/state"), "--now", AS_OF, "--llm"])
    _out, err = capsys.readouterr()
    assert rc == 2
    assert "--llm needs --apply" in err
    assert not (st / SNAPSHOT).exists()


def test_the_apply_path_writes_the_snapshot_and_calls_the_injected_model_once(isolated, capsys, monkeypatch):
    """The live argv's two flags, exercised with an injected callable: the file is the artifact, never an exit code."""
    st, _conn = isolated
    calls = []
    monkeypatch.setattr(SCS, "_flash", lambda prompt: calls.append(prompt) or "Held names moved overnight.")
    rc = SCS.main(["--state-dir", str(st / "data/portfolios/state"), "--now", AS_OF, "--apply", "--llm"])
    out, _err = capsys.readouterr()
    assert rc == 0 and len(calls) == 1
    snap = json.loads((st / SNAPSHOT).read_text())
    assert snap["schema"] == "since_close_card.v1" and snap["generated_at"]
    assert snap["summary"]["source"] == "llm"
    assert snap["window"]["session_date"] == "2026-11-06"
    assert [m["symbol"] for m in snap["moves"] if m["held"]] == ["ZZA"]
    assert f"wrote {st / SNAPSHOT}" in out


# ── the ci gate that runs this module ───────────────────────────────────────────────────────────────────────────
def test_this_module_is_registered_in_the_ci_gate_registry():
    path = CG.gate_path(ROOT, "since_close_lane_registration_20261108")
    doc = CG.validate(json.loads(path.read_text(encoding="utf-8")), stem=path.stem)
    assert doc["files"] == ["tests/test_since_close_lane_registration_20261108.py"]
    assert doc.get("anchor") == "SINCE_CLOSE_LANE_REGISTRATION_20261108"
