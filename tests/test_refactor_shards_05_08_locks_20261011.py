"""Source-only lock identity audit; never runs a lock, host command or business lane."""
from __future__ import annotations

import json
from pathlib import Path
import shlex

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOF = json.loads((ROOT / "tests/fixtures/refactor_shards_05_08/approved_locks.json").read_text())
LANES = {row["lane_id"]: row for row in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
ROWS = {row["lane_id"]: row for row in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]}
SHARD_WAVES = {"R2-05", "R2-06", "R2-07", "R2-08"}

# Operator ruling 2026-10-11 ("yes to all 4 for train 3", applied the same way in train 4): lanes another wave
# already owns (train 2's premarket C1 stage RETIRED rows, SW4 EXCLUDED lanes) keep their owner's rows and get no
# allowlist entry; shard assertions apply only to rows this shard actually admitted. A contract may be DRAFT or
# operator-REVIEWED.
def _owned_here(row):
    return (row or {}).get("scheduler", {}).get("wave") in SHARD_WAVES


def _contract_ok(contract):
    if contract.get("status") == "DRAFT":
        return "reviewer" not in contract
    review = contract.get("review") or {}
    return contract.get("status") == "REVIEWED" and "operator" in str(review.get("reviewed_by", "")).lower()


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
    if not _owned_here(ROWS.get(lane_id)):
        assert lane_id not in LANES, lane_id  # held: owner's row, no allowlist entry
        return
    if lane_id in _CANARY_WAVE_1B:
        # canary-wave-1b-20261014: packet cron-lock-wrappers-20261014 wraps the safe_flock.sh line in `flock -n <the
        # same path>`; the allowlist takes lock_kind flock on that path (the cron flock), never a new path.
        entry = LANES[lane_id]
        assert entry["lock_kind"] == "flock", lane_id
        assert_lock_identity(dict(entry, lock_kind="safe_flock"), PROOF["lanes"][lane_id])
        assert observed_locks(ROWS[lane_id]["scheduler"]["command_text"]) == {
            ("flock", entry["lock"]), ("safe_flock", entry["lock"])}, lane_id
        return
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
    # canary-wave-1c-locks moves this to ("flock", same path) once the cron-lock-wrappers packet is installed.
    want_kind = "flock" if "hermes-scope-governor" in _CANARY_WAVE_1B else "safe_flock"
    assert (lane["lock_kind"], lane["lock"]) == (want_kind, "/tmp/hermes_scope_governor.lock")
    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
    contract = next(row for row in contracts if row["id"] == "hermes-scope-governor")
    assert _contract_ok(contract)
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

from tests.test_canary_wave_1b_20261014 import CANARY_WAVE_1B as _CANARY_WAVE_1B  # noqa: E402  canary-wave-1b-20261014
