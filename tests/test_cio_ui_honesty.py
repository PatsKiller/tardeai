"""UI honesty: no [:400] stub, no DATA_UNAVAILABLE as thesis body, cache follows jsonl."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.symbol_thesis_coverage import classify_symbol
from scripts.lib.thesis_substantiveness import pass_fixture


class _Store:
    def __init__(self, recs=None):
        self._recs = recs or {}

    def get_current(self, tid):
        return self._recs.get(tid)


def test_thesis_summary_is_not_truncated_to_400():
    body = pass_fixture("NOC") + " " + ("backlog durability. " * 80)
    assert len(body) > 400
    rec = {
        "status": "active",
        "published_ts": "2026-08-22T22:47:21+00:00",
        "updated_ts": "2026-08-22T22:47:21+00:00",
        "summary": body,
        "stance": "hold",
        "thesis_version": "symbol_noc@v3",
    }
    store = _Store({"symbol_noc": rec, "desk": {"thesis_version": "desk@v5"}})
    uni = {"memberships": ["HELD"], "held": True}
    out = classify_symbol("NOC", universe_rec=uni, store=store)
    assert out["thesis_summary"] is not None
    assert len(out["thesis_summary"]) > 400
    assert out["thesis_summary"] == body.strip()


def test_operator_text_strips_data_unavailable_token():
    from scripts.lib.symbol_thesis_attach import _operator_text

    assert _operator_text("DATA_UNAVAILABLE") is None
    assert _operator_text("DATA_UNAVAILABLE — no living symbol thesis") is None
    assert _operator_text("Hold the defense compounder") == "Hold the defense compounder"
    assert _operator_text(None) is None


def test_core_thesis_fallback_is_not_the_machine_token():
    src = (ROOT / "scripts/lib/symbol_thesis_cc.py").read_text(encoding="utf-8")
    assert 'DATA_UNAVAILABLE — no living symbol thesis' not in src
    assert '"core_thesis": fields.get("thesis_summary") or "No living thesis"' in src
    assert '[:400]' not in src
    assert '[:300]' not in src


def test_universe_metrics_exposes_substantive_and_thin():
    src = (ROOT / "scripts/lib/symbol_thesis_attach.py").read_text(encoding="utf-8")
    assert "held_substantive_pct" in src
    assert "substantive_pct_material" in src
    assert "_store_token" in src
    cc = (ROOT / "scripts/lib/symbol_thesis_cc.py").read_text(encoding="utf-8")
    assert '"substantive_pct": metrics.get("substantive_pct_material")' in cc
    assert '"held_current": metrics.get("held_current")' in cc


def test_ciohub_renders_substantive_and_thin_not_coverage_only():
    src = (ROOT / "apps/command-center-v3/src/pages/CioHub.tsx").read_text(encoding="utf-8")
    assert "Held substantive" in src
    assert "thesis_state === 'THIN'" in src
    assert "cio-daily-thesis-changes" in src
    assert "dec_${id.slice" not in src
