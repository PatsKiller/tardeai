"""Stage 2 — ban pseudo Iris/Alex/CIO attribution (desk ∧ Maria fixtures).

Fail closed when:
  - Maria A2A-deny: "Iris found…" / "Alex CIO take…" / "Iris / Alex" stripped
  - Desk synthesis without specialist/synthesis row: fake attribution stripped
  - Real evidence present: labels may remain
  - Desk product voice ("Alex · …") preserved
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.lib import maria_parity_hook as mph
from scripts.lib import specialist_attribution as sa

ROOT = Path(__file__).resolve().parents[1]

# Morning Maria failure shape (audit 2026-09-23) — roleplay after A2A deny.
MARIA_A2A_DENY_FIXTURE = """Here's my take on SentinelOne (S).

Iris found elevated cyber spending and a clean balance sheet.
Alex CIO take: book fit is reasonable; size small.

House risk hub was thin.
"""

DESK_FAKE_CIO_FIXTURE = """🧠 *Alex · Trade-AI grounded*

Iris found nothing durable on S.
CIO take: wait for Hermes.

Price was $19.84 (STALE).
"""


def test_maria_a2a_deny_strips_iris_alex_roleplay():
    scrubbed, decision = sa.scrub_operator_specialist_claims(
        MARIA_A2A_DENY_FIXTURE,
        surface="maria",
        a2a_enabled=False,
        evidence=[],
    )
    low = scrubbed.lower()
    assert "iris found" not in low
    assert "alex cio take" not in low
    assert "iris / alex" not in low
    assert sa.A2A_DENY_NOTICE in scrubbed
    assert decision.stripped_claims
    assert decision.text_changed


def test_maria_a2a_on_with_session_ids_keeps_labels():
    evidence = [
        sa.SpecialistRunEvidence("iris", "sess_iris_1", sa.SOURCE_OPENCLAW_A2A),
        sa.SpecialistRunEvidence("alex", "sess_alex_1", sa.SOURCE_OPENCLAW_A2A),
    ]
    body = "Iris found a catalyst.\nAlex CIO take: size small.\n"
    scrubbed, decision = sa.scrub_operator_specialist_claims(
        body, surface="maria", a2a_enabled=True, evidence=evidence
    )
    assert "Iris found" in scrubbed
    assert "Alex CIO take" in scrubbed
    assert sa.A2A_DENY_NOTICE not in scrubbed
    assert not decision.stripped_claims


def test_maria_a2a_on_without_session_still_refuses():
    body = "Iris found a catalyst.\n"
    scrubbed, decision = sa.scrub_operator_specialist_claims(
        body, surface="maria", a2a_enabled=True, evidence=[]
    )
    assert "iris found" not in scrubbed.lower()
    assert decision.stripped_claims
    assert sa.REFUSE_LABEL_NOTICE in scrubbed


def test_desk_fake_attribution_stripped_product_voice_kept():
    scrubbed, decision = sa.scrub_operator_specialist_claims(
        DESK_FAKE_CIO_FIXTURE,
        surface="desk",
        a2a_enabled=False,
        evidence=[],
    )
    assert "🧠 *Alex · Trade-AI grounded*" in scrubbed
    assert "iris found" not in scrubbed.lower()
    assert "cio take:" not in scrubbed.lower()
    assert decision.stripped_claims
    assert sa.REFUSE_LABEL_NOTICE in scrubbed


def test_desk_synthesis_evidence_allows_cio_take():
    evidence = [
        sa.SpecialistRunEvidence("cio", "synth_abc123", sa.SOURCE_DESK_SYNTHESIS),
    ]
    body = "CIO take: hold size; wait for levels.\n"
    scrubbed, decision = sa.scrub_operator_specialist_claims(
        body, surface="desk", evidence=evidence
    )
    assert "CIO take:" in scrubbed
    assert not decision.stripped_claims


def test_desk_agent_job_allows_iris_label():
    evidence = [
        sa.SpecialistRunEvidence("iris", "job_iris_9", sa.SOURCE_DESK_AGENT_JOB),
    ]
    body = "Iris found a gap in coverage.\n"
    scrubbed, _ = sa.scrub_operator_specialist_claims(
        body, surface="desk", evidence=evidence
    )
    assert "Iris found" in scrubbed


def test_maria_parity_hook_scrub_matches_surface_rules():
    scrubbed, decision = mph.scrub_maria_outbound(
        MARIA_A2A_DENY_FIXTURE, a2a_enabled=False
    )
    assert sa.A2A_DENY_NOTICE in scrubbed
    assert decision.surface == "maria"


def test_try_shared_perspective_entry_none_when_join_module_absent():
    """This Stage 2 tree alone (no operator_internal_first) → None."""
    # Ensure a stale successful import from another worktree cannot leak in.
    sys.modules.pop("scripts.lib.operator_internal_first", None)
    sys.modules.pop("scripts.lib.hermes_subject_join", None)
    # Re-import hook after clearing; if module still importable from this tree,
    # skip the None assertion (combined tree).
    if importlib.util.find_spec("scripts.lib.operator_internal_first") is not None:
        pytest.skip("join library present in this tree — see call-path test")
    assert (
        mph.try_shared_perspective_entry(
            question="perspective on S", symbol="S", a2a_enabled=False
        )
        is None
    )


def test_try_shared_perspective_entry_calls_answer_internal_first(monkeypatch):
    """When join API is importable, hook calls answer_internal_first + scrubs."""
    import types

    calls: list[dict] = []

    class _FakeResult:
        def to_dict(self):
            return {
                "text": "Iris found a catalyst.\nHouse notes thin.\n",
                "kind": "internal_first",
                "hermes_join": {"status": "HUB_PROMOTED_0"},
                "schema": "OperatorInternalFirst@v1",
            }

    def _fake_answer(text, **kw):
        calls.append({"text": text, **kw})
        return _FakeResult()

    fake_mod = types.ModuleType("scripts.lib.operator_internal_first")
    fake_mod.answer_internal_first = _fake_answer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.lib.operator_internal_first", fake_mod)

    out = mph.try_shared_perspective_entry(
        question="perspective on SentinelOne",
        a2a_enabled=False,
        chat_id="8797974247",
        use_desk=False,
    )
    assert out is not None
    assert calls and calls[0]["text"] == "perspective on SentinelOne"
    assert calls[0]["surface"] == "maria"
    assert calls[0]["use_desk"] is False
    assert calls[0]["channel"] == "skill"
    assert "iris found" not in out["text"].lower()
    assert sa.A2A_DENY_NOTICE in out["text"]
    assert out["maria_parity_hook"] == mph.SCHEMA
    assert out["hermes_join"]["status"] == "HUB_PROMOTED_0"


def test_cli_hook_scrubs_stdin(tmp_path):
    script = ROOT / "scripts" / "openclaw_maria_hooks" / "specialist_honesty_hook.py"
    assert script.is_file()
    proc = subprocess.run(
        [sys.executable, str(script), "--a2a", "off", "--text-file", "-"],
        input=MARIA_A2A_DENY_FIXTURE,
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "iris found" not in proc.stdout.lower()
    assert sa.A2A_DENY_NOTICE in proc.stdout
    decision = json.loads(proc.stderr.strip().splitlines()[-1])
    assert decision["stripped_claims"]


def test_evidence_from_dicts_filters_bad_rows():
    rows = sa.evidence_from_dicts(
        [
            {"agent_id": "iris", "session_id": "s1", "source": sa.SOURCE_OPENCLAW_A2A},
            {"agent_id": "alex", "run_id": "", "source": sa.SOURCE_OPENCLAW_A2A},
            {"agent_id": "x", "job_id": "j1", "source": "invented"},
        ]
    )
    assert len(rows) == 1
    assert rows[0].agent_id == "iris"


def test_converse_core_prepare_reply_scrubs_fake_desk_attribution(monkeypatch):
    """Static + light integration: _prepare_reply path records specialist_attribution."""
    from scripts.lib import cio_converse_core as core

    # Dry-run a desk-shaped outbound that would otherwise leak Iris roleplay.
    # process_operator_message is heavy; unit-test the scrub contract the
    # chokepoint now calls.
    body = "Iris found nothing.\nCIO take: skip.\n"
    scrubbed, attr = sa.scrub_operator_specialist_claims(
        body, surface="desk", evidence=[]
    )
    assert "iris found" not in scrubbed.lower()
    # Ensure converse_core imports the scrub (wire presence).
    src = Path(core.__file__).read_text(encoding="utf-8")
    assert "scrub_operator_specialist_claims" in src
    assert "specialist_attribution" in src
    assert attr.stripped_claims
