"""Unit tests for the 2026-08-19 cron remediation installer + self-heal.

Covers the pure logic (no crontab/telegram subprocess):
  - install_watchlist_remediation_cron.transform(): additive, idempotent, and
    injects CURATION_AUTO_APPLY=1 on the watch_directives_service line.
  - cron_self_heal._expand(): $PROJ/$PY -> absolute paths (so re-add/re-run is
    independent of the crontab env header).
"""
from __future__ import annotations

from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from install_watchlist_remediation_cron import transform, REMEDIATION_LINES, SELF_HEAL_LINE  # noqa: E402
import cron_self_heal as csh  # noqa: E402
from cron_self_heal import _expand, _script_of  # noqa: E402

BASE = (
    "SHELL=/bin/bash\n"
    "PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild\n"
    "PY=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python\n"
    "*/30 9-16 * * 1-5 cd $PROJ && flock -n /tmp/watch_directives_service.lock "
    "$PY scripts/watch_directives_service.py --apply >> logs/watch_directives_service.log 2>&1\n"
    "0 6 * * * cd $PROJ && $PY scripts/some_other_job.py >> logs/other.log 2>&1\n"
)


def test_transform_adds_all_remediation_jobs():
    new, changes = transform(BASE)
    assert len(REMEDIATION_LINES) == 6
    for line in REMEDIATION_LINES:
        assert line in new
    assert SELF_HEAL_LINE in new


def test_transform_injects_auto_apply():
    new, changes = transform(BASE)
    kinds = [k for k, _ in changes]
    assert "auto-apply" in kinds
    # The watch_directives_service line now carries CURATION_AUTO_APPLY=1 before flock.
    for ln in new.splitlines():
        if "watch_directives_service.py" in ln:
            assert "CURATION_AUTO_APPLY=1 flock -n" in ln


def test_transform_is_idempotent():
    new, _ = transform(BASE)
    new2, changes2 = transform(new)
    # Second pass: only the auto-apply change is already applied; nothing re-added.
    assert not any(k == "add" for k, _ in changes2)


def test_transform_does_not_duplicate_existing_job():
    # Pre-seed one remediation line; transform must not add it twice.
    seeded = BASE.rstrip("\n") + "\n" + REMEDIATION_LINES[0] + "\n"
    new, _ = transform(seeded)
    script = REMEDIATION_LINES[0].split("scripts/")[-1].split(" ")[0]
    assert new.count(script) == 1


def test_expand_resolves_proj_and_py():
    out = _expand("cd $PROJ && $PY scripts/foo.py --apply")
    assert "$PROJ" not in out
    assert "$PY" not in out
    assert "scripts/foo.py" in out
    assert "/.venv/bin/python" in out


def test_script_of_extracts_script_name():
    assert _script_of("0 7 * * 1-5 cd $PROJ && $PY scripts/research_watchlist_discovery.py --apply >> logs/x.log 2>&1") \
        == "research_watchlist_discovery.py"


def _fake_crontab(monkeypatch, current_lines):
    """Return a subprocess.run stand-in for crontab -l / crontab -."""
    calls = []

    def fake_run(args, **kwargs):
        if args == ["crontab", "-l"]:
            class R:
                stdout = "\n".join(current_lines) + "\n"
            return R()
        if args == ["crontab", "-"]:
            calls.append(kwargs["input"])
            class R:
                returncode = 0
                stderr = ""
            return R()
        raise AssertionError(f"unexpected subprocess: {args}")

    monkeypatch.setattr(csh.subprocess, "run", fake_run)
    return calls


def test_re_add_appends_when_absent(monkeypatch):
    calls = _fake_crontab(monkeypatch, ["0 6 * * * cd $PROJ && $PY scripts/other.py"])
    ok = csh._re_add("0 7 * * 1-5 cd $PROJ && $PY scripts/research_watchlist_discovery.py --apply >> logs/x.log 2>&1")
    assert ok is True
    assert len(calls) == 1
    assert "research_watchlist_discovery.py" in calls[0]


def test_re_add_skips_when_present(monkeypatch):
    calls = _fake_crontab(monkeypatch, ["0 7 * * 1-5 cd $PROJ && $PY scripts/research_watchlist_discovery.py --apply"])
    ok = csh._re_add("0 7 * * 1-5 cd $PROJ && $PY scripts/research_watchlist_discovery.py --apply >> logs/x.log 2>&1")
    assert ok is False
    assert calls == []
