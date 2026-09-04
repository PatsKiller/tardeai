"""Pytest entry for the CC runtime validation harness (hermetic)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.cc_runtime_harness.freshness import overview_surface_freshness
from scripts.cc_runtime_harness.negatives import run_negative_controls, timezone_boundary_cases
from scripts.cc_runtime_harness.runner import HarnessConfig, run_harness
from scripts.cc_runtime_harness.safety import assert_method_allowed, classify_base_url


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures" / "cc_runtime"


def test_refuse_production_host() -> None:
    d = classify_base_url("https://prod.trade-ai.example")
    assert not d.allowed
    assert d.host_class == "live_refused"


def test_refuse_live_post() -> None:
    d = assert_method_allowed("POST", "https://live.trade-ai.internal")
    assert not d.allowed


def test_loopback_get_ok() -> None:
    d = assert_method_allowed("GET", "http://127.0.0.1:9")
    assert d.allowed


def test_split_root_stale_never_fresh() -> None:
    now = datetime(2026, 9, 2, 21, 0, 0, tzinfo=timezone.utc)
    ov = {
        "portfolio_value": 1280958.39,
        "as_of": "2026-09-02",
        "data_as_of": "2026-08-03",
        "data_as_of_account": "alpaca_taxable_live",
        "pricing": {"last_repriced": "2026-09-02 16:45:02 ET"},
        "pipeline_status": "fresh",
    }
    fres = overview_surface_freshness(ov, now)
    assert fres.stale is True
    assert fres.asOf == "2026-08-03"
    assert fres.asOf != ov["as_of"]
    assert (fres.surfaceLabel or "").startswith("STALE")


def test_undated_does_not_borrow_loader_date() -> None:
    now = datetime(2026, 9, 2, 21, 0, 0, tzinfo=timezone.utc)
    ov = {"portfolio_value": 1.0, "as_of": "2026-09-02"}
    fres = overview_surface_freshness(ov, now)
    assert fres.stale is True
    assert fres.asOf is None
    assert "UNDATED" in (fres.surfaceLabel or "")


def _head_sha() -> str:
    """The commit under test. Hardcoding one stamped an unrelated SHA across the
    harness evidence and the tracked route ledger for weeks."""
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:  # noqa: BLE001
        return "0" * 40


def test_timezone_boundaries() -> None:
    cases = timezone_boundary_cases()
    assert cases
    assert all(c["pass"] for c in cases)


def test_hermetic_harness_pass(tmp_path: Path) -> None:
    cfg = HarnessConfig(
        mode="hermetic",
        repo_root=REPO,
        fixture_root=FIXTURES,
        output_dir=tmp_path / "out",
        # The identity under test is the commit being verified, never a literal.
        build_sha=_head_sha(),
    )
    result = run_harness(cfg)
    assert result.ok, result.failures
    assert result.counts["negatives_pass"] == result.counts["negatives_total"]
    assert (tmp_path / "out" / "RUNTIME_HARNESS_SUMMARY.md").exists()


def test_negative_controls_all_detect() -> None:
    from scripts.cc_runtime_harness.discover import discover_routes
    from scripts.cc_runtime_harness.runner import CORE_API_PATHS, _ensure_fixtures

    _ensure_fixtures(FIXTURES, _head_sha(), datetime(2026, 9, 2, tzinfo=timezone.utc))
    discovered = discover_routes(REPO)
    ledger = {
        "routes": [{"url": r.url, "path": r.path} for r in discovered.routes],
        "apis": [{"path": p} for p in CORE_API_PATHS],
        "required_apis": list(CORE_API_PATHS),
    }
    results = run_negative_controls(
        positive_dir=FIXTURES / "positive",
        base_url=None,
        discovered=discovered,
        ledger=ledger,
    )
    failed = [r["control"] for r in results if not r.get("pass")]
    assert not failed, failed
