"""ANCHOR: LQ1456_AGENT_SCRATCH_CHILDREN_20261109 — idle agent-tmp children are candidates.

LQ-20261107-1456. The 02:17 ET disk-hygiene run reclaimed 0 bytes while / was at 92%.
The growth is ~/.cache/agent-tmp session dirs. A source file whose name matches *token*
or *secret* inside a repo copy with no .git held the whole directory, and a nested-repo
scan that walks node_modules hit the entry cap and held it too. An idle task directory
inside a still-live session is its own candidate. A real .env at large still holds.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import disk_hygiene as DH
from scripts.lib import disk_hygiene_retention as SR

NOW = datetime(2026, 11, 9, 8, 17, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _evidence():
    vals = {
        "cron": "# fixture\n",
        "units": [],
        "processes": [],
        "pointers": [],
        "prs": [],
        "coordination": {"references": [], "live_claims": [], "live_worklogs": []},
    }
    return {
        "schema": SR.SCHEMA,
        "offline": False,
        "sources": {
            k: {"complete": True, "captured_at": NOW.isoformat(), "data": v, "sha256": SR.digest(v)}
            for k, v in vals.items()
        },
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    cfg = json.loads((ROOT / "config/disk_hygiene_rules.json").read_text())
    cfg["standing_apply"]["rules"] = ["T"]
    cfg["standing_apply"]["approval"] = {
        "status": "APPROVED",
        "approved_by": "SYNTHETIC_TEST_ONLY",
        "approved_at": NOW.isoformat(),
    }
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(cfg))
    rules = DH.load_rules(rules_path, home=home)
    monkeypatch.setattr(DH, "du_bytes", lambda p, *_a, **_k: 10)
    return home, rules


def _old(path: Path, hours: float = 48) -> None:
    stamp = (NOW - timedelta(hours=hours)).timestamp()
    os.utime(path, (stamp, stamp))


def test_source_names_inside_a_repo_copy_do_not_hold_the_scratch_dir(world):
    home, rules = world
    root = home / ".cache" / "agent-tmp" / "session" / "oldtask"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    token = root / "src" / "designTokens.ts"
    secret = root / ".github" / "workflows" / "secret-scan.yml"
    secret.parent.mkdir(parents=True)
    token.write_text("export const color = 1\n")
    secret.write_text("name: secret-scan\n")
    env = root / "notes" / ".env"
    env.parent.mkdir()
    env.write_text("X=1\n")
    loose = home / ".cache" / "agent-tmp" / "session" / "loose" / "prepublish-secrets.log"
    loose.parent.mkdir(parents=True)
    loose.write_text("log\n")
    assert DH.scratch_protected(token, root, rules) is False
    assert DH.scratch_protected(secret, root, rules) is False
    assert DH.scratch_protected(env, root, rules) is True
    assert DH.scratch_protected(loose, loose.parent, rules) is True


def test_nested_repo_scan_does_not_walk_node_modules(tmp_path):
    repo = tmp_path / "scratch"
    modules = repo / "node_modules" / "pkg"
    modules.mkdir(parents=True)
    for i in range(20):
        (modules / f"f{i}.js").write_text("x")
    bundles, why = DH.nested_repos(repo, tmp_path, max_entries=5, skip_dirs=["node_modules", ".venv"])
    assert why is None and bundles == []
    _bundles, limited = DH.nested_repos(repo, tmp_path, max_entries=5)
    assert limited == "nested_repo_scan_limit"


def test_idle_child_of_a_live_session_is_a_candidate_and_a_real_env_is_not(world):
    home, rules = world
    session = home / ".cache" / "agent-tmp" / "cc-fixture"
    old = session / "oldtask"
    (old / "src").mkdir(parents=True)
    (old / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    token = old / "src" / "designTokens.ts"
    token.write_text("export const color = 1\n")
    live = session / "live"
    live.mkdir(parents=True)
    (live / "note.txt").write_text("now\n")
    held = session / "held"
    (held / "notes").mkdir(parents=True)
    env = held / "notes" / ".env"
    env.write_text("X=1\n")
    for path in (session, old, old / "pyproject.toml", old / "src", token, held, held / "notes", env):
        _old(path)
    os.utime(live / "note.txt", (NOW.timestamp(), NOW.timestamp()))
    os.utime(live, (NOW.timestamp(), NOW.timestamp()))
    result = DH.standing_plan(rules, NOW, _evidence())
    items = {Path(row["path"]).name for row in result["items"]}
    assert "oldtask" in items
    assert "cc-fixture" not in items
    assert "live" not in items
    held_row = next(row for row in result["excluded"] if row["path"].endswith("/held"))
    assert "activity_contains_protected_entry" in row_reasons(held_row)


def row_reasons(row: dict) -> list[str]:
    return list(row.get("reasons") or [])
