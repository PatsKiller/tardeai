"""Canonical claim paths, durable TTL/boot-id, concurrency (SOP verifier fixes)."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest

from scripts.lib.agent_file_lease import (
    SCHEMA_VERSION,
    LeaseCoordinator,
    canonicalize_claim_path,
    paths_overlap,
    validate_ttl,
)


# --- A. path canonicalization -------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("scripts/x.py", "scripts/x.py"),
        ("./scripts/x.py", "scripts/x.py"),
        ("scripts//x.py", "scripts/x.py"),
        ("scripts/lib/", "scripts/lib"),
        ("./scripts//lib/", "scripts/lib"),
        ("scripts/./x.py", "scripts/x.py"),
    ],
)
def test_canonicalize_harmless_aliases(raw, expected):
    assert canonicalize_claim_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "/abs/path",
        "",
        ".",
        "/",
        "./",
        "scripts/../etc/passwd",
        "../secrets",
        "a/\x00/b",
        "a/\n/b",
        None,
    ],
)
def test_canonicalize_rejects_malformed(raw):
    with pytest.raises((ValueError, TypeError)):
        canonicalize_claim_path(raw)  # type: ignore[arg-type]


def test_canonicalize_rejects_outside_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # Lexical .. already rejected; also ensure resolve-escape via symlink if possible
    with pytest.raises(ValueError, match="traversal|outside"):
        canonicalize_claim_path("../outside", repo_root=repo)


def test_verifier_exact_reproduction_aliases_collide(tmp_path: Path):
    """Exact verifier bypasses must collide after canonicalization."""
    # 1) file vs parent dir with trailing slash
    assert paths_overlap("scripts/lib/agent_file_lease.py", "scripts/lib/")
    assert paths_overlap("scripts/lib/", "scripts/lib/agent_file_lease.py")
    # 2) leading ./
    assert paths_overlap("scripts/x.py", "./scripts/x.py")
    # 3) repeated /
    assert paths_overlap("scripts//x.py", "scripts/x.py")

    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["scripts/lib/"])
    assert a.paths == ["scripts/lib"]  # stored canonical only
    with pytest.raises(RuntimeError, match="overlap"):
        coord.acquire(session_id="s2", agent_id="codex", paths=["scripts/lib/agent_file_lease.py"])
    with pytest.raises(RuntimeError, match="overlap"):
        coord.acquire(session_id="s3", agent_id="codex", paths=["./scripts/lib/foo.py"])
    coord.release(a.lease_id, session_id="s1")

    b = coord.acquire(session_id="s4", agent_id="grok", paths=["./scripts/x.py"])
    assert b.paths == ["scripts/x.py"]
    with pytest.raises(RuntimeError, match="overlap"):
        coord.acquire(session_id="s5", agent_id="codex", paths=["scripts//x.py"])


def test_parent_child_and_disjoint(tmp_path: Path):
    assert paths_overlap("docs/a", "docs/a/b.md")
    assert paths_overlap("docs/a/b.md", "docs/a")
    assert not paths_overlap("docs/a", "docs/b")
    assert not paths_overlap("docs/a.md", "docs/a")  # file vs sibling-prefix dir name

    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"])
    b = coord.acquire(session_id="s2", agent_id="codex", paths=["docs/b.md"])
    assert a.lease_id != b.lease_id


def test_normalization_before_persist(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-test")
    lease = coord.acquire(session_id="s1", agent_id="grok", paths=["./scripts//lib/"])
    raw = json.loads((coord.leases_dir / f"{lease.lease_id}.json").read_text(encoding="utf-8"))
    assert raw["paths"] == ["scripts/lib"]
    assert "./" not in raw["paths"][0]
    assert "//" not in raw["paths"][0]


def _acquire_worker(root: str, path: str, q: mp.Queue, boot: str) -> None:
    try:
        coord = LeaseCoordinator(root=Path(root), boot_id=boot)
        lease = coord.acquire(session_id=f"p-{os.getpid()}", agent_id="grok", paths=[path])
        q.put(("ok", lease.lease_id, lease.paths))
    except Exception as exc:  # noqa: BLE001
        q.put(("err", type(exc).__name__, str(exc)))


def test_concurrent_alias_claims_one_wins(tmp_path: Path):
    root = tmp_path / "coord"
    q: mp.Queue = mp.Queue()
    procs = [
        mp.Process(target=_acquire_worker, args=(str(root), "scripts/x.py", q, "boot-c")),
        mp.Process(target=_acquire_worker, args=(str(root), "./scripts/x.py", q, "boot-c")),
        mp.Process(target=_acquire_worker, args=(str(root), "scripts//x.py", q, "boot-c")),
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=10)
    results = [q.get(timeout=1) for _ in procs]
    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1, results
    assert len(errs) == 2, results
    assert oks[0][2] == ["scripts/x.py"]


def test_concurrent_disjoint_both_succeed(tmp_path: Path):
    root = tmp_path / "coord"
    q: mp.Queue = mp.Queue()
    procs = [
        mp.Process(target=_acquire_worker, args=(str(root), "docs/a.md", q, "boot-d")),
        mp.Process(target=_acquire_worker, args=(str(root), "docs/b.md", q, "boot-d")),
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=10)
    results = [q.get(timeout=1) for _ in procs]
    assert all(r[0] == "ok" for r in results), results


# --- B. durable TTL / boot id -------------------------------------------------


def test_ttl_bounds():
    with pytest.raises(ValueError):
        validate_ttl(0)
    with pytest.raises(ValueError):
        validate_ttl(10**9)


def test_utc_ttl_expires(tmp_path: Path):
    clock = {"t": 1_700_000_000.0}

    def now():
        return clock["t"]

    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-1", now_utc=now)
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"], ttl_s=1.0)
    assert a.expires_at_utc == clock["t"] + 1.0
    clock["t"] += 1.5
    # expired — new acquire allowed
    b = coord.acquire(session_id="s2", agent_id="codex", paths=["docs/a.md"], ttl_s=60)
    assert b.lease_id != a.lease_id


def test_heartbeat_extends_utc(tmp_path: Path):
    clock = {"t": 1_700_000_000.0}

    def now():
        return clock["t"]

    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-1", now_utc=now)
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"], ttl_s=10)
    clock["t"] += 5
    a2 = coord.heartbeat(a.lease_id, ttl_s=30)
    assert a2.expires_at_utc == clock["t"] + 30
    clock["t"] += 20
    with pytest.raises(RuntimeError, match="overlap"):
        coord.acquire(session_id="s2", agent_id="codex", paths=["docs/a.md"])


def test_boot_id_change_marks_stale(tmp_path: Path):
    clock = {"t": 1_700_000_000.0}
    coord1 = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-old", now_utc=lambda: clock["t"])
    a = coord1.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"], ttl_s=3600)
    # Simulate reboot: new coordinator with new boot id, same wall clock within TTL
    coord2 = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-new", now_utc=lambda: clock["t"] + 10)
    active = coord2.list_active()
    assert active == []
    recovered = coord2.recover_abandoned()
    assert any(r.get("lease_id") == a.lease_id for r in recovered)
    assert any(r.get("recovery_event") == "ABANDONED_BOOT_ID_CHANGED" for r in recovered)
    # Path free for new session — must not delete unrelated records silently
    b = coord2.acquire(session_id="s2", agent_id="codex", paths=["docs/a.md"], ttl_s=60)
    assert b.boot_id == "boot-new"


def test_v1_monotonic_lease_not_trusted_across_boundary(tmp_path: Path):
    """Pre-reboot style: persisted monotonic expires_at must not stay active."""
    root = tmp_path / "coord"
    leases = root / "leases"
    leases.mkdir(parents=True)
    # Craft a v1 record with huge monotonic expires (as if uptime was low at write).
    lid = "11111111-1111-1111-1111-111111111111"
    v1 = {
        "schema": "AgentFileLease@v1",
        "schema_version": 1,
        "lease_id": lid,
        "session_id": "old",
        "agent_id": "grok",
        "paths": ["docs/a.md"],
        "stores": [],
        "issued_at": 10.0,
        "expires_at": 10.0 + 1e9,  # monotonic fantasy
        "heartbeat_s": 60,
    }
    (leases / f"{lid}.json").write_text(json.dumps(v1), encoding="utf-8")
    coord = LeaseCoordinator(root=root, boot_id="boot-now", now_utc=lambda: 1_700_000_000.0)
    assert coord.list_active() == []
    recovered = coord.recover_abandoned()
    assert recovered and recovered[0]["recovery_event"] == "ABANDONED_SCHEMA_UPGRADE"
    # Peer session record was audited, not silently deleted without trail
    assert list((root / "abandoned").glob(f"{lid}.*"))


def test_clock_regression_abandons(tmp_path: Path):
    root = tmp_path / "coord"
    coord = LeaseCoordinator(root=root, boot_id="boot-1", now_utc=lambda: 1_700_000_100.0)
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"], ttl_s=60)
    # Corrupt expires < issued
    path = coord.leases_dir / f"{a.lease_id}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    d["expires_at_utc"] = d["issued_at_utc"] - 10
    d["expires_at"] = d["expires_at_utc"]
    path.write_text(json.dumps(d), encoding="utf-8")
    assert coord.list_active() == []
    recovered = coord.recover_abandoned()
    assert any(r.get("recovery_event") == "ABANDONED_CLOCK_REGRESSION" for r in recovered)


def test_release_refuses_other_session(tmp_path: Path):
    coord = LeaseCoordinator(root=tmp_path / "coord", boot_id="boot-1")
    a = coord.acquire(session_id="s1", agent_id="grok", paths=["docs/a.md"])
    with pytest.raises(RuntimeError, match="session_id mismatch"):
        coord.release(a.lease_id, session_id="s2")
    assert (coord.leases_dir / f"{a.lease_id}.json").is_file()
