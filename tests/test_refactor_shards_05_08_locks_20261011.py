"""Source-only lock identity audit; never runs a lock, host command or business lane."""
from __future__ import annotations

import json
from pathlib import Path
import shlex

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOF = json.loads((ROOT / "tests/fixtures/refactor_shards_05_08/approved_locks.json").read_text())
LANES = {row["lane_id"]: row for row in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}


def observed_locks(command):
    """Read literal approved shell tokens, including bash -c; never evaluate them."""
    tokens = shlex.split(command, comments=True)
    locks = set()
    for index, token in enumerate(tokens):
        if Path(token).name == "safe_flock.sh":
            locks.add(("safe_flock", tokens[index + 1]))
        elif token == "flock":
            pos = index + 1
            while tokens[pos].startswith("-"):
                flag = tokens[pos]
                assert flag in {"-n", "--nonblock", "-E", "--conflict-exit-code"}, flag
                pos += 2 if flag in {"-E", "--conflict-exit-code"} else 1
            locks.add(("flock", tokens[pos]))
        elif token == "-c" and index and tokens[index - 1] in {"bash", "sh"}:
            locks.update(observed_locks(tokens[index + 1]))
    return locks


def assert_lock_identity(entry, proof):
    observed = set().union(*(observed_locks(line) for line in proof["cron_lines"]))
    assert len(observed) <= 1, observed
    if observed:
        assert (entry.get("lock_kind", "safe_flock"), entry["lock"]) == next(iter(observed)), entry["lane_id"]
        assert not proof["lock_proposed"], entry["lane_id"]
    else:
        assert proof["lock_proposed"], entry["lane_id"]
        assert entry["lock"] == "/tmp/" + entry["lane_id"] + ".lock", entry["lane_id"]


@pytest.mark.parametrize("lane_id", sorted(PROOF["lanes"]))
def test_all_22_proposals_reuse_original_lock_kind_and_path(lane_id):
    assert_lock_identity(LANES[lane_id], PROOF["lanes"][lane_id])


@pytest.mark.parametrize("kind,path", [
    ("flock", "/tmp/hermes_scope_governor.lock"),
    ("safe_flock", "/tmp/hermes-scope-governor.lock"),
    ("flock", "/tmp/hermes-scope-governor.lock"),
])
def test_governor_wrong_kind_or_path_is_rejected(kind, path):
    broken = dict(LANES["hermes-scope-governor"], lock_kind=kind, lock=path)
    with pytest.raises(AssertionError, match="hermes-scope-governor"):
        assert_lock_identity(broken, PROOF["lanes"]["hermes-scope-governor"])


def test_governor_reuses_the_pid_guard_and_draft_lock_edge():
    lane = LANES["hermes-scope-governor"]
    assert (lane["lock_kind"], lane["lock"]) == ("safe_flock", "/tmp/hermes_scope_governor.lock")
    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
    contract = next(row for row in contracts if row["id"] == "hermes-scope-governor")
    assert contract["status"] == "DRAFT"
    lock_edges = [edge for edge in contract["connects_to"] if edge["kind"] == "lock"]
    assert len(lock_edges) == 1 and lock_edges[0]["name"] == lane["lock"]
    assert "PID guard reused" in lock_edges[0]["source"]


def test_only_eight_missing_locks_are_proposed_with_retired_states_preserved():
    proposed = {lane for lane, row in PROOF["lanes"].items() if row["lock_proposed"]}
    assert proposed == {"drain-discovery-backlog", "commitment-outcome-sweep", "social-ingest-stocktwits",
                        "instrument-belief-writer", "iris-proposal-curator", "price-db-sync",
                        "sync-dividend-data", "agent-recommendation-normalizer"}
    rows = {row["lane_id"]: row for row in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
    assert sum(rows[lane]["state"] == "ACTIVE" for lane in proposed) == 5
    assert sum(rows[lane]["state"] == "RETIRED" for lane in proposed) == 3
