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


def test_hermes_reads_coverage_stall_24h_counts(tmp_path: Path):
    """Live lane JSON parks deepseek_ok_24h on coverage-stall, not deepseek."""
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "research_lane_health.json").write_text(
        json.dumps(
            {
                "lanes": {
                    "deepseek": {"ok": True, "firing": []},
                    "cio-hermes-queue": {"ok": True, "firing": []},
                    "coverage-stall": {
                        "ok": False,
                        "firing": ["research_up_thesis_flat:deepseek_ok_24h=73,thesis_substantive=7/21"],
                        "non_error_24h": 73,
                        "attempts_24h": 73,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    out = build_scorecard(root=tmp_path, home={"ok": True}, brain={}, health=None)
    hermes = next(t for t in out["tiles"] if t["id"] == "hermes_research")
    assert hermes["status"] == "degraded"
    by_label = {m["label"]: m["value"] for m in hermes["metrics"]}
    assert by_label["DeepSeek ok 24h"] == 73
    assert by_label["Attempts 24h"] == 73


def test_decisions_tile_from_attention_stamp(tmp_path: Path):
    from scripts.lib.cio_scorecard import get_cio_scorecard, stamp_home_attention

    stamp_home_attention(
        {
            "ok": True,
            "as_of": "2026-09-30T12:00:00+00:00",
            "cio_now": {
                "decision_count": 3,
                "material_today_count": 3,
                "open_plans_count": 914,
                "attention": {"material_today": 3, "open_plans": 914},
            },
        },
        root=tmp_path,
    )
    out = get_cio_scorecard(root=tmp_path)
    dec = next(t for t in out["tiles"] if t["id"] == "decisions")
    assert dec["status"] == "working"
    by_label = {m["label"]: m["value"] for m in dec["metrics"]}
    assert by_label["Decisions"] == 3
    assert by_label["Material today"] == 3
    assert by_label["Open plans"] == 914


def test_judgment_stamp_surfaces_on_scorecard(tmp_path: Path):
    from scripts.lib.cio_scorecard import get_cio_scorecard, stamp_brain_judgment

    stamp_brain_judgment(
        {
            "ok": True,
            "as_of": "2026-09-30T12:00:00+00:00",
            "portfolio_state": {
                "total_portfolio_value_usd": 1263019,
                "observed_cash_usd": 902013,
                "truth_quality": "UNVERIFIED_INVESTABLE",
                "investable_cash_status": "UNVERIFIED_INVESTABLE",
            },
            "portfolio_thesis": {"current_posture": "HOLD_CASH_RESEARCH_FIRST", "state": "INSUFFICIENT_DATA"},
            "capital_plan": {"stance": "RESEARCH_FIRST", "next_review": "ON_BLOCKER_RESOLUTION"},
            "capital_situation": {"conclusion": "RESEARCH_FIRST", "blockers": ["POLICY_REQUIRED"]},
            "operator_value": {
                "current_recommendation": "RESEARCH_FIRST",
                "why": "evidence incomplete",
                "what_happens_next": "ON_BLOCKER_RESOLUTION",
                "uncertainty": ["POLICY_REQUIRED"],
            },
            "market_context": {
                "fields": {
                    "regime": {"value": "risk_on_trend", "state": "VERIFIED"},
                    "vix_close": {"value": 16.0, "state": "VERIFIED"},
                    "breadth": {"value": "broad", "state": "VERIFIED"},
                    "valuation": {"value": None, "state": "UNAVAILABLE"},
                }
            },
            "unresolved_conflicts": ["POLICY_REQUIRED"],
        },
        root=tmp_path,
    )
    out = get_cio_scorecard(root=tmp_path)
    j = out.get("judgment") or {}
    assert j.get("ok") is True
    assert j["portfolio_state"]["total_portfolio_value_usd"] == 1263019
    assert j["operator_value"]["current_recommendation"] == "RESEARCH_FIRST"
    assert "POLICY_REQUIRED" in (out.get("blockers_top") or [])
