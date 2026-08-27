"""Divergent state is detected and deliberately not resolved.

The 2026-08-27 finding: the one AUTHORITATIVE store existed as two copies. The
fresher one was internally inconsistent by $3,748; the one the CIO reads
reconciled but was 30h stale. A machine picking "the newer one" would have put a
wrong portfolio total on a live surface.
"""
from __future__ import annotations

import json

from scripts.lib.store_consistency import (
    NEVER_AUTO_REMEDIATE,
    TYPE_DIVERGENCE,
    TYPE_INTERNALLY_INCONSISTENT,
    TYPE_MISSING,
    check,
    compare_copies,
    holdings_reconciles,
)


def _holdings(path, positions, stated):
    path.write_text(json.dumps({
        "holdings": [{"symbol": s, "market_value": v} for s, v in positions],
        "portfolio_totals": {"total_value": stated},
    }), encoding="utf-8")
    return path


# ── the incident ───────────────────────────────────────────────────────────

def test_the_fresher_copy_being_wrong_is_reported_not_resolved(tmp_path):
    """The exact shape: newer shadow, inconsistent; older canonical, consistent."""
    canonical = _holdings(tmp_path / "canonical.json", [("A", 700.0), ("B", 300.0)], 1000.0)
    shadow = _holdings(tmp_path / "shadow.json", [("A", 700.0), ("B", 250.0)], 1000.0)
    import os, time
    os.utime(shadow, (time.time() + 60, time.time() + 60))  # shadow is newer

    findings = check([("portfolio.holdings.current", canonical, shadow)])
    div = [f for f in findings if f["type"] == TYPE_DIVERGENCE]
    assert len(div) == 1

    f = div[0]
    assert f["severity"] == "critical"
    assert f["never_auto_remediate"] is True
    assert f["conflict"]["newer_copy"] == "shadow"
    # The decisive pairing: newer, and wrong.
    assert f["reconciliation"]["canonical"]["reconciles"] is True
    assert f["reconciliation"]["shadow"]["reconciles"] is False


def test_the_finding_carries_both_paths_both_times_and_both_hashes(tmp_path):
    """An operator cannot adjudicate two truths from a summary."""
    canonical = _holdings(tmp_path / "a.json", [("A", 1000.0)], 1000.0)
    shadow = _holdings(tmp_path / "b.json", [("A", 900.0)], 900.0)

    f = [x for x in check([("s", canonical, shadow)]) if x["type"] == TYPE_DIVERGENCE][0]
    c = f["conflict"]
    for side in ("primary", "shadow"):
        assert c[side]["path"] and c[side]["mtime"] and c[side]["sha256"]
    assert str(canonical) in f["message"] and str(shadow) in f["message"]


def test_divergence_is_on_the_never_auto_remediate_list():
    assert TYPE_DIVERGENCE in NEVER_AUTO_REMEDIATE
    assert TYPE_INTERNALLY_INCONSISTENT in NEVER_AUTO_REMEDIATE


# ── what is NOT a divergence ───────────────────────────────────────────────

def test_one_file_seen_twice_is_not_a_fork(tmp_path):
    """Same inode via hardlink — one file, not two truths."""
    a = _holdings(tmp_path / "a.json", [("A", 1000.0)], 1000.0)
    b = tmp_path / "b.json"
    b.hardlink_to(a)
    assert compare_copies(a, b) is None
    assert check([("s", a, b)]) == []


def test_byte_identical_copies_are_not_divergent(tmp_path):
    a = _holdings(tmp_path / "a.json", [("A", 1000.0)], 1000.0)
    b = _holdings(tmp_path / "b.json", [("A", 1000.0)], 1000.0)
    assert compare_copies(a, b) is None


def test_a_missing_shadow_is_not_a_divergence(tmp_path):
    a = _holdings(tmp_path / "a.json", [("A", 1000.0)], 1000.0)
    assert check([("s", a, tmp_path / "nope.json")]) == []


# ── other states ───────────────────────────────────────────────────────────

def test_absent_canonical_is_critical_and_says_whether_a_shadow_exists(tmp_path):
    shadow = _holdings(tmp_path / "shadow.json", [("A", 1000.0)], 1000.0)
    f = check([("s", tmp_path / "gone.json", shadow)])[0]
    assert f["type"] == TYPE_MISSING
    assert f["severity"] == "critical"
    assert f["shadow_exists"] is True


def test_internal_inconsistency_is_found_without_a_second_copy(tmp_path):
    bad = _holdings(tmp_path / "only.json", [("A", 700.0), ("B", 250.0)], 1000.0)
    findings = check([("s", bad, tmp_path / "absent.json")])
    inc = [f for f in findings if f["type"] == TYPE_INTERNALLY_INCONSISTENT]
    assert len(inc) == 1
    assert inc[0]["never_auto_remediate"] is True
    assert inc[0]["drift_pct"] > 0


def test_reconciliation_math(tmp_path):
    good = _holdings(tmp_path / "g.json", [("A", 600.0), ("B", 400.0)], 1000.0)
    bad = _holdings(tmp_path / "b.json", [("A", 600.0), ("B", 300.0)], 1000.0)
    assert holdings_reconciles(good)["reconciles"] is True
    r = holdings_reconciles(bad)
    assert r["reconciles"] is False and r["delta"] == -100.0


def test_a_file_that_is_not_holdings_shaped_is_not_judged(tmp_path):
    """No positions, no verdict — better than inventing one."""
    p = tmp_path / "other.json"
    p.write_text(json.dumps({"unrelated": True}), encoding="utf-8")
    assert holdings_reconciles(p) is None
