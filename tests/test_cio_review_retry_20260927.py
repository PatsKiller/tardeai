"""A failed options CIO review must be retryable, classified honestly, and capped (2026-09-27).

DELL's new 520/500 spread (guid cb162b79) got one INVALID review, then every later lifecycle
pass read "unparseable: no JSON object in response": the router dedupes on the (guid, pin) job
key and returned the failed attempt's empty answer. Meanwhile a probe with a fresh key returned
a valid MONITOR_ONLY review that cited the 8-K itself. Hermetic."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import options_cio_review as ocr  # noqa: E402
from scripts.lib import options_thesis_lifecycle as otl  # noqa: E402
from scripts.lib.options_thesis import OptionsThesisStore  # noqa: E402

P = {"symbol": "DELL", "strategy": "credit_spread", "option_strategy_guid": "g1", "strike": 520.0,
     "short_strike": 520.0, "long_strike": 500.0, "premium": 6.35, "contracts": 1, "dte": 54,
     "underlying_price": 563.0, "options_thesis": {"pin": "opt_g1@v2", "missing_required": []},
     "thesis_state": "THIN", "enterprise": {"blocks": []}, "expiration": "2026-11-20"}


def test_job_key_carries_the_attempt_number_only_on_retries():
    seen = []

    def llm(prompt):
        seen.append(getattr(llm, "key", None))
        return {"success": True, "response": "not json at all"}

    r0 = ocr.review(dict(P), mode="live", llm_fn=llm)
    r2 = ocr.review(dict(P, cio_review_attempt=2), mode="live", llm_fn=llm)
    assert r0["job_key"] == "options_thesis_review:g1:opt_g1@v2"
    assert r2["job_key"] == "options_thesis_review:g1:opt_g1@v2:r2"
    assert r0["status"] == "INVALID" and r0["raw_head"] == "not json at all"


def test_router_dedupe_skip_is_classified_not_called_no_json():
    def llm(prompt):
        return {"success": False, "error": "DEDUPE_SKIP: job already answered", "response": "", "provider": "deepseek"}
    r = ocr.review(dict(P), mode="live", llm_fn=llm)
    assert r["status"] == "DEDUPE_SKIPPED" and r["reason"].startswith("DEDUPE_SKIP")
    empty = ocr.review(dict(P), mode="live", llm_fn=lambda _p: {"success": False, "error": "COST_CAP", "response": ""})
    assert empty["status"] == "LLM_ERROR" and "COST_CAP" in empty["reason"]


def test_truncated_and_invalid_keep_the_raw_head_for_diagnosis():
    r = ocr.review(dict(P), mode="live", llm_fn=lambda _p: {"success": True, "response": '{"outcome": "MONITOR_ONLY", "x": {'})
    assert r["status"] == "TRUNCATED" and r["raw_head"].startswith('{"outcome"')


def _store(tmp_path):
    return OptionsThesisStore(path=tmp_path / "options_theses.jsonl")


def _advance(store, review_fn, *, now):
    return otl.advance([dict(P)], store, {"cio_review_mode": "live", "max_review_failures": 3},
                       request_research=lambda p, qs=None: {"research_id": "r", "plan_id": "pl"},
                       research_status=lambda rid: {}, review_fn=review_fn, record_decision=lambda r: None,
                       apply=True, now=now, recent_requests=lambda sym: [])


def test_each_failed_attempt_is_recorded_and_the_next_gets_a_fresh_key(tmp_path):
    store = _store(tmp_path)
    store.append_event("g1", "OPTIONS_THESIS_VERSION", pin="opt_g1@v2", version=1)
    now = datetime(2026, 9, 27, 23, 0, tzinfo=timezone.utc)
    attempts = []

    def failing(p, mode):
        attempts.append(p.get("cio_review_attempt"))
        return {"status": "INVALID", "errors": ["unparseable: no JSON object in response"],
                "raw_head": "Sorry, I cannot", "job_key": f"k:{p.get('cio_review_attempt')}"}

    for _ in range(3):
        rep = _advance(store, failing, now=now)
        assert rep[0]["action"] == "CIO_REVIEW_NOT_ISSUED"
    assert attempts == [0, 1, 2]
    life = store.lifecycle("g1")
    assert life["review_failures"] == 3
    failed = [t for t in life["timeline"] if t["stage"] == "CIO_REVIEW_FAILED"]
    assert len(failed) == 3 and failed[0]["status"] == "INVALID"
    ev = [e for e in store.history("g1") if e.get("event_type") == "OPTIONS_THESIS_CIO_REVIEW_FAILED"]
    assert ev[0]["raw_head"] == "Sorry, I cannot" and ev[2]["attempt"] == 2
    # Fourth pass: the cap stops the spend and names it; the LLM is not called.
    rep = _advance(store, failing, now=now)
    assert rep[0]["action"] == "REVIEW_FAILURE_CAP" and rep[0]["attempts"] == 3 and attempts == [0, 1, 2]


def test_a_success_after_failures_issues_the_decision_and_resets_the_count(tmp_path):
    store = _store(tmp_path)
    store.append_event("g1", "OPTIONS_THESIS_VERSION", pin="opt_g1@v2", version=1)
    now = datetime(2026, 9, 27, 23, 0, tzinfo=timezone.utc)
    _advance(store, lambda p, m: {"status": "INVALID", "errors": ["x"]}, now=now)
    ok = {"status": "OK", "decision_guid": "dec_1", "model": {},
          "review": {"outcome": "MONITOR_ONLY", "confidence": "MEDIUM", "reasoning": "8-K EX-99.1 confirms $95B backlog"}}
    rep = _advance(store, lambda p, m: ok if p.get("cio_review_attempt") == 1 else {"status": "INVALID"}, now=now)
    assert rep[0]["action"] == "DECISION" and rep[0]["outcome"] == "MONITOR_ONLY"
    life = store.lifecycle("g1")
    assert life["stage"] == "DECISION_ISSUED" and life["review_failures"] == 0


def test_dry_run_failures_are_not_counted(tmp_path):
    store = _store(tmp_path)
    store.append_event("g1", "OPTIONS_THESIS_VERSION", pin="opt_g1@v2", version=1)
    now = datetime(2026, 9, 27, 23, 0, tzinfo=timezone.utc)
    otl.advance([dict(P)], store, {"cio_review_mode": "dry"}, request_research=lambda p, qs=None: {},
                research_status=lambda rid: {}, review_fn=lambda p, m: {"status": "DRY_RUN"},
                record_decision=lambda r: None, apply=True, now=now, recent_requests=lambda sym: [])
    assert store.lifecycle("g1")["review_failures"] == 0
