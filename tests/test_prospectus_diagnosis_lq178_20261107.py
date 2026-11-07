"""ANCHOR: PROSPECTUS_DIAGNOSIS_LQ178_20261107. LQ-20261107-178 — the prospectus page said
"the credit check was refused" with no reason, and a writer reply cut off at the token cap was
reported as a format error.

Live evidence (2026-11-07, read-only):

* `GET /api/v2/prospectus/index` → `budget {credit_remaining_usd: null, status: UNAVAILABLE,
  error: "CreditDenied"}` — the class name only. Reproducing the same call against the live
  policy raised `CreditDenied("CREDIT_UNAVAILABLE")` because
  `data/runtime/provider_cost/anthropic_credit.jsonl` has a truncated final record (21 bytes):
  the Anthropic lane is fail-closed until the fragment is archived (operator step).
* queue.json: PFLT, AVGO, AXTI `state failed`, `attempts 2-3`, `last_error
  "GenerationFailed: OUTPUT_NOT_JSON"` (two of them `batch:`); the batch entry stores the
  writer's `finish_reason` but `finish_doc` only special-cased `refusal`, so a reply ended by
  the token cap was parsed, failed as OUTPUT_NOT_JSON, retried identically, and closed.

Hermetic: no network, no DB; the credit book's snapshot is stubbed to raise.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.anthropic_credit import CreditDenied  # noqa: E402
from scripts.lib.prospectus import generate  # noqa: E402
from scripts.lib.prospectus.generate import GenerationFailed, finish_doc  # noqa: E402
from scripts.lib import prospectus_api  # noqa: E402

ANCHOR = "PROSPECTUS_DIAGNOSIS_LQ178_20261107"
NOW = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)


def _finish(prov, text=""):
    return finish_doc(None, text, prov, gate={}, settings={}, web={}, mode="full", previous=None,
                      now=NOW, version="20261107T180000Z", process_id="prospectus_writer")


# ── the writer's stop reason names the cause ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reason", ["max_tokens", "length"])
def test_a_reply_cut_off_by_the_token_cap_is_named_as_truncation(reason):
    with pytest.raises(GenerationFailed) as exc:
        _finish({"finish_reason": reason}, '{"sections": [')
    assert str(exc.value) == "OUTPUT_TRUNCATED"


def test_a_refusal_is_still_a_refusal():
    with pytest.raises(GenerationFailed) as exc:
        _finish({"finish_reason": "refusal"})
    assert str(exc.value) == "REFUSAL"


def test_a_complete_reply_that_is_not_json_is_still_a_format_error():
    with pytest.raises(GenerationFailed) as exc:
        _finish({"finish_reason": "end_turn"}, "I'm sorry, I can't help with that.")
    assert str(exc.value) == "OUTPUT_NOT_JSON"


def test_a_clean_end_of_turn_is_not_mislabelled():
    # sanity: the new branch must not swallow ordinary replies
    with pytest.raises(GenerationFailed) as exc:
        _finish({"finish_reason": "end_turn"}, "")
    assert str(exc.value) == "OUTPUT_NOT_JSON"


# ── the budget panel carries CreditDenied's own reason ───────────────────────────────────────────────────────

class _Book:
    def __init__(self, *a, **k):
        pass

    def snapshot(self, **_k):
        raise CreditDenied("CREDIT_UNAVAILABLE")


def test_the_budget_payload_names_the_credit_denial_reason(monkeypatch):
    monkeypatch.setattr("scripts.lib.anthropic_credit.CreditBook", _Book)
    monkeypatch.setattr("scripts.lib.anthropic_transport.load_policy", lambda *a, **k: {})
    out = prospectus_api.budget(ROOT)
    assert out["status"] == "UNAVAILABLE" and out["error"] == "CreditDenied"
    assert out["reason"] == "CREDIT_UNAVAILABLE"


def test_the_budget_payload_stays_small_and_bounded(monkeypatch):
    monkeypatch.setattr("scripts.lib.anthropic_credit.CreditBook", _Book)
    monkeypatch.setattr("scripts.lib.anthropic_transport.load_policy", lambda *a, **k: {})
    out = prospectus_api.budget(ROOT)
    assert set(out) == {"credit_remaining_usd", "today_used_usd", "daily_cap_usd", "status", "error", "reason"}
    assert len(out["reason"]) <= 64


def test_a_non_credit_exception_carries_no_invented_reason(monkeypatch):
    class Boom(Exception):
        pass

    class _BadBook:
        def __init__(self, *a, **k):
            pass

        def snapshot(self, **_k):
            raise Boom("connection reset")

    monkeypatch.setattr("scripts.lib.anthropic_credit.CreditBook", _BadBook)
    monkeypatch.setattr("scripts.lib.anthropic_transport.load_policy", lambda *a, **k: {})
    out = prospectus_api.budget(ROOT)
    assert out["error"] == "Boom" and "reason" not in out


# ── the page copy exists for both new states ─────────────────────────────────────────────────────────────────

def test_the_frontend_model_names_the_new_states():
    src = (ROOT / "apps" / "command-center-v3" / "src" / "lib" / "prospectusModel.ts").read_text()
    assert "CREDIT_UNAVAILABLE" in src and "usage journal could not be read" in src
    assert "OUTPUT_TRUNCATED" in src and "ran out of room" in src
