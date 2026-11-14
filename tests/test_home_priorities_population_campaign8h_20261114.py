"""CAMPAIGN-8H Home item 4: the priorities body carries the population its empty list is claimed over.

The ranking's empty list is only ever served with ``state: OK`` (every input read, nothing to do). For the page to
print that claim as evidence rather than an assertion, ``rank()`` now also returns ``inputs``: one entry per input
with whether it was read, how many rows it returned, and why not when it was not.

(The per-principal cache key on the route is a separate change in ``scripts/api_v2.py`` with its own test:
``tests/test_home_priorities_principal_scope_campaign8h_20261114.py``.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import home_priorities_live as hp  # noqa: E402

INC = {"state": "OK", "items": [{"incident_id": "a", "priority": "P0", "blocks_trading": True, "category": "Outage",
                                 "cause": "pipeline failed", "first_seen_at": "2026-11-12T10:00:00+00:00"}]}
APPROVALS_ZERO = {"ok": True, "data": {"count": 0, "urgent_count": 0}}


def test_inputs_evidence_names_every_input_with_its_population():
    body = hp.rank(INC, {"status": "no_snapshot"}, APPROVALS_ZERO)
    assert body["state"] == "PARTIAL"  # stop advice not read in this fixture
    assert body["inputs"] == [
        {"input": "incidents", "read": True, "rows": 1, "reason": None},
        {"input": "stop advice", "read": False, "rows": None, "reason": "stop advice not read"},
        {"input": "approvals", "read": True, "rows": 0, "reason": None},
    ]


def test_all_three_read_and_empty_is_OK_with_a_zero_population():
    body = hp.rank({"state": "OK", "items": []},
                   {"status": "ok", "cio_brief": {"status": "available", "stop_advice": []}},
                   APPROVALS_ZERO)
    assert body["state"] == "OK" and body["items"] == []
    assert [i["rows"] for i in body["inputs"]] == [0, 0, 0]
    assert all(i["read"] is True for i in body["inputs"])


def test_an_unread_approvals_input_is_named_in_evidence_not_counted_as_zero():
    body = hp.rank(INC, {"status": "no_snapshot"}, None)
    assert body["inputs"][2] == {"input": "approvals", "read": False, "rows": None, "reason": "approvals count not read"}
