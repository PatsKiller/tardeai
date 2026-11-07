"""LQ-20261107-364: ``market-event-data-refresh`` is wired as an n8n lane, and the three files agree.

This file ships **with the lane's config patch** (lane_registry row, run-allowlist entry, health contract),
because the rows and the test are one change:

* a registry row at ``stage: shadow`` without a REVIEWED contract fails the health gate
  (``scripts/check_n8n_health_contracts.py``: MISSING_CONTRACT), so the contract travels with the row;
* the n8n executor looks this run's immutable attempt receipt up under ``lane_attempts/<ALLOWLIST lane_id>/``,
  so a script whose LANE_ID differs from the allowlist lane_id would read ``output_unverifiable`` on every live
  run -- a lane that works and can never be graded green;
* the registry's ``output_signal`` and the allowlist's ``output_signal`` must be the same file the receipt
  helper writes (:func:`lane_last_receipt.receipt_path`), or the freshness monitor watches a file nobody writes.

The schedule is pinned as behaviour, not as a string: thirteen fires a week -- Sat 18:00 and Sun 18:00 ET (the
Friday close), Mon-Fri 06:30 ET (the previous session's close). A weekend morning or a weekday evening fire
would mean the lane is refreshing a close that has not happened yet.

Hermetic: reads committed JSON and imports one stdlib-only module. No DB, no network, no n8n.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import finviz_snapshot_refresh as R  # noqa: E402
from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.pipelines import pipeline_manifest as PM  # noqa: E402

LANE = "market-event-data-refresh"
ET = ZoneInfo("America/New_York")
WEEKDAY_PREMARKET = "30 6 * * 1-5"
WEEKEND_EVENING = "0 18 * * 0,6"

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ALLOWLIST = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
CONTRACTS = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))


def _one(rows, key):
    hits = [r for r in rows if r.get(key) == LANE]
    assert len(hits) == 1, f"{len(hits)} rows with {key}=={LANE!r} (the patch must apply once)"
    return hits[0]


def _row():
    return _one(REGISTRY["lanes"], "lane_id")


def _entry():
    return _one(ALLOWLIST["lanes"], "lane_id")


def _contract():
    return _one(CONTRACTS["contracts"], "id")


# --------------------------------------------------------------------------------------------- identity


def test_the_script_writes_its_receipt_under_the_allowlist_lane_id():
    """The executor grades ``lane_attempts/<allowlist lane_id>/<run_id>.json``: a different name is unverifiable."""
    assert R.LANE_ID == _row()["lane_id"] == _entry()["lane_id"] == _contract()["id"] == LANE


def test_the_receipt_path_the_script_writes_is_the_registry_output_signal():
    from lib import lane_last_receipt as LR

    written = LR.receipt_path(R.LANE_ID, state_root=Path("/state")).relative_to("/state").as_posix()
    assert _row()["output_signal"] == {"kind": "json_key", "path": written, "key": "ok_at"}
    assert _entry()["output_signal"] == written


# ------------------------------------------------------------------------------------- registry row


def test_the_registry_row_declares_the_lane_shadow_first():
    row = _row()
    assert row["scheduler"]["kind"] == "n8n"
    assert row["scheduler"]["expression"] == "dispatcher"
    assert row["scheduler"]["match"] == "scripts/finviz_snapshot_refresh.py"
    assert row["scheduler"]["stage"] == "shadow", "shadow first: the executor's stage clamp then forces dry_run"
    assert row["dispatch"]["mode"] == "dry_run"
    assert row["dispatch"]["tz"] == "America/New_York"
    assert row["state"] == "ACTIVE"


def test_the_registry_row_declares_the_thirteen_fires_a_week():
    assert sorted(_row()["dispatch"]["cron"]) == sorted([WEEKDAY_PREMARKET, WEEKEND_EVENING])


# ---------------------------------------------------------------------------------- allowlist entry


def test_the_allowlist_entry_runs_this_script_in_both_modes():
    e = _entry()
    assert e["command"] == ["$PY", "scripts/finviz_snapshot_refresh.py"]
    assert (ROOT / "scripts" / "finviz_snapshot_refresh.py").is_file()
    assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] == ["--apply"]
    assert e["lock"].startswith("/tmp/") and e["lock_kind"] == "safe_flock"
    assert e["market_gate"] is False, "two of the thirteen weekly fires are on a weekend: a market-day gate would skip them"
    assert e["output_receipt"] == "v2", "the lane writes produced_count from a read-back, not from what it sent"


def test_the_allowlist_entry_passes_the_forbidden_token_gates():
    e = _entry()
    tokens = [*e["command"], *(e["dry_run_arg"] or []), *(e["live_arg"] or []), e["lock"], e["output_signal"]]
    for token in tokens:
        for forbidden in PM.FORBIDDEN_COMMAND_TOKENS:
            assert forbidden not in token, (token, forbidden)
        text = token.strip().lower()
        parts = [p for p in re.split(r"[^a-z0-9]+", text) if p]
        assert not [p for p in parts if p in G.FORBIDDEN_ROUTE_TOKENS], token
        collapsed = text.replace("-", "").replace("/", "")
        assert not [t for t in G.FORBIDDEN_ROUTE_TOKENS if t in collapsed and t != "title"], token


def test_the_timeout_covers_the_finviz_spend_the_universe_implies():
    """91 symbols -> ceil(91/20) = 5 export batches x 6 views = 30 requests at a 2.5 s global throttle."""
    from finviz_throttle import MIN_INTERVAL

    batches = -(-R.WATCHLIST_CAP // 20)          # the ceiling division the enrichment writer batches by
    requests = batches * 6                        # the six views finviz_enrichment asks for
    floor_s = requests * MIN_INTERVAL
    assert _entry()["timeout_s"] >= 2 * floor_s, (
        f"timeout_s {_entry()['timeout_s']} < 2x the {floor_s:.0f} s throttle floor for {requests} requests")
    assert _contract()["baseline"]["timeout_s"] == _entry()["timeout_s"]


# ----------------------------------------------------------------------------------- health contract


def test_the_contract_is_reviewed_structurally_valid_and_agrees_with_the_registry():
    c = _contract()
    assert c["status"] == "REVIEWED", "a new lane's contract must be REVIEWED before its registry PR"
    assert c["stage"] == _row()["scheduler"]["stage"], "STAGE_DRIFT: the contract copies the registry stage"
    assert H.validate_contract(c) == [], H.validate_contract(c)
    assert H.unknown_fields(c) == [], "a REVIEWED contract carries no UNKNOWN field"


def test_the_three_files_pass_the_health_gate_together():
    index = H.load_json(H.GENERIC_INDEX_PATH)
    res = H.check(CONTRACTS, REGISTRY, index, today=date(2026, 11, 7))
    mine = [e for e in res["errors"] if LANE in e]
    assert mine == [], mine


def test_empty_output_can_only_pass_with_rows_the_table_actually_holds():
    eo = _contract()["expected_output"]
    assert eo["rule"] == "min_produced" and eo["min_produced"] >= 1
    assert eo["produced_field"] == "produced_count"
    assert eo["empty_allowed_reasons"] == [], "the lane's whole job is rows: there is no legitimate empty run"
    assert eo["fatal_skip_reasons"] == ["dependency_unavailable"]
    src = (ROOT / "scripts" / "finviz_snapshot_refresh.py").read_text(encoding="utf-8")
    assert '"dependency_unavailable"' in src, "the contract's fatal reason must be one the script can emit"


# ---------------------------------------------------------------------------------------- the schedule


def _cron_field(field: str, value: int) -> bool:
    for part in field.split(","):
        if part == "*":
            return True
        if part.startswith("*/"):
            if value % int(part[2:]) == 0:
                return True
            continue
        if "-" in part:
            lo, hi = part.split("-")
            if int(lo) <= value <= int(hi):
                return True
            continue
        if int(part) == value:
            return True
    return False


def _fires(expr: str, dt: datetime) -> bool:
    minute, hour, dom, month, dow = expr.split()
    return (_cron_field(minute, dt.minute) and _cron_field(hour, dt.hour) and _cron_field(dom, dt.day)
            and _cron_field(month, dt.month) and _cron_field(dow, (dt.weekday() + 1) % 7))


def _fires_any(dt: datetime) -> bool:
    return any(_fires(expr, dt) for expr in _row()["dispatch"]["cron"])


def test_the_lane_fires_on_the_weekend_evening_and_the_weekday_premarket():
    for when in (datetime(2026, 11, 7, 18, 0, tzinfo=ET),    # Saturday: the Friday close
                 datetime(2026, 11, 8, 18, 0, tzinfo=ET),    # Sunday: still the Friday close
                 datetime(2026, 11, 9, 6, 30, tzinfo=ET),    # Monday pre-market: the Friday close
                 datetime(2026, 11, 13, 6, 30, tzinfo=ET)):  # Friday pre-market: Thursday's close
        assert _fires_any(when), when


def test_the_lane_does_not_fire_when_there_is_no_new_close():
    for when in (datetime(2026, 11, 7, 6, 30, tzinfo=ET),     # Saturday morning: Friday is already captured
                 datetime(2026, 11, 9, 18, 0, tzinfo=ET),     # Monday evening: not a scheduled slot
                 datetime(2026, 11, 11, 12, 0, tzinfo=ET),    # Tuesday midday
                 datetime(2026, 11, 7, 17, 0, tzinfo=ET)):    # Saturday, an hour early
        assert not _fires_any(when), when


def test_the_close_a_premarket_fire_carries_is_the_previous_session(monkeypatch):
    """The date rule the schedule depends on: at Monday 06:30 today's close has not happened."""
    import lib.cio_market_calendar as cal

    monkeypatch.setattr(cal, "is_us_trading_day", lambda d: datetime.fromisoformat(str(d)).weekday() < 5)
    assert R.last_session_close(datetime(2026, 11, 9, 6, 30, tzinfo=ET)) == "2026-11-06"   # Monday pre-market
    assert R.last_session_close(datetime(2026, 11, 7, 18, 0, tzinfo=ET)) == "2026-11-06"    # Saturday evening
    assert R.last_session_close(datetime(2026, 11, 9, 18, 0, tzinfo=ET)) == "2026-11-09"    # Monday evening
