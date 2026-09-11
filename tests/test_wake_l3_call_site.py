#!/usr/bin/env python3
"""Node 6 finally has a caller — and it must refuse before it spends.

Until 2026-09-11 `provenance.llm` was the literal `None` at four sites in
`persistent_agent_wake.py` and nothing in the wake path referenced a model.
`provenance.llm` was null on 51 of 51 wakes, and that was never an outage:
the governed bridge was up on :8766 and both free OAuth lanes answered 200.
Nothing called them.

These tests pin the ORDER, which is the part that is easy to get wrong. L2
before L3: a model asked over an empty context produces fluent text about
nothing, which is worse than the deterministic template it replaces, because
the template does not sound like it knows something.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import persistent_agent_wake as paw  # noqa: E402

SUBJECT = "a2ee84b5-e1bc-5288-8402-7c1fbca65657"
NOW = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)  # 14:00 ET — inside bulk window
FRESH = (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")

ENV_L3_ON = {
    paw.FEATURE_FLAG: "1",
    paw.L3_JUDGMENT_FLAG: "1",
    "PROVENANCE_PRODUCER": "test",
    "TRADEAI_SOURCE_SHA": "aa43a8c9e61e963030fa15009c975f1de88da85a",
}
ENV_L3_OFF = dict(ENV_L3_ON, **{paw.L3_JUDGMENT_FLAG: "0"})

RESEARCH_SELECTION = {
    "source": "unconsumed_research",
    "source_id": "19337eb2-03b1-59dc-b984-56f382fba121",
    "observed_at": FRESH,
}


def _mem(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "mem.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _row(fid: str, as_of: str) -> dict:
    return {"memory_id": fid, "subject_guid": SUBJECT,
            "content": "prior observation about this subject", "as_of": as_of}


def _run(tmp_path, *, env, rows, selection=RESEARCH_SELECTION):
    state = tmp_path / "state"
    state.mkdir()
    return paw.run_scheduled_wake(
        agent_id="cio", subject_guid=SUBJECT, state_root=state,
        memory_backend=_mem(tmp_path, rows), when=NOW, env=env, selection=selection,
    )


def test_flag_off_is_byte_for_byte_the_old_path(tmp_path):
    """Rollback needs no deploy: clearing the env var restores the template."""
    r = _run(tmp_path, env=ENV_L3_OFF, rows=[_row("f1", FRESH)])
    assert r["ok"] is True
    decisions = r["wake"]["provenance"]["policy_decisions"]
    assert not any(d.startswith("l3_") for d in decisions), decisions
    assert r["wake"]["provenance"]["llm"] is None


def test_ungrounded_never_reaches_a_model(tmp_path):
    """The ordering rail. No facts -> no call, no spend, and it is RECORDED.

    An absent judgment must never be mistakable for a judgment that said
    nothing, so the skip is written down rather than left implicit.
    """
    r = _run(tmp_path, env=ENV_L3_ON, rows=[])
    decisions = r["wake"]["provenance"]["policy_decisions"]
    assert "l3_skipped_ungrounded" in decisions, decisions
    assert r["wake"]["provenance"]["llm"] is None
    assert "l3" not in r["wake"]["provenance"], "the pipeline must not have been entered"


def test_grounded_without_a_material_question_does_not_spend(tmp_path):
    """Grounding alone is not a reason to ask a model."""
    r = _run(tmp_path, env=ENV_L3_ON, rows=[_row("f1", FRESH)],
             selection={"source": "material_change", "source_id": "mc-1"})
    decisions = r["wake"]["provenance"]["policy_decisions"]
    assert "l3_skipped_no_material_question" in decisions, decisions
    assert r["wake"]["provenance"]["llm"] is None


def test_grounded_with_a_question_enters_the_pipeline(tmp_path):
    """The positive control: the call site is reached and its verdict recorded.

    No live provider is configured under test, so the pipeline refuses rather
    than spending — which is itself the point. What this pins is that the wake
    now REACHES node 6 and writes down what happened there, instead of the
    literal `None` that stood in for a judgment for 51 consecutive wakes.
    """
    r = _run(tmp_path, env=ENV_L3_ON, rows=[_row("f1", FRESH)])
    assert r["ok"] is True
    prov = r["wake"]["provenance"]
    assert "l3" in prov, "the judgment pipeline was never entered"
    assert prov["l3"]["status"] in {"JUDGED", "REFUSED"}
    decisions = prov["policy_decisions"]
    assert any(d == "l3_judged" or d.startswith("l3_refused:") for d in decisions), decisions
    if prov["l3"]["status"] == "REFUSED":
        assert prov["llm"] is None, "a refusal must not fabricate model provenance"
        # Under test, paid calls are blocked before the network by
        # WAKE_L3_ALLOW_LIVE_PROVIDER. The first wiring of this call site had no
        # such guard and reached the live deepseek_client from inside pytest.
        assert "l3_live_provider_blocked" in decisions, decisions
        assert prov["l3"]["live_provider_allowed"] is False


def test_tests_can_never_reach_a_paid_provider(tmp_path):
    """A suite must not be able to bill the account.

    The judgment flag and the paid-call flag are deliberately separate. With
    WAKE_L3_JUDGMENT on and WAKE_L3_ALLOW_LIVE_PROVIDER unset, the pipeline is
    entered and refuses before any network call — recorded as blocked, never as
    a provider outage, because nothing was wrong with the provider.
    """
    r = _run(tmp_path, env=ENV_L3_ON, rows=[_row("f1", FRESH)])
    prov = r["wake"]["provenance"]
    assert prov["l3"]["live_provider_allowed"] is False
    assert prov["l3"]["blocked_by"] == paw.L3_ALLOW_LIVE_PROVIDER_FLAG
    assert prov["llm"] is None
    assert paw.l3_live_provider_enabled({}) is False, "live calls must default OFF"


def test_a_judgment_never_reaches_behaviour(tmp_path):
    """MBI_BEHAVIOR = 0 is unconditional and survives the new call site."""
    r = _run(tmp_path, env=ENV_L3_ON, rows=[_row("f1", FRESH)])
    blob = json.dumps(r["wake"])
    for forbidden in ("size_usd", "shares", "qty", "order_id",
                      "stop_price", "limit_price", "target_weight"):
        assert forbidden not in blob, f"{forbidden} must never appear in a wake record"
