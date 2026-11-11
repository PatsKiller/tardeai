"""LQ-20261107-2004 (F1c): the operator's question stays recallable when newer answer versions and sources flood in.

Synthetic fixtures shaped like the production evidence: one ask (shared by two securities), 14 answer versions, a spine
tip of 100 contributions that no longer holds ask.asked, recall limit 4 (config recall.max_items default).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.lib.cross_asset.security_research_spine as sp  # noqa: E402
from scripts.lib import cio_ask_contract as C  # noqa: E402
from scripts.lib.cio_ask_memory import SpineAskMemory, select_recall  # noqa: E402

G1 = "11111111-2222-4333-8444-555555555551"
G2 = "11111111-2222-4333-8444-555555555552"
E1 = C.EntityRef(name="Synth One", symbol="SYNA", security_guid=G1, issuer_guid="11111111-2222-4333-8444-666666666661")
E2 = C.EntityRef(name="Synth Two", symbol="SYNB", security_guid=G2, issuer_guid="11111111-2222-4333-8444-666666666662")
ASK = "ask_synthetic0000001"


class FakeLedger:
    """One ask naming both securities, asked long ago, re-answered 14 times since."""

    def threads(self):
        return {"thr_x": {
            "entities": [{"key": E1.memory_key}, {"key": E2.memory_key}],
            "turns": [{"ask_id": ASK, "asked_at": "2026-10-24T22:10:04Z", "question": "Synthetic question about both?",
                       "answers": [{"version": v, "produced_at": f"2026-11-{v:02d}T01:00:00Z", "summary": f"answer {v}"}
                                   for v in range(1, 15)]}],
        }}


def _flood_spine(path, entity, guid):
    for v in range(10, 15):
        sp.upsert_research_memory(entity.symbol, silo="cio", kind="ask.answer_version", summary=f"[ask.answer_version] answer {v}",
                                  artifact_id=f"{ASK}:v{v}", refs=[f"{ASK}:v{v}"], tags=["ask_the_cio", "ask_answer_version"],
                                  subject_guid=guid, path=path)
    for i in range(110):  # pushes any earlier ask.asked out of the 100-contribution tip
        sp.upsert_research_memory(entity.symbol, silo="cio", kind="ask.source", summary=f"[ask.source] Src {i} (filing)",
                                  artifact_id=f"{ASK}:v14", refs=[f"{ASK}:v14"], tags=["ask_the_cio", "ask_source"],
                                  subject_guid=guid, path=path)


def _kinds(items):
    return [i["kind"] for i in items]


def test_question_is_recalled_for_both_securities_of_a_shared_ask(tmp_path):
    p = tmp_path / "spine.jsonl"
    for e, g in ((E1, G1), (E2, G2)):
        _flood_spine(p, e, g)
    tip = sp.load_latest("SYNA", path=p)
    assert not any(c["kind"] == "ask.asked" for c in tip["contributions"])      # F1c: not in the tip either
    mem = SpineAskMemory(spine_path=p, ledger=FakeLedger())
    for e in (E1, E2):
        got = mem.recall(entity=e, limit=4, exclude_refs=())
        assert "ask.asked" in _kinds(got), _kinds(got)                           # the question is there
        assert len(got) == 4
        assert [i["at"] for i in got] == sorted((i["at"] for i in got), reverse=True)
        assert got[0]["kind"] != "ask.asked"                                    # newest answer still leads


def test_each_security_recalls_only_its_own_memory_even_for_a_shared_ask(tmp_path):
    p = tmp_path / "spine.jsonl"
    _flood_spine(p, E1, G1)                                                      # SYNB has no spine memory at all
    mem = SpineAskMemory(spine_path=p, ledger=FakeLedger())
    a = mem.recall(entity=E1, limit=6)
    b = mem.recall(entity=E2, limit=6)
    assert {i["source"] for i in b} == {"cio_ask_events"}                        # no spine bleed from SYNA into SYNB
    assert "security_research_spine" in {i["source"] for i in a}


def test_select_recall_bounds():
    items = [{"at": f"2026-11-{d:02d}", "kind": "ask.answer_version", "ref": f"a:{d}"} for d in range(1, 10)]
    items.append({"at": "2026-10-01", "kind": "ask.asked", "ref": "a"})
    assert len(select_recall(items, 4)) == 4 and "ask.asked" in _kinds(select_recall(items, 4))
    assert select_recall(items, 0) == []
    assert len(select_recall(items, 1)) == 1                                     # tiny limit: no overshoot
    assert _kinds(select_recall(items[:3], 4)) == ["ask.answer_version"] * 3     # nothing to pin: unchanged
