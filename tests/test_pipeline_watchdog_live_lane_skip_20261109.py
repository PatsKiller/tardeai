"""pipeline_watchdog: never run a second scheduler for a lane the n8n dispatcher runs live.

LQ-20261107-1722. `pipeline_schedule` rows predate the n8n cutover. When the lane's own
`config/lane_registry.json` row says `dispatch.mode: live`, the watchdog retried the script anyway:
outside the coordination ledger, without the lane's lock, from the dev checkout
(DONE-LQ-20261107-1714 §5 — incubator-llm-screener ran twice on 2026-11-09).

The guard must also keep checking rows the dispatcher does NOT own. `news_ingestion` is the case in
the live registry: the live lane is `scripts/news_ingestion.py --tail-rotate`, while the schedule
row runs the un-flagged script (the priority ingestion). A script-only match would silence that row.

Runs without psycopg2 or a rendered .env (CI installs only pytest + pyyaml).
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def wd(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg2", types.ModuleType("psycopg2"))
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    sys.modules.pop("pipeline_watchdog", None)
    mod = importlib.import_module("pipeline_watchdog")
    yield mod
    sys.modules.pop("pipeline_watchdog", None)


def _lane(lane_id, match, *, mode="live", state="ACTIVE"):
    row = {"lane_id": lane_id, "state": state, "scheduler": {"match": match}}
    if mode is not None:
        # the full block `lane_dispatch.parse_dispatch_block` requires
        row["dispatch"] = {
            "mode": mode,
            "cron": ["10 8 * * 1-5"],
            "wave": "W4",
            "class": "pipeline",
            "priority": 4,
            "retry_policy": "standard-transient",
        }
    return row


def _registry(tmp_path, *rows):
    p = tmp_path / "lane_registry.json"
    p.write_text(json.dumps({"schema": "LaneRegistry@v1", "lanes": list(rows)}), encoding="utf-8")
    return p


class _Cur:
    """Returns the schedule rows once, then None for each per-job pipeline_runs lookup."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return None


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cur(self._rows)


def _row(script, command, *, critical=True):
    now = datetime.now()
    # due now (latency 0): the check is only reached when the job is overdue
    return (script, script, now.hour, now.minute, 0, 1, critical, command, "*")


def _issues(wd, rows):
    return wd.check_pipeline_execution(_Conn(rows))


# ── the live lane is skipped ──────────────────────────────────────────────────


def test_row_whose_lane_runs_live_is_skipped_and_logged(wd, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(tmp_path, _lane("incubator-llm-screener", "scripts/incubator_llm_screener.py"))),
    )
    rows = [_row("incubator_llm_screener",
                 "cd /home/runner/proj && python3 scripts/incubator_llm_screener.py --run")]
    with caplog.at_level(logging.INFO, logger=wd.log.name):
        assert _issues(wd, rows) == []
    hits = [r for r in caplog.records if "lane incubator-llm-screener is dispatch.mode live" in r.getMessage()]
    assert hits and hits[0].levelno == logging.INFO


def test_absolute_command_path_matches_the_registry_relative_path(wd, monkeypatch, tmp_path):
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(tmp_path, _lane("finviz-screener-runner", "scripts/finviz_screener_runner.py"))),
    )
    rows = [_row("finviz_screener_runner", "/opt/x/.venv/bin/python /opt/x/scripts/finviz_screener_runner.py --run")]
    assert _issues(wd, rows) == []


def test_script_name_with_py_but_empty_command_is_matched(wd, monkeypatch, tmp_path):
    # aegis_transcript_discovery: script_name carries ".py" and the row has no command
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(tmp_path, _lane("aegis-transcript-discovery", "scripts/aegis_transcript_discovery.py"))),
    )
    assert _issues(wd, [_row("aegis_transcript_discovery.py", None, critical=False)]) == []


def test_registry_match_given_as_a_list_is_supported(wd, monkeypatch, tmp_path):
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(tmp_path, _lane("agent-outcome-scorer", ["scripts/agent_outcome_scorer.py"]))),
    )
    assert _issues(wd, [_row("agent_outcome_scorer", ".venv/bin/python scripts/agent_outcome_scorer.py")]) == []


# ── the rows the dispatcher does NOT own are still checked ────────────────────


def test_same_script_without_the_live_lane_flags_is_still_checked(wd, monkeypatch, tmp_path):
    # news_ingestion: the live lane is --tail-rotate; the row runs the un-flagged priority script
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(
            tmp_path,
            _lane("news-ingestion-tail", "scripts/news_ingestion.py --tail-rotate"),
            _lane("news-ingestion", "scripts/news_ingestion.py --priority", mode=None),
        )),
    )
    issues = _issues(wd, [_row("news_ingestion", ".venv/bin/python scripts/news_ingestion.py")])
    assert [i["script"] for i in issues] == ["news_ingestion"]


def test_flag_match_skips_the_row(wd, monkeypatch, tmp_path):
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(tmp_path, _lane("news-ingestion-tail", "scripts/news_ingestion.py --tail-rotate"))),
    )
    assert _issues(wd, [_row("news_ingestion_tail", ".venv/bin/python scripts/news_ingestion.py --tail-rotate")]) == []


def test_lane_with_mode_off_does_not_skip(wd, monkeypatch, tmp_path):
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(tmp_path, _lane("manual-job", "scripts/manual_job.py", mode=None))),
    )
    issues = _issues(wd, [_row("manual_job", ".venv/bin/python scripts/manual_job.py")])
    assert [i["script"] for i in issues] == ["manual_job"]


def test_redirect_in_the_registry_match_is_not_a_flag(wd, monkeypatch, tmp_path):
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(tmp_path, _lane("finviz-enrichment",
                                      "scripts/finviz_enrichment.py >> logs/finviz_enrichment.log"))),
    )
    assert _issues(wd, [_row("finviz_enrichment", ".venv/bin/python scripts/finviz_enrichment.py")]) == []


def test_a_malformed_dispatch_block_is_not_a_live_lane(wd, monkeypatch, tmp_path):
    # dispatch_mode fails closed to "off", which means "the dispatcher does not run it" — the
    # watchdog is then the only scheduler left and must keep checking the row.
    broken = {"lane_id": "manual-job", "state": "ACTIVE", "scheduler": {"match": "scripts/manual_job.py"},
              "dispatch": {"mode": "live"}}
    monkeypatch.setenv(wd.LANE_REGISTRY_ENV, str(_registry(tmp_path, broken)))
    issues = _issues(wd, [_row("manual_job", ".venv/bin/python scripts/manual_job.py")])
    assert [i["script"] for i in issues] == ["manual_job"]


# ── fail closed ──────────────────────────────────────────────────────────────


def test_unreadable_registry_skips_every_job_and_says_so(wd, monkeypatch, tmp_path, caplog):
    bad = tmp_path / "lane_registry.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(wd.LANE_REGISTRY_ENV, str(bad))
    with caplog.at_level(logging.ERROR, logger=wd.log.name):
        assert _issues(wd, [_row("manual_job", ".venv/bin/python scripts/manual_job.py")]) == []
    assert any(r.levelno >= logging.ERROR and "fail closed" in r.getMessage() for r in caplog.records)


def test_missing_registry_copy_falls_back_to_the_next_copy(wd, tmp_path):
    served = tmp_path / "served.json"
    served.write_text(json.dumps({"lanes": [_lane("incubator-llm-screener", "scripts/incubator_llm_screener.py")]}))
    index = wd._live_lane_index([tmp_path / "absent.json", served])
    assert "incubator_llm_screener.py" in index


def test_missing_registry_everywhere_returns_none(wd, tmp_path):
    assert wd._live_lane_index([tmp_path / "absent.json"]) is None


# ── the retry path cannot re-fire a live lane either ─────────────────────────


def test_handle_pipeline_issues_does_not_retry_a_live_lane(wd, monkeypatch, tmp_path):
    monkeypatch.setenv(
        wd.LANE_REGISTRY_ENV,
        str(_registry(tmp_path, _lane("incubator-llm-screener", "scripts/incubator_llm_screener.py"))),
    )
    ran = []
    monkeypatch.setattr(wd.subprocess, "run", lambda *a, **k: ran.append(a) or types.SimpleNamespace(returncode=0))
    issue = {"script": "incubator_llm_screener", "issue": "not_started", "critical": True,
             "command": "python3 scripts/incubator_llm_screener.py --run"}
    wd.handle_pipeline_issues(_Conn([]), [dict(issue)])
    assert ran == []


def test_handle_pipeline_issues_fails_closed_without_a_registry(wd, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv(wd.LANE_REGISTRY_ENV, str(tmp_path / "absent.json"))
    ran = []
    monkeypatch.setattr(wd.subprocess, "run", lambda *a, **k: ran.append(a) or types.SimpleNamespace(returncode=0))
    issue = {"script": "manual_job", "issue": "not_started", "critical": True,
             "command": ".venv/bin/python scripts/manual_job.py"}
    with caplog.at_level(logging.ERROR, logger=wd.log.name):
        wd.handle_pipeline_issues(_Conn([]), [dict(issue)])
    assert ran == []
    assert any("fail closed" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
