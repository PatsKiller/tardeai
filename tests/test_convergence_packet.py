#!/usr/bin/env python3
"""Convergence packet — safety-invariant tests (Part F). Proves the packet CANNOT deploy from the
live checkout, CANNOT run CONNECT before MOUNT or without a separate ack, classifies the agent-runtime
contract exactly, and never leaks a secret. Pure — no host mutation."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONV = ROOT / "scripts" / "convergence"
sys.path.insert(0, str(ROOT / "scripts" / "convergence"))

import convergence_lib as cl  # noqa: E402
from convergence_lib import (validate_build_source, build_meta, can_run_connect, classify_agent_runtime,
                             mount_contract_ok, connect_contract_ok, verify_markers, redact,
                             contains_secret, BuildSourceError, PhaseGateError, SOURCE_MODE_EXACT,
                             SOURCE_MODE_LIVE, AGENT_RUNTIME_CONTRACT)

SHA = "21366635ce6e2a8610e0ea1ea716036016df299b"  # current-main pin (Front 0); a valid 40-char fixture
ZERO_AUTH = {"mutation": False, "provider_call": False, "service_control": False,
             "schedule_change": False, "financial_action": False}


# ── build source: staged exact-ref only ──
def test_build_source_staged_ok():
    validate_build_source(SOURCE_MODE_EXACT)   # no raise

def test_build_source_live_checkout_forbidden():
    with pytest.raises(BuildSourceError):
        validate_build_source(SOURCE_MODE_LIVE)
    with pytest.raises(BuildSourceError):
        validate_build_source("whatever")

def test_build_meta_requires_full_40_char_commit():
    m = build_meta(SHA, {"agent_runtime": "v1"})
    assert m["source_commit"] == SHA and m["frontend_build_source"] == SOURCE_MODE_EXACT
    assert m["live_checkout_build_input"] == "NONE"
    for bad in ("03bbf00d", "", "xyz", SHA[:39]):
        with pytest.raises(BuildSourceError):
            build_meta(bad, {})


# ── two-phase gating ──
def test_connect_blocked_before_mount():
    with pytest.raises(PhaseGateError):
        can_run_connect(mount_passed=False, connect_ack=True)

def test_connect_requires_separate_ack():
    with pytest.raises(PhaseGateError):
        can_run_connect(mount_passed=True, connect_ack=False)

def test_connect_allowed_only_when_both():
    assert can_run_connect(mount_passed=True, connect_ack=True) is True


# ── agent-runtime contract classification ──
def test_classify_404_mount_absent():
    assert classify_agent_runtime(404, None) == "MOUNT_ABSENT"

def test_classify_503_mounted_disconnected():
    body = {"read_only": True, "connected": False, "authority": ZERO_AUTH}
    assert classify_agent_runtime(503, body) == "MOUNTED_DISCONNECTED"
    assert mount_contract_ok(503, body)

def test_classify_200_connected_read_only():
    body = {"read_only": True, "connected": True, "authority": ZERO_AUTH,
            "reader_role": "agentic_runtime_reader", "contract": AGENT_RUNTIME_CONTRACT}
    assert classify_agent_runtime(200, body) == "CONNECTED_READ_ONLY"
    assert connect_contract_ok(200, body, "agentic_runtime_reader")

def test_connect_contract_rejects_wrong_role_or_authority():
    good = {"read_only": True, "connected": True, "authority": ZERO_AUTH, "reader_role": "agentic_runtime_reader"}
    assert not connect_contract_ok(200, {**good, "reader_role": "postgres"}, "agentic_runtime_reader")
    bad_auth = {**good, "authority": {**ZERO_AUTH, "mutation": True}}
    assert classify_agent_runtime(200, bad_auth) == "CONNECTED_MALFORMED"
    assert not connect_contract_ok(200, bad_auth, "agentic_runtime_reader")

def test_mount_contract_rejects_connected_true():
    # a 200/connected must NOT satisfy the MOUNT (disconnected) contract
    assert not mount_contract_ok(200, {"read_only": True, "connected": True, "authority": ZERO_AUTH})


# ── marker verification ──
def test_verify_markers():
    txt = "…ADMITTED…RESEARCH_ONLY…QUARANTINED…ELIGIBLE NOW…"
    r = verify_markers(txt, cl.WATCH_MARKERS)
    assert r["ok"] and not r["missing"]
    r2 = verify_markers("only ADMITTED here", cl.WATCH_MARKERS)
    assert not r2["ok"] and "QUARANTINED" in r2["missing"]


# ── secret redaction ──
def test_redact_dsn_and_secrets():
    samples = [
        "DATABASE_URL=postgresql://agentic_runtime_reader:hunter2@host:5433/db",
        "PGPASSWORD=supersecret123",
        "api_key: sk-abc123def456",
        "APCA-API-KEY-ID=PKABCDEFGH",
    ]
    for s in samples:
        out = redact(s)
        assert "[REDACTED]" in out
        assert not contains_secret(out)          # nothing sensitive survives
        assert "hunter2" not in out and "supersecret123" not in out and "sk-abc123def456" not in out

def test_redact_leaves_clean_text():
    clean = "agent_runtime_api_state|CONNECTED_READ_ONLY connected=true read_only=true"
    assert redact(clean) == clean and not contains_secret(clean)


# ── rollback manifest ──
def test_rollback_manifest_shape():
    m = cl.rollback_manifest(backend_hashes={"scripts/portfolio_server.py": "abc"}, static_backup="/b/x.tgz",
                             static_build_meta={"source_commit": SHA}, reader_env_present=True,
                             reader_env_mode="600", dropin_present=True, service_state="active",
                             watch_packets={"w1": "h1"}, defense_snapshots={"d1": "h2"})
    assert m["manifest_version"] == "convergence-rollback-v1"
    assert m["reader"]["env_mode"] == "600" and m["service_state"] == "active"
    assert m["backend_hashes"] and m["watch_packets"] and m["defense_snapshots"]


# ── static install / swap / restore — pure decisions ──
def test_swap_parity_hashed_assets_are_superseded_not_dropped():
    live = ["index.html", "build-meta.json", "assets/index-OLD.js", "assets/index-x.css"]
    cand = ["index.html", "build-meta.json", "assets/index-NEW.js", "assets/index-x.css"]
    p = cl.swap_parity(live, cand)
    assert p["ok"] and p["dropped"] == [] and "assets/index-OLD.js" in p["superseded_assets"]

def test_swap_parity_blocks_a_dropped_served_file():
    live = ["index.html", "build-meta.json", "assets/index-OLD.js", "favicon.ico"]
    cand = ["index.html", "build-meta.json", "assets/index-NEW.js"]
    p = cl.swap_parity(live, cand)
    assert not p["ok"] and p["dropped"] == ["favicon.ico"]

def test_dist_shape_ok():
    assert cl.dist_shape_ok(["index.html", "build-meta.json", "assets/index-x.js"])
    assert not cl.dist_shape_ok(["index.html", "assets/index-x.js"])   # no build-meta
    assert not cl.dist_shape_ok(["index.html", "build-meta.json"])     # no asset

def test_install_precheck_accepts_list_or_dict_contracts():
    cl.install_precheck({"source_commit": SHA, "frontend_build_source": SOURCE_MODE_EXACT,
                         "contracts": [AGENT_RUNTIME_CONTRACT, "watch-decision-desk-v5"]})
    cl.install_precheck({"source_commit": SHA, "frontend_build_source": SOURCE_MODE_EXACT,
                         "contracts": {"agent_runtime": AGENT_RUNTIME_CONTRACT}})

def test_install_precheck_rejects_bad_provenance():
    with pytest.raises(cl.BuildSourceError):     # short SHA
        cl.install_precheck({"source_commit": "03bbf00d", "frontend_build_source": SOURCE_MODE_EXACT,
                             "contracts": [AGENT_RUNTIME_CONTRACT]})
    with pytest.raises(cl.BuildSourceError):     # live-checkout build input
        cl.install_precheck({"source_commit": SHA, "frontend_build_source": SOURCE_MODE_LIVE,
                             "contracts": [AGENT_RUNTIME_CONTRACT]})
    with pytest.raises(cl.BuildSourceError):     # no agent-runtime contract declared
        cl.install_precheck({"source_commit": SHA, "frontend_build_source": SOURCE_MODE_EXACT,
                             "contracts": ["watch-decision-desk-v5"]})

def test_smoke_ok():
    assert cl.smoke_ok({"/v3": 200, "/v3/agents": 200})
    assert not cl.smoke_ok({"/v3": 200, "/v3/agents": 503})
    assert not cl.smoke_ok({})                    # nothing probed is not a pass

def test_backup_dir_name():
    assert cl.backup_dir_name("20260727_205318") == "cc-dist-20260727_205318"
    with pytest.raises(cl.ConvergenceError):
        cl.backup_dir_name("nope")


# ── static install / restore — real filesystem apply→auto-rollback→restore against throwaway dirs ──
def _write_dist(path: Path, source_commit: str, js: str, extra_files: tuple[str, ...] = ()):
    (path / "assets").mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text(f'<script src="/v3/assets/{js}"></script>'
                                     '<link href="/v3/assets/index-x.css">')
    # every required bundle marker present so the marker gate passes
    (path / "assets" / js).write_text("ADMITTED QUARANTINED ELIGIBLE NO DECISION agent-runtime hub")
    (path / "assets" / "index-x.css").write_text(".x{}")
    (path / "build-meta.json").write_text(json.dumps({
        "source_commit": source_commit, "frontend_build_source": "STAGED_EXACT_REF",
        "live_checkout_build_input": "NONE",
        "contracts": [AGENT_RUNTIME_CONTRACT, "watch-decision-desk-v5"]}))
    for f in extra_files:
        (path / f).write_text("served")

def _run(script: str, args: list[str], **env):
    e = {**os.environ, **{k: str(v) for k, v in env.items()}}
    return subprocess.run(["bash", str(CONV / script), *args], capture_output=True, text=True, env=e)

class _Serve:
    """Tiny in-process HTTP server over a directory so curl gets real 200s (file:// yields code 000)."""
    def __init__(self, directory):
        import http.server, functools
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
    def __enter__(self):
        import threading
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self
    def __exit__(self, *a):
        self.httpd.shutdown()

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_static_install_then_restore_cycle(tmp_path):
    live, cand, backups = tmp_path / "dist", tmp_path / "cand", tmp_path / "backups"
    _write_dist(live, "b" * 40, "index-OLD1.js")
    _write_dist(cand, "a" * 40, "index-NEW1.js")

    r = _run("static_install.sh", [str(cand), "--apply"],
             CC_DIST=live, BACKUP_ROOT=backups, SKIP_SMOKE="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "INSTALL_APPLIED_AND_VERIFIED" in r.stdout
    # live is now the candidate
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "a" * 40
    # the original was archived to a backup
    bks = [p for p in backups.glob("cc-dist-*") if p.is_dir()]
    assert len(bks) == 1
    assert json.load(open(bks[0] / "build-meta.json"))["source_commit"] == "b" * 40

    # restore the archived backup atomically, bound to its manifest
    manifest = next(backups.glob("cc-dist-*.manifest.json"))
    r2 = _run("rollback.sh", ["--restore", str(bks[0]), "--apply", "--manifest", str(manifest)],
              CC_DIST=live, SKIP_SMOKE="1")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "RESTORE_APPLIED" in r2.stdout and "restore_precheck|OK" in r2.stdout
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "b" * 40  # original back

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_static_install_auto_rolls_back_on_smoke_failure(tmp_path):
    live, cand, backups = tmp_path / "dist", tmp_path / "cand", tmp_path / "backups"
    _write_dist(live, "b" * 40, "index-OLD2.js")
    _write_dist(cand, "a" * 40, "index-NEW2.js")
    # smoke against an unreachable base → every route 000 → must auto-roll-back
    r = _run("static_install.sh", [str(cand), "--apply"],
             CC_DIST=live, BACKUP_ROOT=backups, SMOKE_BASE="http://127.0.0.1:1", SMOKE_ROUTES="/v3")
    assert r.returncode != 0
    assert "INSTALL_VERIFY_FAILED_ROLLED_BACK" in r.stdout
    # live restored to the ORIGINAL despite the attempted swap
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "b" * 40

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_static_install_blocks_candidate_that_drops_a_served_file(tmp_path):
    live, cand = tmp_path / "dist", tmp_path / "cand"
    _write_dist(live, "b" * 40, "index-OLD3.js", extra_files=("favicon.ico",))  # live serves favicon
    _write_dist(cand, "a" * 40, "index-NEW3.js")                                # candidate omits it
    r = _run("static_install.sh", [str(cand), "--apply"], CC_DIST=live, SKIP_SMOKE="1")
    assert r.returncode != 0 and "BLOCKED_GATE_FAILED" in r.stdout
    # live untouched
    assert (live / "favicon.ico").exists()
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "b" * 40

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_static_install_rejects_bad_provenance_candidate(tmp_path):
    live, cand = tmp_path / "dist", tmp_path / "cand"
    _write_dist(live, "b" * 40, "index-OLD4.js")
    _write_dist(cand, "a" * 40, "index-NEW4.js")
    (cand / "build-meta.json").write_text(json.dumps({          # short SHA, no exact-ref proof
        "source_commit": "03bbf00d", "frontend_build_source": "LIVE_CHECKOUT", "contracts": []}))
    r = _run("static_install.sh", [str(cand), "--apply"], CC_DIST=live, SKIP_SMOKE="1")
    assert r.returncode != 0 and "BLOCKED_GATE_FAILED" in r.stdout
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "b" * 40

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_restore_rejects_an_invalid_backup(tmp_path):
    live, junk = tmp_path / "dist", tmp_path / "junk"
    _write_dist(live, "b" * 40, "index-OLD5.js")
    junk.mkdir()
    (junk / "index.html").write_text("only an index, not a dist")   # no build-meta, no asset
    r = _run("rollback.sh", ["--restore", str(junk), "--apply"], CC_DIST=live)
    assert r.returncode != 0 and "BLOCKED_BACKUP_INVALID" in r.stdout
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "b" * 40  # untouched


# ── post-install/restore verification + restore binding — pure decisions ──
def test_served_build_ok():
    assert cl.served_build_ok({"source_commit": SHA}, SHA)
    assert not cl.served_build_ok({"source_commit": "b" * 40}, SHA)   # stale/cached served bundle
    assert not cl.served_build_ok(None, SHA) and not cl.served_build_ok({}, SHA)

def test_read_plane_ok_reuses_connect_contract():
    good = {"read_only": True, "connected": True, "authority": ZERO_AUTH, "reader_role": "agentic_runtime_reader"}
    assert cl.read_plane_ok(200, good, "agentic_runtime_reader")
    assert not cl.read_plane_ok(503, good, "agentic_runtime_reader")            # disconnected
    assert not cl.read_plane_ok(200, {**good, "authority": {**ZERO_AUTH, "mutation": True}},
                                "agentic_runtime_reader")                        # gained authority

def test_restore_binding_ok_and_failures():
    meta = {"source_commit": "b" * 40}
    cl.restore_binding_ok(meta)                                                  # no constraints → ok
    cl.restore_binding_ok(meta, expected_commit="b" * 40)                        # matches → ok
    cl.restore_binding_ok(meta, expected_dir_hash="h1", actual_dir_hash="h1")    # hash matches → ok
    with pytest.raises(cl.ConvergenceError):
        cl.restore_binding_ok(meta, expected_commit="a" * 40)                    # wrong commit
    with pytest.raises(cl.ConvergenceError):
        cl.restore_binding_ok(meta, expected_dir_hash="h1", actual_dir_hash="h2")  # tampered backup
    # a legacy/unprovenanced backup is still restorable when no expectation is bound
    cl.restore_binding_ok({}, )

def test_install_manifest_shape():
    m = cl.install_manifest(stamp="20260727_205318", backup_dir="/b/cc-dist-x",
                            backup_source_commit="b" * 40, backup_dir_hash="deadbeef",
                            candidate_source_commit=SHA)
    assert m["manifest_version"] == "convergence-install-v1"
    assert m["backup_dir_hash"] == "deadbeef" and m["candidate_source_commit"] == SHA


# ── true atomic directory exchange ──
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_dirswap_atomic_exchange(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(); b.mkdir()
    (a / "mark").write_text("I-am-A")
    (b / "mark").write_text("I-am-B")
    r = subprocess.run([sys.executable, str(CONV / "_dirswap.py"), "exchange", str(a), str(b)],
                       capture_output=True, text=True)
    if r.returncode == 3:
        pytest.skip("RENAME_EXCHANGE unsupported on this filesystem")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (a / "mark").read_text() == "I-am-B" and (b / "mark").read_text() == "I-am-A"  # exchanged


# ── install verification auto-rollback + restore binding, via the real shell scripts ──
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_install_auto_rolls_back_on_stale_served_build_meta(tmp_path):
    live, cand, backups = tmp_path / "dist", tmp_path / "cand", tmp_path / "backups"
    _write_dist(live, "b" * 40, "index-OLD6.js")
    _write_dist(cand, "a" * 40, "index-NEW6.js")
    # the "server" reports a DIFFERENT (stale) commit than the candidate → verify must roll back
    stale = tmp_path / "served-meta.json"
    stale.write_text(json.dumps({"source_commit": "c" * 40}))
    r = _run("static_install.sh", [str(cand), "--apply"], CC_DIST=live, BACKUP_ROOT=backups,
             SMOKE_ROUTES="", VERIFY_META_URL=f"file://{stale}", VERIFY_AGENT_URL="none")
    assert r.returncode != 0
    assert "verify_served_meta|MISMATCH" in r.stdout and "INSTALL_VERIFY_FAILED_ROLLED_BACK" in r.stdout
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "b" * 40  # rolled back

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_install_verifies_served_meta_and_read_plane_ok(tmp_path):
    live, cand, backups = tmp_path / "dist", tmp_path / "cand", tmp_path / "backups"
    _write_dist(live, "b" * 40, "index-OLD7.js")
    _write_dist(cand, "a" * 40, "index-NEW7.js")
    srv = tmp_path / "srv"; srv.mkdir()
    (srv / "served-meta.json").write_text(json.dumps({"source_commit": "a" * 40}))
    (srv / "agent.json").write_text(json.dumps({"read_only": True, "connected": True,
        "authority": {"mutation": False, "provider_call": False, "service_control": False,
                      "schedule_change": False, "financial_action": False},
        "reader_role": "agentic_runtime_reader"}))
    with _Serve(srv) as s:
        r = _run("static_install.sh", [str(cand), "--apply"], CC_DIST=live, BACKUP_ROOT=backups,
                 SMOKE_ROUTES="", VERIFY_META_URL=f"{s.base}/served-meta.json",
                 VERIFY_AGENT_URL=f"{s.base}/agent.json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "verify_served_meta|OK" in r.stdout and "verify_read_plane|OK" in r.stdout
    assert "INSTALL_APPLIED_AND_VERIFIED" in r.stdout
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "a" * 40

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_restore_refuses_when_expected_commit_mismatches(tmp_path):
    live, backup = tmp_path / "dist", tmp_path / "backup"
    _write_dist(live, "a" * 40, "index-CUR.js")
    _write_dist(backup, "b" * 40, "index-BK.js")     # backup is commit b...
    r = _run("rollback.sh", ["--restore", str(backup), "--apply", "--expect-commit", "d" * 40],
             CC_DIST=live, SKIP_SMOKE="1")            # ...but we demand commit d -> refuse
    assert r.returncode != 0 and "BLOCKED_BACKUP_INVALID" in r.stdout
    assert json.load(open(live / "build-meta.json"))["source_commit"] == "a" * 40  # live untouched


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
