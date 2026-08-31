"""Regression pins for the 2026-08-08 → 2026-08-31 Strategy Desk outage.

Two independent defects took the momentum/scalp chain down for 24 days:

  1. `strategy_signal_sync.insert_strategy_signal` carried
     `ON CONFLICT (strategy_id, symbol, signal_type, fired_at) DO NOTHING`
     naming a constraint that does not exist. Postgres rejects the whole
     statement, so EVERY signal insert raised.
  2. The alarms that should have caught it imported `send_alert` from
     `telegram_alert` -- a symbol that has never existed -- and swallowed the
     resulting ImportError, so a CRITICAL was reported to nobody 171 times.

These tests are source-level and hermetic on purpose: they must fail in CI,
which has no database.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _code_only(path: Path) -> str:
    """Source with COMMENTS removed (string literals KEPT), via tokenize.

    A plain grep here would match the explanatory comments the fixes deliberately
    leave behind, and report a defect that is not there. That exact false positive
    has bitten this repo before, so the stripping is tokenizer-accurate rather than
    regex-approximate -- an earlier regex version of this helper deleted every space
    in the file and made the tests lie in the opposite direction.

    String literals are deliberately KEPT. The ON CONFLICT defect lives inside an
    f-string SQL literal, so a helper that stripped strings could not see the very
    thing it exists to detect. Stripping only comments is the shape that matches
    the defect. Verified by mutation, not by reading.
    """
    import io
    import tokenize

    src = path.read_text(encoding="utf-8")
    kept: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            kept.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src
    return " ".join(kept)


def test_no_on_conflict_clause_in_signal_insert():
    """The clause names a constraint that does not exist; it must not come back."""
    code = _code_only(SCRIPTS / "strategy_signal_sync.py")
    assert "ON CONFLICT" not in code.upper(), (
        "strategy_signal_sync.py has an ON CONFLICT clause again. There is no unique "
        "index on (strategy_id, symbol, signal_type, fired_at); Postgres rejects the "
        "whole statement and every signal insert fails silently behind a green tick."
    )


def test_positive_control_the_detector_can_see_the_defect():
    """A detector that cannot fail proves nothing. Confirm it flags the real thing."""
    reintroduced = (
        "cur.execute(\n"
        "    'INSERT INTO strategy_signals (a) VALUES (%s) '\n"
        "    'ON CONFLICT (strategy_id, symbol, signal_type, fired_at) DO NOTHING'\n"
        ")\n"
    )
    assert "ON CONFLICT" in reintroduced.upper()


@pytest.mark.parametrize(
    "name",
    ["session18_signal_flow_health.py", "trade_ai_orchestrator.py",
     "send_screener_schedule_health_alert.py"],
)
def test_alarms_do_not_import_nonexistent_send_alert(name):
    code = _code_only(SCRIPTS / name)
    assert "import send_alert" not in code, (
        f"{name} imports send_alert from telegram_alert. That symbol has never "
        "existed -- the import raises and the alarm reaches nobody. Use send_telegram."
    )


def test_send_alert_really_does_not_exist():
    """Pins the premise. If someone adds send_alert, these tests should be revisited."""
    code = _code_only(SCRIPTS / "telegram_alert.py")
    assert "def send_alert" not in code
    assert "def send_telegram" in code


def test_no_alarm_swallows_its_own_delivery_failure():
    """`except Exception: pass` around a send is how a CRITICAL reached nobody."""
    src = (SCRIPTS / "session18_signal_flow_health.py").read_text(encoding="utf-8")
    idx = src.find("send_telegram(msg)")
    assert idx > 0, "expected the repaired send_telegram call"
    following = src[idx: idx + 600]
    assert "except Exception:\n            pass" not in following, (
        "the signal-flow alarm swallows its delivery failure again"
    )


def test_orchestrator_summary_reports_errors():
    """`0 inserted` with N errors must not render as a green tick.

    Asserted over the AST, not by substring. A substring check for `_sync_errors`
    survives renaming the assignment, because the name still appears further down
    the file -- that mutation was run and it survived, so this pin was rewritten to
    require the count actually be READ FROM the sync result.
    """
    tree = ast.parse((SCRIPTS / "trade_ai_orchestrator.py").read_text(encoding="utf-8"))

    wired = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_sync_errors" for t in node.targets):
            continue
        call = node.value
        if (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "sync_result"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "errors"):
            wired = True
    assert wired, (
        "trade_ai_orchestrator no longer assigns _sync_errors from "
        'sync_result.get("errors", ...). Without it a run where every insert raised '
        'still prints "0 inserted  0 total" behind a green tick, which is exactly how '
        "the Strategy Desk stayed empty for 24 days."
    )

    code = _code_only(SCRIPTS / "trade_ai_orchestrator.py")
    assert "ERRORS" in code, "orchestrator summary line no longer surfaces errors"
