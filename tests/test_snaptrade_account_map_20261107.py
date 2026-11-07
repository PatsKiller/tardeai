"""SNAPTRADE_ACCOUNT_MAP_20261107 (LQ-20261107-251): where the SnapTrade account map is found. Synthetic ids only."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import snaptrade_account_map as m  # noqa: E402

SYN = {"accounts": {"synthetic-acct-1": "ACCT_A", "synthetic-acct-2": "ACCT_B"}}


def _put(root: Path, data):
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / m.FILENAME).write_text(data if isinstance(data, str) else json.dumps(data))


def test_release_tree_without_map_reads_the_state_root(tmp_path, monkeypatch):
    monkeypatch.delenv(m.ENV_VAR, raising=False)
    release, state = tmp_path / "release", tmp_path / "state"
    release.mkdir()
    _put(state, SYN)
    assert m.load(repo_root=release, state_root=state) == {"synthetic-acct-1": "ACCT_A", "synthetic-acct-2": "ACCT_B"}
    assert m.map_path(repo_root=release, state_root=state) == state / "config" / m.FILENAME


def test_old_repo_location_still_works(tmp_path, monkeypatch):
    monkeypatch.delenv(m.ENV_VAR, raising=False)
    repo, state = tmp_path / "repo", tmp_path / "state"
    _put(repo, {"synthetic-acct-9": "ACCT_Z"})
    assert m.load(repo_root=repo, state_root=state) == {"synthetic-acct-9": "ACCT_Z"}


def test_state_root_beats_repo_and_env_beats_both(tmp_path, monkeypatch):
    repo, state = tmp_path / "repo", tmp_path / "state"
    _put(repo, {"r": "REPO"})
    _put(state, {"s": "STATE"})
    monkeypatch.delenv(m.ENV_VAR, raising=False)
    assert m.load(repo_root=repo, state_root=state) == {"s": "STATE"}
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps({"e": "ENV"}))
    monkeypatch.setenv(m.ENV_VAR, str(explicit))
    assert m.load(repo_root=repo, state_root=state) == {"e": "ENV"}


def test_missing_everywhere_is_empty_and_names_the_places(tmp_path, monkeypatch):
    monkeypatch.delenv(m.ENV_VAR, raising=False)
    repo, state = tmp_path / "repo", tmp_path / "state"
    assert m.map_path(repo_root=repo, state_root=state) is None
    assert m.load(repo_root=repo, state_root=state) == {}
    text = m.searched(repo_root=repo, state_root=state)
    assert str(state / "config" / m.FILENAME) in text and str(repo / "config" / m.FILENAME) in text


def test_invalid_file_is_empty_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.delenv(m.ENV_VAR, raising=False)
    state = tmp_path / "state"
    _put(state, "{not json")
    assert m.load(repo_root=tmp_path / "r", state_root=state) == {}


def test_broker_access_row_uses_the_resolver(tmp_path, monkeypatch):
    monkeypatch.delenv(m.ENV_VAR, raising=False)
    from lib.data_broker import broker_access as ba
    state = tmp_path / "state"
    row = ba.snaptrade_row(state, {})
    assert row["state"] == ba.DEGRADED and "Looked in" in row["reason"]
    _put(state, SYN)
    monkeypatch.setattr(ba, "PROJECT_ROOT", tmp_path / "release")
    row = ba.snaptrade_row(state, {})
    assert row["mapping_file_present"] is True
