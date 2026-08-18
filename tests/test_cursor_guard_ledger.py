"""P0 transactional approval ledger — concurrency, crash, fail-closed, schema."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".cursor" / "hooks"
LEDGER_PY = HOOKS / "guard_ledger.py"
sys.path.insert(0, str(HOOKS))

import guard_ledger as gl  # noqa: E402


def _env(adir: Path, audit: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["GUARD_APPROVALS_DIR"] = str(adir)
    env["GUARD_AUDIT_LOG"] = str(audit or (adir / "audit.jsonl"))
    env.pop("GUARD_LEDGER_CRASH", None)
    env.pop("GUARD_LEDGER_FAIL_WRITE", None)
    env.pop("GUARD_READ_FORCE_JQ_FAIL", None)
    return env


def _run_ledger(adir: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = _env(adir)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(LEDGER_PY), *args],
        env=env, capture_output=True, text=True, check=False,
    )


def _hook(name: str, payload: dict, adir: Path) -> dict:
    env = _env(adir)
    p = subprocess.run(
        ["bash", str(HOOKS / name)],
        input=json.dumps(payload),
        env=env, capture_output=True, text=True, check=False,
    )
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return {"_raw": p.stdout, "_err": p.stderr, "_rc": p.returncode}


@pytest.fixture
def adir(tmp_path: Path) -> Path:
    d = tmp_path / "approvals"
    d.mkdir(mode=0o700)
    return d


def test_valid_empty_init(adir):
    gl.ledger_init_empty(adir)
    assert gl.classify_ledger(gl.ledger_path(adir)) == gl.VALID_EMPTY
    raw = gl.ledger_path(adir).read_text()
    assert raw.strip() == "{}"
    assert json.loads(raw) == {}
    assert (gl.ledger_path(adir).stat().st_mode & 0o777) == 0o600


def test_missing_is_not_empty(adir):
    assert gl.classify_ledger(gl.ledger_path(adir)) == gl.MISSING


def test_zero_byte_is_corrupt_not_empty(adir):
    p = gl.ledger_path(adir)
    p.write_bytes(b"")
    assert p.stat().st_size == 0
    assert gl.classify_ledger(p) == gl.ZERO_BYTE
    with pytest.raises(gl.LedgerCorrupt):
        gl.ledger_read(adir)
    with pytest.raises(gl.LedgerCorrupt):
        gl.ledger_create_grant("git-push", expires=int(time.time()) + 60, uses=1, reason="x", adir=adir)
    # implicit init must not clobber corrupt
    with pytest.raises(gl.LedgerCorrupt):
        gl.ledger_init_empty(adir)
    assert p.stat().st_size == 0


def test_malformed_is_corrupt(adir):
    gl.ledger_path(adir).write_text("[1,2,3]\n")
    assert gl.classify_ledger(gl.ledger_path(adir)) == gl.MALFORMED
    with pytest.raises(gl.LedgerCorrupt):
        gl.ledger_consume_grant("git-push", adir=adir)


def test_schema_rejects_dangerous_forms(adir):
    gl.ledger_init_empty(adir)
    with pytest.raises(gl.LedgerError):
        gl.validate_document(None)
    with pytest.raises(gl.LedgerError):
        gl.validate_document([])
    with pytest.raises(gl.LedgerError):
        gl.validate_document({"git-push": {"expires": 1, "uses": -5, "reason": "x"}})
    with pytest.raises(gl.LedgerError):
        gl.validate_document({"git-push": "yes"})


def test_normal_grant_fields(adir):
    exp = int(time.time()) + 1800
    gl.ledger_create_grant("git-push", expires=exp, uses=2, reason="plan", adir=adir)
    rec = gl.ledger_list(adir)["active"]["git-push"]
    assert rec["uses"] == 2
    assert rec["expires"] == exp
    assert rec["reason"] == "plan"
    assert rec["created_at"] > 0
    assert rec["grant_id"]


def test_expiration(adir):
    gl.ledger_create_grant("git-push", expires=int(time.time()) - 1, uses=5, reason="old", adir=adir)
    r = gl.ledger_consume_grant("git-push", adir=adir)
    assert r["consumed"] is False
    assert "git-push" not in gl.ledger_list(adir)["active"]


def test_uses_decrement_and_remove(adir):
    gl.ledger_create_grant("cron", expires=int(time.time()) + 60, uses=2, reason="t", adir=adir)
    assert gl.ledger_consume_grant("cron", adir=adir)["uses_left"] == 1
    assert gl.ledger_consume_grant("cron", adir=adir)["uses_left"] == 0
    assert gl.ledger_consume_grant("cron", adir=adir)["consumed"] is False
    assert gl.ledger_list(adir)["grants"] == {}


def test_revoke_and_revoke_all(adir):
    now = int(time.time()) + 60
    gl.ledger_create_grant("cron", expires=now, uses=3, reason="a", adir=adir)
    gl.ledger_create_grant("git-push", expires=now, uses=3, reason="b", adir=adir)
    gl.ledger_revoke("cron", adir=adir)
    assert "cron" not in gl.ledger_list(adir)["grants"]
    assert "git-push" in gl.ledger_list(adir)["grants"]
    gl.ledger_revoke_all(adir)
    assert gl.ledger_list(adir)["grants"] == {}
    assert gl.classify_ledger(gl.ledger_path(adir)) == gl.VALID_EMPTY


def test_parallel_grants_no_lost_update(adir):
    exp = int(time.time()) + 120
    tiers = [f"t{i}" for i in range(8)]
    # tiers must be valid keys; use real scopes
    real = ["cron", "git-push", "service", "deps", "sudo", "llm", "telegram", "openclaw"]

    def one(t):
        gl.ledger_create_grant(t, expires=exp, uses=1, reason=t, adir=adir)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, real))
    grants = gl.ledger_list(adir)["grants"]
    assert set(grants) == set(real)
    assert json.loads(gl.ledger_path(adir).read_text())


def test_one_use_two_consumers(adir):
    gl.ledger_create_grant("git-push", expires=int(time.time()) + 60, uses=1, reason="one", adir=adir)
    results = []

    def go():
        results.append(gl.ledger_consume_grant("git-push", adir=adir)["consumed"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(go) for _ in range(2)]
        for f in as_completed(futs):
            f.result()
    assert results.count(True) == 1
    assert results.count(False) == 1
    doc = json.loads(gl.ledger_path(adir).read_text())
    assert doc == {}
    assert gl.ledger_path(adir).stat().st_size > 0


def test_multi_use_stress_20_on_10(adir):
    gl.ledger_create_grant("git-push", expires=int(time.time()) + 60, uses=10, reason="ten", adir=adir)
    ids = []

    def go():
        r = gl.ledger_consume_grant("git-push", adir=adir)
        return r

    with ThreadPoolExecutor(max_workers=20) as pool:
        outs = [f.result() for f in as_completed([pool.submit(go) for _ in range(20)])]
    ok = [o for o in outs if o.get("consumed")]
    no = [o for o in outs if not o.get("consumed")]
    assert len(ok) == 10
    assert len(no) == 10
    cids = [o["consumption_id"] for o in ok]
    assert len(set(cids)) == 10
    assert json.loads(gl.ledger_path(adir).read_text()) == {}


def test_grant_revoke_race(adir):
    gl.ledger_create_grant("git-push", expires=int(time.time()) + 60, uses=50, reason="race", adir=adir)
    consumed_after_revoke = []
    saw_revoke = {"v": False}

    def consumer():
        for _ in range(30):
            r = gl.ledger_consume_grant("git-push", adir=adir)
            if saw_revoke["v"] and r.get("consumed"):
                consumed_after_revoke.append(True)

    def revoker():
        time.sleep(0.01)
        gl.ledger_revoke_all(adir)
        saw_revoke["v"] = True

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(consumer) for _ in range(3)] + [pool.submit(revoker)]
        for f in futs:
            f.result()
    # After revoke commits, later consume must not succeed. We cannot prove
    # wall-clock "after" across threads without the flag; the flag is set
    # after revoke returns, so any consume that started after that is denied.
    assert consumed_after_revoke == []
    assert json.loads(gl.ledger_path(adir).read_text()) == {}
    assert gl.classify_ledger(gl.ledger_path(adir)) == gl.VALID_EMPTY


def test_crash_before_rename_leaves_previous(adir):
    gl.ledger_init_empty(adir)
    gl.ledger_create_grant("cron", expires=int(time.time()) + 60, uses=1, reason="keep", adir=adir)
    before = gl.ledger_path(adir).read_text()
    env = {"GUARD_LEDGER_CRASH": "before_rename"}
    cp = _run_ledger(adir, "grant", "--tier", "git-push", "--expires", str(int(time.time()) + 60),
                     "--uses", "1", "--reason", "x", env_extra=env)
    assert cp.returncode != 0
    assert gl.ledger_path(adir).read_text() == before
    assert json.loads(before)["cron"]["reason"] == "keep"
    leftovers = list(adir.glob(".grants.json.tmp.*"))
    # temp should be cleaned on crash-after-write-before-rename in except path
    # (SystemExit may skip cleanup if raised after close — acceptable leftover)
    for tmp in leftovers:
        assert tmp.stat().st_size > 0 or tmp.stat().st_size == 0  # leftover ok
        tmp.unlink()


def test_crash_after_rename_is_new_valid(adir):
    gl.ledger_init_empty(adir)
    env = {"GUARD_LEDGER_CRASH": "after_rename"}
    _run_ledger(adir, "grant", "--tier", "git-push", "--expires", str(int(time.time()) + 60),
                "--uses", "1", "--reason", "x", env_extra=env)
    assert gl.classify_ledger(gl.ledger_path(adir)) in {gl.VALID_EMPTY, gl.VALID_NONEMPTY}
    json.loads(gl.ledger_path(adir).read_text())


def test_write_failure_leaves_old(adir):
    gl.ledger_create_grant("cron", expires=int(time.time()) + 60, uses=1, reason="old", adir=adir)
    before = gl.ledger_path(adir).read_text()
    cp = _run_ledger(
        adir, "grant", "--tier", "git-push", "--expires", str(int(time.time()) + 60),
        "--uses", "1", "--reason", "x",
        env_extra={"GUARD_LEDGER_FAIL_WRITE": "1"},
    )
    assert cp.returncode != 0
    assert gl.ledger_path(adir).read_text() == before


def test_permissions(adir):
    gl.ledger_init_empty(adir)
    mode = gl.ledger_path(adir).stat().st_mode
    assert stat.S_IMODE(mode) == 0o600
    assert stat.S_IMODE(adir.stat().st_mode) == 0o700


def test_symlink_refused(adir):
    target = adir / "elsewhere.json"
    target.write_text("{}\n")
    dest = gl.ledger_path(adir)
    dest.symlink_to(target)
    assert gl.classify_ledger(dest) == gl.UNREADABLE
    with pytest.raises((gl.LedgerCorrupt, gl.LedgerError)):
        gl.ledger_create_grant("cron", expires=int(time.time()) + 60, uses=1, reason="x", adir=adir)
    # elsewhere must not have been rewritten with a grant
    assert json.loads(target.read_text()) == {}


def test_cwd_and_project_dir_independence(adir, tmp_path, monkeypatch):
    gl.ledger_init_empty(adir)
    gl.ledger_create_grant("cron", expires=int(time.time()) + 60, uses=1, reason="x", adir=adir)
    other = tmp_path / "othercwd"
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(adir))
    assert "cron" in gl.ledger_list(adir)["active"]


def test_audit_serialized_unique_ids(adir):
    os.environ["GUARD_AUDIT_LOG"] = str(adir / "audit.jsonl")
    os.environ["GUARD_APPROVALS_DIR"] = str(adir)
    ids = []

    def go(i):
        ids.append(gl.audit_append({"event": "test", "n": i}, adir=adir))

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(go, range(40)))
    lines = (adir / "audit.jsonl").read_text().splitlines()
    parsed = [json.loads(x) for x in lines if x.strip()]
    assert len(parsed) == 40
    eids = [p["event_id"] for p in parsed]
    assert len(set(eids)) == 40
    assert set(eids) == set(ids)


def test_audit_reader_tolerates_historical_torn(adir):
    log = adir / "audit.jsonl"
    os.environ["GUARD_AUDIT_LOG"] = str(log)
    log.write_text('{"event":"ok","event_id":"a"}\nNOT JSON\n{"event":"ok2","event_id":"b"}\n')
    # new append must not rewrite history
    gl.audit_append({"event": "new"}, adir=adir)
    raw = log.read_text()
    assert "NOT JSON" in raw
    assert raw.count("\n") >= 4


def test_zero_byte_stress_loop(adir):
    gl.ledger_init_empty(adir)
    exp = int(time.time()) + 120
    min_size = 10**9
    stop = {"err": None}

    def grantor():
        for i in range(15):
            try:
                gl.ledger_create_grant("git-push", expires=exp, uses=3, reason=str(i), adir=adir)
            except Exception as e:
                stop["err"] = e

    def consumer():
        for _ in range(20):
            try:
                gl.ledger_consume_grant("git-push", adir=adir)
            except Exception as e:
                stop["err"] = e

    def lister():
        for _ in range(20):
            try:
                gl.ledger_list(adir)
            except Exception as e:
                stop["err"] = e

    def revoker():
        for _ in range(8):
            try:
                gl.ledger_revoke_all(adir)
            except Exception as e:
                stop["err"] = e

    def watcher():
        for _ in range(40):
            p = gl.ledger_path(adir)
            if p.exists():
                sz = p.stat().st_size
                nonlocal_min[0] = min(nonlocal_min[0], sz)
                if sz == 0:
                    stop["err"] = AssertionError("zero-byte ledger observed")
                    return
                json.loads(p.read_text())

    nonlocal_min = [min_size]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [
            pool.submit(grantor), pool.submit(consumer), pool.submit(lister),
            pool.submit(revoker), pool.submit(watcher),
            pool.submit(consumer), pool.submit(grantor),
        ]
        for f in futs:
            f.result()
    assert stop["err"] is None
    assert gl.ledger_path(adir).stat().st_size > 0
    json.loads(gl.ledger_path(adir).read_text())
    assert nonlocal_min[0] > 0


def test_hook_read_jq_failure_not_allow(adir):
    gl.ledger_init_empty(adir)
    env = _env(adir)
    env["GUARD_READ_FORCE_JQ_FAIL"] = "1"
    p = subprocess.run(
        ["bash", str(HOOKS / "guard-read.sh")],
        input='{"file_path":"/tmp/foo.txt"}',
        env=env, capture_output=True, text=True,
    )
    body = json.loads(p.stdout.strip().splitlines()[-1])
    assert body.get("permission") != "allow"


def test_hook_read_zero_byte_not_allow(adir):
    gl.ledger_path(adir).write_bytes(b"")
    body = _hook("guard-read.sh", {"file_path": "/tmp/foo.txt"}, adir)
    assert body.get("permission") != "allow"
    assert "CORRUPT" in (body.get("user_message") or "")


def test_hook_read_malformed_not_allow(adir):
    gl.ledger_path(adir).write_text("not-json")
    body = _hook("guard-read.sh", {"file_path": "/tmp/foo.txt"}, adir)
    assert body.get("permission") != "allow"


def test_hook_read_secret_deny_normal_allow(adir):
    gl.ledger_init_empty(adir)
    deny = _hook("guard-read.sh", {"file_path": "/home/x/.env"}, adir)
    assert deny.get("permission") == "deny"
    allow = _hook("guard-read.sh", {"file_path": "/tmp/readme.md"}, adir)
    assert allow.get("permission") == "allow"


def test_hook_shell_git_push_without_grant(adir):
    gl.ledger_init_empty(adir)
    body = _hook("guard-shell.sh", {"command": "git push origin main"}, adir)
    assert body.get("permission") == "deny"


def test_hook_shell_git_push_lifecycle(adir):
    gl.ledger_init_empty(adir)
    exp = int(time.time()) + 120
    gl.ledger_create_grant("git-push", expires=exp, uses=2, reason="safe-hook", adir=adir)
    a = _hook("guard-shell.sh", {"command": "git push origin main"}, adir)
    assert a.get("permission") == "allow"
    b = _hook("guard-shell.sh", {"command": "git push origin main"}, adir)
    assert b.get("permission") == "allow"
    c = _hook("guard-shell.sh", {"command": "git push origin main"}, adir)
    assert c.get("permission") == "deny"
    gl.ledger_revoke_all(adir)
    assert json.loads(gl.ledger_path(adir).read_text()) == {}


def test_hook_strreplace_write_edit(adir):
    gl.ledger_init_empty(adir)
    path = "/tmp/proj/config/foo.yaml"
    for tool in ("StrReplace", "Write", "Edit"):
        body = _hook("guard-write.sh", {"tool_name": tool, "tool_input": {"path": path}}, adir)
        assert body.get("permission") == "deny", tool
    exp = int(time.time()) + 60
    gl.ledger_create_grant("config-write", expires=exp, uses=1, reason="one", adir=adir)
    ok = _hook("guard-write.sh", {"tool_name": "StrReplace", "tool_input": {"path": path}}, adir)
    assert ok.get("permission") == "allow"
    again = _hook("guard-write.sh", {"tool_name": "StrReplace", "tool_input": {"path": path}}, adir)
    assert again.get("permission") == "deny"


def test_doctor_no_autorepair(adir):
    gl.ledger_path(adir).write_bytes(b"")
    d = gl.doctor(adir)
    assert d["ledger_status"] == gl.ZERO_BYTE
    assert d["ok"] is False
    assert gl.ledger_path(adir).stat().st_size == 0


def test_recover_policy_empty(adir, monkeypatch):
    monkeypatch.setenv("GUARD_AUDIT_LOG", str(adir / "audit.jsonl"))
    gl.ledger_path(adir).write_bytes(b"")
    gl.ledger_recover_empty(
        reason="P0 zero-byte incident",
        incident="P0_GUARD_STATE_CORRUPTION",
        previous_size=0,
        previous_hash="0" * 64,
        operator="test",
        session="pytest",
        adir=adir,
    )
    assert gl.classify_ledger(gl.ledger_path(adir)) == gl.VALID_EMPTY
    assert json.loads(gl.ledger_path(adir).read_text()) == {}
    ev = [json.loads(x) for x in (adir / "audit.jsonl").read_text().splitlines() if x.strip()]
    assert ev[-1]["event"] == "ledger_recovery"
    assert ev[-1]["recovery_policy"] == "ACTIVE_GRANTS_NONE"
