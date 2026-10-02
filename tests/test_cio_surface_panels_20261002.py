"""CIO surface closure (spec step 13): record-ledger reads and the new panels.

Backend: /api/v3/cio/records returns each ledger's newest rows filtered by the
contract's own schema, with PRESENT / EMPTY / MISSING states and the rows' own
clock.  Frontend (static): the new panels render schema/state/clock labels from
the payload through CioProjectionBlock, never poll faster than 300 s, load
lazily, and use router-relative links only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps/command-center-v3/src"
NEW_PANELS = [
    "components/cio/CioBrainProjectionsPanel.tsx",
    "components/cio/CioOfficeHomeProjections.tsx",
    "components/cio/CioProductHealthPanel.tsx",
    "components/cio/CioRecordLedgersPanel.tsx",
    "components/cio/CioThesisDelegationPanel.tsx",
    "components/cio/CioThesisResearchContextPanel.tsx",
]


def _rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_record_ledgers_filter_by_contract_and_label_missing_stores(tmp_path, monkeypatch):
    from scripts.lib import cio_record_ledgers as rl

    _rows(tmp_path / "outcome_checkpoints.jsonl", [
        {"schema": "OutcomeCheckpoint@v1", "checkpoint_id": "ck1", "as_of": "2026-10-01T00:00:00Z"},
        {"schema": "SomethingElse@v1", "checkpoint_id": "x"},
        {"schema": "OutcomeCheckpoint@v1", "checkpoint_id": "ck2", "as_of": "2026-10-02T00:00:00Z"},
    ])
    (tmp_path / "thesis_change_cards.jsonl").write_text("not json\n", encoding="utf-8")
    _rows(tmp_path / "cio_instrument_records.jsonl", [{
        "schema": "InstrumentRecord@v1", "subject_key": "AAA", "updated_ts": "2026-10-02T01:00:00Z",
        "beliefs": [{"schema": "InstrumentBelief@v1", "belief_key": "b", "recommendation": "HOLD", "as_of": "2026-10-02T01:00:00Z"},
                    {"schema": "Other@v1", "belief_key": "c"}],
    }])
    ck = rl.recent_outcome_checkpoints(tmp_path)
    assert ck["state"] == "PRESENT"
    assert [r["checkpoint_id"] for r in ck["rows"]] == ["ck2", "ck1"]  # newest first, foreign schema dropped
    assert ck["source_as_of"] == "2026-10-02T00:00:00Z"
    assert rl.recent_thesis_change_cards(tmp_path)["state"] == "EMPTY"
    missing = rl.recent_outcome_observations(tmp_path)
    assert missing["state"] == "MISSING" and missing["rows"] == [] and missing["present"] is False
    beliefs = rl.recent_instrument_beliefs(tmp_path)
    assert [b["belief_key"] for b in beliefs["rows"]] == ["b"] and beliefs["rows"][0]["subject_key"] == "AAA"
    assert rl.latest_held_thesis_coverage(tmp_path)["state"] == "MISSING"
    assert rl.operator_product_envelope(tmp_path)["envelope"] is None


def test_record_ledger_tail_window_is_bounded(tmp_path):
    from scripts.lib import cio_record_ledgers as rl

    big = [{"schema": "OutcomeObservation@v1", "i": i, "pad": "x" * 200} for i in range(4000)]
    _rows(tmp_path / "outcome_observations.jsonl", big)
    block = rl.recent_outcome_observations(tmp_path, limit=5)
    assert block["complete"] is False and block["window_bytes"] == rl.TAIL_BYTES
    assert [r["i"] for r in block["rows"]] == [3999, 3998, 3997, 3996, 3995]


def test_records_route_is_dispatched_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS", "off")
    sys.path.insert(0, str(ROOT / "scripts"))
    import api_v3_cio

    out = api_v3_cio.get_cio_record_ledgers()
    assert out["ok"] is True and out["authority"] == "READ_ONLY_ADVISORY"
    assert out["financial_action"] is False and out["mutation"] is False
    for key in ("outcome_checkpoints", "thesis_revisions", "instrument_records", "goal_predicates", "operator_product"):
        assert out[key]["state"] == "MISSING", key
    assert list(tmp_path.iterdir()) == []  # nothing written
    dispatch = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    assert 'if p in ("records", "record-ledgers", "record_ledgers"):' in dispatch


def test_new_panels_render_payload_labels_and_never_poll_fast():
    for rel in NEW_PANELS:
        text = (SRC / rel).read_text(encoding="utf-8")
        assert "CioProjectionBlock" in text, rel
        for m in re.finditer(r"useApi<[^>]*>\(([^,]+),\s*([^,)]+)", text):
            interval = m.group(2).strip()
            assert interval in ("SLOW_POLL_MS", "0"), f"{rel}: poll {interval}"
        if "SLOW_POLL_MS" in text:
            assert "const SLOW_POLL_MS = 300_000" in text, rel
        # lazy: every fetch is gated on the section being open / an explicit load
        for m in re.finditer(r"useApi<[^>]*>\([^\n]*", text):
            assert "enabled" in m.group(0) or "on)" in m.group(0) or "symOn)" in m.group(0), f"{rel}: {m.group(0)}"
        # router-relative links only
        assert not re.search(r"""(?:to|href)=\{?\s*[`'"]/v3/""", text), rel
    block = (SRC / "components/cio/CioProjectionBlock.tsx").read_text(encoding="utf-8")
    assert "projectionLabels(block)" in block and "labels.states.map" in block and "labels.clocks" in block
    assert "state NOT_IN_PAYLOAD" in block and "clock NOT_IN_PAYLOAD" in block
    lib = (SRC / "lib/cioProjection.ts").read_text(encoding="utf-8")
    assert "NOT_IN_PAYLOAD" in lib and "loadLine" in lib


def test_panels_are_mounted_in_existing_cio_tabs():
    hub = (SRC / "pages/CioHub.tsx").read_text(encoding="utf-8")
    assert "<CioOfficeHomeProjections home={home} />" in hub
    assert "<CioProductHealthPanel data={data} />" in hub
    assert "<CioThesisDelegationPanel />" in hub
    assert "<CioThesisResearchContextPanel symbol={sym} />" in hub
    assert "<CioRecordLedgersPanel />" in hub
    brain = (SRC / "components/cio/CioBrainPanel.tsx").read_text(encoding="utf-8")
    assert "<BrainPayloadProjections brain={brain} />" in brain and "<CioBrainProjectionsPanel />" in brain
    maturity = (SRC / "pages/MaturityPanels.tsx").read_text(encoding="utf-8")
    assert "data?.disposition_outcomes" in maturity
