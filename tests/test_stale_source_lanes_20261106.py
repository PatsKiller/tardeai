"""ANCHOR: STALE_SOURCE_LANES_20261106 — stale Command Center sources become n8n lanes (operator decision 2026-11-06).

Covers: the regime VIX join through the classifier snapshot's indicator snapshot id; cash-alternative yields as
named gaps or a computed number (never a guess); the cash-alternatives universe joins the dividend sync; the
standalone dividend calendar CLI; the systemd unit-run snapshot and its reader in /api/v2/jobs-history; desk lane
maps; the three lanes pinned at SHADOW (live_arg null) with REVIEWED contracts and no broker/sender reach.
Hermetic: synthetic symbols and holdings (ZZA..), fake DB callables, a fake systemctl, tmp state roots only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import defense_cash_alternatives as dca  # noqa: E402
import portfolio_dividend_calendar as pdc  # noqa: E402
import sync_dividend_data as sdd  # noqa: E402
import unit_run_snapshot as urs  # noqa: E402
from scripts.lib import cio_truth  # noqa: E402
from scripts.lib import desks_a  # noqa: E402
from scripts.lib import jobs_history as J  # noqa: E402

NOW = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
LANES = ("defense-cash-alternatives", "dividend-calendar-refresh", "unit-run-snapshot")
SCRIPTS = {"defense-cash-alternatives": "scripts/defense_cash_alternatives.py",
           "dividend-calendar-refresh": "scripts/portfolio_dividend_calendar.py",
           "unit-run-snapshot": "scripts/unit_run_snapshot.py"}


@pytest.fixture
def state_root(tmp_path, monkeypatch):
    root = tmp_path / "state"
    root.mkdir()
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    return root


# ── (c) regime: VIX keyed by the collector's SNAP_ id, not the classifier's RS_ id ─────────────────────────────
def test_regime_vix_joins_through_the_classifier_inputs():
    seen = []

    def db_query(sql, params=None, fetch="all"):
        seen.append(sql)
        if "_indicator_snapshot_id" in sql and params == ("RS_SYNTH_1",):
            return [{"value": "21.5", "created_at": "2026-11-04T14:30:00+00:00"}]
        return []

    projection = {"regime": {"snapshot_id": "RS_SYNTH_1", "regime_label": "synthetic_label",
                             "generated_at": "2026-11-04T14:31:00+00:00"}}
    out = cio_truth.regime_for(db_query=db_query, projection=projection, now=NOW)
    assert out["vix"] == 21.5
    assert out["vix_as_of"].startswith("2026-11-04T14:30")
    assert any("JOIN market_regime_snapshots" in s for s in seen)


def test_regime_without_an_indicator_row_names_the_gap():
    out = cio_truth.regime_for(db_query=lambda *a, **k: [], projection={"regime": {"snapshot_id": "RS_SYNTH_2"}},
                               now=NOW)
    assert out["vix"] is None


def test_desk_lane_maps_name_the_new_writers():
    assert "defense-cash-alternatives" in desks_a.DEFENSE_LANES["cash"]
    assert "dividend-calendar-refresh" in desks_a.REENTRY_LANES["dividends"]
    assert {"premarket-data-pipeline", "after-close-pipeline-close-capture"} <= set(desks_a.REENTRY_LANES["regime"])


# ── (b) cash alternatives ─────────────────────────────────────────────────────────────────────────────────────
def _row(annual, *, source="yfinance", age_days=1):
    return {"annual_dividend_per_share": annual, "source": source, "updated_at": NOW - timedelta(days=age_days)}


def test_yield_is_annual_over_price():
    out = dca.yield_for("ZZA", {"price": 50.0}, _row(2.0), NOW)
    assert out["div_yield"] == 4.0 and out["yield_gap"] is None and out["annual_dividend"] == 2.0


@pytest.mark.parametrize("price,row,gap", [
    ({"price": 50.0}, None, "no dividend row"),
    ({"price": 50.0}, _row(2.0, age_days=30), "older than 14 days"),
    ({"price": 50.0}, _row(0), "no annual dividend"),
    (None, _row(2.0), "no price"),
    ({"price": 1.0}, _row(2.0), "implausible yield"),
])
def test_yield_gaps_are_named_never_guessed(price, row, gap):
    out = dca.yield_for("ZZB", price, row, NOW)
    assert out["div_yield"] is None and gap in out["yield_gap"]


def test_retired_provider_row_is_a_gap(monkeypatch):
    monkeypatch.setattr(dca, "_retired", lambda source: source == "synthetic-retired")
    out = dca.yield_for("ZZC", {"price": 50.0}, _row(2.0, source="synthetic-retired"), NOW)
    assert out["div_yield"] is None and "retired provider" in out["yield_gap"]


def _fake_query(symbols_with_yield):
    def query(sql, params=None):
        syms = list(params[0]) if params else []
        if "FROM market_quotes" in sql:
            return [{"symbol": s, "price": 40.0, "day_change_pct": 0.1, "volume": 2_000_000, "fetched_at": NOW}
                    for s in syms]
        if "FROM ticker_dividend_data" in sql:
            return [{"symbol": s, "annual_dividend_per_share": 2.0, "dividend_yield_pct": None, "source": "yfinance",
                     "updated_at": NOW} for s in syms if s in symbols_with_yield]
        return []
    return query


def test_screen_reports_coverage_and_ranks():
    universe = dca.universe_symbols()
    result = dca.screen(_fake_query({universe[0]}), now=NOW)
    cov = result["coverage"]
    assert cov == {"universe": len(result["candidates"]), "priced": len(result["candidates"]), "with_yield": 1}
    scores = [c["total_score"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert next(c for c in result["candidates"] if c["symbol"] == universe[0])["yield_data"]["div_yield"] == 5.0


def test_cash_dry_run_writes_nothing_and_apply_writes_output_and_receipt(state_root, monkeypatch, capsys):
    monkeypatch.setattr(dca, "_db_query", lambda: _fake_query(set(dca.universe_symbols())))
    monkeypatch.setattr(dca, "_retired", lambda source: False)
    assert dca.main(["--dry-run"]) == 0
    assert "nothing written" in capsys.readouterr().out
    assert not any(state_root.rglob("*.json"))
    assert dca.main(["--apply"]) == 0
    out = json.loads((state_root / "data/runtime/defense_cash_alternatives_latest.json").read_text())
    assert out["coverage"]["with_yield"] == out["coverage"]["universe"]
    receipt = json.loads((state_root / "data/runtime/defense-cash-alternatives_last.json").read_text())
    assert receipt["ok_at"] and receipt["produced_count"] == out["coverage"]["universe"]


def test_dividend_sync_universe_includes_cash_alternatives(tmp_path):
    pri = sdd.priority_universe(None, state_root=tmp_path, conn=None)
    assert pri["sources"]["cash_alternatives"]["status"] == "ok"
    assert set(dca.universe_symbols()) <= set(pri["symbols"])


# ── (d) dividend calendar ─────────────────────────────────────────────────────────────────────────────────────
def _synthetic_root(tmp_path):
    root = tmp_path / "proj"
    state = root / "data/portfolios/state"
    state.mkdir(parents=True)
    holdings = {"holdings": [
        {"symbol": "ZZA", "shares": 100, "market_value": 5000.0, "current_price": 50.0, "account": "synthetic"},
        {"symbol": "ZZB", "shares": 10, "market_value": 900.0, "current_price": 90.0, "account": "synthetic"}],
        "portfolio_totals": {"total_value": 5900.0}}
    (state / "holdings.json").write_text(json.dumps(holdings))
    return root, state


def test_calendar_write_false_writes_nothing(tmp_path, monkeypatch):
    root, state = _synthetic_root(tmp_path)
    monkeypatch.setattr(pdc, "_fetch_dividend_dates", lambda symbols, root: {})
    monkeypatch.setitem(pdc.KNOWN_SCHEDULES, "ZZA", {"frequency": "quarterly", "yield_pct": 4.0, "qualified": True,
                                                     "safety": "strong"})
    portfolio = json.loads((state / "holdings.json").read_text())
    result = pdc.build_dividend_calendar(portfolio, root, state, write=False)
    assert "last_updated" in result and [p["symbol"] for p in result["payers"]] == ["ZZA"]
    assert not (state / "dividend_calendar.json").exists()


def test_calendar_cli_dry_run_then_apply(tmp_path, state_root, monkeypatch, capsys):
    root, state = _synthetic_root(tmp_path)
    monkeypatch.setattr(pdc, "_fetch_dividend_dates", lambda symbols, root: {})
    monkeypatch.setitem(pdc.KNOWN_SCHEDULES, "ZZA", {"frequency": "quarterly", "yield_pct": 4.0, "qualified": True,
                                                     "safety": "strong"})
    assert pdc.main(["--dry-run", "--root", str(root)]) == 0
    assert "nothing written" in capsys.readouterr().out
    assert not (state / "dividend_calendar.json").exists()
    assert pdc.main(["--apply", "--root", str(root)]) == 0
    assert json.loads((state / "dividend_calendar.json").read_text())["last_updated"]
    receipt = json.loads((state_root / "data/runtime/dividend-calendar-refresh_last.json").read_text())
    assert receipt["ok_at"] and receipt["produced_count"] == 1


def test_calendar_cli_fails_without_holdings(tmp_path, state_root, monkeypatch):
    root = tmp_path / "empty"
    (root / "data/portfolios/state").mkdir(parents=True)
    assert pdc.main(["--apply", "--root", str(root)]) == 1
    receipt = json.loads((state_root / "data/runtime/dividend-calendar-refresh_last.json").read_text())
    assert not receipt.get("ok_at") or receipt.get("exit") == 1


# ── (e) systemd unit-run snapshot ─────────────────────────────────────────────────────────────────────────────
REGISTRY = {"lanes": [
    {"lane_id": "synthetic-timer-lane", "state": "ACTIVE",
     "scheduler": {"kind": "systemd", "expression": "synthetic-job.timer (OnCalendar=hourly)"}},
    {"lane_id": "synthetic-service-lane", "state": "ACTIVE",
     "scheduler": {"kind": "systemd", "expression": "synthetic-daemon.service"}},
    {"lane_id": "synthetic-retired", "state": "RETIRED",
     "scheduler": {"kind": "systemd", "expression": "synthetic-old.timer"}},
    {"lane_id": "synthetic-n8n", "state": "ACTIVE", "scheduler": {"kind": "n8n", "expression": "dispatcher"}},
]}
T0 = int(NOW.timestamp())


def _fake_show(user_props):
    def show(units, props, scope):
        table = user_props if scope == "user" else {}
        return {u: table[u] for u in units if u in table}
    return show


USER = {
    "synthetic-job.timer": {"Id": "synthetic-job.timer", "LoadState": "loaded", "Unit": "synthetic-job.service"},
    "synthetic-job.service": {"Id": "synthetic-job.service", "LoadState": "loaded", "ActiveState": "inactive",
                              "SubState": "dead", "Result": "exit-code", "InvocationID": "inv-a",
                              "ExecMainStartTimestamp": f"@{T0 - 120}", "ExecMainExitTimestamp": f"@{T0 - 60}",
                              "ExecMainStatus": "2", "NRestarts": "0"},
}


def test_registry_units_skip_retired_and_non_systemd():
    assert urs.registry_units(REGISTRY) == {"synthetic-job.timer": "synthetic-timer-lane",
                                            "synthetic-daemon.service": "synthetic-service-lane"}


def test_parse_show_splits_blocks():
    blocks = urs.parse_show("Id=a.service\nResult=success\n\nId=b.service\nResult=exit-code\n")
    assert [b["Id"] for b in blocks] == ["a.service", "b.service"]


def test_collect_records_finished_runs_and_names_unread_units():
    snap = urs.collect(urs.registry_units(REGISTRY), show=_fake_show(USER), now=NOW)
    assert snap["read"] == 1 and list(snap["unread"]) == ["synthetic-daemon.service"]
    (run,) = snap["runs"]
    assert run["lane_id"] == "synthetic-timer-lane" and run["exit_status"] == 2 and run["succeeded"] is False
    assert run["schema"] == "UnitRun@v1" and run["invocation_id"] == "inv-a"


def test_running_unit_is_not_recorded_yet():
    running = {**USER, "synthetic-job.service": {**USER["synthetic-job.service"], "ActiveState": "activating",
                                                 "SubState": "running"}}
    assert urs.collect({"synthetic-job.timer": "x"}, show=_fake_show(running), now=NOW)["runs"] == []


def test_new_runs_dedup_by_invocation_and_record(tmp_path):
    snap = urs.collect(urs.registry_units(REGISTRY), show=_fake_show(USER), now=NOW)
    fresh = urs.new_runs(snap["runs"], {})
    runs_path, state_path = urs.record(fresh, {}, tmp_path, NOW)
    state = json.loads(state_path.read_text())
    assert state["last"] == {"synthetic-job.timer": "inv-a"}
    assert urs.new_runs(snap["runs"], state) == []
    assert len(runs_path.read_text().splitlines()) == 1


def test_unit_snapshot_dry_run_writes_nothing_and_apply_writes(tmp_path, state_root, monkeypatch, capsys):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps(REGISTRY))
    monkeypatch.setattr(urs, "systemctl_show", _fake_show(USER))
    assert urs.main(["--dry-run", "--registry", str(reg)]) == 0
    assert "nothing written" in capsys.readouterr().out
    assert not (state_root / "data/runtime/unit_runs.jsonl").exists()
    assert urs.main(["--apply", "--registry", str(reg)]) == 0
    assert len((state_root / "data/runtime/unit_runs.jsonl").read_text().splitlines()) == 1
    receipt = json.loads((state_root / "data/runtime/unit-run-snapshot_last.json").read_text())
    assert receipt["produced_count"] == 1
    assert urs.main(["--apply", "--registry", str(reg)]) == 0
    receipt = json.loads((state_root / "data/runtime/unit-run-snapshot_last.json").read_text())
    assert receipt["produced_count"] == 0 and receipt["empty_reason"] == "nothing_new"


def test_jobs_history_shows_unit_runs_for_a_systemd_lane(tmp_path):
    snap = urs.collect(urs.registry_units(REGISTRY), show=_fake_show(USER), now=NOW)
    runs_path, _ = urs.record(snap["runs"], {}, tmp_path, NOW)
    rows = J.read_unit_runs(runs_path)["unit_runs"]
    by_lane = J.unit_runs_by_lane(rows + rows)
    assert len(by_lane["synthetic-timer-lane"]) == 1
    lane = {"lane_id": "synthetic-timer-lane", "state": "ACTIVE", "expected_cadence_hours": 1,
            "scheduler": {"kind": "systemd", "expression": "synthetic-job.timer"}}
    out = J.build({"lanes": [lane]}, {"unit_runs": rows, "ledger_since": NOW - timedelta(days=1),
                                      "journal_since": NOW - timedelta(days=1)},
                  now=NOW, trading_day=lambda d: d.weekday() < 5)
    row = next(r for r in out["rows"] if r["lane_id"] == "synthetic-timer-lane")
    assert "systemd unit snapshot" in row["history_sources"]
    assert row["last_run"]["result"] == "failed"


# ── registration pins ─────────────────────────────────────────────────────────────────────────────────────────
def _config(name):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("lane_id", LANES)
def test_lanes_are_registered_at_shadow_with_reviewed_contracts(lane_id):
    reg = next(r for r in _config("lane_registry.json")["lanes"] if r["lane_id"] == lane_id)
    assert reg["scheduler"]["kind"] == "n8n" and reg["scheduler"]["stage"] == "shadow"
    assert reg["scheduler"]["match"] == SCRIPTS[lane_id] and reg["dispatch"]["mode"] == "dry_run"
    allow = next(r for r in _config("n8n_run_allowlist.json")["lanes"] if r["lane_id"] == lane_id)
    assert allow["command"] == ["$PY", SCRIPTS[lane_id]] and allow["dry_run_arg"] == ["--dry-run"]
    assert allow["live_arg"] is None and allow["output_signal"] == reg["output_signal"]["path"]
    contract = next(c for c in _config("n8n_health_contracts.json")["contracts"] if c["id"] == lane_id)
    assert contract["status"] == "REVIEWED" and contract["stage"] == "shadow"


@pytest.mark.parametrize("lane_id", LANES)
def test_lane_reach_has_no_broker_account_or_sender(lane_id):
    from scripts.lib import advisory_lane_guard as G
    rep = G.scan_entry(SCRIPTS[lane_id])
    assert not rep.broker_modules and not rep.account_reads and not rep.sends and not rep.direct_sends
