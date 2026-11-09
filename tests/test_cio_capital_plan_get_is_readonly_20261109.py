"""LQ-20261107-1608 — a GET on /api/v2/cio/capital-plan must not append to the decision journal.

AGENTS.md §28.9 (a GET that writes durable state is forbidden) and §28.11 (no new side-effecting
GET exceptions) are already cited in this module by ``_cio_capital_plan_probe``, which serves the
Home Do-now queue with ``record=False``. The main read route was never given the same treatment:
``_cio_capital_plan()`` called ``_cio_capital_plan_build()`` with its default ``record=True``, so
every page view of the plan — and every v3 call into ``_v2._cio_capital_plan()`` — could append to
``cio_capital_plan_decisions.jsonl``.

The fixture plan is synthetic. The positive control in the last test is what makes "no insert"
mean something: the same fixture, built with ``record=True``, does write a row.

Hermetic: no DB, no providers, no network. The journal is redirected to ``tmp_path`` through the
store's own ``CIO_CAPITAL_PLAN_DECISIONS_JSONL`` override.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import api_v2  # noqa: E402  (the read route under test)
from scripts.lib import cio_capital_plan as plan_lib  # noqa: E402
from scripts.lib import cio_opportunity_queue as queue_lib  # noqa: E402

DECISION_ID = "dec_synthetic_1608_get_readonly"


def _fixture_plan() -> dict:
    """One position decision, so a recorder with the bit set has something to append."""
    return {
        "position_decisions": [{
            "decision_id": DECISION_ID,
            "symbol": "SYNTH",
            "stance_code": "HOLD",
            "cio_stance": "HOLD",
            "why_now": "synthetic fixture — no live book",
        }],
        "capital": {"total_usd": 100000.0},
    }


def _isolate(monkeypatch, journal: Path) -> None:
    monkeypatch.setenv("CIO_CAPITAL_PLAN_DECISIONS_JSONL", str(journal))
    # Sources: every api_v2 helper the builder reads, answered with an empty world.
    monkeypatch.setattr(api_v2, "_load_json", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(api_v2, "_redeploy_opportunity_set", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(api_v2, "_cio_sector_opportunities", lambda *a, **k: {"opportunities": []}, raising=False)
    monkeypatch.setattr(api_v2, "_desk_thesis_head", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(api_v2, "_risk_posture", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(api_v2, "_ratified_investment_policy", lambda *a, **k: None, raising=False)
    # The per-request memo would otherwise serve a plan built under a different monkeypatch.
    monkeypatch.setattr(api_v2, "_request_memoized", lambda key, fn: fn(), raising=False)
    # The two libs the builder imports INSIDE the function: patch the attributes the import binds.
    monkeypatch.setattr(queue_lib, "build_queue_from_executor", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(plan_lib, "build_capital_plan_from_sources", lambda *a, **k: _fixture_plan(), raising=False)


def _rows(journal: Path) -> list[dict]:
    if not journal.exists():
        return []
    return [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]


def test_a_get_makes_no_insert(tmp_path, monkeypatch):
    journal = tmp_path / "cio_capital_plan_decisions.jsonl"
    _isolate(monkeypatch, journal)

    out = api_v2._cio_capital_plan()

    assert out["ok"] is True, out
    assert _rows(journal) == [], f"the GET appended {len(_rows(journal))} row(s) to the journal"
    assert not journal.exists(), "the GET created the journal file"


def test_a_get_with_a_query_makes_no_insert(tmp_path, monkeypatch):
    """The non-memoized branch (``query is not None``) is a separate call site and must match."""
    journal = tmp_path / "cio_capital_plan_decisions.jsonl"
    _isolate(monkeypatch, journal)

    out = api_v2._cio_capital_plan({"as_of": "2026-11-09"})

    assert out["ok"] is True, out
    assert _rows(journal) == [], f"the queried GET appended {len(_rows(journal))} row(s)"


def test_the_positive_control_and_the_explicit_recorder_still_write(tmp_path, monkeypatch):
    """Same fixture, recording requested: one row. Without this, test one proves nothing."""
    journal = tmp_path / "cio_capital_plan_decisions.jsonl"
    _isolate(monkeypatch, journal)

    out = api_v2._cio_capital_plan_build(record=True)

    assert out["ok"] is True, out
    rows = _rows(journal)
    assert len(rows) == 1, rows
    assert rows[0]["decision_id"] == DECISION_ID
    assert rows[0]["symbol"] == "SYNTH"

    # And the scheduled recorder reaches the same store through its own entry point.
    journal.write_text("")
    from scripts.lib.cio_capital_plan_decision_store import record_position_decisions

    written = record_position_decisions(api_v2._cio_capital_plan_build(record=False)["position_decisions"])
    assert written["written"] == 1, written
