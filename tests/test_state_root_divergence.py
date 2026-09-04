#!/usr/bin/env python3
"""The state-root divergence report tells the truth, and repairs nothing.

Producers run under `cd $PROJ`; every deployed release symlinks
data/portfolios/state at the persistent root. A producer resolving its path
from the checkout writes a tree the server never reads and still reports
success. Measured 2026-09-03 on the live tree: 59 of 88 stores forked, worst
skew 143 days, and no Command Center surface said so.

Every filesystem path here is under tmp_path. No network, broker, scheduler,
database or production path is touched.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import state_root_divergence as srd  # noqa: E402

REL = srd.STATE_REL


@pytest.fixture()
def two_roots(tmp_path, monkeypatch):
    """A producer checkout and a served persistent root, separate inodes."""
    producer = tmp_path / "checkout"
    served = tmp_path / "persistent-state"
    (producer / REL).mkdir(parents=True)
    (served / REL).mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(served))
    return producer, served


def _write(root: Path, name: str, payload, *, age_days: float = 0.0) -> Path:
    p = root / REL / name
    p.write_text(json.dumps(payload))
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
    return p


# ── the defect, reproduced ───────────────────────────────────────────────────


def test_producer_ahead_fork_is_reported_with_direction(two_roots):
    producer, served = two_roots
    _write(producer, "portfolio_news.json", {"v": "new"})
    _write(served, "portfolio_news.json", {"v": "old"}, age_days=8)

    r = srd.scan(checkout_root=producer)
    assert r["status"] == "DIVERGENT"
    row = next(s for s in r["stores"] if s["store"] == "portfolio_news.json")
    assert row["verdict"] == srd.DIVERGENT
    assert row["direction"] == srd.PRODUCER_AHEAD, "the server is serving stale truth"
    assert row["skew_seconds"] > 7 * 86400
    assert row["served_age_hours"] > 24 * 7
    assert r["producer_ahead_count"] == 1


def test_served_ahead_fork_is_reported_as_a_different_direction(two_roots):
    """A served-ahead fork is not the same defect and must not be conflated."""
    producer, served = two_roots
    _write(producer, "health_agent_status.json", {"v": "old"}, age_days=8)
    _write(served, "health_agent_status.json", {"v": "new"})

    r = srd.scan(checkout_root=producer)
    row = next(s for s in r["stores"] if s["store"] == "health_agent_status.json")
    assert row["direction"] == srd.SERVED_AHEAD
    assert r["served_ahead_count"] == 1
    assert r["producer_ahead_count"] == 0


def test_converged_roots_report_converged(two_roots):
    producer, served = two_roots
    for root in (producer, served):
        p = _write(root, "holdings.json", {"v": 1})
        os.utime(p, (1_700_000_000, 1_700_000_000))
    r = srd.scan(checkout_root=producer)
    assert r["status"] == "CONVERGED"
    assert r["diverged_count"] == 0


def test_identical_bytes_with_different_mtime_is_not_a_fork(two_roots):
    """A rewrite of identical content is not divergence. Byte identity wins."""
    producer, served = two_roots
    _write(producer, "stops.json", {"same": True})
    _write(served, "stops.json", {"same": True}, age_days=3)

    without = srd.scan(checkout_root=producer)
    assert without["diverged_count"] == 1, "mtime alone flags it"
    with_hashes = srd.scan(checkout_root=producer, with_hashes=True)
    row = next(s for s in with_hashes["stores"] if s["store"] == "stops.json")
    assert row["byte_identical"] is True
    assert row["verdict"] == srd.IDENTICAL
    assert with_hashes["diverged_count"] == 0


def test_missing_on_one_side_is_named_not_silently_dropped(two_roots):
    producer, served = two_roots
    _write(producer, "producer_only.json", {"a": 1})
    _write(served, "served_only.json", {"b": 2})
    r = srd.scan(checkout_root=producer)
    v = {s["store"]: s["verdict"] for s in r["stores"]}
    assert v["producer_only.json"] == srd.PRODUCER_ONLY
    assert v["served_only.json"] == srd.SERVED_ONLY


# ── fail-closed ──────────────────────────────────────────────────────────────


def test_unreadable_root_is_UNKNOWN_never_converged(tmp_path, monkeypatch):
    """A zero over an unlisted directory is not a zero divergence."""
    producer = tmp_path / "checkout"
    served = tmp_path / "persistent-state"
    (producer / REL).mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(served))  # never created

    r = srd.scan(checkout_root=producer)
    assert r["status"] == "UNKNOWN"
    assert r["status"] != "CONVERGED"
    assert r["roots_readable"]["served"] is False


def test_report_never_repairs_anything(two_roots):
    """Detection must not become resolution (AGENTS.md 9.4 / WAVE G1)."""
    producer, served = two_roots
    _write(producer, "portfolio_news.json", {"v": "new"})
    _write(served, "portfolio_news.json", {"v": "old"}, age_days=8)

    def snapshot(root: Path):
        return {p.name: (p.stat().st_mtime, p.stat().st_size, p.read_bytes()) for p in (root / REL).glob("*.json")}

    before = (snapshot(producer), snapshot(served))
    r = srd.scan(checkout_root=producer, with_hashes=True)
    after = (snapshot(producer), snapshot(served))

    assert before == after, "the report mutated a store"
    assert r["auto_remediate"] is False
    assert r["action"] == "REPORT_AND_ESCALATE"
    # the fork is still there — reporting it did not resolve it
    assert json.loads((served / REL / "portfolio_news.json").read_text())["v"] == "old"


def test_producer_root_is_the_hub_not_this_process(monkeypatch):
    """A release's own root IS the served symlink; comparing it to itself lies."""
    from lib.persistent_state_root import DEFAULT_LEGACY_SOURCE

    assert srd.producer_checkout_root() == Path(DEFAULT_LEGACY_SOURCE)
    assert srd.producer_checkout_root() != ROOT or ROOT == Path(DEFAULT_LEGACY_SOURCE)


def test_schema_and_version_are_published(two_roots):
    producer, _ = two_roots
    r = srd.scan(checkout_root=producer)
    assert r["schema"] == "StateRootDivergenceReport@v1"
    assert r["calculation_version"] == srd.CALCULATION_VERSION
    assert r["authority"] == "READ_ONLY_ADVISORY"
    assert json.loads(json.dumps(r)) == r, "report must serialize round-trip"


# ── the API surface ──────────────────────────────────────────────────────────


def test_endpoint_is_registered_and_read_only():
    import ast

    src = (ROOT / "scripts" / "api_v2.py").read_bytes()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_state_root_divergence")
    forbidden = {"write_text", "write_bytes", "atomic_write_json", "write_state_json", "dump", "mkdir"}
    called = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                called.add(f.id)
            elif isinstance(f, ast.Attribute):
                called.add(f.attr)
    assert not (forbidden & called), f"handler performs a write: {forbidden & called}"
    assert '"/api/v2/system/state-root-divergence"' in src.decode()


def test_endpoint_fails_closed_when_scan_raises(monkeypatch):
    import api_v2

    def boom(*a, **k):
        raise RuntimeError("state root unreadable")

    monkeypatch.setattr("lib.state_root_divergence.scan", boom)
    r = api_v2._state_root_divergence({})
    assert r["status"] == "UNAVAILABLE"
    assert r["status"] != "CONVERGED"
    assert r["auto_remediate"] is False
    assert "RuntimeError" in r["reason"]


class TestSidecarsAreNotStores:
    """The migration's own bookkeeping must not read as a divergence it caused.

    A conflict sidecar records which records inside a store could not be reconciled.
    It is written to the served root only, on purpose. A scanner that treats every
    *.json in the directory as a governed store saw it as a new served-only fork and
    reported UNKNOWN_BLOCKING — turning correct bookkeeping into a blocking finding.
    """

    def test_a_conflict_sidecar_is_not_a_store(self):
        assert srd.is_sidecar("tax_lots.json.conflicts.json")
        assert srd.is_sidecar("stops.json.conflicts.json")

    def test_a_real_store_is_not_a_sidecar(self):
        for name in ("tax_lots.json", "stops.json", "_freshness.json", "conflicts.json"):
            assert not srd.is_sidecar(name), name

    def test_the_scan_excludes_sidecars(self, tmp_path, monkeypatch):
        prod, served = tmp_path / "producer", tmp_path / "served"
        prod.mkdir()
        served.mkdir()
        (prod / "a.json").write_text("{}")
        (served / "a.json").write_text("{}")
        (served / "a.json.conflicts.json").write_text('{"records": []}')
        monkeypatch.setattr(srd, "_roots", lambda _r=None: (prod, served))
        rep = srd.scan(with_hashes=False)
        names = {s["store"] for s in rep["stores"]}
        assert names == {"a.json"}, f"sidecar leaked into the scan: {names}"
