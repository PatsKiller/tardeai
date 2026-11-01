"""Lost design approval (2026-10-31): two phone taps on DSN-20261031-market-risk-ui recorded nothing. Hermetic.

The Approvals Center served design-registry designs as RECORD items. Their reader Approve was a disabled button until
"Start reading" plus a 3-second read of every line (51 for that design), so a tap did nothing and said nothing. Even a
completed approval went to governance/operator_decisions.jsonl (RECORD_ONLY), which design_registry never reads; it
reads only <claims_dir>/designs/approvals.jsonl from Ops Controls kind pipeline.approve_design. The work pipeline card
that offers that Approve was cut by MAX_ITEMS because awaiting designs are grouped last.

Pinned here: a design-registry design is GOVERNED_PATH with a link to its pipeline card; the governance ledger refuses
its APPROVE visibly (GOVERNED_ACTION_REQUIRED, nothing written); the awaiting design card and its Tier 2 Approve
survive the item cap.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import operator_approvals as core  # noqa: E402
from scripts.lib import operator_approvals_api as api  # noqa: E402
from scripts.lib import work_pipeline as W  # noqa: E402
from scripts.lib import work_pipeline_tier2 as T2  # noqa: E402

NOW = datetime(2032, 4, 12, 14, 0, tzinfo=timezone.utc)
DESIGN_ID = "DSN-20320412-demo-ui"
TEXT = "---\nid: DSN-20320412-demo-ui\ntitle: Demo design\nstatus: PROPOSED\napproval: awaiting operator\n---\n# Demo\n"
META = {"title": "Demo design", "proposed_by": "fixture agent", "created_at": "2032-04-12T12:00:00Z"}


def design_row() -> dict:
    return {
        "kind": "design",
        "id": DESIGN_ID,
        "title": "Demo design",
        "status": "PROPOSED",
        "approval": "awaiting operator",
        "path": f"design/registry/{DESIGN_ID}.md",
    }


@pytest.fixture
def rig(tmp_path):
    clock = [NOW]
    row = api.design_registry_entry(design_row(), META, TEXT, "a" * 40)
    ledger = core.DecisionLedger(
        tmp_path / "governance" / "operator_decisions.jsonl", approved=lambda: True, clock=lambda: clock[0]
    )
    ctx = api.Ctx(
        principal=lambda: "tailnet:operator@example.test",
        listener=lambda: "serve_proxy",
        csrf=lambda m, p: (True, ""),
        allowed_logins=frozenset({"operator@example.test"}),
        sources={"design_decisions": lambda: {"rows": [row], "resolved": [], "gap": None}},
        ledger=ledger,
        policy=lambda: {},
        clock=lambda: clock[0],
        can_read=lambda: True,
    )
    return ctx, row, clock, tmp_path


def post(ctx, route: str, body: dict) -> tuple[int, dict]:
    path = f"/api/v2/governance/approvals/design%3A{DESIGN_ID}/{route}"
    return api.handle(path, "POST", body, ctx=ctx)


def test_design_registry_design_is_governed_and_links_to_its_pipeline_card(rig):
    _, row, _, _ = rig
    assert row["kind"] == "DESIGN" and row["source"] == "design_registry"
    assert row["decision_mode"] == "GOVERNED_PATH"
    assert row["governed_href"] == f"/coordination?design={DESIGN_ID}"
    packet = api.design_registry_entry({**design_row(), "kind": "packet"}, META, TEXT, "a" * 40)
    assert packet["kind"] == "ACTIVATE" and packet["decision_mode"] == "GOVERNED_PATH"
    assert packet["governed_href"] == "/coordination?tab=work"


def test_reader_approve_of_a_design_fails_visibly_and_writes_no_decision(rig):
    """The lost-approval path end to end through the HTTP handler: open, read every change, approve."""
    ctx, row, clock, tmp_path = rig
    sha = row["document"]["document_sha"]
    status, out = post(ctx, "open", {"document_sha": sha})
    assert status == 200, out
    review = out["data"]["review_id"]
    for change in row["document"]["changes"]:
        marker = {"review_id": review, "document_sha": sha, "change_id": change["id"]}
        assert post(ctx, "read", {**marker, "phase": "enter"})[0] == 200
        clock[0] += timedelta(seconds=3)
        assert post(ctx, "read", {**marker, "phase": "read"})[0] == 200
    status, out = post(
        ctx,
        "decide",
        {
            "decision": "APPROVE",
            "review_id": review,
            "document_sha": sha,
            "request_id": "request_123456",
            "comment": "",
        },
    )
    # Before the fix: 200 + a RECORD_ONLY DECIDED row the design registry never reads (the design stayed PROPOSED).
    assert (status, out) == (409, {"ok": False, "error": "GOVERNED_ACTION_REQUIRED"})
    assert not [r for r in ctx.ledger.rows() if r.get("event") == "DECIDED"]
    claims = tmp_path / "claims"
    assert DESIGN_ID not in T2.design_approvals(claims)  # nothing pretends the design was approved


def test_registry_reads_only_the_tier2_design_ledger(tmp_path):
    """Where an approval must land for design_registry to see it, and that the governance ledger is not it."""
    claims = tmp_path / "claims"
    ledger = core.DecisionLedger(tmp_path / "governance" / "operator_decisions.jsonl", approved=lambda: True)
    with ledger._transaction() as (_, append):
        append({"event": "DECIDED", "item_id": "design:" + DESIGN_ID, "kind": "DESIGN", "decision": "APPROVE"})
    assert T2.design_approvals(claims) == {}
    (claims / "designs").mkdir(parents=True)
    (claims / T2.DESIGN_LEDGER_REL).write_text(
        json.dumps({"schema": T2.DESIGN_SCHEMA, "id": DESIGN_ID, "status": "APPROVED"}) + "\n"
    )
    assert DESIGN_ID in T2.design_approvals(claims)


def _open_pr(n: int) -> dict:
    at = (NOW - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    return {
        "number": n,
        "title": f"PR {n}",
        "url": f"https://github.com/o/r/pull/{n}",
        "branch": f"feat/{n}",
        "head_sha": "abc1234def",
        "base": "main",
        "draft": False,
        "author": "fixture",
        "created_at": at,
        "updated_at": at,
        "state": "open",
        "ci": {"state": "green", "failing": [], "pending": [], "total": 1, "completed_at": at},
    }


def test_awaiting_design_and_its_tier2_approve_survive_the_item_cap():
    census = {"open": [_open_pr(1000 + i) for i in range(W.MAX_ITEMS + 25)], "merged": [], "batches": {}}
    items = W.build_items(
        tasks=[],
        claims=[],
        census=census,
        awaiting=[design_row()],
        now=NOW,
        latest_line=lambda p: None,
        tier2={"flags": {"pipeline.approve_design": True}, "notes": {}},
    )
    assert len(items) == W.MAX_ITEMS
    card = next((i for i in items if i["id"] == DESIGN_ID), None)
    assert card is not None, "the awaiting design was truncated away: no Approve anywhere"
    assert card["what"]["design_id"] == DESIGN_ID  # what /coordination?design=<id> filters on
    approve = [a for a in card["actions"]["tier2"] if a["kind"] == "pipeline.approve_design"]
    assert approve == [
        {
            "kind": "pipeline.approve_design",
            "label": "Approve",
            "params": {"design_id": DESIGN_ID},
            "enabled": True,
            "policy_note": None,
        }
    ]
