"""Three shipped-but-broken code paths, each an undefined name that passed every existing check.

`ruff` selects F (which includes F821) but the per-change gate runs the security rules only, so a name that
does not exist can still ship and stay green. These are the three that change what the operator sees or what
the system records; each test fails on the parent commit for the reason given in the docstring.

1. `api_v3_watch_commands.post_suggest_decision` read `by` while assigning it, so **every unauthenticated**
   System-Suggests decision raised UnboundLocalError instead of being recorded as "unauthenticated".
2. `paper_trade_logger` imports `os` inside one function only and reads it in another, so the paper→broker
   promotion lineage patch raised NameError (the name was not a module global at all).
3. `pipeline_failures.load` built a lambda over the `except ... as exc` variable, which Python clears at the
   end of the block. It only worked because `project()` calls the callable before that; run afterwards it says
   `NameError: cannot access free variable 'exc'` instead of the real import error — a latent trap in the
   single path the operator reads when the DB is down.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import scripts.api_v3_watch_commands as watch  # noqa: E402
import scripts.lib.pipeline_failures as pipeline_failures  # noqa: E402
import scripts.paper_trade_logger as paper_trade_logger  # noqa: E402


def test_an_unauthenticated_suggest_decision_is_recorded_not_crashed(monkeypatch):
    recorded: list[tuple[str, tuple]] = []

    def db_execute(sql, params):
        recorded.append((sql, params))
        return 1

    monkeypatch.setattr(watch, "_principal", lambda: "")
    out = watch.post_suggest_decision("dismiss", {"symbol": "NVDA"}, db_execute=db_execute)
    assert out.get("ok") is True, out
    payload = json.loads(recorded[0][1][3])
    assert payload["by"] == "unauthenticated"


def test_a_named_principal_is_recorded(monkeypatch):
    recorded: list[tuple[str, tuple]] = []

    def db_execute(sql, params):
        recorded.append((sql, params))
        return 1

    monkeypatch.setattr(watch, "_principal", lambda: "john")
    out = watch.post_suggest_decision("dismiss", {"symbol": "NVDA"}, db_execute=db_execute)
    assert out.get("ok") is True, out
    assert json.loads(recorded[0][1][3])["by"] == "john"


def test_paper_promotion_lineage_can_read_its_env_fallback():
    """The promotion patch reads `os.getenv` at module scope-free call time; `os` must be a module global."""
    assert hasattr(paper_trade_logger, "os")
    assert paper_trade_logger.os.getenv("NO_SUCH_VAR_FOR_THIS_TEST_20261103") is None


def test_a_broken_db_import_is_reported_even_when_the_callable_runs_later(monkeypatch):
    """`project(fn)` may keep the callable. Bound inside the except block, the old closure only worked because
    `project` happened to call it before the block exited; run after that, it said
    `NameError: cannot access free variable 'exc'` instead of the import error."""
    deferred = []

    def fake_project(fn, hours=None):
        deferred.append(fn)          # the caller keeps the callable and runs it after load() returns
        return {"status": "UNAVAILABLE"}

    monkeypatch.setitem(sys.modules, "db_adapter", None)     # `from db_adapter import ...` raises ImportError
    monkeypatch.setattr(pipeline_failures, "project", fake_project)
    out = pipeline_failures.load(24)

    assert out["status"] == "UNAVAILABLE" and deferred
    with pytest.raises(ImportError) as ei:
        deferred[0]("s", "p")
    assert not isinstance(ei.value, NameError), f"a cleared except binding leaked out: {ei.value!r}"
