"""Importing claude_escalation_handler must not read a release .env (backlog E-B1)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_import_ignores_a_fake_release_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    fake = tmp_path / "release"
    fake.mkdir()
    (fake / ".env").write_text("CLAUDE_ESCALATION_ENV_SENTINEL=leaked\n", encoding="utf-8")
    import lib.live_project_root as lpr

    monkeypatch.setattr(lpr, "get_live_project_root", lambda: fake)
    sys.modules.pop("claude_escalation_handler", None)
    before = dict(os.environ)
    import claude_escalation_handler as handler

    assert os.environ.get("CLAUDE_ESCALATION_ENV_SENTINEL") is None
    assert os.environ == before
    assert handler.PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert handler.PROJECT_ROOT != fake
    handler._ensure_scripts_path()
    assert str(fake / "scripts") not in sys.path
    assert not (fake / ".env").read_text(encoding="utf-8").split("=", 1)[0] in os.environ
