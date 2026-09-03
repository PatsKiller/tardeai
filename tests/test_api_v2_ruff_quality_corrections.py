"""Regression pins for the 16 ruff F-codes cleared in scripts/api_v2.py.

Campaign: cc-header-truth-v2-20260903 final quality-gate correction.
These findings were inherited debt that entered the changed-file quality floor
because this tranche touches api_v2.py. Each class is pinned so silent
reintroduction of the defect fails CI.

AUTHORITY: READ_ONLY_ADVISORY — no broker, order, or financial mutation.
"""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "scripts" / "api_v2.py"
sys.path.insert(0, str(ROOT / "scripts"))


# ── Gate floor: the exact 16 findings must stay green ─────────────────────────


def test_ruff_check_clean_on_api_v2():
    """The changed-file quality floor runs `ruff check` on every changed .py."""
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", str(API)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_ruff_format_check_clean_on_api_v2():
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", str(API)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_api_v2_compiles():
    compile(API.read_text(encoding="utf-8"), str(API), "exec")


# ── F601: duplicate dict keys must not recur for the cleared keys ─────────────


_CLEARED_DUP_KEYS = frozenset(
    {"total_cash", "last_repriced", "forward_pe", "bench_sharpe", "bench_sortino", "bench_maxdd"}
)


def _duplicate_string_keys(tree: ast.AST) -> list[tuple[str, int, int]]:
    hits: list[tuple[str, int, int]] = []

    class V(ast.NodeVisitor):
        def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
            seen: dict[str, int] = {}
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    if k.value in seen:
                        hits.append((k.value, seen[k.value], k.lineno))
                    else:
                        seen[k.value] = k.lineno
            self.generic_visit(node)

    V().visit(tree)
    return hits


def test_cleared_duplicate_keys_do_not_recur():
    tree = ast.parse(API.read_text(encoding="utf-8"))
    dups = [h for h in _duplicate_string_keys(tree) if h[0] in _CLEARED_DUP_KEYS]
    assert dups == [], f"cleared duplicate keys reappeared: {dups}"


def test_overview_emits_total_cash_and_last_repriced_once():
    """Authoritative keys live once in the overview() return dict."""
    src = API.read_text(encoding="utf-8")
    # Extract overview function body via AST and find the return Dict
    tree = ast.parse(src)
    overview = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "overview")
    ret_dicts = [n.value for n in ast.walk(overview) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    assert ret_dicts, "overview() must return a dict literal"
    # The outermost / final return is the response contract
    keys = [k.value for k in ret_dicts[-1].keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    assert keys.count("total_cash") == 1
    assert keys.count("last_repriced") == 1
    # Sprint 4A unique keys must still be present (not deleted with the dupes)
    for required in ("weighted_beta", "concentration_alerts", "pending_pipeline", "index_tape", "delta_events"):
        assert required in keys, f"overview lost required key {required}"


def test_attribution_bench_keys_appear_once():
    tree = ast.parse(API.read_text(encoding="utf-8"))
    # Find function that returns bench_sharpe (performance attribution)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for ret in (n for n in ast.walk(node) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)):
            keys = [k.value for k in ret.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if "bench_sharpe" in keys:
                assert keys.count("bench_sharpe") == 1
                assert keys.count("bench_sortino") == 1
                assert keys.count("bench_maxdd") == 1
                assert "accounts" in keys
                return
    pytest.fail("no attribution return dict with bench_sharpe found")


# ── F821: undefined names resolved to canonical sources ───────────────────────


def test_stops_management_does_not_reference_undefined_risk_metrics():
    src = API.read_text(encoding="utf-8")
    assert "_risk_metrics()" not in src
    assert 'STATE_DIR / "risk_management.json"' in src


def test_stops_management_heat_fails_closed_when_risk_file_absent(monkeypatch, tmp_path):
    import api_v2

    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
    # No risk_management.json → heat/risk stay at 0.0 (fail closed)
    monkeypatch.setattr(api_v2, "portfolio_holdings", lambda: {"holdings": []})
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None if k.get("fetch") == "one" else [])
    out = api_v2._stops_management_api_build({})
    assert isinstance(out, dict)
    summary = out.get("summary") or {}
    assert summary.get("portfolio_heat_pct") == 0.0 or summary.get("portfolio_heat_pct") == 0
    assert summary.get("total_open_risk") == 0 or summary.get("total_open_risk") == 0.0


def test_stops_management_reads_canonical_risk_file(monkeypatch, tmp_path):
    import api_v2
    import json

    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
    (tmp_path / "risk_management.json").write_text(
        json.dumps({"portfolio_heat_pct": 4.5, "total_risk_dollars": 12000}),
        encoding="utf-8",
    )
    monkeypatch.setattr(api_v2, "portfolio_holdings", lambda: {"holdings": []})
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None if k.get("fetch") == "one" else [])
    out = api_v2._stops_management_api_build({})
    summary = out.get("summary") or {}
    assert summary.get("portfolio_heat_pct") == 4.5


def test_broker_connectors_as_of_does_not_call_undefined_now_iso():
    src = API.read_text(encoding="utf-8")
    assert '_now_iso() if "_now_iso" in globals()' not in src
    # Canonical: module-level datetime.now(timezone.utc).isoformat()
    assert "datetime.now(timezone.utc).isoformat()" in src


def test_broker_connectors_as_of_is_iso_string(monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    out = api_v2._system_broker_connectors()
    assert isinstance(out, dict)
    assert out.get("as_of"), "as_of must be populated (fail-closed previously returned None)"
    # ISO-8601 shape
    assert "T" in out["as_of"]


# ── F823: datetime no longer shadowed inside handle() ─────────────────────────


def test_handle_does_not_shadow_module_datetime():
    """A local `from datetime import datetime` inside handle() made weekly-report
    raise UnboundLocalError before the local import ran."""
    tree = ast.parse(API.read_text(encoding="utf-8"))
    handle = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "handle")
    for node in ast.walk(handle):
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            names = {a.name for a in node.names}
            # Aliased imports are fine; bare `datetime` as a local name is not.
            for a in node.names:
                if a.name == "datetime" and a.asname is None:
                    pytest.fail(
                        f"handle() still binds bare name 'datetime' at L{node.lineno} "
                        f"(shadows module-level import; F823 recurrence)"
                    )


def test_weekly_report_path_does_not_raise_unbound_datetime(monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    status, body = api_v2.handle("/api/v2/weekly-report", method="GET")
    assert status == 200
    assert body.get("ok") is True
    assert "generated_at" in (body.get("data") or {})


def test_monthly_report_path_does_not_raise_unbound_datetime(monkeypatch):
    import api_v2

    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
    status, body = api_v2.handle("/api/v2/monthly-report", method="GET")
    assert status == 200
    assert body.get("ok") is True
    assert "generated_at" in (body.get("data") or {})


# ── F541: placeholder-free f-strings converted ────────────────────────────────


_FORBIDDEN_FSTRINGS = (
    'f"Verified catalyst exists but critic flags concerns. Consider as cautious paper test only."',
    'f"Limited conviction — unverified catalyst. Paper test only if testing system handling of this setup type."',
    'f" · target = 20d-high/2R"',
    'f"SELECT count(*) as n FROM youtube_transcripts WHERE channel_name = %s"',
    'f"Data staleness alert"',
    'f"SELECT MAX(created_at) as t FROM watchlist_agent_results WHERE agent=%s"',
    'f" AND source_table=%s"',
)


def test_placeholder_free_fstrings_are_gone():
    src = API.read_text(encoding="utf-8")
    for bad in _FORBIDDEN_FSTRINGS:
        assert bad not in src, f"placeholder-free f-string still present: {bad}"


# ── Tranche contracts still wired after quality pass ──────────────────────────


def test_tranche_contracts_still_wired():
    src = API.read_text(encoding="utf-8")
    for needle in (
        "portfolio_aggregate",
        "setup_run_summary",
        "project_quote_selection",
        "build_setup_run_summary",
        "JournalMetrics@v1",
        "_vix_observation",
    ):
        assert needle in src, f"tranche wiring lost: {needle}"
