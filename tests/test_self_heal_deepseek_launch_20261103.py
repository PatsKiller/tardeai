"""The repo-owned DeepSeek launcher: key by descriptor, cwd preserved, no key in env (2026-11-03)."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "scripts" / "lib" / "self_heal_deepseek_launch.py"


def test_launcher_moves_the_key_to_a_descriptor_and_keeps_cwd(tmp_path):
    shim = tmp_path / "claude"
    seen = tmp_path / "seen.json"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"fd = int(os.environ.get('CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR','-1'))\n"
        "key = os.read(fd, 200).decode() if fd >= 0 else None\n"
        f"open({str(seen)!r},'w').write(json.dumps({{'cwd': os.getcwd(), 'key': key,"
        " 'base': os.environ.get('ANTHROPIC_BASE_URL'), 'model': os.environ.get('ANTHROPIC_MODEL'),"
        " 'auth_token': os.environ.get('ANTHROPIC_AUTH_TOKEN'), 'api_key': os.environ.get('ANTHROPIC_API_KEY')}))\n"
    )
    shim.chmod(0o755)
    fake = "proof-fake-not-a-key"
    r, w = os.pipe()
    os.write(w, fake.encode())
    os.close(w)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "FAKE": "1", "TRADEAI_DEEPSEEK_KEY_FD": str(r)}
    try:
        subprocess.run([sys.executable, str(LAUNCH), "--version"], cwd=str(tmp_path), env=env, check=True,
                       pass_fds=(r,), timeout=30)
    finally:
        os.close(r)
    doc = json.loads(seen.read_text())
    assert doc["key"] == fake, doc
    assert doc["cwd"] == str(tmp_path), doc
    assert doc["base"] == "https://api.deepseek.com/anthropic" and doc["model"] == "deepseek-flash[1m]", doc
    assert doc["auth_token"] is None and doc["api_key"] is None, doc


def test_launcher_refuses_without_a_descriptor():
    proc = subprocess.run([sys.executable, str(LAUNCH), "--version"], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"}, timeout=30)
    assert proc.returncode == 2 and "descriptor" in proc.stderr
