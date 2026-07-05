#!/usr/bin/env python3
"""URDL Stage-2 LLM review lane tests (spec Part D hard rules).

Fully DB-free and LLM-free: every seam (_fetch_candidate/_write_review/
_audit_review/_count_llm_reviews_today/_local_generate/_cloud_available/
_cloud_review/_schedule_caps) is monkeypatched, so this suite runs under
TRADE_AI_CI as pure unit tests.

    .venv/bin/python -m pytest tests/test_hermes_discovery_llm_review.py -q
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import llm_review  # noqa: E402

CAPS = {"llm_review_daily_cap": 20, "cloud_lane_daily_cap": 5}

GOOD_LLM_OBJ = {
    "relevance_score": 0.8, "source_quality_score": 0.7, "novelty_score": 0.6,
    "risk_score": 0.2, "hallucination_risk": 0.1, "duplicate_risk": 0.1,
    "legal_tax_sensitive": False, "needs_professional_review": False,
    "recommended_action": "approve_research_topic",
    "reasoning_summary": "Well-sourced recurring theme.",
    "evidence_gaps": [], "required_citations": [], "confidence": 0.85,
}


def _candidate(**over) -> dict:
    base = {
        "id": 101, "candidate_type": "TOPIC_CANDIDATE",
        "label": "grid interconnection queue reform",
        "summary": "recurring energy research topic",
        "status": "READY_FOR_REVIEW", "safe_action_level": "OPERATOR_REVIEW_REQUIRED",
        "discovery_score": 0.72, "seen_count": 3, "duplicate_cluster_id": None,
        "source_domain": "utilitydive.com",
        "evidence_json": [{"source_domain": "utilitydive.com", "note": "coverage"}],
        "risk_flags": [],
        "meta_json": {"research_domain": "technology",
                      "advisory_label": "Advisory research only."},
    }
    base.update(over)
    return base


def _policy(**over) -> dict:
    base = {"name": "technology", "risk_level": "general",
            "requires_professional_review_label": False,
            "professional_review_label": None, "requires_citation": False,
            "llm_review_required": False, "promotion_paths": ["research_topic"],
            "advisory_label": "Advisory research only.", "auto_promote": False}
    base.update(over)
    return base


class Harness:
    """Records every seam call; simulates a DB row store for one candidate."""

    def __init__(self, monkeypatch, candidate: dict, policy: dict,
                 llm_raw: str | None = None, cloud_used_today: int = 0,
                 cloud_ok: bool = True,
                 cloud_result: dict | None = None,
                 mutate_status_on_write: str | None = None):
        self.candidate = copy.deepcopy(candidate)
        self.policy = dict(policy)
        self.writes: list[dict] = []
        self.audits: list[dict] = []
        self.local_prompts: list[str] = []
        self.cloud_calls: list[dict] = []
        self.cloud_used_today = cloud_used_today
        self._llm_raw = (json.dumps(GOOD_LLM_OBJ) if llm_raw is None else llm_raw)
        self._cloud_ok = cloud_ok
        self._cloud_result = cloud_result or {
            "ok": True,
            "lanes": {"chatgpt": {"ok": True, "verdict": "AGREE"},
                      "grok": {"ok": True, "verdict": "AGREE"}},
            "consensus": {"verdict": "AGREE", "lanes_ok": 2},
        }
        self._mutate_status = mutate_status_on_write

        monkeypatch.setattr(llm_review, "_schedule_caps", lambda: dict(CAPS))
        monkeypatch.setattr(llm_review, "_fetch_candidate",
                            lambda cid: copy.deepcopy(self.candidate)
                            if cid == self.candidate["id"] else None)
        monkeypatch.setattr(llm_review.domains, "domain_policy",
                            lambda name: dict(self.policy))
        monkeypatch.setattr(llm_review, "_count_llm_reviews_today",
                            lambda cloud_only=False:
                            self.cloud_used_today if cloud_only else 0)
        monkeypatch.setattr(llm_review, "_local_generate", self._local)
        monkeypatch.setattr(llm_review, "_cloud_available", lambda: self._cloud_ok)
        monkeypatch.setattr(llm_review, "_cloud_review", self._cloud)
        monkeypatch.setattr(llm_review, "_write_review", self._write)
        monkeypatch.setattr(llm_review, "_audit_review", self._audit)

    def _local(self, prompt):
        self.local_prompts.append(prompt)
        return self._llm_raw

    def _cloud(self, local_review, candidate, domain):
        self.cloud_calls.append({"local_review": copy.deepcopy(local_review),
                                 "candidate": candidate, "domain": domain})
        return copy.deepcopy(self._cloud_result)

    def _write(self, candidate_id, meta_json, risk_flags):
        self.writes.append({"candidate_id": candidate_id,
                            "meta_json": copy.deepcopy(meta_json),
                            "risk_flags": list(risk_flags)})
        row = copy.deepcopy(self.candidate)
        row["meta_json"] = copy.deepcopy(meta_json)
        row["risk_flags"] = list(risk_flags)
        if self._mutate_status:  # invariant-violation simulation
            row["status"] = self._mutate_status
        return row

    def _audit(self, candidate_id, action, actor, before, after, notes):
        self.audits.append({"candidate_id": candidate_id, "action": action,
                            "actor": actor, "before": before, "after": after,
                            "notes": notes})


# ── schema completeness ──────────────────────────────────────────────────────

def test_review_schema_exactly_matches_spec(monkeypatch):
    h = Harness(monkeypatch, _candidate(), _policy())
    result = llm_review.review_candidate(101)
    assert result["ok"] is True
    rv = result["llm_review_json"]
    assert set(rv) == set(llm_review.REVIEW_SCHEMA_KEYS)  # EXACT key set
    assert rv["review_version"] == llm_review.REVIEW_VERSION
    assert rv["advisory_only"] is True
    assert rv["lanes_used"] == ["local"]
    assert rv["domain"] == "technology"
    assert rv["candidate_type"] == "TOPIC_CANDIDATE"
    assert rv["recommended_action"] in llm_review.RECOMMENDED_ACTIONS
    for k in ("relevance_score", "source_quality_score", "novelty_score",
              "risk_score", "hallucination_risk", "duplicate_risk", "confidence"):
        assert 0.0 <= rv[k] <= 1.0
    assert isinstance(rv["evidence_gaps"], list)
    assert isinstance(rv["required_citations"], list)
    assert rv["reviewed_at"]  # iso timestamp
    # persisted meta carries the review under the single allowed key
    assert h.writes and h.writes[0]["meta_json"]["llm_review_json"] == rv


# ── no-promotion invariant ───────────────────────────────────────────────────

def test_review_never_touches_status_or_promotion(monkeypatch):
    h = Harness(monkeypatch, _candidate(status="NEEDS_VALIDATION",
                                        candidate_type="TICKER_CANDIDATE",
                                        label="AI",
                                        meta_json={"research_domain": "watchlist",
                                                   "ticker_validation":
                                                       {"verdict": "NEEDS_VALIDATION"}}),
                _policy(name="watchlist", risk_level="financial"))
    result = llm_review.review_candidate(101)
    assert result["ok"] is True
    assert result["status"] == "NEEDS_VALIDATION"  # unchanged
    # write seam received only meta_json + risk_flags — no status, no decision
    write = h.writes[0]
    assert set(write) == {"candidate_id", "meta_json", "risk_flags"}
    # meta write only ADDS llm_review_json; everything pre-existing untouched
    assert write["meta_json"]["ticker_validation"] == {"verdict": "NEEDS_VALIDATION"}
    # audit trail row present with action LLM_REVIEW
    assert [a["action"] for a in h.audits] == ["LLM_REVIEW"]
    assert h.audits[0]["before"]["status"] == "NEEDS_VALIDATION"


def test_status_drift_on_write_raises_invariant_error(monkeypatch):
    Harness(monkeypatch, _candidate(), _policy(),
            mutate_status_on_write="APPROVED_RESEARCH_ONLY")
    with pytest.raises(llm_review.LLMReviewError, match="invariant"):
        llm_review.review_candidate(101)


def test_persist_sql_never_sets_status():
    src = (ROOT / "scripts" / "lib" / "hermes_discovery" / "llm_review.py") \
        .read_text(encoding="utf-8")
    updates = re.findall(r"UPDATE\s+hermes_discovery_candidates.*?WHERE",
                         src, re.DOTALL | re.IGNORECASE)
    assert updates, "expected the persist UPDATE statement"
    for stmt in updates:
        low = stmt.lower()
        for forbidden in ("status", "safe_action_level", "decided_at",
                          "decided_by", "decision_notes"):
            assert forbidden not in low, f"persist statement touches {forbidden}"


# ── ticker validation is authoritative ───────────────────────────────────────

def test_review_cannot_flip_unvalidated_ticker(monkeypatch):
    llm_out = dict(GOOD_LLM_OBJ, recommended_action="stage_ticker_review",
                   relevance_score=0.9)
    h = Harness(monkeypatch,
                _candidate(candidate_type="TICKER_CANDIDATE", label="AI",
                           status="NEEDS_VALIDATION",
                           meta_json={"research_domain": "watchlist",
                                      "ticker_validation":
                                          {"verdict": "NEEDS_VALIDATION",
                                           "reason": "denylisted-shaped"}}),
                _policy(name="watchlist", risk_level="financial"),
                llm_raw=json.dumps(llm_out))
    result = llm_review.review_candidate(101)
    rv = result["llm_review_json"]
    assert rv["recommended_action"] == "needs_more_data"  # degraded, not staged
    assert any("symbol" in g.lower() or "validat" in g.lower()
               for g in rv["evidence_gaps"])
    assert result["status"] == "NEEDS_VALIDATION"
    # stored verdict untouched
    assert h.writes[0]["meta_json"]["ticker_validation"]["verdict"] == \
        "NEEDS_VALIDATION"


def test_valid_ticker_may_be_recommended_for_staging(monkeypatch):
    llm_out = dict(GOOD_LLM_OBJ, recommended_action="stage_ticker_review",
                   relevance_score=0.9)
    Harness(monkeypatch,
            _candidate(candidate_type="TICKER_CANDIDATE", label="GOOGL",
                       meta_json={"research_domain": "watchlist",
                                  "ticker_validation": {"verdict": "VALID"}}),
            _policy(name="watchlist", risk_level="financial"),
            llm_raw=json.dumps(llm_out))
    result = llm_review.review_candidate(101)
    assert result["llm_review_json"]["recommended_action"] == "stage_ticker_review"


# ── sensitive domains force professional review + citations ─────────────────

def test_sensitive_domain_forces_flags_and_degrades_without_citations(monkeypatch):
    llm_out = dict(GOOD_LLM_OBJ, recommended_action="approve_research_topic",
                   legal_tax_sensitive=False, needs_professional_review=False,
                   required_citations=[], relevance_score=0.9)
    h = Harness(monkeypatch,
                _candidate(label="roth conversion bracket rules",
                           meta_json={"research_domain": "taxes"}),
                _policy(name="taxes", risk_level="tax",
                        requires_professional_review_label=True,
                        professional_review_label="Research summary only — "
                                                  "consult a qualified professional.",
                        requires_citation=True),
                llm_raw=json.dumps(llm_out), cloud_ok=False)
    rv = llm_review.review_candidate(101)["llm_review_json"]
    assert rv["legal_tax_sensitive"] is True          # forced
    assert rv["needs_professional_review"] is True    # forced
    assert rv["required_citations"] == []
    assert rv["recommended_action"] == "needs_more_data"  # degraded: no citations
    assert any("citation" in g.lower() for g in rv["evidence_gaps"])
    assert h.writes  # still persisted (as advisory review metadata)


def test_sensitive_domain_with_citations_keeps_action(monkeypatch):
    llm_out = dict(GOOD_LLM_OBJ, recommended_action="approve_research_topic",
                   required_citations=["IRS Pub 590-B"], relevance_score=0.9)
    Harness(monkeypatch,
            _candidate(label="rmd rules", meta_json={"research_domain": "retirement"}),
            _policy(name="retirement", risk_level="planning",
                    requires_professional_review_label=True,
                    professional_review_label="x", requires_citation=True),
            llm_raw=json.dumps(llm_out), cloud_ok=False)
    rv = llm_review.review_candidate(101)["llm_review_json"]
    assert rv["recommended_action"] == "approve_research_topic"
    assert rv["needs_professional_review"] is True and rv["legal_tax_sensitive"] is True


def test_sensitive_reject_stands_without_citations(monkeypatch):
    llm_out = dict(GOOD_LLM_OBJ, recommended_action="reject",
                   required_citations=[], relevance_score=0.1)
    Harness(monkeypatch,
            _candidate(label="tax clickbait", meta_json={"research_domain": "taxes"}),
            _policy(name="taxes", risk_level="tax",
                    requires_professional_review_label=True,
                    professional_review_label="x"),
            llm_raw=json.dumps(llm_out), cloud_ok=False)
    rv = llm_review.review_candidate(101)["llm_review_json"]
    assert rv["recommended_action"] == "reject"  # non-promotive, citation-exempt
    assert rv["needs_professional_review"] is True


# ── cloud escalation policy + caps ───────────────────────────────────────────

def test_no_escalation_when_clear_and_not_required(monkeypatch):
    h = Harness(monkeypatch, _candidate(), _policy(llm_review_required=False))
    result = llm_review.review_candidate(101)  # relevance 0.8 — unambiguous
    assert h.cloud_calls == []
    assert result["lanes_used"] == ["local"]
    assert result["escalation"]["escalate"] is False


def test_escalates_when_domain_requires_llm_review(monkeypatch):
    h = Harness(monkeypatch,
                _candidate(label="estate law basics",
                           meta_json={"research_domain": "legal_general"}),
                _policy(name="legal_general", risk_level="legal",
                        requires_professional_review_label=True,
                        professional_review_label="x", llm_review_required=True),
                llm_raw=json.dumps(dict(GOOD_LLM_OBJ, relevance_score=0.9,
                                        required_citations=["USC Title 11"])))
    result = llm_review.review_candidate(101)
    assert len(h.cloud_calls) == 1
    assert result["lanes_used"] == ["local", "chatgpt", "grok"]
    assert result["escalation"]["escalate"] is True


def test_escalates_on_ambiguous_relevance(monkeypatch):
    h = Harness(monkeypatch, _candidate(), _policy(llm_review_required=False),
                llm_raw=json.dumps(dict(GOOD_LLM_OBJ, relevance_score=0.5)))
    result = llm_review.review_candidate(101)
    assert len(h.cloud_calls) == 1
    assert "ambiguous" in result["escalation"]["reason"]


def test_cloud_cap_exhausted_blocks_escalation(monkeypatch):
    h = Harness(monkeypatch,
                _candidate(meta_json={"research_domain": "legal_general"}),
                _policy(name="legal_general", risk_level="legal",
                        requires_professional_review_label=True,
                        professional_review_label="x", llm_review_required=True),
                llm_raw=json.dumps(dict(GOOD_LLM_OBJ,
                                        required_citations=["statute"])),
                cloud_used_today=CAPS["cloud_lane_daily_cap"])  # 5/5 used
    result = llm_review.review_candidate(101)
    assert h.cloud_calls == []
    assert result["lanes_used"] == ["local"]
    assert "cap" in result["escalation"]["reason"]


def test_lanes_local_never_escalates(monkeypatch):
    h = Harness(monkeypatch,
                _candidate(meta_json={"research_domain": "legal_general"}),
                _policy(name="legal_general", risk_level="legal",
                        requires_professional_review_label=True,
                        professional_review_label="x", llm_review_required=True),
                llm_raw=json.dumps(dict(GOOD_LLM_OBJ,
                                        required_citations=["statute"])))
    result = llm_review.review_candidate(101, lanes="local")
    assert h.cloud_calls == []
    assert result["lanes_used"] == ["local"]


def test_cloud_disagree_degrades_action_and_flags(monkeypatch):
    disagree = {"ok": True,
                "lanes": {"chatgpt": {"ok": True, "verdict": "DISAGREE"},
                          "grok": {"ok": True, "verdict": "CAUTION"}},
                "consensus": {"verdict": "DISAGREE", "lanes_ok": 2}}
    h = Harness(monkeypatch, _candidate(), _policy(),
                llm_raw=json.dumps(dict(GOOD_LLM_OBJ, relevance_score=0.5,
                                        recommended_action="approve_research_topic")),
                cloud_result=disagree)
    result = llm_review.review_candidate(101)
    rv = result["llm_review_json"]
    assert rv["recommended_action"] == "needs_more_data"
    assert rv["confidence"] <= 0.35
    assert "cloud_review_disagree" in h.writes[0]["risk_flags"]


def test_cloud_packet_is_redacted(monkeypatch):
    """Exercise the REAL _cloud_review packet builder against a fake
    cloud_review module: holdings/accounts/amounts must never leave."""
    import types
    captured: dict = {}

    def fake_review(task, local_output, context=None, **kw):
        captured.update(task=task, local_output=local_output, context=context,
                        symbol=kw.get("symbol"))
        return {"ok": True, "lanes": {}, "consensus": {"verdict": "UNKNOWN"}}

    monkeypatch.setitem(sys.modules, "cloud_review",
                        types.SimpleNamespace(review=fake_review))
    cand = _candidate(meta_json={
        "research_domain": "technology",
        "subject_json": {"holdings_if_relevant": [{"account": "ROLLOVER-9",
                                                   "market_value": 54321.0}],
                         "accounts_if_relevant": ["ROLLOVER-9"]}})
    llm_review._cloud_review(dict(GOOD_LLM_OBJ), cand, "technology")
    blob = json.dumps([captured["context"], captured["local_output"]],
                      default=str).lower()
    assert "holdings" not in blob and "54321" not in blob \
        and "rollover-9" not in blob and "account" not in blob
    assert captured["context"]["label"] == cand["label"]
    assert captured["symbol"] is None  # not a ticker candidate


# ── daily review cap (batch selection) ───────────────────────────────────────

def test_select_review_batch_caps_by_daily_cap(monkeypatch):
    monkeypatch.setattr(llm_review, "_schedule_caps", lambda: dict(CAPS))
    fetched: list = []

    def fake_exec(sql, params=None, fetch=None):
        if "hermes_discovery_audit" in sql:
            return {"n": 18}  # 18 reviews already today
        fetched.append(params)
        assert "READY_FOR_REVIEW" in str(params) or "READY_FOR_REVIEW" in sql \
            or params[0] == llm_review.REVIEWABLE_STATUSES
        return [dict(_candidate(id=i)) for i in range(params[-1])]

    monkeypatch.setattr(llm_review.inbox, "_exec", fake_exec)
    batch = llm_review.select_review_batch(limit=20)
    assert batch["used_today"] == 18
    assert batch["remaining_today"] == 2       # 20 - 18
    assert len(batch["selected"]) == 2         # limit capped to remaining
    assert fetched[0][-1] == 2                 # SQL LIMIT was the capped value


def test_select_review_batch_zero_when_cap_reached(monkeypatch):
    monkeypatch.setattr(llm_review, "_schedule_caps", lambda: dict(CAPS))

    def fake_exec(sql, params=None, fetch=None):
        if "hermes_discovery_audit" in sql:
            return {"n": 20}
        raise AssertionError("must not query candidates when cap is exhausted")

    monkeypatch.setattr(llm_review.inbox, "_exec", fake_exec)
    batch = llm_review.select_review_batch(limit=20)
    assert batch["remaining_today"] == 0 and batch["selected"] == []


# ── bad-JSON failure path ────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "sorry, I cannot help", "{not json", "[1,2]"])
def test_unparseable_output_is_review_failed_no_meta_write(monkeypatch, bad):
    h = Harness(monkeypatch, _candidate(), _policy(), llm_raw=bad)
    result = llm_review.review_candidate(101)
    assert result["ok"] is False and result["error"] == "review_failed"
    assert result["status"] == "READY_FOR_REVIEW"  # untouched
    assert h.writes == []                          # NO meta write
    assert len(h.audits) == 1
    assert h.audits[0]["action"] == "LLM_REVIEW_FAILED"
    assert "review_failed" in h.audits[0]["notes"]
    assert h.audits[0]["after"] is None


# ── prompt contract ──────────────────────────────────────────────────────────

def test_prompt_instructs_structured_json_and_enum(monkeypatch):
    h = Harness(monkeypatch, _candidate(), _policy())
    llm_review.review_candidate(101)
    prompt = h.local_prompts[0]
    assert "ONLY one JSON object" in prompt
    for action in sorted(llm_review.RECOMMENDED_ACTIONS):
        assert action in prompt, f"action {action} missing from prompt enum"
    for key in ("relevance_score", "recommended_action", "required_citations",
                "confidence", "reasoning_summary", "evidence_gaps"):
        assert key in prompt
    assert "ADVISORY" in prompt.upper()


# ── hygiene ──────────────────────────────────────────────────────────────────

def test_no_broker_imports_in_review_lane():
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?(brokers\b|schwab_adapter|"
        r"schwab_order_adapter|alpaca)", re.MULTILINE)
    for rel in ("scripts/lib/hermes_discovery/llm_review.py",
                "scripts/hermes_discovery_llm_review.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not forbidden.search(text), f"broker import in {rel}"


def test_local_lane_disables_metered_fallbacks():
    """External-LLM policy: never metered keys — local_llm must be called
    with fallback=False (its OpenAI/Anthropic fallbacks are paid lanes)."""
    src = (ROOT / "scripts" / "lib" / "hermes_discovery" / "llm_review.py") \
        .read_text(encoding="utf-8")
    assert "fallback=False" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
