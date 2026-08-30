from scripts.lib.cio_council_synthesis import synthesize
from scripts.lib.cio_delivery_receipt import build as build_receipt
from scripts.lib.cio_research_templates import build as build_template


def test_council_preserves_workflow_identity():
    row = synthesize(workflow_id="wf-1", artifacts=[], symbol="SCHD")
    assert row["workflow_id"] == "wf-1"


def test_research_template_carries_workflow_identity():
    prompt = build_template("flash", symbol="SCHD", research_id="r-1", workflow_id="wf-1")
    assert prompt["carry"]["workflow_id"] == "wf-1"


def test_delivery_receipt_preserves_workflow_and_generation():
    row = build_receipt({
        "notification_id": "n-1",
        "workflow_id": "wf-1",
        "generation_id": "g-1",
        "decision": "SUPPRESSED",
    })
    assert row["workflow_id"] == "wf-1"
    assert row["generation_id"] == "g-1"
