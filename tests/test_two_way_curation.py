"""Two-way watchlist curation — dry tests for every component, both directions.

These are DETERMINISTIC dry tests: no live database, broker, or LLM. Each two-way
edge is validated with a fake in-memory executor/cursor so the round-trip logic is
provable in CI without any production side effects.

Forward edge (sources -> watchlist):  CIO / advisory / defense mapping + emit + drain.
Reverse edge (outcomes -> watchlist): realized outcome, options edge, hermes research.
P4: graduated autonomy gate.  P3: instrument class resolution.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib import two_way_curation as tc  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# fake executor — simulates db_adapter._execute(sql, params=None, fetch=None)
# ─────────────────────────────────────────────────────────────────────────────
class FakeExecutor:
    def __init__(self):
        self.log: list = []
        self.staged = {t: [] for t in tc.STAGING_TABLE.values()}
        self.directives = {}
        self.audit = []
        self._next_directive = 1000

    def __call__(self, sql, params=None, fetch=None):
        self.log.append((sql, params, fetch))
        sql_u = sql.upper()

        for source, tbl in tc.STAGING_TABLE.items():
            if tbl in sql and "INSERT" in sql_u:
                self.staged[tbl].append({
                    "directive_id": params[0],
                    "symbol": params[1],
                    "thesis": params[2],
                    "source_detail": params[3],
                })
                return True

        if "SELECT ID FROM WATCH_DIRECTIVES" in sql_u and fetch == "one":
            key = (params[0], params[1])
            return [self.directives[key]] if key in self.directives else None

        if "INSERT INTO WATCH_DIRECTIVES" in sql_u:
            key = (params[0], params[1])
            if key not in self.directives:
                self._next_directive += 1
                self.directives[key] = self._next_directive
            return [self.directives[key]]

        if "UPDATE WATCHLIST_ITEMS" in sql_u:
            return True

        if "INSERT INTO CURATION_LOOP_AUDIT" in sql_u:
            self.audit.append({"source": params[0], "event": params[1], "payload": params[2]})
            return True

        for source, tbl in tc.STAGING_TABLE.items():
            if tbl in sql and "DRAINED = FALSE" in sql_u and fetch == "all":
                return self.staged[tbl]

        return None


# ─────────────────────────────────────────────────────────────────────────────
# FORWARD edge — pure mapping
# ─────────────────────────────────────────────────────────────────────────────

def test_cio_defensive_regime_maps_two_edges():
    fb = tc.cio_situation_to_feedback(
        {"situation_type": "S8_DEFENSIVE_REGIME", "rationale": "risk off", "symbols": ["SCHD"]}
    )
    assert len(fb) == 2
    assert {f["directive_kind"] for f in fb} == {"sector", "trend"}


def test_cio_sector_rotation_maps_sectors():
    fb = tc.cio_situation_to_feedback(
        {"situation_type": "S4_SECTOR_ROTATION", "sectors": ["Financials", "Energy"]}
    )
    assert [f["directive_kind"] for f in fb] == ["sector", "sector"]
    assert "Financials" in fb[0]["directive_label"]


def test_cio_cash_deployment_maps_symbols():
    fb = tc.cio_situation_to_feedback(
        {"situation_type": "S5_CASH_DEPLOYMENT", "symbols": ["AAPL", "MSFT"]}
    )
    assert fb[0]["directive_kind"] == "trend"
    assert "AAPL" in fb[0]["spec"]["seed_symbols"]


def test_cio_unknown_situation_maps_nothing():
    assert tc.cio_situation_to_feedback({"situation_type": "S1_POSITION_LIFECYCLE"}) == []


def test_advisory_actionable_with_evidence_emits():
    fb = tc.advisory_verdict_to_feedback("ADD", "NVDA", evidence_count=4, conviction=80)
    assert fb is not None and fb["directive_kind"] == "ticker"
    assert fb["spec"]["symbol"] == "NVDA"


def test_advisory_actionable_without_evidence_is_gated():
    assert tc.advisory_verdict_to_feedback("ADD", "NVDA", evidence_count=1) is None
    assert tc.advisory_verdict_to_feedback("TRIM", "NVDA", evidence_count=0) is None
    # ADD/RE_ENTER allow 2+; TRIM/EXIT still require 3
    assert tc.advisory_verdict_to_feedback("ADD", "NVDA", evidence_count=2) is not None
    assert tc.advisory_verdict_to_feedback("TRIM", "NVDA", evidence_count=2) is None


def test_advisory_non_actionable_never_emits():
    assert tc.advisory_verdict_to_feedback("WAIT", "NVDA", evidence_count=5) is None
    assert tc.advisory_verdict_to_feedback("HOLD", "NVDA", evidence_count=5) is None


def test_advisory_allocation_row_is_gated():
    fb = tc.advisory_verdict_to_feedback("TRIM", "NVDA", row_class="allocation", evidence_count=0)
    assert fb is None


def test_defense_get_into_maps_sector():
    fb = tc.defense_card_to_feedback({"group": "get_into", "symbol": "XLF", "sector": "Financials"})
    assert fb["directive_kind"] == "sector"
    assert fb["spec"]["gics_sector"] == "Financials"


def test_defense_income_maps_ticker():
    fb = tc.defense_card_to_feedback({"group": "income", "symbol": "SCHD"})
    assert fb["directive_kind"] == "ticker"
    assert fb["spec"]["symbol"] == "SCHD"


def test_defense_protect_never_emits():
    assert tc.defense_card_to_feedback({"group": "protect", "symbol": "AAPL"}) is None


# ─────────────────────────────────────────────────────────────────────────────
# FORWARD edge — emit + ensure_directive + round-trip
# ─────────────────────────────────────────────────────────────────────────────

def test_emit_feedback_stages_and_roundtrips():
    ex = FakeExecutor()
    fb = tc.advisory_verdict_to_feedback("ADD", "NVDA", evidence_count=4, conviction=80)
    res = tc.emit_feedback("advisory", fb, executor=ex)
    assert res["ok"] is True
    undrained = tc.undrained_staging("advisory", executor=ex)
    assert len(undrained) == 1
    assert undrained[0]["symbol"] == "NVDA"


def test_emit_rejects_unknown_source():
    assert tc.emit_feedback("bogus", {}, executor=FakeExecutor())["ok"] is False


def test_emit_all_summary_counts():
    ex = FakeExecutor()
    out = tc.emit_all("cio", [
        {"directive_kind": "ticker", "spec": {"symbol": "AAPL"}},
        None,
    ], executor=ex)
    assert out["staged"] == 1 and out["skipped"] == 1 and out["failed"] == 0


def test_ensure_directive_dedupes_by_kind_label():
    ex = FakeExecutor()
    fb = {"directive_kind": "sector", "directive_label": "CIO defensive regime — rotate to defensive",
          "spec": {"gics_sector": "Consumer Defensive"}, "rationale": "risk off"}
    first = tc.ensure_directive("cio", fb, executor=ex)
    second = tc.ensure_directive("cio", fb, executor=ex)
    assert first == second


def test_ensure_directive_rejects_no_kind():
    assert tc.ensure_directive("cio", {"directive_label": "x"}, executor=FakeExecutor()) is None


# ─────────────────────────────────────────────────────────────────────────────
# FORWARD edge — drain via fake cursor
# ─────────────────────────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, staged_rows):
        self._staged = list(staged_rows)
        self._did_lookup = {}
        self._next_id = 500
        self.inserted_directives = []

    def execute(self, sql, params=None):
        self._last = sql
        self._last_params = params

    def fetchall(self):
        if "DRAINED=FALSE" in self._last.upper().replace(" ", ""):
            return list(self._staged)
        return []

    def fetchone(self):
        if "SELECT ID FROM WATCH_DIRECTIVES" in self._last.upper():
            key = (self._last_params[0], self._last_params[1])
            return {"id": self._did_lookup[key]} if key in self._did_lookup else None
        if "RETURNING ID" in self._last.upper():
            self._next_id += 1
            self.inserted_directives.append((self._last_params[0], self._last_params[1]))
            return {"id": self._next_id}


def test_drain_mints_directive_and_promotes():
    staged = [{"id": 1, "directive_id": None, "symbol": "NVDA", "thesis": "Advisory ADD",
               "source_detail": {"directive_kind": "ticker",
                                 "directive_label": "Advisory ADD — NVDA",
                                 "spec": {"symbol": "NVDA"}, "thesis": "Advisory ADD: NVDA"}}]
    cur = FakeCursor(staged)
    calls = []
    report = {}

    def evaluate(sym, did, reason, source, auto):
        calls.append((sym, did, source))
        return {"status": "PROMOTED"}

    def resolve_fn(d):
        return [d["spec"]["symbol"]]

    tc.drain_curation_sources(cur, False, report, evaluate, resolve_fn)
    assert report["promoted"] >= 1
    assert len(calls) >= 1
    assert calls[0][1] is not None and calls[0][1] > 0
    assert len(cur.inserted_directives) >= 1


def test_drain_skips_row_without_kind():
    staged = [{"id": 9, "directive_id": None, "symbol": None, "thesis": None,
               "source_detail": {"no_directive_kind": True}}]
    cur = FakeCursor(staged)
    report = {}

    def evaluate(*a):
        raise AssertionError("must not evaluate a kind-less row")

    tc.drain_curation_sources(cur, False, report, evaluate, lambda d: [])
    assert report["curation_skipped_no_kind"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# REVERSE edge — outcome -> watchlist
# ─────────────────────────────────────────────────────────────────────────────

def test_outcome_verdict_to_ledger_mapping():
    assert tc.outcome_verdict_to_ledger("hit") == ("win", True)
    assert tc.outcome_verdict_to_ledger("miss") == ("loss", False)
    assert tc.outcome_verdict_to_ledger("neutral") == ("scratch", None)
    assert tc.outcome_verdict_to_ledger("ungradeable") == (None, None)


def test_write_realized_outcome():
    res = tc.write_realized_outcome("NVDA", "win", True, executor=FakeExecutor())
    assert res["ok"] is True and res["symbol"] == "NVDA"


def test_write_realized_outcome_requires_symbol():
    assert tc.write_realized_outcome("", "win", True, executor=FakeExecutor())["ok"] is False


def test_options_edge_factor_bounds():
    assert tc.options_edge_factor(None, None) is None
    assert tc.options_edge_factor(50, 70) == 85.0
    assert 0 <= tc.options_edge_factor(100, 0) <= 100


def test_hermes_research_factor():
    assert tc.hermes_research_factor(None) is None
    assert tc.hermes_research_factor(120) == 100.0
    assert tc.hermes_research_factor(-5) == 0.0


def test_options_outcomes_to_conviction_aggregates():
    outcomes = [
        {"symbol": "NVDA", "outcome": "win", "pnl": 120, "iv_rank": 50, "edge_score": 70},
        {"symbol": "NVDA", "outcome": "loss", "pnl": -40, "iv_rank": 50, "edge_score": 70},
        {"symbol": "AMD", "outcome": "win", "pnl": 30, "iv_rank": None, "edge_score": None},
    ]
    conv = tc.options_outcomes_to_conviction(outcomes)
    assert "NVDA" in conv and "AMD" in conv
    assert conv["NVDA"]["n"] == 2
    assert conv["NVDA"]["win_rate"] == 0.5
    assert conv["NVDA"]["net_pnl"] == 80.0
    assert conv["NVDA"]["options_edge"] == 85.0
    assert conv["NVDA"]["conviction_delta"] > 0


def test_options_outcomes_losing_book_nudges_negative():
    outcomes = [{"symbol": "NVDA", "outcome": "loss", "pnl": -100, "iv_rank": 30, "edge_score": 30}]
    conv = tc.options_outcomes_to_conviction(outcomes)
    assert conv["NVDA"]["win_rate"] == 0.0
    assert conv["NVDA"]["conviction_delta"] < 0


def test_write_options_edge():
    assert tc.write_options_edge("NVDA", 85.0, {"n": 2}, executor=FakeExecutor())["ok"] is True


def test_write_hermes_research():
    assert tc.write_hermes_research("NVDA", 60.0, {"source": "hermes"},
                                    executor=FakeExecutor())["ok"] is True


def test_audit_records():
    ex = FakeExecutor()
    tc.audit("options", "folded", {"symbol": "NVDA"}, executor=ex)
    assert ex.audit and ex.audit[0]["event"] == "folded"


def test_hermes_research_score_from_action():
    assert tc.hermes_research_score_from_action("trade") == 90.0
    assert tc.hermes_research_score_from_action("proposal") == 75.0
    assert tc.hermes_research_score_from_action("directive_hit") == 60.0
    assert tc.hermes_research_score_from_action("none") == 15.0
    assert tc.hermes_research_score_from_action(None) is None
    assert tc.hermes_research_score_from_action("bogus") is None


def test_emit_records_audit_trail():
    ex = FakeExecutor()
    fb = tc.advisory_verdict_to_feedback("ADD", "NVDA", evidence_count=4, conviction=80)
    tc.emit_feedback("advisory", fb, executor=ex)
    assert any(a["source"] == "advisory" and a["event"] == "staged" for a in ex.audit)


def test_write_options_edge_records_audit():
    ex = FakeExecutor()
    tc.write_options_edge("NVDA", 85.0, {"n": 2}, executor=ex)
    assert any(a["source"] == "options" and a["event"] == "folded" for a in ex.audit)



# ─────────────────────────────────────────────────────────────────────────────
# P4 — graduated autonomy gate
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_apply_gate_trusted_high_hitrate():
    g = tc.auto_apply_gate("trusted", "aligned", 0.8)
    assert g["auto_apply"] is True and g["action"] == "auto_apply"


def test_auto_apply_gate_blocks_candidate_tier():
    g = tc.auto_apply_gate("candidate", "aligned", 0.9)
    assert g["auto_apply"] is False and g["action"] == "stage_for_review"


def test_auto_apply_gate_blocks_divergent():
    assert tc.auto_apply_gate("trusted", "divergent", 0.9)["auto_apply"] is False


def test_auto_apply_gate_blocks_low_hitrate():
    assert tc.auto_apply_gate("trusted", "aligned", 0.4)["auto_apply"] is False


# ─────────────────────────────────────────────────────────────────────────────
# P3 — instrument class resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_instrument_class():
    assert tc.resolve_instrument_class("AAPL") == "equity"
    assert tc.resolve_instrument_class("SPY") == "etf"
    assert tc.resolve_instrument_class("037833100") == "bond"
    assert tc.resolve_instrument_class("SPAXX") == "cash"
    assert tc.resolve_instrument_class("") == "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Scorer integration (P1 + P5) — factors dropped when absent, present when written
# ─────────────────────────────────────────────────────────────────────────────

def test_scorer_hermes_research_and_options_edge_factors():
    import hermes_watchlist_scorer as hs
    weights = {"technical_momentum": 0.2, "hermes_research": 0.1, "options_edge": 0.1,
               "risk_reward": 0.2, "analyst": 0.3, "thesis_outcome": 0.1}
    wi = {"symbol": "NVDA", "rsi": 55, "trend": "bullish", "price": 100,
          "target_price": 130, "stop_loss": 90}
    comp, components = hs.score_symbol(wi, {}, None, {}, weights)
    assert comp is not None
    assert "hermes_research" not in components
    assert "options_edge" not in components
    assert "thesis_outcome" not in components

    wi2 = dict(wi, hermes_research_score=80, options_edge_score=85,
               realized_outcome="win", thesis_win=True)
    comp2, components2 = hs.score_symbol(wi2, {}, None, {}, weights)
    assert "hermes_research" in components2
    assert "options_edge" in components2
    assert "thesis_outcome" in components2
    assert components2["hermes_research"]["score"] == 80.0
    assert components2["options_edge"]["score"] == 85.0
    assert components2["thesis_outcome"]["score"] == 78.0


def test_scorer_thesis_loss_penalty():
    import hermes_watchlist_scorer as hs
    weights = {"thesis_outcome": 1.0, "analyst": 0.0}
    wi = {"symbol": "X", "realized_outcome": "loss", "thesis_win": False}
    comp, components = hs.score_symbol(wi, {}, None, {}, weights)
    assert "thesis_outcome" in components
    assert components["thesis_outcome"]["score"] == 22.0


# ─────────────────────────────────────────────────────────────────────────────
# P5 — validation.py fold round-trip (fake executor)
# ─────────────────────────────────────────────────────────────────────────────

def test_fold_options_to_underlying():
    from lib.options_pipeline import validation as v
    ex = FakeExecutor()

    def fold_executor(sql, params=None, fetch=None):
        if "SELECT SYMBOL, OUTCOME" in sql.upper():
            return [
                {"symbol": "NVDA", "outcome": "win", "pnl": 100,
                 "edge_score": "70", "iv_rank": "50"},
            ]
        return ex(sql, params, fetch=fetch)

    res = v.fold_options_to_underlying("NVDA", executor=fold_executor)
    assert res["ok"] is True and res["folded"] is True
    assert res["options_edge"] == 85.0


# ─────────────────────────────────────────────────────────────────────────────
# P2 — hermes_outcome_grader.writeback_trade_outcomes (reverse edge round-trip)
# ─────────────────────────────────────────────────────────────────────────────

class OutcomeLedgerCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.updates = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        if sql.upper().startswith("SELECT"):
            return
        self.updates.append((sql, params))
        self.rowcount = 1

    def fetchall(self):
        return self.rows


def test_writeback_trade_outcomes_roundtrip():
    import hermes_outcome_grader as hg
    cur = OutcomeLedgerCursor([
        ("NVDA", "hit"),
        ("MSTR", "miss"),
        ("COIN", "neutral"),
        ("PFE", "ungradeable"),
    ])
    res = hg.writeback_trade_outcomes(cur)
    assert res["outcomes_written"] == 3
    # Updates go through write_realized_outcome (UPDATE + audit INSERT)
    updates = [u for u in cur.updates if u[0] and "UPDATE WATCHLIST_ITEMS" in u[0].upper()]
    written_symbols = {u[1][-1] for u in updates}
    assert "NVDA" in written_symbols and "MSTR" in written_symbols and "COIN" in written_symbols
    assert "PFE" not in written_symbols
    audits = [u for u in cur.updates if u[0] and "CURATION_LOOP_AUDIT" in u[0].upper()]
    assert len(audits) >= 3


def test_writeback_hermes_research_roundtrip():
    import hermes_outcome_grader as hg
    cur = OutcomeLedgerCursor([
        ("NVDA", "trade"),
        ("MSFT", "proposal"),
        ("IBM", "none"),
        ("GME", None),
    ])
    res = hg.writeback_hermes_research(cur)
    assert res["hermes_research_written"] == 3
    updates = [u for u in cur.updates if u[0] and "UPDATE WATCHLIST_ITEMS" in u[0].upper()]
    by_sym = {u[1][-1]: u[1][0] for u in updates}
    assert by_sym["NVDA"] == 90.0
    assert by_sym["MSFT"] == 75.0
    assert by_sym["IBM"] == 15.0
    assert "GME" not in by_sym


