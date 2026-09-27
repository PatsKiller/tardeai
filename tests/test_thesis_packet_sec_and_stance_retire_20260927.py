"""DELL v5 (2026-09-27): SEC facts reached the catalog but not the prompt, and gap retirement
never fired because the model rewords the gap each version."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib.symbol_thesis_synthesis import build_synthesis_packet, _build_flash_synthesis_prompt  # noqa: E402


def _item(i, source_type, quality, fact):
    return {"evidence_id": f"ev_{source_type}_{i}", "source_type": source_type, "quality": quality,
            "fact": fact, "polarity": "NEUTRAL"}


def test_sec_facts_survive_the_structured_cap_even_when_news_is_listed_first():
    news = [_item(i, "news", "APPROVED_NEWS", f"headline {i}") for i in range(10)]
    sec = [_item(i, "sec_xbrl", "PRIMARY_REGULATORY", f"DELL metric {i} from 10-Q") for i in range(13)]
    catalog = {"supporting": [], "contradictory": [], "structured": news + sec,
               "sufficiency": {"sufficient_for_synthesis": True}}
    packet = build_synthesis_packet("DELL", question="q", evidence_catalog=catalog)
    got = packet["evidence"]["structured"]
    assert [r["source_type"] for r in got[:13]] == ["sec_xbrl"] * 13
    assert sum(r["source_type"] == "news" for r in got) == 8
    prompt = _build_flash_synthesis_prompt("DELL", packet)
    assert "DELL metric 12 from 10-Q" in prompt


def _write(led, rows):
    led.parent.mkdir(parents=True, exist_ok=True)
    led.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_reworded_gaps_still_retire_after_consecutive_stanceless_publishes(tmp_path):
    import run_symbol_thesis_acquisition as rsa
    fields = {"research_gaps": ["What is Dell's exact AI server backlog dollar figure?"], "thesis_stance": ""}
    kw = dict(root=tmp_path, memberships=["WATCHLIST"], role="UNKNOWN", thesis_state="THIN")
    led = tmp_path / rsa.LEDGER_REL
    rows = [{"symbol": "DELL", "status": "PUBLISHED", "question_digest": f"reworded{i}"}
            for i in range(rsa.STANCELESS_RUN_LIMIT - 1)]
    _write(led, rows)
    assert rsa.choose_question("DELL", fields, **kw)[1] == "first_open_gap"
    rows.append({"symbol": "DELL", "status": "PUBLISHED", "question_digest": "reworded_last", "stance_after": ""})
    _write(led, rows)
    q, why = rsa.choose_question("DELL", fields, **kw)
    assert why == "gaps_exhausted_form_stance" and "Form a thesis stance for DELL" in q


def test_a_published_stance_resets_the_count(tmp_path):
    import run_symbol_thesis_acquisition as rsa
    fields = {"research_gaps": ["Gap?"], "thesis_stance": ""}
    kw = dict(root=tmp_path, memberships=["WATCHLIST"], role="UNKNOWN", thesis_state="THIN")
    rows = [{"symbol": "DELL", "status": "PUBLISHED", "question_digest": f"x{i}"} for i in range(5)]
    rows.append({"symbol": "DELL", "status": "PUBLISHED", "question_digest": "y", "stance_after": "watch"})
    rows.append({"symbol": "HOOD", "status": "PUBLISHED", "question_digest": "z"})
    rows.append({"symbol": "DELL", "status": "BLOCKED", "question_digest": "w"})
    _write(tmp_path / rsa.LEDGER_REL, rows)
    assert rsa._stanceless_runs(tmp_path, "DELL") == 0
    assert rsa.choose_question("DELL", fields, **kw)[1] == "first_open_gap"
