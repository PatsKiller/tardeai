"""hermes_tag_engine carries a process dollar cap, and the cap is enforced (2026-10-15).

A dry run on 2026-10-15 logged::

    llm_lane_unregistered process_id=hermes_tag_engine has no daily_cost_cap_usd;
    process cap not enforced for this lane

The row existed in ``config/llm_process_registry.json`` but had no ``daily_cost_cap_usd``, so
``check_cost_cap`` skipped the process check. Pinned here:

  * the registry row declares a positive cap;
  * ``check_cost_cap`` no longer emits ``llm_lane_unregistered`` for it;
  * with mocked ledger consumption, spend + projection over the cap is refused with
    ``COST_CAP_EXCEEDED`` / ``scope=process``, and spend under it is allowed;
  * control: a process with no cap still emits the warning, so the log capture is live.

Hermetic: the DB connection raises (``get_process_config`` falls back to the registry) and
``ledger_paid_usd_today`` is replaced; no DB, no provider call.
"""

from __future__ import annotations

import json
import logging
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must not connect")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)

from lib import llm_consumption as lc  # noqa: E402

COVERS = ["scripts/lib/llm_consumption.py", "config/llm_process_registry.json"]

PID = "hermes_tag_engine"
EXPECTED_CAP = 0.05


def _registry_row(pid: str) -> dict:
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    return next(p for p in reg["processes"] if p.get("id") == pid)


@pytest.fixture
def hermetic(monkeypatch):
    """Registry from the repo, no DB, ledger spend set per test."""
    monkeypatch.setattr(lc, "_REGISTRY", None)
    monkeypatch.setattr(lc, "REGISTRY_PATH", ROOT / "config" / "llm_process_registry.json")

    def _no_db():
        raise RuntimeError("hermetic test: no DB")

    monkeypatch.setattr(lc, "_conn", _no_db)
    spend: dict[str, float] = {}

    def _ledger(process_id=None, *, cur=None):
        return float(spend.get(process_id or "__global__", 0.0))

    monkeypatch.setattr(lc, "ledger_paid_usd_today", _ledger)
    yield spend
    lc._REGISTRY = None


def _unregistered_records(caplog, pid: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if "llm_lane_unregistered" in r.getMessage() and f"process_id={pid} " in r.getMessage()]


def test_registry_row_declares_positive_cap():
    row = _registry_row(PID)
    assert row.get("daily_cost_cap_usd") == pytest.approx(EXPECTED_CAP)
    assert float(row["daily_cost_cap_usd"]) > 0
    # The lane allowlist is unchanged: still OAuth-only via lane_policy "either".
    assert row.get("lane_policy") == "either"
    assert "allowed_lanes" not in row


def test_process_config_resolves_cap_without_db(hermetic):
    cfg = lc.get_process_config(PID)
    assert cfg["registered"] is True
    assert cfg["daily_cost_cap_usd"] == pytest.approx(EXPECTED_CAP)


def test_warning_no_longer_fires(hermetic, caplog):
    caplog.set_level(logging.WARNING, logger=lc.__name__)
    out = lc.check_cost_cap(PID, projected_usd=0.0, global_cap=None)
    assert out["allow"] is True, out
    assert _unregistered_records(caplog, PID) == []


def test_under_cap_is_allowed(hermetic):
    hermetic[PID] = 0.02
    out = lc.check_cost_cap(PID, projected_usd=0.01, global_cap=None)
    assert out["allow"] is True, out
    assert out["spent_process_usd"] == pytest.approx(0.02)


def test_projection_over_cap_is_refused(hermetic):
    hermetic[PID] = 0.049
    out = lc.check_cost_cap(PID, projected_usd=0.002, global_cap=None)
    assert out["allow"] is False
    assert out["reason"] == "COST_CAP_EXCEEDED"
    assert out["scope"] == "process"
    assert out["cap_usd"] == pytest.approx(EXPECTED_CAP)
    assert out["spent_usd"] == pytest.approx(0.049)


def test_spend_already_over_cap_is_refused(hermetic):
    hermetic[PID] = 0.06
    out = lc.check_cost_cap(PID, projected_usd=0.0, global_cap=None)
    assert out["allow"] is False
    assert out["reason"] == "COST_CAP_EXCEEDED"
    assert out["scope"] == "process"


def test_control_uncapped_process_still_warns(hermetic, caplog):
    """Proves the capture above is live: a registered id without a cap still warns."""
    uncapped = "hermes_scalp_review"
    assert _registry_row(uncapped).get("daily_cost_cap_usd") is None
    caplog.set_level(logging.WARNING, logger=lc.__name__)
    out = lc.check_cost_cap(uncapped, projected_usd=0.0, global_cap=None)
    assert out["allow"] is True
    assert len(_unregistered_records(caplog, uncapped)) == 1
