"""record_send persists the morning-brief send outcome next to the claim (2026-10-07)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.lib.brief_semantic_dedupe import claim, record_send
from scripts.lib.n8n_pilot_observations import morning_brief


def test_record_send_writes_sent_flag_and_observation_sees_it(tmp_path):
    now = datetime(2026, 10, 7, 11, 30, tzinfo=timezone.utc)
    res = claim(kind="MORNING", session="2026-10-07", material_generation="gen-1", root=tmp_path)
    assert res["published"] is True
    assert record_send(kind="MORNING", key=None, sent=True, root=tmp_path)["recorded"] is False
    assert record_send(kind="MORNING", key="nope", sent=True, root=tmp_path)["reason"] == "unclaimed_key"
    out = record_send(kind="MORNING", key=res["key"], sent=True, root=tmp_path, now=now)
    assert out["recorded"] is True
    doc = json.loads((tmp_path / "data" / "cio" / "morning_brief_semantic_state.json").read_text())
    rec = doc["published"][res["key"]]
    assert rec["sent"] is True and rec["sent_at"] == now.isoformat()
    obs = morning_brief(tmp_path, session_date="2026-10-07")
    assert obs["send_receipt"] == "OBSERVED" and obs["sent"] is True
    assert obs["send"] is False  # the observation never asks to send
