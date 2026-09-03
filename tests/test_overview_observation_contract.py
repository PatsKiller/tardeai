#!/usr/bin/env python3
"""GET /api/v2/overview: read-only, one envelope, named counts.

Three proven defects are pinned here:

* the handler wrote `portfolio_snapshot.json` on every cache miss, so a GET was
  not a read and the snapshot was refreshed by whoever browsed;
* `pipeline_status` was republished verbatim from a file whose `status` field
  was a hardcoded literal;
* `position_count` 14 disagreed with risk's 15, both unlabeled.

Structural assertions use the AST, never a substring search: a grep cannot
tell code from a comment quoting it, and every one of these call sites now has
a comment quoting the thing it fixed.

No network, broker, scheduler, Drive, database or production path is touched.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API_V2 = ROOT / "scripts" / "api_v2.py"
SNAPSHOT_MODULE = ROOT / "scripts" / "lib" / "data_broker" / "portfolio_snapshot.py"


@pytest.fixture(scope="module")
def overview_fn() -> ast.FunctionDef:
    tree = ast.parse(API_V2.read_bytes())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "overview":
            return node
    pytest.fail("overview() not found in api_v2.py")


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name) and fn.id == name:
                out.append(sub)
            elif isinstance(fn, ast.Attribute) and fn.attr == name:
                out.append(sub)
    return out


# ── the GET must not write ───────────────────────────────────────────────────


def test_overview_asks_the_snapshot_broker_not_to_write(overview_fn):
    calls = _calls(overview_fn, "get_portfolio_snapshot")
    assert calls, "overview() no longer reads the broker snapshot"
    for call in calls:
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        assert "write_on_miss" in kwargs, "a GET must declare it does not publish"
        assert isinstance(kwargs["write_on_miss"], ast.Constant)
        assert kwargs["write_on_miss"].value is False


def test_overview_contains_no_write_call_at_all(overview_fn):
    forbidden = {
        "write_portfolio_snapshot",
        "write_state_json",
        "atomic_write_json",
        "write_text",
        "write_bytes",
        "dump",
    }
    found = sorted(n for n in forbidden if _calls(overview_fn, n))
    assert found == [], f"overview() performs a write: {found}"


def test_read_only_snapshot_path_publishes_nothing(tmp_path, monkeypatch):
    """Behavioural proof, not only structural."""
    from lib.data_broker import portfolio_snapshot as ps

    target = tmp_path / "portfolio_snapshot.json"
    monkeypatch.setattr(ps, "SNAPSHOT_PATH", target)
    monkeypatch.setattr(
        ps,
        "build_portfolio_snapshot",
        lambda: {"totals": {"total_value": 1.0}, "computed_at": "2026-09-02T21:00:00+00:00"},
    )
    result = ps.get_portfolio_snapshot(write_on_miss=False)

    assert not target.exists(), "a read request created a store"
    assert result["_cache"]["wrote"] is False


def test_default_still_writes_so_existing_callers_are_unchanged(tmp_path, monkeypatch):
    """Backward-compatible adapter behaviour: the four other callers keep theirs."""
    from lib.data_broker import portfolio_snapshot as ps

    target = tmp_path / "portfolio_snapshot.json"
    monkeypatch.setattr(ps, "SNAPSHOT_PATH", target)
    monkeypatch.setattr(
        ps, "build_portfolio_snapshot", lambda: {"totals": {}, "computed_at": "2026-09-02T21:00:00+00:00"}
    )
    result = ps.get_portfolio_snapshot()
    assert target.exists()
    assert result["_cache"]["wrote"] is True


def test_write_on_miss_is_keyword_only_and_defaults_true():
    tree = ast.parse(SNAPSHOT_MODULE.read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_portfolio_snapshot")
    names = [a.arg for a in fn.args.kwonlyargs]
    assert "write_on_miss" in names, "must be keyword-only so no positional caller changes meaning"
    default = fn.args.kw_defaults[names.index("write_on_miss")]
    assert isinstance(default, ast.Constant) and default.value is True


# ── freshness is computed, not republished ───────────────────────────────────


def test_pipeline_status_is_not_the_files_literal_status(overview_fn):
    """Before: "pipeline_status": fresh.get("status", "unknown")."""
    for node in ast.walk(overview_fn):
        if not (isinstance(node, ast.Dict)):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "pipeline_status":
                src = ast.dump(value)
                assert "fresh" not in src or "get" not in src, (
                    "pipeline_status still republishes the file's own status field"
                )


def test_overview_publishes_a_computed_status_and_the_reported_one(overview_fn):
    keys = {
        k.value
        for node in ast.walk(overview_fn)
        if isinstance(node, ast.Dict)
        for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert "pipeline_status" in keys
    assert "pipeline_status_source" in keys, "consumers must be able to see the status was derived"
    assert "pipeline_status_reported" in keys, "the file's own claim stays visible for comparison"
    assert "observation" in keys, "the envelope block must be published"


def test_overview_reads_every_store_through_the_envelope(overview_fn):
    calls = _calls(overview_fn, "observe_state_file")
    read = set()
    for call in calls:
        if call.args and isinstance(call.args[0], ast.Constant):
            read.add(call.args[0].value)
    assert {"holdings.json", "performance_history.json", "_freshness.json", "portfolio_news.json"} <= read, (
        f"stores still read outside the envelope: {read}"
    )


def test_surface_status_is_the_worst_contributing_dataset(overview_fn):
    assert _calls(overview_fn, "worst_status"), "the surface must not be as fresh as its newest dataset"


def test_one_trace_id_is_minted_per_request(overview_fn):
    assert len(_calls(overview_fn, "new_trace_id")) == 1


# ── position-count contract ──────────────────────────────────────────────────


def test_overview_publishes_named_position_scopes(overview_fn):
    assert _calls(overview_fn, "position_count_contract"), "counts are still unlabeled"
    keys = {
        k.value
        for node in ast.walk(overview_fn)
        if isinstance(node, ast.Dict)
        for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert "position_counts" in keys
    assert "position_count" in keys, "the legacy scalar must stay for existing callers"


def test_the_risk_scope_uses_the_same_rule_as_the_risk_endpoint():
    """Both sides must count `not risk_excluded`, or the contract lies."""
    src = API_V2.read_text()
    assert 'sum(1 for p in _rm_positions if not p.get("risk_excluded"))' in src
    assert 'sum(1 for p in positions if not p.get("risk_excluded"))' in src


# ── backward compatibility ───────────────────────────────────────────────────


def test_every_pre_existing_overview_key_survives(overview_fn):
    keys = {
        k.value
        for node in ast.walk(overview_fn)
        if isinstance(node, ast.Dict)
        for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    for legacy in (
        "portfolio_value",
        "today_change",
        "today_pct",
        "total_cash",
        "as_of",
        "data_as_of",
        "data_as_of_account",
        "last_repriced",
        "periods",
        "position_count",
        "account_count",
        "pipeline_status",
        "pipeline_completed",
        "news_count",
        "sectors",
        "top_movers",
        "journal",
        "pricing",
    ):
        assert legacy in keys, f"removed a key existing callers read: {legacy}"
