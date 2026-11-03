"""Fixer-side key handoff for the DeepSeek provider (2026-11-03).

Source-only proof: a fake key file and a fake CLI. No real key is read, no network, no bwrap needed.
This host's bubblewrap 0.11.1 has no --preserve-fds, so the key crosses the boundary as the FIRST LINE of
stdin and the launcher seals it in a memfd: never in the env, never a path, never argv.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import self_heal_fixer as FX  # noqa: E402
from lib import self_heal_deepseek_launch as L  # noqa: E402


def _attempt(tmp_path, provider):
    from datetime import datetime, timezone
    cfg = {
        "repo": {"repo_root": str(tmp_path / "repo"), "python": sys.executable,
                 "worktree_root": str(tmp_path / "wt"), "branch_prefix": "shf/"},
        "claude": {"bin": str(tmp_path / "claude"), "timeout_s": 5, "provider": provider,
                   "env_names": ["HOME", "PATH"]},
        "agent_sandbox": {"enabled": False},
    }
    return FX.Attempt({"job_id": "shf-test", "lane": "test", "signature": "sig-0123456789"},
                      {"base_sha": "0" * 40}, cfg=cfg, environ={"HOME": str(tmp_path)},
                      now=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc), evidence_dir=tmp_path,
                      may_push=False, backend="claude_cli")


def test_the_key_is_read_on_the_host_and_a_symlink_is_refused(tmp_path):
    key = tmp_path / "deepseek.key"
    key.write_bytes(b"proof-fake-not-a-key\n")
    assert _attempt(tmp_path, {"name": "deepseek", "key_file": str(key)})._read_provider_key() == b"proof-fake-not-a-key"
    link = tmp_path / "planted.key"
    link.symlink_to(key)
    assert _attempt(tmp_path, {"name": "deepseek", "key_file": str(link)})._read_provider_key() is None
    assert _attempt(tmp_path, {"name": "deepseek", "key_file": str(tmp_path / "absent")})._read_provider_key() is None
    multi = tmp_path / "multi.key"
    multi.write_bytes(b"two\nlines")
    assert _attempt(tmp_path, {"name": "deepseek", "key_file": str(multi)})._read_provider_key() is None


def test_the_key_line_precedes_the_prompt_on_stdin(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(FX, "run", lambda cmd, **kw: seen.update(kw) or {"rc": 0, "out": "", "err": ""})
    prov = {"name": "deepseek", "launcher": str(tmp_path / "l.py"), "key_file": str(tmp_path / "k")}
    a = _attempt(tmp_path, prov)
    a.py = sys.executable
    a.agent_prefix = ["bwrap"]          # sandbox off, but the launch chain is what is under test
    a.key_line = b"proof-fake-not-a-key"
    a.run_agent([str(tmp_path / "claude")], "THE PROMPT")
    assert seen["stdin"] == "proof-fake-not-a-key\nTHE PROMPT", seen
    b = _attempt(tmp_path, prov)
    b.py = sys.executable
    b.agent_prefix = ["bwrap"]
    b.run_agent([str(tmp_path / "claude")], "THE PROMPT")
    assert seen["stdin"] == "THE PROMPT", seen


def test_the_launcher_is_the_inner_command_not_the_raw_cli(tmp_path):
    launcher = tmp_path / "launch.py"
    launcher.write_text("# launcher\n")
    a = _attempt(tmp_path, {"name": "deepseek", "launcher": str(launcher), "cli_bin": "/x/claude",
                            "key_file": str(tmp_path / "k")})
    a.py = sys.executable
    a.agent_prefix = ["bwrap", "--die-with-parent"]
    cmd = a.agent_cmd(["/x/claude", "--print", "hi"])
    assert cmd[:4] == ["bwrap", "--die-with-parent", sys.executable, "-I"], cmd
    assert cmd[4] == str(launcher) and cmd[5:] == ["--print", "hi"], cmd
    a.provider = {}
    assert a.agent_cmd(["/x/claude", "--print"]) == ["bwrap", "--die-with-parent", "/x/claude", "--print"]


def test_key_line_reader_takes_exactly_one_line_and_leaves_the_rest():
    r, w = os.pipe()
    os.write(w, b"proof-fake-not-a-key\nTHE PROMPT\nsecond line")
    os.close(w)
    try:
        assert L.read_key_line(r) == b"proof-fake-not-a-key"
        assert os.read(r, 100) == b"THE PROMPT\nsecond line"   # the prompt is intact for the CLI
    finally:
        os.close(r)
    r2, w2 = os.pipe()
    os.close(w2)
    try:
        assert L.read_key_line(r2) == b""
    finally:
        os.close(r2)


def test_end_to_end_launcher_seals_the_key_and_the_cli_never_sees_it_in_env(tmp_path):
    """launcher (as bwrap would exec it) -> fake CLI: key readable only through the named descriptor."""
    shim = tmp_path / "claude"
    out = tmp_path / "seen.json"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "fd = int(os.environ.get('CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR','-1'))\n"
        "key = os.read(fd, 200).decode() if fd >= 3 else None\n"
        f"open({str(out)!r},'w').write(json.dumps({{'key': key, 'argv': sys.argv[1:], 'cwd': os.getcwd(),"
        " 'env_has_key': any('proof-fake' in str(v) for v in os.environ.values()),"
        " 'env_has_anthropic': any(str(v).startswith('synthetic-') for v in os.environ.values()),"
        " 'auth_token': os.environ.get('ANTHROPIC_AUTH_TOKEN'), 'api_key': os.environ.get('ANTHROPIC_API_KEY'),"
        " 'stdin_flag': os.environ.get('TRADEAI_DEEPSEEK_KEY_STDIN')}))\n"
    )
    shim.chmod(0o755)
    env = {"TRADEAI_DEEPSEEK_KEY_STDIN": "1", "TRADEAI_CLAUDE_BIN": str(shim), "PATH": "/usr/bin:/bin",
           "HOME": str(tmp_path), "ANTHROPIC_AUTH_TOKEN": "synthetic-token", "ANTHROPIC_API_KEY": "synthetic-key"}
    proc = subprocess.run([sys.executable, str(L.__file__), "--print"], cwd=str(tmp_path), env=env,
                          input="proof-fake-not-a-key\nTHE PROMPT", capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    doc = json.loads(out.read_text())
    assert doc["key"] == "proof-fake-not-a-key", doc
    assert doc["env_has_key"] is False and doc["stdin_flag"] is None, doc
    assert doc["env_has_anthropic"] is False and doc["auth_token"] is None and doc["api_key"] is None, doc
    assert doc["cwd"] == str(tmp_path) and doc["argv"] == ["--print"], doc


# ---------------------------------------------------------------- provider gating (cc4 BLOCK, 2026-11-03)
def _cfg_with_egress(tmp_path, provider, egress):
    from datetime import datetime, timezone
    cfg = {
        "repo": {"repo_root": str(tmp_path / "repo"), "python": sys.executable,
                 "worktree_root": str(tmp_path / "wt"), "branch_prefix": "shf/"},
        "claude": {"bin": str(tmp_path / "claude"), "timeout_s": 5, "provider": provider,
                   "env_names": ["HOME", "PATH"], "auth": {"mode": "credentials_file"}},
        "agent_sandbox": {"enabled": False, "egress_allow": list(egress)},
    }
    return FX.Attempt({"job_id": "shf-test", "lane": "test", "signature": "sig-0123456789"},
                      {"base_sha": "0" * 40}, cfg=cfg, environ={"HOME": str(tmp_path)},
                      now=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc), evidence_dir=tmp_path,
                      may_push=False, backend="claude_cli")


def test_egress_stays_anthropic_only_while_no_provider_is_active(tmp_path):
    base = ["api.anthropic.com:443", "claude.ai:443"]
    a = _cfg_with_egress(tmp_path, {}, base)
    assert a.egress_allow() == base and not any("deepseek" in h for h in a.egress_allow())
    # even a half block (name only) must not add a host
    b = _cfg_with_egress(tmp_path, {"name": "deepseek", "egress_allow": ["api.deepseek.com:443"]}, base)
    assert b.egress_allow() == base
    # active provider: the host comes from the provider block, not the global list
    prov = {"name": "deepseek", "launcher": str(tmp_path / "l.py"), "key_file": str(tmp_path / "k"),
            "egress_allow": ["api.deepseek.com:443"]}
    c = _cfg_with_egress(tmp_path, prov, base)
    assert c.egress_allow() == [*base, "api.deepseek.com:443"]


def test_the_live_config_does_not_carry_the_provider_host(tmp_path):
    live = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())
    assert "api.deepseek.com:443" not in (live["agent_sandbox"].get("egress_allow") or [])


def test_an_active_provider_must_bind_no_oauth_credential(tmp_path):
    launcher = tmp_path / "l.py"; launcher.write_text("# launcher\n")
    good = {"name": "deepseek", "launcher": str(launcher), "key_file": str(tmp_path / "k"), "auth_mode": "none"}
    assert _cfg_with_egress(tmp_path, good, []).provider_setup_problem() is None
    for bad_mode in (None, "", "credentials_file"):
        prov = dict(good)
        if bad_mode is None:
            prov.pop("auth_mode")
        else:
            prov["auth_mode"] = bad_mode
        assert _cfg_with_egress(tmp_path, prov, []).provider_setup_problem() == "provider_auth_mode_invalid", bad_mode
    missing = dict(good); missing["launcher"] = str(tmp_path / "absent.py")
    assert _cfg_with_egress(tmp_path, missing, []).provider_setup_problem() == "provider_launcher_unavailable"


def test_inbound_anthropic_credentials_never_reach_the_child_env(tmp_path):
    """Non-vacuous: the inbound env REALLY carries the names; the allowlist must drop them anyway."""
    from lib import self_heal_fixer as F
    inbound = {"HOME": str(tmp_path), "PATH": "/bin", "ANTHROPIC_AUTH_TOKEN": "synthetic-token",
               "ANTHROPIC_API_KEY": "synthetic-key"}
    cfg = {"claude": {"env_names": ["HOME", "PATH", "TERM"]}, "sandbox": {}, "agent_sandbox": {}}
    for env in (F.child_env(inbound, cfg, scratch_state=str(tmp_path)),
                F.agent_env(inbound, cfg, scratch_state=str(tmp_path), agent_home=str(tmp_path), proxy_port=None)):
        assert "ANTHROPIC_AUTH_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env, env
        assert "synthetic" not in json.dumps(env), env


def test_the_agent_run_uses_the_configured_timeout(tmp_path, monkeypatch):
    """cc4: the timeout had no test. run_agent must pass claude.timeout_s to run(), with the descriptors it holds."""
    seen = {}
    monkeypatch.setattr(FX, "run", lambda cmd, **kw: seen.update(kw) or {"rc": 124, "out": "", "err": "timeout"})
    a = _attempt(tmp_path, {})
    a.cfg["claude"]["timeout_s"] = 7
    a.run_agent([str(tmp_path / "claude")], "prompt")
    assert seen["timeout"] == 7.0, seen
