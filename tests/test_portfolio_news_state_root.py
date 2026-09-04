#!/usr/bin/env python3
"""portfolio_news.json reaches every root a reader may use.

The producer runs under `cd $PROJ` while every deployed release symlinks
data/portfolios/state at the persistent root. Writing only the checkout copy
stranded the Command Center on an August file while this producer reported
success every morning. Measured 2026-09-03: producer copy 09-03 07:41, served
copy 08-26 07:44 — 8 days apart, separate inodes.

The same fix already existed twice in this repository (portfolio_stops.
save_risk_state, and the orchestrator's _freshness / performance_history
writes). This pins the third.

All writes go to tmp_path. No network, broker, scheduler or production path.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

NEWS = ROOT / "scripts" / "portfolio_news.py"
REL = "data/portfolios/state"


def _collect_fn() -> ast.FunctionDef:
    tree = ast.parse(NEWS.read_bytes())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "collect_portfolio_news")


def test_current_state_is_written_through_the_canonical_dual_write():
    """AST, not grep: a comment quoting the old line must not satisfy this."""
    fn = _collect_fn()
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
    named = set()
    for c in calls:
        f = c.func
        named.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    assert "_wsj" in named or "write_state_json" in named, (
        "portfolio_news.json is no longer routed through the canonical dual-write"
    )


def test_the_single_root_write_is_gone():
    """The exact defect: `state_dir / "portfolio_news.json"` written directly."""
    fn = _collect_fn()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "write_text":
            src = ast.dump(f.value)
            assert "portfolio_news" not in src, "portfolio_news.json is still written to a single root"


def test_root_is_in_scope_so_the_write_cannot_NameError():
    fn = _collect_fn()
    assert "root" in [a.arg for a in fn.args.args]


def test_dual_write_reaches_both_roots_from_one_object(tmp_path, monkeypatch):
    producer = tmp_path / "checkout"
    served = tmp_path / "persistent-state"
    (producer / REL).mkdir(parents=True)
    (served / REL).mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(served))

    from lib.canonical_observation import write_state_json

    snapshot = {"catalysts": [{"symbol": "AAA"}], "as_of": "2026-09-03T12:00:00+00:00"}
    res = write_state_json("portfolio_news.json", snapshot, checkout_root=producer)

    assert res["errors"] == []
    assert res["target_count"] == 2, "the served copy is the one that was stranded"
    a = producer / REL / "portfolio_news.json"
    b = served / REL / "portfolio_news.json"
    assert a.is_file() and b.is_file()
    assert json.loads(a.read_text()) == json.loads(b.read_text()) == snapshot
    assert a.stat().st_ino != b.stat().st_ino, "separate inodes, as measured live"


def test_the_divergence_report_sees_this_store_converge(tmp_path, monkeypatch):
    """End to end: fork it, then write canonically, and the report agrees."""
    from lib import state_root_divergence as srd
    from lib.canonical_observation import write_state_json

    producer = tmp_path / "checkout"
    served = tmp_path / "persistent-state"
    (producer / REL).mkdir(parents=True)
    (served / REL).mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(served))

    import os, time

    (producer / REL / "portfolio_news.json").write_text(json.dumps({"v": "new"}))
    old = served / REL / "portfolio_news.json"
    old.write_text(json.dumps({"v": "old"}))
    t = time.time() - 8 * 86400
    os.utime(old, (t, t))

    before = srd.scan(checkout_root=producer)
    assert before["status"] == "DIVERGENT"

    write_state_json("portfolio_news.json", {"v": "canonical"}, checkout_root=producer)
    after = srd.scan(checkout_root=producer, with_hashes=True)
    row = next(s for s in after["stores"] if s["store"] == "portfolio_news.json")
    assert row["byte_identical"] is True
    assert row["verdict"] == srd.IDENTICAL
