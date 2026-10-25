"""Desks A (approved boards 1-4): pinned fixtures, explicit gaps, one CIO source, no side effects.

ANCHOR: DESKS_A_20261025. Field trace: docs/ops/DESKS_A_REDESIGN_20261025.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import desks_a as desk  # noqa: E402

NOW = datetime(2026, 10, 25, 14, 0, tzinfo=timezone.utc)
REG = {"cio-entry-state": "ACTIVE", "market-regime-classifier": "RETIRED", "portfolio-repricer": "ACTIVE",
       "watch-alerts-eval": "ACTIVE", "hermes-analyst-coverage": "ACTIVE", "pro-analyst-fetch": "ACTIVE",
       "portfolio-ai-analyst": "ACTIVE", "sync-dividend-data": "RETIRED", "feedback-loop-processor": "ACTIVE",
       "daily-incubator-refresh": "ACTIVE", "weekly-incubator-builder": "ACTIVE", "incubator-proposal-promoter": "ACTIVE",
       "proposal-backtest-engine": "ACTIVE", "setup-quality-prior": "ACTIVE", "sector-momentum-engine": "ACTIVE",
       "industry-momentum-groups": "ACTIVE", "defense-recommendations": "ACTIVE", "defense-inverse-stoplights": "ACTIVE",
       "options-lifecycle-run": "PAUSED", "run-watchlist-agent-jobs-offpeak": "ACTIVE", "cio-memory-shadow-measure": "ACTIVE",
       "agent-calibration-engine": "ACTIVE", "multi-tier-trade-reviewer-weekly": "ACTIVE", "advisory-lessons-reflect": "ACTIVE",
       "tradeai-agent-runtime-alex": "ACTIVE", "tradeai-agent-runtime-sentinel": "RETIRED"}


def write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def tree_digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


class FakeDb:
    """Answers by SQL fragment; records every statement so tests prove SELECT only."""

    def __init__(self, answers: dict[str, list[dict] | None]):
        self.answers, self.seen = answers, []

    def __call__(self, sql, params=None):
        self.seen.append(" ".join(sql.split()))
        for fragment, rows in self.answers.items():
            if fragment in sql:
                return rows
        return []


def panel(payload, tab, pid):
    return next(p for p in payload["tabs"][tab]["panels"] if p["id"] == pid)


def row(panel_doc, rid):
    return next(r for r in panel_doc["rows"] if r["id"] == rid)


def labels(payload):
    return json.dumps(payload)


# ── Board 1 ────────────────────────────────────────────────────────────────
def reentry_inputs():
    packets = {"rows": [{"symbol": "ALFA", "state": "BUY_READY", "entry_low": 10.0, "entry_high": 11.5, "price": 10.4,
                         "stop": 9.1, "target": 14.0, "rr_plan": 2.6, "saved_at": (NOW - timedelta(hours=3)).isoformat()},
                        {"symbol": "BETA", "state": "ENTRY_NEAR", "entry_low": None, "entry_high": None,
                         "saved_at": (NOW - timedelta(hours=5)).isoformat()}],
               "stale": [{"symbol": "OLDY", "state": "BUY_READY", "packet_age_h": 90}], "max_age_h": 48}
    truth = {"portfolio": {"quote_as_of": (NOW - timedelta(minutes=20)).isoformat()},
             "regime": {"label": "Fixture regime", "as_of": (NOW - timedelta(hours=40)).isoformat(), "gap": None}}
    stances = {"ALFA": {"stance": "ADD", "conviction": 71, "gap": None}, "BETA": {"stance": None, "gap": {"reason": "x"}}}
    exits = {"ok": True, "rows": [
        {"event_key": "e1", "symbol": "GAMA", "trade_date": (NOW - timedelta(days=3)).date().isoformat(), "proceeds_usd": 12500, "account": "fixture_ira"},
        {"event_key": "e2", "symbol": "DELT", "trade_date": (NOW - timedelta(days=10)).date().isoformat(), "proceeds_usd": 800},
        {"event_key": "e3", "symbol": "OLDX", "trade_date": (NOW - timedelta(days=90)).date().isoformat(), "proceeds_usd": 50}]}
    prefs = [{"key": "portfolio.reentry.event-classifications.v1", "value": {"e1": {"eventType": "stopped_out", "reason": "stop hit"}, "e3": {"eventType": "trim"}}},
             {"key": "portfolio.reentry.resistance.v1", "value": {"generated_at": (NOW - timedelta(hours=2)).isoformat(), "symbol_count": 1,
                                                                   "symbols": {"GAMA": {"state": "TESTING", "resistance": 52.0, "distance_pct": -1.2}}}}]
    return packets, truth, stances, exits, prefs


def test_reentry_ready_now_hides_stale_packets_and_uses_cio_stance(tmp_path):
    packets, truth, stances, exits, prefs = reentry_inputs()
    write(tmp_path / "data/runtime/pro_analyst_pills_latest.json", {"updated_at": NOW.isoformat(), "symbol_count": 2,
          "pills": [{"symbol": "ALFA", "target_mean_price": 15.25, "number_of_analyst_opinions": 9}]})
    db = FakeDb({"FROM ui_prefs": prefs})
    out = desk.reentry_payload(root=tmp_path, db_query=db, now=NOW, packets=packets, truth=truth, stances=stances, exits=exits, states=REG)
    ready = panel(out, "ready-now", "ready")
    assert [r["label"] for r in ready["rows"][:2]] == ["ALFA · zone $10.00–$11.50", "BETA · zone not on file"]
    assert "OLDY" not in labels(ready)
    assert "1 packet older than 48 h is hidden here and kept in history." == ready["gap"]
    alfa = row(ready, "pkt-ALFA")["detail"]["fields"]
    assert {"label": "CIO stance (cio_truth)", "value": "ADD · conviction 71"} in alfa
    beta = row(ready, "pkt-BETA")["detail"]["fields"]
    assert {"label": "CIO stance (cio_truth)", "value": "CIO stance not on file"} in beta
    cls = panel(out, "ready-now", "classification")
    assert row(cls, "cls-stopped")["value"] == "1" and row(cls, "cls-saved")["value"] == "2"
    assert row(cls, "cls-res")["value"] == "2"  # DELT and OLDX have no resistance level; GAMA does
    work = panel(out, "exits-review", "workbench")
    assert [r["label"].split(" sold")[0] for r in work["rows"]] == ["GAMA", "DELT"]  # 30-day window
    assert {"label": "Reclaim price vs now", "value": "not measured"} in work["rows"][0]["detail"]["fields"]
    analyst = panel(out, "analyst-evidence", "analyst")
    assert row(analyst, "an-ALFA")["value"] == "$15.25"
    assert {"label": "Revisions, 30 days", "value": "not measured"} in row(analyst, "an-ALFA")["detail"]["fields"]
    titles = [d["title"] for d in out["decisions"]]
    assert "Market regime (CIO): writer market-regime-classifier RETIRED" in titles
    assert any("older than 48 h" in t for t in titles)
    owned = panel(out, "ready-now", "owned")
    assert {r["href"] for r in owned["rows"]} == {"/portfolio?tab=Look-through", "/rotation", "/watch"}
    assert all(s.startswith("SELECT") for s in db.seen)


def test_reentry_unreadable_sources_are_named_gaps_not_zeros(tmp_path):
    out = desk.reentry_payload(root=tmp_path, db_query=None, now=NOW, packets=None, truth=None, stances=None, exits=None, states=None)
    cls = panel(out, "ready-now", "classification")
    assert row(cls, "cls-stopped")["value"] == "not on file"
    assert panel(out, "ready-now", "ready")["gap"] == "The buy-ready packet index could not be read."
    assert panel(out, "exits-review", "workbench")["gap"] == "Sell history could not be read."
    src = {s["id"]: s for s in out["sources"]}
    assert src["analyst"]["gap"] == "pro_analyst_pills_latest.json is not on file."
    assert src["holdings"]["as_of"] is None and src["holdings"]["gap"]
    assert '"value": "0"' not in labels(panel(out, "ready-now", "classification"))


def test_dividend_naive_clock_is_not_promoted_to_an_instant(tmp_path):
    write(tmp_path / "data/portfolios/state/dividend_calendar.json", {"last_updated": "2026-10-23 07:41"})
    out = desk.reentry_payload(root=tmp_path, now=NOW, states=REG)
    div = next(s for s in out["sources"] if s["id"] == "dividends")
    assert div["as_of"] is None and "without a time zone" in div["gap"]


# ── Board 2 ────────────────────────────────────────────────────────────────
def test_strategy_uses_leaderboard_ranking_and_reads_readiness_file_without_recompute(tmp_path):
    write(tmp_path / "data/paper_trading/paper_trade_statistics_latest.json",
          {"timestamp": (NOW - timedelta(hours=2)).isoformat(), "level": "P1_EARLY_SIGNAL", "closed_usable": 157, "win_rate": 51.2})
    lb = {"leaderboard": [{"strategy_id": "fixture_breakout", "rank": 1, "live": {"n": 12, "wins": 7, "win_rate": 58.3, "total_pnl": 412.5, "avg_r": 0.4},
                           "snapshot": {"snapshot_date": "2026-10-22"}, "backtest": None},
                          {"strategy_id": "fixture_fade", "rank": 2, "live": {"n": 4, "wins": 1, "win_rate": 25.0, "total_pnl": -90, "avg_r": -0.3}}]}
    db = FakeDb({"max(snapshot_date) AS d, count(DISTINCT": [{"d": "2026-10-22", "n": 10}],
                 "strategy_state_transitions": [], "FROM incubator_universe": [{"total": 200, "active": 150, "promoted": 10, "updated_at": NOW - timedelta(hours=6)}],
                 "count(*) AS n, max(created_at) AS latest": [{"n": 100, "latest": NOW - timedelta(hours=4)}],
                 "candidate_setup_advisory": [{"n": 800, "d": "2026-10-24"}]})
    out = desk.strategy_payload(root=tmp_path, db_query=db, now=NOW, leaderboard=lb, states=REG)
    board = panel(out, "leaderboard", "leaderboard")
    assert board["rows"][0]["label"] == "fixture breakout · win 58.3% · 12 trades" and board["rows"][0]["value"] == "+$412"
    assert board["rows"][1]["value"] == "−$90" and board["rows"][1]["tone"] == "bad"
    ready = panel(out, "leaderboard", "readiness")
    assert row(ready, "rd-closed")["value"] == "157 / 2,000" and row(ready, "rd-phase")["value"] == "P1 EARLY SIGNAL"
    src = {s["id"]: s for s in out["sources"]}
    assert src["snapshots"]["as_of"] is None and "date only" in src["snapshots"]["gap"]
    assert src["readiness"]["lane_ids"] == [] and src["incubator"]["label"] == "Incubator · 200 names · 10 promoted"
    assert any(d["id"] == "writer-readiness" and d["title"] == "Readiness: no scheduled writer" for d in out["decisions"])
    assert "No strategy changed state in 30 days" in panel(out, "desk", "desk")["gap"]
    planner = panel(out, "planner", "planner")
    assert planner["rows"][0]["href"] == "/strategy/classic?tab=Planner"
    assert not (tmp_path / "data/paper_trading/paper_trade_statistics_latest.json.tmp").exists()
    assert all(s.startswith(("SELECT", "WITH")) for s in db.seen)


def test_strategy_failed_reads_never_render_as_zero(tmp_path):
    out = desk.strategy_payload(root=tmp_path, db_query=FakeDb({"": None}), now=NOW, leaderboard={"error": "db down", "leaderboard": []}, states=REG)
    inc = panel(out, "incubator", "incubator")
    assert row(inc, "inc-cand")["value"] == "not on file" and inc["gap"] == "The incubator could not be read."
    assert panel(out, "leaderboard", "leaderboard")["gap"] == "db down"
    assert row(panel(out, "desk", "desk"), "st-count")["value"] == "not on file"


# ── Board 3 ────────────────────────────────────────────────────────────────
def defense_tree(root: Path):
    rt = root / "data/runtime"
    write(rt / "sector_momentum_latest.json", {"generated_at": (NOW - timedelta(hours=3)).isoformat(),
          "transitions_today": [{"sector": "Technology", "etf": "XLK", "from": "LEADING", "to": "WEAKENING"}]})
    write(rt / "industry_momentum_latest.json", {"captured_at": NOW.isoformat(), "industries": [{}] * 144})
    write(rt / "defense_recommendations_latest.json", {"generated_at": NOW.isoformat(), "mode": "SHADOW",
          "groups": {"protect": [{}, {}], "short_side": [{"title": "HEDGE · PSQ", "instruments": [{"symbol": "PSQ", "kind": "inverse ETF"}]}]}})
    write(rt / "inverse_stoplights_latest.json", {"generated_at": NOW.isoformat(), "candidates": [
        {"inverse": "SH", "bench": "SPY", "leverage": "-1x", "lights": {"THESIS": {"state": "RED", "reason": "no thesis"}, "EXIT": {"state": "GREEN"}}}]})
    write(rt / "options_lifecycle_latest.json", {"generated_at": "2026-10-14T19:40:03+00:00", "counts": {"open_strategies": 0, "action_now": 0}})
    write(rt / "defense_cash_alternatives_latest.json", {"generated_at": "2026-08-06T14:58:59+00:00",
          "top3": [{"symbol": "SGOV", "category": "t-bill", "yield_data": {"sec_yield": 4.31}}]})
    write(root / "config/promote_criteria.json", {"criteria_locked": True, "locked_at": "2026-07-18T22:57", "amendments": [], "decisions": [1, 2]})


def test_defense_book_comes_from_cio_truth_and_unmeasured_fields_say_so(tmp_path):
    defense_tree(tmp_path)
    truth = {"regime": {"label": "Fixture regime", "as_of": NOW.isoformat()},
             "positions": {"rows": [{"symbol": "ALFA", "account_id": "fixture_ira", "account_label": "Fixture IRA", "market_value": 50000,
                                     "stop_state": "pending_activation", "stop_source": "broker_resting", "broker_protected": False},
                                    {"symbol": "BETA", "account_id": "fixture_tax", "account_label": "Fixture taxable", "market_value": 9000,
                                     "stop_state": "active", "stop_source": "broker_resting", "stop_price": 40, "broker_protected": True}],
                           "unprotected_value_usd": 50000},
             "stops": {"unprotected_count": 1}}
    before = tree_digest(tmp_path)
    out = desk.defense_payload(root=tmp_path, now=NOW, truth=truth, states=REG)
    assert tree_digest(tmp_path) == before
    book = panel(out, "your-book", "book")
    assert row(book, "bk-ALFA-fixture_ira")["value"] == "$50,000 · stop pending activation"
    assert row(book, "bk-hedged")["value"] == "not measured" and row(book, "bk-exposed")["value"] == "not measured"
    assert row(book, "bk-unprot")["value"] == "1"
    act = panel(out, "where-to-act", "act")
    assert row(act, "act-regime")["value"] == "Fixture regime"
    assert row(act, "act-trans")["value"] == "1 sector"
    assert row(act, "act-sectors")["href"] == "/watch?tab=sectors"
    opts = panel(out, "hedges", "options")
    assert "options-lifecycle-run is PAUSED" in opts["gap"] and "2026-10-14" in opts["gap"]
    cash = panel(out, "hedges", "cash")
    assert cash["gap"] == "No job writes this file: it has no scheduled writer."
    assert row(cash, "ca-SGOV")["value"] == "4.31%"
    lights = panel(out, "hedges", "stoplights")
    assert lights["rows"][0]["tone"] == "bad"
    titles = [d["title"] for d in out["decisions"]]
    assert "Options lifecycle: writer options-lifecycle-run PAUSED" in titles
    assert "Cash alternatives: no scheduled writer" in titles
    assert any("Review console last locked" in t for t in titles)


def test_projection_code_never_imports_execution_or_side_effecting_helpers():
    import ast

    tree = ast.parse((ROOT / "scripts/lib/desks_a.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert imported <= {"__future__", "json", "math", "datetime", "pathlib", "typing"}, imported
    for forbidden in ("defense_execution", "place_order", "subprocess", "ensure_tables", "atomic_write_json_soft",
                      "compute_statistics", "ensure_analyst_batch", "write_text", "write_bytes", "unlink", "mkdir", "commit"):
        assert forbidden not in names, forbidden
    opens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "open"]
    assert opens and all(c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == "rb" for c in opens)


# ── Board 4 ────────────────────────────────────────────────────────────────
def test_agents_run_timeline_reads_producer_journals_by_record_time(tmp_path):
    journals = tmp_path / "data/runtime/agent_runtime_journals"
    older = write(journals / "alex/alex-aaa.jsonl", json.dumps({"run_id": "alex-aaa", "agent_id": "alex", "job_type": "wake_event_bus",
                                                                "ts": "2026-10-25T13:00:00Z"}) + "\n")
    newer = write(journals / "steph/steph-bbb.jsonl", json.dumps({"run_id": "steph-bbb", "agent_id": "steph", "job_type": "review",
                                                                  "model_error": "PROVIDER_BLOCKED: fixture", "ts": "2026-10-25T13:30:00Z"}) + "\n")
    os.utime(older, (2_000_000_000, 2_000_000_000))  # newest mtime but older record: mtime is not the clock
    os.utime(newer, (1_000_000_000, 1_000_000_000))
    write(tmp_path / "data/cio/aif_memory.jsonl", "\n".join(json.dumps(r) for r in [
        {"memory_id": "m1", "status": "ACTIVE", "memory_type": "CASE_SUMMARY", "created_at": "2026-10-24T01:00:00+00:00"},
        {"memory_id": "m1", "status": "ACTIVE", "memory_type": "CASE_SUMMARY", "created_at": "2026-10-25T01:00:00+00:00"},
        {"memory_id": "m2", "status": "RETRACTED", "memory_type": "LESSON", "created_at": "2026-10-20T01:00:00+00:00"}]) + "\n")
    write(tmp_path / "data/cio/aif_memory_admissions.jsonl", json.dumps({"display_status": "ADMITTED", "admitted_at": "2026-10-25T02:00:00+00:00"}) + "\n")
    write(tmp_path / "data/runtime/advisory_kb_lessons.jsonl", json.dumps({"id": "l1", "ts": "2026-10-09T22:36:02+00:00", "title": "Fixture lesson", "embedding": [0.1] * 4}) + "\n")
    db = FakeDb({"FROM watchlist_agent_jobs": [{"completed": 107, "failed": 2, "queued": 3, "processing": 0, "total": 112, "newest": NOW}],
                 "agent_calibration_windows": [{"agent_name": "alex", "brier_score": 0.12, "resolved": 40, "low_sample_size": False, "created_at": NOW - timedelta(days=7)},
                                               {"agent_name": "morgan", "brier_score": 0.31, "resolved": 22, "low_sample_size": False, "created_at": NOW - timedelta(days=7)},
                                               {"agent_name": "tiny", "brier_score": 0.01, "resolved": 2, "low_sample_size": True, "created_at": NOW - timedelta(days=7)}],
                 "paper_trade_multi_reviews": [{"newest": NOW - timedelta(days=2), "n": 5}]})
    out = desk.agents_payload(root=tmp_path, db_query=db, now=NOW, states=REG)
    tl = panel(out, "runtime", "timeline")
    assert [r["label"] for r in tl["rows"][1:]] == ["steph · review", "alex · wake event bus"]
    assert row(tl, "run-total")["value"] == "2" and tl["gap"] == "1 of the 2 newest runs recorded a model error."
    src = {s["id"]: s for s in out["sources"]}
    assert src["timeline"]["as_of"] == "2026-10-25T13:30:00+00:00"
    rt = panel(out, "runtime", "runtime")
    assert row(rt, "rt-done")["value"] == "107" and row(rt, "rt-failed")["tone"] == "bad"
    assert row(rt, "rt-catalog")["value"] == "2 registered · 1 active"
    cal = panel(out, "calibration", "calibration")
    assert row(cal, "cal-best")["value"] == "alex · 0.120" and row(cal, "cal-worst")["value"] == "morgan · 0.310"
    mem = panel(out, "memory", "memory")
    assert row(mem, "mem-records")["value"] == "2" and row(mem, "mem-active")["value"] == "1" and row(mem, "mem-today")["value"] == "1"
    assert row(panel(out, "learning", "learning"), "ln-newest")["value"] == "2026-10-09 22:36 UTC"
    assert "embedding" not in labels(out)
    assert all(s.startswith("SELECT") for s in db.seen)


def test_gate_b_placeholder_is_pinned_to_the_producer_text():
    """desks_a mirrors the sentinel text instead of importing the producer; this pin makes drift fail CI."""
    import ast

    src = ROOT / "scripts/agent_runtime_live_providers.py"
    fn = next(n for n in ast.walk(ast.parse(src.read_text(encoding="utf-8")))
              if isinstance(n, ast.FunctionDef) and n.name == "_build_governed_gateway_provider")
    errors = [v for d in ast.walk(fn) if isinstance(d, ast.Dict)
              for k, v in zip(d.keys, d.values) if isinstance(k, ast.Constant) and k.value == "error"]
    assert len(errors) == 1 and isinstance(errors[0], ast.Constant), "Gate-B sentinel no longer returns one literal error"
    assert errors[0].value == desk.GATE_B_PLACEHOLDER
    assert desk.run_model_state({"model_error": desk.GATE_B_PLACEHOLDER}) == "gate_b"
    assert desk.run_model_state({"model_error": desk.GATE_B_PLACEHOLDER[:-1]}) == "error"
    assert desk.run_model_state({"model_error": "PROVIDER_BLOCKED: fixture"}) == "error"
    assert desk.run_model_state({"model_error": None}) == desk.run_model_state({}) == "none"


def gate_b_journals(tmp_path, *, shadow_runs=3):
    """alex/morgan carry the Gate-B placeholder (retrieval_count 0); steph records a real model error."""
    journals = tmp_path / "data/runtime/agent_runtime_journals"
    for agent in ("alex", "morgan"):
        for i in range(shadow_runs):
            write(journals / f"{agent}/{agent}-g{i}.jsonl", json.dumps({
                "run_id": f"{agent}-g{i}", "agent_id": agent, "job_type": "wake_event_bus", "environment": "shadow",
                "retrieval_count": 0, "model_error": desk.GATE_B_PLACEHOLDER, "authority": "READ_ONLY_ADVISORY",
                "ts": (NOW - timedelta(minutes=15 * (i + 1))).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
    write(journals / "alex/alex-old.jsonl", json.dumps({"run_id": "alex-old", "agent_id": "alex", "job_type": "wake_event_bus",
                                                        "retrieval_count": 0, "model_error": desk.GATE_B_PLACEHOLDER,
                                                        "ts": (NOW - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
    write(journals / "steph/steph-err.jsonl", json.dumps({"run_id": "steph-err", "agent_id": "steph", "job_type": "review",
                                                          "retrieval_count": 4, "model_error": "TimeoutError: provider fixture",
                                                          "ts": (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
    return journals


def test_agents_gate_b_runs_are_neutral_and_real_errors_stay_red(tmp_path):
    gate_b_journals(tmp_path)
    out = desk.agents_payload(root=tmp_path, db_query=None, now=NOW, states=REG)
    tl = panel(out, "runtime", "timeline")
    # 8 newest: 1 real error + 7 Gate-B; the 30 h-old alex run is in the timeline but outside the 24 h window.
    assert row(tl, "run-total")["value"] == "8"
    gate = row(tl, "run-gate-b")
    assert gate["label"] == "No model by design" and gate["tone"] == "info"
    assert gate["value"] == "7 of 8 newest runs"
    assert gate["detail"]["title"] == desk.GATE_B_STATE
    fields = {f["label"]: f["value"] for f in gate["detail"]["fields"]}
    assert fields["Provider contacted"] == "no" and fields["Recorded text"] == desk.GATE_B_PLACEHOLDER
    assert fields["alex · last 24 h"] == "3 runs · 3 no model · 3 with retrieval_count 0"
    assert fields["morgan · last 24 h"] == "3 runs · 3 no model · 3 with retrieval_count 0"
    assert "steph · last 24 h" not in fields
    # Only the real error is red and counted as a model error.
    assert row(tl, "run-steph-err")["tone"] == "bad"
    assert {row(tl, f"run-{a}-g0")["tone"] for a in ("alex", "morgan")} == {"info"}
    assert tl["gap"] == "1 of the 8 newest runs recorded a model error."
    shadow = {f["label"]: f["value"] for f in row(tl, "run-morgan-g0")["detail"]["fields"]}
    assert shadow["Model"] == desk.GATE_B_STATE and "Model error" not in shadow
    real = {f["label"]: f["value"] for f in row(tl, "run-steph-err")["detail"]["fields"]}
    assert real["Model error"] == "TimeoutError: provider fixture"
    decisions = {d["id"]: d for d in out["decisions"]}
    assert decisions["runs-model-error"]["title"] == "1 recent agent run recorded a model error"
    gd = decisions["runs-gate-b-shadow"]
    assert gd["title"] == "tradeai-agent-runtime@{alex,morgan} timers: 6 runs in the last 24 h, no model by design"
    assert "6 of these runs carry the Gate-B placeholder" in gd["detail"] and "6 recorded retrieval_count 0" in gd["detail"]
    assert "pause or slow these timers, or to wire these agents to the CIO governed bridge" in gd["detail"]
    assert gd["href"] == "/agents?tab=runtime&detail=timeline:run-gate-b"
    for word in ("recommend", "should", "suggest"):
        assert word not in gd["detail"].lower()


def test_agents_all_gate_b_is_not_a_model_error(tmp_path):
    journals = gate_b_journals(tmp_path)
    (journals / "steph/steph-err.jsonl").unlink()
    out = desk.agents_payload(root=tmp_path, db_query=None, now=NOW, states=REG)
    tl = panel(out, "runtime", "timeline")
    assert tl["gap"] is None
    assert "runs-model-error" not in {d["id"] for d in out["decisions"]}
    assert not [r for r in tl["rows"] if r["tone"] == "bad"]
    assert "model error" not in json.dumps(out["decisions"]).lower()


def test_desks_a_fixture_agents_projection_shows_neutral_and_red_runs():
    fixture = json.loads((ROOT / "apps/command-center-v3/e2e/fixtures/desksA.fixture.json").read_text(encoding="utf-8"))
    agents = fixture["projections"]["agents"]
    tl = panel(agents, "runtime", "timeline")
    assert row(tl, "run-gate-b")["tone"] == "info"
    assert any(r["tone"] == "bad" for r in tl["rows"]) and any(r["tone"] == "info" and r["id"] != "run-gate-b" for r in tl["rows"])
    assert {"runs-model-error", "runs-gate-b-shadow"} <= {d["id"] for d in agents["decisions"]}
    assert desk.GATE_B_PLACEHOLDER in json.dumps(agents)


def test_agents_missing_stores_are_gaps(tmp_path):
    out = desk.agents_payload(root=tmp_path, db_query=None, now=NOW, states=None)
    assert panel(out, "runtime", "timeline")["gap"] == "The agent run journals are not on file."
    assert panel(out, "memory", "memory")["gap"] == "The durable memory ledger is not on file."
    assert row(panel(out, "calibration", "calibration"), "cal-best")["value"] == "not measured"


# ── shared contract ─────────────────────────────────────────────────────────
def test_select_only_and_unknown_desk_rejected():
    with pytest.raises(ValueError):
        desk._select(lambda *a: [], "CREATE TABLE x (a int)")
    with pytest.raises(ValueError):
        desk.build("nope", root=Path("."))


@pytest.mark.parametrize("name", desk.DESKS)
def test_every_desk_payload_is_small_and_shaped_for_the_frame(tmp_path, name):
    out = desk.build(name, root=tmp_path, now=NOW, states=REG)
    assert out["read_only"] is True and out["financial_action"] is False
    assert len(json.dumps(out)) < 500_000
    for s in out["sources"]:
        assert set(s) >= {"id", "label", "as_of", "lane_ids", "gap"}
        assert s["as_of"] is None or s["as_of"].endswith("+00:00")
    for tab in out["tabs"].values():
        for p in tab["panels"]:
            for r in p["rows"]:
                assert r["label"] and r["value"] not in (None, "", "None", "nan")


def test_tabs_match_the_approved_boards():
    expected = {"reentry": ["ready-now", "exits-review", "resistance-levels", "analyst-evidence"],
                "strategy": ["leaderboard", "plan-vs-performance", "planner", "desk", "incubator", "backtests"],
                "defense": ["where-to-act", "your-book", "hedges", "review-log"],
                "agents": ["runtime", "learning", "calibration", "memory", "promotion-cases", "legacy-analytics"]}
    for name, tabs in expected.items():
        assert list(desk.build(name, root=Path("/nonexistent"), now=NOW, states=REG)["tabs"]) == tabs
        page = {"reentry": "ReEntryDesk", "strategy": "StrategyDesk", "defense": "DefenseDesk", "agents": "AgentsDesk"}[name]
        text = (ROOT / f"apps/command-center-v3/src/pages/desks/{page}.tsx").read_text(encoding="utf-8")
        for tab in tabs:
            assert f"id: '{tab}'" in text


def test_route_is_get_only_and_rail_opens_new_desks_with_classic_kept():
    import api_v2

    assert api_v2.handle("/api/v2/desks/strategy", "POST")[0] == 405
    assert api_v2.handle("/api/v2/desks/not-a-desk", "GET")[0] == 404
    app = (ROOT / "apps/command-center-v3/src/App.tsx").read_text(encoding="utf-8")
    for route, page in (("portfolio/re-entry", "ReEntryDesk"), ("strategy", "StrategyDesk"), ("defense", "DefenseDesk"), ("agents", "AgentsDesk")):
        assert f'path="{route}" element={{<RouteErrorBoundary route="/v3/{route}"><{page}' in app
        assert f'path="{route}/classic"' in app
    rail = (ROOT / "apps/command-center-v3/src/components/NavRail.tsx").read_text(encoding="utf-8")
    for to in ("/portfolio/re-entry", "/defense", "/strategy", "/agents"):
        assert f"{{ to: '{to}'" in rail


def test_board13_duplicates_replaced_by_links():
    src = ROOT / "apps/command-center-v3/src"
    journal = (src / "pages/JournalHub.tsx").read_text(encoding="utf-8")
    assert "<BacktestPanel" not in journal and "/v3/strategy?tab=backtests" in journal
    rotation = (src / "pages/RotationIntelligence.tsx").read_text(encoding="utf-8")
    assert "Ask the Rotation Advisor" not in rotation and "/v3/cio/questions" in rotation
    strategy = (src / "pages/desks/StrategyDesk.tsx").read_text(encoding="utf-8")
    assert "<BacktestPanel" in strategy
    reentry = (src / "pages/desks/ReEntryDesk.tsx").read_text(encoding="utf-8")
    assert "ReEntryAnalystLookthroughBoard" not in reentry and "ReEntryRotationWorkspace" not in reentry
