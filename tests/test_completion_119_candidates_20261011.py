"""Held-candidate controls prevent omission, duplication and authority inflation."""
from __future__ import annotations

import copy
import json

import pytest

from scripts.check_completion_119_candidates import PACKETS, findings, main


def packets():
    scope = json.loads((PACKETS / "scope-119.json").read_text())
    candidates = [json.loads((PACKETS / f"candidates-{group}.json").read_text())
                  for group in ("01-03", "04-06", "07-08")]
    return scope, candidates


def test_all_119_are_present_once_and_held():
    scope, candidates = packets()
    assert findings(scope, candidates) == []
    assert main([]) == 0


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "live", "reviewed", "runtime", "fake_cron"])
def test_bad_packet_is_refused(mutation):
    scope, candidates = packets()
    candidates = copy.deepcopy(candidates)
    row = candidates[0]["rows"][0]
    if mutation == "missing":
        candidates[0]["rows"].pop()
    elif mutation == "duplicate":
        candidates[1]["rows"].append(copy.deepcopy(row))
    elif mutation == "foreign":
        row["lane_id"] = "outside-the-approved-scope"
    elif mutation == "live":
        row["proposed_candidate"]["live_arg"] = "--apply"
    elif mutation == "reviewed":
        row["proposed_candidate"]["status"] = "REVIEWED"
    elif mutation == "runtime":
        candidates[0]["runtime"] = "LIVE"
    elif mutation == "fake_cron":
        row["registry_candidate"] = {"scheduler": {"kind": "cron", "expression": "0 * * * *"}}
    assert findings(scope, candidates)


def test_unreadable_packets_are_not_a_pass(tmp_path):
    assert main(["--directory", str(tmp_path)]) == 2
