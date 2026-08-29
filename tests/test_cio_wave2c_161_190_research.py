"""Wave 2C items 186 / 188 / 190 — the deterministic path stays deterministic.

`cio_run_worker`'s injected synthesis_fn is a product build, not a model. Before
`ff09c255` it still stamped `CIO_RUN_MODEL_CALL_RECORDED` at $0.001 — 46 fake
receipts across 2026-08-27/28, the last at 13:46:33Z, three minutes before that
fix was committed. 47 completed runs since have recorded none.

These lock the contract so the receipts cannot come back quietly.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import inspect

from scripts.lib import cio_run_worker


def test_deterministic_synthesis_declares_zero_cost_and_no_model_call():
    src = inspect.getsource(cio_run_worker)
    assert '"dispatch_kind", "DETERMINISTIC_PRODUCT"' in src
    assert '"dispatch_kind": "DETERMINISTIC_PRODUCT"' in src
    # the three fields that make a fake receipt impossible to write
    assert '"llm_dispatch", False' in src
    assert '"model_calls", 0' in src
    assert '"cost_usd", 0.0' in src


def test_the_reason_is_written_down_next_to_the_code():
    """A bare `cost_usd = 0.0` invites someone to 'fix' it later."""
    src = inspect.getsource(cio_run_worker)
    assert "not a model" in src
    assert "CIO_RUN_MODEL_CALL_RECORDED" in src


def test_deterministic_defaults_are_never_a_nonzero_cost():
    src = inspect.getsource(cio_run_worker)
    for bad in ('"cost_usd": 0.001', '"cost_usd", 0.001', "cost_usd = 0.001"):
        assert bad not in src


def test_research_verdicts_cannot_create_an_action():
    """Item 186: research is context. It never becomes a DO_NOW."""
    from scripts.lib.research_quality import critique

    verdict = critique({
        "symbol": "SCHD",
        "summary": "SCHD income ballast as of 2026-08-01. Place an order to buy.",
        "sources": ["https://example.test"],
        "as_of": "2026-08-01",
    })
    # execution language is caught and refused, never promoted
    assert verdict["verdict"] == "FAILED"
    assert "forbidden_authority" in verdict["reasons"]
    assert verdict["financial_action"] is False


def test_attach_rule_still_refuses_a_failed_critique():
    from scripts.lib.hermes_research_loop import research_complete_is_attachable

    assert research_complete_is_attachable(
        {"status": "completed"}, {"verdict": "FAILED"},
    ) is False
