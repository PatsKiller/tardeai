"""Wake → cortex shadow canary hook (flags default OFF; MBI=0)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cortex_shadow_pipeline import (  # noqa: E402
    AGENT_VIEW_FLAG,
    CORTEX_SHADOW_FLAG,
)
from scripts.lib.governed_commitment import FEATURE_FLAG as COMMITMENT_FLAG  # noqa: E402
from scripts.lib.persistent_agent_wake import FEATURE_FLAG as WAKE_FLAG  # noqa: E402
from scripts.lib.persistent_wake_schedule import FEATURE_FLAG as SCHED_FLAG  # noqa: E402
from scripts.run_persistent_wake import (  # noqa: E402
    _maybe_cortex_shadow_after_wake,
    run_once,
)

SG = "97172f54-916c-5960-aa73-f16321f1cf3e"
NOW = datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)
WAKE_ENV = {
    WAKE_FLAG: "1",
    SCHED_FLAG: "1",
    "PROVENANCE_PRODUCER": "test",
    "TRADEAI_SOURCE_SHA": "bd9950df8e9bf23002e6a126e0736e4b3e4b3f02",
}


def _mem(tmp_path: Path, content: str = "alpha", *, hours_ago: float = 1.0) -> Path:
    p = tmp_path / "mem.jsonl"
    row = {
        "fact_id": "f1",
        "subject_guid": SG,
        "content": content,
        "as_of": (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z"),
    }
    p.write_text(json.dumps(row) + "\n")
    return p


def test_helper_flag_off_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(AGENT_VIEW_FLAG, raising=False)
    monkeypatch.delenv(CORTEX_SHADOW_FLAG, raising=False)
    out = _maybe_cortex_shadow_after_wake(
        state_root=tmp_path,
        subject_guid=SG,
        wake_id="wake-abc",
        env={},
    )
    assert out is None
    assert list(tmp_path.iterdir()) == []


def test_helper_flag_on_writes_agent_views_no_commitments(tmp_path, monkeypatch):
    monkeypatch.setenv(CORTEX_SHADOW_FLAG, "1")
    monkeypatch.delenv(COMMITMENT_FLAG, raising=False)
    env = {CORTEX_SHADOW_FLAG: "1", COMMITMENT_FLAG: "1"}  # must still force commitment off
    out = _maybe_cortex_shadow_after_wake(
        state_root=tmp_path,
        subject_guid=SG,
        wake_id="wake-abc",
        env=env,
    )
    assert out is not None
    assert out["ok"] is True
    assert out["outcome"] == "shadow_written"
    path = tmp_path / "agent_views.jsonl"
    assert path.exists()
    row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["schema_version"] == "AgentView@v1"
    assert row["mbi_behavior"] == 0
    assert row["citations"] == ["wake:wake-abc"]
    assert "buy " not in row["summary"].lower()
    assert "sell " not in row["summary"].lower()
    assert not (tmp_path / "commitments.jsonl").exists()


def test_run_once_flag_off_no_agent_views(tmp_path, monkeypatch):
    monkeypatch.delenv(AGENT_VIEW_FLAG, raising=False)
    monkeypatch.delenv(CORTEX_SHADOW_FLAG, raising=False)
    state = tmp_path / "s"
    rc = run_once(
        agent_id="cio",
        subject_guid=SG,
        env=dict(WAKE_ENV),
        when=NOW,
        state_root=state,
        memory_backend=_mem(tmp_path),
    )
    assert rc == 0
    assert (state / "wakes.jsonl").exists()
    assert not (state / "agent_views.jsonl").exists()


def test_run_once_flag_on_writes_agent_views_no_governed_commitment(tmp_path, monkeypatch):
    monkeypatch.setenv(AGENT_VIEW_FLAG, "1")
    monkeypatch.delenv(COMMITMENT_FLAG, raising=False)
    state = tmp_path / "s"
    env = dict(WAKE_ENV)
    env[AGENT_VIEW_FLAG] = "1"
    env[COMMITMENT_FLAG] = "1"  # wake path must still refuse governed minting
    rc = run_once(
        agent_id="cio",
        subject_guid=SG,
        env=env,
        when=NOW,
        state_root=state,
        memory_backend=_mem(tmp_path),
    )
    assert rc == 0
    views = state / "agent_views.jsonl"
    assert views.exists()
    row = json.loads(views.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["schema_version"] == "AgentView@v1"
    assert row["mbi_behavior"] == 0
    assert any(str(c).startswith("wake:") for c in row["citations"])
    # Wake engine may write CommitmentRecord@v2; cortex must not mint GovernedCommitment@v1.
    cpath = state / "commitments.jsonl"
    if cpath.exists():
        for line in cpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            crow = json.loads(line)
            assert crow.get("schema_version") != "GovernedCommitment@v1"
            assert crow.get("source_identity") != "cortex_shadow_pipeline"
