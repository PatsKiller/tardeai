"""C3 — find alarm deliveries whose failure is swallowed.

An alarm whose failure is swallowed is worse than no alarm: it consumes the budget
of attention that would otherwise notice silence. Two incidents were exactly this
shape -- `except Exception: pass` around an alarm whose import could never resolve.

Three classes, distinguished mechanically:

  pure_swallow  the handler does nothing at all (`pass`, `...`)
  log_only      the handler only writes a log line -- no durable record
  records       the handler calls something else, re-raises, or returns

A log line is not a durable surface. `log_only` is therefore a finding, but a
weaker one than `pure_swallow`, and a handler may declare an explicit reason with
a DECLARED marker instead of recording.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ALARM = re.compile(
    r"^(send_telegram|publish_operator_message|dispatch_alert|send_email|send_alert"
    r"|notify\w*|escalate\w*|_notify|_alert|deliver_text|send_message)$", re.I)

LOG_FNS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "print"}

# A handler may declare why it does not record, instead of recording.
DECLARED = "ALARM-DELIVERY-DECLARED:"


def _alarm_calls(stmts) -> set[str]:
    found = set()
    for st in stmts:
        for n in ast.walk(st):
            if isinstance(n, ast.Call):
                f = n.func
                nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
                if nm and ALARM.match(nm):
                    found.add(nm)
    return found


def _handler_kind(h: ast.ExceptHandler) -> str:
    body = h.body
    if all(isinstance(s, ast.Pass) for s in body):
        return "pure_swallow"
    if len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        return "pure_swallow"
    kinds = set()
    for s in body:
        if isinstance(s, (ast.Raise, ast.Return)):
            kinds.add("other")
        # A bare log statement is "log", and we do NOT descend into its arguments.
        # Descending misclassified log-only handlers as "records" whenever the message
        # was formatted with a helper -- `log.error("...", type(exc).__name__, exc)`
        # counted `type(...)` as real work. That false negative made the log_only
        # count under-report, including for the handler repaired in #787.
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
            f = s.value.func
            nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            if nm in LOG_FNS:
                kinds.add("log")
                continue
        for n in ast.walk(s):
            if isinstance(n, ast.Call):
                f = n.func
                nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
                if nm in LOG_FNS:
                    kinds.add("log")
                elif nm:
                    kinds.add("other")
    if not kinds:
        return "pure_swallow"
    if kinds == {"log"}:
        return "log_only"
    return "records"


def scan(scripts_dir: Path) -> list[tuple[str, int, str, str]]:
    """(relpath, lineno, kind, alarms) for handlers guarding an alarm call."""
    scripts_dir = Path(scripts_dir)
    rows: list[tuple[str, int, str, str]] = []
    for path in sorted(scripts_dir.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except SyntaxError:
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            alarms = _alarm_calls(node.body)
            if not alarms:
                continue
            for h in node.handlers:
                kind = _handler_kind(h)
                if kind == "records":
                    continue
                # a declaration inside the handler exempts it
                seg = "\n".join(lines[h.lineno - 1: (h.end_lineno or h.lineno)])
                if DECLARED in seg:
                    continue
                try:
                    rel = str(path.relative_to(scripts_dir.parent))
                except ValueError:
                    rel = str(path)
                rows.append((rel, h.lineno, kind, ",".join(sorted(alarms))))
    return rows


def counts_by_file(scripts_dir: Path) -> dict[str, int]:
    """File -> number of undeclared swallowing handlers.

    Keyed by FILE, not line number: a baseline keyed on line numbers goes stale on
    the first unrelated edit above it, and a stale baseline is a gate nobody trusts.
    """
    out: dict[str, int] = {}
    for rel, _ln, _kind, _a in scan(scripts_dir):
        out[rel] = out.get(rel, 0) + 1
    return out
