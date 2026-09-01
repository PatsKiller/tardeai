"""WAVE F4 — search health monitor + degradation into research output.

Rails:
  * Monitor can run dry (probe=False) without inventing CAPTCHA data
  * Per-source state reports serving vs unresponsive (CAPTCHA named when measured)
  * Impaired / CAPTCHA-suspended stamps research output so thinner ≠ full
  * Durable status under production_state_root/data/runtime — survives cron
  * Thin call site: residual-web forwards stamp through run_hop (no silent drop)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import search_health as sh
from scripts.lib import search_health_degradation as shd
from scripts.lib import cio_residual_web as rw

NOW = datetime(2026, 8, 31, 5, 30, tzinfo=timezone.utc)

CAPTCHA_POOL = {
    "schema": "SearchHealth@v1",
    "authority": "READ_ONLY_ADVISORY",
    "as_of": "2026-08-31T05:30:00+00:00",
    "impaired": True,
    "reachable": True,
    "results": 10,
    "serving_engines": ["bing"],
    "engines_serving_count": 1,
    "unresponsive_engines": [
        {"engine": "duckduckgo", "reason": "CAPTCHA"},
        {"engine": "startpage", "reason": "Suspended: CAPTCHA"},
        {"engine": "brave", "reason": "too many requests"},
    ],
    "min_healthy_engines": 2,
    "degradation_note": (
        "Search pool impaired: 1 engine(s) served results (bing); "
        "3 unavailable (duckduckgo: CAPTCHA; startpage: Suspended: CAPTCHA; "
        "brave: too many requests). Coverage is narrower than a normal "
        "result set of this size."
    ),
}

HEALTHY_POOL = {
    "schema": "SearchHealth@v1",
    "impaired": False,
    "reachable": True,
    "results": 24,
    "serving_engines": ["bing", "brave"],
    "engines_serving_count": 2,
    "unresponsive_engines": [
        {"engine": "duckduckgo", "reason": "CAPTCHA"},
        {"engine": "startpage", "reason": "Suspended: CAPTCHA"},
    ],
    "degradation_note": "Search pool healthy: 2 engines served results (bing, brave).",
}


# ── monitor dry ────────────────────────────────────────────────────────────

def test_monitor_runs_dry_without_probing():
    lane = sh.collect_search_health(now=NOW, probe=False)
    assert lane["lane"] == "search-providers"
    assert isinstance(lane.get("budgets"), dict)
    assert lane.get("pool") == {} or not lane.get("pool")


def test_dry_report_does_not_invent_captcha_when_no_durable_status(tmp_path: Path):
    report = shd.dry_report(root=tmp_path, now=NOW, probe=False)
    assert report["dry"] is True
    assert report["monitor"]["lane"] == "search-providers"
    assert report["per_source"] == []
    assert report["captcha_suspended"] == []
    assert report["impaired"] is None
    assert "unavailable" in (report.get("degradation_note") or "").lower()
    assert report["durable_present"] is False


# ── per-source state ───────────────────────────────────────────────────────

def test_per_source_state_names_captcha_when_measured():
    rows = shd.per_source_state(CAPTCHA_POOL)
    by_eng = {r["engine"]: r for r in rows}
    assert by_eng["bing"]["state"] == "serving"
    assert by_eng["bing"]["captcha_suspended"] is False
    assert by_eng["duckduckgo"]["captcha_suspended"] is True
    assert by_eng["startpage"]["captcha_suspended"] is True
    assert by_eng["brave"]["captcha_suspended"] is False
    assert by_eng["brave"]["reason"] == "too many requests"


def test_per_source_state_empty_on_missing_pool_never_invents():
    assert shd.per_source_state(None) == []
    assert shd.per_source_state({}) == []
    assert shd.captcha_suspended_engines(None) == []


# ── durable status ─────────────────────────────────────────────────────────

def test_status_path_is_under_runtime_not_a_release():
    p = shd.status_path()
    assert p.as_posix().endswith("data/runtime/search_health.json")
    assert "portfolio-server/" not in p.as_posix()


def test_write_then_dry_read_round_trips_measured_captcha(tmp_path: Path):
    shd.write_status(CAPTCHA_POOL, root=tmp_path, now=NOW)
    doc = shd.read_status(tmp_path)
    assert doc is not None
    assert doc["impaired"] is True
    assert "duckduckgo" in doc["captcha_suspended"]
    assert "startpage" in doc["captcha_suspended"]

    stamp = shd.degradation_stamp(dry=True, root=tmp_path, now=NOW)
    assert stamp["search_pool_impaired"] is True
    assert stamp["search_thinner_than_full"] is True
    assert "duckduckgo" in stamp["search_captcha_suspended"]
    assert stamp["search_pool"]["status_source"] == "durable"


def test_corrupt_durable_status_yields_unavailable_not_invented_captcha(tmp_path: Path):
    path = shd.status_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert shd.read_status(tmp_path) is None
    stamp = shd.degradation_stamp(dry=True, root=tmp_path, now=NOW)
    assert stamp["search_sources"] == []
    assert stamp["search_captcha_suspended"] == []
    assert stamp["search_pool_impaired"] is None


# ── attach to research output ──────────────────────────────────────────────

def test_attach_degradation_marks_thinner_than_full_on_impaired_pool():
    out = {"answers": [{"claim": "x"}], "source_urls": ["https://example.com"]}
    shd.attach_degradation(out, pool=CAPTCHA_POOL, now=NOW)
    assert out["search_pool_impaired"] is True
    assert out["search_thinner_than_full"] is True
    assert "duckduckgo" in out["search_captcha_suspended"]
    assert "impaired" in out["search_degradation_note"].lower()
    assert len(out["search_sources"]) == 4


def test_healthy_pool_still_surfaces_captcha_suspended_peers():
    """Even when MIN_HEALTHY_ENGINES is met, CAPTCHA peers must be named —
    otherwise partial pool loss is silent."""
    stamp = shd.degradation_stamp(pool=HEALTHY_POOL, now=NOW)
    assert stamp["search_pool_impaired"] is False
    assert stamp["search_thinner_than_full"] is False
    assert stamp["search_captcha_suspended"] == ["duckduckgo", "startpage"]
    assert "CAPTCHA-suspended" in stamp["search_degradation_note"]


def test_attach_never_invents_captcha_without_measured_pool(tmp_path: Path):
    out: dict = {"answers": []}
    shd.attach_degradation(out, dry=True, root=tmp_path, now=NOW)
    assert out["search_captcha_suspended"] == []
    assert out["search_sources"] == []
    assert "CAPTCHA" not in (out.get("search_degradation_note") or "")


# ── residual-web thin call site: stamp survives run_hop ────────────────────

def test_run_hop_forwards_degradation_stamp_from_transport():
    """The F4 bug: live transport stamped, run_hop dropped. Prove forward."""

    def _transport(_req):
        return shd.attach_degradation(
            {
                "provider": "residual_web",
                "outcome": "PARTIAL",
                "cost_usd": 0.0,
                "answers": [],
                "still_unresolved": ["q1"],
                "source_urls": [],
                "note": "fixture transport",
            },
            pool=CAPTCHA_POOL,
            now=NOW,
        )

    hop = rw.run_hop(
        "HELD:FIXTURE",
        question="What do sources show?",
        question_ids=["q1"],
        apply=False,
        transport=_transport,
        now=NOW,
    )
    assert hop["search_pool_impaired"] is True
    assert hop["search_thinner_than_full"] is True
    assert "duckduckgo" in hop["search_captcha_suspended"]
    assert hop["search_degradation_note"]
    assert any(s["engine"] == "bing" for s in hop["search_sources"])


def test_stub_hop_does_not_invent_search_degradation():
    hop = rw.run_hop(
        "HELD:FIXTURE",
        question="stub only",
        apply=False,
        now=NOW,
    )
    # stub transport has no stamp keys — forward_stamp must not invent them
    for key in shd.STAMP_KEYS:
        assert key not in hop


def test_narrative_suffix_says_thinner_when_impaired():
    suffix = shd.narrative_suffix({
        "search_pool_impaired": True,
        "search_degradation_note": "Search pool impaired: 1 engine.",
        "search_captcha_suspended": ["duckduckgo"],
    })
    assert "thinner" in suffix.lower()
    assert suffix.endswith(".")


def test_narrative_suffix_names_captcha_when_not_impaired():
    suffix = shd.narrative_suffix({
        "search_pool_impaired": False,
        "search_captcha_suspended": ["duckduckgo", "startpage"],
    })
    assert "CAPTCHA-suspended" in suffix
    assert "duckduckgo" in suffix


def test_narrative_suffix_empty_when_nothing_measured():
    assert shd.narrative_suffix({}) == ""
    assert shd.narrative_suffix(None) == ""


def test_cc_binding_forwards_stamp():
    hop = shd.attach_degradation(
        {
            "outcome": "PARTIAL",
            "source_refs": [],
            "librarian": None,
            "cost_usd": 0.0,
            "paid_dispatch_entered": False,
        },
        pool=CAPTCHA_POOL,
        now=NOW,
    )
    binding = rw.cc_binding({"subject_key": "HELD:X"}, hop, now=NOW)
    assert binding["search_pool_impaired"] is True
    assert "startpage" in binding["search_captcha_suspended"]


# ── probe path persists for later dry reads ────────────────────────────────

def test_probe_persist_writes_durable_for_subsequent_dry(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        sh, "probe_searxng",
        lambda *a, **k: {
            "reachable": True,
            "results": 10,
            "serving_engines": ["bing"],
            "engine_counts": {"bing": 10},
            "unresponsive": [
                {"engine": "duckduckgo", "reason": "CAPTCHA"},
                {"engine": "startpage", "reason": "Suspended: CAPTCHA"},
            ],
        },
    )
    stamp = shd.degradation_stamp(
        probe=True, persist=True, root=tmp_path, now=NOW,
    )
    assert stamp["search_pool_impaired"] is True
    assert stamp["search_pool"]["status_source"] == "probe"
    assert shd.status_path(tmp_path).is_file()

    dry = shd.degradation_stamp(dry=True, root=tmp_path, now=NOW)
    assert dry["search_pool"]["status_source"] == "durable"
    assert "duckduckgo" in dry["search_captcha_suspended"]
