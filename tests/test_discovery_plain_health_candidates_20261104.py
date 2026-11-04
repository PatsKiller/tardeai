"""FQ-059 — research staging: a system-health candidate says what broke and what it costs.

Live at release 105df180e the RI desk's "Proposed topics" rail showed:
  label   "System health: proposal_enrichment ERROR"
  summary "cron_health check for proposal_enrichment is ERROR (severity INFO, failure_count 1) — success_timestamp_in_future"

The operator is reading the health checker's vocabulary, not the finding. These tests pin:
* the plain wording names the task and the consequence, in words;
* the health checker's own sentence is kept, as `technical` / in the evidence / in the meta — never dropped;
* a candidate that does not have this shape is left exactly as it is (no guessing at another producer's text);
* the producer writes the plain text at the source, so a new row is born readable.

Hermetic: no database, no network. The producer test stubs its row reader.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery.plain_text import plain_health_candidate as plain  # noqa: E402
from lib.hermes_discovery import coverage as COV  # noqa: E402

LIVE_LABEL = "System health: proposal_enrichment ERROR"
LIVE_SUMMARY = ("cron_health check for proposal_enrichment is ERROR "
                "(severity INFO, failure_count 1) — success_timestamp_in_future")


# ── the helper ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_live_candidate_reads_in_plain_english():
    got = plain(LIVE_LABEL, LIVE_SUMMARY)
    assert got is not None
    assert "proposal enrichment" in got["label"]
    assert "reported an error" in got["summary"]
    assert "last-success time is in the future" in got["summary"], got["summary"]
    assert "research it feeds" in got["summary"], got["summary"]


def test_no_health_checker_vocabulary_reaches_the_plain_fields():
    got = plain(LIVE_LABEL, LIVE_SUMMARY)
    for key in ("label", "summary"):
        text = got[key]
        for raw in ("cron_health", "success_timestamp_in_future", "failure_count", "severity INFO", "ERROR"):
            assert raw not in text, (key, raw, text)


def test_the_raw_sentence_is_kept_as_technical():
    got = plain(LIVE_LABEL, LIVE_SUMMARY)
    assert "cron_health" in got["technical"]
    assert "success_timestamp_in_future" in got["technical"]


def test_a_missing_task_says_what_is_not_happening():
    got = plain("System health: atm_position_reconciler MISSING",
                "cron_health check for atm_position_reconciler is MISSING (severity INFO, failure_count 1)")
    assert "no recent run" in got["summary"]
    assert "not being produced" in got["summary"]


def test_an_unknown_reason_is_quoted_not_invented():
    got = plain("System health: x_task ERROR", "cron_health check for x_task is ERROR — brand_new_failure_mode")
    assert "brand_new_failure_mode" in got["summary"]
    assert "reported an error" in got["summary"]


def test_a_non_health_candidate_is_left_alone():
    assert plain("Watchlist coverage: missing research over 30 days",
                 "50+ governed watchlist symbol(s) with no research rows in 30d: AAA, BBB") is None
    assert plain(None, None) is None


# ── the producer ─────────────────────────────────────────────────────────────────────────────────────────────────


def _row(**kw):
    base = {"component": "proposal_enrichment", "check_type": "cron_health", "status": "ERROR", "severity": "INFO",
            "failure_count": 1, "last_error": "success_timestamp_in_future", "updated_at": "2026-11-04T15:00:00Z"}
    base.update(kw)
    return base


def test_the_producer_writes_a_plain_label_and_summary(monkeypatch):
    monkeypatch.setattr(COV, "_rows", lambda *a, **k: [_row()])
    payloads = COV.system_ops_findings(limit=1)
    assert len(payloads) == 1
    p = payloads[0]
    assert "proposal enrichment" in p["label"]
    assert "cron_health" not in p["label"]
    assert "success_timestamp_in_future" not in p["summary"]
    assert "research it feeds" in p["summary"]


def test_the_producer_keeps_the_raw_sentence_in_evidence_and_meta(monkeypatch):
    monkeypatch.setattr(COV, "_rows", lambda *a, **k: [_row()])
    p = COV.system_ops_findings(limit=1)[0]
    assert "cron_health" in (p["meta"].get("technical") or "")
    assert "success_timestamp_in_future" in (p["meta"].get("technical") or "")
    note = (p["evidence"] or [{}])[0].get("note", "")
    assert "proposal_enrichment" in note and "ERROR" in note
    assert p["meta"].get("component") == "proposal_enrichment"
