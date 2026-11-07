"""HERMES_GRAFT_BASELINE_20261107 — the graft gate counts only evidence measured against the live weights (LQ-20261107-213).

The outcome writer compared its shadow weights against whatever yaml the serving release carried. When a
release served the v9 seed instead of the learned weights, the live spread collapsed and the shadow "won",
so those days were marked eligible=1; weekend reruns on unchanged inputs counted as extra days; and the
tuner grafted those suggestions onto a different baseline. Each row now names the weights it was measured
against and its input set, and the gate/graft/governor read only rows whose baseline is the live one.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib import hermes_score_weights as store  # noqa: E402

V9 = {"technical_momentum": 0.06, "setup_quality": 0.008, "analyst": 0.44, "social_sentiment": 0.10,
      "sector_strength": 0.045, "news_catalyst": 0.10, "risk_reward": 0.09, "hermes_research": 0.055,
      "options_edge": 0.045, "thesis_outcome": 0.057}
V20 = {"technical_momentum": 0.0098, "setup_quality": 0.0098, "analyst": 0.4962, "social_sentiment": 0.0344,
       "sector_strength": 0.0861, "news_catalyst": 0.0898, "risk_reward": 0.1211, "hermes_research": 0.0536,
       "options_edge": 0.0438, "thesis_outcome": 0.0555}


def _like(pattern: str, text: str) -> bool:
    """SQL LIKE (no escapes in our patterns): % = any run, _ = any one char."""
    rx = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern)
    return re.fullmatch(rx, text, flags=re.S) is not None


def _pairs(n=40, shift=0.0):
    out = []
    for i in range(n):
        comp = {"analyst": {"score": 30 + i}, "risk_reward": {"score": 70 - i},
                "technical_momentum": {"score": 50}}
        out.append((comp, (i - n / 2) / n + shift))
    return out


class _Cur:
    def __init__(self):
        self.rows = []

    def execute(self, sql, params=None):
        if "INSERT INTO hermes_weight_calibration" in sql:
            self.rows.append(params)


def _write(monkeypatch, weights, pairs):
    import hermes_outcome_learning as OL

    monkeypatch.setattr(OL, "_pairs", lambda cur, tw: pairs)
    monkeypatch.setattr(OL, "_live_weights", lambda: dict(weights))
    cfg = {"weights": {"trade_weight": 1, "min_hi": 1, "min_lo": 1, "max_step": 0.02, "quantile": 0.2}}
    cur = _Cur()
    res = OL.calibrate_weights(cur, cfg, apply=True)
    return res, cur.rows


def test_writer_rows_name_their_baseline_and_inputs(monkeypatch):
    res, rows = _write(monkeypatch, V20, _pairs())
    assert rows and res["weights_fingerprint"] == store.weights_fingerprint(V20)
    rationale = rows[0][5]
    assert rationale.startswith("OUTCOME_LEDGER|eligible=")
    assert f"|weights={store.weights_fingerprint(V20)}|inputs={res['inputs_fingerprint']}" in rationale


def test_gate_pattern_matches_only_rows_measured_against_the_live_weights(monkeypatch):
    res, rows = _write(monkeypatch, V20, _pairs())
    rationale = rows[0][5].replace("eligible=0", "eligible=1")  # the pattern also requires eligible=1
    assert _like(store.eligible_evidence_pattern(store.weights_fingerprint(V20)), rationale)
    # a row measured while a release served the v9 seed does not count toward a graft of v20
    assert not _like(store.eligible_evidence_pattern(store.weights_fingerprint(V9)), rationale)
    # a pre-fix row (no baseline tag) never counts
    legacy = "OUTCOME_LEDGER|eligible=1|live_spread=0.00143|shadow_spread=0.01898"
    assert not _like(store.eligible_evidence_pattern(store.weights_fingerprint(V20)), legacy)
    assert not _like(store.eligible_evidence_pattern(store.weights_fingerprint(V9)), legacy)


def test_unchanged_inputs_share_one_fingerprint_new_outcomes_do_not(monkeypatch):
    import hermes_outcome_learning as OL

    p = _pairs()
    assert OL._inputs_fingerprint(p) == OL._inputs_fingerprint(list(reversed(p)))  # order-free (weekend rerun)
    assert OL._inputs_fingerprint(p) != OL._inputs_fingerprint(_pairs(shift=0.01))
    assert OL._inputs_fingerprint(p) != OL._inputs_fingerprint(_pairs(n=41))


def test_fingerprint_is_the_weight_vector_not_the_document():
    assert store.weights_fingerprint(V20) == store.weights_fingerprint(dict(reversed(list(V20.items()))))
    assert store.weights_fingerprint(V20) != store.weights_fingerprint(V9)
    assert store.weights_fingerprint({"analyst": 0.44}) == store.weights_fingerprint({"analyst": 0.44000001})


def test_days_sql_counts_a_rerun_on_unchanged_inputs_once():
    sql = " ".join(store.ELIGIBLE_EVIDENCE_DAYS_SQL.split())
    assert "count(DISTINCT created_at::date)" in sql
    assert "NOT EXISTS" in sql and "e.created_at::date < c.created_at::date" in sql
    assert sql.count("%s") == 3


class _GateCur:
    def __init__(self, days):
        self.log = []
        self.days = days
        self._q = ""

    def execute(self, sql, params=None):
        self._q = " ".join(sql.split())
        self.log.append((self._q, params))

    def fetchone(self):
        if "count(DISTINCT created_at::date)" in self._q:
            return (self.days,)
        if "jsonb_array_elements" in self._q:
            return (0, 0)
        return None

    def fetchall(self):
        return [("analyst", 0.60, 0.42)] if "DISTINCT ON (factor)" in self._q else []


@pytest.fixture
def tune(monkeypatch):
    import hermes_autonomous_self_tune as ST

    monkeypatch.setattr(ST, "_load_weights", lambda: ({"version": 20, "weights": dict(V20)}, "config_documents"))
    monkeypatch.setattr(ST, "_LEARN_ONLY", False)
    return types.SimpleNamespace(mod=ST, pattern=store.eligible_evidence_pattern(store.weights_fingerprint(V20)))


def test_gate_and_graft_read_only_evidence_against_the_live_baseline(tune):
    cur = _GateCur(days=6)
    res = tune.mod.auto_graft_weights(cur, apply=False, audit_present=False)
    assert res["status"] == "dry" and res["changes"]
    gate_sql, gate_params = cur.log[0]
    assert "count(DISTINCT created_at::date)" in gate_sql
    assert gate_params == (tune.pattern, tune.mod.GRAFT_ELIGIBLE_WINDOW_DAYS, tune.pattern)
    picks = [p for q, p in cur.log if "DISTINCT ON (factor)" in q]
    assert picks == [(tune.pattern,)]  # suggestions come from the same baseline, never any eligible row
    for q, _p in cur.log:
        assert "LIKE 'OUTCOME_LEDGER|eligible=1%" not in q  # the untagged-prefix match is gone


def test_gate_reports_the_baseline_it_measured(tune):
    res = tune.mod.auto_graft_weights(_GateCur(days=3), apply=False, audit_present=False)
    assert res["status"] == "gated_persistence" and res["eligible_days"] == 3
    assert res["weights_fingerprint"] == store.weights_fingerprint(V20)
    assert res["weights_source"] == "config_documents"


def test_governor_clamp_pressure_uses_the_same_baseline(monkeypatch):
    import hermes_config_governor as GOV

    monkeypatch.setattr(store, "load", lambda **kw: ({"version": 20, "weights": dict(V20)}, "config_documents"))
    seen = []

    class Cur:
        def execute(self, sql, params=None):
            seen.append((" ".join(sql.split()), params))

        def fetchone(self):
            return (0, 0)

        def fetchall(self):
            return []

    GOV.detect(Cur(), apply=False)
    clamp = [p for q, p in seen if "avg(ABS(suggested_weight - current_weight))" in q]
    pat = store.eligible_evidence_pattern(store.weights_fingerprint(V20))
    assert clamp == [(pat, pat)]
