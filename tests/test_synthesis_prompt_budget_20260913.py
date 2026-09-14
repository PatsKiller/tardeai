"""The CIO synthesis prompt stays inside its input cap.

2026-08-29/30: DXCM's CIO synthesis failed 26 times in a row with prompts of
~39k-44.5k tokens against the 16k cap of watchlist_cio_synthesis_cron, and
re-queued a retry after each failure. run_synthesis included EVERY completed
agent result ever stored for the symbol. On 2026-09-13 CRXP held 86 results
(~44.9k narrative tokens) and DIT 46 (~24.8k): both past the cap today.

The operator asked to raise the limit and fix the prompt. These tests pin:
* only the newest results per agent go in (default 2), newest first
* the estimated narrative size stays within a character budget (default 40000)
* the prompt says how many older results were left out
* both are environment-tunable
* the cron synthesis cap is 32000 tokens

Pure: no database, no model.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import process_watchlist_agent_jobs as W  # noqa: E402

COVERS = ["scripts/process_watchlist_agent_jobs.py", "config/llm_process_registry.json"]


def _rows(n_per_agent: int, agents=("maria", "steph", "risk_agent", "tax_agent", "full_chain"), size=3000):
    base = datetime(2026, 9, 13, 12, 0)
    out = []
    for i in range(n_per_agent):
        for j, a in enumerate(agents):
            out.append({"agent": a, "full_narrative": f"{a} view {i} " + "x" * size,
                        "created_at": base - timedelta(hours=i, minutes=j)})
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out


def test_newest_rows_per_agent_are_kept_and_the_rest_counted():
    rows = _rows(18)  # 90 results, like CRXP's 86
    kept, omitted = W._select_synthesis_rows(rows, per_agent=2, char_budget=1_000_000)
    assert len(kept) == 10 and omitted == 80
    for a in ("maria", "steph", "risk_agent", "tax_agent", "full_chain"):
        mine = [r for r in kept if r["agent"] == a]
        assert [r["full_narrative"].split()[2] for r in mine] == ["0", "1"], "the two newest per agent"


def test_the_character_budget_bounds_the_narratives_section():
    rows = _rows(18, size=3000)
    kept, omitted = W._select_synthesis_rows(rows, per_agent=2, char_budget=12000)
    used = sum(len(r["full_narrative"]) + 600 for r in kept)
    assert used <= 12000 and len(kept) == 3 and omitted == len(rows) - 3


def test_defaults_come_from_the_environment(monkeypatch):
    rows = _rows(5)
    monkeypatch.delenv("SYNTHESIS_RESULTS_PER_AGENT", raising=False)
    monkeypatch.delenv("SYNTHESIS_NARRATIVE_CHAR_BUDGET", raising=False)
    kept, _ = W._select_synthesis_rows(rows)
    assert len(kept) == 10
    monkeypatch.setenv("SYNTHESIS_RESULTS_PER_AGENT", "1")
    kept1, _ = W._select_synthesis_rows(rows)
    assert len(kept1) == 5


def test_one_oversized_row_is_still_kept_rather_than_an_empty_prompt():
    rows = [{"agent": "maria", "full_narrative": "y" * 90000, "created_at": datetime(2026, 9, 13)}]
    kept, omitted = W._select_synthesis_rows(rows, per_agent=2, char_budget=40000)
    assert len(kept) == 1 and omitted == 0


def test_crxp_scale_history_now_fits_the_cap():
    rows = _rows(18, size=3000)
    kept, _ = W._select_synthesis_rows(rows)
    narrative_tokens = sum(len(r["full_narrative"]) + 600 for r in kept) // 4
    cap = next(p for p in json.loads((ROOT / "config" / "llm_process_registry.json").read_text())["processes"]
               if p["id"] == "watchlist_cio_synthesis_cron")["max_input_tokens"]
    assert cap == 32000
    assert narrative_tokens <= 10000 < cap


def test_run_synthesis_builds_narratives_from_the_selection():
    src = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text()
    body = src[src.index("def run_synthesis("):src.index("def run_synthesis(") + 6000]
    assert "narr_rows, narr_omitted = _select_synthesis_rows(results)" in body
    assert "for r in narr_rows:" in body and "older analyst result(s) omitted" in body
