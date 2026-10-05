"""Secrets: one write path, no silent render failure, drift visible, Finviz cookie tool (2026-10-05).

Temp files and stubs only: no Bitwarden, no real secrets, no network. Every test also asserts that
no fake secret value appears in printed output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

import finviz_cookie as fc  # noqa: E402
import secret_drift_check as sdc  # noqa: E402
import secrets_admin as sa  # noqa: E402

OLD = "a=1; .ASPXAUTH=" + "O" * 80
NEW = "a=1; .ASPXAUTH=" + "N" * 90


def _env(path: Path, **kv):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}='{v}'\n" for k, v in kv.items()))


@pytest.fixture
def layout(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg))
    monkeypatch.delenv("FINVIZ_COOKIE", raising=False)
    repo = tmp_path / "repo"
    monkeypatch.setattr(fc, "ROOT", repo)
    monkeypatch.setattr(sdc, "ROOT", repo)
    return {"render": xdg / "tradeai" / "env", "disk": repo / ".env"}


def test_status_names_the_shadowing_copy(layout, capsys):
    _env(layout["render"], FINVIZ_COOKIE=OLD)
    _env(layout["disk"], FINVIZ_COOKIE=NEW)
    out = fc.copies(root=fc.ROOT, environ={})
    assert out["in_use"] == "render" and out["all_match"] is False
    assert "render is used" in out["drift"] and "disk_env" in out["drift"]
    assert out["render"]["sha8"] != out["disk_env"]["sha8"]
    assert fc.main(["status"]) == 1
    printed = capsys.readouterr().out
    assert OLD not in printed and NEW not in printed and "OOOO" not in printed and "NNNN" not in printed


def test_sync_from_env_is_a_dry_run_without_apply(layout, capsys):
    _env(layout["render"], FINVIZ_COOKIE=OLD)
    _env(layout["disk"], FINVIZ_COOKIE=NEW)
    called = []
    res = fc.write(NEW, apply=False, setter=lambda *a, **k: called.append(1))
    assert res["applied"] is False and called == [] and res["would_write"]["len"] == len(NEW)
    assert fc.main(["sync-from-env"]) == 0
    printed = capsys.readouterr().out
    assert NEW not in printed and json.loads(printed)["applied"] is False


def test_apply_writes_through_set_secret_and_verifies_all_copies(layout):
    _env(layout["render"], FINVIZ_COOKIE=OLD)
    _env(layout["disk"], FINVIZ_COOKIE=NEW)

    def fake_set_secret(key, value, actor=""):
        assert key == "FINVIZ_COOKIE" and value == NEW
        _env(layout["render"], FINVIZ_COOKIE=value)          # what SM upsert + render produce
        return {"ok": True, "action": "edited", "backend": "bitwarden_sm", "render": {"ok": True}}

    res = fc.write(NEW, apply=True, setter=fake_set_secret)
    assert res["applied"] and res["ok"] and res["after"]["all_match"] and res["after"]["in_use"] == "render"


def test_apply_reports_failure_when_render_did_not_change(layout):
    _env(layout["render"], FINVIZ_COOKIE=OLD)
    _env(layout["disk"], FINVIZ_COOKIE=NEW)
    res = fc.write(NEW, apply=True, setter=lambda *a, **k: {"ok": True, "render": {"ok": False}})
    assert res["applied"] and res["ok"] is False


@pytest.mark.parametrize("bad", ["", "short", "x" * 80])
def test_truncated_cookie_is_refused_before_any_write(bad):
    with pytest.raises(ValueError):
        fc.write(bad, apply=True, setter=lambda *a, **k: pytest.fail("must not write"))


def test_drift_check_names_keys_never_values(layout, capsys):
    _env(layout["render"], FINVIZ_COOKIE=OLD, SAME_API_KEY="abcd1234", BWS_ACCESS_TOKEN="x1")
    _env(layout["disk"], FINVIZ_COOKIE=NEW, SAME_API_KEY="abcd1234", BWS_ACCESS_TOKEN="y2")
    res = sdc.check(render_path=layout["render"], disk_path=layout["disk"])
    assert res["status"] == "DRIFT" and [d["key"] for d in res["drift"]] == ["FINVIZ_COOKIE"]
    assert sdc.main([]) == 1
    printed = capsys.readouterr().out
    assert "FINVIZ_COOKIE" in printed and OLD not in printed and NEW not in printed


def test_drift_check_match_and_no_render(layout):
    _env(layout["disk"], FINVIZ_COOKIE=NEW)
    assert sdc.check(render_path=layout["render"], disk_path=layout["disk"])["status"] == "NO_RENDER"
    _env(layout["render"], FINVIZ_COOKIE=NEW)
    assert sdc.check(render_path=layout["render"], disk_path=layout["disk"])["status"] == "MATCH"


def test_render_now_reports_instead_of_swallowing(monkeypatch):
    import subprocess

    class R:
        returncode = 3
        stderr = "render failed"
        stdout = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    res = sa.render_now()
    assert res == {"ok": False, "returncode": 3, "error": "render failed"}

    def boom(*a, **k):
        raise FileNotFoundError("no python")
    monkeypatch.setattr(subprocess, "run", boom)
    assert sa.render_now()["ok"] is False


def test_render_now_does_not_require_a_repo_venv():
    src = (ROOT / "scripts" / "secrets_admin.py").read_text()
    seg = src[src.index("def render_now"):src.index("def set_secret")]
    assert "sys.executable" in seg and "except Exception:\n        pass" not in seg
