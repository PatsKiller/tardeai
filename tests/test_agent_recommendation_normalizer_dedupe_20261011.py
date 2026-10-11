"""The normalizer id is a function of the source row, so a re-run does not insert again."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "agent_recommendation_normalizer.py"
    spec = importlib.util.spec_from_file_location("agent_recommendation_normalizer", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_recommendation_id_is_stable_and_source_specific():
    mod = _load()
    a = mod._recommendation_id("watchlist_agent_results", "42")
    b = mod._recommendation_id("watchlist_agent_results", "42")
    c = mod._recommendation_id("cio_decisions", "42")
    assert a == b
    assert a != c
    assert a.startswith("AREC_")
