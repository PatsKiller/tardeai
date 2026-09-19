"""Hermetic SLO eval for agent number grounding report."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scripts" / "report_agent_number_grounding.py"


def _load():
    spec = importlib.util.spec_from_file_location("report_agent_number_grounding", SPEC)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_slo_unknown_when_too_few_results(tmp_path):
    m = _load()
    slo = {
        "status": "PROPOSED",
        "floors": {
            "max_ungrounded_share": 0.05,
            "max_soft_unsupported_share": 0.15,
            "min_results_for_slo": 20,
        },
    }
    p = tmp_path / "slo.json"
    p.write_text(json.dumps(slo), encoding="utf-8")
    ev = m.evaluate_slo({"results": 3, "ungrounded_share": 0.9, "soft_unsupported_share": 0.9}, p)
    assert ev["verdict"] == "UNKNOWN"
    assert ev["ok"] is True


def test_slo_fail_when_above_floor(tmp_path):
    m = _load()
    slo = {
        "floors": {
            "max_ungrounded_share": 0.05,
            "max_soft_unsupported_share": 0.15,
            "min_results_for_slo": 5,
        },
    }
    p = tmp_path / "slo.json"
    p.write_text(json.dumps(slo), encoding="utf-8")
    ev = m.evaluate_slo(
        {"results": 100, "ungrounded_share": 0.10, "soft_unsupported_share": 0.01},
        p,
    )
    assert ev["verdict"] == "FAIL"
    assert ev["ok"] is False


def test_slo_config_exists():
    assert (ROOT / "config" / "agent_number_grounding_slo.json").is_file()
