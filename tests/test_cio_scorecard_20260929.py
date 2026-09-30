"""Hermetic tests for CIO Desk scorecard aggregation."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.cio_scorecard import build_scorecard


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_scorecard_shape_and_fail_soft_dark(tmp_path: Path):
    out = build_scorecard(root=tmp_path, home={"ok": False}, brain={}, health=None)
    assert out["ok"] is True
    assert out["schema"] == "CIOScorecard@v1"
    assert out["authority"] == "READ_ONLY_ADVISORY"
    assert out["memory_behavior_influence"] == 0
    ids = [t["id"] for t in out["tiles"]]
    assert ids == [
        "desk_telegram",
        "hermes_research",
        "shared_spine",
        "decisions",
        "outcomes_learning",
        "platform_pin",
    ]
    by = {t["id"]: t for t in out["tiles"]}
    assert by["desk_telegram"]["status"] == "dark"
    assert by["shared_spine"]["status"] in ("dark", "degraded")
    assert by["platform_pin"]["status"] == "dark"


def test_organic_only_canary_is_not_working(tmp_path: Path):
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "spine_llm_organic.json").write_text(
        json.dumps(
            {
                "organic_latest_llm": 0,
                "canary_or_backfill_latest_llm": 1,
                "tips_with_latest_llm": 1,
                "spine_symbols": 10,
                "organic_symbols_sample": [],
            }
        ),
        encoding="utf-8",
    )
    out = build_scorecard(root=tmp_path, home={"ok": True, "cio_now": {"decisions": []}}, brain={}, health=None)
    spine = next(t for t in out["tiles"] if t["id"] == "shared_spine")
    assert spine["status"] == "degraded"
    assert spine["working"] is False
    assert "organic=0" in spine["verdict"]


def test_organic_observed_is_working(tmp_path: Path):
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "spine_llm_organic.json").write_text(
        json.dumps(
            {
                "organic_latest_llm": 1,
                "canary_or_backfill_latest_llm": 1,
                "tips_with_latest_llm": 2,
                "spine_symbols": 86,
                "organic_symbols_sample": ["HPE"],
            }
        ),
        encoding="utf-8",
    )
    out = build_scorecard(root=tmp_path, home={"ok": True}, brain={}, health=None)
    spine = next(t for t in out["tiles"] if t["id"] == "shared_spine")
    assert spine["status"] == "working"
    assert spine["working"] is True


def test_platform_tile_uses_health_criticals(tmp_path: Path):
    brain = {"_serving": {"pin_match": True, "loaded_pin_sha": "abc", "current_pin_sha": "abc"}}
    health = {"overall_score": 86, "status": "healthy", "counts": {"critical": 0}}
    out = build_scorecard(root=tmp_path, home={"ok": True}, brain=brain, health=health)
    plat = next(t for t in out["tiles"] if t["id"] == "platform_pin")
    assert plat["status"] == "working"
    health_bad = {"overall_score": 64, "status": "unhealthy", "counts": {"critical": 3}}
    out2 = build_scorecard(root=tmp_path, home={"ok": True}, brain=brain, health=health_bad)
    plat2 = next(t for t in out2["tiles"] if t["id"] == "platform_pin")
    assert plat2["status"] == "blocked"


def test_desk_telegram_counts_receipts(tmp_path: Path):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    _write_jsonl(
        tmp_path / "data" / "cio" / "cio_telegram_receipts.jsonl",
        [{"ts": now, "ok": True, "chat_id": "1"}, {"ts": now, "ok": True, "chat_id": "1"}],
    )
    out = build_scorecard(root=tmp_path, home={"ok": True}, brain={}, health=None)
    desk = next(t for t in out["tiles"] if t["id"] == "desk_telegram")
    assert desk["status"] == "working"
    assert desk["metrics"][0]["value"] == 2


def test_hermes_blocked_when_queue_not_ok(tmp_path: Path):
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "research_lane_health.json").write_text(
        json.dumps(
            {
                "lanes": {
                    "deepseek": {"ok": True, "firing": [], "non_error_24h": 10, "attempts_24h": 10},
                    "cio-hermes-queue": {"ok": False, "firing": ["unclassified_24h:3"]},
                }
            }
        ),
        encoding="utf-8",
    )
    out = build_scorecard(root=tmp_path, home={"ok": True}, brain={}, health=None)
    hermes = next(t for t in out["tiles"] if t["id"] == "hermes_research")
    assert hermes["status"] == "blocked"
