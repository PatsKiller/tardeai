"""Governed research producer — canonical recurring research → wake feed path.

Phase 2 (Grok-closure). Fixtures only; no paid calls. The ONLY provider path is
``brave_router.search``, injected with a fake transport.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import brave_router as br
from scripts.lib.governed_research_producer import (
    FEATURE_FLAG,
    ProducerResult,
    enabled,
    feed_summary,
    produce_research,
    source_sha,
)


class FixedClock:
    def __init__(self, start: datetime):
        self._t = start

    def __call__(self) -> datetime:
        return self._t

    def advance(self, **kw) -> None:
        self._t = self._t + timedelta(**kw)


def _fixture_transport(payload=None):
    payload = payload or {
        "web": {
            "results": [
                {
                    "title": "Visa earnings guidance upgrade",
                    "url": "https://www.reuters.com/markets/v-earnings",
                    "description": "Visa reports strong quarter",
                }
            ]
        }
    }

    def _t(url: str, hdrs: dict):
        return payload, {"x-ratelimit-policy": "50;w=1, 0;w=2592000"}

    return _t


def _failing_transport(exc: Exception | None = None):
    def _t(url: str, hdrs: dict):
        raise exc or RuntimeError("provider down")

    return _t


@pytest.fixture
def env(tmp_path: Path) -> dict:
    return {
        FEATURE_FLAG: "1",
        "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH": str(tmp_path / "feed" / "research_objects.jsonl"),
        "GOVERNED_RESEARCH_PRODUCER_HEALTH_PATH": str(tmp_path / "health.json"),
        "TRADEAI_SOURCE_SHA": "abc123",
    }


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


def _targets():
    return [{"symbol": "V", "subject_guid": "sg-v", "query": "Visa stock catalyst news"}]


def test_disabled_no_side_effect(tmp_path: Path, env: dict):
    env[FEATURE_FLAG] = "0"
    res = produce_research(targets=_targets(), env=env, root=tmp_path)
    assert isinstance(res, ProducerResult)
    assert res.disabled and res.outcome == "disabled" and not res.ok
    feed = Path(env["TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"])
    assert not feed.exists()


def test_produces_research_object_only_after_real_success(tmp_path: Path, env: dict):
    res = produce_research(
        targets=_targets(),
        env=env,
        root=tmp_path,
        transport=_fixture_transport(),
    )
    assert res.ok and res.produced == 1 and res.outcome == "produced"
    feed = Path(env["TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"])
    rows = [json.loads(l) for l in feed.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    row = rows[0]
    # Identifier-compatible with wake_subject_selector (research_object_id OR id).
    assert row["research_object_id"] and row["id"] == row["research_object_id"]
    assert row["subject_guid"] == "sg-v"
    assert row["source_url"].startswith("https://")
    assert row["content_hash"]
    assert row["source_sha"] == "abc123"
    assert row["trigger"]["kind"] == "scheduled"
    assert row["provenance"]["producer"] == "governed_research_producer"


def test_provider_unavailable_no_object(tmp_path: Path, env: dict):
    res = produce_research(
        targets=_targets(),
        env=env,
        root=tmp_path,
        transport=_failing_transport(),
    )
    assert not res.ok and res.produced == 0 and res.failed == 1
    assert res.outcome == "broken"
    feed = Path(env["TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"])
    assert not feed.exists()


def test_budget_denied_distinguished(tmp_path: Path, env: dict, monkeypatch):
    def _refused(**kw):
        raise br.BudgetRefused("daily cap")

    monkeypatch.setattr(br, "reserve", _refused)
    res = produce_research(
        targets=_targets(),
        env=env,
        root=tmp_path,
        transport=_fixture_transport(),
    )
    assert not res.ok and res.produced == 0
    assert res.budget_denied == 1
    assert any("BUDGET_REFUSED" in e for e in res.errors)


def test_stale_only_empty_results_not_broken(tmp_path: Path, env: dict):
    res = produce_research(
        targets=_targets(),
        env=env,
        root=tmp_path,
        transport=_fixture_transport({"web": {"results": []}}),
    )
    assert res.produced == 0 and res.failed == 0
    assert res.outcome == "nothing_eligible"


def test_duplicate_result_deduped(tmp_path: Path, env: dict):
    t = _fixture_transport()
    first = produce_research(targets=_targets(), env=env, root=tmp_path, transport=t)
    second = produce_research(targets=_targets(), env=env, root=tmp_path, transport=t)
    assert first.produced == 1
    assert second.produced == 0 and second.deduped == 1
    feed = Path(env["TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"])
    rows = [json.loads(l) for l in feed.read_text().splitlines() if l.strip()]
    assert len(rows) == 1


def test_source_sha_without_env_resolves_via_runtime_identity(tmp_path: Path, env: dict):
    """Cron often omits BUILD_SHA; producers must still stamp a real served SHA."""
    env.pop("TRADEAI_SOURCE_SHA", None)
    env.pop("BUILD_SHA", None)
    env.pop("SOURCE_COMMIT", None)
    sha = source_sha(env)
    assert sha and sha != "unknown"
    res = produce_research(
        targets=_targets(),
        env=env,
        root=tmp_path,
        transport=_fixture_transport(),
    )
    assert res.ok
    feed = Path(env["TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"])
    row = json.loads(feed.read_text().splitlines()[0])
    assert row["source_sha"] == sha


def test_missing_subject_guid_skipped(tmp_path: Path, env: dict, monkeypatch):
    # lookup_subject returns no guid for an unknown symbol → not eligible.
    monkeypatch.setattr(
        "scripts.lib.cio_subject_guid.lookup_subject",
        lambda symbol, root=None: {"subject_guid": None},
    )
    res = produce_research(
        targets=[{"symbol": "UNKNOWNXYZ", "query": "x"}],
        env=env,
        root=tmp_path,
        transport=_fixture_transport(),
    )
    assert res.eligible == 0 and res.outcome == "nothing_eligible"
    assert not Path(env["TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"]).exists()


def test_empty_feed_summary(tmp_path: Path, env: dict):
    s = feed_summary(env)
    assert s["rows"] == 0 and s["latest_at"] is None


def test_feed_summary_reports_age(tmp_path: Path, env: dict):
    produce_research(targets=_targets(), env=env, root=tmp_path, transport=_fixture_transport())
    s = feed_summary(env)
    assert s["rows"] == 1
    assert s["latest_at"] is not None
    assert s["age_seconds"] is not None


def test_no_direct_provider_bypass():
    """The ONLY provider path is brave_router.search; no urlopen/requests/socket."""
    text = (ROOT / "scripts" / "lib" / "governed_research_producer.py").read_text()
    for forbidden in (
        "urlopen(",
        "urllib.request",
        "requests.get",
        "requests.post",
        "socket.",
        "http.client",
        "api.search.brave.com",
    ):
        assert forbidden not in text, f"direct provider bypass found: {forbidden}"
    # The governed router call site is present.
    assert "router.search(" in text or "brave_router.search(" in text


def test_atomic_feed_append_leaves_no_tmp(tmp_path: Path, env: dict):
    produce_research(targets=_targets(), env=env, root=tmp_path, transport=_fixture_transport())
    feed_dir = Path(env["TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"]).parent
    leftovers = [p for p in feed_dir.glob("*.tmp")]
    assert leftovers == []
