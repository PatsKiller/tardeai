"""PR-5 (2026-09-28, root cause 3): the pre-open scan was small by design and labelled as failure,
and top-gainer injects without RVOL/gap/float were scored 11–13 and shown as NOGO.

- `assets/screeners.yaml run_windows.<label>.expected_min_symbols` declares each window's own floor;
  `classify_run_health` says PREOPEN_WINDOW_BY_DESIGN (status still RUN_UNDERFILLED — the 40-symbol
  auto-proposal gate is unchanged) when that floor is met, UNIVERSE_TOO_SMALL when it is not.
- `universe_coverage` flags `_enrichment_missing`; `scoring` routes such rows to MANUAL_REVIEW
  (UNENRICHED_INJECT) instead of scoring empty data. GO threshold (40) and the other lanes untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import screener_run_health as srh  # noqa: E402
from unenriched_inject_review import apply_unenriched_inject_fields, qualifies_unenriched_inject  # noqa: E402

CFG = yaml.safe_load((ROOT / "assets/screeners.yaml").read_text())


def test_window_floors_declared():
    rw = CFG["run_windows"]
    assert rw["0400"]["expected_min_symbols"] == 15 and rw["0700"]["expected_min_symbols"] == 20
    assert rw["0900"]["expected_min_symbols"] == 40 and rw["1000"]["expected_min_symbols"] == 40
    assert srh.window_expected_min_symbols("0700", CFG) == 20
    assert srh.window_expected_min_symbols("0900") == 40          # reads the repo yaml
    assert srh.window_expected_min_symbols("nope", CFG) is None


def _stats(symbols, window_min=None, **kw):
    s = {"symbols_scanned": symbols, "raw_rows": symbols + 5, "screener_count": 2, "has_cookie": True,
         "expected_min_symbols": 40}
    if window_min is not None:
        s["window_expected_min_symbols"] = window_min
    s.update(kw)
    return s


def test_0700_with_19_symbols_is_by_design_not_too_small():
    status, reasons = srh.classify_run_health(_stats(19, window_min=15))
    assert status == "RUN_UNDERFILLED" and reasons == ["PREOPEN_WINDOW_BY_DESIGN"]


def test_0700_below_its_own_floor_is_still_too_small():
    status, reasons = srh.classify_run_health(_stats(12, window_min=15))
    assert status == "RUN_UNDERFILLED" and reasons == ["UNIVERSE_TOO_SMALL"]


def test_0900_with_19_symbols_is_too_small():
    status, reasons = srh.classify_run_health(_stats(19, window_min=40))
    assert status == "RUN_UNDERFILLED" and "UNIVERSE_TOO_SMALL" in reasons
    status, reasons = srh.classify_run_health(_stats(19))              # no window floor supplied → legacy
    assert reasons == ["UNIVERSE_TOO_SMALL"]


def test_real_failures_are_never_masked_as_by_design():
    status, reasons = srh.classify_run_health(_stats(19, window_min=15, auth_failed=True))
    assert "FINVIZ_AUTH_FAILED" in reasons and "PREOPEN_WINDOW_BY_DESIGN" not in reasons
    status, reasons = srh.classify_run_health(_stats(19, window_min=15, raw_rows=8))
    assert "ROW_LIMIT_10_DETECTED" in reasons


def test_healthy_and_partial_unchanged():
    assert srh.classify_run_health(_stats(45, window_min=15))[0] == "RUN_HEALTHY"
    assert srh.classify_run_health(_stats(30, window_min=15))[0] == "RUN_PARTIAL"


def test_orchestrator_passes_the_window_floor():
    src = (ROOT / "scripts/trade_ai_orchestrator.py").read_text()
    assert '"window_expected_min_symbols": _window_expected_min(run_label)' in src
    assert "min_symbols=40" in src and "if len(scored) >= min_symbols or allow_underfilled:" in src  # gate unchanged


# ---- unenriched injects

def test_inject_rows_are_flagged_when_rvol_and_gap_are_zero():
    src = (ROOT / "scripts/lib/universe_coverage.py").read_text()
    assert '"_enrichment_missing": bool(float(rvol or 0) == 0 and float(gap or 0) == 0)' in src


def test_unenriched_inject_goes_to_manual_review_never_go():
    row = {"symbol": "KOD", "_enrichment_missing": True}
    scored = {"symbol": "KOD", "decision": "AVOID", "score": 13, "rvol": 0, "float_m": 0, "grade": "D"}
    assert qualifies_unenriched_inject(row, scored)
    apply_unenriched_inject_fields(scored)
    assert scored["decision"] == "MANUAL_REVIEW" and scored["manual_review_reason"] == "UNENRICHED_INJECT"
    assert scored["not_tradeable"] and scored["not_validation_ready"] and scored["awareness_status"] == "UNENRICHED"
    # enriched inject (has RVOL) scores normally
    assert not qualifies_unenriched_inject(row, {"decision": "AVOID", "rvol": 6.2, "float_m": 0})
    # a non-inject with zero data is left to the existing lanes
    assert not qualifies_unenriched_inject({"symbol": "X"}, scored)
    # a GO is never overwritten
    assert not qualifies_unenriched_inject(row, {"decision": "GO", "rvol": 0, "float_m": 0})


def test_scoring_wires_the_lane_before_the_others():
    src = (ROOT / "scripts/scoring.py").read_text()
    assert "from unenriched_inject_review import qualifies_unenriched_inject, apply_unenriched_inject_fields" in src
    i = src.index("if qualifies_unenriched_inject(row, scored):"); j = src.index("elif squeeze_manual:")
    assert i < j
