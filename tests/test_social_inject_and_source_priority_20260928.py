"""PR-4 (2026-09-28, root cause 4): the scanner's social overlay was silently dead and source
labels were alphabetical.

- `continuous_runner` called `_execute(sql)` with no `fetch`; `db_adapter._execute` returns True in
  that case, so the loop raised `'bool' object is not iterable` on every live cycle for weeks and
  the social/route-aware injection contributed nothing. The call now passes fetch="all" and a
  failure is counted, not only printed.
- `api_v2` labelled a row with the alphabetically-first `watchlist_items.source`, so
  `ai_discovered` outranked `screener`. Labels now follow `assets/screeners.yaml
  source_label_priority` and every source is exposed as `sources_all`.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.source_priority import DEFAULT_PRIORITY, load_priority, pick_primary_source  # noqa: E402


# ---------------------------------------------------------------- social inject


def _social_inject_call():
    src = (ROOT / "scripts/continuous_runner.py").read_text()
    m = re.search(r"_social = _execute\((.*?)\)\s*or \[\]", src, re.S)
    assert m, "social inject call not found"
    return m.group(0), src


def test_social_inject_query_requests_rows_not_a_bool():
    call, _ = _social_inject_call()
    assert 'fetch="all"' in call, "without fetch the adapter returns True and the loop raises"
    assert "FROM scalp_scan_results" in call


def test_db_adapter_contract_still_makes_fetch_mandatory_for_rows():
    """Positive control on the adapter contract this bug depended on: fetch defaults to None and only
    'one'/'all' return rows. If that changes, the runner call and this file need a look."""
    src = (ROOT / "scripts/db_adapter.py").read_text()
    assert re.search(r"def _execute\(sql: str, params=None, fetch: str = None\)", src)
    assert "fetch='one'|'all'|None" in src


def test_social_inject_failure_is_counted():
    _, src = _social_inject_call()
    assert "_SOCIAL_INJECT_ERRORS: list = []" in src
    assert "_SOCIAL_INJECT_ERRORS.append(" in src
    assert "social inject ERROR" in src


# ---------------------------------------------------------------- source priority


def test_priority_declared_in_config_and_loaded():
    cfg = yaml.safe_load((ROOT / "assets/screeners.yaml").read_text())
    assert cfg["source_label_priority"][:3] == ["screener", "social", "ai_discovered"]
    assert load_priority() == cfg["source_label_priority"]


def test_screener_beats_ai_discovered_regardless_of_alphabet():
    pri = ["screener", "social", "ai_discovered", "topic_research"]
    assert pick_primary_source(["ai_discovered", "screener"], pri) == "screener"
    assert pick_primary_source(["ai_discovered", "topic_research"], pri) == "ai_discovered"
    assert pick_primary_source(["social", "screener"], pri) == "screener"
    assert pick_primary_source(["zzz_unknown", "ai_discovered"], pri) == "ai_discovered"
    assert pick_primary_source([], pri) == "screener"
    assert pick_primary_source(None, pri, default="none") == "none"
    assert pick_primary_source(["b_unknown", "a_unknown"], pri) == "a_unknown"
    assert DEFAULT_PRIORITY[0] == "screener"


def test_api_labels_by_priority_and_exposes_all_sources():
    src = (ROOT / "scripts/api_v2.py").read_text()
    assert "from lib.source_priority import pick_primary_source" in src
    assert 't["sources_all"] = _all' in src
    assert 'src = ws[0] if ws else "screener"' not in src, "alphabetical first-source labelling must be gone"
