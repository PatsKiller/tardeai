"""The health-agent -> boundary translation, and the enforcement gate.

CL-63. The boundary was wired but never fed. Feeding it is not a pass-through:
the producer and consumer share no category vocabulary, and the producer's
severities are strings where the consumer compares integers.

These tests pin the properties that make feeding it SAFE rather than merely
done. The mapping itself lives in config/cio_health_snapshot_feed.json because
it decides what can block CIO advisory output.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cio_health_boundary import CIOHealthBoundary
from scripts.lib.cio_health_snapshot_feed import (
    enforcement_enabled,
    load_feed_config,
    load_health_snapshot,
)

CFG = {
    "source_path": "s/health.json",
    "max_age_minutes": 120,
    "enforce": False,
    "severity_map": {"critical": 3, "warning": 2, "info": 1},
    "category_map": {"data_quality": ["database"], "retirement_planning": []},
}


def _write(root, payload):
    p = root / "s"
    p.mkdir(parents=True, exist_ok=True)
    (p / "health.json").write_text(json.dumps(payload), encoding="utf-8")


def _payload(**over):
    d = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": 64,
        "status": "unhealthy",
        "category_scores": {"data_quality": 60},
        "findings": [{"category": "data_quality", "severity": "critical", "type": "t1"}],
    }
    d.update(over)
    return d


def test_translates_categories_and_severities(tmp_path):
    _write(tmp_path, _payload())
    snap = load_health_snapshot(CFG, root=tmp_path)
    assert snap.category_scores == {"database": 60}
    assert [f["severity"] for f in snap.findings] == [3], "strings become ints"
    assert snap.findings[0]["category"] == "database"


def test_string_severity_would_have_crashed_evaluate(tmp_path):
    """Raw pass-through raises TypeError inside evaluate(); translation is not
    cosmetic."""
    _write(tmp_path, _payload())
    snap = load_health_snapshot(CFG, root=tmp_path)
    CIOHealthBoundary(snap).evaluate("cio_run", ["income"])  # must not raise


def test_unmapped_category_carries_no_evidence(tmp_path):
    """retirement_planning maps to nothing, so it must not invent coverage."""
    _write(tmp_path, _payload(category_scores={"retirement_planning": 100}, findings=[]))
    snap = load_health_snapshot(CFG, root=tmp_path)
    assert snap.category_scores == {}
    assert CIOHealthBoundary(snap).evaluate("cio_run", ["income"]).state == "UNKNOWN"


def test_worst_score_wins_not_average(tmp_path):
    """Averaging a failing category against a healthy one manufactures a
    passing grade neither earned."""
    cfg = dict(CFG, category_map={"a": ["database"], "b": ["database"]})
    _write(tmp_path, _payload(category_scores={"a": 20, "b": 100}, findings=[]))
    assert load_health_snapshot(cfg, root=tmp_path).category_scores == {"database": 20}


def test_stale_snapshot_is_not_evidence(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
    _write(tmp_path, _payload(captured_at=old))
    assert load_health_snapshot(CFG, root=tmp_path) is None


def test_missing_or_malformed_artifact_returns_none(tmp_path):
    assert load_health_snapshot(CFG, root=tmp_path) is None
    (tmp_path / "s").mkdir(parents=True, exist_ok=True)
    (tmp_path / "s" / "health.json").write_text("{not json", encoding="utf-8")
    assert load_health_snapshot(CFG, root=tmp_path) is None


def test_no_timestamp_is_refused(tmp_path):
    _write(tmp_path, _payload(captured_at=None))
    assert load_health_snapshot(CFG, root=tmp_path) is None


def test_unmappable_severity_is_dropped_not_guessed(tmp_path):
    _write(tmp_path, _payload(findings=[{"category": "data_quality", "severity": "spicy"}]))
    assert load_health_snapshot(CFG, root=tmp_path).findings == []


@pytest.mark.parametrize("val,expected", [(True, True), (False, False), (None, False),
                                          ("true", False), (1, False)])
def test_enforcement_defaults_closed(val, expected):
    """Only a real boolean True enables gating. A truthy string must not."""
    assert enforcement_enabled({"enforce": val}) is expected


def test_enforcement_absent_config_is_off():
    assert enforcement_enabled({}) is False


def test_shipped_config_is_valid_and_measured():
    """The real config must parse, and the mapping choices that make
    enforcement survivable must hold.

    `enforce` is deliberately NOT asserted either way: it is an operator switch
    and a test that pins it would fight the operator. What IS pinned is the pair
    of mapping decisions that were measured -- because with enforcement ON, a
    regression in either one stops being a wrong answer and becomes an outage.
    """
    cfg = load_feed_config()
    assert cfg, "config/cio_health_snapshot_feed.json must be readable"
    assert isinstance(cfg["enforce"], bool), "must be a real bool, not truthy"
    assert cfg["severity_map"]["critical"] == 3, (
        "critical=4 was measured to block all 15 domains; see _severity_why"
    )
    assert "broker" not in cfg["category_map"]["execution_health"], (
        "execution_health->broker was measured to block portfolio/holdings/risk "
        "on workflow evidence that does not support it; see _category_map_why"
    )
    assert cfg.get("max_age_minutes"), (
        "with enforcement on, an unbounded-age snapshot could block runs on a "
        "stale bill of health"
    )


def test_enforcement_requires_a_bounded_snapshot_age():
    """A gate that can block must not act on evidence of unknown age."""
    cfg = load_feed_config()
    if cfg.get("enforce") is True:
        assert isinstance(cfg["max_age_minutes"], (int, float))
        assert 0 < cfg["max_age_minutes"] <= 1440
