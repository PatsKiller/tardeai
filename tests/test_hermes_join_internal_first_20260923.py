"""Stage 1+3 parity: Hermes join honesty + internal-first LEGEND/Sources.

Plan §6.1 (2026-09-23): fail closed when
- shared helper returns perspective text without LEGEND/Sources when stores were read
- join sees completed res_* but claim says 0 findings / queued-not-analyzed
- never treat Hub backlog total==500 as queue depth

Offline fixtures only. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import hermes_subject_join as hj  # noqa: E402
from scripts.lib import operator_internal_first as oif  # noqa: E402
from scripts.lib import reply_provenance as rp  # noqa: E402

COVERS = [
    "scripts/lib/hermes_subject_join.py",
    "scripts/lib/operator_internal_first.py",
]


THIN_RESULT = {
    "event": "HERMES_RESEARCH_COMPLETED",
    "result_id": "rr_abb8acb2f962",
    "research_id": "res_c3a661c21740",
    "plan_id": "plan_e2cdd9c8c1a8",
    "status": "completed",
    "symbol": "S",
    "model": "deepseek-flash",
    "completed_ts": "2026-09-23T11:46:01+00:00",
    "thesis_stance": "INSUFFICIENT_DATA",
    "summary": "INSUFFICIENT_DATA — thin packet",
    "answers": [{"question_id": "q1", "summary": "INSUFFICIENT_DATA on thesis.", "status": "answered"}],
    "findings": [{"id": "f1", "text": "INSUFFICIENT_DATA: off-symbol RAG only."}],
}


def _cio_fixture(tmp_path: Path, *, result: dict | None = None, gap: dict | None = None) -> Path:
    d = tmp_path / "cio"
    d.mkdir()
    if result is not None:
        (d / "hermes_research_results.jsonl").write_text(
            json.dumps(result) + "\n", encoding="utf-8"
        )
    if gap is not None:
        (d / "cio_operator_gap_requests.jsonl").write_text(
            json.dumps(gap) + "\n", encoding="utf-8"
        )
    (d / "cio_operator_pending_replies.jsonl").write_text("", encoding="utf-8")
    return d


def test_join_completed_thin_is_analyzed_thin_not_hub_zero(tmp_path, monkeypatch):
    cio = _cio_fixture(tmp_path, result=THIN_RESULT, gap={
        "pending_id": "opr_ab7192d3b009",
        "research_id": "res_c3a661c21740",
        "symbols": ["S"],
        "kind": "hermes_operator_forced",
    })

    class _FakeHR:
        @staticmethod
        def _load_projection():
            return {"by_research_id": {
                "res_c3a661c21740": {
                    "research_id": "res_c3a661c21740",
                    "symbol": "S",
                    "status": "completed",
                    "latest_result_id": "rr_abb8acb2f962",
                }
            }}

    monkeypatch.setitem(sys.modules, "scripts.lib.cio_hermes_research", _FakeHR)
    monkeypatch.setitem(sys.modules, "lib.cio_hermes_research", _FakeHR)

    join = hj.join_subject_hermes("S", cio_dir=cio, hub_finder=lambda _s: 0)
    assert join.status == hj.STATUS_ANALYZED_THIN
    assert "res_c3a661c21740" in join.research_ids
    assert "opr_ab7192d3b009" in join.pending_ids
    assert "INSUFFICIENT_DATA" in join.honesty_line
    assert "Hub promoted 0" in join.honesty_line or "not the same as Hub" in join.honesty_line
    # Hub 0 must NOT overwrite desk completion status
    assert join.status != hj.STATUS_HUB_PROMOTED_0


def test_claim_zero_findings_beside_desk_completion_is_a_lie(tmp_path, monkeypatch):
    cio = _cio_fixture(tmp_path, result=THIN_RESULT)

    class _FakeHR:
        @staticmethod
        def _load_projection():
            return {"by_research_id": {}}

    monkeypatch.setitem(sys.modules, "scripts.lib.cio_hermes_research", _FakeHR)
    monkeypatch.setitem(sys.modules, "lib.cio_hermes_research", _FakeHR)

    join = hj.join_subject_hermes("S", cio_dir=cio)
    assert join.has_desk_completion
    assert hj.claim_contradicts_join("Hermes: 0 recent findings for S", join)
    assert hj.claim_contradicts_join("queued not analyzed", join)
    assert hj.claim_contradicts_join("backlog of 500 deep", join)
    assert not hj.claim_contradicts_join("analyzed-thin / INSUFFICIENT_DATA on res_c3a661c21740", join)


def test_hub_only_zero_is_hub_promoted_0_vocabulary(tmp_path, monkeypatch):
    cio = _cio_fixture(tmp_path)

    class _FakeHR:
        @staticmethod
        def _load_projection():
            return {"by_research_id": {}}

    monkeypatch.setitem(sys.modules, "scripts.lib.cio_hermes_research", _FakeHR)
    monkeypatch.setitem(sys.modules, "lib.cio_hermes_research", _FakeHR)

    join = hj.join_subject_hermes("S", cio_dir=cio, hub_finder=lambda _s: 0)
    assert join.status == hj.STATUS_HUB_PROMOTED_0
    # Honesty may mention "500" only to refuse the backlog misread — never as depth.
    assert "backlog claim" in join.honesty_line or "promoted" in join.honesty_line.lower()
    assert "queue depth" not in join.honesty_line.lower()
    assert join.hub_count == 0
    assert not join.has_desk_completion


def test_internal_first_without_legend_or_sources_fails_closed(monkeypatch):
    """A Maria-bridge / shared helper must not return perspective without chrome."""
    # Bypass desk (live I/O); join-only body still finalizes.
    monkeypatch.setattr(oif, "join_subject_hermes", lambda *a, **k: hj.HermesJoinResult(
        symbol="S",
        status=hj.STATUS_ANALYZED_THIN,
        research_ids=["res_c3a661c21740"],
        result_ids=["rr_abb8acb2f962"],
        honesty_line=hj.honesty_line_for(
            hj.STATUS_ANALYZED_THIN, symbol="S", result_id="rr_abb8acb2f962",
            research_ids=["res_c3a661c21740"],
        ),
        sources=["hermes_research_results · rr_abb8acb2f962"],
        latest_result=THIN_RESULT,
    ))
    monkeypatch.setattr(oif, "_resolve_primary", lambda _t: {
        "symbol": "S", "kind": "company", "guid": "84601d7d-ae35-5dc7-b664-1b77ad8ea57e",
    })

    result = oif.answer_internal_first(
        "perspective on SentinelOne",
        surface="maria",
        use_desk=False,
    )
    assert result.text.startswith("Key:") or rp.LEGEND.split(" · ", 1)[0] in result.text
    assert "Sources:" in result.text
    assert "Origin:" in result.text
    assert "READ_ONLY_ADVISORY" in result.text
    assert "INSUFFICIENT_DATA" in result.text or "analyzed-thin" in result.text
    assert result.provenance and result.provenance.get("sources_line_present") is True


def test_internal_first_rejects_zero_findings_lie_when_desk_text_claims_empty(monkeypatch):
    monkeypatch.setattr(oif, "join_subject_hermes", lambda *a, **k: hj.HermesJoinResult(
        symbol="S",
        status=hj.STATUS_ANALYZED_THIN,
        research_ids=["res_c3a661c21740"],
        result_ids=["rr_x"],
        honesty_line="Hermes desk research on S completed as analyzed-thin / INSUFFICIENT_DATA (rr_x).",
        sources=["hermes_research_results · rr_x"],
        latest_result=THIN_RESULT,
    ))
    monkeypatch.setattr(oif, "_resolve_primary", lambda _t: {
        "symbol": "S", "kind": "ticker", "guid": "84601d7d-ae35-5dc7-b664-1b77ad8ea57e",
    })

    def _fake_desk(text, **kwargs):
        return {
            "kind": "answered",
            "text": "Hermes has 0 recent findings for S. Queued not analyzed.",
            "sources": ["fake_hub"],
            "intent": {"symbols": ["S"], "text": text},
            "model": None,
        }

    import scripts.lib.cio_operator_desk_loop as desk  # noqa: PLC0415
    monkeypatch.setattr(desk, "handle_operator_desk_question", _fake_desk)

    result = oif.answer_internal_first("perspective on S", surface="maria", use_desk=True)
    assert "0 recent findings" not in result.text
    assert "Sources:" in result.text
    assert "Key:" in result.text or "green" in result.text


def test_maria_api_surface_exports_are_stable():
    """Maria skill imports these names — do not rename without a consumer update."""
    for name in (
        "answer_internal_first",
        "join_subject_hermes",
        "finalize_operator_reply",
        "ReplyProvenance",
        "LEGEND",
        "InternalFirstResult",
        "HermesJoinResult",
        "claim_contradicts_join",
    ):
        assert hasattr(oif, name), name


def test_sentinel_one_spaced_and_lowercase_bind_guid():
    from scripts.lib.company_name_index import resolve_name
    from scripts.lib.inbound_identity_tagger import tag_inbound

    assert resolve_name("Sentinel One")["symbol"] == "S"
    assert resolve_name("Sentinel One")["matched_on"] == "compacted"
    tag = tag_inbound("give me perspective on sentinel one")
    assert any(r["symbol"] == "S" and r["subject_guid"] for r in tag["resolved"])
    # Must not also bind Perspective Therapeutics (CATX) from the word "perspective"
    assert not any(r["symbol"] == "CATX" for r in tag["resolved"])
