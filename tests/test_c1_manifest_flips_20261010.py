"""C1 manifest flips (operator approval 2026-10-10 ~18:28 ET, JOB_REDUCTION_DEEP_PASS.md D-1).

Pins the manifest sync that makes the four pipeline manifests flippable to --apply without a double run:
  * exactly the 75 approved crontab lines are stage steps, each tagged with its inventory id;
  * the dual-claimed lines (L184, L243: consolidation plan, operator ruling 2026-10-10 ~19:45 ET), approval-sheet lines (L185, L264) and the C2 line
    (L832) are `deferred`, never steps, so an --apply stage cannot run them a second time;
  * universe_history_retention (no cron line since tranche A rank 4) is excluded, not a step;
  * the steps whose cron text drifted (flock added, off-peak wrapper dropped) carry the live text again, so the
    step command is the same as what cron runs today;
  * the first flip's registry edit (hermes_learning) retires the 7 absorbed rows into the two stage lanes and
    takes hermes-config-governor out of dispatcher shadow wave D1b (row and allowlist entry together);
  * the premarket flip's registry edit (2026-10-11) retires the 36 rows whose every line is a premarket step and
    keeps market-regime-collector ACTIVE on its 16:05 line (after_close is not admissible).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pipelines"))

import pipeline_manifest as pm  # noqa: E402

MANIFESTS = ("premarket", "after_close", "hermes_learning", "hermes_overnight")
APPROVED = {
    "premarket/premarket": 37, "after_close/close-capture": 10, "after_close/broker-truth": 2,
    "after_close/planning": 14, "hermes_overnight/night": 4, "hermes_overnight/close": 1,
    "hermes_learning/learn": 6, "hermes_learning/tune": 1,
}
HELD = {"cron:L184": "DEFERRED_CONSOLIDATION_PLAN", "cron:L243": "DEFERRED_CONSOLIDATION_PLAN",
        "cron:L264": "DEFERRED_APPROVAL_SHEET", "cron:L185": "DEFERRED_APPROVAL_SHEET",
        "cron:L832": "DEFERRED_OTHER_PLAN"}


def _m(name: str) -> dict:
    return json.loads((ROOT / "config" / "pipelines" / f"{name}.json").read_text(encoding="utf-8"))


def _steps():
    for name in MANIFESTS:
        for stage, spec in _m(name)["stages"].items():
            for st in spec["steps"]:
                yield name, stage, st


def test_manifests_validate():
    for name in MANIFESTS:
        assert pm.validate(_m(name)) == [], name


def test_exactly_the_75_approved_lines_are_steps():
    counts: dict[str, int] = {}
    ids = []
    for name, stage, st in _steps():
        counts[f"{name}/{stage}"] = counts.get(f"{name}/{stage}", 0) + 1
        ids.append(st["inv_id"])
    assert counts == APPROVED
    assert sum(counts.values()) == 75
    assert len(set(ids)) == 75, "one crontab line can be absorbed once"


def test_held_lines_are_deferred_not_steps():
    step_ids = {st["inv_id"] for _, _, st in _steps()}
    assert not step_ids & set(HELD)
    deferred = {e.get("inv_id"): e["category"] for n in MANIFESTS for e in _m(n)["deferred"] if e.get("inv_id")}
    for inv, cat in HELD.items():
        assert deferred.get(inv) == cat, inv


def test_universe_history_retention_is_not_a_step():
    m = _m("hermes_overnight")
    assert "universe_history_retention" not in {st["id"] for s in m["stages"].values() for st in s["steps"]}
    assert any(e.get("former_step") == "night/universe_history_retention" and e["category"] == "ABSORBED_ELSEWHERE"
               for e in m["excluded"])


def test_drifted_steps_carry_the_live_lock():
    want = {"mint_identity_registry": "/tmp/tradeai_mint_identity_registry.lock",
            "market_regime_collector_am": "/tmp/tradeai_market_regime_collector.lock",
            "classify_candidates": "/tmp/tradeai_classify_candidates.lock",
            "sync_watchlist_items_to_db": "/tmp/tradeai_watchlist_sync.lock",
            "materialize_income_engine": "/tmp/materialize_income_engine.lock",
            "regime_collector_pm": "/tmp/tradeai_market_regime_classifier.lock",
            "sector_rs_daily": "/tmp/sector_rs_daily.lock",
            "data_gap_resolver_pre_overnight": "/tmp/data_gap_resolver.lock"}
    seen = {}
    for _, _, st in _steps():
        if st["id"] in want:
            seen[st["id"]] = st
            assert want[st["id"]] in st["command"], st["id"]
            assert st["command"] in st["cron_line_verbatim"], st["id"]
    assert set(seen) == set(want)
    yb = next(st for _, _, st in _steps() if st["id"] == "discovery_yield_builder")
    assert "run_with_deepseek_offpeak" not in yb["command"], "live L824 runs without the off-peak wrapper"


def test_hermes_learning_registry_edit():
    reg = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]}
    for lane in ("hermes-learning-pipeline-learn", "hermes-learning-pipeline-tune"):
        assert reg[lane]["state"] == "ACTIVE"
        assert reg[lane]["scheduler"]["command_text"].endswith("--apply")
    absorbed = {"hermes-outcome-grader": "learn", "hermes-tag-engine": "learn", "hermes-outcome-feedback-agent": "learn",
                "hermes-outcome-learning": "learn", "hermes-score-history-retention": "learn",
                "hermes-config-governor": "learn", "hermes-autonomous-self-tune": "tune"}
    for lane, stage in absorbed.items():
        r = reg[lane]
        assert r["state"] == "RETIRED" and r["superseded_by"] == f"hermes-learning-pipeline-{stage}", lane
        assert r["reason_confidence"] in ("CORRELATED", "ESTABLISHED")
    gov = reg["hermes-config-governor"]
    assert "dispatch" not in gov and "stage" not in gov["scheduler"]
    assert gov["dispatch_retired"]["wave"] == "D1b"
    allow = (ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8")
    assert '"lane_id": "hermes-config-governor"' not in allow
    # after_close is NOT flipped (not admissible: operator ruling 2026-10-11). hermes_overnight was flipped on cron
    # 2026-10-11 10:55 ET (grant 1ce02c1b) and its registry edit landed in train 6: test_hermes_overnight_registry_edit.
    assert reg["after-close-pipeline-planning"]["scheduler"]["command_text"].endswith("--dry-run")


def test_hermes_overnight_registry_edit():
    """C1 flip 2 (hermes_overnight, cron installed 2026-10-11 10:55 ET, grant 1ce02c1b): stage lanes --apply and the
    5 absorbed rows RETIRED into them; the two dispatcher shadow rows leave their waves and the allowlist."""
    reg = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]}
    for lane in ("hermes-overnight-pipeline-night", "hermes-overnight-pipeline-close"):
        assert reg[lane]["state"] == "ACTIVE"
        assert reg[lane]["scheduler"]["command_text"].endswith("--apply"), lane
    absorbed = {"hermes-discovery-yield-builder": "night", "hermes-tag-lift-discovery": "night",
                "hermes-industry-novelty-discovery": "night", "siem-to-hermes-backlog": "night",
                "hermes-source-curation": "close"}
    for lane, stage in absorbed.items():
        r = reg[lane]
        assert r["state"] == "RETIRED" and r["superseded_by"] == f"hermes-overnight-pipeline-{stage}", lane
        assert r["reason_confidence"] in ("CORRELATED", "ESTABLISHED")
    for lane, wave in (("hermes-tag-lift-discovery", "W4"), ("hermes-industry-novelty-discovery", "D2")):
        assert "dispatch" not in reg[lane] and "stage" not in reg[lane]["scheduler"], lane
        assert reg[lane]["dispatch_retired"]["wave"] == wave, lane
    allow = (ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8")
    assert '"lane_id": "hermes-tag-lift-discovery"' not in allow
    assert '"lane_id": "hermes-industry-novelty-discovery"' not in allow


#: C1 premarket flip (2026-10-11): the 36 rows whose every cron line is a premarket step.
PREMARKET_RETIRED = (
    "catalyst-calibration", "catalyst-calibration-monitor", "register-analyst-sources", "overnight-batch-outcomes",
    "source-outcome-attribution", "indicator-cache-refresh", "run-sec-form4-momentum-context", "mint-identity-registry",
    "strategy-backtester", "backtest-history-snapshot", "fred-data-ingest", "candidate-discovery-orchestrator",
    "backtest-results-aggregator", "watch-directives-monitor", "classify-candidates", "market-regime-classifier",
    "earnings-enrich", "research-intelligence-materialize", "fund-technicals-enrich", "refresh-symbol-cards",
    "build-lesson-candidates", "distributions-enrich", "sync-watchlist-items-to-db", "build-symbol-profiles-watchlist",
    "volatility-tier-refresh", "watch-valuation-backfill", "cio-draft-plan-hygiene", "materialize-income-engine",
    "llm-retry-monitor", "iris-taxonomy-agent-gaps", "opening-intelligence", "research-watchlist-discovery",
    "sync-dividend-data", "recommendation-intelligence-engine", "price-db-sync", "iris-proposal-curator",
)


def test_premarket_registry_edit():
    reg = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]}
    stage = reg["premarket-data-pipeline"]
    assert stage["state"] == "ACTIVE" and stage["scheduler"]["command_text"].endswith("--stage premarket --apply")
    allow = (ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8")
    for lane in PREMARKET_RETIRED:
        r = reg[lane]
        assert r["state"] == "RETIRED" and r["superseded_by"] == "premarket-data-pipeline", lane
        assert r["reason_confidence"] in ("CORRELATED", "ESTABLISHED"), lane
        assert r["c1_flip"]["manifest"] == "premarket", lane
        assert "generated_by" not in r and "dispatch" not in r and "stage" not in r["scheduler"], lane
        assert f'"lane_id": "{lane}"' not in allow, lane
    assert sum(1 for r in reg.values() if (r.get("c1_flip") or {}).get("manifest") == "premarket") == 36
    # market-regime-collector is NOT retired: its 16:05 line (L213, collector && classifier) stays on cron because
    # after_close is not admissible. Only its 06:30 line (L199) is absorbed; the row keeps the 16:05 slot alone.
    mrc = reg["market-regime-collector"]
    assert mrc["state"] == "ACTIVE" and "superseded_by" not in mrc
    assert mrc["scheduler"]["expression"] == "5 16 * * 1-5" and mrc["scheduler"]["schedules"] == ["5 16 * * 1-5"]
    assert "L199" in mrc["c1_note"] and "16:05" in mrc["c1_note"]
    # 37 steps = 36 retired rows + market_regime_collector_am (the kept row's absorbed 06:30 line)
    steps = pm.load(ROOT / "config" / "pipelines" / "premarket.json")["stages"]["premarket"]["steps"]
    assert len(steps) == len(PREMARKET_RETIRED) + 1
    assert "market_regime_collector_am" in {s["id"] for s in steps}
